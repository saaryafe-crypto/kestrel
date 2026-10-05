#!/usr/bin/env python3
"""English news pool from X (twitterapi.io), owner-approved redesign 2026-10-05.

Sources = watchlist-x.json: official accounts, outlets/reporters (tech keyword
filter server side), and a discovery net that only discovers. Rank = how fast
a post is moving, times how far above THAT author's own normal it is, so a lab
post at 3x its usual beats an Elon post at 1x.

Cost: ~150-250 reads per harvest (~$0.03). The pool is cached in pool-en.json
for 4h; reels add a 7-day video-only harvest cached ~20h in pool-video.json.
Expected ~28K reads/month, under CAP_READS_MONTH; every read is counted in
x-used.json.

Usage: python3 news_pool.py [--force]   prints the ranked pool"""
import json, os, statistics, sys, time, urllib.parse, urllib.request
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
WATCH = os.path.join(HERE, "watchlist-x.json")
POOL = os.path.join(HERE, "pool-en.json")
LEDGER = os.path.join(HERE, "x-used.json")
CAP_READS_MONTH = 33_000   # ~= $5/mo at $0.15/1K reads (unchanged)
TTL_H = 4
VIDEO_POOL = os.path.join(HERE, "pool-video.json")
VIDEO_TTL_H = 20
WINDOW_H = 48


def key():
    for n in ("TWITTERAPI_KEY", "TWITTER_API_KEY"):
        if os.environ.get(n):
            return os.environ[n]
    for env in (os.path.join(HERE, "..", ".env"), os.path.expanduser("~/kestrel/.env")):
        if os.path.exists(env):
            for line in open(env):
                k, _, v = line.strip().partition("=")
                if k in ("TWITTERAPI_KEY", "TWITTER_API_KEY") and v:
                    return v
    return None


def search(k, query, cursor=""):
    url = ("https://api.twitterapi.io/twitter/tweet/advanced_search?"
           + urllib.parse.urlencode({"query": query, "queryType": "Top", "cursor": cursor}))
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"X-API-Key": k})
            return json.loads(urllib.request.urlopen(req, timeout=30).read())
        except Exception as e:
            print(f"x search retry ({e})", file=sys.stderr)
            time.sleep(8)
    return {}


def ts(s):
    for f in ("%a %b %d %H:%M:%S %z %Y", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(s, f).timestamp()
        except Exception:
            pass
    return None


def video(t):
    """Best mp4 + the ORIGINAL uploader (X marks re-uploaded clips with
    source_user / source_status_id; the reel credits and links the original)."""
    for m in (t.get("extendedEntities") or {}).get("media") or []:
        if m.get("type") != "video":
            continue
        vs = [v for v in (m.get("video_info") or {}).get("variants", []) if v.get("bitrate")]
        if not vs:
            continue
        su = ((m.get("additional_media_info") or {}).get("source_user") or {})
        su = (su.get("user_results") or {}).get("result") or {}
        orig = ((su.get("core") or {}).get("screen_name")
                or (su.get("legacy") or {}).get("screen_name"))
        return {"mp4": max(vs, key=lambda v: v["bitrate"])["url"],
                "ms": (m.get("video_info") or {}).get("duration_millis"),
                "w": (m.get("original_info") or {}).get("width"),
                "h": (m.get("original_info") or {}).get("height"),
                "orig_user": orig or t["author"]["userName"],
                "orig_url": (f"https://x.com/{orig}/status/{m['source_status_id_str']}"
                             if orig and m.get("source_status_id_str") else None)}
    return None


def ledger(add=0):
    try:
        led = json.load(open(LEDGER))
    except Exception:
        led = {}
    month = datetime.now().strftime("%Y-%m")
    if led.get("month") != month:
        led = {"month": month, "reads": 0}
    if add:
        led["reads"] = led.get("reads", 0) + add
        json.dump(led, open(LEDGER, "w"), indent=1)
    return led["reads"]


def harvest(window_h=WINDOW_H, videos=False, out=POOL):
    w, k = json.load(open(WATCH)), key()
    if not k:
        raise SystemExit("no twitterapi.io key (TWITTERAPI_KEY)")
    now = time.time()
    since = int(now - window_h * 3600)
    vf, pages = (" filter:videos", 1) if videos else ("", 2)
    plans = [("official", w["official"][i:i + 8], w["official_min_faves"], vf, pages)
             for i in range(0, len(w["official"]), 8)]
    plans += [("outlets", w["outlets"][i:i + 10], w["outlets_min_faves"],
               " " + w["tech_filter"] + vf, pages) for i in range(0, len(w["outlets"]), 10)]
    if not videos:
        plans += [("discovery", None, w["discovery_min_faves"], w["discovery"], 3)]
    plans += [("discovery", None, w["video_discovery_min_faves"], w["video_discovery"], 2 if videos else 1)]
    if videos:
        plans += [("discovery", None, w["video_discovery_min_faves"], w["ai_video_discovery"], 1)]
    raw, reads = {}, 0
    for lane, handles, floor, extra, pages in plans:
        frm = "(" + " OR ".join(f"from:{h}" for h in handles) + ")" if handles else ""
        q = f"{frm}{extra} min_faves:{floor} since_time:{since} -filter:replies".strip()
        cursor = ""
        for _ in range(pages):
            d = search(k, q, cursor)
            for t in d.get("tweets") or []:
                t["_lane"] = raw.get(str(t["id"]), {}).get("_lane") or lane
                raw[str(t["id"])] = t
            reads += len(d.get("tweets") or [])
            if not d.get("has_next_page"):
                break
            cursor = d.get("next_cursor")
            time.sleep(5)
        time.sleep(5)
    ledger(reads)
    by_author = {}
    for t in raw.values():
        by_author.setdefault(t["author"]["userName"], []).append(int(t.get("likeCount") or 0))
    rows = []
    for t in raw.values():
        text = " ".join((t.get("text") or "").split())
        if text.startswith("RT @") or t.get("isReply"):
            continue
        a = t["author"]["userName"]
        age = max((now - (ts(t["createdAt"]) or now)) / 3600, 1)
        likes = int(t.get("likeCount") or 0)
        eng = likes + 2 * int(t.get("retweetCount") or 0) + int(t.get("quoteCount") or 0)
        rel = likes / max(statistics.median(by_author[a]), 50)
        media = (t.get("extendedEntities") or {}).get("media") or []
        links = [u.get("expanded_url") for u in (t.get("entities") or {}).get("urls", [])
                 if u.get("expanded_url") and "x.com" not in u["expanded_url"]
                 and "twitter.com" not in u["expanded_url"]]
        rows.append({
            "id": str(t["id"]), "author": a, "name": t["author"].get("name"),
            "lane": t["_lane"], "text": text[:600], "likes": likes,
            "views": t.get("viewCount"), "age_h": round(age, 1),
            "vel": round(eng / age), "rel": round(rel, 2),
            "score": round(eng / age * min(rel, 10) ** 0.7),
            "img": next((m.get("media_url_https") for m in media if m.get("type") == "photo"), None)
                   or next((m.get("media_url_https") for m in media), None),
            "video": video(t), "links": links[:2],
            "quoted": " ".join(((t.get("quoted_tweet") or {}).get("text") or "").split())[:300],
            "url": f"https://x.com/{a}/status/{t['id']}"})
    rows.sort(key=lambda r: -r["score"])
    pool = {"updated": now, "reads": reads, "rows": rows}
    json.dump(pool, open(out, "w"), indent=1, ensure_ascii=False)
    print(f"x pool: {len(rows)} posts, {reads} reads", file=sys.stderr)
    return pool


def pool(force=False, videos=False):
    """Cached pool if fresh, else a new harvest (if the monthly cap allows).
    videos=True: the 7-day video-only pool for reels."""
    path, ttl = (VIDEO_POOL, VIDEO_TTL_H) if videos else (POOL, TTL_H)
    try:
        p = json.load(open(path))
    except Exception:
        p = None
    fresh = p and time.time() - p["updated"] < ttl * 3600
    if p and (fresh and not force or ledger() >= CAP_READS_MONTH):
        return p
    return harvest(7 * 24, True, path) if videos else harvest()


if __name__ == "__main__":
    p = pool("--force" in sys.argv)
    for r in p["rows"][:60]:
        print(f"{r['score']:>7} {r['vel']:>6}/h x{r['rel']:<5} {r['lane'][:4]} "
              f"{'V' if r['video'] else ' '} @{r['author']:<15} {r['text'][:100]}")
