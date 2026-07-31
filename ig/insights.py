#!/usr/bin/env python3
"""Truth Loop: pull REAL Instagram numbers via bundle.social analytics
(account already connected through Facebook — free, no new tokens).

- Account snapshots (bundle refreshes daily, rolling 30d): impressions,
  likes, comments, postCount, FOLLOWERS — the one KPI, finally in data.
- Per-reel post analytics (bundle-published reels only): likes, comments,
  saves, shares. bundle.py stores bundle_post_id in reel.json at publish.

Carousels go out via Make.com, so per-carousel saves/reach would need
bundle's post-history import (free tier: 5 posts/month — useless at
5 carousels/day) or a Meta Graph API token. Owner decision pending;
account-level numbers carry the trend meanwhile, and learn.py's spy
scrape still covers per-carousel likes/comments.

Run daily from ig-health.yml; history accumulates in insights.json."""
import glob, json, os
import bundle

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "insights.json")
KEEP = ("impressions", "impressionsUnique", "views", "likes", "comments",
        "postCount", "followers", "createdAt")


def main():
    data = json.load(open(OUT)) if os.path.exists(OUT) else {"account": [], "reels": {}}

    # 1) account snapshots — append only the ones we haven't stored yet
    acct = bundle.api(f"/analytics/social-account?teamId={bundle.TEAM_ID}"
                      "&platformType=INSTAGRAM")
    seen = {s["id"] for s in data["account"]}
    for i in acct.get("items", []):
        if i["id"] not in seen:
            data["account"].append({"id": i["id"], **{k: i.get(k) for k in KEEP}})
    data["account"].sort(key=lambda s: s.get("createdAt", ""))

    # 2) per-reel lifetime numbers (only reels published through bundle)
    for rj in glob.glob(os.path.join(HERE, "posts", "*", "reel.json")):
        r = json.load(open(rj))
        pid = r.get("bundle_post_id")
        if not pid:
            continue
        try:
            pa = bundle.api(f"/analytics/post?postId={pid}&platformType=INSTAGRAM")
        except Exception as e:  # deleted post / analytics not ready yet
            print(f"reel {os.path.basename(os.path.dirname(rj))}: {e}")
            continue
        items = pa.get("items") or []
        if items:
            latest = max(items, key=lambda i: i.get("createdAt", ""))
            data["reels"][os.path.basename(os.path.dirname(rj))] = {
                k: latest.get(k) for k in
                ("likes", "comments", "saves", "shares", "views",
                 "impressions", "createdAt")}

    json.dump(data, open(OUT, "w"), indent=1)

    # 3) compact report for the CI log
    snaps = data["account"]
    if snaps:
        cur = snaps[-1]
        prev = snaps[-2] if len(snaps) > 1 else {}
        print(f"@yaffeai {cur.get('createdAt', '')[:10]}: "
              f"{cur.get('followers', 0)} followers "
              f"({cur.get('followers', 0) - prev.get('followers', 0):+d}), "
              f"{cur.get('impressions', 0):,} impressions 30d "
              f"({cur.get('impressions', 0) - prev.get('impressions', 0):+,d}), "
              f"{cur.get('likes', 0)} likes, {cur.get('comments', 0)} comments, "
              f"{cur.get('postCount', 0)} posts")
    for name, m in sorted(data["reels"].items(),
                          key=lambda kv: -(kv[1].get("saves") or 0))[:5]:
        print(f"reel {name}: {m.get('views') or 0} views, "
              f"{m.get('saves') or 0} saves, {m.get('shares') or 0} shares, "
              f"{m.get('likes') or 0} likes")


if __name__ == "__main__":
    main()
