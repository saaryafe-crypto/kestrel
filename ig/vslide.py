"""Video-in-carousel producer (owner ask Sep 6).

The PUBLISH pipe has existed since Jul 31 and was never fed: post.py maps a
video-N.mp4 in the post dir to a VIDEO child right after slide N, the
ig-post workflow already copies video-*.mp4 to the media repo, and
render.py's cover strip already reads "Full video next" when the cover
carries video=True. This module is the missing producer: it turns the
picked story's own tweet footage (radar "video" = highest-bitrate mp4,
harvested by radar_x since day one) into a brand-fit 4:5 video slide.

DESIGN (owner order Sep 6: "if you put words make sure not to cover the
video and make the video smaller"): the @technology tweet-embed anatomy
reel.py already uses, adapted to 4:5 — dark #050505 canvas, the slide
masthead (wordmark + hairline rules) at the top, the footage SMALLER on a
rounded card in the middle, and the swipe-strip label at the bottom. Words
NEVER touch the footage. Inside the card the clip sits at its own aspect
over a blurred fill of itself, so wide demos are never butchered by a
crop. The frame renders as a transparent-holed PNG by the SAME Chrome +
fonts + CSS values as render.py — pixel-matched to the jpg slides around
it. Frame failure is never fatal: the clean blur-pad card ships alone.
Audio is the clip's OWN sound only (owner rule Jul 29: never add music).

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
# video card geometry: masthead band ends ~120px, strip starts ~1260px
HX, HY, HW, HH = 40, 150, 1000, 1040
MAX_CLIP_S = 30            # IG feed autoplay attention window
MIN_SRC_S = 3              # under this it reads as a broken gif
MAX_SRC_S = 90             # accuracy law: longer sources cut mid-thought
UA = {"User-Agent": "Mozilla/5.0"}

# frame PNG: #050505 everywhere except a rounded transparent hole for the
# video card (the reel.py punched-hole trick: box-shadow floods the frame
# color around a transparent rounded div). Masthead/strip CSS values are
# copied from render.py so the slide before and after match exactly.
FRAME_HTML = f"""<!doctype html><meta charset="utf-8"><style>
@font-face{{font-family:Anton;src:url("{HERE}/fonts/Anton-Regular.ttf")}}
@font-face{{font-family:Poppins;src:url("{HERE}/fonts/Poppins-ExtraBold.ttf");font-weight:800}}
*{{margin:0;box-sizing:border-box}}
html,body{{width:{W}px;height:{H}px;overflow:hidden;background:transparent}}
.hole{{position:absolute;left:{HX}px;top:{HY}px;width:{HW}px;height:{HH}px;
      border-radius:36px;box-shadow:0 0 0 4000px #050505}}
.masthead{{position:absolute;top:44px;left:0;right:0;z-index:2;
          display:flex;align-items:center;justify-content:center;gap:30px}}
.masthead img{{height:32px;filter:drop-shadow(0 2px 6px rgba(0,0,0,.7))}}
.masthead:before,.masthead:after{{content:"";height:2px;width:130px;
          background:rgba(255,255,255,.45)}}
.ctastrip{{position:absolute;bottom:56px;left:0;right:0;z-index:2;text-align:center}}
.swipe{{font-family:Poppins;font-weight:800;font-size:27px;letter-spacing:.18em;
       color:#FFF;text-transform:uppercase;text-indent:.18em}}
.swipe em{{font-style:normal;color:#D97757}}
</style><body>
<div class="hole"></div>
<div class="masthead"><img src="{HERE}/art/wordmark.png"></div>
<div class="ctastrip"><div class="swipe">LABEL</div></div>
</body>"""


def _dur(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path], capture_output=True, text=True, timeout=60)
    return float(out.stdout.strip())


def _frame(out_png, label):
    """Render the brand frame PNG. Returns path or None (never fatal)."""
    try:
        hp = out_png.replace(".png", ".html")
        open(hp, "w").write(FRAME_HTML.replace(
            "LABEL", html.escape(label).upper() + ' <em>&rarr;</em>'))
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


def make(video_url, out_path, label="The actual footage"):
    """Download the tweet's mp4, cut a <=30s opening segment, composite it
    onto the framed 4:5 canvas. Returns out_path on success, None on any
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
        fp = _frame(frame, label)
        # card: clip at its own aspect over a blurred fill of itself, padded
        # onto the dark canvas at the hole's position, frame PNG on top
        vf = (f"[0:v]split[a][b];"
              f"[a]scale={HW}:{HH}:force_original_aspect_ratio=increase,"
              f"crop={HW}:{HH},gblur=sigma=30,eq=brightness=-0.08[bg];"
              f"[b]scale={HW}:{HH}:force_original_aspect_ratio=decrease[fg];"
              f"[bg][fg]overlay=(W-w)/2:(H-h)/2[card];"
              f"[card]pad={W}:{H}:{HX}:{HY}:color=0x050505[base];"
              + ("[base][1:v]overlay=0:0,format=yuv420p[v]" if fp
                 else "[base]format=yuv420p[v]"))
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
        print(f"video slide: {min(dur, MAX_CLIP_S):.0f}s framed card at "
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
    make(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "video-1.mp4")
