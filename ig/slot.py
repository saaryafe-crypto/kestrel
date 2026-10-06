#!/usr/bin/env python3
"""Publish on time despite GitHub cron lateness (owner 2026-10-05).

The workflows fire ~2-3h BEFORE the slot, build the post, then call
`python3 slot.py wait <lang> <card|reel> <index>` which sleeps until the
slot's local wall-clock time in the page's timezone (pages.py). A run that
starts late publishes immediately; one that crossed local midnight
exits 3 (skip). DST never moves a slot: the time is
computed in the page's own zone, not in UTC.
`index` = "now" publishes immediately (manual runs)."""
import sys, time
from datetime import datetime
from zoneinfo import ZoneInfo

from pages import PAGES


def target(lang, kind, idx, now=None):
    p = PAGES[lang]
    tz = ZoneInfo(p["tz"])
    now = now or datetime.now(tz)
    hh, mm = map(int, p["cards" if kind == "card" else "reels"][int(idx)].split(":"))
    return now.replace(hour=hh, minute=mm, second=0, microsecond=0)


def main(lang, kind, idx):
    if idx == "now":
        return
    t = target(lang, kind, idx)
    wait = (t - datetime.now(t.tzinfo)).total_seconds()
    print(f"slot {lang} {kind} #{idx} = {t.isoformat()}; "
          + (f"waiting {wait / 60:.0f} min" if wait > 0 else f"late by {-wait / 60:.0f} min, publishing now"))
    if wait > 5 * 3600:  # the run crossed local midnight: this slot is gone
        print("slot already passed yesterday, not publishing")
        sys.exit(3)
    if wait > 0:
        time.sleep(wait)


if __name__ == "__main__":
    main(*sys.argv[2:5])  # argv[1] is the "wait" subcommand
