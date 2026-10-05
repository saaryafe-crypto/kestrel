#!/usr/bin/env python3
"""Single-image news card, @fast.news.il format (owner order 2026-10-05):
brand bar on top, white box with a plain 2-line headline, the story's own
photo below. No AI-generated imagery. EN = navy/black + orange #D97757,
HE = Israeli blue/white, RTL Heebo.

Usage: python3 news_card.py card.json out.png
card.json: {"format": "card"|"reel" (optional), "lang": "en"|"he", "headline": str, "kicker": str (optional),
            "photo": path, "focus": "50% 30%" (optional), "credit": str}"""
import html, json, os, subprocess, sys, tempfile

from render import CHROME

HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = os.path.join(HERE, "fonts")

THEMES = {
    "en": {"bar": "#0B1020", "accent": "#D97757", "ink": "#0B1020",
           "font": "Inter", "dir": "ltr", "name": "YAFFE<b>AI</b>",
           "tag": "AI &amp; TECH NEWS", "handle": "@yaffeai"},
    "he": {"bar": "#0A3BA8", "accent": "#0A3BA8", "ink": "#0B1B3F",
           "font": "Heebo", "dir": "rtl", "name": "AI NEWS <b>ISRAEL</b>",
           "tag": "חדשות בינה מלאכותית", "handle": "@ainews.israel"},
}

CSS = """
@font-face{font-family:Inter;src:url("FONTS/Inter.ttf")}
@font-face{font-family:Heebo;src:url("FONTS/Heebo-Variable.ttf")}
*{margin:0;padding:0;box-sizing:border-box}
html,body{width:1080px;height:HEIGHTpx;overflow:hidden;background:BAR}
body{font-family:FONT,sans-serif;direction:DIR;display:flex;flex-direction:column}
.top{background:BAR;padding:34px 36px 36px}
.brand{display:flex;align-items:center;justify-content:space-between;
  direction:ltr;color:#fff;margin-bottom:28px}
.name{font-family:Inter,sans-serif;font-weight:800;font-size:46px;
  letter-spacing:1px}
.name b{color:ACCENTBARCLR;font-weight:800}
.tag{font-weight:700;font-size:24px;letter-spacing:2px;opacity:.85;
  border:2px solid rgba(255,255,255,.55);border-radius:6px;padding:6px 14px}
.box{background:#fff;padding:30px 36px 34px;text-align:center}
.kicker{display:inline-block;font-weight:800;font-size:34px;color:ACCENT;
  border-bottom:5px solid ACCENT;padding-bottom:2px;margin-bottom:14px}
h1{font-weight:850;font-size:66px;line-height:1.13;color:INK;
  letter-spacing:-.5px;text-wrap:balance}
.photo{flex:1;position:relative;overflow:hidden;background:#111}
.photo img{width:100%;height:100%;object-fit:cover;object-position:FOCUS}
.credit{position:absolute;bottom:18px;LEFT:22px;color:#fff;font-size:20px;
  font-family:Inter,sans-serif;opacity:.85;text-shadow:0 1px 4px rgba(0,0,0,.8);
  direction:ltr}
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


def _h(c):
    # reel = 9:16 first frame / persistent top overlay (same brand system)
    return 1920 if c.get("format") == "reel" else 1350


def card_html(c):
    t = THEMES[c["lang"]]
    css = CSS
    for k, v in (("FONTS", FONTS), ("ACCENTBARCLR", "#D97757" if c["lang"] == "en" else "#9EC1FF"),
                 ("BAR", t["bar"]), ("INK", t["ink"]), ("ACCENT", t["accent"]), ("FONT", t["font"]), ("DIR", t["dir"]),
                 ("FOCUS", c.get("focus", "50% 40%")), ("HEIGHT", str(_h(c))),
                 ("LEFT", "left" if c["lang"] == "en" else "right"),
                 ("RIGHT", "right" if c["lang"] == "en" else "left")):
        css = css.replace(k, v)
    kicker = (f'<div class="kicker">{html.escape(c["kicker"])}</div><br>'
              if c.get("kicker") else "")
    photo = "file://" + os.path.abspath(c["photo"])
    return f"""<!doctype html><html lang="{c['lang']}"><meta charset="utf-8">
<style>{css}{REEL_CSS if c.get("format") == "reel" else ""}</style><body>
<div class="top"><div class="brand"><div class="name">{t['name']}</div>
<div class="tag">{t['tag']}</div></div>
<div class="box">{kicker}<h1>{html.escape(c['headline'])}</h1></div></div>
<div class="photo"><img src="{photo}">
<div class="credit">{html.escape(c.get('credit', ''))}</div>
<div class="handle">{t['handle']}</div></div>{FIT_JS}</body></html>"""


def render_card(c, out_png):
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False) as f:
        f.write(card_html(c))
    subprocess.run([CHROME, "--headless", "--disable-gpu", "--hide-scrollbars",
                    "--allow-file-access-from-files", f"--screenshot={out_png}",
                    f"--window-size=1080,{_h(c)}", "--virtual-time-budget=4000",
                    f"file://{f.name}"], check=True, capture_output=True)
    os.unlink(f.name)
    return out_png


if __name__ == "__main__":
    render_card(json.load(open(sys.argv[1])), sys.argv[2])
