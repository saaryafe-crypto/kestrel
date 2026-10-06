#!/usr/bin/env python3
"""Backup trigger for the news lanes (2026-10-06: GitHub skipped the EN
08:00 cron and fired the HE 08:00 one 7h late).

Runs every 10 min on the Mac (LaunchAgent ai.yaffe.ig-news-backup). For each
lane slot of today: if the slot is less than LEAD away (or a little past) and
no run for that slot exists on GitHub (run titles carry the slot, see
run-name in the caller workflows), dispatch the lane with that slot index.
Never double posts: news.py skips a slot that already has a reserved post dir
(slot_taken), and the lane's concurrency group runs one at a time.

  python3 backup_dispatch.py            check + dispatch
  python3 backup_dispatch.py --dry      only print what it would do"""
import json, os, re, subprocess, sys
from datetime import datetime, timedelta

import slot
from pages import PAGES

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = "saaryafe-crypto/kestrel"
LANES = {("en", "card"): "ig-post.yml", ("he", "card"): "ig-post-he.yml",
         ("en", "reel"): "ig-reel.yml", ("he", "reel"): "ig-reel-he.yml"}
LEAD = timedelta(minutes=90)        # crons fire ~2h early; none by 90 min before = skipped
LAST = timedelta(seconds=slot.MAX_LATE_S) - timedelta(minutes=45)  # leave time to build
DEAD = {"startup_failure", "cancelled"}


def gh(*a):
    return subprocess.run(["gh", *a, "-R", REPO], capture_output=True, text=True, check=True).stdout


def main(dry):
    for (lang, kind), wf in LANES.items():
        crons = re.findall(r'cron: "([^"]+)"', open(os.path.join(HERE, "..", ".github", "workflows", wf)).read())
        times = PAGES[lang]["cards" if kind == "card" else "reels"]
        runs = None
        for i, cron in enumerate(crons[:len(times)]):
            t = slot.target(lang, kind, i)
            now = datetime.now(t.tzinfo)
            if not (t - LEAD <= now <= t + LAST):
                continue
            if runs is None:
                runs = json.loads(gh("run", "list", "--workflow", wf, "--limit", "30",
                                     "--json", "displayTitle,createdAt,conclusion"))
            since = (t - timedelta(hours=6)).timestamp()
            mine = [r for r in runs
                    if datetime.fromisoformat(r["createdAt"].replace("Z", "+00:00")).timestamp() >= since
                    and (r["displayTitle"].endswith(f"| slot {i}") or r["displayTitle"].endswith(f"| {cron}"))]
            live = [r for r in mine if r["conclusion"] not in DEAD]
            tag = f"{lang} {kind} slot {i} ({t:%H:%M} {PAGES[lang]['tz']})"
            if live:
                continue
            if len(mine) >= 3:
                print(f"{now:%F %T} {tag}: 3 dead runs already, giving up")
                continue
            print(f"{now:%F %T} {tag}: no run on GitHub, dispatching {wf} slot={i}")
            if not dry:
                gh("workflow", "run", wf, "-f", f"slot={i}")


if __name__ == "__main__":
    main("--dry" in sys.argv)
