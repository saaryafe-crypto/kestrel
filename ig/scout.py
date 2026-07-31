#!/usr/bin/env python3
"""Scout: content-intelligence layer for the IG pipeline.
Usage: python3 scout.py [out.json]

Everything fetch.py harvests (feeds, Google News, Reddit RSS crowd ranking)
PLUS Hacker News via Algolia — the only source whose REAL vote counts are
reachable from CI (reddit .json is blocked everywhere). On top of the
mechanical score it adds:
  1. crowd bonus: HN points (real numbers, not rank guesses)
  2. corroboration bonus: the same story carried by 2+ independent sources
     means it's spreading — velocity we can measure without any API key
  3. Claude interest judge: every finalist scored 0-10 on "would a
     19-year-old scrolling IG stop for this?" before final ranking
Writes stories.json in the exact schema fetch.py writes, so write.py /
recap.py / edu.py inherit it unchanged. Every stage fails open — a judge
outage degrades to mechanical ranking, never an empty pool (7/day is a must).
"""
import json, os, re, sys, time
from datetime import date, datetime

from fetch import (FEEDS, GNEWS, MIN_IMG_WIDTH, get, og_image, parse_feed,
                   reddit_stories, score)

HERE = os.path.dirname(os.path.abspath(__file__))

STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
        "is", "are", "was", "has", "have", "its", "it", "at", "by", "from",
        "that", "this", "as", "be", "will", "new", "how", "why", "what"}

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "scores": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"i": {"type": "integer"},
                               "interest": {"type": "integer", "minimum": 0, "maximum": 10}},
                "required": ["i", "interest"],
            },
        },
    },
    "required": ["scores"],
}


def hn_stories():
    """Hacker News via Algolia: front page + high-point AI stories. Unlike
    every other source, this returns REAL vote counts from CI — no auth."""
    out = []
    for url, src in [
        ("https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage=30",
         "hn:front"),
        ("https://hn.algolia.com/api/v1/search_by_date?query=AI&tags=story"
         "&numericFilters=points%3E80&hitsPerPage=20", "hn:ai"),
    ]:
        try:
            hits = json.loads(get(url))["hits"]
        except Exception as e:
            print(f"  ! {src}: {e}", file=sys.stderr)
            continue
        for h in hits:
            if not h.get("url") or not h.get("title"):  # Ask HN / self posts
                continue
            out.append({"title": h["title"], "link": h["url"],
                        "date": h.get("created_at", ""), "src": src,
                        "points": h.get("points") or 0,
                        "comments": h.get("num_comments") or 0})
    print(f"hn: {len(out)} stories with real point counts", file=sys.stderr)
    return out


def sig(title):
    return {w for w in re.findall(r"[a-z0-9']+", title.lower())
            if w not in STOP and len(w) > 2}


def domain(story):
    s = story["src"]
    return s.split("/")[2] if s.startswith("http") else s.split(":")[0]


def same(a, b):
    """Two titles tell the same story: >=3 shared significant words covering
    half the shorter title."""
    shared = len(a & b)
    return shared >= 3 and shared >= min(len(a), len(b)) / 2


def corroborate(stories):
    """Same story in N independent sources = it's spreading."""
    sigs = [sig(s["title"]) for s in stories]
    for i, s in enumerate(stories):
        srcs = {domain(s)}
        for j, o in enumerate(stories):
            if i != j and domain(o) not in srcs and same(sigs[i], sigs[j]):
                srcs.add(domain(o))
        s["sources"] = len(srcs)


def collapse(stories):
    """One version per story — the highest-scored wording survives; the other
    outlets' variants already paid their corroboration bonus. Without this,
    one hot story floods the top of the pool with 4 near-identical entries."""
    kept, ksigs = [], []
    for s in sorted(stories, key=lambda s: -s["score"]):
        g = sig(s["title"])
        if any(same(g, k) for k in ksigs):
            continue
        kept.append(s)
        ksigs.append(g)
    return kept


def market_boost(stories):
    """Ground-truth crowd data harvested daily on the Mac (market.py): big IG
    pages' last-48h winners with like counts + real reddit upvote scores —
    crowds CI can't reach itself. A story that 2+ independent crowds already
    loved is nearly never a dud; an IG-proven story also carries the winning
    hook wording forward to the writer (ig_proof rides into stories.json).
    Fails open: missing or stale (>48h) file = no boost, ranking stands."""
    try:
        m = json.load(open(os.path.join(HERE, "market.json")))
        age_h = (time.time() - datetime.fromisoformat(m["updated"]).timestamp()) / 3600
        if age_h > 48:
            print(f"market.json is {age_h:.0f}h old — skipping ground-truth boost",
                  file=sys.stderr)
            return
    except Exception as e:
        print(f"no market data ({e}) — mechanical ranking stands", file=sys.stderr)
        return
    ig = [(sig(h["hook"]), h) for h in m.get("competitor_hits", [])]
    rd = [(sig(r["title"]), r) for r in m.get("reddit_hot", [])]
    n_ig = n_rd = 0
    for s in stories:
        g = sig(s["title"])
        hit = next((h for hs, h in ig if same(g, hs)), None)
        if hit:
            s["ig_proof"] = hit
            s["score"] += min(50, 20 + 10 * hit["ratio"])
            n_ig += 1
        rp = next((r for rs, r in rd if same(g, rs)), None)
        if rp:
            s["reddit_proof"] = rp
            s["score"] += min(40, rp["score"] / 400)
            n_rd += 1
    print(f"market boost: {n_ig} IG-proven, {n_rd} reddit-proven stories",
          file=sys.stderr)


def radar_boost(stories):
    """Demand Radar (radar.py, Mac, every 2h): live Reddit breakout moments
    with velocity math + top-comment mining. The strategy shift behind it:
    harvest PROVEN demand instead of predicting it. A story already matched
    in the harvest gets a velocity boost; a radar moment the press hasn't
    written up yet (screenshot posts, demos, drama threads) joins the pool
    as its own candidate — social-native stories used to be invisible here.
    Fails open: missing or stale (>24h) radar.json = nothing changes."""
    try:
        r = json.load(open(os.path.join(HERE, "radar.json")))
        age_h = (time.time() - datetime.fromisoformat(r["updated"]).timestamp()) / 3600
        if age_h > 24:
            print(f"radar.json is {age_h:.0f}h old — skipping radar boost",
                  file=sys.stderr)
            return
    except Exception as e:
        print(f"no radar data ({e}) — ranking stands", file=sys.stderr)
        return
    sigs = [(sig(m["title"]), m) for m in r.get("moments", [])]
    matched = added = 0
    for s in stories:
        g = sig(s["title"])
        m = next((m for ms, m in sigs if same(g, ms)), None)
        if m:
            s["radar"] = m
            s["score"] += min(60, 20 + m["vph"] / 25)
            matched += 1
    known = [sig(s["title"]) for s in stories]
    for ms, m in sigs:
        if any(same(ms, k) for k in known):
            continue
        src = (f"x:{m['sub']}" if m.get("unit") == "likes"
               else f"reddit:r/{m['sub']}")
        stories.append({"title": m["title"],
                        "link": m.get("outlink") or m["permalink"],
                        "date": r["updated"], "src": src,
                        "score": round(40 + min(80, m["vph"] / 12), 1),
                        "image": m.get("image"), "radar": m})
        added += 1
    print(f"radar boost: {matched} matched, {added} social-native candidates added",
          file=sys.stderr)


def saturation(stories):
    """Dead-inventory check (the audience's memory): if the freshest sighting
    of a story on a big IG page is 3+ days old, the IG audience has already
    seen it — posting it now reads as being late, not first. A sighting
    inside the last 2 days is a cresting wave (market_boost already rewards
    it; @pubity model: rarely first, never late). Uses market-history.json,
    the 14-day rolling ledger market.py keeps of every competitor post seen.
    Fails open: no ledger = no demotion."""
    try:
        hist = json.load(open(os.path.join(HERE, "market-history.json")))
    except Exception:
        print("no market history — saturation check skipped", file=sys.stderr)
        return
    sigs = [(sig(h["hook"]), h["date"]) for h in hist]
    today, n = date.today(), 0
    for s in stories:
        g = sig(s["title"])
        ages = [(today - date.fromisoformat(d)).days
                for hs, d in sigs if same(g, hs)]
        if ages and min(ages) >= 3:
            s["saturated_d"] = min(ages)
            s["score"] = round(s["score"] * 0.35, 1)
            n += 1
    print(f"saturation: {n} dead-inventory stories demoted", file=sys.stderr)


def trends_boost(stories):
    """Google Trends daily-search RSS — free, keyless, reachable from CI.
    The one crowd our other signals miss: mainstream America OUTSIDE the
    tech bubble, with approximate search-traffic numbers. A candidate that
    matches a trending search rides a wave already cresting with normal
    people — exactly the audience a viral page needs. Fails open."""
    try:
        xml = get("https://trends.google.com/trending/rss?geo=US").decode("utf-8", "ignore")
    except Exception as e:
        print(f"  ! google trends: {e}", file=sys.stderr)
        return
    trends = []
    for item in re.findall(r"<item>(.*?)</item>", xml, re.S):
        t = re.search(r"<title>([^<]+)</title>", item)
        if not t:
            continue
        tr = re.search(r"<ht:approx_traffic>([\d,]+)\+?</ht:approx_traffic>", item)
        traffic = int(tr.group(1).replace(",", "")) if tr else 0
        # match on the trend's news headlines too — the bare term ("ceasefire")
        # is too short for word-overlap matching on its own
        words = sig(t.group(1) + " " + " ".join(
            re.findall(r"<ht:news_item_title>([^<]*)</ht:news_item_title>", item)))
        trends.append((words, t.group(1), traffic))
    n = 0
    for s in stories:
        g = sig(s["title"])
        hit = next(((term, tf) for w, term, tf in trends if same(g, w)), None)
        if hit:
            s["trend_term"], s["trend_traffic"] = hit
            s["score"] += min(30, 10 + hit[1] / 5000)
            n += 1
    print(f"google trends: {len(trends)} trending searches, {n} matched",
          file=sys.stderr)


def judge(stories):
    """Claude scores every finalist 0-10: would a 19-year-old stop scrolling?
    Fails open — on any error every story keeps a neutral 5."""
    lines = []
    for i, s in enumerate(stories):
        ev = []
        if s.get("points"):
            ev.append(f"{s['points']} HN points, {s.get('comments', 0)} comments")
        if "reddit_rank" in s:
            ev.append(f"#{s['reddit_rank'] + 1} of the day on {s['src']}")
        if s.get("sources", 1) > 1:
            ev.append(f"carried by {s['sources']} independent sources")
        if s.get("ig_proof"):
            p = s["ig_proof"]
            ev.append(f"a big IG tech page already posted this and got "
                      f"{p['likes']:,} likes ({p['ratio']}x their own median)")
        if s.get("reddit_proof"):
            r = s["reddit_proof"]
            ev.append(f"{r['score']:,} real upvotes on r/{r['sub']} today")
        if s.get("radar"):
            m = s["radar"]
            ev.append(f"BREAKING OUT RIGHT NOW: {m['score']:,} "
                      f"{m.get('unit', 'upvotes')} on "
                      f"{m.get('where', 'r/' + m['sub'])} in "
                      f"{m['age_h']:.0f}h ({m['vph']:.0f}/hr)")
            if m.get("top_comments"):
                ev.append(f'the top comment: "{m["top_comments"][0][:90]}"')
        if s.get("trend_term"):
            ev.append(f'"{s["trend_term"]}" is a trending US Google search '
                      f"right now ({s['trend_traffic']:,}+ searches)")
        lines.append(f"[{i}] {s['title']}" + (f"  ({'; '.join(ev)})" if ev else ""))
    prompt = f"""You are the content scout for an Instagram page covering AI, technology, space, business, investing, and money. Score EVERY story below 0-10 on INTEREST: would a 19-year-old scrolling Instagram stop for this?

Scoring doctrine:
- 9-10: a PERSON did something outrageous and there's a concrete outcome with a number ("a student built an app that made $40K while he slept"). People DOING things beat companies announcing things. Top shapes in this tier: the MONEY ARC (tiny spend, built a real thing, short time, big money out: "spent $20 on Claude, built X in 9 days, sold it for $317K"); THE INVENTOR (a college kid, teenager, or scrappy entrepreneur BUILT or INVENTED a real cool thing — the underdog-builds story); "PEOPLE ARE LETTING AI DO X FOR THEM" (ordinary people quietly handing a real job like trading or selling to an AI, already happening, reader feels late); a named rich person BUYING or LOSING something huge ("Zuckerberg just bought X for $2B", "Musk lost $16B in one day"); and SPACE-AS-BUSINESS AWE (a Starship exploding on the pad, SpaceX/Starlink hitting a giant number, a space startup pulling off something crazy) — space belongs here ONLY as a technology/company/money story, never as astronomy.
- 7-8: touches the reader's own life TODAY — their phone, their money, their job, their rent, their salary, apps everyone uses, robots doing something jaw-dropping on video. OR real business value with numbers (AI saved a real company money/hours — our paying audience is small-business owners who book meetings). Salary reveals, net-worth swings, and "what $X buys now vs then" belong here.
- 4-6: big-name news (OpenAI, Musk, Apple, SpaceX, Buffett) that's genuinely surprising but institutional.
- 0-3: funding rounds, benchmarks, enterprise partnerships, chip supply chains, research papers, routine earnings, Fed-minutes-style finance process, policy process stories — newspaper-register news a young scroller flicks past.
BEING ON-TOPIC IS NOT ENOUGH. A pillar match earns nothing by itself — the STORY must be the viral kind. Routine space coverage (launch schedules, mission previews, "how to watch") scores 0-3, and PURE ASTRONOMY (astronomers found a star/planet/galaxy, telescope images, asteroid flybys) scores 0-3 no matter how cool — this page is about AI, technology, and building businesses; a space story must be a company/tech/money story to score high. Daily market noise (stocks rose/fell today, market wraps, analyst price targets, earnings recaps) scores 0-3 even though it is money. Only the specific jaw-dropping event scores high: the explosion, the rescue drama, the first-ever, the named person winning or losing a giant number.
- +1 to any story that is DEBATABLE — the comments will fill with people arguing (job loss, AI art theft, privacy, kids cheating with AI, "this should be illegal"). Arguments are free reach; a story everyone just agrees with is a story nobody comments on.
The engagement data in parentheses is REAL crowd behavior — a story thousands already upvoted or that multiple outlets picked up deserves benefit of the doubt over your own taste.

STORIES:
{chr(10).join(lines)}

Return ONLY JSON: {{"scores": [{{"i": <index>, "interest": <0-10>}}, ...]}} — one entry per story, all {len(stories)} of them."""
    try:
        from write import call_claude
        r = call_claude(prompt, schema=JUDGE_SCHEMA)
        got = {x["i"]: x["interest"] for x in r["scores"]
               if 0 <= x.get("i", -1) < len(stories)}
    except Exception as e:
        print(f"interest judge failed ({e}) — mechanical ranking stands", file=sys.stderr)
        got = {}
    for i, s in enumerate(stories):
        s["interest"] = got.get(i, 5)  # neutral on any miss


def main(out_path="stories.json"):
    urls = FEEDS + [f"https://news.google.com/rss/search?q={q.replace(' ', '%20')}%20when:1d&hl=en-US&gl=US&ceid=US:en" for q in GNEWS]
    stories, seen = [], set()

    def add(s):
        key = re.sub(r"\W+", "", s["title"].lower())[:60]
        if not s["title"] or key in seen:
            return
        seen.add(key)
        s["score"] = score(s)
        if s["score"] < 0:  # too old — points can't resurrect stale news
            return
        if s.get("points"):  # real crowd numbers beat keyword guesses
            s["score"] += min(50, s["points"] / 10)
        if s["score"] > 0:
            stories.append(s)

    # order matters: on a title collision the version with crowd data survives
    for s in reddit_stories():
        add(s)
    for s in hn_stories():
        add(s)
    for u in urls:
        print("fetching", u.split("/")[2], file=sys.stderr)
        for s in parse_feed(u):
            add(s)

    corroborate(stories)
    for s in stories:
        s["score"] += min(36, 18 * (s.get("sources", 1) - 1))
    market_boost(stories)  # ground truth from IG competitors + real reddit scores
    radar_boost(stories)   # live Reddit breakouts: velocity + top-comment mining
    trends_boost(stories)  # mainstream-America search wave (Google Trends RSS)
    saturation(stories)    # dead inventory: IG audience saw it days ago
    # Tier 5 doctrine: press is the SLOW LANE. A story with zero social proof
    # (no crowd numbers anywhere, single outlet) hasn't earned the fast lane —
    # "a newspaper reading newspapers" is the exact failure mode this demotes.
    # Uniform 0.7 keeps press stories' relative order, so the 7/day fallback
    # pool is untouched; social-proven stories simply outrank them.
    for s in stories:
        if not (s.get("radar") or s.get("ig_proof") or s.get("reddit_proof")
                or s.get("trend_term") or s.get("points")
                or "reddit_rank" in s or s.get("sources", 1) > 1):
            s["score"] = round(s["score"] * 0.7, 1)
    stories = collapse(stories)  # already sorted by -score

    finalists = stories[:30]
    judge(finalists)
    for s in finalists:
        # interest 5 = neutral, 10 = 1.6x, 0 = 0.375x — the judge reorders,
        # the mechanical score still anchors (crowd data keeps its vote)
        s["score"] = round(s["score"] * (s["interest"] + 3) / 8, 1)
    # cut what the judge calls boring — but never below a 5-story pool
    keep = [s for s in finalists if s["interest"] > 2]
    if len(keep) < 5:
        keep = finalists
    keep.sort(key=lambda s: -s["score"])

    top = keep[:25]
    for s in top:
        if s.get("image"):  # radar moments carry their own full-res preview
            continue
        if "news.google.com" in s["link"]:  # encrypted redirect; trend signal only
            s["image"] = None
            continue
        img, w = og_image(s["link"])
        s["image"] = img if img and w >= MIN_IMG_WIDTH else None
        time.sleep(0.3)
    json.dump(top, open(out_path, "w"), indent=1)
    print(f"{len(stories)} harvested, {len(finalists)} judged, top {len(top)} -> {out_path}", file=sys.stderr)
    for s in top[:10]:
        print(f"  {s['score']:6.1f}  int:{s['interest']}  src:{s.get('sources', 1)}  {s['title'][:70]}", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "stories.json")
