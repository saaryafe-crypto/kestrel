#!/usr/bin/env python3
"""Weekly inspirational photo reel (owner order Aug 12 — the reference:
TheAiOrbit's "next time you think of giving up, remember this photo of Elon
in 2008" — Elon crouched in Falcon 1 wreckage, Hans Zimmer under it, 845
shares).

Owner rules for this lane:
  - EXTRA reel, once a week — never replaces a slot, so skipping a week when
    nothing qualifies is LEGAL (unlike the always-post carousel slots).
  - Subject MUST fit the channel vision: a famous entrepreneur / CEO /
    builder in an iconic real moment that embodies persistence or building
    from nothing. Not generic history trivia.
  - MUST be proven-viral: candidates come only from inspire-pool.json —
    viral photo moments the X radar already caught (ground rule Aug 12:
    ride the wave, never invent).
  - Music: real Hans Zimmer as IG NATIVE audio via bundle.social — the
    licensed `music` catalog has no Zimmer, but audioType=original_sound
    (user-uploaded sounds) does; we rotate 4 iconic tracks from it, with a
    licensed-catalog fallback if an upload id dies. bundle is the ONLY
    publish route here: Make cannot attach native audio, and a silent
    inspirational reel is dead — no other fallback, alert instead.
  - The Aug 10 static-image ban (reel.py _static_clip) does NOT apply: that
    ban exists because reposted AUDIO is unverifiable — here we author the
    reel ourselves (our photo pick, our title, catalog music).

Usage: .venv/bin/python inspire.py [--dry]
"""
import json, os, shutil, subprocess, sys, urllib.request
from datetime import date, datetime

import bundle
from reel import build_video, make_overlay, push_media, sh
from write import call_claude, no_dashes

HERE = os.path.dirname(os.path.abspath(__file__))
POOL = os.path.join(HERE, "inspire-pool.json")
USED = os.path.join(HERE, "inspire-used.json")
RAW = "https://raw.githubusercontent.com/saaryafe-crypto/kestrel-media/main"

CLIP_S = 14  # Ken Burns length; completion beats length, story lives in caption

# Real Hans Zimmer via IG ORIGINAL SOUNDS (owner insisted Aug 12 and was
# right: audioType=original_sound reaches user-uploaded sounds, where the
# licensed-catalog wall doesn't apply — verified live Aug 12; the licensed
# `music` catalog still has zero Zimmer). Rotate weekly so back-to-back
# reels never share a track. All ids checked >= 14s (CLIP_S).
AUDIO = [
    ("326791823645097", "Time - Hans Zimmer (Inception)"),
    ("271619868995493", "Cornfield Chase - Hans Zimmer"),
    ("239447935356064", "No Time for Caution - Hans Zimmer"),
    ("135338016212274", "A Way of Life - Hans Zimmer"),
]
# Original sounds are user uploads and can vanish; if the pick dies at
# publish time, retry ONCE on this licensed-catalog cinematic track (stable
# ids) so a built reel never dies over an audio id.
FALLBACK_AUDIO = ("1515990402427650", "Hopeful Ascent by Global Genius")

SCHEMA = {
    "type": "object",
    "properties": {"pick": {"type": "integer"},
                   "title": {"type": "string"},
                   "caption": {"type": "string"}},
    "required": ["pick"],
}


def alert(msg):
    subprocess.run(["gh", "issue", "create", "-R", "saaryafe-crypto/kestrel",
                    "-t", f"inspire reel: {msg[:60]} "
                          f"{datetime.now():%Y-%m-%d %H:%M}",
                    "-b", msg], capture_output=True)


def fetch(url, out):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as r, open(out, "wb") as f:
        shutil.copyfileobj(r, f)


def pick(cands, photos):
    """One vision call: judge + writer. photos[i] is the downloaded image of
    cands[i]. Returns validated {pick,title,caption} or None (nothing
    qualifies — legal for this bonus lane)."""
    lines = []
    for i, c in enumerate(cands):
        lines.append(f"[{i}] @{c['sub']} on X, {c.get('score', 0):,} likes, "
                     f"{c.get('comments_n', 0):,} comments\n"
                     f"    POST TEXT: {c['title'][:400]}"
                     + (f"\n    MORE: {c['selftext'][:400]}"
                        if c.get("selftext") else ""))
    prompt = f"""You run @yaffeai, an AI/tech/business Instagram page whose audience is 20-30 year olds who want to build things. Once a week the page posts ONE inspirational photo reel. The gold-standard reference: a photo of Elon Musk in 2008 crouched among the wreckage of the third failed Falcon 1 launch, titled "next time you think of giving up, remember this photo of Elon in 2008".

Below are viral photos from X (each attached as an image, in order). Pick the ONE that matches the reference's power — or refuse.

CANDIDATES:
{chr(10).join(lines)}

HARD GATES (owner rules — refusing beats forcing):
- SUBJECT GATE: the photo's subject must be a famous entrepreneur, CEO, founder, or builder (or their company's defining moment) — someone a 20-year-old recognizes or a story about building/persisting. Actors, memes, nature, generic history = pick -1.
- STORY GATE: the photo must capture a REAL iconic moment with a documented comeback/persistence/built-from-nothing arc stated in the post text. Never invent facts beyond the post text.
- EMOTION GATE: a stranger seeing photo + your title must feel the chill in 2 seconds.
If no candidate passes ALL gates, return exactly {{"pick": -1}}.

WHEN ONE PASSES, also return:
- "title": overlay line, max 80 chars, sentence case, the "next time you think of giving up, remember this photo of Elon in 2008" family — name the PERSON and anchor the moment (year or event) so a cold viewer instantly gets it. Simple words a 16-year-old gets. No emojis, no dashes.
- "caption": the story in 2-3 short paragraphs — what the moment was, how bad it looked, what happened next (only facts from the post text). Then exactly:\\n\\nLove AI? Follow @yaffeai for daily AI news\\n\\nCredits: <the X account's plain name, no @>. DM for credit or removal\\n\\n<exactly 5 hashtags>

Return ONLY JSON: {{"pick": <index or -1>, "title": "...", "caption": "..."}}"""
    r = call_claude(prompt, schema=SCHEMA, images=photos)
    if r.get("pick", -1) < 0 or r.get("pick", -1) >= len(cands):
        print("inspire judge: no candidate passes the gates this week",
              file=sys.stderr)
        return None
    errs = []
    if not r.get("title") or len(r["title"]) > 85:
        errs.append("title missing or over 85 chars")
    cap = r.get("caption", "")
    if "@yaffeai" not in cap or "Credits:" not in cap:
        errs.append("caption missing follow line or Credits")
    if len([w for w in cap.split() if w.startswith("#")]) != 5:
        errs.append("need exactly 5 hashtags")
    if errs:
        print("inspire qa failed: " + "; ".join(errs), file=sys.stderr)
        return None
    return r


def ken_burns(photo, out_mp4):
    """Still photo -> slow-zoom clip sized for reel.py's video hole. Upscale
    first so zoompan doesn't jitter on sub-pixel steps."""
    vf = ("scale=3840:-2,"
          f"zoompan=z='min(zoom+0.0004,1.13)':d={CLIP_S * 30}:"
          "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=960x1200:fps=30,"
          "format=yuv420p")
    sh("ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", photo,
       "-vf", vf, "-frames:v", str(CLIP_S * 30), "-c:v", "libx264",
       "-preset", "medium", "-crf", "18", out_mp4)


def main():
    dry = "--dry" in sys.argv
    used = json.load(open(USED)) if os.path.exists(USED) else []
    used_ids = {u["id"] for u in used}
    try:
        pool = json.load(open(POOL))["photos"]
    except Exception as e:
        raise SystemExit(f"no inspire-pool.json ({e}) — radar builds it")
    cands = [p for p in pool if p["id"] not in used_ids][:4]
    # legal skips exit 0: this is a BONUS lane (owner Aug 12), not an
    # always-post slot — the launchd wrapper only alarms on real failures
    if not cands:
        print("inspire pool empty this week — skipping (bonus lane)")
        return
    if not dry and not bundle.budget_left():
        alert("bundle budget out — weekly inspirational reel skipped (native "
              "audio has no other route)")
        return

    photos = []
    for i, c in enumerate(cands):
        fp = f"/tmp/inspire-{i}.jpg"
        try:
            fetch(c["image"], fp)
            photos.append(fp)
        except Exception as e:
            print(f"photo download failed @{c['sub']}: {e}", file=sys.stderr)
            photos.append(None)
    pairs = [(c, p) for c, p in zip(cands, photos) if p]
    if not pairs:
        print("no candidate photo downloadable — skipping (bonus lane)")
        return
    cands, photos = [c for c, _ in pairs], [p for _, p in pairs]

    r = pick(cands, photos)
    if not r:
        print("no inspirational reel this week (judge refused — legal for "
              "the bonus lane)")
        return
    c = cands[r["pick"]]
    r["title"], r["caption"] = no_dashes(r["title"]), no_dashes(r["caption"])
    print(f"picked @{c['sub']} ({c['score']:,} likes): {c['title'][:70]}\n"
          f"overlay: {r['title']}", file=sys.stderr)

    name = f"{date.today()}-inspire-{c['id']}"
    post_dir = os.path.join(HERE, "posts", name)
    os.makedirs(post_dir, exist_ok=True)
    src = "/tmp/inspire-src.mp4"
    ken_burns(photos[r["pick"]], src)
    make_overlay(r["title"], os.path.join(post_dir, "overlay.png"))
    out_mp4 = os.path.join(post_dir, "reel.mp4")
    build_video(src, os.path.join(post_dir, "overlay.png"), out_mp4, 0, CLIP_S)
    os.remove(src)
    if not os.path.exists(out_mp4) or os.path.getsize(out_mp4) < 100_000:
        shutil.rmtree(post_dir, ignore_errors=True)
        raise SystemExit("reel.mp4 came out broken")

    audio_id, audio_title = AUDIO[date.today().isocalendar()[1] % len(AUDIO)]
    meta = {**r, "source": c["permalink"], "channel": c["sub"],
            "publish": "bundle", "audio_id": audio_id,
            "audio_title": audio_title, "kind": "inspire"}
    json.dump(meta, open(os.path.join(post_dir, "reel.json"), "w"), indent=1)
    print("reel ready:", out_mp4)
    if dry:
        return

    push_media(post_dir, name)
    try:
        try:
            post = bundle.publish_reel(r["caption"], f"{RAW}/{name}/reel.mp4",
                                       audio_id=audio_id, music_volume=100,
                                       original_volume=0)
        except Exception as e:
            audio_id, audio_title = FALLBACK_AUDIO
            print(f"zimmer original-sound id failed ({e}) — retrying on the "
                  f"licensed catalog track", file=sys.stderr)
            post = bundle.publish_reel(r["caption"], f"{RAW}/{name}/reel.mp4",
                                       audio_id=audio_id, music_volume=100,
                                       original_volume=0)
            meta["audio_id"], meta["audio_title"] = audio_id, audio_title
        meta["bundle_post_id"] = post.get("id")
        json.dump(meta, open(os.path.join(post_dir, "reel.json"), "w"), indent=1)
        bundle.log_use(name)
    except Exception as e:
        alert(f"bundle publish failed for {name}: {e}")
        raise
    used.append({"id": c["id"], "date": str(date.today()), "title": c["title"]})
    json.dump(used, open(USED, "w"), indent=1)
    sh("git", "add", "posts", os.path.basename(USED), "bundle-used.json",
       cwd=HERE)
    subprocess.run(["git", "commit", "-m", f"IG inspire reel: {name}"], cwd=HERE)
    subprocess.run(["git", "pull", "--rebase", "--autostash"], cwd=HERE, timeout=180)
    subprocess.run(["git", "push"], cwd=HERE, timeout=180)
    print("published inspire reel:", post.get("id"))


if __name__ == "__main__":
    main()
