#!/usr/bin/env python3
"""Viral-clip scout across the platforms where virality actually lives
(owner verdict Jul 28: "the best video platforms are ig, tiktok, youtube" —
Reddit stays for data/copy, video sourcing moves here).

Three scouts, one normalized candidate shape:
  {id, url, title, channel, platform, views, age_h, vph, duration, res}
- instagram: watchlist pages' /reels/ grids scraped with the spy.py session
  (.igprofile) — view counts on the exact platform + audience we post to.
- tiktok:    watchlist accounts via yt-dlp flat extraction (view counts come
  free, no search anti-bot fight).
- youtube:   official-channel watchlist via yt-dlp — pristine source files.

Ranking = TOTAL views (owner rule Aug 1: the most viral clip we never posted
wins — it does not need to be new; the 90-day cap keeps out ancient shelf
clips), after per-platform viral floors. Quality gate: short side >= 720px.
Every scout fails soft: one dead handle or blocked platform never kills the
run. Watchlist lives in watchlist.json — add/remove handles, no code change.
"""
import json, os, re, subprocess, sys, time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
WATCHLIST = os.path.join(HERE, "watchlist.json")
COOKIES = "/tmp/ig-cookies.txt"          # exported from .igprofile per run
MAX_AGE_H = 90 * 24                      # owner Jul 28: reels may be a few
                                         # months old; vph still favors fresh
FLOORS = {"instagram": 200_000, "tiktok": 300_000, "youtube": 100_000}
PROBE_CAP = 18                           # full yt-dlp probes per run (seconds each)

VIEWS_RE = re.compile(r"^([\d.,]+)\s*([KMB]?)$", re.I)
MULT = {"": 1, "K": 1e3, "M": 1e6, "B": 1e9}


def _views(tok):
    m = VIEWS_RE.match(tok.strip())
    if not m:
        return 0
    return int(float(m.group(1).replace(",", "")) * MULT[m.group(2).upper()])


def _yt_json(url, cookies=None):
    cmd = ["yt-dlp", "--no-update", "-J", "--no-download", url]
    if cookies:
        cmd += ["--cookies", cookies]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if r.returncode:
        raise RuntimeError(r.stderr.strip()[-200:])
    return json.loads(r.stdout)


def _yt_flat(url, n=12):
    r = subprocess.run(["yt-dlp", "--no-update", "-J", "--flat-playlist",
                        "--playlist-end", str(n), url],
                       capture_output=True, text=True, timeout=120)
    if r.returncode:
        raise RuntimeError(r.stderr.strip()[-200:])
    return json.loads(r.stdout).get("entries") or []


def _probe(cand, cookies=None):
    """Full metadata for one candidate: timestamp -> vph, duration, res.
    Returns the enriched candidate or None (too old / too soft / low-res)."""
    try:
        d = _yt_json(cand["url"], cookies)
    except Exception as e:
        print(f"  probe failed {cand['url']} ({e})", file=sys.stderr)
        return None
    ts = d.get("timestamp")
    if not ts and d.get("upload_date"):
        ts = datetime.strptime(d["upload_date"], "%Y%m%d")\
                     .replace(tzinfo=timezone.utc).timestamp()
    age_h = max(1.0, (time.time() - ts) / 3600) if ts else None
    views = cand.get("views") or d.get("view_count") or 0
    dur = d.get("duration") or 0
    res = min(d.get("width") or 0, d.get("height") or 0)
    reason = (f"stale ({age_h/24:.0f}d)" if age_h and age_h > MAX_AGE_H else
              f"below floor ({views:,}v)" if views < FLOORS[cand["platform"]] else
              f"bad duration ({dur}s)" if not (8 <= dur <= 300) else
              f"low-res ({res}p)" if res < 720 else None)
    if reason:
        print(f"  reject {cand['platform']} {cand['id']}: {reason}", file=sys.stderr)
        return None
    cand.update(views=int(views), duration=int(dur), res=int(res),
                age_h=age_h, vph=views / age_h if age_h else views / MAX_AGE_H,
                title=cand.get("title") or d.get("title") or
                      (d.get("description") or "")[:120],
                channel=cand.get("channel") or d.get("uploader") or
                        d.get("channel") or "unknown")
    return cand


def export_ig_cookies(ctx):
    """Playwright context cookies -> Netscape file for yt-dlp."""
    with open(COOKIES, "w") as f:
        f.write("# Netscape HTTP Cookie File\n")
        for c in ctx.cookies():
            if "instagram" not in c.get("domain", ""):
                continue
            f.write("\t".join([
                c["domain"], "TRUE" if c["domain"].startswith(".") else "FALSE",
                c.get("path", "/"), "TRUE" if c.get("secure") else "FALSE",
                str(int(c.get("expires") or time.time() + 3600 * 24 * 30)),
                c["name"], c["value"]]) + "\n")
    return COOKIES


def scout_instagram(handles, used):
    """Reels grids of watchlist pages: each tile shows the view count — the
    strongest possible signal (proven on our exact platform + audience)."""
    from playwright.sync_api import sync_playwright
    out = []
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            os.path.join(HERE, ".igprofile"), headless=True)
        export_ig_cookies(ctx)
        page = ctx.new_page()
        for h in handles:
            try:
                page.goto(f"https://www.instagram.com/{h}/reels/",
                          wait_until="domcontentloaded", timeout=45000)
                time.sleep(5)
                tiles = page.eval_on_selector_all(
                    "a[href*='/reel/']",
                    "els => els.map(e => [e.href, e.innerText])")
            except Exception as e:
                print(f"  ig @{h} failed ({e})", file=sys.stderr)
                continue
            for href, text in tiles[:12]:
                code = href.rstrip("/").rsplit("/", 1)[-1]
                views = max((_views(t) for t in text.split("\n") if t.strip()),
                            default=0)
                if code in used or views < FLOORS["instagram"]:
                    continue
                out.append({"id": code, "url": f"https://www.instagram.com/reel/{code}/",
                            "platform": "instagram", "channel": h, "views": views})
            time.sleep(3)  # gentle
        ctx.close()
    # KEEP GRID ORDER (recency): sorting by views puts pinned years-old
    # mega-hits first and they eat the probe budget (seen on first dry-run:
    # 539d/229d rejects). The floor already guarantees viral; _probe ranks.
    return out


def scout_tiktok(handles, used):
    out = []
    for h in handles:
        try:
            entries = _yt_flat(f"https://www.tiktok.com/@{h}", 10)
        except Exception as e:
            print(f"  tiktok @{h} failed ({e})", file=sys.stderr)
            continue
        for e in entries:
            vid = str(e.get("id") or "")
            if not vid or vid in used:
                continue
            out.append({"id": vid, "url": e.get("url") or
                        f"https://www.tiktok.com/@{h}/video/{vid}",
                        "platform": "tiktok", "channel": h,
                        "views": e.get("view_count") or 0,
                        "title": e.get("title") or ""})
    out.sort(key=lambda c: -c["views"])
    return out


def scout_youtube(queries, used):
    """SEARCH, not channel watchlists (owner point Jul 28: official channels
    don't produce enough viral output). yt-dlp searches YouTube with no auth
    and no anti-bot fight — the easiest big-pool scrape there is. Recency and
    virality are enforced later by _probe (MAX_AGE_H + floor + vph rank)."""
    out, seen = [], set()
    for q in queries:
        # results URL with sp=EgIIBA%3D%3D ("upload date: this month" filter —
        # the ytsearchdate: scheme is broken in yt-dlp 2026.07.04, and the
        # CAI%3D upload-date SORT still let years-old shelf videos through).
        # Month filter (owner Aug 1: clips don't need to be new) widens the
        # pool; the merged pool is then sorted by views so probes hit viral.
        try:
            entries = _yt_flat("https://www.youtube.com/results?search_query="
                               + re.sub(r"\s+", "+", q.strip()) + "&sp=EgIIBA%3D%3D", 15)
        except Exception as e:
            print(f"  youtube search '{q}' failed ({e})", file=sys.stderr)
            continue
        for e in entries:
            vid = str(e.get("id") or "")
            dur = e.get("duration") or 0
            if not vid or vid in used or vid in seen or dur > 300:
                continue
            seen.add(vid)
            out.append({"id": vid, "url": f"https://www.youtube.com/watch?v={vid}",
                        "platform": "youtube",
                        "channel": e.get("uploader") or e.get("channel") or "",
                        "views": e.get("view_count") or 0,
                        "title": e.get("title") or ""})
    out.sort(key=lambda c: -c["views"])
    return out


def scout(used):
    """All platforms -> probe the strongest -> rank by views/hour.
    Guarantees platform diversity in what gets probed (top slice per platform
    rather than one platform hogging the probe budget)."""
    wl = json.load(open(WATCHLIST)) if os.path.exists(WATCHLIST) else {}
    pools = []
    for name, fn in (("instagram", scout_instagram), ("tiktok", scout_tiktok),
                     ("youtube", scout_youtube)):
        handles = wl.get(name) or []
        if not handles:
            continue
        try:
            pool = fn(handles, used)
        except Exception as e:
            print(f"  {name} scout failed ({e})", file=sys.stderr)
            pool = []
        print(f"  {name}: {len(pool)} raw candidates", file=sys.stderr)
        pools.append(pool)
    cands, per = [], PROBE_CAP // max(1, len(pools))
    for pool in pools:
        probed = 0
        for c in pool:
            if probed >= per:
                break
            cookies = COOKIES if c["platform"] == "instagram" and \
                os.path.exists(COOKIES) else None
            got = _probe(c, cookies)
            probed += 1
            if got:
                cands.append(got)
    # owner rule Aug 1: rank by TOTAL views, not views/hour — the most viral
    # clip we never posted wins even if it is weeks old (MAX_AGE_H still caps)
    cands.sort(key=lambda c: -c["views"])
    for i, c in enumerate(cands):
        print(f"  cand [{i}] {c['platform']} @{c['channel']} {c['views']:,}v "
              f"{c['age_h']/24:.1f}d {c['res']}p {c['duration']}s "
              f"({c['vph']:,.0f}/h): {c['title'][:50]}", file=sys.stderr)
    return cands


if __name__ == "__main__":
    scout(set())
