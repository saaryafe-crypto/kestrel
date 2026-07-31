#!/usr/bin/env python3
"""Fetches candidate stories for IG posts.
Usage: python3 fetch.py [out.json]
Pulls RSS feeds + Google News topic queries, ranks by topic weight + recency,
grabs each article's og:image (the high-res press photo), applies the media
reject rule (min width), and writes ranked stories.json. Stdlib only."""
import json, re, sys, time, urllib.request, xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

UA = {"User-Agent": "Mozilla/5.0 (Macintosh) YaffeAI/1.0"}

FEEDS = [
    "https://techcrunch.com/category/artificial-intelligence/feed/",
    "https://techcrunch.com/feed/",
    "https://www.theverge.com/rss/index.xml",
    "https://feeds.arstechnica.com/arstechnica/index",
    "https://hnrss.org/frontpage",
    # builder stories: Claude Code / vibe-coding posts with real traction
    "https://hnrss.org/newest?q=%22Claude+Code%22&points=50",
    "https://openai.com/news/rss.xml",
    "https://www.engadget.com/rss.xml",
    "https://www.wired.com/feed/tag/ai/latest/rss",
    "https://venturebeat.com/category/ai/feed/",
    "https://www.theguardian.com/technology/rss",
    # space pillar, industry/business sources only (owner rule Jul 29: no pure
    # astronomy — dropped space.com and nasa.gov, they're discovery-heavy)
    "https://spacenews.com/feed/",
    "https://spaceflightnow.com/feed/",
    "https://www.nasaspaceflight.com/feed/",
    "https://www.teslarati.com/feed/",
    # business / investing pillar: acquisitions, markets, big-money moves
    "https://feeds.bloomberg.com/markets/news.rss",
    "https://feeds.bloomberg.com/technology/news.rss",
    "https://www.cnbc.com/id/100003114/device/rss/rss.html",  # CNBC top news
    "https://www.cnbc.com/id/10001147/device/rss/rss.html",   # CNBC business
    "https://fortune.com/feed/",
    # money / wealth pillar: net worth, salaries, personal-finance shocks
    "https://feeds.bloomberg.com/wealth/news.rss",
    "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
    "https://feeds.content.dowjones.io/public/rss/mw_topstories",
    "https://finance.yahoo.com/news/rssindex",
    # @technology's own sources (owner supplied their Sources: lines Jul 29)
    "https://feeds.macrumors.com/MacRumors-All",
    "https://9to5mac.com/feed/",
    "https://www.tomshardware.com/feeds/all",
    "https://www.techspot.com/backend.xml",
    "https://feeds.feedburner.com/TheHackersNews",
    "https://www.notebookcheck.net/News.152.100.html",
]
GNEWS = ["Anthropic", "OpenAI", "ChatGPT", "Nvidia AI", "Meta AI", "AI agents",
         # what regular people share: AI touching jobs, money, daily life
         "AI jobs replaced", "AI fired employees", "viral AI", "AI banned",
         "humanoid robot", "Tesla Optimus", "AI deepfake",
         # X-active people/orgs — news sites cover their big tweets within hours
         "Sam Altman", "Elon Musk AI", "xAI Grok", "Google DeepMind",
         "Perplexity AI", "Mistral AI",
         # business-owner pillar: real value/data for the people who book meetings
         "AI small business", "small business AI automation", "AI saves business money",
         "AI customer service results", "business AI case study", "AI marketing results",
         "restaurant AI", "AI bookkeeping", "AI agents business",
         # builders pillar: inspirational solo/small teams shipping with AI
         "solo founder AI startup", "one person company AI",
         "built with AI revenue", "indie hacker AI",
         "bootstrapped AI startup million",
         "built with Claude Code", "vibe coding app", "AI app built in days",
         # space pillar, tech/business angle only: companies, rockets, money
         "SpaceX launch", "Starship", "Starlink", "space startup",
         "rocket company", "satellite business",
         # business/investing pillar: named actor + giant number
         "billionaire net worth", "acquisition billion", "stock surge",
         "Warren Buffett", "Nvidia stock", "IPO",
         # money pillar: salaries, wealth shocks, everyday money
         "salary tech workers", "millionaire", "housing market", "layoffs",
         # inventors pillar: students/entrepreneurs building cool real things
         "college student invented", "teenager built", "student startup",
         "invention viral", "engineer invented device", "high school student built"]

# Topic gate: a story matching NONE of the page's pillars (AI / space /
# business-money) is off-topic and gets its score slashed (kills e.g. celebrity
# gossip, sports, politics-only stories no matter how big they trend).
# "AI" itself needs word boundaries — plain substring matches "raising", "said"
AI_RE = re.compile(r"\ba\.?i\b")
AI_SIGNALS = ["artificial intelligence", "gpt", "chatgpt", "claude",
              "openai", "anthropic", "gemini", "grok", "copilot", "llm",
              "robot", "humanoid", "agent", "machine learning", "neural",
              "deepmind", "midjourney", "hugging face", "nvidia"]
# space counts ONLY through the tech/business lens (owner rule Jul 29): the
# companies, the rockets, the satellite economy — never pure astronomy
# ("astronomers found a star" is off-brand for an AI/business page)
SPACE_SIGNALS = ["spacex", "starship", "starlink", "rocket", "satellite",
                 "blue origin", "space station", "launch pad", "space startup",
                 "nasa contract", "spaceport", "reusable"]
MONEY_SIGNALS = ["billion", "million", "net worth", "billionaire", "millionaire",
                 "stock", "shares", "ipo", "acqui", "salary", "salaries",
                 "invest", "market cap", "wealth", "fortune", "revenue",
                 "profit", "valuation", "buffett", "wall street", "layoff",
                 "housing market", "interest rate", "crypto", "bitcoin"]
INVENT_SIGNALS = ["invent", "built", "created a", "prototype", "patented",
                  "startup", "founder", "college student", "teenager",
                  "high school", "engineer", "dropout", "student"]
# consumer tech the reference page covers daily: big-brand product news the
# reader holds in their hand (an iPhone leak has no AI/money keyword but is
# 100% on-brand for a technology page)
TECH_SIGNALS = ["iphone", "apple", "samsung", "galaxy", "android", "ipad",
                "macbook", "airpods", "pixel", "whatsapp", "instagram",
                "tiktok", "youtube", "netflix", "spotify", "playstation",
                "xbox", "nintendo", "steam", "windows", "tesla", "google",
                "amazon", "microsoft", "meta ", "uber", "airbnb"]

# topic weights: what the audience actually cares about — consumer AI moments,
# jobs/money impact, robots, and founder stories. People > infrastructure.
WEIGHTS = {
    "chatgpt": 10, "openai": 9, "claude": 10, "anthropic": 10, "gpt": 8,
    "gemini": 7, "grok": 7, "robot": 9, "humanoid": 10, "agent": 8,
    # human impact — the shareable stuff
    "jobs": 8, "fired": 8, "replace": 8, "layoff": 8, "salary": 6,
    "banned": 7, "lawsuit": 6, "sued": 6, "leaked": 7, "secret": 6,
    "viral": 7, "creepy": 6, "scam": 6, "deepfake": 8, "caught": 6,
    # founders / builders pillar
    "solo founder": 10, "one-person": 10, "one person": 9, "founder": 6,
    "claude code": 12, "vibe cod": 8, "cursor": 5, "built": 4,
    "bootstrapped": 7, "indie": 5, "side project": 7, "no employees": 10,
    "million": 5, "billion": 5, "revenue": 5,
    # business-owner value — the audience that books meetings
    "small business": 12, "automat": 7, "saves": 6, "customer service": 7,
    "case study": 8, "roi": 8, "productivity": 5, "hours a week": 8,
    # space pillar — the tech/business side only: companies, rockets, money
    "spacex": 9, "starship": 9, "starlink": 8, "rocket": 6, "explod": 8,
    "nasa contract": 8, "space startup": 10, "satellite": 5,
    # business / investing / money pillar — named actor + giant number
    "billionaire": 9, "net worth": 9, "acquired": 8, "acquisition": 7,
    "buys": 6, "bought": 6, "stock": 5, "ipo": 6, "warren buffett": 8,
    "millionaire": 8, "wealth": 6, "crypto": 5, "bitcoin": 6,
    "housing": 6, "interest rate": 5, "stake": 5,
    # inventors pillar — students/entrepreneurs building cool real things
    "invented": 9, "invention": 8, "college student": 10, "teenager": 9,
    "high school": 8, "student built": 12, "prototype": 5, "patented": 6,
    "garage": 6, "dropout": 8,
    # general ("ai" itself is scored via AI_RE in score(), not here)
    "first": 4, "record": 4, "breakthrough": 5,
    "elon musk": 4, "nvidia": 5, "meta": 4,
    # routine-coverage penalties: on-topic but zero stopping power — schedule
    # journalism and daily market noise (owner rule Jul 29: pillars must be
    # SPECIFIC viral stories, not "everything about space/stocks")
    # (sized to beat the +25 direct-link and +6 freshness bonuses)
    "markets wrap": -40, "launch preview": -40, "how to watch": -45,
    "what to know": -30, "week ahead": -30, "live updates": -25,
    "live coverage": -25, "preview": -15, "roundup": -25, "recap": -20,
    "here's what": -20, "explained": -15, "everything we know": -15,
    "stocks rise": -35, "stocks fall": -35, "stocks slip": -35,
    "market close": -35, "premarket": -40, "opening bell": -40,
    "analyst": -20, "price target": -25, "earnings call": -25,
    "fed decision": -20, "opinion:": -30, "editorial": -25,
}
MIN_IMG_WIDTH = 1000
MAX_AGE_H = 36

# Reddit = the crowd-validated virality layer: a story at the top of a big
# sub's day already won a vote among millions. NEWS-heavy subs only — meme
# subs (r/ChatGPT) top out with personal screenshots we can't write from.
SUBREDDITS = ["singularity", "OpenAI", "ClaudeAI", "artificial"]

def get(url, timeout=15):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()

def text(el, *tags):
    for t in tags:
        found = el.find(t)
        if found is not None and (found.text or "").strip():
            return found.text.strip()
    return ""

def parse_feed(url):
    out = []
    try:
        root = ET.fromstring(get(url))
    except Exception as e:
        print(f"  ! {url}: {e}", file=sys.stderr)
        return out
    ns = {"a": "http://www.w3.org/2005/Atom"}
    for item in root.iter("item"):  # RSS
        link = text(item, "link")
        if "news.google.com" in link:  # real article URL hides in the description anchor
            m = re.search(r'href="(https?://(?!news\.google)[^"]+)"', text(item, "description"))
            if m:
                link = m.group(1)
        out.append({"title": text(item, "title"), "link": link,
                    "date": text(item, "pubDate"), "src": url})
    for entry in root.iter("{http://www.w3.org/2005/Atom}entry"):  # Atom
        link = entry.find("a:link", ns)
        out.append({"title": text(entry, "a:title".replace("a:", "{http://www.w3.org/2005/Atom}")),
                    "link": link.get("href") if link is not None else "",
                    "date": text(entry, "{http://www.w3.org/2005/Atom}published",
                                 "{http://www.w3.org/2005/Atom}updated"), "src": url})
    return out

def reddit_stories():
    """Top-of-day link posts from news-heavy subreddits. The upvote ranking is
    a free, crowd-validated virality signal for the same stories our feeds
    carry. RSS only (unauthenticated JSON died May 2026) at ~1 req/min, so
    requests are spaced; datacenter IPs may get filtered — skip cleanly then."""
    ns = {"a": "http://www.w3.org/2005/Atom"}
    out = []
    for i, sub in enumerate(SUBREDDITS):
        if i:
            time.sleep(61)  # unauthenticated RSS rate limit: ~1 request/min
        try:
            root = ET.fromstring(get(f"https://www.reddit.com/r/{sub}/top.rss?t=day&limit=10"))
        except Exception as e:
            print(f"  ! reddit r/{sub}: {e}", file=sys.stderr)
            continue
        rank = 0
        for e in root.findall("a:entry", ns):
            content = e.find("a:content", ns)
            m = re.search(r'href="([^"]+)">\[link\]',
                          (content.text or "") if content is not None else "")
            link = m.group(1).replace("&amp;", "&") if m else ""
            # article link posts only: self/media posts are other people's
            # content with no article behind them to write from
            if not link.startswith("http") or re.search(r"reddit\.com|redd\.it", link):
                continue
            title_el, date_el = e.find("a:title", ns), e.find("a:published", ns)
            if title_el is None or not (title_el.text or "").strip():
                continue
            out.append({"title": title_el.text.strip(), "link": link,
                        "date": date_el.text if date_el is not None else "",
                        "src": f"reddit:r/{sub}", "reddit_rank": rank})
            rank += 1
    print(f"reddit: {len(out)} article links from {len(SUBREDDITS)} subs", file=sys.stderr)
    return out

def age_hours(datestr):
    try:
        try:
            dt = parsedate_to_datetime(datestr)
        except Exception:
            dt = datetime.fromisoformat(datestr.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 3600
    except Exception:
        return 999

def score(story):
    t = story["title"].lower()
    s = sum(w for k, w in WEIGHTS.items() if k in t)
    age = age_hours(story["date"])
    if age > MAX_AGE_H:
        return -1
    if "news.google.com" not in story["link"]:
        s += 25  # direct link: article text + press image are fetchable
    is_ai = bool(AI_RE.search(t)) or any(k in t for k in AI_SIGNALS)
    on_topic = is_ai or any(k in t for k in SPACE_SIGNALS) \
        or any(k in t for k in MONEY_SIGNALS) \
        or any(k in t for k in INVENT_SIGNALS) \
        or any(k in t for k in TECH_SIGNALS)
    if AI_RE.search(t):
        s += 5  # the literal word AI (was WEIGHTS["ai"])
    s += max(0, (MAX_AGE_H - age)) / 6  # freshness bonus
    if "reddit_rank" in story:
        # crowd-validated virality: rank 1 of the day in a big sub outranks
        # any keyword-scored feed story; decays fast down the ranking
        s += max(0, 45 - 6 * story["reddit_rank"])
    if not on_topic:
        s *= 0.15  # off every pillar, no matter how big the story
    return s

def jpeg_width(data):
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            return 0
        marker, seglen = data[i + 1], int.from_bytes(data[i + 2:i + 4], "big")
        if marker in (0xC0, 0xC1, 0xC2, 0xC3):  # SOF: height then width
            return int.from_bytes(data[i + 7:i + 9], "big")
        i += 2 + seglen
    return 0

def og_image(url):
    """Article's own press image + its width (parsed from image bytes)."""
    try:
        html = get(url).decode("utf-8", "ignore")
        m = re.search(r'property=["\']og:image["\'][^>]*content=["\']([^"\']+)', html) or \
            re.search(r'content=["\']([^"\']+)["\'][^>]*property=["\']og:image["\']', html)
        if not m:
            return None, 0
        img_url = m.group(1).replace("&amp;", "&")
        data = get(img_url)
        width = 0
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            width = int.from_bytes(data[16:20], "big")
        elif data[:3] == b"\xff\xd8\xff":
            width = jpeg_width(data)
        return img_url, width
    except Exception:
        return None, 0

def main(out_path="stories.json"):
    urls = FEEDS + [f"https://news.google.com/rss/search?q={q.replace(' ', '%20')}%20when:1d&hl=en-US&gl=US&ceid=US:en" for q in GNEWS]
    stories, seen = [], set()
    # reddit first: on a title collision the crowd-ranked version must survive dedupe
    for s in reddit_stories():
        key = re.sub(r"\W+", "", s["title"].lower())[:60]
        if s["title"] and key not in seen:
            seen.add(key)
            s["score"] = score(s)
            if s["score"] > 0:
                stories.append(s)
    for u in urls:
        print("fetching", u.split("/")[2], file=sys.stderr)
        for s in parse_feed(u):
            key = re.sub(r"\W+", "", s["title"].lower())[:60]
            if not s["title"] or key in seen:
                continue
            seen.add(key)
            s["score"] = score(s)
            if s["score"] > 0:
                stories.append(s)
    stories.sort(key=lambda s: -s["score"])
    top = stories[:25]
    for s in top:
        if "news.google.com" in s["link"]:  # encrypted redirect; trend signal only
            s["image"] = None
            continue
        img, w = og_image(s["link"])
        s["image"] = img if img and w >= MIN_IMG_WIDTH else None
        time.sleep(0.3)
    json.dump(top, open(out_path, "w"), indent=1)
    print(f"{len(stories)} scored, top {len(top)} -> {out_path}", file=sys.stderr)
    for s in top[:8]:
        print(f"  {s['score']:5.1f}  {s['title'][:80]}  [img:{'Y' if s.get('image') else 'n'}]", file=sys.stderr)

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "stories.json")
