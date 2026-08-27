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
# MUST match the launchd plists (ai.yaffe.ig-reel / ig-reel-he) — Aug 13:
# stale 4-slot times here made the watchdog count a phantom slot all day
# (and until Aug 27 this list still carried the HE 13:15 slot the Aug 15
# plist fix had moved to 16:15 — same phantom-slot bug, now moot).
# 1 reel/day per channel since Aug 27 (owner match-the-data order: measured
# reels 178 likes/1M vs carousels 4,381 — freed slots fund 5 carousels/day).
CHANNELS = [
    ("reel.py",    "posts",    [(19, 0)]),
    ("reel_he.py", "posts-he", [(20, 15)]),
]


def built_today(root):
    """Reels that made it to PUBLISH today, not just to an mp4 on disk.
    EN truth is the reels-used.json ledger — reel.py writes it only after the
    media push succeeds (Aug 12: a reel BUILT fine, died on push, and the
    mp4-mtime check here counted it as done, so it was never retried).
    HE has no ledger, so mp4 mtime stays the best signal there."""
    today, n = datetime.now().strftime("%Y-%m-%d"), 0
    if root == "posts":
        try:
            used = json.load(open(os.path.join(HERE, "reels-used.json")))
            return sum(1 for u in used if u.get("date") == today)
        except Exception:
            pass  # unreadable ledger must never block ticks — fall back to mp4s
    root = os.path.join(HERE, root)
    if not os.path.isdir(root):
        return 0
    for d in os.listdir(root):
        mp4 = os.path.join(root, d, "reel.mp4")
        if os.path.exists(mp4) and datetime.fromtimestamp(
                os.path.getmtime(mp4)).strftime("%Y-%m-%d") == today:
            n += 1
    return n


MAX_JOB_MIN = 90  # a full reel build with every retry finishes well under 35


def _age_min(pid):
    out = subprocess.run(["ps", "-o", "etime=", "-p", str(pid)],
                         capture_output=True, text=True).stdout.strip()
    if not out:
        return 0
    days, rest = out.split("-") if "-" in out else ("0", out)
    parts = [int(p) for p in rest.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    return int(days) * 1440 + parts[0] * 60 + parts[1]


def reap_or_defer():
    """True = a HEALTHY job is running, skip this tick. Aug 2 post-mortem:
    a git clone with no timeout hung a reel job for 11 hours and this
    watchdog politely skipped every tick — the stuck job blocked its own
    rescuer. Now a job older than MAX_JOB_MIN is killed (with a loud gh
    issue) and the tick proceeds to refill the slot. Never-silent rule."""
    pids = subprocess.run(["pgrep", "-f", r"reel(_he)?\.py"],
                          capture_output=True, text=True).stdout.split()
    stuck = [p for p in pids if _age_min(p) >= MAX_JOB_MIN]
    if not stuck:
        return bool(pids)
    for p in stuck:
        subprocess.run(["kill", "-9", p])
    print(f"REAPED stuck reel job(s) {stuck} (ran > {MAX_JOB_MIN} min) — "
          "refilling the slot this tick")
    subprocess.run(["gh", "issue", "create", "-R", "saaryafe-crypto/kestrel",
                    "-t", f"reelwatch reaped a stuck reel job "
                          f"{datetime.now():%Y-%m-%d %H:%M}",
                    "-b", f"A reel job ran past {MAX_JOB_MIN} minutes (a "
                          "healthy build finishes under 35) and was killed so "
                          "the watchdog could refill the slot. If this "
                          "recurs, something new is hanging — check "
                          "/tmp/ig-reel*.log for the last line before the "
                          "freeze."], capture_output=True)
    return False


def main():
    # never run alongside a live HEALTHY slot job (a reel takes minutes to
    # build; a tick landing mid-run would see "not done yet" and start a
    # duplicate) — but a stuck job gets reaped, never deferred to
    if reap_or_defer():
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
