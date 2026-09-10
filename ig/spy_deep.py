#!/usr/bin/env python3
"""ONE-OFF deep study scraper (owner order Sep 10: "look into every
getintoai post and technology post... pictures, stories, hook,
storytelling, format") — NOT part of the daily pipeline; spy.py stays the
production scraper.

Per handle: newest POST_CAP carousel/image posts, EVERY slide at full
resolution + caption/likes/date, via IG's own media-info API on the
logged-in .igprofile session (shortcode -> media pk decode).

Run on the Mac (residential IP): .venv/bin/python spy_deep.py [handle ...]
Output: reference/deep/<handle>/<shortcode>/slide-N.jpg + meta.json
"""
import json, os, random, sys, time

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
PROFILE = os.path.join(HERE, ".igprofile")
OUT = os.path.join(HERE, "reference", "deep")
HANDLES = ["getintoai", "technology"]
POST_CAP = 20  # owner Sep 10: "take last 20 from each"
ALPHA = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
API_HDRS = {"x-ig-app-id": "936619743392459",
            "referer": "https://www.instagram.com/"}


def pk(shortcode):
    v = 0
    for c in shortcode[:11]:
        v = v * 64 + ALPHA.index(c)
    return v


def grab(page, handle):
    page.goto(f"https://www.instagram.com/{handle}/",
              wait_until="domcontentloaded")
    page.wait_for_timeout(5000)
    codes = []
    for _ in range(8):  # grid lazy-loads ~12 at a time — scroll until enough
        for a in page.query_selector_all('a[href*="/p/"]'):  # posts, no reels
            c = (a.get_attribute("href") or "").strip("/").split("/")[-1]
            if c and c not in codes:
                codes.append(c)
        if len(codes) >= POST_CAP:
            break
        page.mouse.wheel(0, 2500)
        page.wait_for_timeout(random.uniform(2000, 3500))
    codes = codes[:POST_CAP]
    print(f"@{handle}: {len(codes)} posts", file=sys.stderr)
    for code in codes:
        pdir = os.path.join(OUT, handle, code)
        if os.path.exists(os.path.join(pdir, "meta.json")):
            continue
        try:
            r = page.request.get(
                f"https://www.instagram.com/api/v1/media/{pk(code)}/info/",
                headers=API_HDRS)
            item = r.json()["items"][0]
        except Exception as e:
            print(f"  {code}: API failed ({e}) — skipped", file=sys.stderr)
            time.sleep(random.uniform(5, 9))
            continue
        os.makedirs(pdir, exist_ok=True)
        slides = item.get("carousel_media") or [item]
        kinds = []
        for i, s in enumerate(slides, 1):
            iv = (s.get("image_versions2") or {}).get("candidates") or []
            kinds.append("video" if s.get("video_versions") else "image")
            if iv:
                img = page.request.get(iv[0]["url"])
                with open(os.path.join(pdir, f"slide-{i}.jpg"), "wb") as f:
                    f.write(img.body())
            time.sleep(random.uniform(0.8, 1.6))
        meta = {"handle": handle, "shortcode": code,
                "likes": item.get("like_count"),
                "comments": item.get("comment_count"),
                "taken_at": time.strftime(
                    "%Y-%m-%d", time.gmtime(item.get("taken_at", 0))),
                "n_slides": len(slides), "kinds": kinds,
                "caption": ((item.get("caption") or {}).get("text") or "")}
        with open(os.path.join(pdir, "meta.json"), "w") as f:
            json.dump(meta, f, ensure_ascii=False, indent=1)
        print(f"  {code}: {len(slides)} slides, "
              f"{meta['likes']} likes ({meta['taken_at']})", file=sys.stderr)
        time.sleep(random.uniform(6, 12))


def main():
    handles = sys.argv[1:] or HANDLES
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            PROFILE, headless=True,
            viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        for h in handles:
            grab(page, h)
            time.sleep(random.uniform(8, 15))
        ctx.close()


if __name__ == "__main__":
    main()
