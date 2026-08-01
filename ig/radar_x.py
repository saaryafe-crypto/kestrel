#!/usr/bin/env python3
"""X/Twitter arm of the Demand Radar (Module 1 Tier 1 — where AI virality is
born; owner call Jul 29: third-party API lane, not the $200/mo official tier,
and "we dont need news on the minute" -> slow cadence).

Provider: twitterapi.io — $0.15 per 1K tweets, pay-as-you-go, no monthly
minimum (verified Jul 29). Header X-API-Key. QPS scales with credit balance
(unfunded = 1 req / 5s — the 6s pacing below).

ONE MECHANISM, TWO NETS — everything is advanced_search with engagement
floors, so the filter runs on X's servers and we only pay for tweets that are
ALREADY viral (owner audit Jul 29: per-account polling paid to read ~95% junk
and capped the watchlist at 26; batched from:-OR queries lift it to 70+):
  1. WIDE NET — topic searches ("AI min_faves:5000 filter:videos", space,
     tech/science lanes): viral moments from ANY account on X. Same move the
     pros make (LADbible's in-house LAD RADAR, NewsWhip for newsrooms).
  2. WATCHLIST NET — watchlist-x.json lanes (labs/founders, clip posters,
     robots, space, breaking-news pages, wow-aggregators) chunked into
     "(from:a OR from:b ...) min_faves:1000" batches: story-is-the-person
     tweets + pre-harvested virality from X-native aggregator pages. No
     lang:en here (curated accounts; keeps media-only tweets, lang=und).
Junk gate (bare links, one-word takes) + per-account cap keep one loud voice
from flooding the radar (first poll: Elon filled 10 of 12 slots). Ranking =
raw likes/hour, same doctrine as Reddit.

Spend is hard-capped by a monthly read ledger (x-used.json, ~$6/mo ceiling).
Never scheduled itself: radar.py calls harvest() every run, but a fresh poll
happens at most every POLL_EVERY_H hours — between polls the last harvest
(x-moments.json) is re-served with ages advanced. Fails open everywhere: no
key / over budget / network down -> cached or [] and Reddit stands alone."""
import json, os, re, sys, time, urllib.parse, urllib.request
from datetime import datetime

# One topic doctrine, one politics blocklist, both lanes (radar.py imports
# this module lazily inside main(), so the reverse import is cycle-safe).
# First funded poll proved the need: a Tommy Robinson culture-war video and a
# football tweet rode min_faves floors into the radar — engagement floors
# filter for VIRAL, not for ON-BRAND.
from radar import TOPIC, political

# TOPIC covers the AI/robot doctrine; the wide-net TEXT lanes also search
# quantum/fusion/space/science, so the X gate accepts those tokens too. The
# principle: X matches keywords inside quoted tweets and alt text (how a
# football tweet rode the tech search), so a wide-net keep must show its
# keyword in the VISIBLE text we would publish.
TOPIC_X = re.compile(
    r"\bquantum|\bsemiconductor|\bfusion\b|\bnasa\b|\brocket|\bbooster"
    r"|\bspace|\bscience|\btech\b|\btechnolog|breakthrough|\bdiscover"
    # markets lane (Aug 1): finance keeps must show their keyword in the
    # publishable text, same rule as every other wide-net lane
    r"|\bstocks?\b|\bnasdaq|\bwall st|\bhedge fund|\bearnings|\bbuffett"
    r"|\bipo\b|\bmarket cap|\binvestor", re.I)

HERE = os.path.dirname(os.path.abspath(__file__))
WATCH = os.path.join(HERE, "watchlist-x.json")
CACHE = os.path.join(HERE, "x-moments.json")
LEDGER = os.path.join(HERE, "x-used.json")

POLL_EVERY_H = 8           # 3 fresh polls/day (owner Jul 29: X is the main
                           # source now; ~$3/mo at measured ~225 reads/poll)
MAX_AGE_H = 36             # older tweets already peaked everywhere
FLOOR_LIKES = 1000         # junk filter; ranking itself is likes/hour
CAP_READS_MONTH = 33_000   # hard cap ~= $5/mo at $0.15/1K reads (owner
                           # topped up $10 for 2 months, Jul 29)
N_MOMENTS = 16
N_VIDEO = 6                # reserved video slots — text tweets out-vph clips
                           # 5-10x (audit Jul 29: 1 video in 12 moments), so
                           # videos get their own lane or reels starve
N_REPLY_MINE = 3           # top video moments get their replies mined (the
                           # crowd's emotional angle, parity with reddit lane)
N_PER_ACCOUNT = 2          # one loud account never fills the radar

# The wide net: viral moments from ANY account. VIDEO searches run at lower
# floors (a 2K-like Unitree clip 2h old is reel gold; a 20K-like one-liner is
# not) and feed the reserved video slots. Operators verified against
# twitterapi.io docs (since_time: = unix seconds). lang:en because bare "AI"
# matches pt/ja interjections ("ai gente") — first live poll proved it.
SEARCHES_VIDEO = [
    "AI lang:en min_faves:3000 filter:videos",
    "(robot OR robotics OR humanoid OR drone) lang:en min_faves:2000 filter:videos",
    "(SpaceX OR Starship OR NASA OR rocket OR booster) lang:en min_faves:3000 filter:videos",
]
SEARCHES_TEXT = [
    "(ChatGPT OR OpenAI OR Claude OR Gemini OR Grok OR DeepSeek) lang:en min_faves:10000",
    "(quantum OR semiconductor OR fusion OR breakthrough OR discovery) lang:en min_faves:10000",
    "AI lang:en min_faves:20000",
    "(tech OR technology OR science OR space) lang:en min_faves:30000",
    # investment world (owner Aug 1: Wall St drama — Citadel/Situational
    # Awareness class stories, Buffett): floor between the AI (10K) and
    # catch-all (30K) lanes — finance X is loud, but we only want the
    # stories everyone will be talking about tomorrow
    "(stocks OR \"Wall Street\" OR \"hedge fund\" OR Buffett OR Nasdaq"
    " OR earnings) lang:en min_faves:15000",
]
SEARCHES = SEARCHES_VIDEO + SEARCHES_TEXT
BATCH_FLOOR = FLOOR_LIKES  # watchlist batches: floor matches the keep filter
BATCH_SIZE = 18            # from:-OR handles per query (stay under length cap)


def _key():
    names = ("TWITTERAPI_KEY", "TWITTER_API_KEY")  # owner saved the 2nd form
    for n in names:
        if os.environ.get(n):
            return os.environ[n]
    try:  # root .env, same home as the other paid keys
        for line in open(os.path.join(os.path.dirname(HERE), ".env")):
            k, _, v = line.strip().partition("=")
            if k in names and v:
                return v
    except Exception:
        pass
    return None


def _get(key, path, **params):
    """One API call with the unfunded-tier pacing + one 429 retry."""
    url = (f"https://api.twitterapi.io{path}?"
           + urllib.parse.urlencode(params))
    for attempt in range(2):
        try:
            req = urllib.request.Request(url, headers={"X-API-Key": key})
            return json.loads(urllib.request.urlopen(req, timeout=25).read())
        except Exception as e:
            if "429" in str(e) and attempt == 0:
                time.sleep(15)
                continue
            raise


def _ts(created):
    """createdAt in either classic twitter or ISO form -> epoch seconds."""
    for fmt in ("%a %b %d %H:%M:%S %z %Y", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(created, fmt).timestamp()
        except Exception:
            continue
    return None


def _video_url(media):
    for m in media:
        if m.get("type") in ("video", "animated_gif"):
            vs = [v for v in (m.get("video_info") or {}).get("variants", [])
                  if v.get("bitrate")]
            if vs:
                return max(vs, key=lambda v: v["bitrate"])["url"]
    return None


def _moment(t, now):
    """Tweet object -> radar moment, or None (too old / junk / soft)."""
    likes = int(t.get("likeCount") or 0)
    ts = _ts(t.get("createdAt") or "")
    if not ts or likes < FLOOR_LIKES:
        return None
    age_h = max((now - ts) / 3600, 0.5)
    if age_h > MAX_AGE_H:
        return None
    text = " ".join((t.get("text") or "").split())
    if not text or text.startswith("RT @"):
        return None
    media = ((t.get("extendedEntities") or {}).get("media")
             or (t.get("entities") or {}).get("media") or [])
    img = next((m.get("media_url_https") for m in media
                if m.get("type") == "photo"), None)
    vid = _video_url(media)
    # junk gate: a bare link or a one-word take ("Cool") is a reaction,
    # not a moment — unless it carries its own media
    bare = re.sub(r"https?://\S+", "", text).strip()
    if len(bare) < 15 and not (img or vid):
        return None
    h = (t.get("author") or {}).get("userName") or "unknown"
    return {"id": str(t.get("id")),
            "title": (bare or text)[:220], "sub": h, "where": f"@{h} on X",
            "unit": "likes",
            # full tweet text -> write.py picks radar.selftext up as the
            # article body (x.com links are a login wall, unfetchable from CI)
            "selftext": bare if len(bare) >= 15 else None,
            "permalink": t.get("url") or f"https://x.com/{h}/status/{t.get('id')}",
            "outlink": None, "score": likes,
            "comments_n": int(t.get("replyCount") or 0),
            "views": int(t.get("viewCount") or 0),
            "age_h": round(age_h, 1), "vph": round(likes / age_h, 1),
            "image": img, "video": vid}


def _cached():
    """Last harvest, ages advanced — stale entries drop out on their own."""
    try:
        c = json.load(open(CACHE))
        elapsed_h = (time.time() - c["at"]) / 3600
        out = []
        for m in c["moments"]:
            age = round(m["age_h"] + elapsed_h, 1)
            if age <= MAX_AGE_H:
                out.append({**m, "age_h": age,
                            "vph": round(m["score"] / age, 1)})
        return out
    except Exception:
        return []


def alert_dead(reason):
    """Owner directive Aug 1 ('the x radar is the most important... it is dead
    and we do not know about it'): a dead X lane is NEVER silent. One GitHub
    issue fires the moment it dies (deduped against open issues so the 2h
    radar cadence can't spam). Fails open — alerting must never break radar."""
    import subprocess
    title = "X radar DEAD — viral X lane offline"
    try:
        open_ = subprocess.run(
            ["gh", "issue", "list", "-R", "saaryafe-crypto/kestrel",
             "--state", "open", "--search", f'"{title}" in:title',
             "--json", "title"],
            capture_output=True, text=True, timeout=30).stdout
        if title in (open_ or ""):
            return
        subprocess.run(
            ["gh", "issue", "create", "-R", "saaryafe-crypto/kestrel",
             "-t", title,
             "-b", f"{reason}\n\nReels and radar stories are running on Reddit "
                   "alone until this is fixed. First check: TWITTER_API_KEY in "
                   "~/kestrel/.env (the Jul 31 repo move left keys behind in "
                   "~/yaffeai/.env once already)."],
            capture_output=True, timeout=30)
    except Exception as e:
        print(f"x radar: alert failed too ({e})", file=sys.stderr)


def harvest():
    key = _key()
    if not key:
        print("x radar: no TWITTERAPI_KEY — skipping (reddit radar stands alone)",
              file=sys.stderr)
        alert_dead("No TWITTER_API_KEY/TWITTERAPI_KEY found in the environment "
                   "or ~/kestrel/.env — the X radar cannot poll.")
        return []
    try:
        led = json.load(open(LEDGER))
    except Exception:
        led = {}
    month = datetime.now().strftime("%Y-%m")
    if led.get("month") != month:
        led = {"month": month, "reads": 0, "last_poll": 0}
    if led["reads"] >= CAP_READS_MONTH:
        print(f"x radar: monthly read cap hit ({led['reads']:,}) — serving cache",
              file=sys.stderr)
        return _cached()
    if time.time() - led.get("last_poll", 0) < POLL_EVERY_H * 3600:
        return _cached()

    now, pool, seen_ids = time.time(), [], set()
    since = int(now - MAX_AGE_H * 3600)

    # net 2 queries: watchlist lanes -> "(from:a OR from:b) min_faves:N"
    # batches — server-side floor means we only pay for already-viral tweets
    try:
        lanes = json.load(open(WATCH))["lanes"]
        handles = [h for lane in lanes.values() for h in lane]
    except Exception as e:
        print(f"x radar: no watchlist ({e})", file=sys.stderr)
        handles = []
    batches = [
        "(" + " OR ".join(f"from:{h}" for h in handles[i:i + BATCH_SIZE])
        + f") min_faves:{BATCH_FLOOR}"
        for i in range(0, len(handles), BATCH_SIZE)]

    for i, q in enumerate(SEARCHES + batches):
        if i:
            time.sleep(6)  # unfunded-tier QPS: 1 req / 5s
        try:
            d = _get(key, "/twitter/tweet/advanced_search",
                     query=f"{q} since_time:{since}", queryType="Top")
        except Exception as e:
            print(f"  ! x search '{q[:40]}': {e}", file=sys.stderr)
            continue
        tweets = d.get("tweets") or []
        led["reads"] += max(len(tweets), 1)
        wide = i < len(SEARCHES)  # watchlist handles are curated: politics
        for t in tweets:          # gate yes, topic gate no (keeps media-only
            if str(t.get("id")) in seen_ids:  # tweets from meme/wow pages)
                continue
            seen_ids.add(str(t.get("id")))
            m = _moment(t, now)
            if not m:
                continue
            blob = f"{m['title']} {m.get('selftext') or ''}"
            if political(blob) or (
                    wide and not (TOPIC.search(blob) or TOPIC_X.search(blob))):
                continue
            pool.append(m)

    pool.sort(key=lambda m: -m["vph"])
    moments, taken, per_acct = [], set(), {}

    def _take(pred, cap):
        for m in pool:  # one loud voice never fills the radar
            if len(moments) >= cap:
                return
            if m["id"] in taken or not pred(m):
                continue
            if per_acct.get(m["sub"], 0) >= N_PER_ACCOUNT:
                continue
            per_acct[m["sub"]] = per_acct.get(m["sub"], 0) + 1
            taken.add(m["id"])
            moments.append(m)

    _take(lambda m: m.get("video"), N_VIDEO)  # reserved video lane first
    _take(lambda m: True, N_MOMENTS)          # rest by raw vph, any kind

    # crowd-emotion mining, reddit-lane parity: top replies on the best video
    # moments = thousands of people voting on which emotion the clip triggers
    # (reel.py aims the overlay title at it). ~20 reads per moment.
    for m in [m for m in moments if m.get("video")][:N_REPLY_MINE]:
        time.sleep(6)
        try:
            d = _get(key, "/twitter/tweet/replies/v2",
                     tweetId=m["id"], queryType="Likes")
        except Exception as e:
            print(f"  ! x replies {m['id']}: {e}", file=sys.stderr)
            continue
        replies = d.get("tweets") or []
        led["reads"] += max(len(replies), 1)
        replies.sort(key=lambda r: -(r.get("likeCount") or 0))
        tc = []
        for rp in replies:
            # endpoint echoes the parent tweet as a "reply" by its own author
            if ((rp.get("author") or {}).get("userName") or "") == m["sub"]:
                continue
            body = re.sub(r"https?://\S+|@\w+", "", rp.get("text") or "").strip()
            if len(body) >= 15:
                tc.append(body[:240])
            if len(tc) >= 5:
                break
        if tc:
            m["top_comments"] = tc

    led["last_poll"] = now
    json.dump(led, open(LEDGER, "w"), indent=1)
    json.dump({"at": now, "moments": moments}, open(CACHE, "w"), indent=1)
    print(f"x radar: {len(moments)} moments ({len(pool)} candidates) | "
          f"{led['reads']:,} reads this month "
          f"(~${led['reads'] * 0.15 / 1000:.2f} of "
          f"${CAP_READS_MONTH * 0.15 / 1000:.2f} cap)", file=sys.stderr)
    return moments


if __name__ == "__main__":
    for m in harvest():
        print(f"  {m['vph']:>7}/hr {m['score']:>7} likes {m['age_h']:>5}h"
              f"  @{m['sub']:<18} {m['title'][:60]}", file=sys.stderr)
