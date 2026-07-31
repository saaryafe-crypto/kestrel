#!/usr/bin/env python3
"""Daily owner report, BOTH channels (@yaffeai + @ainews.israel): every paid
tool's spend against its cap, and yesterday's publishes VERIFIED against the
live Instagram profiles (owner rule Jul 29: webhook "Accepted" is not posted —
scrape reality, and if verification fails SAY SO, never assume). Delivered as
a GitHub issue (-> owner email); older report issues get closed so only the
newest stays open. Weekly deep-dive stays in report.py — this is the daily
truth check.

Runs on the Mac (IG scraping needs the residential IP + the .igprofile
session spy.py already maintains). launchd: ai.yaffe.ig-daily, 08:45 local.

Usage: .venv/bin/python daily.py [--dry]   (--dry: print only, no issue)"""
import json, os, re, subprocess, sys
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import spy  # DESC_RE + meta() + n() — same parsing as the competitor scrape

CHANNELS = {"yaffeai": {"carousels": 5, "reels": 4},      # reels 2->4 (owner Jul 31)
            "ainews.israel": {"carousels": 5, "reels": 4}}
COMMIT_PATTERNS = {  # git subjects are the system's own publish ledger
    "yaffeai": {"carousels": r"^IG post: ", "reels": r"^IG reel: "},
    "ainews.israel": {"carousels": r"^IG post HE: ", "reels": r"^IG reel HE: "}}
FOLLOWERS_RE = re.compile(
    r"([\d.,KM]+)\s+Followers,\s*[\d.,KM]+\s+Following,\s*([\d.,KM]+)\s+Posts")


def commits_on(day, pattern):
    """Post NAMES the system published on `day` (git subjects are the
    system's own ledger; commit time ≈ publish time)."""
    out = subprocess.run(
        ["git", "log", "--since", f"{day} 00:00", "--until", f"{day} 23:59",
         "--pretty=%s"], capture_output=True, text=True, cwd=HERE).stdout
    return [re.sub(pattern, "", s) for s in out.splitlines()
            if re.match(pattern, s)]


def norm(t):
    """Caption-match normalization: IG's og:description wraps the caption in
    quotes and reflows whitespace."""
    return re.sub(r"\s+", " ", (t or "").replace('"', "").replace("\u201c", "")
                  .replace("\u201d", "")).strip().lower()


def own_caption(name, he):
    """First ~40 normalized chars of the caption the system published."""
    root = os.path.join(HERE, "posts-he" if he else "posts", name)
    rj = os.path.join(root, "reel.json")
    if os.path.exists(rj):
        return norm(json.load(open(rj)).get("caption", ""))[:40]
    cp = os.path.join(root, "caption.txt")
    return norm(open(cp).read() if os.path.exists(cp) else "")[:40]


def scrape_channel(handle, cap=12):
    """What is ACTUALLY on the profile right now: followers + total posts
    from the profile meta, then date/likes/caption from each of the newest
    post pages. Raises on failure; the caller reports it, never papers over."""
    from playwright.sync_api import sync_playwright
    posts, counts = [], {}
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            spy.PROFILE, headless=True, viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        page.goto(f"https://www.instagram.com/{handle}/",
                  wait_until="domcontentloaded")
        page.wait_for_timeout(4000)
        desc = spy.meta(page, "og:description") or spy.meta(page, "description") or ""
        m = FOLLOWERS_RE.search(desc)
        if m:
            counts = {"followers": spy.n(m.group(1)), "posts": spy.n(m.group(2))}
        hrefs = []
        for a in page.query_selector_all('a[href*="/p/"], a[href*="/reel/"]'):
            h = a.get_attribute("href")
            if h and h not in hrefs:
                hrefs.append(h)
            if len(hrefs) >= cap:
                break
        for href in hrefs:
            page.goto(f"https://www.instagram.com{href}",
                      wait_until="domcontentloaded")
            page.wait_for_timeout(2500)
            d = (spy.meta(page, "og:description")
                 or spy.meta(page, "description") or "")
            e = {"date": "", "likes": -1, "caption": d, "desc": d}
            pm = spy.DESC_RE.search(d)
            if pm:
                e.update(likes=spy.n(pm.group(1)), date=pm.group(3),
                         caption=pm.group(4).strip())
            posts.append(e)
        ctx.close()
    return counts, posts


def budget_lines():
    from genimg import MONTH_BUDGET       # caps live in their modules
    from radar_x import CAP_READS_MONTH   # (single source of truth)
    m = str(date.today())[:7]

    def ledger(name):
        fp = os.path.join(HERE, name)
        return json.load(open(fp)) if os.path.exists(fp) else None

    lines = []
    img = sum(u["cost"] for u in (ledger("genimg-used.json") or [])
              if u["date"][:7] == m)
    lines.append(f"Replicate image-gen (Seedream): ${img:.2f} of "
                 f"${MONTH_BUDGET:.2f}/mo cap")
    led = ledger("x-used.json") or {}
    xr = led.get("reads", 0) if led.get("month") == m else 0
    lines.append(f"twitterapi.io X radar: ${xr * 0.15 / 1000:.2f} of "
                 f"${CAP_READS_MONTH * 0.15 / 1000:.2f}/mo cap ({xr:,} reads)")
    bn = sum(1 for e in (ledger("bundle-used.json") or [])
             if e.get("date", "")[:7] == m)
    lines.append(f"bundle.social free tier: {bn} of 20 posts/mo")
    lines.append("Make.com (both scenarios), Claude subscription, GitHub "
                 "Actions: flat/free tiers, no per-use meter")
    return lines


def open_alerts():
    out = subprocess.run(
        ["gh", "issue", "list", "--state", "open", "--limit", "30",
         "--json", "number,title"], capture_output=True, text=True, cwd=HERE)
    try:
        return [i for i in json.loads(out.stdout)
                if re.search(r"FAILED|health|budget", i["title"], re.I)
                and not i["title"].startswith("IG daily report")]
    except Exception:
        return []


def main():
    dry = "--dry" in sys.argv
    y = date.today() - timedelta(days=1)
    body = []
    for handle, plan in CHANNELS.items():
        he = handle != "yaffeai"
        pats = COMMIT_PATTERNS[handle]
        car = commits_on(y, pats["carousels"])
        reels = commits_on(y, pats["reels"])
        body.append(f"## @{handle}")
        body.append(f"System ledger (git) for {y}: {len(car)} carousels of "
                    f"{plan['carousels']}, {len(reels)} reels of {plan['reels']}"
                    + (" published" if car or reels else " — NOTHING went out"))
        try:
            counts, live = scrape_channel(handle)
            if counts:
                body.append(f"Profile now: {counts['followers']:,} followers, "
                            f"{counts['posts']:,} posts total")
            # truth check: each published carousel's caption must be findable
            # among the newest grid posts (caption match beats date-bucket
            # counting: no timezone wobble, names the exact missing post)
            descs = " || ".join(norm(e["desc"]) for e in live)
            missing = []
            for name in car:
                key = own_caption(name, he)
                if not key or key not in descs:
                    missing.append(name)
            body.append(f"Grid check (scraped just now, newest {len(live)} "
                        f"posts): {len(car) - len(missing)} of {len(car)} "
                        f"carousels found live by caption")
            for name in missing:
                body.append(f"- NOT FOUND on the grid: {name}")
            # cover ladder flag (owner rule: never again a silent plain
            # cover): write.py marks post.json when every image rung failed
            for name in car:
                pj = os.path.join(HERE, "posts", name, "post.json")
                if os.path.exists(pj):
                    flag = json.load(open(pj)).get("cover_fallback")
                    if flag:
                        body.append(f"- COVER FALLBACK ({flag}): {name}")
            if reels:
                body.append(f"Reels ({len(reels)}): published off-grid by "
                            "design (share_to_feed=off) — grid scrape can't "
                            "see them; spot-check the Reels tab or bundle "
                            "analytics")
            liked = [e for e in live if e["likes"] > 0]
            if liked:
                body.append("Top recent: " + " | ".join(
                    f'{e["likes"]:,} likes "{e["caption"][:50]}"'
                    for e in sorted(liked, key=lambda e: -e["likes"])[:3]))
            body.append("VERDICT: OK — every published carousel is live."
                        if not missing else
                        f"VERDICT: MISMATCH — {len(missing)} published "
                        "carousel(s) NOT live. Check the Make scenario "
                        "history and the open alerts below.")
        except Exception as e:
            body.append(f"LIVE VERIFICATION FAILED ({type(e).__name__}: {e}) "
                        "— live state UNKNOWN, not assumed. Re-run: cd "
                        "~/kestrel/ig && .venv/bin/python daily.py --dry")
        body.append("")

    body.append("## Budgets (month to date)")
    try:
        body += [f"- {ln}" for ln in budget_lines()]
    except Exception as e:
        body.append(f"- budget read FAILED: {e}")
    body.append("")
    body.append("## Open failure alerts")
    body += [f"- #{i['number']} {i['title']}" for i in open_alerts()] or ["- none"]

    text = "\n".join(body)
    print(text)
    if dry:
        return
    title = f"IG daily report {date.today()}"
    subprocess.run(["gh", "issue", "create", "--title", title,
                    "--body", text], check=True, cwd=HERE)
    out = subprocess.run(  # keep exactly one report issue open
        ["gh", "issue", "list", "--state", "open", "--search",
         "IG daily report in:title", "--json", "number,title"],
        capture_output=True, text=True, cwd=HERE)
    try:
        for i in json.loads(out.stdout):
            if i["title"].startswith("IG daily report") and i["title"] != title:
                subprocess.run(["gh", "issue", "close", str(i["number"])],
                               cwd=HERE)
    except Exception:
        pass


if __name__ == "__main__":
    main()
