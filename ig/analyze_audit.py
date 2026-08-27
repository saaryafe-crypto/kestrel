#!/usr/bin/env python3
"""Analysis for the Aug 27 competitor deep audit (audit-accounts.json).
Numbers only — no opinions. Prints per-account and cross-account tables:
cadence (posts/day from timestamp span), format mix, engagement per format
(visible likes only, normalized per 1M followers), posting-hour histogram.
Usage: python3 analyze_audit.py
"""
import json, os, statistics, sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
data = json.load(open(os.path.join(HERE, "audit-accounts.json")))


def parse_ts(ts):
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


rows = []
for prof in data["profiles"]:
    posts = prof.get("posts") or []
    if not posts:
        continue
    tss = sorted(t for t in (parse_ts(p.get("ts", "")) for p in posts) if t)
    # pinned posts sit at the grid top with OLD dates — drop anything more
    # than 30 days older than the newest before measuring cadence
    if tss:
        recent = [t for t in tss if (tss[-1] - t).days <= 30]
    else:
        recent = []
    span_d = ((recent[-1] - recent[0]).total_seconds() / 86400
              if len(recent) > 1 else 0)
    per_day = (len(recent) - 1) / span_d if span_d > 0 else 0
    kinds = {}
    for p in posts:
        kinds[p["kind"]] = kinds.get(p["kind"], 0) + 1
    vis = [p for p in posts if p.get("likes")]
    med = {k: statistics.median([p["likes"] for p in vis if p["kind"] == k])
           for k in kinds if any(p["kind"] == k for p in vis)}
    rows.append({"handle": prof["handle"], "followers": prof["followers"],
                 "n": len(posts), "span_d": round(span_d, 1),
                 "per_day": round(per_day, 1), "kinds": kinds,
                 "med_likes": {k: int(v) for k, v in med.items()},
                 "visible": len(vis)})

rows.sort(key=lambda r: -r["followers"])
print(f"{'account':<16}{'followers':>11}{'posts/day':>10}  formats (of {12})"
      f"{'':<14} median likes by format (visible n)")
for r in rows:
    fmts = " ".join(f"{k}:{v}" for k, v in sorted(r["kinds"].items()))
    meds = " ".join(f"{k}:{v:,}" for k, v in sorted(r["med_likes"].items()))
    # likes per 1M followers for cross-account comparison
    norm = {k: int(v * 1e6 / r["followers"]) for k, v in r["med_likes"].items()
            if r["followers"]}
    norms = " ".join(f"{k}:{v:,}" for k, v in sorted(norm.items()))
    print(f"{r['handle']:<16}{r['followers']:>11,}{r['per_day']:>10}  "
          f"{fmts:<28} {meds}  (vis {r['visible']}/{r['n']})")
    print(f"{'':<16}{'per-1M-followers:':>21} {norms}")

# posting-hour histogram (UTC) across all accounts
hours = {}
for prof in data["profiles"]:
    for p in prof.get("posts") or []:
        t = parse_ts(p.get("ts", ""))
        if t:
            hours[t.hour] = hours.get(t.hour, 0) + 1
print("\nposting hours UTC (all accounts):")
for h in sorted(hours):
    print(f"  {h:02d}:00  {'#' * hours[h]} {hours[h]}")

# cross-account format medians, normalized
allnorm = {}
for r in rows:
    for k, v in r["med_likes"].items():
        if r["followers"]:
            allnorm.setdefault(k, []).append(v * 1e6 / r["followers"])
print("\ncross-account median of per-1M-normalized median likes:")
for k, vals in sorted(allnorm.items()):
    print(f"  {k:<9} {int(statistics.median(vals)):>8,}  (n={len(vals)} accounts)")
