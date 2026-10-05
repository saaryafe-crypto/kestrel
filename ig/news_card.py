#!/usr/bin/env python3
"""Single-image news card (owner-approved 2026-10-05): brand bar on top,
white box with a plain headline (max 2 lines), the story's own photo below.
No AI-generated imagery. EN = black + neon green, HE = Israeli blue/white RTL.

Render glitch fix (owner report: a black rectangle sometimes covered the
bottom of the photo near the credit line): Chrome no longer loads the photo
at all. Chrome renders only the OVERLAY (bar, box, credit, handle) on a
transparent canvas; Pillow pastes the photo underneath. There is no image
load to race, and verify() refuses any overlay that is opaque where the
photo should show. The same overlay is the persistent top layer of reels
(the video plays in the transparent area).

Usage: python3 news_card.py card.json out.jpg
card.json: {"lang": "en"|"he", "headline": str, "kicker": str (optional),
            "photo": path, "focus": [x, y] 0-1 (optional), "credit": str,
            "format": "card"|"reel" (optional)}"""
import html, json, os, re, subprocess, sys, tempfile

from PIL import Image, ImageStat

from pages import PAGES

CHROME = os.environ.get(
    "CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = os.path.join(HERE, "fonts")
W = 1080

THEMES = {
    "en": {"bar": "#050706", "accent": "#00E676", "wm": "#00E676",
           "ink": "#0A0A0A", "font": "Inter", "dir": "ltr",
           "tagclr": "#00E676", "tagborder": "#00E676"},
    "he": {"bar": "#0A3BA8", "accent": "#0A3BA8", "wm": "#9EC1FF",
           "ink": "#0B1B3F", "font": "Heebo", "dir": "rtl",
           "tagclr": "#FFFFFF", "tagborder": "rgba(255,255,255,.55)"},
}

CSS = """
@font-face{font-family:Inter;src:url("FONTS/Inter.ttf")}
@font-face{font-family:Heebo;src:url("FONTS/Heebo-Variable.ttf")}
*{margin:0;padding:0;box-sizing:border-box}
html,body{width:1080px;height:HEIGHTpx;overflow:hidden;background:transparent}
body{font-family:FONT,sans-serif;direction:DIR;display:flex;flex-direction:column}
.top{background:BAR;padding:34px 36px 36px}
.brand{display:flex;align-items:center;justify-content:space-between;
  direction:ltr;color:#fff;margin-bottom:28px}
.name{font-family:Inter,sans-serif;font-weight:800;font-size:46px;letter-spacing:1px}
.name b{color:WM;font-weight:800}
.tag{font-weight:700;font-size:24px;letter-spacing:2px;color:TAGCLR;
  border:2px solid TAGBORDER;border-radius:6px;padding:6px 14px}
.box{background:#fff;padding:30px 36px 34px;text-align:center}
.kicker{display:inline-block;font-weight:800;font-size:34px;color:ACCENT;
  border-bottom:5px solid ACCENT;padding-bottom:2px;margin-bottom:14px}
h1{font-weight:850;font-size:66px;line-height:1.13;color:INK;
  letter-spacing:-.5px;text-wrap:balance}
.nw{white-space:nowrap}
.photo{flex:1;position:relative}
.photo:after{content:"";position:absolute;left:0;right:0;bottom:0;height:SHADEpx;
  background:linear-gradient(transparent,rgba(0,0,0,.45))}
.credit,.handle{z-index:1}
.credit{position:absolute;bottom:18px;LEFT:22px;color:#fff;font-size:20px;
  font-family:Inter,sans-serif;text-shadow:0 1px 4px rgba(0,0,0,.9);direction:ltr}
.handle{position:absolute;bottom:18px;RIGHT:22px;color:#fff;font-size:22px;
  font-weight:700;font-family:Inter,sans-serif;background:rgba(0,0,0,.45);
  padding:6px 12px;border-radius:6px;direction:ltr}
"""
# reel safe zones: IG's top bar covers ~110px, caption/buttons the bottom ~340px
REEL_CSS = ".top{padding-top:120px}.credit,.handle{bottom:350px}"
# shrink the headline until it fits in two lines (never more than 2)
FIT_JS = """<script>
const h=document.querySelector('h1');let s=66;
const lines=()=>Math.round(h.getBoundingClientRect().height/(s*1.13));
while(lines()>2&&s>40){s-=2;h.style.fontSize=s+'px'}
</script>"""


def height(c):
    return 1920 if c.get("format") == "reel" else 1350


def overlay_html(c):
    t, p = THEMES[c["lang"]], PAGES[c["lang"]]
    css = CSS
    for k, v in (("FONTS", FONTS), ("TAGBORDER", t["tagborder"]),
                 ("TAGCLR", t["tagclr"]), ("BAR", t["bar"]), ("INK", t["ink"]),
                 ("ACCENT", t["accent"]), ("WM", t["wm"]), ("FONT", t["font"]),
                 ("DIR", t["dir"]), ("HEIGHT", str(height(c))),
                 ("SHADE", "470" if c.get("format") == "reel" else "120"),
                 ("LEFT", "left" if t["dir"] == "ltr" else "right"),
                 ("RIGHT", "right" if t["dir"] == "ltr" else "left")):
        css = css.replace(k, v)
    # never break a line inside a hyphenated word ("AI-|generated")
    headline = re.sub(r"(\S+-\S+)", r'<span class="nw">\1</span>', html.escape(c["headline"]))
    kicker = (f'<div class="kicker">{html.escape(c["kicker"])}</div><br>'
              if c.get("kicker") else "")
    return f"""<!doctype html><html lang="{c['lang']}"><meta charset="utf-8">
<style>{css}{REEL_CSS if c.get("format") == "reel" else ""}</style><body>
<div class="top"><div class="brand"><div class="name">{p['wordmark']}</div>
<div class="tag">{p['tag']}</div></div>
<div class="box">{kicker}<h1>{headline}</h1></div></div>
<div class="photo"><div class="credit">{html.escape(c.get('credit', ''))}</div>
<div class="handle">{p['handle']}</div></div>{FIT_JS}</body></html>"""


def render_overlay(c, out_png):
    """Transparent-background PNG of everything except the photo/video.
    Returns the y where the photo area starts."""
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False) as f:
        f.write(overlay_html(c))
    try:
        subprocess.run([CHROME, "--headless", "--disable-gpu", "--hide-scrollbars",
                        "--default-background-color=00000000",
                        f"--screenshot={out_png}", f"--window-size={W},{height(c)}",
                        "--virtual-time-budget=4000", f"file://{f.name}"],
                       check=True, capture_output=True, timeout=120)
    finally:
        os.unlink(f.name)
    return verify(out_png, c)


def verify(png, c):
    """Find the photo area (first fully transparent row under the box) and
    refuse an overlay that would cover the photo: wrong size, no transparent
    area, or more than 4% opaque pixels inside it (credit + handle only)."""
    im = Image.open(png).convert("RGBA")
    if im.size != (W, height(c)):
        raise RuntimeError(f"overlay is {im.size}, expected {(W, height(c))}")
    a = im.getchannel("A")
    top = next((y for y in range(60, im.height)
                if a.crop((0, y, W, y + 1)).getextrema()[1] == 0), None)
    if top is None or top > im.height * 0.6:
        raise RuntimeError(f"overlay has no photo area (top={top})")
    area = a.crop((0, top, W, im.height))
    opaque = sum(area.point(lambda v: 255 if v > 200 else 0).histogram()[255:])
    if opaque / (W * (im.height - top)) > 0.04:
        raise RuntimeError("overlay covers the photo area, refusing to ship")
    return top


def cover_crop(photo, w, h, focus=(0.5, 0.35)):
    im = Image.open(photo).convert("RGB")
    s = max(w / im.width, h / im.height)
    im = im.resize((round(im.width * s) + 1, round(im.height * s) + 1), Image.LANCZOS)
    x = int((im.width - w) * focus[0])
    y = int((im.height - h) * focus[1])
    return im.crop((x, y, x + w, y + h))


def render_card(c, out_jpg):
    ov = out_jpg + ".overlay.png"
    top = render_overlay(c, ov)
    canvas = Image.new("RGB", (W, height(c)), THEMES[c["lang"]]["bar"])
    pic = cover_crop(c["photo"], W, height(c) - top, tuple(c.get("focus") or (0.5, 0.35)))
    if ImageStat.Stat(pic.convert("L")).stddev[0] < 8:
        raise RuntimeError("photo is blank or flat, refusing to ship")
    canvas.paste(pic, (0, top))
    overlay = Image.open(ov).convert("RGBA")
    canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")
    canvas.save(out_jpg, "JPEG", quality=92)
    os.remove(ov)
    return out_jpg


if __name__ == "__main__":
    render_card(json.load(open(sys.argv[1])), sys.argv[2])
