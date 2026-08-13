#!/usr/bin/env python3
"""X/Twitter arm of the Demand Radar (Module 1 Tier 1 — where AI virality is
born; owner call Jul 29: third-party API lane, not the $200/mo official tier,
and "we dont need news on the minute" -> slow cadence).

Provider: twitterapi.io — $0.15 per 1K tweets, pay-as-you-go, no monthly
minimum (verified Jul 29). Header X-API-Key. QPS scales with credit balance
(unfunded = 1 req / 5s — the 6s pacing below).

WATCHLIST NET ONLY (owner order Aug 3 — the Queen Elizabeth and Mario Lopez
disasters both rode in through the old WIDE NET topic searches, from accounts
the owner never approved: @seiyaposting, @yashar. Owner: "i want to take the
data ONLY from the channels i personally approved and from nothing else").
watchlist-x.json lanes chunked into "(from:a OR from:b ...) min_faves:1000"
batches — the filter runs on X's servers and we only pay for tweets that are
ALREADY viral. No lang:en (curated accounts; keeps media-only tweets,
lang=und). A HARD allowlist filter re-checks every moment (fresh AND cached)
against watchlist-x.json handles, so nothing outside the approved channels
can reach radar.json even via an old cache or an API quirk.
Junk gate (bare links, one-word takes) + per-account cap keep one loud voice
from flooding the radar (first poll: Elon filled 10 of 12 slots). Ranking =
raw likes/hour.

Spend is hard-capped by a monthly read ledger (x-used.json, ~$6/mo ceiling).
Never scheduled itself: radar.py calls harvest() every run, but a fresh poll
happens at most every POLL_EVERY_H hours — between polls the last harvest
(x-moments.json) is re-served with ages advanced. Fails open everywhere: no
key / over budget / network down -> cached or [] and the slot STARVES loudly
(alert_dead GitHub issue) — with the wide net and Reddit gone, there is no
other source to stand alone."""
import json, os, re, sys, time, urllib.parse, urllib.request
from datetime import datetime

# Politics blocklist (radar.py imports this module lazily inside main(), so
# the reverse import is cycle-safe). First funded poll proved the need: a
# Tommy Robinson culture-war video rode min_faves floors into the radar —
# engagement floors filter for VIRAL, not for ON-BRAND.
from radar import political

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
                           # crowd's emotional angle for captions/briefs)
N_PER_ACCOUNT = 2          # one loud account never fills the radar
N_GUIDE = 4                # reserved guide slots (owner order Aug 4: "find the
                           # viral guides on twitter... it is much better and
                           # more viral" — edu.py builds its carousel on the
                           # most viral watchlist guide instead of inventing
                           # a topic). Same watchlist-only net, no new sources.
N_THREAD_MINE = 3          # top guide moments get the author's OWN thread
                           # fetched (the head tweet is just the promise —
                           # the self-reply chain holds the actual guide, and
                           # edu.py runs in CI with no X key, so the content
                           # must ride inside radar.json)

# WIDE GUIDE NET (owner order Aug 10: "we must take all guides from twitter
# api. ALL viral things... it can be [from] the last 2 weeks or a month —
# since it is a guide"). This reopens topic search for GUIDES ONLY — the
# Aug 3 wide-net ban stands for news, where junk and politics rode in.
# Guides are quadruple-filtered: server-side floor + guide regex + AI
# context + politics gate, and they feed ONLY the guide pool (radar.py
# strips them before radar.json), never the news radar.
GUIDE_SEARCH_EVERY_H = 24  # once/day; ~80 reads (~$0.015/day)
GUIDE_SEARCH_FLOOR = 2000  # proven-viral only — higher bar than watchlist
GUIDE_SEARCH_AGE_D = 21    # guides stay postable for weeks
N_WIDE_GUIDE = 16          # top wide guides per day, 1/account
# Aug 13 pool-exhaustion post-mortem: the same 3 fixed queries over the same
# 21-day window returned the same top tweets every day — after day one the
# net caught ~nothing new while edu.py consumes 3-7 guides/day (reel/news
# fallback carousels also land on edu), so the pool ran dry and the writer
# self-invented "6 prompts that..." formula posts. Rotate 4 of these 9
# phrasings daily (stride 4, gcd(4,9)=1 → a different set every day, full
# coverage every 9 days) so each day surfaces a different top-of-X.
GUIDE_QUERIES = (
    '("ChatGPT prompts" OR "AI prompts" OR "Claude prompts" OR "AI tools")',
    '("how to use AI" OR "AI cheat sheet" OR "free AI course" OR "AI course")',
    '("AI agents" OR "AI automation" OR ChatGPT) '
    '("here\'s how" OR "step by step" OR ways)',
    '("AI side hustle" OR "make money with AI" OR "AI for business") '
    '(how OR ways OR steps OR tools)',
    '("Claude Code" OR Cursor OR "AI coding" OR "vibe coding") '
    '(how OR tips OR tools OR guide)',
    '(Gemini OR NotebookLM OR Perplexity OR Grok) '
    '(prompts OR tricks OR "how to" OR features)',
    '("AI video" OR "AI images" OR Midjourney OR Veo OR Sora) '
    '(how OR ways OR tools OR free)',
    '(automate OR n8n OR Zapier OR "no code") (AI OR ChatGPT OR agents) '
    '(how OR guide OR tutorial)',
    '("use ChatGPT" OR "use Claude" OR "use AI") '
    '(marketing OR productivity OR studying OR writing)',
)

# What counts as a guide: a teaching promise, not a news event. Numbered-list
# promises ("10 insane ways...", "5 free tools..."), how-to framing, cheat
# sheets, free courses — AND it must be about AI/tech tools (first live poll
# Aug 4: bare "how to" flagged a Paris pickpocket video from MarioNawfal).
# Remaining false positives are cheap — edu.py's writer is told to ignore
# anything that isn't genuinely teachable.
GUIDE_RE = re.compile(
    r"(?i)\b\d+\s+(?:\w+[- ]){0,2}(ways|things|tools|apps|sites|websites"
    r"|prompts|tips|tricks|use ?cases|examples|features|skills|hacks|secrets"
    r"|lessons|courses)\b"
    r"|\bhow to\b|\bhere'?s how\b|\bstep[- ]by[- ]step\b|\bcheat ?sheet\b"
    r"|\bmasterclass\b|\btutorial\b|\bfree (?:\w+ )?(course|certification)")
AI_CONTEXT_RE = re.compile(
    r"(?i)\bAI\b|chat\s?gpt|claude|gemini|copilot|openai|anthropic|\bgpt\b"
    r"|gpt-?\d|\bllms?\b|midjourney|\bprompts?\b|\bagents?\b|automat"
    r"|\bcoding\b|\bapp\b|n8n|deepseek|grok|perplexity|notebooklm")


def _is_guide(text):
    return bool(GUIDE_RE.search(text) and AI_CONTEXT_RE.search(text))


# Wide-net-only bar (first wide poll Aug 10: a buried "how to" let in a news
# story, a MoonPay ad and an exam-tragedy thread). Anonymous all-of-X needs a
# STRONG guide signal: a numbered-list promise / cheat sheet / tutorial
# anywhere, or how-to framing IN THE HOOK (first 80 chars) — real guide
# tweets lead with it, junk buries it mid-story.
WIDE_STRONG_RE = re.compile(
    r"(?i)\b\d+\s+(?:\w+[- ]){0,2}(ways|things|tools|apps|sites|websites"
    r"|prompts|tips|tricks|use ?cases|examples|features|skills|hacks|secrets"
    r"|lessons|courses)\b"
    r"|\bstep[- ]by[- ]step\b|\bcheat ?sheet\b|\bmasterclass\b|\btutorial\b"
    r"|\bfree (?:\w+ )?(course|certification)")


def _is_wide_guide(text):
    return bool(WIDE_STRONG_RE.search(text)
                or re.search(r"(?i)\bhow to\b|\bhere'?s how\b", text[:80]))

# ISRAEL NEWS LANE (owner order Aug 10: "pull from twitter api the most viral
# news in israel that are relevant to israel... and then write the israeli
# news from twitter api and viral score only in the hebrew channel"). Scope
# owner-confirmed same day: AI/tech Israel ONLY — war/politics NEVER post,
# the Decart/Musk $7B exit is the model story. Feeds il-news.json exclusively;
# by construction nothing here can reach radar.json (the EN news pool stays
# watchlist-only, Aug 3 order).
IL_HE_FLOOR = 500          # Hebrew Twitter is tiny — 500 likes IS viral there
IL_EN_FLOOR = 2000         # English Israel-tech news competes with all of X
IL_MAX_AGE_H = 48          # IL AI/tech stories are rarer; wider window than
                           # the 36h EN news peak
N_IL = 8                   # pool size, 1 per account
IL_POOL = os.path.join(HERE, "il-news.json")

# War/politics blocklist in HEBREW (owner: "we gotta be carefuul with that").
# The English political() gate can't read Hebrew — without this, war news
# would sail into the IL pool on pure engagement. Bias toward blocking: a
# false positive costs one candidate, a false negative posts war news to a
# tech page.
HEB_POLITICS = re.compile(
    "מלחמ|עזה|חמאס|חטופ|חטיפ|צה[\"״׳']ל|נתניהו|ביבי|הפגנ|בחירות|פיגוע"
    "|חיזבאלל|חות'י|איראן|רקטות|טילים|כיפת ברזל|כנסת|ממשל|מילואים"
    "|לבנון|טרור|הרוג|פצוע|שגריר|סנקציות")

# ENGLISH war gate for the IL lane, and unlike radar.political() it has NO
# AI-collision exemption — first live test (Aug 10) let in "Iran: 10,000
# cheap AI suicide drones" and a genocide-discourse thread BECAUSE they name
# AI. On the Israel search, military AI is still war content: never post
# (owner scope: AI/tech Israel only, the Decart exit is the model).
# "strike on" not \bstrike\b — "strike a deal" is exactly our model story.
IL_WAR_EN = re.compile(
    r"(?i)\bwar\b|\bgaza\b|\bhamas\b|hezbollah|\bidf\b|\biran(ian)?\b"
    r"|missile|rocket|air ?strike|strike[sd]? on\b|ceasefire|hostage"
    r"|genocide|\bterror|\bmilitary\b|netanyahu|west bank|settler|intifada"
    r"|zionis|antisemit|jihad|\bbombing\b|\bkilled\b|casualt|soldier")

# AI/tech context, Hebrew + English + Hebrew transliterations of the brands
# (Israeli tweets mix scripts freely: "אנבידיה" and "Nvidia" both appear).
IL_TECH_RE = re.compile(
    r"(?i)\bAI\b|ChatGPT|OpenAI|Claude|Gemini|Nvidia|Tesla|Intel|\bWiz\b"
    r"|Mobileye|בינה מלאכותית|סטארט[- ]?אפ|אקזיט|הייטק|סייבר|שבב|רובוט"
    r"|אפליקצי|אנבידיה|אינטל|גוגל|מיקרוסופט|טסלה|מאסק|אלטמן|צוקרברג")


# The wide net (topic searches over ALL of X) is GONE — owner order Aug 3.
# Every query is a watchlist "(from:a OR from:b)" batch; nothing else runs.
BATCH_FLOOR = FLOOR_LIKES  # watchlist batches: floor matches the keep filter
BATCH_SIZE = 18            # from:-OR handles per query (stay under length cap)


def _watch_handles():
    """Approved channels, lowercased — the single source of truth for the
    hard allowlist filter below."""
    try:
        lanes = json.load(open(WATCH))["lanes"]
        return {h.lower() for lane in lanes.values() for h in lane}
    except Exception as e:
        print(f"x radar: no watchlist ({e})", file=sys.stderr)
        return set()


def _approved_only(moments, handles):
    """HARD gate (owner order Aug 3): a moment survives ONLY if its author is
    in watchlist-x.json. Applies to fresh polls AND the served cache, so a
    pre-order cache or an API quirk can never leak an unapproved account."""
    out, dropped = [], []
    for m in moments:
        (out if m.get("sub", "").lower() in handles else dropped).append(m)
    for m in dropped:
        print(f"x radar: DROPPED unapproved @{m.get('sub')}: "
              f"{m.get('title', '')[:60]}", file=sys.stderr)
    return out


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


def _moment(t, now, max_age_h=MAX_AGE_H, floor=FLOOR_LIKES):
    """Tweet object -> radar moment, or None (too old / junk / soft).
    max_age_h: news peaks in 36h, but the wide guide net (owner Aug 10)
    accepts guides weeks old — a guide doesn't expire like a headline.
    floor: Hebrew Twitter is ~1/50th of English — the IL lane viral bar
    sits lower (owner-confirmed Aug 10)."""
    likes = int(t.get("likeCount") or 0)
    ts = _ts(t.get("createdAt") or "")
    if not ts or likes < floor:
        return None
    age_h = max((now - ts) / 3600, 0.5)
    if age_h > max_age_h:
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
            "image": img, "video": vid,
            "guide": _is_guide(bare or text)}


def _cached():
    """Last harvest, ages advanced — stale entries drop out on their own.
    Allowlist-filtered too: a cache written before the Aug 3 watchlist-only
    order may still hold wide-net moments from unapproved accounts."""
    try:
        c = json.load(open(CACHE))
        elapsed_h = (time.time() - c["at"]) / 3600
        out = []
        for m in c["moments"]:
            age = round(m["age_h"] + elapsed_h, 1)
            if age <= MAX_AGE_H:
                out.append({**m, "age_h": age,
                            "vph": round(m["score"] / age, 1)})
        return _approved_only(out, _watch_handles())
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
             "-b", f"{reason}\n\nX is the ONLY content source (owner order "
                   "Aug 3) — posts and reels are STARVING until this is fixed. "
                   "First check: TWITTER_API_KEY in "
                   "~/kestrel/.env (the Jul 31 repo move left keys behind in "
                   "~/yaffeai/.env once already)."],
            capture_output=True, timeout=30)
    except Exception as e:
        print(f"x radar: alert failed too ({e})", file=sys.stderr)


def harvest():
    key = _key()
    if not key:
        print("x radar: no TWITTERAPI_KEY — the ONLY source is offline",
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

    # ONLY watchlist lanes -> "(from:a OR from:b) min_faves:N" batches —
    # server-side floor means we only pay for already-viral tweets, and
    # server-side from: means only owner-approved accounts are ever read
    watch = _watch_handles()
    handles = sorted(watch)
    if not handles:
        alert_dead("watchlist-x.json is missing or empty — the X radar has "
                   "nothing to poll (watchlist-ONLY mode, owner order Aug 3).")
        return []
    batches = [
        "(" + " OR ".join(f"from:{h}" for h in handles[i:i + BATCH_SIZE])
        + f") min_faves:{BATCH_FLOOR}"
        for i in range(0, len(handles), BATCH_SIZE)]

    for i, q in enumerate(batches):
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
        for t in tweets:  # watchlist handles are curated: politics gate yes,
            if str(t.get("id")) in seen_ids:  # topic gate no (keeps media-
                continue                      # only tweets from wow pages)
            seen_ids.add(str(t.get("id")))
            m = _moment(t, now)
            if not m:
                continue
            blob = f"{m['title']} {m.get('selftext') or ''}"
            if political(blob):
                continue
            pool.append(m)
    pool = _approved_only(pool, watch)  # belt over the server-side from:

    if not pool:
        # twitterapi.io soft-fail (seen Aug 3: "success" + zero tweets on
        # EVERY query while account credits were fine). A degraded API must
        # not nuke the cache or burn the 8h poll window: keep last_poll
        # unchanged so the next run retries, serve the last good harvest,
        # and raise the alarm only if that is empty too.
        json.dump(led, open(LEDGER, "w"), indent=1)  # reads still count
        cached = _cached()
        print(f"x radar: 0 tweets from ALL batches — degraded API? serving "
              f"cache ({len(cached)} moments), retrying next run", file=sys.stderr)
        if not cached:
            alert_dead("advanced_search returned 0 tweets for every watchlist "
                       "batch and the cache is empty too — the X lane (the "
                       "ONLY content source) is starving.")
        return cached

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
    # reserved guide lane (owner Aug 4): news out-vphs guides most days, so
    # without reserved slots the guide edu.py wants would get crowded out
    _take(lambda m: m.get("guide"), len(moments) + N_GUIDE)
    _take(lambda m: True, N_MOMENTS)          # rest by raw vph, any kind

    # WIDE GUIDE NET (owner order Aug 10, constants above): all-of-X search
    # for proven-viral AI guides, guide pool only. Runs once a day.
    if now - led.get("last_guide_search", 0) >= GUIDE_SEARCH_EVERY_H * 3600:
        g_since = int(now - GUIDE_SEARCH_AGE_D * 86400)
        wide, wide_accts = [], set()
        day = int(now // 86400)  # rotating slice of the bank (see constants)
        for q in [GUIDE_QUERIES[(day * 4 + k) % len(GUIDE_QUERIES)]
                  for k in range(4)]:
            time.sleep(6)
            try:
                d = _get(key, "/twitter/tweet/advanced_search",
                         query=f"{q} min_faves:{GUIDE_SEARCH_FLOOR} "
                               f"since_time:{g_since}", queryType="Top")
            except Exception as e:
                print(f"  ! x guide search '{q[:40]}': {e}", file=sys.stderr)
                continue
            tweets = d.get("tweets") or []
            led["reads"] += max(len(tweets), 1)
            for t in tweets:
                if str(t.get("id")) in seen_ids:
                    continue
                seen_ids.add(str(t.get("id")))
                m = _moment(t, now, max_age_h=GUIDE_SEARCH_AGE_D * 24)
                if not m or not m.get("guide") or m["sub"] in wide_accts:
                    continue
                blob = f"{m['title']} {m.get('selftext') or ''}"
                if political(blob) or not _is_wide_guide(blob):
                    continue
                wide_accts.add(m["sub"])
                m["wide_guide"] = True
                wide.append(m)
        wide.sort(key=lambda m: -m["score"])
        wide = wide[:N_WIDE_GUIDE]
        led["last_guide_search"] = now
        print(f"wide guide net: {len(wide)} viral guides from all of X",
              file=sys.stderr)
        moments.extend(wide)  # guide pool + thread mining; radar.py strips
                              # wide_guide before writing radar.json

    # ISRAEL NEWS LANE (owner order Aug 10, constants above): two searches per
    # fresh poll (~40 reads, 3x/day ≈ $0.02/day) into il-news.json ONLY —
    # never into the returned moments, so the EN radar can't be contaminated.
    # Triple gate: English politics + Hebrew war/politics + AI/tech context.
    il_since = int(now - IL_MAX_AGE_H * 3600)
    il_pool, il_accts = [], set()
    for q, floor in (
            ('(AI OR ChatGPT OR OpenAI OR "בינה מלאכותית" OR סטארטאפ OR '
             'אקזיט OR הייטק OR אנבידיה OR מאסק) lang:he', IL_HE_FLOOR),
            ('(Israel OR Israeli OR "Tel Aviv") (AI OR startup OR '
             'acquisition OR exit OR Nvidia OR OpenAI OR Intel OR cyber OR '
             'robot)', IL_EN_FLOOR)):
        time.sleep(6)
        try:
            d = _get(key, "/twitter/tweet/advanced_search",
                     query=f"{q} min_faves:{floor} since_time:{il_since}",
                     queryType="Top")
        except Exception as e:
            print(f"  ! x IL search '{q[:40]}': {e}", file=sys.stderr)
            continue
        tweets = d.get("tweets") or []
        led["reads"] += max(len(tweets), 1)
        for t in tweets:
            m = _moment(t, now, max_age_h=IL_MAX_AGE_H, floor=floor)
            if not m or m["sub"] in il_accts:
                continue
            blob = f"{m['title']} {m.get('selftext') or ''}"
            if (political(blob) or HEB_POLITICS.search(blob)
                    or IL_WAR_EN.search(blob)):
                continue
            if not IL_TECH_RE.search(blob):
                continue
            il_accts.add(m["sub"])
            il_pool.append(m)
    # every poll re-searches the whole 48h window, so an empty result means
    # the window is genuinely empty — overwrite, never serve ghosts
    il_pool.sort(key=lambda m: -m["score"])  # viral score ranks the lane
    json.dump({"updated": datetime.now().astimezone().isoformat(),
               "moments": il_pool[:N_IL]}, open(IL_POOL, "w"),
              ensure_ascii=False, indent=1)
    print(f"IL news lane: {len(il_pool)} Israel AI/tech moments -> il-news.json",
          file=sys.stderr)

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

    # guide-thread mining (owner order Aug 4): viral guides are usually
    # threads — the head tweet promises "10 ways...", the author's own
    # replies ARE the 10 ways. conversation_id search returns exactly the
    # author's tweets inside that thread. ~20 reads per guide, ~$0.03/poll.
    for m in sorted([m for m in moments if m.get("guide")],
                    key=lambda m: -m["score"])[:N_THREAD_MINE]:
        time.sleep(6)
        try:
            d = _get(key, "/twitter/tweet/advanced_search",
                     query=f"from:{m['sub']} conversation_id:{m['id']}",
                     queryType="Latest")
        except Exception as e:
            print(f"  ! x thread {m['id']}: {e}", file=sys.stderr)
            continue
        tweets = d.get("tweets") or []
        led["reads"] += max(len(tweets), 1)
        own = [t for t in tweets if str(t.get("id")) != m["id"]]
        own.sort(key=lambda t: _ts(t.get("createdAt") or "") or 0)
        parts = []
        for t in own:
            body = re.sub(r"https?://\S+", "", t.get("text") or "").strip()
            if len(body) >= 15:
                parts.append(" ".join(body.split())[:600])
            if len(parts) >= 10:
                break
        if parts:
            m["thread"] = parts

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
