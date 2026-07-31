#!/usr/bin/env python3
"""bundle.social client — publishes reels with NATIVE Instagram audio
(trending music from IG's own library, unreachable via the public Meta API).
Free tier = 20 posts/month, tracked in bundle-used.json; over budget the
caller falls back to the Make.com route with an embedded music bed.
Usage as CLI (from CI): python3 bundle.py publish <post_dir> <video_url>"""
import json, os, sys, urllib.parse, urllib.request
from datetime import date, datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
API = "https://api.bundle.social/api/v1"
TEAM_ID = "1e9b4b15-d159-46ac-a0dd-f2ce14c3332f"  # workspace "yaffeai"
USED = os.path.join(HERE, "bundle-used.json")
MONTHLY_BUDGET = 20  # free tier


def key():
    if os.environ.get("BUNDLE_API_KEY"):
        return os.environ["BUNDLE_API_KEY"]
    env = os.path.join(HERE, "..", ".env")  # local Mac runs: launchd exports nothing
    if os.path.exists(env):
        for line in open(env):
            if line.startswith("BUNDLE_API_KEY=") and line.split("=", 1)[1].strip():
                return line.split("=", 1)[1].strip()
    return None


def api(path, payload=None):
    req = urllib.request.Request(
        API + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        # UA required: Cloudflare fronts the API and 403s python-urllib (code 1010)
        headers={"x-api-key": key(), "Content-Type": "application/json",
                 "User-Agent": "ig-bot/1.0"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.load(r)


def month_used():
    used = json.load(open(USED)) if os.path.exists(USED) else []
    return sum(1 for u in used if u["date"][:7] == str(date.today())[:7])


def log_use(name):
    used = json.load(open(USED)) if os.path.exists(USED) else []
    used.append({"date": str(date.today()), "name": name})
    json.dump(used, open(USED, "w"), indent=1)


def budget_left():
    return key() is not None and month_used() < MONTHLY_BUDGET


def trending_audio(query=None):
    """IG music catalog; no query = trending. Needs Facebook-connected account."""
    q = f"&searchQuery={urllib.parse.quote(query)}" if query else ""
    return api(f"/misc/instagram/audio?teamId={TEAM_ID}&audioType=music" + q)["audio"]


def publish_reel(caption, video_url, audio_id=None):
    """Upload video from public URL, post as REEL now, native audio attached."""
    up = api("/upload/from-url", {"teamId": TEAM_ID, "url": video_url})
    # shareToFeed False = Reels tab only (owner rule Jul 29: the main grid is
    # carousels only — reels never appear on the profile grid)
    ig = {"type": "REEL", "text": caption, "uploadIds": [up["id"]],
          "shareToFeed": False}
    if audio_id:
        # IG mixes at publish time: trending track under the clip's own sound
        ig["musicSoundInfo"] = {"musicSoundId": str(audio_id),
                                "musicSoundVolume": 30,
                                "videoOriginalSoundVolume": 100}
    return api("/post/", {
        "teamId": TEAM_ID,
        "title": caption.split("\n")[0][:80] or "reel",
        "postDate": datetime.now(timezone.utc).isoformat(),
        "status": "SCHEDULED",
        "socialAccountTypes": ["INSTAGRAM"],
        "data": {"INSTAGRAM": ig}})


def main():
    if sys.argv[1:2] != ["publish"]:
        raise SystemExit(__doc__)
    post_dir, video_url = sys.argv[2], sys.argv[3]
    rj = os.path.join(post_dir, "reel.json")
    r = json.load(open(rj))
    post = publish_reel(r["caption"], video_url.rstrip("/") + "/reel.mp4",
                        audio_id=r.get("audio_id"))
    if post.get("id"):  # insights.py joins analytics on this later
        r["bundle_post_id"] = post["id"]
        json.dump(r, open(rj, "w"), indent=1)
    print("bundle post:", post.get("id"),
          "| audio:", r.get("audio_title") or "none")


if __name__ == "__main__":
    main()
