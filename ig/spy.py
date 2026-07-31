#!/usr/bin/env python3
"""Scrapes reference IG pages (@technology etc.) for covers + captions + likes.
Run with the venv python: .venv/bin/python spy.py [--login] [handle ...]

First run:  .venv/bin/python spy.py --login   (headed browser, log in once —
session persists in .igprofile/). After that it runs headless.

Per handle: grabs the newest POST_CAP posts. Each post page's meta tags carry
everything we need — og:image (the cover) and the description ("123K likes,
456 comments - technology on July 25, 2026: caption"). Saves covers to
reference/<handle>/<shortcode>.jpg and appends to reference/index.json,
then prints the handle's posts ranked by likes so the best hooks surface."""
import json, os, re, sys, time, random

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
PROFILE = os.path.join(HERE, ".igprofile")
REF = os.path.join(HERE, "reference")
HANDLES = ["technology"]
POST_CAP = 12          # newest posts per handle per run — keep it gentle
DESC_RE = re.compile(r"([\d.,KM]+)\s+likes?,\s*([\d.,KM]+)\s+comments?\s*-\s*\S+\s+on\s+([A-Z][a-z]+ \d+, \d{4})[^:]*:\s*(.*)", re.S)


def n(tok):
    tok = tok.replace(",", "")
    if tok.endswith("K"): return int(float(tok[:-1]) * 1e3)
    if tok.endswith("M"): return int(float(tok[:-1]) * 1e6)
    return int(float(tok))


def meta(page, sel):
    el = page.query_selector(f'meta[property="{sel}"]') or page.query_selector(f'meta[name="{sel}"]')
    return el.get_attribute("content") if el else ""


def scrape_handle(ctx, handle, index):
    page = ctx.new_page()
    page.goto(f"https://www.instagram.com/{handle}/", wait_until="domcontentloaded")
    page.wait_for_timeout(4000)
    hrefs = []
    for a in page.query_selector_all('a[href*="/p/"], a[href*="/reel/"]'):
        h = a.get_attribute("href")
        if h and h not in hrefs:
            hrefs.append(h)
        if len(hrefs) >= POST_CAP:
            break
    print(f"@{handle}: {len(hrefs)} posts found", file=sys.stderr)
    os.makedirs(os.path.join(REF, handle), exist_ok=True)
    known = {e["shortcode"] for e in index if e["handle"] == handle}
    for href in hrefs:
        code = href.strip("/").split("/")[-1]
        if code in known:
            continue
        page.goto(f"https://www.instagram.com{href}", wait_until="domcontentloaded")
        page.wait_for_timeout(2500)
        img, desc = meta(page, "og:image"), meta(page, "og:description") or meta(page, "description")
        entry = {"handle": handle, "shortcode": code, "likes": 0, "comments": 0,
                 "date": "", "caption": desc, "scraped": time.strftime("%Y-%m-%d")}
        m = DESC_RE.search(desc or "")
        if m:
            entry.update(likes=n(m.group(1)), comments=n(m.group(2)),
                         date=m.group(3), caption=m.group(4).strip()[:600])
        if img:
            try:
                data = ctx.request.get(img).body()
                open(os.path.join(REF, handle, f"{code}.jpg"), "wb").write(data)
                entry["cover"] = f"reference/{handle}/{code}.jpg"
            except Exception as e:
                print(f"  cover failed {code}: {e}", file=sys.stderr)
        index.append(entry)
        print(f"  {code}: {entry['likes']:>8} likes  {entry['caption'][:60]}", file=sys.stderr)
        page.wait_for_timeout(random.randint(2000, 4500))
    page.close()


def main():
    login = "--login" in sys.argv
    handles = [a for a in sys.argv[1:] if not a.startswith("-")] or HANDLES
    os.makedirs(REF, exist_ok=True)
    idx_path = os.path.join(REF, "index.json")
    index = json.load(open(idx_path)) if os.path.exists(idx_path) else []
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            PROFILE, headless=not login, viewport={"width": 1280, "height": 900})
        if login:
            ctx.pages[0].goto("https://www.instagram.com/")
            input("Log in to Instagram in the browser, then press Enter here... ")
        for h in handles:
            scrape_handle(ctx, h, index)
        ctx.close()
    json.dump(index, open(idx_path, "w"), indent=1)
    print(f"\n{len(index)} posts in index", file=sys.stderr)
    for h in handles:
        top = sorted((e for e in index if e["handle"] == h), key=lambda e: -e["likes"])[:10]
        print(f"\nTOP HOOKS @{h} (by likes):", file=sys.stderr)
        for e in top:
            print(f"  {e['likes']:>8}  {e['caption'][:90]}", file=sys.stderr)


if __name__ == "__main__":
    main()
