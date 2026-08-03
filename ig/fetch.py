#!/usr/bin/env python3
"""Shared HTTP helpers ONLY (get + jpeg_width, imported by write/scout/edu/recap).

Owner order Aug 3: content data comes ONLY from the X channels the owner
personally approved in watchlist-x.json. The news harvest that used to live
here (RSS FEEDS, Google News queries, r/singularity-style Reddit mining,
keyword scoring, og:image scraping, the whole `python3 fetch.py` -> stories.json
lane) is DELETED, not just skipped. Story sourcing now happens exclusively in
radar_x.py; scout.py builds stories.json from radar.json alone."""
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (Macintosh) YaffeAI/1.0"}


def get(url, timeout=15):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()


def jpeg_width(data):
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            return 0
        marker, seglen = data[i + 1], int.from_bytes(data[i + 2:i + 4], "big")
        if marker in (0xC0, 0xC1, 0xC2, 0xC3):  # SOF: height then width
            return int.from_bytes(data[i + 7:i + 9], "big")
        i += 2 + seglen
    return 0
