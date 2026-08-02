#!/usr/bin/env python3
"""Three-way git merge driver for the append-style JSON ledgers.

Two workflows frequently commit the same ledgers in parallel (EN autopost
+ HE autopost + manual pushes) and a plain text merge ALWAYS conflicts —
run 30759942650 lost a whole posting slot that way. Semantic merge instead:

  lists -> theirs + our additions since base (multiset via Counter, so the
           many identical {"date","cost"} budget entries are never
           collapsed or lost)
  dicts -> key-wise: the side that changed a key wins; if both changed the
           same key take max() (values are ISO dates, max = newest)

git calls:  python merge_ledgers.py %O %A %B   (base, ours, theirs)
Result is written to %A. Exit 0 = merged clean, 1 = give up (git falls
back to a normal conflict and the workflow's failure alert fires).
Wired up via .gitattributes (merge=ledger) + `git config
merge.ledger.driver` in the workflow save steps.
"""
import json
import sys
from collections import Counter


def _key(x):
    return json.dumps(x, sort_keys=True, ensure_ascii=False)


def merge(base, ours, theirs):
    if all(isinstance(x, list) for x in (base, ours, theirs)):
        added_by_us = Counter(map(_key, ours)) - Counter(map(_key, base))
        merged = list(theirs)
        for k, n in added_by_us.items():
            merged.extend([json.loads(k)] * n)
        return merged
    if all(isinstance(x, dict) for x in (base, ours, theirs)):
        merged = dict(base)
        for k in set(base) | set(ours) | set(theirs):
            b = base.get(k)
            changed = [d[k] for d in (ours, theirs) if k in d and d[k] != b]
            if changed:
                merged[k] = max(changed)
        return merged
    return None  # mixed/unknown types -> real conflict


def main():
    base_p, ours_p, theirs_p = sys.argv[1:4]

    def load(path):
        with open(path, encoding="utf-8") as f:
            s = f.read().strip()
        return json.loads(s) if s else None

    ours = load(ours_p)
    theirs = load(theirs_p)
    base = load(base_p)
    if base is None:
        base = [] if isinstance(ours, list) else {}
    merged = merge(base, ours, theirs)
    if merged is None:
        sys.exit(1)
    with open(ours_p, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False,
                  indent=1 if isinstance(merged, dict) else None)
        f.write("\n")


if __name__ == "__main__":
    main()
