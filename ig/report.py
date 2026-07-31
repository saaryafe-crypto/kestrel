#!/usr/bin/env python3
"""Weekly IG performance report. Runs Sundays right after learn.py (same
launchd job), so the spy index is fresh. Scrapes the follower count, joins
engagement with our generated posts (carousel vs reel), tracks week-over-week
deltas in report-history.json, and delivers the report as a GitHub issue —
GitHub emails it to the owner. Meetings section reads meetings.json if it exists
(no booking tool is wired yet)."""
import json, os, re, statistics, subprocess, sys, time

import spy
from learn import norm, local_posts

HERE = os.path.dirname(os.path.abspath(__file__))
OWN = "yaffeai"
HISTORY = os.path.join(HERE, "report-history.json")
REPO = "saaryafe-crypto/kestrel"


def profile_counts(handle):
    """followers/following/posts from the profile page's meta description."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            spy.PROFILE, headless=True, viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        page.goto(f"https://www.instagram.com/{handle}/", wait_until="domcontentloaded")
        page.wait_for_timeout(4000)
        desc = spy.meta(page, "og:description") or spy.meta(page, "description") or ""
        ctx.close()
    m = re.search(r"([\d.,KM]+)\s+Followers,\s*([\d.,KM]+)\s+Following,\s*([\d.,KM]+)\s+Posts", desc)
    return {"followers": spy.n(m.group(1)), "following": spy.n(m.group(2)),
            "posts": spy.n(m.group(3))} if m else {}


def reel_posts():
    out, root = [], os.path.join(HERE, "posts")
    for d in sorted(os.listdir(root)):
        rj = os.path.join(root, d, "reel.json")
        if os.path.exists(rj):
            r = json.load(open(rj))
            out.append({"dir": d, "title": r.get("title", ""),
                        "key": norm(r.get("caption", ""))[:40]})
    return out


def main():
    counts = profile_counts(OWN)
    idx_path = os.path.join(spy.REF, "index.json")
    index = json.load(open(idx_path)) if os.path.exists(idx_path) else []
    scraped = [e for e in index if e["handle"] == OWN]

    cars, reels = local_posts(), reel_posts()
    rows = []
    for e in scraped:
        key = norm(e["caption"])[:40]
        c = next((p for p in cars if key and p["key"] == key), None)
        r = next((p for p in reels if key and p["key"] == key), None)
        rows.append({"likes": e.get("likes", 0), "comments": e.get("comments", 0),
                     "kind": "reel" if r else "carousel",
                     "hook": (r["title"] if r else c["headline"] if c else e["caption"][:70])})
    measured = [r for r in rows if r["likes"] > 0]

    hist = json.load(open(HISTORY)) if os.path.exists(HISTORY) else []
    prev = hist[-1] if hist else {}
    entry = {"date": time.strftime("%Y-%m-%d"), **counts,
             "measured_posts": len(measured),
             "total_likes": sum(r["likes"] for r in measured),
             "total_comments": sum(r["comments"] for r in measured)}
    hist.append(entry)
    json.dump(hist, open(HISTORY, "w"), indent=1)

    def delta(k):
        if k in entry and k in prev:
            d = entry[k] - prev[k]
            return f"{entry[k]:,} ({'+' if d >= 0 else ''}{d:,} this week)"
        return f"{entry[k]:,}" if k in entry else "n/a"

    L = [f"# Weekly IG report — {entry['date']}", "",
         "## Account",
         f"- Followers: {delta('followers')}",
         f"- Posts on page: {delta('posts')}",
         f"- Measured engagement: {delta('total_likes')} likes, {delta('total_comments')} comments "
         f"across {len(measured)} posts", ""]

    for kind in ("carousel", "reel"):
        v = [r["likes"] for r in measured if r["kind"] == kind]
        L.append(f"- {kind}s: {len(v)} measured, median "
                 f"{statistics.median(v):,.0f} likes" if v else f"- {kind}s: no engagement data yet")
    L.append("")

    if measured:
        L.append("## Best performers")
        for r in sorted(measured, key=lambda r: -r["likes"])[:5]:
            L.append(f"- {r['likes']:,} likes / {r['comments']:,} comments [{r['kind']}]: {r['hook']}")
        L.append("")
        L.append("## Worst performers")
        for r in sorted(measured, key=lambda r: r["likes"])[:3]:
            L.append(f"- {r['likes']:,} likes [{r['kind']}]: {r['hook']}")
        L.append("")

    mfile = os.path.join(HERE, "meetings.json")
    L.append("## Meetings booked")
    if os.path.exists(mfile):
        ms = json.load(open(mfile))
        week = [m for m in ms if m.get("date", "") >= time.strftime("%Y-%m-%d", time.localtime(time.time() - 7 * 86400))]
        L.append(f"- {len(week)} this week, {len(ms)} total")
        L += [f"  - {m.get('date')}: {m.get('who', '?')} — {m.get('source', '')}" for m in week]
    else:
        L.append("- No booking tool wired yet (tracking starts when the DM funnel / booking link is live)")

    body = "\n".join(L)
    print(body)
    subprocess.run(["gh", "issue", "create", "-R", REPO,
                    "-t", f"Weekly IG report — {entry['date']}",
                    "-b", body], check=True)

    subprocess.run(["git", "add", os.path.basename(HISTORY)], cwd=HERE)
    r = subprocess.run(["git", "commit", "-m", f"weekly report {entry['date']}"], cwd=HERE)
    if r.returncode == 0:
        subprocess.run(["git", "pull", "--rebase", "--autostash"], cwd=HERE)
        subprocess.run(["git", "push"], cwd=HERE)


if __name__ == "__main__":
    main()
