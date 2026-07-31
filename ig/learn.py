#!/usr/bin/env python3
"""Pure-data learning loop. Run weekly: .venv/bin/python learn.py [handle]
1. Re-scrapes OUR OWN page's recent posts (likes/comments) via spy.py — no login.
2. Joins them with the generated posts in posts/*/post.json (caption match).
3. Rewrites the measured-performance block in inspiration/learned.md.
   Numbers only — no assumptions. The writer prompt reads this file, so the
   system automatically writes more of what measurably worked.
4. Commits + pushes learned.md so the cloud writer sees the fresh data."""
import json, os, re, statistics, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
OWN = "yaffeai"
LEARNED = os.path.join(HERE, "inspiration", "learned.md")
MARK = ("<!-- data:begin -->", "<!-- data:end -->")


def norm(s):
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def scrape_own(handle):
    from playwright.sync_api import sync_playwright
    import spy
    idx_path = os.path.join(spy.REF, "index.json")
    index = json.load(open(idx_path)) if os.path.exists(idx_path) else []
    # drop this handle's old entries so like-counts get refreshed, not skipped
    index = [e for e in index if e["handle"] != handle]
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            spy.PROFILE, headless=True, viewport={"width": 1280, "height": 900})
        spy.scrape_handle(ctx, handle, index)
        ctx.close()
    os.makedirs(spy.REF, exist_ok=True)
    json.dump(index, open(idx_path, "w"), indent=1)
    return [e for e in index if e["handle"] == handle]


def local_posts():
    out, root = [], os.path.join(HERE, "posts")
    for d in sorted(os.listdir(root)):
        pj = os.path.join(root, d, "post.json")
        if not os.path.exists(pj):
            continue
        p = json.load(open(pj))
        out.append({"dir": d, "container": p.get("container", "?"),
                    "headline": re.sub(r"</?em>", "", p["slides"][0].get("headline", "")),
                    "judge": (p.get("story") or {}).get("judge_interest"),
                    "key": norm(p.get("caption", ""))[:40]})
    return out


def main(handle=OWN):
    scraped = [e for e in scrape_own(handle) if e.get("likes", 0) > 0]
    if not scraped:
        raise SystemExit("no posts with engagement scraped — page too new, or IG blocked the request")
    posts = local_posts()
    rows = []
    for e in scraped:
        key = norm(e["caption"])[:40]
        m = next((p for p in posts if key and p["key"] == key), None)
        rows.append({"likes": e["likes"], "comments": e["comments"],
                     "container": m["container"] if m else "?",
                     "judge": m["judge"] if m else None,
                     "hook": (m["headline"] if m else e["caption"][:80])})

    med = statistics.median(r["likes"] for r in rows)
    lines = [f"## Measured performance @{handle} — auto-updated {time.strftime('%Y-%m-%d')}, {len(rows)} posts, median {med:.0f} likes",
             "Real engagement numbers, not opinion. Write MORE like the over-performers, LESS like the under-performers.", ""]
    by_cont = {}
    for r in rows:
        by_cont.setdefault(r["container"], []).append(r["likes"])
    for c, ls in sorted(by_cont.items(), key=lambda kv: -statistics.median(kv[1])):
        lines.append(f"- container `{c}`: median {statistics.median(ls):.0f} likes across {len(ls)} posts")
    lines.append("")
    lines.append("OVER-performing hooks:")
    for r in sorted(rows, key=lambda r: -r["likes"])[:5]:
        lines.append(f"- {r['likes']} likes ({r['likes']/med:.1f}x median): {r['hook']}")
    lines.append("")
    lines.append("UNDER-performing hooks:")
    for r in sorted(rows, key=lambda r: r["likes"])[:3]:
        lines.append(f"- {r['likes']} likes ({r['likes']/med:.1f}x median): {r['hook']}")

    # judge calibration: does the scout's interest score predict real likes?
    # (write.py stores story.judge_interest in post.json since Jul 29)
    judged = [r for r in rows if isinstance(r.get("judge"), (int, float))]
    if len(judged) >= 8:  # below this, buckets are noise, not signal
        lines += ["", "Judge calibration (scout interest score vs real likes):"]
        buckets = {}
        for r in judged:
            buckets.setdefault(int(r["judge"]), []).append(r["likes"])
        for score, ls in sorted(buckets.items()):
            if len(ls) < 2:
                continue
            lines.append(f"- judged {score}/10: median {statistics.median(ls):.0f} likes across {len(ls)} posts")
        lines.append("If high-judged stories don't out-perform low-judged ones, the judge prompt needs recalibrating.")

    block = MARK[0] + "\n" + "\n".join(lines) + "\n" + MARK[1]
    text = open(LEARNED).read()
    if MARK[0] in text:
        text = re.sub(re.escape(MARK[0]) + r".*?" + re.escape(MARK[1]), block, text, flags=re.S)
    else:
        text = text.rstrip() + "\n\n" + block + "\n"
    open(LEARNED, "w").write(text)
    print("\n" + block)

    subprocess.run(["git", "add", os.path.relpath(LEARNED, HERE)], cwd=HERE)
    r = subprocess.run(["git", "commit", "-m", f"learn: refresh @{handle} performance data"], cwd=HERE)
    if r.returncode == 0:
        subprocess.run(["git", "pull", "--rebase", "--autostash"], cwd=HERE, check=True)
        subprocess.run(["git", "push"], cwd=HERE, check=True)
        print("pushed — the cloud writer will use this data on the next post")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else OWN)
