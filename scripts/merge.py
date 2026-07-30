#!/usr/bin/env python3
"""
Merge multiple M3U playlists into one deduplicated playlist.m3u.

- Each language source is tagged with a fixed group-title.
- Show TV and the Danish regional TV2 stations (Fyn, Nord, Syd,
  Østjylland, Øst, Midtvest, Lorry) all use JavaScript-generated stream
  URLs with short-lived tokens. scrape_channels.js (a headless-browser
  step that runs before this script) visits each station's official live
  page and captures a fresh URL, writing them to channels.json. If a
  channel isn't in that file (scrape failed this run), it's simply
  skipped rather than served a stale/broken link.
- The Sports source is auto-split into subcategories based on keyword
  matches in the channel name.
- Aggregator/FAST-TV channels (Pluto TV, Tubi, South Park, etc.) are
  routed into their own "Other / Aggregators" category.
- Deduplication is done PER CATEGORY, by BOTH exact URL match AND
  normalized channel name, so the same channel from two different
  sources never shows up twice.
- PRIORITY_ORDER pins specific channels to the top of specific
  categories, in a defined order; everything else keeps its normal
  relative order after them.
"""

import json
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

SCRAPED_CHANNELS_FILE = "channels.json"


def load_scraped_channels() -> dict:
    if os.path.exists(SCRAPED_CHANNELS_FILE):
        try:
            with open(SCRAPED_CHANNELS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                print(f"Loaded {len(data)} freshly scraped channel URLs.", file=sys.stderr)
                return data
        except Exception as e:
            print(f"WARNING: failed to read {SCRAPED_CHANNELS_FILE}: {e}", file=sys.stderr)
    return {}


SCRAPED = load_scraped_channels()

SHOWTV_LOGO = "https://www.showtv.com.tr/assets/v4/images/common/logo/svg/show-tv-logo.svg"

# (category, display name, scrape key, logo url or None)
# If a key isn't in channels.json this run (scrape failed), the channel
# is skipped entirely for this run rather than shown broken.
SCRAPED_EXTRA_CHANNELS = [
    ("2. Tyrkisk", "Show TV",        "showtv",        SHOWTV_LOGO),
    ("1. Dansk",   "TV 2 Fyn",       "tv2fyn",        "https://i.imgur.com/4L6AIMH.png"),
    ("1. Dansk",   "TV 2 Nord",      "tv2nord",       "https://i.imgur.com/tEJ22UW.png"),
    ("1. Dansk",   "TV Syd+",        "tvsyd",         "https://i.imgur.com/k2jf591.png"),
    ("1. Dansk",   "TV 2 Østjylland","tv2ostjylland", "https://i.imgur.com/qEUXjHp.png"),
    ("1. Dansk",   "TV 2 Øst",       "tv2ost",        "https://i.imgur.com/H9l6Ulw.png"),
    ("1. Dansk",   "TV Midtvest",   "tvmidtvest",    "https://i.imgur.com/OU7xIVa.png"),
    ("1. Dansk",   "TV 2 Lorry",     "tv2lorry",      "https://i.imgur.com/oVmCoKY.png"),
]

# Static, non-scraped extras (no known better source yet).
STATIC_EXTRA_CHANNELS = [
    ("1. Dansk", "TV Storbyen",
     "https://5eeb3940cfaa0.streamlock.net/webtv_live/_definst_/mp4:kanalnordvest/playlist.m3u8",
     "https://i.imgur.com/QqjRqow.png"),
]


def get_extra_channels():
    channels = []
    for category, name, key, logo in SCRAPED_EXTRA_CHANNELS:
        url = SCRAPED.get(key)
        if url:
            channels.append((category, name, url, logo))
        else:
            print(f"Skipping '{name}' this run -- no scraped URL available for key '{key}'.", file=sys.stderr)
    channels.extend(STATIC_EXTRA_CHANNELS)
    return channels


# category -> ordered list of regex patterns; channels matching earlier
# patterns are pinned higher. Everything not matched keeps its normal
# order, placed after all pinned channels.
PRIORITY_ORDER = {
    "1. Dansk": [
        r"\bdr(\s|\d)",       # DR1, DR2, DR Ramasjang, etc.
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
        r"\batv\b(?!\s*(avrupa|alanya))",
        r"\bstar\s?tv\b",
        r"\bshow\s?tv\b",
        r"\bkanal\s?d\b",
        r"\bnow\s?tv\b",
        r"\bntv\b",
        r"\bhabert[üu]rk\b",
        r"\btrt\s?2\b",
        r"\btv\s?8\b",
        r"\bkanal\s?7\b",
    ],
    "3. Kurdisk": [
        r"\btrt\s?kurd",
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
    # Normalize slashes to spaces so names like "TV 2/Bornholm" or
    # "TV 2/Fyn" still match patterns written with spaces.
    name_lower = channel_name.lower().replace("/", " ")
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
