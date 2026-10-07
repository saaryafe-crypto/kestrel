"""The two pages, in ONE place. The English page was renamed Yaffe AI
(@yaffeai) -> Flash AI News (@flashainews) on 2026-10-06; "account" is also
the Make account lock (post.py sends it, scenario 6706257 filters on it).
Slot times are LOCAL wall-clock times in the page's own timezone; slot.py
converts them, so DST changes never move a post."""

# lightning mark in front of the EN wordmark (inline SVG, accent color)
BOLT = ('<svg viewBox="0 0 24 24" style="height:.9em;vertical-align:-.08em;margin-right:.18em">'
        '<path fill="#00E676" d="M14.2 1 4 13.6h6.4L8.9 23 20 9.6h-6.6z"/></svg>')

PAGES = {
    "en": {
        "account": "flashainews",        # IG username (no @)
        "handle": "@flashainews",
        "former": ["yaffeai"],           # old usernames (follower history, dedupe)
        "display": "Flash AI News",      # reel tweet-frame name (reel_frame.py)
        "avatar": "avatar-flash.png",    # ig/art/ (made by art/make_avatar.py)
        "wordmark": BOLT + "FLASH <b>AI NEWS</b>",  # <b> part takes the accent color
        "tag": "AI &amp; TECH",
        "tz": "America/New_York",
        "cards": ["08:00", "12:30", "18:00"],
        "reels": ["15:00", "20:30"],
        "posts": "posts",                # post dirs (dedupe history lives here)
    },
    "he": {
        "account": "ainews.israel",
        "handle": "@ainews.israel",
        "display": "AI News Israel",
        "avatar": "avatar-he.jpg",
        "wordmark": "AI NEWS <b>ISRAEL</b>",
        "tag": "חדשות בינה מלאכותית",
        "tz": "Asia/Jerusalem",
        "cards": ["08:00", "13:00", "20:30"],
        "reels": ["18:00", "22:00"],     # Israel prime time (TZ-bug fix)
        "posts": "posts-he",
    },
}
