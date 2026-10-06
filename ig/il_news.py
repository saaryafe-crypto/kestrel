#!/usr/bin/env python3
"""Hebrew news pool from Israeli tech press RSS (owner-approved 2026-10-05).
The Hebrew page is written natively from these Hebrew articles, never
translated from the English page. Virality = how many distinct Israeli
outlets carry the story in 48h (counted by gates.py when it clusters).
Calcalist's own RSS 403s, so it arrives through Google News.

Usage: python3 il_news.py   prints the pool"""
import html, json, os, re, sys, time, urllib.request
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
POOL = os.path.join(HERE, "pool-he.json")
WINDOW_H = 48
FEEDS = {
    "גיקטיים": "https://www.geektime.co.il/feed/",
    "ynet": "https://www.ynet.co.il/Integration/StoryRss544.xml",
    "גלובס": "https://www.globes.co.il/webservice/rss/rssfeeder.asmx/FeederNode?iID=594",
    "gnews_ai": "https://news.google.com/rss/search?q=%D7%91%D7%99%D7%A0%D7%94+%D7%9E%D7%9C%D7%90%D7%9B%D7%95%D7%AA%D7%99%D7%AA+when:2d&hl=he&gl=IL&ceid=IL:he",
    "gnews_tech": "https://news.google.com/rss/search?q=%28%D7%94%D7%99%D7%99%D7%98%D7%A7%20OR%20%D7%A1%D7%98%D7%90%D7%A8%D7%98%D7%90%D7%A4%20OR%20%D7%90%D7%A7%D7%96%D7%99%D7%98%20OR%20%D7%A1%D7%99%D7%99%D7%91%D7%A8%20OR%20%D7%A9%D7%91%D7%91%D7%99%D7%9D%20OR%20%D7%90%D7%A0%D7%91%D7%99%D7%93%D7%99%D7%94%29%20when%3A2d&hl=he&gl=IL&ceid=IL:he",
    "gnews_calcalist": "https://news.google.com/rss/search?q=site%3Acalcalist.co.il%20%28%D7%91%D7%99%D7%A0%D7%94%20%D7%9E%D7%9C%D7%90%D7%9B%D7%95%D7%AA%D7%99%D7%AA%20OR%20%D7%94%D7%99%D7%99%D7%98%D7%A7%20OR%20%D7%A1%D7%98%D7%90%D7%A8%D7%98%D7%90%D7%A4%20OR%20%D7%A1%D7%99%D7%99%D7%91%D7%A8%20OR%20%D7%90%D7%A4%D7%9C%20OR%20%D7%92%D7%95%D7%92%D7%9C%20OR%20%D7%A9%D7%91%D7%91%D7%99%D7%9D%20OR%20OpenAI%29%20when%3A2d&hl=he&gl=IL&ceid=IL:he",
}
BLOCK = {"Vietnam.vn"}  # Google News leaks machine-translated mirrors
# one outlet, one name (Google News names ynet "ynet.co.il", the direct feed "ynet")
CANON = {"ynet.co.il": "ynet", "calcalist": "כלכליסט", "www.calcalist.co.il": "כלכליסט",
         "israelhayom.co.il": "ישראל היום", "globes.co.il": "גלובס", "themarker.com": "TheMarker",
         "geektime.co.il": "גיקטיים", "haaretz.co.il": "הארץ", "maariv.co.il": "מעריב"}
# established Israeli newsrooms: one of them carrying a global story is
# enough for the Hebrew page (gates in news.py); small sites need a 2nd outlet
REPUTABLE = {"גיקטיים", "ynet", "גלובס", "כלכליסט", "TheMarker", "הארץ", "מעריב", "mako",
             "ישראל היום", "וואלה", "N12", "כאן", "i24NEWS", "ice (אייס)", "אנשים ומחשבים",
             "ביזפורטל", "דבר", "davar1.co.il", "מקור ראשון", "The Times of Israel"}
UA = {"User-Agent": "Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/120 Safari/537.36"}


def fetch(url, timeout=20):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()


def harvest():
    now, items = time.time(), []
    for feed, url in FEEDS.items():
        try:
            root = ET.fromstring(fetch(url))
        except Exception as e:
            print(f"rss {feed} failed: {e}", file=sys.stderr)
            continue
        for it in root.iter("item"):
            g = lambda t: (it.findtext(t) or "").strip()
            try:
                age = (now - parsedate_to_datetime(g("pubDate")).timestamp()) / 3600
            except Exception:
                continue
            if age > WINDOW_H or not re.search("[\u0590-\u05FF]", g("title")):
                continue  # Hebrew titles only (Google News leaks foreign sites)
            title, outlet = html.unescape(g("title")), feed
            if feed.startswith("gnews"):
                # Google News titles end with " - <outlet>"
                src = it.find("source")
                outlet = (src.text if src is not None else "").strip() or outlet
                title = re.sub(r"\s+-\s+[^-]+$", "", title)
            outlet = CANON.get(outlet, outlet)
            if outlet in BLOCK:
                continue
            img = None
            for el in it:
                if el.tag.endswith("content") or el.tag.endswith("thumbnail") or el.tag == "enclosure":
                    img = img or el.attrib.get("url")
            if not img:
                # ynet/Geektime put the article photo inside the description /
                # content:encoded HTML (their pages block CI runners, so this
                # is often the only photo a GitHub run can get)
                body = g("description") + "".join(el.text or "" for el in it if el.tag.endswith("encoded"))
                m = re.search(r"<img[^>]+src=[\"']([^\"']+)", html.unescape(body))
                if m:
                    img = m.group(1).replace("_medium.jpg", "_large.jpg")
            items.append({"id": f"he{len(items)}", "outlet": outlet, "title": title,
                          "link": g("link"), "age_h": round(age, 1), "img": img,
                          "desc": re.sub(r"<[^>]+>", "", html.unescape(g("description")))[:300]})
    pool = {"updated": now, "items": items}
    json.dump(pool, open(POOL, "w"), indent=1, ensure_ascii=False)
    print(f"he pool: {len(items)} items", file=sys.stderr)
    return pool


if __name__ == "__main__":
    for i in harvest()["items"]:
        print(f"{i['age_h']:>5}h {i['outlet'][:12]:<12} {i['title'][:100]}")
