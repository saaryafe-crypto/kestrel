#!/usr/bin/env python3
"""Demand Radar: Reddit breakout detector (runs on the Mac, launchd, every 2h).

The strategy shift (owner audit, Jul 29): stop predicting virality, HARVEST it.
The internet A/B tests millions of moments a day for free; this module catches
the winners in the first hours of breakout — score VELOCITY (upvotes/hour vs
the subreddit's own baseline), not raw totals. A 4,000-upvote post that is 30
hours old already peaked everywhere; a 900-upvote post that is 2 hours old is
a rocket lifting off.

Two source tiers:
  CORE  — AI-native subs: everything qualifies.
  CROSS — giant normie subs (r/interestingasfuck...): only AI/robot/tech posts
          pass the topic gate. A moment that escapes the AI bubble into a
          normie sub is PRE-PROVEN for the exact audience a viral IG page needs.

Top-comment mining (the sharpest edge here): the top comments on a viral post
are thousands of humans voting on which EMOTION the moment triggers. They ride
into radar.json and reach the hook writer as the validated angle.

Source route: old.reddit HTML with a browser UA — the .json API died May 2026
(market.py learned this first); HTML from a residential IP still carries real
scores, timestamps, comment counts, and permalinks. Ranking = raw upvotes/hour
(owner call Jul 29: no per-sub baseline ratios — a bootstrapped baseline is a
bad indicator, absolute velocity + per-sub floors are honest). Fails open
everywhere — scout.py treats a missing/stale radar.json as "no boost".
Writes radar.json, commits, pushes (market.py pattern)."""
import html as htmllib
import json, os, re, subprocess, sys, time, urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "radar.json")

BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# sub -> absolute upvote floor (junk filter; ranking itself is upvotes/hour).
# Core = AI-native subs, everything on-topic by definition.
CORE = {"ChatGPT": 300, "OpenAI": 250, "singularity": 300,
        "ArtificialInteligence": 250, "artificial": 200, "ClaudeAI": 150,
        "LocalLLaMA": 250, "robotics": 200,
        "StableDiffusion": 200, "midjourney": 150, "aivideo": 100}
# general subs — topic gate mandatory (first run proved it: ungated
# r/technology flooded the top 20 with politics-outrage posts).
# The escape subs are the key filter: AI/robot content that breaks out in a
# normie sub is PRE-PROVEN for the exact audience a viral IG page needs.
# antiwork/jobs = where "AI took my job" confessionals break.
CROSS = {"technology": 800, "Futurology": 500,
         "interestingasfuck": 3000, "Damnthatsinteresting": 3000,
         "nextfuckinglevel": 3000, "BeAmazed": 2000, "oddlyterrifying": 1500,
         "funny": 5000, "videos": 1500, "pics": 3000,
         "blackmagicfuckery": 1500, "Unexpected": 3000,
         "mildlyinfuriating": 2500, "gadgets": 600,
         "EngineeringPorn": 800, "antiwork": 2000, "jobs": 800}

TOPIC = re.compile(
    r"\ba\.?i\b|artificial intel|chatgpt|\bgpt|openai|claude|anthropic|gemini"
    r"|grok|deepfake|neural|machine learn|humanoid|robot|autonomous|self.driv"
    r"|optimus|boston dynamics|unitree|figure 0\d|\bllm\b|algorithm|automat"
    r"|drone|starship|spacex|neuralink|data cent|waymo|\bsora\b|midjourney"
    r"|diffusion|dall.e|laid off|layoff|my job|replaced by", re.I)

# Politics/outrage leak plug (audit Jul 29: "teacher arrested for clapping",
# "Willie Nelson urges Americans", pepper-spray drones slipped through on
# 'data cent'/'drone' tokens). A single-word TOPIC hit inside a political
# outrage story is not our content — it wastes radar slots and reads
# off-brand. Deliberately narrow: robotaxi-vs-cops and AI-drama stay in.
POLITICS = re.compile(
    r"\barrest|\bprotest|\bsenat|\bcongress\b|\blawmaker|\belection"
    r"|\bgovernor\b|\bmayor\b|\bwhite house|\btrump\b|\bbiden\b|\brepublican"
    r"|\bdemocrat|\burges\b|\bshooting|\bshooter|\bimmigra|\bdeport|\btariff"
    r"|\bracis|\bmigrant",
    re.I)

# Politics×AI COLLISION exemption (owner Aug 1: "if something with politics
# and ai collides we also need to share that" — governments disabling models,
# AI regulation drama). A politics hit passes IF the text names AI explicitly.
# Deliberately narrower than TOPIC: 'drone'/'data cent' tokens are how the
# pepper-spray-drone politics story leaked in Jul 29 — those do NOT exempt.
AI_CORE = re.compile(
    r"\ba\.?i\b|artificial intel|chatgpt|openai|claude|anthropic|gemini"
    r"|\bgrok\b|deepseek|\bllm\b|deepfake", re.I)


def political(text):
    """True = off-brand politics; AI-collision stories stay in."""
    return bool(POLITICS.search(text)) and not AI_CORE.search(text)

MAX_AGE_H = 30       # older = the wave already broke on IG too
N_MOMENTS = 24       # radar.json cap (raised Jul 29: X sends up to 16
                     # high-vph moments; reddit breakouts keep >=8 slots)
N_COMMENTS_FETCH = 15  # top-N moments get their comments + selftext mined


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA})
    return urllib.request.urlopen(req, timeout=25).read().decode("utf-8", "ignore")


def strip_tags(s):
    return htmllib.unescape(re.sub(r"<[^>]+>", " ", s)).strip()


def harvest_sub(sub, floor, gate):
    """One sub's /hot HTML -> qualifying posts."""
    posts = []
    try:
        page = get(f"https://old.reddit.com/r/{sub}/?limit=40")
    except Exception as e:
        print(f"  ! r/{sub}: {e}", file=sys.stderr)
        return posts
    now = time.time()
    for chunk in page.split('<div class=" thing ')[1:]:
        chunk = chunk[:4000]
        classes = chunk.split('"', 1)[0]
        if "promoted" in classes or "stickied" in classes or "over18" in classes:
            continue
        sc = re.search(r'data-score="(\d+)"', chunk)
        ts = re.search(r'data-timestamp="(\d+)"', chunk)
        pl = re.search(r'data-permalink="([^"]+)"', chunk)
        ti = re.search(r'<a class="title[^"]*"[^>]*href="([^"]+)"[^>]*>([^<]+)</a>', chunk)
        if not (sc and ts and pl and ti):
            continue
        score = int(sc.group(1))
        age_h = max((now - int(ts.group(1)) / 1000) / 3600, 0.5)
        if age_h > MAX_AGE_H:
            continue
        vph = score / age_h
        title = htmllib.unescape(ti.group(2)).strip()
        if score < floor:
            continue
        if gate and (not TOPIC.search(title) or political(title)):
            continue
        url = htmllib.unescape(ti.group(1))
        img = url if re.match(r"https?://i\.redd\.it/", url) else None
        video = url if re.match(r"https?://v\.redd\.it/", url) else None
        outlink = url if (url.startswith("http")
                          and not re.search(r"redd\.it|reddit\.com", url)) else None
        cn = re.search(r'data-comments-count="(\d+)"', chunk)
        posts.append({
            "title": title,
            "sub": sub,
            "where": f"r/{sub}",
            "unit": "upvotes",
            "permalink": "https://old.reddit.com" + pl.group(1),
            "outlink": outlink,
            "score": score,
            "comments_n": int(cn.group(1)) if cn else 0,
            "age_h": round(age_h, 1),
            "vph": round(vph, 1),
            "image": img,
            "video": video,
        })
    return posts


def mine_thread(permalink):
    """Comments page HTML -> (selftext, top comments by score).
    The top comments are the crowd's vote on the moment's emotional angle."""
    try:
        page = get(permalink + "?sort=top&limit=40")
    except Exception as e:
        print(f"  ! thread {permalink[:60]}: {e}", file=sys.stderr)
        return None, []
    selftext = None
    ex = re.search(r'<div class="expando".*?<div class="md">(.*?)</div>', page, re.S)
    if ex:
        selftext = strip_tags(ex.group(1))[:1500] or None
    comments = []
    for chunk in page.split('data-type="comment"')[1:]:
        chunk = chunk[:6000]
        au = re.search(r'data-author="([^"]+)"', chunk)
        if not au or au.group(1) == "AutoModerator":
            continue
        sc = re.search(r'<span class="score unvoted"[^>]*title="(\d+)"', chunk)
        bd = re.search(r'<div class="md">(.*?)</div>', chunk, re.S)
        if not (sc and bd):
            continue
        body = re.sub(r"\s+", " ", strip_tags(bd.group(1)))
        if body and body not in ("[deleted]", "[removed]"):
            comments.append({"score": int(sc.group(1)), "body": body[:240]})
    comments.sort(key=lambda c: -c["score"])
    return selftext, [c["body"] for c in comments[:5]]


def main():
    moments, seen = [], set()
    for sub, floor in {**CORE, **CROSS}.items():
        posts = harvest_sub(sub, floor, gate=sub in CROSS)
        for p in posts:
            key = re.sub(r"\W+", "", p["title"].lower())[:60]
            if key in seen:  # crossposts: first (higher-tier) sub wins
                continue
            seen.add(key)
            moments.append(p)
        print(f"r/{sub}: {len(posts)} qualifying", file=sys.stderr)
        time.sleep(3)

    # X lane (radar_x polls at most 2x/day, serves its cache between polls)
    try:
        import radar_x
        for m in radar_x.harvest():
            key = re.sub(r"\W+", "", m["title"].lower())[:60]
            if key not in seen:
                seen.add(key)
                moments.append(m)
    except Exception as e:
        print(f"x radar failed ({e}) — reddit lane stands alone", file=sys.stderr)
        try:  # never-silent rule (Aug 1): the X lane is the primary source — raise the alarm
            import radar_x
            radar_x.alert_dead(f"radar.py X lane crashed: {e}")
        except Exception:
            pass

    moments.sort(key=lambda m: -m["vph"])  # raw velocity — honest from run #1
    moments = moments[:N_MOMENTS]
    for m in moments[:N_COMMENTS_FETCH]:
        if "old.reddit.com" not in m["permalink"]:
            continue  # comment mining is a reddit-HTML technique
        m["selftext"], m["top_comments"] = mine_thread(m["permalink"])
        time.sleep(3)

    now = datetime.now(timezone.utc).isoformat()
    json.dump({"updated": now, "moments": moments}, open(OUT, "w"), indent=1)
    print(f"radar: {len(moments)} moments -> radar.json", file=sys.stderr)
    for m in moments[:8]:
        print(f"  {m['vph']:>6}/hr  {m['score']:>6} {m['age_h']:>4}h  "
              f"{m.get('where', m['sub']):<22} {m['title'][:60]}", file=sys.stderr)

    # persist for CI (scout.py reads radar.json from the repo) — market.py
    # pattern. X ledger+cache ride along so the daily budget watch sees spend.
    subprocess.run(["git", "add", os.path.basename(OUT),
                    "x-used.json", "x-moments.json"], cwd=HERE)
    r = subprocess.run(["git", "commit", "-m", f"radar {now[:16]}"], cwd=HERE,
                       capture_output=True)
    if r.returncode == 0:
        subprocess.run(["git", "pull", "--rebase", "--autostash"], cwd=HERE, timeout=180)
        subprocess.run(["git", "push"], cwd=HERE, timeout=180)


if __name__ == "__main__":
    main()
