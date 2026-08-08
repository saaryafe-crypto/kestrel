#!/usr/bin/env python3
"""Demand Radar — X WATCHLIST ONLY (runs on the Mac, launchd, every 2h).

Owner order Aug 3: content data comes ONLY from the X channels the owner
personally approved in watchlist-x.json — not Reddit, not news feeds,
nothing else. The Reddit harvest that used to live here (CORE/CROSS subs,
old.reddit HTML scraping, top-comment mining) is DELETED, not just skipped:
this file is now a thin orchestrator around radar_x.harvest(), which polls
twitterapi.io with "(from:approved OR ...)" batches and hard-filters every
moment against the watchlist — see radar_x._approved_only().

The politics blocklist stays here (radar_x imports political()). Fails open
downstream — scout.py treats a missing/stale radar.json as an empty pool,
and radar_x raises a GitHub-issue alarm the moment the X lane dies.
Writes radar.json, commits, pushes (market.py pattern)."""
import json, os, re, subprocess, sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "radar.json")

# Politics/outrage leak plug (audit Jul 29: "teacher arrested for clapping",
# "Willie Nelson urges Americans", pepper-spray drones slipped through).
# Off-brand politics is not our content — it wastes radar slots.
POLITICS = re.compile(
    r"\barrest|\bprotest|\bsenat|\bcongress\b|\blawmaker|\belection"
    r"|\bgovernor\b|\bmayor\b|\bwhite house|\btrump\b|\bbiden\b|\brepublican"
    r"|\bdemocrat|\burges\b|\bshooting|\bshooter|\bimmigra|\bdeport|\btariff"
    r"|\bracis|\bmigrant",
    re.I)

# Politics×AI COLLISION exemption (owner Aug 1: "if something with politics
# and ai collides we also need to share that" — governments disabling models,
# AI regulation drama). A politics hit passes IF the text names AI explicitly.
AI_CORE = re.compile(
    r"\ba\.?i\b|artificial intel|chatgpt|openai|claude|anthropic|gemini"
    r"|\bgrok\b|deepseek|\bllm\b|deepfake", re.I)


def political(text):
    """True = off-brand politics; AI-collision stories stay in."""
    return bool(POLITICS.search(text)) and not AI_CORE.search(text)


N_MOMENTS = 24  # radar.json cap

GUIDES = os.path.join(HERE, "guides.json")
GUIDE_POOL_DAYS = 7   # owner token-diet order Aug 8: the daily guide slot
GUIDE_POOL_CAP = 40   # posts the most viral X guide of the WEEK, so guide
                      # moments must outlive the 2h radar snapshot


def update_guide_pool(moments, now_iso):
    """Rolling 7-day pool of guide-flagged moments (owner Aug 8, kills the
    '6 prompts' repetition): radar.json only holds the current 2h snapshot,
    so edu.py used to see 0-3 guides and self-pick a pillar topic — which
    repeats. Persist every guide moment for a week; edu.py then always has
    a deep bench of PROVEN-viral guides and self-pick becomes the rare
    empty-pool fallback. Merge by tweet id, keep the mined thread (thread
    mining only runs for the top guides per poll, so an old entry's thread
    is often richer than a fresh re-sighting without one)."""
    try:
        pool = {g["id"]: g for g in json.load(open(GUIDES)).get("guides", [])}
    except Exception:
        pool = {}
    now_ts = datetime.fromisoformat(now_iso).timestamp()
    for m in moments:
        if not m.get("guide"):
            continue
        g = dict(m)
        g["born"] = now_ts - m.get("age_h", 0) * 3600  # tweet birth, absolute
        old = pool.get(g["id"])
        if old:
            g["born"] = old.get("born", g["born"])
            g["score"] = max(g.get("score", 0), old.get("score", 0))
            if not g.get("thread") and old.get("thread"):
                g["thread"] = old["thread"]
        pool[g["id"]] = g
    keep = [g for g in pool.values()
            if now_ts - g.get("born", 0) < GUIDE_POOL_DAYS * 86400]
    keep.sort(key=lambda g: -g.get("score", 0))
    keep = keep[:GUIDE_POOL_CAP]
    json.dump({"updated": now_iso, "guides": keep}, open(GUIDES, "w"), indent=1)
    print(f"guide pool: {len(keep)} viral guides (7-day) -> guides.json",
          file=sys.stderr)


def main():
    try:
        import radar_x
        moments = radar_x.harvest()
    except Exception as e:
        print(f"x radar failed ({e})", file=sys.stderr)
        try:  # never-silent rule (Aug 1): X is the ONLY source — raise the alarm
            import radar_x
            radar_x.alert_dead(f"radar.py X lane crashed: {e}")
        except Exception:
            pass
        moments = []

    moments.sort(key=lambda m: -m["vph"])  # raw velocity — honest ranking
    moments = moments[:N_MOMENTS]

    now = datetime.now(timezone.utc).isoformat()
    json.dump({"updated": now, "moments": moments}, open(OUT, "w"), indent=1)
    try:  # fails open — a pool hiccup must never kill the radar commit
        update_guide_pool(moments, now)
    except Exception as e:
        print(f"guide pool update failed ({e})", file=sys.stderr)
    print(f"radar: {len(moments)} moments -> radar.json (X watchlist only)",
          file=sys.stderr)
    for m in moments[:8]:
        print(f"  {m['vph']:>6}/hr  {m['score']:>6} {m['age_h']:>4}h  "
              f"{m.get('where', m['sub']):<22} {m['title'][:60]}", file=sys.stderr)

    # persist for CI (scout.py reads radar.json from the repo) — market.py
    # pattern. X ledger+cache ride along so the daily budget watch sees spend.
    subprocess.run(["git", "add", os.path.basename(OUT), "guides.json",
                    "x-used.json", "x-moments.json"], cwd=HERE)
    r = subprocess.run(["git", "commit", "-m", f"radar {now[:16]}"], cwd=HERE,
                       capture_output=True)
    if r.returncode == 0:
        subprocess.run(["git", "pull", "--rebase", "--autostash"], cwd=HERE, timeout=180)
        subprocess.run(["git", "push"], cwd=HERE, timeout=180)


if __name__ == "__main__":
    main()
