#!/usr/bin/env python3
"""Daily owner report for BOTH pages (@flashainews + @ainews.israel), ultra short
(owner 2026-10-06: "even more simple, with colors or a nice visual").

For yesterday, per page: every slot in pages.py (3 news cards + 2 reels) is
green (posted), grey (skipped by the gates: no strong story/video, NOT a
problem) or red (failed / never ran / not on Instagram). Posted = post dir
with published.txt on origin/main; skipped vs failed = how that slot's
GitHub run ended. Posts are re-checked live on Instagram (owner rule Jul 29:
"Accepted" is not posted), followers scraped and kept per day in
followers-history.json (7-day sparkline in the email).

Delivery: one email (plain text + one colorful HTML card with inline PNG
sparklines). A GitHub issue ONLY when something needs the owner.
Runs on the Mac (IG scraping needs the residential IP + spy.py's .igprofile
session). launchd: ai.yaffe.ig-daily, 08:45 New York.

Usage: .venv/bin/python daily.py [--dry] [--day YYYY-MM-DD] [--out DIR]
  --dry: print only (no email, no issue); --out: also write email.html + PNGs"""
import json, os, re, subprocess, sys, time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import spy  # DESC_RE + meta() + n() — same parsing as the competitor scrape

from pages import PAGES  # account names + slot times live there
REPO = "saaryafe-crypto/kestrel"
WORKFLOWS = {("en", "card"): "ig-post.yml", ("he", "card"): "ig-post-he.yml",
             ("en", "reel"): "ig-reel.yml", ("he", "reel"): "ig-reel-he.yml"}
NAMES = {"en": ("🇺🇸", "English"), "he": ("🇮🇱", "Hebrew")}
FOLLOWERS_RE = re.compile(
    r"([\d.,KM]+)\s+Followers,\s*[\d.,KM]+\s+Following,\s*([\d.,KM]+)\s+Posts")
HISTORY = os.path.join(HERE, "followers-history.json")
GMAIL = "saaryafe@gmail.com"      # the courier: logs in and sends, gets no mail
RECIPIENTS = ["saar@yaffeai.com"]  # the report lands ONLY here (owner Aug 1)
GREEN, GREY, RED, AMBER = "#1e8e3e", "#b0b6bd", "#d93025", "#e37400"


def env_key(name):
    """os.environ first, then ~/kestrel/.env (never printed, never committed)."""
    if os.environ.get(name):
        return os.environ[name]
    try:
        for line in open(os.path.join(os.path.dirname(HERE), ".env")):
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return None


def send_email(subject, text, html=None, images=None):
    """Plain text + HTML twin; `images` = {cid: png bytes} shown inline.
    Needs GMAIL_APP_PASSWORD in ~/kestrel/.env; returns False without it."""
    pw = env_key("GMAIL_APP_PASSWORD")
    if not pw:
        return False
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.image import MIMEImage
    from email.mime.multipart import MIMEMultipart
    if html:
        alt = MIMEMultipart("alternative")
        alt.attach(MIMEText(text, "plain", "utf-8"))
        alt.attach(MIMEText(html, "html", "utf-8"))
        msg = MIMEMultipart("related")
        msg.attach(alt)
        for cid, png in (images or {}).items():
            img = MIMEImage(png, "png")
            img.add_header("Content-ID", f"<{cid}>")
            img.add_header("Content-Disposition", "inline", filename=f"{cid}.png")
            msg.attach(img)
    else:
        msg = MIMEText(text, "plain", "utf-8")
    msg["Subject"], msg["From"] = subject, GMAIL
    msg["To"] = ", ".join(RECIPIENTS)
    # RETRY LADDER (Aug 3: the Mac's Wi-Fi/DNS is still waking up at 08:45):
    # 5 attempts over ~8 minutes, alternating SSL:465 / STARTTLS:587
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
                # Google's copy button pads app pws with (non-breaking) spaces
                s.login(GMAIL, re.sub(r"\s+", "", pw))
                s.send_message(msg)
            return True
        except Exception as e:
            last = e
            print(f"email attempt {attempt + 1}/5 failed "
                  f"({type(e).__name__}: {e}) — retrying", file=sys.stderr)
    raise last


# ---- what was published: origin/main is the ledger (posts are built and
# published on GitHub runners, this Mac's checkout may lag behind)

def git(*a):
    return subprocess.run(["git", *a], capture_output=True, text=True,
                          cwd=HERE).stdout


def show(path):
    return git("show", f"origin/main:ig/{path}")


def post_dirs(lang, day):
    """{dir name: post.json dict + "published": bool} for dirs of `day`."""
    root = PAGES[lang]["posts"]
    files = git("ls-tree", "-r", "--name-only", "--full-tree", "origin/main",
                f"ig/{root}/").splitlines()
    out = {}
    for f in files:
        parts = f.split("/")
        if len(parts) != 4 or not parts[2].startswith(str(day)):
            continue
        if parts[3] == "post.json":
            try:
                out.setdefault(parts[2], {}).update(json.loads(show(f"{root}/{parts[2]}/post.json")))
            except ValueError:
                pass
        elif parts[3] == "published.txt":
            out.setdefault(parts[2], {})["published"] = True
    return {k: v for k, v in out.items() if v.get("slot_time") == str(day)}


def norm(t):
    """Caption-match normalization: IG's og:description wraps the caption in
    quotes and reflows whitespace."""
    return re.sub(r"\s+", " ", (t or "").replace('"', "").replace("“", "")
                  .replace("”", "")).strip().lower()


def own_caption(lang, name):
    """First ~40 normalized chars of the caption the system published."""
    root = f"{PAGES[lang]['posts']}/{name}"
    try:
        return norm(json.loads(show(f"{root}/reel.json")).get("caption", ""))[:40]
    except ValueError:
        return norm(show(f"{root}/caption.txt"))[:40]


def runs(wf):
    try:
        return json.loads(subprocess.run(
            ["gh", "run", "list", "-R", REPO, "--workflow", wf, "--limit", "60",
             "--json", "displayTitle,createdAt,status,conclusion"],
            capture_output=True, text=True, timeout=60).stdout)
    except Exception:
        return None


def slot_states(lang, kind, day, posts, now):
    """One entry per planned slot: {"time", "state": posted|skipped|failed|
    later, "why", "name"}."""
    p = PAGES[lang]
    tz = ZoneInfo(p["tz"])
    times = p["cards" if kind == "card" else "reels"]
    crons = re.findall(r'cron: "([^"]+)"', open(os.path.join(
        HERE, "..", ".github", "workflows", WORKFLOWS[(lang, kind)])).read())
    slots = [{"time": t, "state": None, "why": "", "name": None} for t in times]
    mine = {n: d for n, d in posts.items() if d.get("kind") == kind}
    loose = []
    for n, d in sorted(mine.items()):
        i = str(d.get("slot"))
        if i.isdigit() and int(i) < len(slots) and slots[int(i)]["state"] is None:
            s = slots[int(i)]
            s.update(name=n, state="posted" if d.get("published") else "failed",
                     why="" if d.get("published") else "was built but never published")
        elif d.get("published"):
            loose.append(n)  # manual "now" runs fill the earliest open slot
    for n in loose:
        s = next((s for s in slots if s["state"] is None), None)
        if s:
            s.update(name=n, state="posted")
    rl = None
    for i, s in enumerate(slots):
        if s["state"]:
            continue
        hh, mm = map(int, s["time"].split(":"))
        t = datetime(day.year, day.month, day.day, hh, mm, tzinfo=tz)
        if rl is None:
            rl = runs(WORKFLOWS[(lang, kind)])
        if rl is None:
            s.update(state="failed", why="could not reach GitHub to check")
            continue
        cron = crons[i] if i < len(crons) else "-"
        hit = [r for r in rl
               if (r["displayTitle"].endswith(f"| slot {i}") or r["displayTitle"].endswith(f"| {cron}"))
               and t - timedelta(hours=6) <= datetime.fromisoformat(r["createdAt"].replace("Z", "+00:00")) <= t + timedelta(hours=8)]
        if any(r["conclusion"] == "success" for r in hit):
            s["state"] = "skipped"
        elif any(r["status"] != "completed" for r in hit) or (not hit and t > now):
            s["state"] = "later"
        else:
            s.update(state="failed", why="failed" if hit else "never started")
    return slots


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


def record_followers(handle, n, today):
    """-> (change vs the last earlier day or None, last 7 daily values)."""
    try:
        hist = json.load(open(HISTORY))
    except Exception:
        hist = {}
    rows = hist.get(handle) or []
    for old in (p.get("former") or [] for p in PAGES.values() if p["account"] == handle):
        for o in old:  # renamed page keeps its follower line (@yaffeai -> @flashainews)
            if not rows and hist.get(o):
                rows = hist.pop(o)
    if isinstance(rows, dict):  # old format: only the last reading
        rows = [rows]
    rows = [r for r in rows if r.get("date") != today]
    prev = rows[-1]["followers"] if rows else None
    rows = (rows + [{"date": today, "followers": n}])[-60:]
    hist[handle] = rows
    json.dump(hist, open(HISTORY, "w"), indent=1)
    return (None if prev is None else n - prev), [r["followers"] for r in rows[-7:]]


def sparkline(values, color):
    """Tiny 7-day follower line as PNG bytes (2x for phone screens)."""
    from io import BytesIO
    from PIL import Image, ImageDraw
    W, H, P = 240, 64, 8
    im = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(im)
    vals = values or [0]
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1
    pts = [(P + (W - 2 * P) * (i / max(len(vals) - 1, 1)),
            H - P - (H - 2 * P) * ((v - lo) / span if hi > lo else 0.5))
           for i, v in enumerate(vals)]
    if len(pts) == 1:
        pts = [(P, pts[0][1])] + pts
        pts[1] = (W - P, pts[0][1])
    d.line(pts, fill=color, width=4, joint="curve")
    x, y = pts[-1]
    d.ellipse([x - 6, y - 6, x + 6, y + 6], fill=color)
    out = BytesIO()
    im.save(out, "PNG")
    return out.getvalue()


def count_part(slots, noun):
    posted = sum(s["state"] == "posted" for s in slots)
    skipped = sum(s["state"] == "skipped" for s in slots)
    failed = sum(s["state"] == "failed" for s in slots)
    later = sum(s["state"] == "later" for s in slots)
    icon = "❌" if failed else "⏭" if skipped and not posted else "✅"
    txt = f"{icon} {posted} of {len(slots)} {noun}"
    if skipped:
        txt += f" ({skipped} skipped, no strong {'story' if noun == 'posts' else 'video'})"
    if later:
        txt += f" ({later} still to come)"
    return txt


def render_html(day, rows, followers, problems, color, headline):
    dot = {"posted": GREEN, "skipped": GREY, "failed": RED, "later": "#e8eaed"}
    out = [f'<div style="font-family:Arial,Helvetica,sans-serif;max-width:480px;margin:0 auto;'
           f'background:#ffffff;border-radius:16px;overflow:hidden;border:1px solid #eee">'
           f'<div style="background:{color};color:#fff;padding:22px 20px;font-size:26px;'
           f'font-weight:bold;line-height:1.25">{headline}'
           f'<div style="font-size:14px;font-weight:normal;opacity:.9;margin-top:4px">'
           f'{day:%A %b %-d}</div></div>']
    for lang, slots in rows.items():
        flag, name = NAMES[lang]
        n, delta = followers[lang]
        dots = "".join(
            f'<span style="display:inline-block;width:22px;height:22px;border-radius:11px;'
            f'background:{dot[s["state"]]};margin-right:6px"></span>' for s in slots["card"])
        dots += '<span style="display:inline-block;width:10px"></span>' + "".join(
            f'<span style="display:inline-block;width:22px;height:22px;border-radius:5px;'
            f'background:{dot[s["state"]]};margin-right:6px"></span>' for s in slots["reel"])
        dtxt = "" if delta is None else f'{"+" if delta >= 0 else ""}{delta}'
        dcol = GREEN if (delta or 0) > 0 else RED if (delta or 0) < 0 else "#666"
        out.append(
            f'<div style="padding:18px 20px;border-bottom:1px solid #f0f0f0">'
            f'<div style="font-size:20px;font-weight:bold;margin-bottom:10px">{flag} {name}</div>'
            f'<div>{dots}</div>'
            f'<table cellpadding="0" cellspacing="0" style="margin-top:12px"><tr>'
            f'<td style="font-size:30px;font-weight:bold;padding-right:10px">{n}</td>'
            f'<td style="font-size:18px;font-weight:bold;color:{dcol};padding-right:14px">{dtxt}</td>'
            f'<td><img src="cid:spark-{lang}" width="120" height="32" alt="" style="display:block"></td>'
            f'</tr></table><div style="font-size:12px;color:#888">followers</div></div>')
    need = "<br>".join(problems) if problems else "nothing"
    out.append(f'<div style="padding:18px 20px;font-size:18px;line-height:1.4">'
               f'👉 <b>Needs you:</b> {need}</div>'
               f'<div style="padding:0 20px 14px;font-size:12px;color:#999">'
               f'<span style="color:{GREEN}">●</span> posted &nbsp; <span style="color:{GREY}">●</span> skipped (no strong story) '
               f'&nbsp; <span style="color:{RED}">●</span> failed &nbsp; ■ = reel</div></div>')
    return "\n".join(out)


def main():
    dry = "--dry" in sys.argv
    y = date.today() - timedelta(days=1)
    if "--day" in sys.argv:  # test a specific day: daily.py --dry --day 2026-10-06
        y = date.fromisoformat(sys.argv[sys.argv.index("--day") + 1])
    git("fetch", "-q", "origin", "main")
    today = str(date.today())
    lines, problems, action, rows, followers, sparks = [], [], False, {}, {}, {}
    for lang in ("en", "he"):
        p = PAGES[lang]
        flag, name = NAMES[lang]
        now = datetime.now(ZoneInfo(p["tz"]))
        posts = post_dirs(lang, y)
        rows[lang] = {k: slot_states(lang, k, y, posts, now) for k in ("card", "reel")}
        for kind, noun in (("card", "post"), ("reel", "reel")):
            for s in rows[lang][kind]:
                if s["state"] == "failed":
                    problems.append(f"{name} {s['time']} {noun} {s['why']}. "
                                    "Nothing to do, the next slots run as normal.")
        lines.append(f"{flag} {name}: {count_part(rows[lang]['card'], 'posts')} · "
                     f"{count_part(rows[lang]['reel'], 'reels')}")
        try:
            counts, live, live_reels = scrape_channel(p["account"])
            delta, hist = record_followers(p["account"], counts["followers"], today)
            followers[lang] = (counts["followers"], delta)
            sparks[lang] = sparkline(hist, GREEN if hist[-1] >= hist[0] else RED)
            # live truth check: each published caption must be on the profile
            for kind, noun, pool in (("card", "post", live), ("reel", "reel", live_reels)):
                descs = " || ".join(norm(e["desc"]) for e in pool)
                for s in rows[lang][kind]:
                    if s["state"] == "posted":
                        key = own_caption(lang, s["name"])
                        if not key or key not in descs:
                            s["state"] = "failed"
                            action = True
                            problems.append(f"{name} {s['time']} {noun} is not showing on Instagram. "
                                            "Open the app, check Account Status.")
        except Exception as e:
            print(f"instagram check {p['account']}: {type(e).__name__}: {e}", file=sys.stderr)
            followers[lang] = ("?", None)
            sparks[lang] = sparkline([], GREY)
            problems.append(f"Could not open {name} Instagram to double-check. "
                            "Nothing to do, I'll check again tomorrow.")
        # counts may have changed after the live check
        lines[-1] = (f"{flag} {name}: {count_part(rows[lang]['card'], 'posts')} · "
                     f"{count_part(rows[lang]['reel'], 'reels')}")

    def fol(lang):
        n, d = followers[lang]
        return f"{n}" + ("" if d is None else f" ({'+' if d >= 0 else ''}{d})")
    lines.append(f"👥 Followers: {fol('en')} · {fol('he')}")
    lines.append("👉 Needs you: " + ("nothing" if not problems else
                                     problems[0] if len(problems) == 1 else
                                     "\n" + "\n".join(f"• {x}" for x in problems)))
    n = len(problems)
    subject = ("✅ AI pages: all good" if not n else
               f"⚠️ AI pages: {n} thing{'s' if n > 1 else ''} need{'' if n > 1 else 's'} you")
    text = "\n".join(lines)
    color = GREEN if not n else RED if action else AMBER
    headline = "All good ✅" if not n else f"{n} thing{'s' if n > 1 else ''} need{'' if n > 1 else 's'} you"
    html = render_html(y, rows, followers, problems, color, headline)
    images = {f"spark-{k}": v for k, v in sparks.items()}
    print(subject + "\n\n" + text)
    if "--out" in sys.argv:  # preview: email.html + PNGs side by side
        od = sys.argv[sys.argv.index("--out") + 1]
        os.makedirs(od, exist_ok=True)
        for cid, png in images.items():
            open(os.path.join(od, cid + ".png"), "wb").write(png)
        open(os.path.join(od, "email.html"), "w").write(
            '<meta charset="utf-8">' + re.sub(r'src="cid:([\w-]+)"', r'src="\1.png"', html))
    if "--json" in sys.argv:  # combined report (~/ig-report) reads this; no email from here
        with open(sys.argv[sys.argv.index("--json") + 1], "w") as f:
            json.dump({"day": str(y), "rows": rows, "followers": followers,
                       "problems": problems, "action": action}, f, ensure_ascii=False)
    if dry:
        return
    try:
        if "--json" in sys.argv:  # owner 2026-10-06: one combined report; issue only when needed
            mailed, note = True, "Email goes out from the combined report (~/ig-report)."
        else:
            mailed = send_email(subject, text, html=html, images=images)
            note = "Emailed." if mailed else "EMAIL NOT SENT: no GMAIL_APP_PASSWORD in ~/kestrel/.env."
    except Exception as e:
        mailed, note = False, f"EMAIL FAILED ({type(e).__name__}: {e})."
    print(note, file=sys.stderr)
    # GitHub issue only when something needs the owner, or the email did not
    # go out (then the issue is the only copy)
    if not problems and mailed:
        return
    title = f"IG daily report {date.today()}"
    for attempt in range(3):
        if attempt:
            time.sleep(120)
        r = subprocess.run(["gh", "issue", "create", "-R", REPO, "--title", title,
                            "--body", f"{subject}\n\n{text}\n\n{note}"], cwd=HERE)
        if r.returncode == 0:
            break
    else:
        raise RuntimeError("gh issue create failed after 3 attempts")
    out = subprocess.run(  # keep exactly one report issue open
        ["gh", "issue", "list", "-R", REPO, "--state", "open", "--search",
         "IG daily report in:title", "--json", "number,title"],
        capture_output=True, text=True, cwd=HERE)
    try:
        for i in json.loads(out.stdout):
            if i["title"].startswith("IG daily report") and i["title"] != title:
                subprocess.run(["gh", "issue", "close", "-R", REPO, str(i["number"])], cwd=HERE)
    except Exception:
        pass


if __name__ == "__main__":
    main()
