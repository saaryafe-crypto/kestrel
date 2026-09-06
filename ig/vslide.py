"""Video-in-carousel producer (owner ask Sep 6).

The PUBLISH pipe has existed since Jul 31 and was never fed: post.py maps a
video-N.mp4 in the post dir to a VIDEO child right after slide N, the
ig-post workflow already copies video-*.mp4 to the media repo, and
render.py's cover strip already reads "Full video next" when the cover
carries video=True. This module is the missing producer: it turns the
picked story's own tweet footage (radar "video" = highest-bitrate mp4,
harvested by radar_x since day one) into a brand-fit 4:5 video slide.

Design: full 1080x1350 canvas, the clip centered at its own aspect over a
blurred, slightly darkened fill of itself — the same treatment reel.py uses
for the 9:16 frame, so wide demo footage never gets butchered by a crop.
Audio is the clip's OWN sound only (owner rule Jul 29: never add music).

Accuracy law (owner Aug 18, relayed to this repo): no confusing partial
clips — a short self-explanatory segment or skip. So: sources longer than
MAX_SRC_S are skipped (a 30s bite of a 3-minute interview starts
mid-thought), short sources ship whole, and everything else ships its
opening MAX_CLIP_S (viral clips front-load the money shot).

NEVER raises: a failed video slide must not kill the slot — the carousel
simply ships without it, exactly as it did before Sep 6.
"""

import os
import shutil
import subprocess
import sys
import urllib.request

W, H = 1080, 1350          # 4:5, same as every slide jpg
MAX_CLIP_S = 30            # IG feed autoplay attention window
MIN_SRC_S = 3              # under this it reads as a broken gif
MAX_SRC_S = 90             # accuracy law: longer sources cut mid-thought
UA = {"User-Agent": "Mozilla/5.0"}

# blur-pad composite: [bg] cover-crop + blur + dim, [fg] fit inside, overlay
_VF = (f"[0:v]split[a][b];"
       f"[a]scale={W}:{H}:force_original_aspect_ratio=increase,"
       f"crop={W}:{H},gblur=sigma=30,eq=brightness=-0.08[bg];"
       f"[b]scale={W}:{H}:force_original_aspect_ratio=decrease[fg];"
       f"[bg][fg]overlay=(W-w)/2:(H-h)/2,format=yuv420p[v]")


def _dur(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path], capture_output=True, text=True, timeout=60)
    return float(out.stdout.strip())


def make(video_url, out_path):
    """Download the tweet's mp4 and composite a <=30s opening segment onto
    the 4:5 canvas. Returns out_path on success, None on any failure."""
    src = out_path + ".src.mp4"
    try:
        if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
            print("video slide: no ffmpeg on this machine — skipping",
                  file=sys.stderr)
            return None
        req = urllib.request.Request(video_url, headers=UA)
        with urllib.request.urlopen(req, timeout=120) as r, \
                open(src, "wb") as f:
            shutil.copyfileobj(r, f)
        dur = _dur(src)
        if not MIN_SRC_S <= dur <= MAX_SRC_S:
            print(f"video slide: source is {dur:.0f}s — outside the "
                  f"{MIN_SRC_S}-{MAX_SRC_S}s self-contained window, skipping",
                  file=sys.stderr)
            return None
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-t", str(MAX_CLIP_S),
             "-i", src, "-filter_complex", _VF, "-map", "[v]", "-map", "0:a?",
             "-c:v", "libx264", "-preset", "medium", "-b:v", "5M", "-r", "30",
             "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
             out_path], check=True, timeout=600)
        size = os.path.getsize(out_path)
        if size < 150_000:  # post.py's urls_live floor is 100KB — stay clear
            print(f"video slide: output only {size}B — broken encode, skipping",
                  file=sys.stderr)
            os.remove(out_path)
            return None
        print(f"video slide: {min(dur, MAX_CLIP_S):.0f}s at {W}x{H} "
              f"({size // 1024}KB) -> {os.path.basename(out_path)}",
              file=sys.stderr)
        return out_path
    except Exception as e:
        print(f"video slide failed ({e}) — carousel ships without it",
              file=sys.stderr)
        return None
    finally:
        if os.path.exists(src):
            os.remove(src)


if __name__ == "__main__":
    make(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "video-1.mp4")
