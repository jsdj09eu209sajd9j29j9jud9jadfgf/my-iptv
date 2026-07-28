#!/usr/bin/env python3
"""
Merge multiple M3U playlists into one deduplicated playlist.m3u.

Sources are listed in SOURCES below. Each source is fetched, parsed into
(#EXTINF line, url line) pairs, and combined. Duplicate stream URLs are
dropped (keeps the first occurrence) so overlapping channels across
playlists don't show up twice.
"""

import urllib.request
import sys

SOURCES = [
    "https://iptv-org.github.io/iptv/languages/dan.m3u",   # Danish
    "https://iptv-org.github.io/iptv/languages/eng.m3u",   # English
    "https://iptv-org.github.io/iptv/languages/tur.m3u",   # Turkish
    "https://iptv-org.github.io/iptv/languages/kur.m3u",   # Kurdish
    "https://iptv-org.github.io/iptv/categories/sports.m3u",  # Sports category
]

OUTPUT_FILE = "playlist.m3u"


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def parse_entries(text: str):
    """Yield (extinf_line, url_line) pairs from raw M3U text."""
    lines = [l.rstrip("\n").rstrip("\r") for l in text.splitlines()]
    entries = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("#EXTINF"):
            extinf = line
            # collect any extra tag lines (e.g. #EXTVLCOPT, #EXTGRP) until we hit the URL
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


def main():
    seen_urls = set()
    merged = ["#EXTM3U"]
    total_before = 0
    total_after = 0

    for src in SOURCES:
        print(f"Fetching {src} ...", file=sys.stderr)
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
            merged.append(extinf)
            merged.extend(extra_tags)
            merged.append(url)
            total_after += 1

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(merged) + "\n")

    print(f"Done. {total_before} entries fetched, {total_after} unique entries written to {OUTPUT_FILE}.", file=sys.stderr)


if __name__ == "__main__":
    main()
