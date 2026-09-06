"""Video-in-carousel producer (owner ask Sep 6).

The PUBLISH pipe has existed since Jul 31 and was never fed: post.py maps a
video-N.mp4 in the post dir to a VIDEO child right after slide N, the
ig-post workflow already copies video-*.mp4 to the media repo, and
render.py's cover strip already reads "Full video next" when the cover
carries video=True. This module is the missing producer: it turns the
picked story's own tweet footage (radar "video" = highest-bitrate mp4,
harvested by radar_x since day one) into a brand-fit 4:5 video slide.

DESIGN (owner order Sep 6, round 2 — "it should look like the examples of
the pictures in my ig folder on desktop"): the reference @technology
video slide is a TWEET EMBED — small brand mark up top, the source's X
card centered on a near-black backdrop, footage flush inside the card
below an avatar + name + @handle header. That is exactly render.py's R3
tweetcard anatomy, so this frame copies its values verbatim (card #080809,
2px rgba(255,255,255,.14) border, 28px radius, 84px avatar-initial circle,
33px/800 name, 28px #71767b handle) plus the standard centered masthead —
pixel-matched to the jpg slides around it. Words NEVER touch the footage.
Backdrop = the clip's own image blurred and dimmed (render.py art_bg
language). Inside the card the clip sits at its own aspect over a blurred
fill, so wide demos are never butchered by a crop.

The punched hole is reel.py's trick: a transparent rounded div whose
box-shadow floods the rest of the canvas — here with a translucent dark
flood so the blurred backdrop breathes through, the card header band and
border ring drawn opaque on top. Frame failure is never fatal: the clean
blur-pad video ships alone. Audio is the clip's OWN sound only (owner rule
Jul 29: never add music).

Accuracy law (owner Aug 18, relayed to this repo): no confusing partial
clips — a short self-explanatory segment or skip. So: sources longer than
MAX_SRC_S are skipped (a 30s bite of a 3-minute interview starts
mid-thought), short sources ship whole, and everything else ships its
opening MAX_CLIP_S (viral clips front-load the money shot).

NEVER raises: a failed video slide must not kill the slot — the carousel
simply ships without it, exactly as it did before Sep 6.
"""

import html
import os
import shutil
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CHROME = os.environ.get("CHROME",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")

W, H = 1080, 1350          # 4:5, same as every slide jpg
# X-card geometry: same 64px side margins as render.py's body.tweet frame;
# 150px header band (84px avatar + padding), media flush to the card edges,
# card centered vertically on the canvas
CX, CW = 64, 952           # card x / width
CY, CH = 190, 970          # card y / height
HDR = 150                  # header band height
HX, HY = CX, CY + HDR      # media hole position
HW, HH = CW, CH - HDR      # media hole size
MAX_CLIP_S = 30            # IG feed autoplay attention window
MIN_SRC_S = 3              # under this it reads as a broken gif
MAX_SRC_S = 90             # accuracy law: longer sources cut mid-thought
UA = {"User-Agent": "Mozilla/5.0"}

# frame PNG layers, bottom to top: translucent dark flood (punched at the
# media hole, so the blurred backdrop shows through like art_bg heavy),
# opaque card header band, border ring around the whole card, masthead.
FRAME_HTML = f"""<!doctype html><meta charset="utf-8"><style>
@font-face{{font-family:Anton;src:url("{HERE}/fonts/Anton-Regular.ttf")}}
@font-face{{font-family:Poppins;src:url("{HERE}/fonts/Poppins-SemiBold.ttf");font-weight:600}}
@font-face{{font-family:Poppins;src:url("{HERE}/fonts/Poppins-ExtraBold.ttf");font-weight:800}}
*{{margin:0;box-sizing:border-box}}
html,body{{width:{W}px;height:{H}px;overflow:hidden;background:transparent;
          font-family:Poppins}}
.hole{{position:absolute;left:{HX}px;top:{HY}px;width:{HW}px;height:{HH}px;
      border-radius:0 0 26px 26px;box-shadow:0 0 0 4000px rgba(5,5,6,.84)}}
.thead{{position:absolute;left:{CX}px;top:{CY}px;width:{CW}px;height:{HDR}px;
       background:#080809;border-radius:28px 28px 0 0;
       display:flex;align-items:center;gap:24px;padding:0 44px}}
.avatar{{width:84px;height:84px;border-radius:50%;flex:none;
        display:flex;align-items:center;justify-content:center;
        font-family:Anton;font-size:44px;color:#fff;
        background:radial-gradient(circle at 32% 28%,#3a3a44 0%,#141419 80%)}}
.tname{{font-size:33px;font-weight:800;color:#fff;line-height:1.15}}
.thandle{{font-size:28px;font-weight:600;color:#71767b}}
.ring{{position:absolute;left:{CX - 2}px;top:{CY - 2}px;
      width:{CW + 4}px;height:{CH + 4}px;border-radius:30px;
      border:2px solid rgba(255,255,255,.14);
      box-shadow:0 30px 90px rgba(0,0,0,.55)}}
.masthead{{position:absolute;top:44px;left:0;right:0;
          display:flex;align-items:center;justify-content:center;gap:30px}}
.masthead img{{height:32px;filter:drop-shadow(0 2px 6px rgba(0,0,0,.7))}}
.masthead:before,.masthead:after{{content:"";height:2px;width:130px;
          background:rgba(255,255,255,.45)}}
</style><body>
<div class="hole"></div>
<div class="thead"><div class="avatar">INITIAL</div>
<div><div class="tname">NAME</div><div class="thandle">@HANDLE</div></div></div>
<div class="ring"></div>
<div class="masthead"><img src="{HERE}/art/wordmark.png"></div>
</body>"""


def _dur(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path], capture_output=True, text=True, timeout=60)
    return float(out.stdout.strip())


def _frame(out_png, handle):
    """Render the X-card frame PNG. Returns path or None (never fatal)."""
    try:
        h = html.escape((handle or "").lstrip("@") or "source")
        hp = out_png.replace(".png", ".html")
        open(hp, "w").write(FRAME_HTML
                            .replace("INITIAL", h[:1].upper())
                            .replace("NAME", h)
                            .replace("HANDLE", h))
        subprocess.run(
            [CHROME, "--headless", "--disable-gpu",
             "--default-background-color=00000000",
             f"--screenshot={out_png}", f"--window-size={W},{H}",
             "file://" + hp], check=True, capture_output=True, timeout=120)
        os.remove(hp)
        return out_png if os.path.exists(out_png) else None
    except Exception as e:
        print(f"video frame render failed ({e}) — shipping bare card",
              file=sys.stderr)
        return None


def make(video_url, out_path, handle=None):
    """Download the tweet's mp4, cut a <=30s opening segment, composite it
    into the X-card 4:5 canvas. Returns out_path on success, None on any
    failure."""
    src = out_path + ".src.mp4"
    frame = out_path + ".frame.png"
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
        fp = _frame(frame, handle)
        if fp:
            # backdrop = the clip itself blurred/dimmed full-canvas (art_bg
            # language; the frame's translucent flood adds the heavy dim);
            # card media = clip at own aspect over a blurred fill of itself
            vf = (f"[0:v]split=3[a][b][c];"
                  f"[a]scale={W}:{H}:force_original_aspect_ratio=increase,"
                  f"crop={W}:{H},gblur=sigma=45[bd];"
                  f"[b]scale={HW}:{HH}:force_original_aspect_ratio=increase,"
                  f"crop={HW}:{HH},gblur=sigma=30,eq=brightness=-0.08[hg];"
                  f"[c]scale={HW}:{HH}:force_original_aspect_ratio=decrease[fg];"
                  f"[hg][fg]overlay=(W-w)/2:(H-h)/2[card];"
                  f"[bd][card]overlay={HX}:{HY}[base];"
                  f"[base][1:v]overlay=0:0,format=yuv420p[v]")
        else:  # frame died — full-bleed blur-pad, still our measurements
            vf = (f"[0:v]split[a][b];"
                  f"[a]scale={W}:{H}:force_original_aspect_ratio=increase,"
                  f"crop={W}:{H},gblur=sigma=30,eq=brightness=-0.08[bg];"
                  f"[b]scale={W}:{H}:force_original_aspect_ratio=decrease[fg];"
                  f"[bg][fg]overlay=(W-w)/2:(H-h)/2,format=yuv420p[v]")
        cmd = (["ffmpeg", "-y", "-loglevel", "error", "-t", str(MAX_CLIP_S),
                "-i", src] + (["-i", fp] if fp else [])
               + ["-filter_complex", vf, "-map", "[v]", "-map", "0:a?",
                  "-c:v", "libx264", "-preset", "medium", "-b:v", "5M",
                  "-r", "30", "-c:a", "aac", "-b:a", "128k",
                  "-movflags", "+faststart", out_path])
        subprocess.run(cmd, check=True, timeout=600)
        size = os.path.getsize(out_path)
        if size < 150_000:  # post.py's urls_live floor is 100KB — stay clear
            print(f"video slide: output only {size}B — broken encode, skipping",
                  file=sys.stderr)
            os.remove(out_path)
            return None
        print(f"video slide: {min(dur, MAX_CLIP_S):.0f}s X-card at "
              f"{W}x{H} ({size // 1024}KB) -> {os.path.basename(out_path)}",
              file=sys.stderr)
        return out_path
    except Exception as e:
        print(f"video slide failed ({e}) — carousel ships without it",
              file=sys.stderr)
        return None
    finally:
        for f in (src, frame):
            if os.path.exists(f):
                os.remove(f)


if __name__ == "__main__":
    make(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "video-1.mp4",
         handle=sys.argv[3] if len(sys.argv) > 3 else None)
