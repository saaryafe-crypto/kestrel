#!/usr/bin/env python3
"""Market intelligence harvester. Runs daily on the Mac (launchd
ai.yaffe.ig-market) BEFORE the first posting slot: .venv/bin/python market.py

Why on the Mac: all three ground-truth crowds are unreachable from CI
(IG + reddit block datacenter IPs) but fine from a residential IP.
  1. Competitor IG pages (spy.py, anonymous) — the only same-platform signal:
     which tech stories are winning ON INSTAGRAM right now, with like counts
     AND the winning hook wording (proven angles our writer can learn from).
  2. Reddit REAL upvote scores via old.reddit HTML (the .json api died
     May 2026; RSS has rank but no numbers).
  3. Our own page -> scoreboard.json: every post's engagement joined to
     posts/*/post.json — the 24h feedback loop (weak signal until ~30 posts).

Writes ig/market.json + ig/scoreboard.json, commits, pushes. scout.py (CI)
gives crowd-proven stories a score bonus + hands the proven hook to the
writer. Every stage fails open — a scrape outage degrades the signal, it
never blocks the 7/day plan."""
import json, os, re, statistics, subprocess, sys, time, urllib.request
from datetime import date, datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
MARKET = os.path.join(HERE, "market.json")
HISTORY = os.path.join(HERE, "market-history.json")
SCOREBOARD = os.path.join(HERE, "scoreboard.json")
OWN = "yaffeai"
# big consumer-tech pages that post news daily = a free running focus group
COMPETITORS = ["technology", "futurism", "mashable", "techcrunch", "wired"]
# GOLD TIER (Module 1 Tier 4): fast-growing 10K-500K AI/tech pages. Mega
# pages show what works WITH distribution; these show what punches through
# cold — our actual situation. A riser post at 3x+ its own median is the
# single most relevant signal we can get. Handles need owner approval —
# machinery ships first, list fills after.
RISERS = []
SUBS = ["ChatGPT", "singularity", "OpenAI", "artificial", "technology", "Futurology"]
BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def reddit_hot():
    """Real top-of-day scores from old.reddit HTML (residential IP only)."""
    out = []
    for i, sub in enumerate(SUBS):
        if i:
            time.sleep(4)
        try:
            req = urllib.request.Request(
                f"https://old.reddit.com/r/{sub}/top/?t=day&limit=25",
                headers={"User-Agent": BROWSER_UA})
            html = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "ignore")
        except Exception as e:
            print(f"  ! r/{sub}: {e}", file=sys.stderr)
            continue
        for chunk in html.split('data-fullname="t3_')[1:]:
            sc = re.search(r'data-score="(\d+)"', chunk[:2000])
            ti = re.search(r'<a class="title[^>]*>([^<]+)</a>', chunk)
            if sc and ti and int(sc.group(1)) >= 200:
                out.append({"sub": sub, "score": int(sc.group(1)),
                            "title": ti.group(1).strip()})
    out.sort(key=lambda r: -r["score"])
    print(f"reddit: {len(out)} posts with real scores", file=sys.stderr)
    return out[:40]


def scrape_pages(handles):
    """Fresh likes for each handle's newest posts via spy.py (anonymous)."""
    import spy
    from playwright.sync_api import sync_playwright
    idx_path = os.path.join(spy.REF, "index.json")
    index = json.load(open(idx_path)) if os.path.exists(idx_path) else []
    index = [e for e in index if e["handle"] not in handles]  # refresh likes
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            spy.PROFILE, headless=True, viewport={"width": 1280, "height": 900})
        for h in handles:
            try:
                spy.scrape_handle(ctx, h, index)
            except Exception as e:
                print(f"  ! @{h}: {e}", file=sys.stderr)
        ctx.close()
    os.makedirs(spy.REF, exist_ok=True)
    json.dump(index, open(idx_path, "w"), indent=1)
    return index


def competitor_hits(index):
    """Last-48h competitor posts ranked by how far they beat their own page's
    median — relative overperformance compares fairly across page sizes."""
    hits = []
    cutoff = date.today() - timedelta(days=2)
    for h in COMPETITORS + RISERS:
        posts = [e for e in index if e["handle"] == h and e.get("likes", 0) > 0]
        if len(posts) < 3:
            continue
        med = statistics.median(e["likes"] for e in posts)
        for e in posts:
            try:
                posted = datetime.strptime(e["date"], "%B %d, %Y").date()
            except Exception:
                continue
            if posted >= cutoff and med:
                hits.append({"page": h, "likes": e["likes"],
                             "ratio": round(e["likes"] / med, 2),
                             "tier": "riser" if h in RISERS else "mega",
                             "hook": e["caption"][:220], "date": str(posted)})
    hits.sort(key=lambda x: -x["ratio"])
    print(f"competitors: {len(hits)} posts from the last 48h", file=sys.stderr)
    return hits[:25]


def update_history(index):
    """Rolling 14-day ledger of every competitor post ever seen — the memory
    behind scout.py's saturation check (dead-inventory doctrine: a story a
    big page posted 3+ days ago is already burned into the IG audience's
    feed). The grid scrape only shows each page's newest ~12 posts, so
    without this ledger a 5-day-old story looks brand new to Scout."""
    try:
        hist = json.load(open(HISTORY))
    except Exception:
        hist = []
    seen = {(h["page"], h["hook"][:80]) for h in hist}
    added = 0
    for e in index:
        if e["handle"] not in COMPETITORS + RISERS or not e.get("caption"):
            continue
        try:
            posted = datetime.strptime(e["date"], "%B %d, %Y").date()
        except Exception:
            continue
        key = (e["handle"], e["caption"][:80])
        if key in seen:
            continue
        seen.add(key)
        hist.append({"page": e["handle"], "hook": e["caption"][:220],
                     "date": str(posted)})
        added += 1
    cutoff = str(date.today() - timedelta(days=14))
    hist = [h for h in hist if h["date"] >= cutoff]
    json.dump(hist, open(HISTORY, "w"), indent=1)
    print(f"history ledger: +{added} new, {len(hist)} posts in 14-day window",
          file=sys.stderr)


def scoreboard(index):
    """Own-page engagement joined to our generated posts (learn.py's join)."""
    import learn
    posts = learn.local_posts()
    rows = []
    for e in index:
        if e["handle"] != OWN or not e.get("likes"):
            continue
        key = learn.norm(e["caption"])[:40]
        m = next((p for p in posts if key and p["key"] == key), None)
        rows.append({"container": m["container"] if m else "?",
                     "hook": (m["headline"] if m else e["caption"][:80]),
                     "likes": e["likes"], "comments": e["comments"],
                     "date": e.get("date", ""), "scraped": str(date.today())})
    rows.sort(key=lambda r: -r["likes"])
    return rows


def main():
    index = scrape_pages(COMPETITORS + RISERS + [OWN])
    market = {"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "competitor_hits": competitor_hits(index),
              "reddit_hot": reddit_hot()}
    json.dump(market, open(MARKET, "w"), indent=1)
    update_history(index)
    rows = scoreboard(index)
    json.dump(rows, open(SCOREBOARD, "w"), indent=1)
    print(f"market.json: {len(market['competitor_hits'])} IG hits, "
          f"{len(market['reddit_hot'])} reddit; scoreboard: {len(rows)} own posts",
          file=sys.stderr)

    subprocess.run(["git", "add", "market.json", "market-history.json",
                    "scoreboard.json"], cwd=HERE)
    r = subprocess.run(["git", "commit", "-m", "market: daily ground-truth refresh"], cwd=HERE)
    if r.returncode == 0:
        subprocess.run(["git", "pull", "--rebase", "--autostash"], cwd=HERE, check=True, timeout=180)
        subprocess.run(["git", "push"], cwd=HERE, check=True, timeout=180)
        print("pushed — Scout uses this on the next slot", file=sys.stderr)


if __name__ == "__main__":
    main()
