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

CHANNELS = {"yaffeai": {"carousels": 5, "reels": 2},      # Aug 27: 5 carousels
            "ainews.israel": {"carousels": 5, "reels": 2}}  # (match-the-data)
# + 2 reels/day (owner Aug 27 evening: reels drove the follower growth; the
# followers-history delta above is the experiment that decides 1 vs 3)
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


def send_email(subject, text, html=None):
    """Owner rule Aug 1: this report lands in the inbox every day no matter
    what. Needs a Google app password (Google Account -> Security ->
    2-Step Verification -> App passwords) saved as GMAIL_APP_PASSWORD in
    ~/kestrel/.env. Returns False until the key exists — the gh-issue route
    still delivers, and the missing key is named loudly in the report."""
    pw = env_key("GMAIL_APP_PASSWORD")
    if not pw:
        return False
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    if html:  # colored report + plain-text twin (owner Aug 1: readable, 14yo)
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(text))
        msg.attach(MIMEText(html, "html"))
    else:
        msg = MIMEText(text)
    msg["Subject"], msg["From"] = subject, GMAIL
    msg["To"] = ", ".join(RECIPIENTS)
    # RETRY LADDER (Aug 3 audit: the email NEVER landed — Aug 2 gaierror,
    # Aug 3 connection-reset, both at 08:45 while the Mac's Wi-Fi/DNS was
    # still waking up; both ports tested fine minutes later). 5 attempts
    # over ~8 minutes, alternating SSL:465 / STARTTLS:587, so one flaky
    # wake-up moment can no longer cost the day's report.
    last = None
    for attempt in range(5):
        if attempt:
            time.sleep(120)
        try:
            if attempt % 2 == 0:
                s = smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60)
            else:
                s = smtplib.SMTP("smtp.gmail.com", 587, timeout=60)
                s.starttls()
            with s:
                # Google's copy button pads app pws with regular AND
                # non-breaking spaces (\xa0 — seen in the owner's first
                # paste); strip all whitespace
                s.login(GMAIL, re.sub(r"\s+", "", pw))
                s.send_message(msg)
            return True
        except Exception as e:
            last = e
            print(f"email attempt {attempt + 1}/5 failed "
                  f"({type(e).__name__}: {e}) — retrying", file=sys.stderr)
    raise last


# ---- colored HTML rendering (owner Aug 1: "easy to read and nice ... like i
# am 14 yo and also with colors. dont miss information") — the HTML is built
# FROM the exact same text lines, so nothing can be lost in the pretty view.
BAD_RE = re.compile(r"NOT FOUND|NOT on Instagram|FAILED|MISSING|PROBLEM|"
                    r"BARE COVER|DEAD|STALE|NOTHING went out|NOT SENT|"
                    r"NOT flowing|UNKNOWN|NOT live")
WARN_RE = re.compile(r"FALLBACK|possible|Account Status")
GOOD_RE = re.compile(r"ALL GOOD|really (there|live)|real cover photo|"
                     r"connected|ARE flowing|no problems")
ICONS = {"@yaffeai": "🇺🇸", "@ainews.israel": "🇮🇱", "X (Twitter)": "📡",
         "Money": "💰", "Problems": "🚨"}


def tone(ln):
    if BAD_RE.search(ln):
        return "#d93025"   # red
    if WARN_RE.search(ln):
        return "#e37400"   # orange
    if GOOD_RE.search(ln):
        return "#1e8e3e"   # green
    return "#333333"


def render_html(day, lines):
    ok = not any(tone(ln) == "#d93025" for ln in lines)
    head = ("✅ ALL GOOD — everything checked out" if ok
            else "❌ SOMETHING NEEDS YOUR ATTENTION")
    out = [f'<div style="font-family:Arial,Helvetica,sans-serif;max-width:640px;'
           f'margin:0 auto;background:#f5f5f5;padding:16px">'
           f'<div style="background:{"#1e8e3e" if ok else "#d93025"};color:#fff;'
           f'padding:18px 20px;border-radius:10px 10px 0 0;font-size:20px;'
           f'font-weight:bold">{head}<div style="font-size:13px;font-weight:'
           f'normal;margin-top:4px">Daily report for {day}</div></div>']
    section_open = False
    for ln in lines:
        ln = ln.rstrip()
        if not ln:
            continue
        if ln.startswith("## "):
            if section_open:
                out.append("</div>")
            title = ln[3:]
            icon = next((v for k, v in ICONS.items() if k in title), "📋")
            out.append(f'<div style="background:#fff;margin-top:12px;padding:'
                       f'14px 18px;border-radius:8px">'
                       f'<div style="font-size:16px;font-weight:bold;'
                       f'margin-bottom:8px">{icon} {title}</div>')
            section_open = True
            continue
        c = tone(ln)
        mark = ("❌" if c == "#d93025" else "⚠️" if c == "#e37400"
                else "✅" if c == "#1e8e3e" else "•")
        txt = ln[2:] if ln.startswith("- ") else ln
        weight = ("bold" if c != "#333333" or txt.startswith(("ALL GOOD",
                  "PROBLEM", "VERDICT")) else "normal")
        out.append(f'<div style="color:{c};font-weight:{weight};font-size:14px;'
                   f'line-height:1.6;margin:3px 0">{mark} {txt}</div>')
    if section_open:
        out.append("</div>")
    out.append('<div style="color:#999;font-size:11px;padding:12px 4px">'
               'Sent automatically every morning at 08:45 by the kestrel '
               'system on your Mac. A copy lives in the GitHub issues as '
               'backup.</div></div>')
    return "\n".join(out)


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
    gen = ledger("genimg-used.json") or []
    img = sum(u["cost"] for u in gen if u["date"][:7] == m)
    img_today = sum(u["cost"] for u in gen if u["date"] == str(date.today()))
    # owner ask (Aug 2): the mail must show today's spend, the month's spend,
    # and how much room is left. Replicate's API has no balance endpoint, so
    # "left" = room under OUR monthly cap, not the account balance.
    lines.append(f"AI images we generated (Replicate): ${img_today:.2f} today, "
                 f"${img:.2f} this month, ${max(MONTH_BUDGET - img, 0):.2f} "
                 f"left of the ${MONTH_BUDGET:.2f} monthly limit")
    led = ledger("x-used.json") or {}
    xr = led.get("reads", 0) if led.get("month") == m else 0
    lines.append(f"X (Twitter) data (twitterapi.io): "
                 f"${xr * 0.15 / 1000:.2f} spent, limit is "
                 f"${CAP_READS_MONTH * 0.15 / 1000:.2f} a month")
    bn = sum(1 for e in (ledger("bundle-used.json") or [])
             if e.get("date", "")[:7] == m)
    lines.append(f"bundle.social (reel uploads): {bn} of 20 free posts used")
    lines.append("Everything else (Make.com, Claude, GitHub): fixed price, "
                 "cannot surprise us")
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
        body.append(f"## @{handle} ({'Hebrew' if he else 'English'} account)")
        body.append(f"Posted yesterday: {len(car)} of {plan['carousels']} "
                    f"carousels, {len(reels)} of {plan['reels']} reels"
                    + ("" if car or reels else " — NOTHING went out"))
        try:
            counts, live, live_reels = scrape_channel(handle)
            if counts:
                # followers-per-day ledger (owner Aug 27 evening: reels vs
                # carousels must be settled by FOLLOWER growth, not likes —
                # this line is the experiment's readout, ~2 weeks decides)
                hp = os.path.join(HERE, "followers-history.json")
                try:
                    hist = json.load(open(hp))
                except Exception:
                    hist = {}
                prev = hist.get(handle) or {}
                line = (f"Followers right now: {counts['followers']:,} "
                        f"({counts['posts']:,} posts on the page)")
                if prev.get("followers") is not None:
                    diff = counts["followers"] - prev["followers"]
                    line += (f" — {'+' if diff >= 0 else ''}{diff:,} since "
                             f"{prev.get('date', 'last check')}")
                body.append(line)
                hist[handle] = {"date": str(date.today()),
                                "followers": counts["followers"]}
                json.dump(hist, open(hp, "w"), indent=1)
            # truth check: each published carousel's caption must be findable
            # among the newest grid posts (caption match beats date-bucket
            # counting: no timezone wobble, names the exact missing post)
            descs = " || ".join(norm(e["desc"]) for e in live)
            missing = []
            for name in car:
                key = own_caption(name, he)
                if not key or key not in descs:
                    missing.append(name)
            body.append(f"We just opened the Instagram page and checked: "
                        f"{len(car) - len(missing)} of {len(car)} carousels "
                        "are really there")
            for name in missing:
                body.append(f"- This post is NOT on Instagram: {name}")
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
                if p.get("topic_source") == "self-invented":
                    # owner Aug 10: guide pool ran dry and the writer made
                    # up its own topic — unacceptable, must be named
                    bare.append(f"- SELF-INVENTED TOPIC (guide pool was "
                                f"empty): {name}")
                elif p.get("topic_source") == "ignored-pool":
                    # owner ground rule Aug 12: ride the viral X wave, never
                    # invent — the writer dodged a live guide pool twice
                    bare.append(f"- IGNORED GUIDE POOL (self-invented topic "
                                f"while viral X guides waited): {name}")
                if p.get("qa_override"):
                    # Sep 4 final-floor rung: the edu floor shipped over
                    # unresolved QA failures rather than skip the slot —
                    # the owner must see exactly which post and why
                    bare.append(f"- QA OVERRIDE (EDU_FORCE floor shipped over "
                                f"QA failures — {p['qa_override'][:160]}): "
                                f"{name}")
            if car:
                body += bare or ["Cover photos: every carousel has a real "
                                 "cover photo"]
            # reels truth check: the /reels/ tab is scraped live, same
            # caption-match as the grid (a webhook 200 or even an IG media
            # id is NOT proof — the Aug 1 handwriting reel vanished after
            # publish)
            if reels:
                rdescs = " || ".join(norm(e["desc"]) for e in live_reels)
                rmissing = [nm for nm in reels
                            if not own_caption(nm, he)
                            or own_caption(nm, he) not in rdescs]
                body.append(f"We checked the reels tab too: "
                            f"{len(reels) - len(rmissing)} of {len(reels)} "
                            "reels are really there")
                for nm in rmissing:
                    body.append(f"- This reel is NOT on Instagram: {nm} "
                                "(maybe Instagram removed it — check the "
                                "app -> Account Status)")
                missing += rmissing
            liked = [e for e in live if e["likes"] > 0]
            if liked:
                body.append("Top recent: " + " | ".join(
                    f'{e["likes"]:,} likes "{e["caption"][:50]}"'
                    for e in sorted(liked, key=lambda e: -e["likes"])[:3]))
            body.append("ALL GOOD: everything we posted yesterday is really "
                        "live on Instagram."
                        if not missing else
                        f"PROBLEM: {len(missing)} thing(s) we posted are NOT "
                        "on Instagram. Check the Make history and the "
                        "problems section below.")
        except Exception as e:
            body.append(f"PROBLEM: could not open Instagram to check "
                        f"({type(e).__name__}: {e}) — so what is live today "
                        "is UNKNOWN. Re-run: cd ~/kestrel/ig && "
                        ".venv/bin/python daily.py --dry")
        body.append("")

    body.append("## X (Twitter) data feed — where our stories come from")
    try:
        led = json.load(open(os.path.join(HERE, "x-used.json")))
        age_h = (time.time() - led.get("last_poll", 0)) / 3600
        r = json.load(open(os.path.join(HERE, "radar.json")))
        xm = [m for m in r.get("moments", []) if "on X" in m.get("where", "")]
        xv = [m for m in xm if m.get("video")]
        body.append(f"- X account key: "
                    f"{'connected' if env_key('TWITTER_API_KEY') else 'MISSING from ~/kestrel/.env'}"
                    f" | last check of X: {age_h:.0f} hours ago"
                    + (" — STALE, too long ago, the feed may be dead"
                       if age_h > 26 else ""))
        body.append(f"- {len(xm)} of the {len(r.get('moments', []))} hot "
                    f"stories on our radar came from X ({len(xv)} of them "
                    "have video we can turn into reels)")
        body.append("- ALL GOOD: viral X stories ARE flowing into our posts"
                    if xm and age_h <= 26 else
                    "- PROBLEM: no X stories are flowing in — check the "
                    "'X radar DEAD' alerts")
    except Exception as e:
        body.append(f"- PROBLEM: could not read the X feed status ({e}) — "
                    "state UNKNOWN")
    # editor gate A health (Sep 1 recalibration): 39/40 kills shipped a day
    # of clone listicles; ~100% approves would ship junk. One free line so
    # drift is visible in the owner's inbox without anyone digging.
    try:
        rows = json.load(open(os.path.join(HERE, "editor-log.json")))
        day_ago = time.time() - 86400
        import calendar
        a = [r for r in rows if r.get("gate") == "A" and calendar.timegm(
            time.strptime(r["t"], "%Y-%m-%dT%H:%M:%SZ")) > day_ago]
        if a:
            ap = sum(1 for r in a if r["verdict"] == "APPROVE")
            pct = ap * 100 // len(a)
            note = (" — TOO STRICT, story slots are falling to listicles"
                    if pct <= 5 else
                    " — TOO SOFT, junk stories may be shipping"
                    if pct >= 90 else " — healthy range")
        body.append(f"- Story editor (gate A) last 24h: approved {ap} of "
                    f"{len(a)} candidates ({pct}%){note}" if a else
                    "- Story editor (gate A): no verdicts in the last 24h")
    except Exception as e:
        body.append(f"- Story editor stats unreadable ({e})")
    body.append("")
    body.append("## Money spent this month (each tool vs its limit)")
    try:
        body += [f"- {ln}" for ln in budget_lines()]
    except Exception as e:
        body.append(f"- PROBLEM: could not read the budgets: {e}")
    body.append("")
    body.append("## Problems that need your attention")
    body += ([f"- #{i['number']} {i['title']}" for i in open_alerts()]
             or ["- no problems 🎉"])

    text = "\n".join(body)
    print(text)
    if dry:
        return
    title = f"IG daily report {date.today()}"
    try:  # primary delivery (owner Aug 1): straight to the inbox, in color
        mailed = send_email(title, text, html=render_html(y, body))
        note = (f"Emailed to {', '.join(RECIPIENTS)}." if mailed else
                f"EMAIL NOT SENT — no GMAIL_APP_PASSWORD in ~/kestrel/.env. "
                "Create a Google app password (Google Account -> Security -> "
                "2-Step Verification -> App passwords) and add it there to "
                f"get this report at {', '.join(RECIPIENTS)} daily.")
    except Exception as e:
        note = f"EMAIL FAILED ({type(e).__name__}: {e}) — issue is the backup."
    print(note, file=sys.stderr)
    # gh issue rides along as backup + history, and carries the email status.
    # Retries too (Aug 3 audit: on Aug 2 the SAME wake-up network blip killed
    # this create with check=True and the whole day's report was lost).
    for attempt in range(3):
        if attempt:
            time.sleep(120)
        r = subprocess.run(["gh", "issue", "create", "--title", title,
                            "--body", note + "\n\n" + text], cwd=HERE)
        if r.returncode == 0:
            break
        print(f"gh issue create attempt {attempt + 1}/3 failed — retrying",
              file=sys.stderr)
    else:
        raise RuntimeError("gh issue create failed after 3 attempts")
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
