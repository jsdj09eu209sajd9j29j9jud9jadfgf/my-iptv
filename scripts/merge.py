#!/usr/bin/env python3
"""
Merge multiple M3U playlists into one deduplicated playlist.m3u, tagging
every channel with a fixed group-title so IPTV players display them as
separate categories (Danish / English / Turkish / Kurdish / Sports)
instead of mixing everything by the original source's own grouping.
"""

import re
import urllib.request
import sys

# (source URL, category label to force on every channel from this source)
SOURCES = [
    ("https://iptv-org.github.io/iptv/languages/dan.m3u", "1. Dansk"),
    ("https://iptv-org.github.io/iptv/languages/eng.m3u", "4. Engelsk"),
    ("https://iptv-org.github.io/iptv/languages/tur.m3u", "2. Tyrkisk"),
    ("https://iptv-org.github.io/iptv/languages/kur.m3u", "3. Kurdisk"),
    ("https://iptv-org.github.io/iptv/categories/sports.m3u", "5. Sports"),
]

OUTPUT_FILE = "playlist.m3u"


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def parse_entries(text: str):
    """Yield (extinf_line, extra_tag_lines, url_line) tuples from raw M3U text."""
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


def set_group_title(extinf_line: str, category: str) -> str:
    """Force the group-title attribute on an #EXTINF line to `category`."""
    if 'group-title="' in extinf_line:
        return re.sub(r'group-title="[^"]*"', f'group-title="{category}"', extinf_line, count=1)
    # No group-title present: insert one right after the duration field.
    match = re.match(r'(#EXTINF:-?\d+)(.*)', extinf_line)
    if match:
        return f'{match.group(1)} group-title="{category}"{match.group(2)}'
    return extinf_line


def main():
    seen_urls = set()
    merged = ["#EXTM3U"]
    total_before = 0
    total_after = 0

    for src, category in SOURCES:
        print(f"Fetching {src} (category: {category}) ...", file=sys.stderr)
        try:
            text = fetch(src)
        except Exception as e:
            print(f"  WARNING: failed to fetch {src}: {e}", file=sys.stderr)
            continue

        entries = parse_entries(text)
        total_before += len(entries)

        for extinf, extra_tags, url in entries:
            if url in seen_urls:
                continue
            seen_urls.add(url)
            merged.append(set_group_title(extinf, category))
            merged.extend(extra_tags)
            merged.append(url)
            total_after += 1

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(merged) + "\n")

    print(f"Done. {total_before} entries fetched, {total_after} unique entries written to {OUTPUT_FILE}.", file=sys.stderr)


if __name__ == "__main__":
    main()
