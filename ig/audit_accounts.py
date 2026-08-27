#!/usr/bin/env python3
"""One-off competitor deep audit (owner order Aug 27: "really understand top
accounts in my field... only based on data"). NOT part of the daily pipeline —
spy.py stays the production scraper. This goes deeper per handle: follower
count, ~24 newest posts each with format (reel/carousel/image), EXACT posting
timestamp, likes, comments, caption. Output: ig/audit-accounts.json.

Run on the Mac (residential IP): .venv/bin/python audit_accounts.py [handle ...]
Reuses the logged-in .igprofile session from spy.py.
"""
import json, os, random, re, sys, time

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
PROFILE = os.path.join(HERE, ".igprofile")
OUT = os.path.join(HERE, "audit-accounts.json")
POST_CAP = 24
DESC_RE = re.compile(r"([\d.,KM]+)\s+likes?,\s*([\d.,KM]+)\s+comments?\s*-\s*\S+\s+on\s+([A-Z][a-z]+ \d+, \d{4})[^:]*:\s*(.*)", re.S)
# some posts hide counts in meta ('handle on August 27, 2026: "caption"')
DESC2_RE = re.compile(r"\S+\s+on\s+([A-Z][a-z]+ \d+, \d{4})[^:]*:\s*[\"\u201c]?(.*)", re.S)
PROF_RE = re.compile(r"([\d.,KM]+)\s+Followers?,\s*([\d.,KM]+)\s+Following,\s*([\d.,KM]+)\s+Posts", re.I)

HANDLES = ["technology", "evolving.ai", "chatgptricks", "getintoai",
           "techskills", "theaisurfer", "eluna.ai", "dailychatgpt",
           "theaiavalanche", "chatgptmastery", "godofprompt", "aitoolreport",
           "futurism", "techcrunch"]


def n(tok):
    tok = tok.replace(",", "")
    if tok.endswith("K"): return int(float(tok[:-1]) * 1e3)
    if tok.endswith("M"): return int(float(tok[:-1]) * 1e6)
    return int(float(tok))


def meta(page, sel):
    el = (page.query_selector(f'meta[property="{sel}"]')
          or page.query_selector(f'meta[name="{sel}"]'))
    return el.get_attribute("content") if el else ""


def save(data):
    json.dump(data, open(OUT, "w"), indent=1, ensure_ascii=False)


def scrape_handle(ctx, handle, data):
    page = ctx.new_page()
    try:
        page.goto(f"https://www.instagram.com/{handle}/",
                  wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(4500)
        desc = meta(page, "og:description") or meta(page, "description") or ""
        prof = {"handle": handle, "followers": 0, "posts_total": 0, "posts": []}
        m = PROF_RE.search(desc)
        if m:
            prof.update(followers=n(m.group(1)), posts_total=n(m.group(3)))
        print(f"@{handle}: {prof['followers']:,} followers", file=sys.stderr)
        if not m:
            print(f"  profile meta unreadable ({desc[:80]!r}) — skipping",
                  file=sys.stderr)
            data["profiles"].append(prof)
            save(data)
            return
        # collect grid links, scrolling until POST_CAP or no growth
        hrefs, stall = [], 0
        while len(hrefs) < POST_CAP and stall < 2:
            before = len(hrefs)
            for a in page.query_selector_all('a[href*="/p/"], a[href*="/reel/"]'):
                h = a.get_attribute("href")
                if h and h not in hrefs:
                    hrefs.append(h)
            stall = stall + 1 if len(hrefs) == before else 0
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(random.randint(2000, 3500))
        hrefs = hrefs[:POST_CAP]
        print(f"  {len(hrefs)} post links", file=sys.stderr)
        for i, href in enumerate(hrefs):
            try:
                page.goto(f"https://www.instagram.com{href}",
                          wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(random.randint(2500, 4000))
                d = meta(page, "og:description") or meta(page, "description")
                entry = {"shortcode": href.strip("/").split("/")[-1],
                         "kind": "reel" if "/reel/" in href else "post",
                         "likes": 0, "comments": 0, "caption": (d or "")[:400]}
                m2 = DESC_RE.search(d or "")
                if m2:
                    entry.update(likes=n(m2.group(1)), comments=n(m2.group(2)),
                                 caption=m2.group(4).strip()[:400])
                else:
                    m3 = DESC2_RE.search(d or "")
                    if m3:
                        entry["caption"] = m3.group(2).strip()[:400]
                    # anonymous views hide counts on some posts — record as
                    # MISSING, never guess (a body-text fallback caught
                    # comment like-counts and poisoned the data)
                    entry["likes"] = entry["comments"] = None
                t = page.query_selector("time")
                if t:
                    entry["ts"] = t.get_attribute("datetime")
                if entry["kind"] == "post":
                    # carousel = the "Next" arrow inside the media viewer
                    entry["kind"] = ("carousel" if
                                     page.query_selector('button[aria-label="Next"]')
                                     else "image")
                prof["posts"].append(entry)
                lk = "hidden" if entry["likes"] is None else f"{entry['likes']:,}"
                print(f"  [{i+1}/{len(hrefs)}] {entry['kind']:8} {lk:>9}  "
                      f"{entry.get('ts','?')[:16]}", file=sys.stderr)
            except Exception as e:
                print(f"  post {href} failed: {e}", file=sys.stderr)
            page.wait_for_timeout(random.randint(1500, 3500))
        data["profiles"].append(prof)
        save(data)  # incremental — a crash keeps every finished handle
    finally:
        page.close()


def main():
    handles = [a for a in sys.argv[1:] if not a.startswith("-")] or HANDLES
    data = (json.load(open(OUT)) if os.path.exists(OUT)
            else {"scraped": time.strftime("%Y-%m-%d"), "profiles": []})
    done = {p["handle"] for p in data["profiles"] if p.get("posts")}
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            PROFILE, headless=True, viewport={"width": 1280, "height": 900})
        for h in handles:
            if h in done:
                print(f"@{h}: already scraped — skipping", file=sys.stderr)
                continue
            scrape_handle(ctx, h, data)
            time.sleep(random.randint(8, 15))
        ctx.close()
    save(data)
    print(f"done: {sum(len(p['posts']) for p in data['profiles'])} posts "
          f"across {len(data['profiles'])} profiles -> {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
