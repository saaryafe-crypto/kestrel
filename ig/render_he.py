#!/usr/bin/env python3
"""Hebrew (RTL) renderer for the @ainews.israel arm — a sibling of render.py,
never a patch to it (owner rule Jul 29: the English system is frozen, the
Hebrew arm only ADDS files).

Same design language as render.py (black bg, orange #D97757 accents, masthead
with hairline rules, photo-bleed anatomy) with the RTL deltas:
  - Hebrew fonts: Anton -> Secular One (display), Poppins -> Heebo (body).
    Anton/Poppins carry zero Hebrew glyphs — text would render tofu.
  - direction:rtl on all reading text; the masthead brand line stays LTR
    English ("AI NEWS ISRAEL") per owner: the tag stays as usual, only the
    words flow right-to-left. Drop art/wordmark-he.png to replace the text
    masthead with an image one.
  - Swipe/CTA strings in Hebrew ("swipe left" — IG advances leftward).
Usage: python3 render_he.py post-he.json out_dir/"""
import json, os, subprocess, sys, tempfile

CHROME = os.environ.get("CHROME",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
HERE = os.path.dirname(os.path.abspath(__file__))

CSS = """
@font-face{font-family:HebHead;src:url("FONTS/SecularOne-Regular.ttf")}
@font-face{font-family:HebBody;src:url("FONTS/Heebo-Variable.ttf");font-weight:100 900}
*{margin:0;box-sizing:border-box}
html,body{width:1080px;height:1350px;overflow:hidden}
body{background:#050505;font-family:HebBody,sans-serif;color:#FFF;position:relative;
     direction:rtl}
.bgblur{position:absolute;inset:-80px;background-size:cover;background-position:center;
        filter:blur(50px) brightness(.22) saturate(.9);z-index:0}
.glow{position:absolute;left:50%;top:58%;width:1400px;height:1400px;z-index:0;
      transform:translate(-50%,-50%);
      background:radial-gradient(circle,rgba(217,119,87,.13) 0%,rgba(0,0,0,0) 60%)}
.artbg{position:absolute;inset:0;z-index:0;background-size:cover;background-position:center}
.artdim{position:absolute;inset:0;z-index:1;
        background:linear-gradient(180deg,rgba(5,5,5,.3) 0%,rgba(5,5,5,.45) 40%,
        rgba(5,5,5,.9) 76%,#050505 100%)}
.artdim.heavy{background:rgba(5,5,5,.82)}
/* masthead is the English brand line — LTR island inside the RTL page */
.masthead{display:flex;align-items:center;justify-content:center;gap:30px;
          direction:ltr;font-family:HebHead;font-size:27px;letter-spacing:.42em;
          color:#FFF;text-transform:uppercase;white-space:nowrap;text-indent:.42em}
.masthead img{height:32px;filter:drop-shadow(0 2px 6px rgba(0,0,0,.7))}
.masthead:before,.masthead:after{content:"";height:2px;width:130px;background:rgba(255,255,255,.45)}
.mast-top{position:absolute;top:38px;left:0;right:0;z-index:3}
h1{font-family:HebHead;font-weight:400;font-size:SIZEpx;
   line-height:1.06;letter-spacing:0;color:#FFF}
h1 em{font-style:normal;color:#D97757;
      text-shadow:none;filter:drop-shadow(0 4px 10px rgba(0,0,0,.85))}
.body{font-size:39px;line-height:1.42;font-weight:600;color:#FFF}
.body b{font-weight:800}
body.cover .frame{position:relative;z-index:2;height:1350px;display:flex;
                  flex-direction:column;justify-content:flex-end;
                  text-align:center;padding:0 12px 100px}
body.cover .masthead{font-size:24px;letter-spacing:.34em;text-indent:0;
                     margin-bottom:26px;gap:24px}
body.cover .masthead span{display:flex;align-items:center}
body.cover .masthead img{height:28px}
body.cover .masthead:before,body.cover .masthead:after{width:110px;height:3px;
                     background:rgba(255,255,255,.9)}
body.cover h1{line-height:.92;letter-spacing:0;
              text-shadow:0 4px 14px rgba(0,0,0,.9),0 0 3px rgba(0,0,0,.8);
              -webkit-text-stroke:1px rgba(0,0,0,.35)}
.ctastrip{position:absolute;bottom:56px;left:0;right:0;z-index:3;text-align:center}
/* flex row, LTR: arrow ALWAYS renders at the RIGHT end of the strip, like the
   English covers (owner Jul 31: swipe arrows live on the right, period) */
.swipe{font-family:HebBody;font-weight:800;font-size:30px;letter-spacing:.04em;
       color:#FFF;direction:ltr;display:flex;justify-content:center;
       align-items:center;gap:14px}
.swipe em{font-style:normal;color:#D97757}
.subline{font-family:HebBody;font-weight:800;font-size:56px;letter-spacing:.01em;
         color:#FFF;margin-top:18px}
.logorow{position:absolute;top:110px;left:0;right:0;z-index:2;
         display:flex;align-items:center;justify-content:center;gap:70px}
.logorow img{height:170px;max-width:440px;object-fit:contain;
             filter:drop-shadow(0 8px 34px rgba(0,0,0,.9))}
.logorow .vs{font-family:HebHead;font-size:120px;color:#D97757;
             text-shadow:0 6px 26px rgba(0,0,0,.9)}
body.nophoto .logorow{top:150px;height:44%}
body.nophoto .logorow img{height:230px;max-width:480px}
/* photo bleed: extends DOWN TO the caption block (height set by scrim() after
   text layout — no fixed band, no dead space). Bottom 300px feathered via mask;
   the "black" is a scrim anchored to the text top, never a solid empty block. */
.bleed{position:absolute;top:0;left:0;right:0;height:66%;z-index:0;
       background-size:cover;background-position:center top;
       -webkit-mask-image:linear-gradient(180deg,#000 calc(100% - 300px),rgba(0,0,0,0) 100%);
       mask-image:linear-gradient(180deg,#000 calc(100% - 300px),rgba(0,0,0,0) 100%)}
.bleed.collage{display:flex;gap:6px}
.bleed.collage .col{flex:1;background-size:cover;background-position:center top}
.shade{position:absolute;inset:0;z-index:1;
       background:linear-gradient(180deg,rgba(0,0,0,.25) 0%,rgba(0,0,0,0) 14%,
       rgba(0,0,0,0) 46%,rgba(5,5,5,.6) 62%,rgba(5,5,5,.9) 72%,rgba(5,5,5,.94) 100%)}
body.content .frame{position:relative;z-index:2;height:1350px;display:flex;
                    flex-direction:column;justify-content:flex-end;
                    padding:104px 44px 56px}
body.content .bleed{background-position:center}
body.content h1{margin-bottom:28px;text-shadow:0 4px 14px rgba(0,0,0,.9)}
body.content .body{text-shadow:0 3px 12px rgba(0,0,0,.85)}
body.content.nomedia .frame{justify-content:center;padding-top:60px}
body.cta .frame{position:relative;z-index:2;height:1350px;display:flex;
                flex-direction:column;justify-content:center;text-align:center;
                padding:0 44px}
body.cta .masthead{margin-bottom:44px}
body.cta h1{margin-bottom:56px}
.pill{display:inline-block;background:#D97757;color:#FFF;font-family:HebHead;
      font-size:52px;letter-spacing:.02em;
      padding:26px 70px;border-radius:999px}
.pill bdi{unicode-bidi:embed}
.cta-sub{font-size:38px;line-height:1.5;font-weight:600;max-width:24ch;margin:48px auto 0}
.cta-sub b{font-weight:800}
"""

def bidi(t):
    """@handles are LTR islands — bare inside RTL text the @ flips to the
    wrong side (seen on the first live render: "ainews.israel@")."""
    import re
    return re.sub(r"@[\w.]+", lambda m: f'<bdi dir="ltr">{m.group(0)}</bdi>', t)


def masthead():
    """art/wordmark-he.png if the owner drops one; else the English brand text
    (the brand tag stays LTR English — owner spec Jul 29)."""
    wm = os.path.join(HERE, "art", "wordmark-he.png")
    if os.path.exists(wm):
        return f'<div class="masthead"><span><img src="{wm}"></span></div>'
    return '<div class="masthead"><span>AI NEWS ISRAEL</span></div>'

# Same fit engine as render.py: greedy wrap, block cap, orphan rebalance,
# per-line scale to fill the frame. Bidi note: words are stored in LOGICAL
# order and each line div inherits direction:rtl, so the browser lays Hebrew
# right-to-left (with Latin brand names as embedded LTR runs) on its own.
FIT_JS = """<script>
function fitLines(h){
  var target=h.clientWidth, base=parseFloat(getComputedStyle(h).fontSize);
  var words=[];
  h.childNodes.forEach(function(n){
    if(n.nodeType===3)n.textContent.trim().split(/\\s+/).filter(Boolean)
      .forEach(function(w){words.push({t:w,em:false})});
    else if(n.tagName==='EM')n.textContent.trim().split(/\\s+/).filter(Boolean)
      .forEach(function(w){words.push({t:w,em:true})});
  });
  if(!words.length)return;
  var meas=document.createElement('span');
  meas.style.cssText='position:absolute;visibility:hidden;white-space:nowrap';
  meas.style.fontSize=base+'px';
  h.appendChild(meas);
  function width(ws){meas.textContent=ws.map(function(w){return w.t}).join(' ');
    return meas.getBoundingClientRect().width;}
  function wrap(){
    var lines=[],cur=[];
    words.forEach(function(w){
      cur.push(w);
      if(width(cur)>target&&cur.length>1){cur.pop();lines.push(cur);cur=[w];}
    });
    if(cur.length)lines.push(cur);
    return lines;
  }
  var MAXH=400, LH=.92;             // Secular One sits taller than Anton
  var lines=wrap();
  for(var i=0;i<4&&lines.length*base*LH>MAXH;i++){
    base=MAXH/(lines.length*LH);
    meas.style.fontSize=base+'px';
    lines=wrap();
  }
  while(lines.length>1&&lines[lines.length-2].length>1
        &&width(lines[lines.length-1])<target*.55){
    lines[lines.length-1].unshift(lines[lines.length-2].pop());
  }
  var scales=lines.map(function(ln){
    return Math.max(.72,Math.min(1.18,target/width(ln)));
  });
  meas.remove();
  h.innerHTML='';
  lines.forEach(function(ln,i){
    var d=document.createElement('div');
    d.style.whiteSpace='nowrap';
    d.style.fontSize=(base*scales[i])+'px';
    d.innerHTML=ln.map(function(w){return w.em?'<em>'+w.t+'</em>':w.t}).join(' ');
    h.appendChild(d);
  });
}
function fitOne(el){
  el.style.whiteSpace='nowrap';
  var target=el.parentElement.clientWidth*.86;
  var w=el.getBoundingClientRect().width;
  if(w>target)el.style.fontSize=(parseFloat(getComputedStyle(el).fontSize)*target/w)+'px';
}
/* scrim(): photo fades exactly into the first text line — zero dead band,
   any caption length (same engine as render.py) */
function scrim(){
  var bleed=document.querySelector('.bleed'),shade=document.querySelector('.shade');
  if(!bleed||!shade)return;
  var anchor=document.querySelector('body.cover .frame .masthead')
           ||document.querySelector('body.content .frame h1');
  if(!anchor)return;
  var top=anchor.getBoundingClientRect().top;
  var edge=Math.max(420,Math.min(1350,Math.round(top)+120));
  bleed.style.height=edge+'px';
  shade.style.background='linear-gradient(180deg,rgba(0,0,0,.25) 0px,rgba(0,0,0,0) 140px,'
    +'rgba(0,0,0,0) '+Math.max(140,edge-330)+'px,rgba(5,5,5,.55) '+Math.max(200,edge-150)+'px,'
    +'rgba(5,5,5,.9) '+edge+'px,rgba(5,5,5,.94) 1350px)';
}
document.fonts.ready.then(function(){
  var h=document.querySelector('body.cover h1');
  if(h)fitLines(h);
  var s=document.querySelector('.subline');
  if(s)fitOne(s);
  scrim();
});
</script>"""

def art_bg(seed, heavy=False):
    import glob, zlib
    arts = sorted(glob.glob(os.path.join(HERE, "art", "backdrop-*.jpg")))
    if not arts:
        return '<div class="glow"></div>'
    pick = arts[zlib.crc32(seed.encode()) % len(arts)]
    return (f'<div class="artbg" style="background-image:url(\'{pick}\')"></div>'
            f'<div class="artdim{" heavy" if heavy else ""}"></div>')

def slide_html(s, handle, total, fallback_media=None):
    css = (CSS.replace("FONTS", HERE + "/fonts")
              .replace("SIZE", str(s.get("hsize", 100))))
    media = os.path.join(HERE, s["media"]) if s.get("media") else None

    if s["type"] == "cover":
        css = css.replace(f"font-size:{s.get('hsize', 100)}px",
                          f"font-size:{int(s.get('hsize', 100) * 1.7)}px", 1)
        # arrow on the RIGHT side pointing right, same as the English covers
        # (owner Jul 31: the left-pointing arrow read as reversed)
        swipe = ('<span>הסרטון המלא בתמונה הבאה</span><em>&#8594;</em>' if s.get("video")
                 else '<span>החליקו לעוד</span><em>&#8594;</em>')
        logos = ""
        if s.get("logos"):
            imgs = '<span class="vs">×</span>'.join(
                f'<img src="{HERE}/logos/{l}.svg">' for l in s["logos"])
            logos = f'<div class="logorow">{imgs}</div>'
        if s.get("media_list"):
            first = os.path.join(HERE, s["media_list"][0])
            cols = "".join(f'<div class="col" style="background-image:url(\'{os.path.join(HERE, m)}\')"></div>'
                           for m in s["media_list"])
            bg = (f'<div class="bgblur" style="background-image:url(\'{first}\')"></div>'
                  f'<div class="bleed collage">{cols}</div><div class="shade"></div>')
            cls = "cover"
        elif media:
            bg = (f'<div class="bgblur" style="background-image:url(\'{media}\')"></div>'
                  f'<div class="bleed" style="background-image:url(\'{media}\')"></div><div class="shade"></div>')
            cls = "cover"
        else:
            bg = art_bg(s["headline"])
            cls = "cover nophoto"
        subline = f'<div class="subline">{s["subline"]}</div>' if s.get("subline") else ""
        return f'''<!doctype html><meta charset="utf-8"><style>{css}</style>
<body class="{cls}">{bg}{logos}
<div class="frame">{masthead()}<h1>{s["headline"]}</h1>{subline}</div>
<div class="ctastrip"><div class="swipe">{swipe}</div></div>{FIT_JS}</body>'''

    if s["type"] == "cta":
        return f'''<!doctype html><meta charset="utf-8"><style>{css}</style>
<body class="cta">{art_bg(s["headline"], heavy=True)}
<div class="frame">{masthead()}
<h1>{s["headline"]}</h1>
<div><span class="pill">עקבו אחרי <bdi>{handle}</bdi></span></div>
<p class="cta-sub">{bidi(s["body"]).replace(chr(10), "<br>")}</p>
</div></body>'''

    nomedia = "" if media else " nomedia"
    if media:
        bg = (f'<div class="bgblur" style="background-image:url(\'{media}\')"></div>'
              f'<div class="bleed" style="background-image:url(\'{media}\')"></div><div class="shade"></div>')
    elif fallback_media:  # cover photo blurred deep — never a dead-black void
        fm = os.path.join(HERE, fallback_media)
        bg = f'<div class="bgblur" style="background-image:url(\'{fm}\')"></div>'
    else:
        bg = ""
    return f'''<!doctype html><meta charset="utf-8"><style>{css}</style>
<body class="content{nomedia}">
{bg}
<div class="mast-top">{masthead()}</div>
<div class="frame">
<h1>{s["headline"]}</h1>
<p class="body">{bidi(s["body"]).replace(chr(10), "<br>")}</p></div></body>'''

def to_jpeg(png):
    jpg = png[:-4] + ".jpg"
    if sys.platform == "darwin":
        subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "92",
                        png, "--out", jpg], check=True, capture_output=True)
    else:
        from PIL import Image
        Image.open(png).convert("RGB").save(jpg, quality=92)
    os.remove(png)
    return jpg


def render(post_path, out_dir):
    post = json.load(open(post_path))
    slides = post["slides"]
    os.makedirs(out_dir, exist_ok=True)
    # image gate (Jul 31, same as render.py): a referenced photo missing on
    # disk silently renders as a black void — fail loud instead.
    for n, s in enumerate(slides, 1):
        m = s.get("media")
        if m and not os.path.exists(os.path.join(HERE, m)):
            raise SystemExit(f"slide {n} media missing on disk: {m} — refusing "
                             "to render a black slide; fix the upstream image step")
    # first available photo in the post backs imageless slides as a deep blur
    fallback = next((s.get("media") for s in slides if s.get("media")), None)
    for n, s in enumerate(slides, 1):
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False) as f:
            f.write(slide_html(s, post["handle"], len(slides), fallback))
        png = os.path.join(out_dir, f"slide-{n}.png")
        subprocess.run([CHROME, "--headless", "--disable-gpu", f"--screenshot={png}",
                        "--window-size=1080,1350", "--hide-scrollbars",
                        "--virtual-time-budget=4000",
                        f"file://{f.name}"],
                       check=True, capture_output=True)
        os.unlink(f.name)
        out = to_jpeg(png)
        size = os.path.getsize(out) if os.path.exists(out) else 0
        if size < 15000 or open(out, "rb").read(2) != b"\xff\xd8":
            raise SystemExit(f"{out} looks broken ({size} bytes) — render failed")
        print("rendered", out)
    open(os.path.join(out_dir, "caption.txt"), "w").write(post["caption"])
    print("caption written")

if __name__ == "__main__":
    render(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "out-he")
