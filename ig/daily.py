#!/usr/bin/env python3
"""Daily owner report, BOTH channels (@yaffeai + @ainews.israel): every paid
tool's spend against its cap, and yesterday's publishes VERIFIED against the
live Instagram profiles (owner rule Jul 29: webhook "Accepted" is not posted —
scrape reality, and if verification fails SAY SO, never assume). Owner spec
Aug 1: emailed to saaryafe@gmail.com daily at the same time no matter what,
and must cover (a) exactly what was posted, verified live — carousels AND the
reels tab, (b) a cover photo present in every carousel, (c) Replicate budget,
(d) X API token connected and data actually sourced from X. Delivery: Gmail
SMTP (GMAIL_APP_PASSWORD in ~/kestrel/.env) + a GitHub issue as backup/history;
older report issues get closed so only the newest stays open. Weekly deep-dive
stays in report.py — this is the daily truth check.

Runs on the Mac (IG scraping needs the residential IP + the .igprofile
session spy.py already maintains). launchd: ai.yaffe.ig-daily, 08:45 local.

Usage: .venv/bin/python daily.py [--dry]   (--dry: print only, no issue)"""
import json, os, re, subprocess, sys, time
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
GMAIL = "saaryafe@gmail.com"      # the courier: logs in and sends, gets no mail
RECIPIENTS = ["saar@yaffeai.com"]  # the report lands ONLY here (owner Aug 1)


def env_key(name):
    """os.environ first, then ~/kestrel/.env (same file as the other paid
    keys — never printed, never committed)."""
    if os.environ.get(name):
        return os.environ[name]
    try:
        for line in open(os.path.join(os.path.dirname(HERE), ".env")):
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return None


def send_email(subject, text):
    """Owner rule Aug 1: this report lands in the Gmail inbox every day no
    matter what. Needs a Google app password (Google Account -> Security ->
    2-Step Verification -> App passwords) saved as GMAIL_APP_PASSWORD in
    ~/kestrel/.env. Returns False until the key exists — the gh-issue route
    still delivers, and the missing key is named loudly in the report."""
    pw = env_key("GMAIL_APP_PASSWORD")
    if not pw:
        return False
    import smtplib
    from email.mime.text import MIMEText
    msg = MIMEText(text)
    msg["Subject"], msg["From"] = subject, GMAIL
    msg["To"] = ", ".join(RECIPIENTS)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60) as s:
        # Google's copy button pads app pws with regular AND non-breaking
        # spaces (\xa0 — seen in the owner's first paste); strip all whitespace
        s.login(GMAIL, re.sub(r"\s+", "", pw))
        s.send_message(msg)
    return True


def commits_on(day, pattern):
    """Post NAMES the system published on `day` (git subjects are the
    system's own ledger; commit time ≈ publish time). Date filter happens
    here in Python, NOT via git --since/--until: this history mixes CI-UTC
    and local-tz commits out of order, and git's window traversal returned
    only the init commit (found Aug 1 — the report claimed NOTHING went out
    on a 10-post day)."""
    out = subprocess.run(
        ["git", "log", "-500", "--date=format-local:%Y-%m-%d",
         "--pretty=%cd %s"], capture_output=True, text=True, cwd=HERE).stdout
    names = []
    for line in out.splitlines():
        d, _, s = line.partition(" ")
        if d == str(day) and re.match(pattern, s):
            names.append(re.sub(pattern, "", s))
    return names


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


def scrape_channel(handle, cap=12, reel_cap=8):
    """What is ACTUALLY on the profile right now: followers + total posts
    from the profile meta, then date/likes/caption from each of the newest
    post pages, PLUS the /reels/ tab (reels publish share_to_feed=off so the
    grid never shows them — the tab is the only live truth for them, owner
    Aug 1). Raises on failure; the caller reports it, never papers over."""
    from playwright.sync_api import sync_playwright
    posts, reels, counts = [], [], {}
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
        page.goto(f"https://www.instagram.com/{handle}/reels/",
                  wait_until="domcontentloaded")
        page.wait_for_timeout(4000)
        rhrefs = []
        for a in page.query_selector_all('a[href*="/reel/"]'):
            h = a.get_attribute("href")
            if h and h not in rhrefs:
                rhrefs.append(h)
            if len(rhrefs) >= reel_cap:
                break
        for href in rhrefs:
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
            reels.append(e)
        ctx.close()
    return counts, posts, reels


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
    if "--day" in sys.argv:  # test a specific day: daily.py --dry --day 2026-08-01
        y = date.fromisoformat(sys.argv[sys.argv.index("--day") + 1])
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
            counts, live, live_reels = scrape_channel(handle)
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
            # cover-photo check (owner Aug 1, Chrome-bugs post-mortem: every
            # carousel MUST ship a real cover photo; a bare one gets named)
            bare = []
            for name in car:
                pj = os.path.join(HERE, "posts-he" if he else "posts", name,
                                  "post-he.json" if he else "post.json")
                if not os.path.exists(pj):
                    continue
                p = json.load(open(pj))
                cov = (p.get("items") or p.get("slides") or [{}])[0]
                if not cov.get("media"):
                    bare.append(f"- BARE COVER (no photo at all): {name}")
                elif p.get("cover_fallback"):
                    bare.append(f"- COVER FALLBACK "
                                f"({p['cover_fallback']}): {name}")
            if car:
                body += bare or ["Cover photos: every carousel shipped "
                                 "with a real cover image"]
            # reels truth check: the /reels/ tab is scraped live, same
            # caption-match as the grid (a webhook 200 or even an IG media
            # id is NOT proof — the Aug 1 handwriting reel vanished after
            # publish)
            if reels:
                rdescs = " || ".join(norm(e["desc"]) for e in live_reels)
                rmissing = [nm for nm in reels
                            if not own_caption(nm, he)
                            or own_caption(nm, he) not in rdescs]
                body.append(f"Reels tab (scraped just now, newest "
                            f"{len(live_reels)}): "
                            f"{len(reels) - len(rmissing)} of {len(reels)} "
                            "published reels found live by caption")
                for nm in rmissing:
                    body.append(f"- reel NOT FOUND on the reels tab: {nm} "
                                "(possible IG removal — check app -> "
                                "Account Status)")
                missing += rmissing
            liked = [e for e in live if e["likes"] > 0]
            if liked:
                body.append("Top recent: " + " | ".join(
                    f'{e["likes"]:,} likes "{e["caption"][:50]}"'
                    for e in sorted(liked, key=lambda e: -e["likes"])[:3]))
            body.append("VERDICT: OK — every published carousel and reel "
                        "verified live."
                        if not missing else
                        f"VERDICT: MISMATCH — {len(missing)} published "
                        "item(s) NOT live. Check the Make scenario "
                        "history and the open alerts below.")
        except Exception as e:
            body.append(f"LIVE VERIFICATION FAILED ({type(e).__name__}: {e}) "
                        "— live state UNKNOWN, not assumed. Re-run: cd "
                        "~/kestrel/ig && .venv/bin/python daily.py --dry")
        body.append("")

    body.append("## X radar (twitterapi.io) — token + data actually flowing")
    try:
        led = json.load(open(os.path.join(HERE, "x-used.json")))
        age_h = (time.time() - led.get("last_poll", 0)) / 3600
        r = json.load(open(os.path.join(HERE, "radar.json")))
        xm = [m for m in r.get("moments", []) if "on X" in m.get("where", "")]
        xv = [m for m in xm if m.get("video")]
        body.append(f"- API key: "
                    f"{'connected' if env_key('TWITTER_API_KEY') else 'MISSING from ~/kestrel/.env'}"
                    f" | last successful poll {age_h:.0f}h ago"
                    + (" — STALE, radar may be dead" if age_h > 26 else ""))
        body.append(f"- radar.json: {len(xm)} of {len(r.get('moments', []))} "
                    f"moments sourced from X ({len(xv)} with video for "
                    f"reels), updated {r.get('updated', '?')[:16]}")
        body.append("- VERDICT: X data IS feeding carousels + reels"
                    if xm and age_h <= 26 else
                    "- VERDICT: X lane NOT feeding content — check open "
                    "'X radar DEAD' issues")
    except Exception as e:
        body.append(f"- X radar health read FAILED ({e}) — state UNKNOWN, "
                    "not assumed")
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
    try:  # primary delivery (owner Aug 1): straight to the Gmail inbox
        mailed = send_email(title, text)
        note = (f"Emailed to {GMAIL}." if mailed else
                f"EMAIL NOT SENT — no GMAIL_APP_PASSWORD in ~/kestrel/.env. "
                "Create a Google app password (Google Account -> Security -> "
                "2-Step Verification -> App passwords) and add it there to "
                f"get this report at {GMAIL} daily.")
    except Exception as e:
        note = f"EMAIL FAILED ({type(e).__name__}: {e}) — issue is the backup."
    print(note, file=sys.stderr)
    # gh issue rides along as backup + history, and carries the email status
    subprocess.run(["gh", "issue", "create", "--title", title,
                    "--body", note + "\n\n" + text], check=True, cwd=HERE)
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
