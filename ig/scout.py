#!/usr/bin/env python3
"""Scout: content-intelligence layer for the IG pipeline.
Usage: python3 scout.py [out.json]

X-WATCHLIST ONLY (owner order Aug 3): the story pool is radar.json — viral
tweets from the owner-approved channels in watchlist-x.json, nothing else.
The old harvesting (RSS news feeds, Google News, Reddit RSS, Hacker News)
is deleted. On top of the pool it adds:
  1. crowd re-ranking: IG competitor scrape + Google Trends + saturation
     memory (signals only — they can never ADD a story to the pool)
  2. Claude interest judge: every finalist scored 0-10 on "would a
     19-year-old scrolling IG stop for this?" before final ranking
  3. a hard source gate: any story without an x: source is dropped
Writes stories.json in the same schema as before, so write.py / recap.py /
edu.py inherit it unchanged. Every stage fails open — a judge outage
degrades to mechanical ranking."""
import json, os, re, sys, time
from datetime import date, datetime

from fetch import get  # shared HTTP helper (Google Trends booster only)

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


def sig(title):
    return {w for w in re.findall(r"[a-z0-9']+", title.lower())
            if w not in STOP and len(w) > 2}


def same(a, b):
    """Two titles tell the same story: >=3 shared significant words covering
    half the shorter title."""
    shared = len(a & b)
    return shared >= 3 and shared >= min(len(a), len(b)) / 2


def collapse(stories):
    """One version per story — the highest-scored wording survives. Without
    this, one hot story floods the top of the pool with 4 near-identical
    entries. CONSENSUS BOOST (owner news-first order Sep 3): before a variant
    is discarded, it votes — the same story surfacing on 2+ DIFFERENT
    watchlist accounts is the strongest signal available that this is the
    day's real news (independent editors chose it), so the surviving version
    gets +30 per extra distinct account (cap +90) and the pool re-sorts."""
    kept, ksigs, srcs = [], [], []
    for s in sorted(stories, key=lambda s: -s["score"]):
        g = sig(s["title"])
        hit = next((i for i, k in enumerate(ksigs) if same(g, k)), None)
        if hit is not None:
            if s.get("src"):
                srcs[hit].add(s["src"])
            continue
        kept.append(s)
        ksigs.append(g)
        srcs.append({s.get("src")} - {None})
    for s, acc in zip(kept, srcs):
        if len(acc) >= 2:
            s["consensus"] = len(acc)
            s["score"] = round(s["score"] + min(90, 30 * (len(acc) - 1)), 1)
            print(f"consensus boost: {len(acc)} accounts ran "
                  f"\"{s['title'][:60]}\"", file=sys.stderr)
    kept.sort(key=lambda s: -s["score"])
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


def evergreen_boost(stories):
    """Story-arc / wow-fact bench (owner order Aug 27: the competitor audit
    measured these as the niche's two STRONGEST content types — 3,788 and
    2,625 median likes/1M vs 1,600 for news — and he ordered them made legal
    and pulled from X: "pull these most viral things from twitter!").
    story-pool.json is filled by radar_x's high-floor wide net (10K+ likes,
    politics- and lens-gated). The top few unseen entries join every slot's
    candidate pool scored on RAW likes (evergreen has no velocity); the
    interest judge, Gate A, and the dupe judge still rule on each one. The
    add cap keeps 100K-like monsters from crowding news out of every slot.
    Fails open: no pool = ranking stands."""
    try:
        pool = json.load(open(os.path.join(HERE, "story-pool.json")))
        entries = pool.get("stories", [])
    except Exception:
        return
    known = [sig(s["title"]) for s in stories]
    added = 0
    for m in sorted(entries, key=lambda m: -m.get("score", 0)):
        if added >= 6:
            break
        ms = sig(m.get("title", ""))
        if any(same(ms, k) for k in known):
            continue
        stories.append({"title": m["title"], "link": m.get("permalink"),
                        "date": pool.get("updated", ""),
                        # src is x: — these ARE X tweets (owner's Aug 27
                        # wide-net order), so the source gate passes them
                        "src": f"x:{m.get('sub', 'unknown')}",
                        "score": round(40 + min(80, m.get("score", 0) / 2500), 1),
                        "image": m.get("image"), "radar": m,
                        "evergreen": True})
        known.append(ms)
        added += 1
    if added:
        print(f"evergreen bench: {added} story-arc/wow-fact candidates joined",
              file=sys.stderr)


def radar_boost(stories):
    """Demand Radar (radar.py, Mac, every 2h): breakout moments from the
    owner-approved X watchlist ONLY (owner order Aug 3), with velocity math
    + top-reply mining. Every fresh moment joins the pool as a candidate —
    with the news harvest deleted, this is the ONLY door into stories.json.
    Fails open: missing or stale (>24h) radar.json = empty pool, the slot
    starves loudly (radar_x raises the alarm) rather than filling with junk."""
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
    # HARD ALLOWLIST (owner order Aug 3): even if radar.json is stale or
    # contaminated (old wide-net/Reddit harvests), only moments authored by
    # a watchlist-x.json handle may enter the pool. The x: label alone is
    # not proof — the handle itself is checked against the approved list.
    try:
        lanes = json.load(open(os.path.join(HERE, "watchlist-x.json")))["lanes"]
        approved = {h.lower() for lane in lanes.values() for h in lane}
    except Exception as e:
        print(f"no watchlist-x.json ({e}) — radar pool EMPTY", file=sys.stderr)
        return
    moments = []
    for m in r.get("moments", []):
        if m.get("sub", "").lower() in approved:
            moments.append(m)
        else:
            print(f"radar boost: DROPPED unapproved @{m.get('sub')}: "
                  f"{m.get('title', '')[:55]}", file=sys.stderr)
    sigs = [(sig(m["title"]), m) for m in moments]
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
        src = f"x:{m['sub']}"  # radar is X-watchlist-only (owner order Aug 3)
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
    # THE LAW rides on every judge call (owner order Aug 4): the scout scores
    # against the same doctrine.md every other stage reads — ten private
    # definitions of "good" is how the Queen/Mario disasters shipped.
    try:
        law = open(os.path.join(HERE, "doctrine.md")).read() + "\n\n----\n\n"
    except Exception:
        law = ""
    prompt = f"""{law}You are the content scout for an Instagram page covering AI, technology, space, business, investing, and money. Score EVERY story below 0-10 on INTEREST: would a 19-year-old scrolling Instagram stop for this?

Scoring doctrine:
- 9-10: a PERSON did something outrageous and there's a concrete outcome with a number ("a student built an app that made $40K while he slept"). People DOING things beat companies announcing things. Top shapes in this tier: the MONEY ARC (tiny spend, built a real thing, short time, big money out: "spent $20 on Claude, built X in 9 days, sold it for $317K"); THE INVENTOR (a college kid, teenager, or scrappy entrepreneur BUILT or INVENTED a real cool thing — the underdog-builds story); "PEOPLE ARE LETTING AI DO X FOR THEM" (ordinary people quietly handing a real job like trading or selling to an AI, already happening, reader feels late); a named rich person BUYING or LOSING something huge ("Zuckerberg just bought X for $2B", "Musk lost $16B in one day"); and SPACE-AS-BUSINESS AWE (a Starship exploding on the pad, SpaceX/Starlink hitting a giant number, a space startup pulling off something crazy) — space belongs here ONLY as a technology/company/money story, never as astronomy.
- 7-8: touches the reader's own life TODAY — their phone, their money, their job, their rent, their salary, apps everyone uses, robots doing something jaw-dropping on video. OR real business value with numbers (AI saved a real company money/hours — our paying audience is small-business owners who book meetings). Salary reveals, net-worth swings, and "what $X buys now vs then" belong here.
- 4-6: big-name news (OpenAI, Musk, Apple, SpaceX, Buffett) that's genuinely surprising but institutional.
- 0-3: funding rounds, benchmarks, enterprise partnerships, chip supply chains, research papers, routine earnings, Fed-minutes-style finance process, policy process stories — newspaper-register news a young scroller flicks past.
REACTION-BAIT scores 0-3 (owner rule Aug 3, the Queen-Elizabeth-meme and Mario-Lopez-video disasters): a story whose whole event is that someone POSTED something online and people REACTED — a viral tweet, a meme, an AI-generated video, a screenshot, measured in likes/replies/views. Someone else's content plus a like count is not a story. It climbs out of 0-3 ONLY if there is a REAL-WORLD consequence: money made or lost, someone fired or sued, a product pulled, a company forced to respond.
BEING ON-TOPIC IS NOT ENOUGH. A pillar match earns nothing by itself — the STORY must be the viral kind. Routine space coverage (launch schedules, mission previews, "how to watch") scores 0-3, and PURE ASTRONOMY (astronomers found a star/planet/galaxy, telescope images, asteroid flybys) scores 0-3 no matter how cool — this page is about AI, technology, and building businesses; a space story must be a company/tech/money story to score high. Daily market noise (stocks rose/fell today, market wraps, analyst price targets, earnings recaps) scores 0-3 even though it is money. Only the specific jaw-dropping event scores high: the explosion, the rescue drama, the first-ever, the named person winning or losing a giant number.
- +1 to any story that is DEBATABLE — the comments will fill with people arguing (job loss, AI art theft, privacy, kids cheating with AI, "this should be illegal"). Arguments are free reach; a story everyone just agrees with is a story nobody comments on.
The engagement data in parentheses is REAL crowd behavior — a story thousands already upvoted or that multiple outlets picked up deserves benefit of the doubt over your own taste.

STORIES:
{chr(10).join(lines)}

Return ONLY JSON: {{"scores": [{{"i": <index>, "interest": <0-10>}}, ...]}} — one entry per story, all {len(stories)} of them."""
    try:
        from write import CHEAP, call_claude
        r = call_claude(prompt, schema=JUDGE_SCHEMA, model=CHEAP)  # token diet Aug 8: taste gate stays, Haiku is enough for 0-10 scoring
        got = {x["i"]: x["interest"] for x in r["scores"]
               if 0 <= x.get("i", -1) < len(stories)}
    except Exception as e:
        print(f"interest judge failed ({e}) — mechanical ranking stands", file=sys.stderr)
        got = {}
    for i, s in enumerate(stories):
        s["interest"] = got.get(i, 5)  # neutral on any miss


def main(out_path="stories.json"):
    """X-WATCHLIST ONLY (owner order Aug 3): the entire story pool comes from
    radar.json, and every moment in it is a viral tweet from an owner-approved
    watchlist-x.json channel (radar_x enforces that twice: server-side from:
    queries + a hard client-side allowlist filter). The old harvesting — RSS
    news feeds, Google News, Reddit, Hacker News — is DELETED, not disabled.
    The boosters below only RE-RANK the X stories with outside crowd signals
    (IG competitor scrape, Google Trends, saturation memory); by construction
    they can never add a story to the pool."""
    stories = []
    radar_boost(stories)   # empty pool in -> every fresh X moment joins as a candidate
    evergreen_boost(stories)  # story-arc/wow-fact bench (owner order Aug 27)
    # HARD source gate, the last line of defense: any story whose src is not
    # an x: handle dies here — even if a booster or future code ever tries
    # to inject one, it cannot reach stories.json.
    before = len(stories)
    stories = [s for s in stories if (s.get("src") or "").startswith("x:")]
    if len(stories) != before:
        print(f"source gate: dropped {before - len(stories)} non-X stories",
              file=sys.stderr)
    market_boost(stories)  # crowd signal: IG competitors + reddit scores (re-rank only)
    trends_boost(stories)  # crowd signal: mainstream-America search wave (re-rank only)
    saturation(stories)    # dead inventory: IG audience saw it days ago
    stories = collapse(stories)  # one version per story, best score survives

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
        # x.com is a login wall — a moment either carries its own media
        # image from the tweet or ships imageless (the gen ladder covers it)
        s.setdefault("image", None)
    json.dump(top, open(out_path, "w"), indent=1)
    print(f"{len(stories)} X-watchlist candidates, {len(finalists)} judged, "
          f"top {len(top)} -> {out_path}", file=sys.stderr)
    for s in top[:10]:
        print(f"  {s['score']:6.1f}  int:{s['interest']}  {s.get('src', '?'):<20}"
              f"  {s['title'][:70]}", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "stories.json")
