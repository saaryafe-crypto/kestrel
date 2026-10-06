#!/usr/bin/env python3
"""Tweet-style reel frame (owner 2026-10-06: reels go back to the old look,
feed cards keep the news card). Solid near-black background, our page as a
"tweet": avatar + display name + blue check + @handle, the headline as the
tweet text, the video inside a rounded hole at its own aspect ratio, and a
small "Video: <uploader>" credit under it.

Everything sits inside the IG reel safe area (IG's top bar covers ~220px,
caption + buttons the bottom ~420px, 60px side margins); verify() refuses a
frame with anything outside it. Chrome renders the frame as a PNG with a
transparent hole; the hole's position is read back from the alpha channel,
so ffmpeg places the clip exactly where the browser laid it out.

Usage (sample): python3 reel_frame.py en|he "headline" "uploader" W H out.png"""
import html, os, re, subprocess, sys, tempfile

from PIL import Image

from pages import PAGES

CHROME = os.environ.get(
    "CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
HERE = os.path.dirname(os.path.abspath(__file__))
W, H = 1080, 1920
BG = "#050505"
SAFE = {"left": 60, "right": W - 60, "top": 230, "bottom": H - 430}
MIN_ASPECT = 0.8  # taller clips are center-cropped to 4:5 (as the old reels did)

CHECK = ('<svg viewBox="0 0 24 24" fill="#1d9bf0"><path d="M22.25 12c0-1.43-.88-2.67-2.19-3.34.46-1.39.2-2.9-.81-3.91s-2.52-1.27-3.91-.81c-.66-1.31-1.91-2.19-3.34-2.19s-2.67.88-3.33 2.19c-1.4-.46-2.91-.2-3.92.81s-1.26 2.52-.8 3.91c-1.31.67-2.2 1.91-2.2 3.34s.89 2.67 2.2 3.34c-.46 1.39-.21 2.9.8 3.91s2.52 1.26 3.91.81c.67 1.31 1.91 2.19 3.34 2.19s2.68-.88 3.34-2.19c1.39.45 2.9.2 3.91-.81s1.27-2.52.81-3.91c1.31-.67 2.19-1.91 2.19-3.34zm-11.71 4.2L6.8 12.46l1.41-1.42 2.26 2.26 4.8-5.23 1.47 1.36-6.2 6.77z"/></svg>')

PAGE = """<!doctype html><html lang="@LANG@"><meta charset="utf-8"><style>
@font-face{font-family:Poppins;src:url("@FONTS@/Poppins-SemiBold.ttf");font-weight:600}
@font-face{font-family:Poppins;src:url("@FONTS@/Poppins-ExtraBold.ttf");font-weight:800}
@font-face{font-family:Heebo;src:url("@FONTS@/Heebo-Variable.ttf");font-weight:100 900}
*{margin:0;padding:0;box-sizing:border-box}
html,body{width:1080px;height:1920px;overflow:hidden;background:transparent}
body{font-family:Poppins,sans-serif;position:relative}
#wrap{position:absolute;left:@SL@px;width:@SW@px;display:flex;flex-direction:column}
.card{display:flex;align-items:center;gap:26px;direction:ltr}
.card img{width:120px;height:120px;border-radius:50%;display:block;flex:none}
.name{display:flex;align-items:center;gap:12px;font-weight:800;font-size:46px;
  color:#fff;line-height:1.15;white-space:nowrap}
.name svg{width:44px;height:44px;flex:none}
.handle{font-weight:600;font-size:38px;color:#8B98A5;margin-top:2px}
.title{margin-top:34px;padding:0 6px;font-weight:600;font-size:50px;line-height:1.32;
  color:#fff;direction:@DIR@;text-align:@ALIGN@;font-family:@TFONT@}
.card,.title,.credit{position:relative;z-index:1}
.hole{margin-top:34px;align-self:center;border-radius:26px;box-shadow:0 0 0 2400px @BG@}
.credit{margin-top:14px;align-self:center;padding:0 4px;font-size:26px;color:#8B98A5;direction:@DIR@;
  text-align:@ALIGN@;font-family:@TFONT@;font-weight:500}
</style><body>
<div id="wrap">
<div class="card"><img src="@AVATAR@"><div>
  <div class="name">@DISPLAY@ @CHECK@</div><div class="handle">@HANDLE@</div></div></div>
<div class="title">@TITLE@</div>
<div class="hole"></div>
<div class="credit">@CREDIT@</div>
</div>
<script>
document.fonts.ready.then(()=>{
const SAFE_T=@ST@, SAFE_B=@SB@, SW=@SW@, ASPECT=@ASP@;
const t=document.querySelector('.title'), hole=document.querySelector('.hole'),
      wrap=document.getElementById('wrap');
// tweet text: at most 3 lines, shrinking from 50px to 40px
let s=50; const lines=()=>Math.round(t.getBoundingClientRect().height/(s*1.32));
while(lines()>3&&s>40){s-=2;t.style.fontSize=s+'px'}
hole.style.width='0px';hole.style.height='0px';
const rest=wrap.getBoundingClientRect().height;
const avail=SAFE_B-SAFE_T-rest-8;
let hw=SW, hh=hw/ASPECT;
if(hh>avail){hh=avail;hw=hh*ASPECT}
hw=Math.floor(hw/2)*2; hh=Math.floor(hh/2)*2;
hole.style.width=hw+'px';hole.style.height=hh+'px';
document.querySelector('.credit').style.width=hw+'px';
const total=wrap.getBoundingClientRect().height;
wrap.style.top=Math.round(SAFE_T+(SAFE_B-SAFE_T-total)/2)+'px';
// even pixel position for the hole (libx264 / overlay alignment)
const r=hole.getBoundingClientRect();
if(Math.round(r.top)%2) wrap.style.top=(parseInt(wrap.style.top)+1)+'px';
if(Math.round(r.left)%2) hole.style.marginLeft='1px';
});
</script></body></html>"""


def frame_html(lang, headline, credit, aspect):
    p = PAGES[lang]
    he = lang == "he"
    rep = {
        "LANG": lang, "FONTS": "file://" + os.path.join(HERE, "fonts"),
        "SL": str(SAFE["left"]), "SW": str(SAFE["right"] - SAFE["left"]),
        "ST": str(SAFE["top"]), "SB": str(SAFE["bottom"]), "ASP": f"{aspect:.5f}",
        "DIR": "rtl" if he else "ltr", "ALIGN": "right" if he else "left",
        "TFONT": "Heebo,sans-serif" if he else "Poppins,sans-serif", "BG": BG,
        "AVATAR": "file://" + os.path.join(HERE, "art", p["avatar"]),
        "DISPLAY": html.escape(p["display"]), "CHECK": CHECK,
        "HANDLE": html.escape(p["handle"]),
        "TITLE": html.escape(headline), "CREDIT": credit,
    }
    # single pass: replaced text (the headline) is never re-scanned
    return re.sub(r"@([A-Z]+)@", lambda m: rep[m.group(1)], PAGE)


def render(lang, headline, uploader, aspect, out_png):
    """Render the frame PNG for a clip of this aspect (w/h). Returns the
    hole (x, y, w, h) the clip must fill."""
    aspect = max(aspect, MIN_ASPECT)
    up = html.escape(uploader)
    credit = (f"וידאו: <bdi>{up}</bdi> ב־X" if lang == "he" else f"Video: {up} on X")
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False) as f:
        f.write(frame_html(lang, headline, credit, aspect))
    try:
        subprocess.run([CHROME, "--headless", "--disable-gpu", "--hide-scrollbars",
                        "--default-background-color=00000000",
                        f"--screenshot={out_png}", f"--window-size={W},{H}",
                        "--virtual-time-budget=4000", f"file://{f.name}"],
                       check=True, capture_output=True, timeout=120)
    finally:
        os.unlink(f.name)
    return verify(out_png)


def verify(png):
    """Find the transparent video hole and refuse a frame where the hole or
    any text/avatar pixel falls outside the safe area."""
    im = Image.open(png).convert("RGBA")
    if im.size != (W, H):
        raise RuntimeError(f"reel frame is {im.size}, expected {(W, H)}")
    hole = im.getchannel("A").point(lambda v: 255 if v == 0 else 0).getbbox()
    if not hole:
        raise RuntimeError("reel frame has no video hole")
    x0, y0, x1, y1 = hole
    # content = anything visibly brighter than the background
    ink = im.convert("L").point(lambda v: 255 if v > 30 else 0)
    ink.paste(0, hole)
    box = ink.getbbox()
    for name, (bx0, by0, bx1, by1) in (("hole", hole), ("text", box or hole)):
        if bx0 < SAFE["left"] or bx1 > SAFE["right"] or by0 < SAFE["top"] or by1 > SAFE["bottom"]:
            raise RuntimeError(f"reel frame {name} {(bx0, by0, bx1, by1)} outside safe area {SAFE}")
    w, h = x1 - x0, y1 - y0
    return x0, y0, w - w % 2, h - h % 2


if __name__ == "__main__":
    lang, headline, up, sw, sh, out = sys.argv[1:7]
    print(render(lang, headline, up, int(sw) / int(sh), out))
