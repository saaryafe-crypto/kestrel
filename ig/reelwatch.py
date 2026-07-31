#!/usr/bin/env python3
"""Reel catch-up watchdog (owner Jul 31: "if my mac isn't awake create a
mechanism that will post WHEN the mac is awake. and will wait for it").

Why launchd alone is not enough: StartCalendarInterval slots missed while the
Mac SLEEPS are coalesced into ONE run at wake (2+ missed slots still lose
reels), and slots missed while the Mac was OFF are skipped entirely.

This runs every 30 min + at login (RunAtLoad). Each tick it compares reels
built today vs slots already passed today, per channel, and catches up AT MOST
one reel per tick — spacing catch-ups ~30 min apart instead of bursting three
reels at once. A 55-min per-channel cooldown stops a persistently failing
channel from burning attempts all day. Same-day only: after midnight the
counter resets (yesterday's missed slot is stale news, not worth a 3am post).
"""
import json, os, subprocess, sys, time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = "/tmp/ig-reelwatch.json"
GRACE_MIN = 12   # slot counts as "due" this many minutes after its start
COOLDOWN_S = 55 * 60

# (script, output root, slot times on the Mac clock = IL time)
CHANNELS = [
    ("reel.py",    "posts",    [(14, 0), (17, 0), (20, 0), (23, 0)]),
    ("reel_he.py", "posts-he", [(9, 15), (13, 15), (17, 15), (20, 15)]),
]


def built_today(root):
    today, n = datetime.now().strftime("%Y-%m-%d"), 0
    root = os.path.join(HERE, root)
    if not os.path.isdir(root):
        return 0
    for d in os.listdir(root):
        mp4 = os.path.join(root, d, "reel.mp4")
        if os.path.exists(mp4) and datetime.fromtimestamp(
                os.path.getmtime(mp4)).strftime("%Y-%m-%d") == today:
            n += 1
    return n


def main():
    # never run alongside a live slot job (a reel takes minutes to build; a
    # tick landing mid-run would see "not done yet" and start a duplicate)
    if subprocess.run(["pgrep", "-f", r"reel(_he)?\.py"],
                      capture_output=True).returncode == 0:
        print("a reel job is already running — skipping this tick")
        return
    now = datetime.now()
    try:
        state = json.load(open(STATE))
    except Exception:
        state = {}
    for script, root, slots in CHANNELS:
        due = sum(1 for h, m in slots
                  if (now.hour, now.minute) >= (h, m + GRACE_MIN))
        done = built_today(root)
        if done >= due:
            continue
        if time.time() - state.get(script, 0) < COOLDOWN_S:
            print(f"{script}: {done}/{due} but cooling down after a recent attempt")
            continue
        print(f"{script}: {done}/{due} reels today — catching up one missed slot")
        state[script] = time.time()
        json.dump(state, open(STATE, "w"))
        subprocess.run([os.path.join(HERE, ".venv", "bin", "python"),
                        os.path.join(HERE, script)], cwd=HERE)
        return  # one catch-up per tick; the next tick handles the next gap
    print(f"reelwatch {now:%H:%M}: all channels caught up")


if __name__ == "__main__":
    main()
