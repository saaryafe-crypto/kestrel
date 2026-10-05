"""The two pages, in ONE place. Renaming the English page = edit its
"wordmark" / "handle" / "account" here (owner 2026-10-05: EN rename is coming).
Slot times are LOCAL wall-clock times in the page's own timezone; slot.py
converts them, so DST changes never move a post."""

PAGES = {
    "en": {
        "account": "yaffeai",            # IG username (no @)
        "handle": "@yaffeai",
        "wordmark": "YAFFE<b>AI</b>",    # <b> part takes the accent color
        "tag": "AI &amp; TECH NEWS",
        "tz": "America/New_York",
        "cards": ["08:00", "12:30", "18:00"],
        "reels": ["15:00", "20:30"],
        "posts": "posts",                # post dirs (dedupe history lives here)
    },
    "he": {
        "account": "ainews.israel",
        "handle": "@ainews.israel",
        "wordmark": "AI NEWS <b>ISRAEL</b>",
        "tag": "חדשות בינה מלאכותית",
        "tz": "Asia/Jerusalem",
        "cards": ["08:00", "13:00", "20:30"],
        "reels": ["18:00", "22:00"],     # Israel prime time (TZ-bug fix)
        "posts": "posts-he",
    },
}
