#!/usr/bin/env python3
"""
Merge multiple M3U playlists into one deduplicated playlist.m3u.

- Each language source is tagged with a fixed group-title.
- grevsen.dk provides a real, fetchable M3U for Danish regional TV2
  stations (Fyn, Lorry, Midtvest, Nord, Syd, Østjylland, Bornholm, Øst)
  plus DR1/DR2/DR Ramasjang with catchup -- far more reliable than
  hardcoded stream URLs, which go stale.
- The Sports source is auto-split into subcategories based on keyword
  matches in the channel name.
- Aggregator/FAST-TV channels (Pluto TV, Tubi, South Park, etc.) are
  routed into their own "Other / Aggregators" category.
- Show TV's URL is refreshed each run via scrape_showtv.js (headless
  browser), since it uses a short-lived signed token.
- Deduplication is done PER CATEGORY, by BOTH exact URL match AND
  normalized channel name -- so if the same channel (e.g. "DR1") shows
  up from two different sources with two different URLs, it still only
  appears once (first source processed wins).
- PRIORITY_ORDER pins specific channels to the top of specific
  categories, in a defined order; everything else keeps its normal
  relative order after them.
"""

import os
import re
import urllib.request
import sys

# Language sources: (url, fixed category label)
LANGUAGE_SOURCES = [
    ("https://iptv-org.github.io/iptv/languages/dan.m3u", "1. Dansk"),
    ("https://iptv-org.github.io/iptv/languages/tur.m3u", "2. Tyrkisk"),
    ("https://iptv-org.github.io/iptv/languages/kur.m3u", "3. Kurdisk"),
    ("https://iptv-org.github.io/iptv/languages/eng.m3u", "4. Engelsk"),
]

# Fetched BEFORE dan.m3u so its versions of DR1/DR2/DR Ramasjang (which
# have catchup/archive) win the name-based dedup over iptv-org's copies.
GREVSEN_SOURCE = "http://grevsen.dk/DRTV/public.m3u"
GREVSEN_CATEGORY = "1. Dansk"

SPORTS_SOURCE = "https://iptv-org.github.io/iptv/categories/sports.m3u"
SPORTS_PREFIX = "5. Sports"

AGGREGATOR_CATEGORY = "6. Other - Aggregators"

AGGREGATOR_KEYWORDS = [
    r"\bpluto\s?tv\b",
    r"\btubi\b",
    r"\bsamsung tv plus\b",
    r"\blg channels\b",
    r"\broku channel\b",
    r"\bxumo\b",
    r"\bstirr\b",
    r"\blocal now\b",
    r"\bfrndly\b",
    r"\bfreevee\b",
    r"\bredbox\b",
    r"\bplex\b",
    r"\bfubo\b",
    r"\bsouth\s?park\b",
]

# Sports subcategory keywords. Order matters: first match wins.
SPORTS_KEYWORDS = [
    ("Soccer",      [r"\bfootball\b", r"\bsoccer\b", r"\bfifa\b", r"\bfc\b", r"\bpremier league\b", r"\bla liga\b", r"\bserie a\b", r"\bbundesliga\b", r"\bligue 1\b", r"\buefa\b", r"\bchampions league\b"]),
    ("Basketball",  [r"\bbasketball\b", r"\bnba\b", r"\beuroleague\b"]),
    ("American Football", [r"\bnfl\b", r"\bamerican football\b"]),
    ("Baseball",    [r"\bbaseball\b", r"\bmlb\b"]),
    ("Hockey",      [r"\bhockey\b", r"\bnhl\b"]),
    ("Tennis",      [r"\btennis\b", r"\batp\b", r"\bwta\b", r"\bwimbledon\b", r"\broland garros\b"]),
    ("Motorsport",  [r"\bf1\b", r"\bformula\s?1\b", r"\bmotogp\b", r"\bnascar\b", r"\bracing\b", r"\brally\b"]),
    ("Combat Sports", [r"\bufc\b", r"\bmma\b", r"\bboxing\b", r"\bwrestling\b", r"\bwwe\b"]),
    ("Golf",        [r"\bgolf\b", r"\bpga\b"]),
    ("Cricket",     [r"\bcricket\b", r"\bipl\b"]),
    ("Rugby",       [r"\brugby\b"]),
    ("Cycling",     [r"\bcycling\b", r"\btour de france\b"]),
    ("Athletics / Olympics", [r"\bathletics\b", r"\bolympic\b"]),
]
SPORTS_FALLBACK = "General"

FALLBACK_SHOWTV_URL = "https://showtv.blutv.com/blutv_showtv_live/live.m3u8"
SHOWTV_SCRAPED_FILE = "showtv_url.txt"
SHOWTV_LOGO = "https://www.showtv.com.tr/assets/v4/images/common/logo/svg/show-tv-logo.svg"


def get_showtv_url() -> str:
    if os.path.exists(SHOWTV_SCRAPED_FILE):
        with open(SHOWTV_SCRAPED_FILE, "r", encoding="utf-8") as f:
            url = f.read().strip()
            if url:
                print(f"Using freshly scraped Show TV URL: {url}", file=sys.stderr)
                return url
    print("No freshly scraped Show TV URL found -- using static fallback (likely stale).", file=sys.stderr)
    return FALLBACK_SHOWTV_URL


# Standalone channels not covered by any fetched source.
# (category, display name, url, logo url or None)
#
# Most Danish regional channels moved to the grevsen.dk fetch above
# (more reliable, has catchup). TV Storbyen has no known alternative
# source yet, so it stays here from the original Free-TV/IPTV list --
# unverified, may not work.
def get_extra_channels():
    return [
        ("2. Tyrkisk", "Show TV", get_showtv_url(), SHOWTV_LOGO),

        ("1. Dansk", "TV Storbyen",
         "https://5eeb3940cfaa0.streamlock.net/webtv_live/_definst_/mp4:kanalnordvest/playlist.m3u8",
         "https://i.imgur.com/QqjRqow.png"),
    ]


# category -> ordered list of regex patterns; channels matching earlier
# patterns are pinned higher. Everything not matched keeps its normal
# order, placed after all pinned channels.
PRIORITY_ORDER = {
    "1. Dansk": [
        r"\bdr(\s|\d)",       # DR1, DR2, DR Ramasjang, etc.
        # Main TV2 -- but NOT any of the regional stations below.
        r"\btv\s?2\b(?!\s*(fyn|lorry|midtvest|nord|syd|østjylland|øst|bornholm))",
        r"\btv\s?2?\s?fyn\b",
        r"\blorry\b",
        r"\bmidt.?vest\b",
        r"\btv\s?2?\s?nord\b",
        r"\btv\s?2?\s?syd\b",
        r"\btv\s?2?\s?østjylland\b",
        r"\btv\s?2?\s?øst\b",
        r"\btv\s?2?\s?bornholm\b",
    ],
    "2. Tyrkisk": [
        r"\btrt\s?1\b",
        r"\batv\b(?!\s*(avrupa|alanya))",   # ATV, but not ATV Avrupa / ATV Alanya
        r"\bstar\s?tv\b",
        r"\bshow\s?tv\b",
        r"\bkanal\s?d\b",
        r"\bnow\s?tv\b",
        # A few more well-known ones added below Kanal D / Now TV.
        r"\bntv\b",
        r"\bhabert[üu]rk\b",
        r"\btrt\s?2\b",
        r"\btv\s?8\b",
        r"\bkanal\s?7\b",
    ],
    "3. Kurdisk": [
        r"\btrt\s?kurd",      # no trailing \b: also matches "Kurdî" (accented i)
        r"\bzarok\s?tv\b",
    ],
    "4. Engelsk": [
        r"\bbbc\s?one\b",
        r"\bbbc\s?two\b",
        r"\bcnn\b",
        r"\bsky\s?news\b",
        r"\bitv\b",
        r"\bchannel\s?4\b",
        r"\bfox\s?news\b",
        r"\bal\s?jazeera\b",
        r"\bfrance\s?24\b",
        r"\bcnbc\b",
    ],
}


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def parse_entries(text: str):
    lines = [l.rstrip("\n").rstrip("\r") for l in text.splitlines()]
    entries = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("#EXTINF"):
            extinf = line
            j = i + 1
            extra_tags = []
            while j < len(lines) and lines[j].strip().startswith("#"):
                extra_tags.append(lines[j].strip())
                j += 1
            if j < len(lines) and lines[j].strip():
                url = lines[j].strip()
                entries.append((extinf, extra_tags, url))
                i = j + 1
                continue
        i += 1
    return entries


def channel_display_name(extinf_line: str) -> str:
    return extinf_line.rsplit(",", 1)[-1].strip()


def normalize_name(name: str) -> str:
    """Collapse naming variations (TV 2/Fyn vs TV2 Fyn vs tv2fyn) so
    name-based dedup catches them as the same channel."""
    return re.sub(r"[^a-zæøå0-9]", "", name.lower())


def is_aggregator_channel(channel_name: str) -> bool:
    name_lower = channel_name.lower()
    return any(re.search(pat, name_lower) for pat in AGGREGATOR_KEYWORDS)


def classify_sport(channel_name: str) -> str:
    name_lower = channel_name.lower()
    for label, patterns in SPORTS_KEYWORDS:
        for pat in patterns:
            if re.search(pat, name_lower):
                return label
    return SPORTS_FALLBACK


def set_group_title(extinf_line: str, category: str) -> str:
    if 'group-title="' in extinf_line:
        return re.sub(r'group-title="[^"]*"', f'group-title="{category}"', extinf_line, count=1)
    match = re.match(r'(#EXTINF:-?\d+)(.*)', extinf_line)
    if match:
        return f'{match.group(1)} group-title="{category}"{match.group(2)}'
    return extinf_line


def priority_rank(category: str, channel_name: str) -> int:
    patterns = PRIORITY_ORDER.get(category)
    if not patterns:
        return 0
    name_lower = channel_name.lower()
    for idx, pat in enumerate(patterns):
        if re.search(pat, name_lower):
            return idx
    return len(patterns)


def already_seen(category, url, name, seen_urls_per_category, seen_names_per_category):
    urls = seen_urls_per_category.setdefault(category, set())
    names = seen_names_per_category.setdefault(category, set())
    norm = normalize_name(name)
    return (url in urls) or (norm in names)


def mark_seen(category, url, name, seen_urls_per_category, seen_names_per_category):
    seen_urls_per_category[category].add(url)
    seen_names_per_category[category].add(normalize_name(name))


def process_source(src, category_fn, seen_urls_per_category, seen_names_per_category, category_entries, stats):
    print(f"Fetching {src} ...", file=sys.stderr)
    try:
        text = fetch(src)
    except Exception as e:
        print(f"  WARNING: failed to fetch {src}: {e}", file=sys.stderr)
        return

    entries = parse_entries(text)
    stats["before"] += len(entries)

    for extinf, extra_tags, url in entries:
        name = channel_display_name(extinf)

        if is_aggregator_channel(name):
            category = AGGREGATOR_CATEGORY
        else:
            category = category_fn(extinf)

        if already_seen(category, url, name, seen_urls_per_category, seen_names_per_category):
            continue
        mark_seen(category, url, name, seen_urls_per_category, seen_names_per_category)

        bucket = category_entries.setdefault(category, [])
        bucket.append((extinf, extra_tags, url, name))
        stats["after"] += 1


def add_extra_channels(seen_urls_per_category, seen_names_per_category, category_entries, stats):
    for category, name, url, logo in get_extra_channels():
        if already_seen(category, url, name, seen_urls_per_category, seen_names_per_category):
            continue
        mark_seen(category, url, name, seen_urls_per_category, seen_names_per_category)

        if logo:
            extinf = f'#EXTINF:-1 tvg-logo="{logo}" group-title="{category}",{name}'
        else:
            extinf = f'#EXTINF:-1 group-title="{category}",{name}'
        bucket = category_entries.setdefault(category, [])
        bucket.append((extinf, [], url, name))
        stats["before"] += 1
        stats["after"] += 1


def main():
    seen_urls_per_category = {}
    seen_names_per_category = {}
    category_entries = {}
    stats = {"before": 0, "after": 0}

    # Grevsen first, so its DR1/DR2/DR Ramasjang + regional TV2 entries
    # win the name-based dedup over iptv-org's dan.m3u copies.
    process_source(
        GREVSEN_SOURCE,
        lambda extinf: GREVSEN_CATEGORY,
        seen_urls_per_category, seen_names_per_category, category_entries, stats,
    )

    for src, category in LANGUAGE_SOURCES:
        process_source(
            src, lambda extinf, cat=category: cat,
            seen_urls_per_category, seen_names_per_category, category_entries, stats,
        )

    def sports_category(extinf_line):
        name = channel_display_name(extinf_line)
        sport = classify_sport(name)
        return f"{SPORTS_PREFIX} - {sport}"

    process_source(
        SPORTS_SOURCE, sports_category,
        seen_urls_per_category, seen_names_per_category, category_entries, stats,
    )

    add_extra_channels(seen_urls_per_category, seen_names_per_category, category_entries, stats)

    merged = ["#EXTM3U"]
    for category, entries in category_entries.items():
        ordered = sorted(entries, key=lambda e: priority_rank(category, e[3]))
        for extinf, extra_tags, url, _name in ordered:
            merged.append(set_group_title(extinf, category))
            merged.extend(extra_tags)
            merged.append(url)

    with open("playlist.m3u", "w", encoding="utf-8") as f:
        f.write("\n".join(merged) + "\n")

    print(f"Done. {stats['before']} entries fetched, {stats['after']} unique entries written to playlist.m3u.", file=sys.stderr)
    print(f"Categories created: {sorted(category_entries.keys())}", file=sys.stderr)


if __name__ == "__main__":
    main()
