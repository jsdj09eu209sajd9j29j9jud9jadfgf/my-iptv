#!/usr/bin/env python3
"""
Merge multiple M3U playlists into one deduplicated playlist.m3u.

- Each language source is tagged with a fixed group-title.
- The Sports source is auto-split into subcategories (Football, Basketball,
  Tennis, etc.) based on keyword matches in the channel name.
- Aggregator/FAST-TV channels (Pluto TV, Tubi, Samsung TV Plus, South Park,
  etc.) are detected by name and routed into their own "Other / Aggregators"
  category.
- EXTRA_CHANNELS lets you manually add standalone channels not covered by
  any fetched source (e.g. Show TV). For Show TV, the stream URL is
  refreshed each run by scrape_showtv.js (headless-browser step that runs
  before this script), with a static fallback if that scrape fails.
- Within specific categories, certain channels can be pinned to appear
  first (see PRIORITY_ORDER below), with everything else keeping its
  normal relative order after them.

Deduplication is done PER CATEGORY, so a channel can appear in more than
one category (e.g. a language channel that's also a sports channel).
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

# Static backup used only if the headless-browser scrape (scrape_showtv.js)
# didn't produce a fresh URL this run.
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
# The Danish regional TV2 stations below are not in iptv-org at all --
# they're sourced from a different open list, Free-TV/IPTV
# (github.com/Free-TV/IPTV/blob/master/lists/denmark.md). Their URLs may
# carry session tokens similar to Show TV's, so they could go stale over
# time; not yet confirmed either way.
#
# NOTE: in that source list, "TV 2/Østjylland" and "TV/Midt-Vest" are
# listed with the IDENTICAL stream URL -- almost certainly a copy-paste
# error upstream, not intentional. Included as-is for now; flag it if
# Østjylland just plays Midt-Vest's feed instead of its own.
def get_extra_channels():
    return [
        ("2. Tyrkisk", "Show TV", get_showtv_url(), SHOWTV_LOGO),

        ("1. Dansk", "TV Syd+",
         "https://cdn-lt-live.tvsyd.dk/env/cluster-1-e.live.nvp1/live/hls/p/1956351/e/0_e9slj9wh/tl/main/st/0/t/rFEtaqAbdhUFGef_BNF4WQ/index-s32.m3u8",
         "https://i.imgur.com/k2jf591.png"),
        ("1. Dansk", "TV 2 Fyn",
         "https://cdn-lt-live.tv2fyn.dk/env/cluster-1-e.live.nvp1/live/hls/p/1966291/e/0_vsfrv0zm/tl/main/st/0/t/EgP1FA1D39taZFVewCa42w/index-s32.m3u8",
         "https://i.imgur.com/4L6AIMH.png"),
        ("1. Dansk", "TV 2 Lorry",
         "https://cdn-lt-live.tv2lorry.dk/env/cluster-1-d.live.nvp1/live/hls/p/2045321/e/1_grusx1zd/tl/main/st/0/t/rCct87c-v2SFFCvQK1BBOg/index-s32.m3u8",
         "https://i.imgur.com/oVmCoKY.png"),
        ("1. Dansk", "TV Midtvest",
         "https://cdn-lt-live.tvmidtvest.dk/env/cluster-1-d.live.frp1/live/hls/p/1953371/e/1_9x5lzos9/tl/main/st/0/t/9MTEhotxVwKuatx1EVXdGg/index-s34.m3u8",
         "https://i.imgur.com/OU7xIVa.png"),
        ("1. Dansk", "TV 2 Nord",
         "https://cdn-lt-live.tv2nord.dk/env/cluster-1-e.live.nvp1/live/hls/p/1956931/e/1_h9yfe7h2/tl/main/st/1/t/_FUn1YHQ6_P6lES4U6mmsA/index-s32.m3u8",
         "https://i.imgur.com/tEJ22UW.png"),
        # WARNING: the source list gives this the exact same URL as
        # Midt-Vest above. A trailing "#" fragment is appended purely so
        # this entry doesn't get silently deduped away as an "exact
        # duplicate" -- the underlying stream is still Midt-Vest's until
        # a correct Østjylland-specific URL is found.
        ("1. Dansk", "TV 2 Østjylland",
         "https://cdn-lt-live.tvmidtvest.dk/env/cluster-1-d.live.frp1/live/hls/p/1953371/e/1_9x5lzos9/tl/main/st/0/t/9MTEhotxVwKuatx1EVXdGg/index-s34.m3u8#ostjylland",
         "https://i.imgur.com/qEUXjHp.png"),
        ("1. Dansk", "TV 2 Øst",
         "https://cdn-lt-live.tveast.dk/env/cluster-1-e.live.nvp1/live/hls/p/1953381/e/0_zphj9q61/tl/main/st/0/t/THUB80e-ZMufZCE4pDhO0g/index-s32.m3u8",
         "https://i.imgur.com/H9l6Ulw.png"),

        # Additional channels from the same Free-TV/IPTV Denmark list.
        # Skipped from that list (to avoid duplicates / dead links):
        #  - DR1, DR2, DR Ramasjang: almost certainly already present via
        #    the iptv-org dan.m3u fetch above (different URL, same
        #    channel) -- adding them here risked showing "DR1" twice.
        #  - TV 2 Kosmopol: same exact stream URL as "TV 2 Lorry" above,
        #    just a different display name in the source list.
        #  - TV 2/Bornholm: user already has this one separately.
        #  - KKRtv: source list has no stream link for it at all.
        ("1. Dansk", "Folketinget TV",
         "https://cdnapi.kaltura.com/p/2158211/sp/327418300/playManifest/entryId/1_24gfa7qq/protocol/https/format/applehttp/a.m3u8",
         "https://i.imgur.com/RqQDUzX.png"),
        ("1. Dansk", "TV Storbyen",
         "https://5eeb3940cfaa0.streamlock.net/webtv_live/_definst_/mp4:kanalnordvest/playlist.m3u8",
         "https://i.imgur.com/QqjRqow.png"),
        ("1. Dansk", "Kanal Hovedstaden",
         "http://khkbh.dk:8080/hls/livestream/index.m3u8",
         "https://i.imgur.com/MCXYDwH.png"),
    ]


# category -> ordered list of regex patterns; channels matching earlier
# patterns are pinned higher. Everything not matched keeps its normal
# order, placed after all pinned channels.
PRIORITY_ORDER = {
    "1. Dansk": [
        r"\bdr(\s|\d)",       # DR1, DR2, DR Ramasjang, etc.
        # Main TV2 -- but NOT if it's actually one of the regional TV2
        # stations below (those get their own dedicated rank instead).
        r"\btv\s?2\b(?!\s*(fyn|lorry|midtvest|nord|syd|østjylland|øst))",
        r"\btv2?\s?fyn\b",
        r"\blorry\b",
        r"\bmidt.?vest\b",
        r"\btv2?\s?nord\b",
        r"\btv2?\s?syd\b",
        r"\btv2?\s?østjylland\b",
        r"\btv2?\s?øst\b",
    ],
    "2. Tyrkisk": [
        r"\btrt\s?1\b",
        r"\batv\b(?!\s*(avrupa|alanya))",   # ATV, but not ATV Avrupa / ATV Alanya
        r"\bstar\s?tv\b",
        r"\bshow\s?tv\b",
    ],
    "3. Kurdisk": [
        r"\btrt\s?kurdi\b",
        r"\bzarok\s?tv\b",
    ],
    "4. Engelsk": [
        # Assumed "most known" -- adjust freely if you had different ones in mind.
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


def process_source(src, category_fn, seen_per_category, category_entries, stats):
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

        seen_urls = seen_per_category.setdefault(category, set())
        if url in seen_urls:
            continue
        seen_urls.add(url)

        bucket = category_entries.setdefault(category, [])
        bucket.append((extinf, extra_tags, url, name))
        stats["after"] += 1


def add_extra_channels(seen_per_category, category_entries, stats):
    for category, name, url, logo in get_extra_channels():
        seen_urls = seen_per_category.setdefault(category, set())
        if url in seen_urls:
            continue
        seen_urls.add(url)
        if logo:
            extinf = f'#EXTINF:-1 tvg-logo="{logo}" group-title="{category}",{name}'
        else:
            extinf = f'#EXTINF:-1 group-title="{category}",{name}'
        bucket = category_entries.setdefault(category, [])
        bucket.append((extinf, [], url, name))
        stats["before"] += 1
        stats["after"] += 1


def main():
    seen_per_category = {}
    category_entries = {}
    stats = {"before": 0, "after": 0}

    for src, category in LANGUAGE_SOURCES:
        process_source(src, lambda extinf, cat=category: cat, seen_per_category, category_entries, stats)

    def sports_category(extinf_line):
        name = channel_display_name(extinf_line)
        sport = classify_sport(name)
        return f"{SPORTS_PREFIX} - {sport}"

    process_source(SPORTS_SOURCE, sports_category, seen_per_category, category_entries, stats)

    add_extra_channels(seen_per_category, category_entries, stats)

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
