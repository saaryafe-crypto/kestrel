#!/usr/bin/env python3
"""Renders an IG carousel (1080x1350 slides) from a post JSON.
Usage: python3 render.py post.json out_dir/

Layout spec (from @technology system analysis):
- Masthead: centered, all caps, letterspaced, hairline rules both sides.
  On the cover it sits directly above the headline (publication, not watermark).
- Cover: three zones — masthead, lower-half edge-to-edge condensed headline,
  single CTA strip at bottom with carousel dots. Cover promises a FORMAT,
  never a single story (container covers live in containers.json).
- Accent color: applied only to payload tokens — the minimum set of words that
  still communicates the claim standalone. Writer marks them with <em>.
- Content slides: photo edge-to-edge top ~58% feathered into black, headline +
  bold body below (connected, like the cover). No media -> big-type plain-black slide.
- CTA slide: exactly one CTA (the FOLLOW pill).
- Safe zone: critical type inside middle 80% vertically."""
import json, os, subprocess, sys, tempfile

CHROME = os.environ.get("CHROME",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
HERE = os.path.dirname(os.path.abspath(__file__))

CSS = """
@font-face{font-family:Anton;src:url("FONTS/Anton-Regular.ttf")}
@font-face{font-family:Poppins;src:url("FONTS/Poppins-SemiBold.ttf");font-weight:600}
@font-face{font-family:Poppins;src:url("FONTS/Poppins-ExtraBold.ttf");font-weight:800}
*{margin:0;box-sizing:border-box}
html,body{width:1080px;height:1350px;overflow:hidden}
body{background:#050505;font-family:Poppins,sans-serif;color:#FFF;position:relative}
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
.masthead{display:flex;align-items:center;justify-content:center;gap:30px;
          font-family:Anton;font-size:27px;letter-spacing:.42em;color:#FFF;
          text-transform:uppercase;white-space:nowrap;text-indent:.42em}
.masthead img{height:32px;filter:drop-shadow(0 2px 6px rgba(0,0,0,.7))}
.masthead:before,.masthead:after{content:"";height:2px;width:130px;background:rgba(255,255,255,.45)}
.mast-top{position:absolute;top:38px;left:0;right:0;z-index:3}
h1{font-family:Anton;font-weight:400;text-transform:uppercase;font-size:SIZEpx;
   line-height:1.03;letter-spacing:.004em;color:#FFF}
/* accent words: brand orange (owner call Jul 28 evening: "I prefer the
   orange and white" — sky-blue texture retired same day it arrived) */
h1 em{font-style:normal;color:#D97757;
      text-shadow:none;filter:drop-shadow(0 4px 10px rgba(0,0,0,.85))}
.body{font-size:39px;line-height:1.4;font-weight:600;color:#FFF}
.body b{font-weight:800}
/* cover: photo-dominant anatomy (photo top ~62% feathered into solid black
   band; small masthead chip; huge edge-to-edge headline; bold substrip) */
/* cover geometry = AVERAGE of 5 measured @technology covers (Jul 29,
   Desktop/ig/technology ig): headline glyphs avg 7.0% of canvas (range
   5-10.7), pitch 7.7% (lh .84), text edge-to-edge (side margin 1-3%),
   photo hard edge avg 47.5% (cutouts spill lower), headline top ~61.5%,
   last text bottom ~92% (=100px bottom pad), substrip glyphs 3.0-3.2% */
body.cover .frame{position:relative;z-index:2;height:1350px;display:flex;
                  flex-direction:column;justify-content:flex-end;
                  text-align:center;padding:0 12px 100px}
body.cover .masthead{font-size:24px;letter-spacing:.34em;text-indent:0;
                     margin-bottom:26px;gap:24px}
/* no chip behind the wordmark (owner Jul 29: the black rectangle looked awful;
   @technology's masthead sits bare on the dark band) */
body.cover .masthead span{display:flex;align-items:center}
body.cover .masthead img{height:28px}
body.cover .masthead:before,body.cover .masthead:after{width:110px;height:3px;
                     background:rgba(255,255,255,.9)}
body.cover h1{line-height:.87;letter-spacing:0;
              text-shadow:0 4px 14px rgba(0,0,0,.9),0 0 3px rgba(0,0,0,.8);
              -webkit-text-stroke:1px rgba(0,0,0,.35)}
.ctastrip{position:absolute;bottom:56px;left:0;right:0;z-index:3;text-align:center}
.swipe{font-family:Poppins;font-weight:800;font-size:27px;letter-spacing:.18em;
       color:#FFF;text-transform:uppercase;text-indent:.18em}
.swipe em{font-style:normal;color:#D97757}
/* badge: the story-brand's logo as a big circular chip on the cover photo
   (owner example Aug 1, @techskills Mercor cover — the logo is a design
   element beside the person, not a watermark). Opt-in via "badge_logo";
   the image brief must keep the subject right-of-center. */
.badge{position:absolute;top:96px;left:60px;width:310px;height:310px;
       border-radius:50%;z-index:2;display:flex;align-items:center;
       justify-content:center;
       background:radial-gradient(circle at 35% 30%,#17171d 0%,#050507 78%);
       box-shadow:0 16px 55px rgba(0,0,0,.75),inset 0 0 0 2px rgba(255,255,255,.09)}
.badge img{width:60%;filter:drop-shadow(0 6px 18px rgba(0,0,0,.65))}
.logorow{position:absolute;top:110px;left:0;right:0;z-index:2;
         display:flex;align-items:center;justify-content:center;gap:70px}
.logorow img{height:170px;max-width:440px;object-fit:contain;
             filter:drop-shadow(0 8px 34px rgba(0,0,0,.9))}
.logorow .vs{font-family:Anton;font-size:120px;color:#D97757;
             text-shadow:0 6px 26px rgba(0,0,0,.9)}
body.nophoto .logorow{top:150px;height:44%}
body.nophoto .logorow img{height:230px;max-width:480px}
/* photo bleed: extends DOWN TO the caption block (height set per-slide by
   SCRIM_JS after text layout — no fixed band, no dead space between photo and
   text for any caption length). Bottom 300px feathered via mask into the
   blurred backdrop, so the "black" is a subtle scrim over image texture,
   never a solid empty block (owner spec Jul 31). */
.bleed{position:absolute;top:0;left:0;right:0;height:66%;z-index:0;
       background-size:cover;background-position:center top;
       -webkit-mask-image:linear-gradient(180deg,#000 calc(100% - 300px),rgba(0,0,0,0) 100%);
       mask-image:linear-gradient(180deg,#000 calc(100% - 300px),rgba(0,0,0,0) 100%)}
.bleed.collage{display:flex;gap:6px}
.bleed.collage .col{flex:1;background-size:cover;background-position:center top}
/* cover: tighter feather — the photo stays bright until just above the
   wordmark seam (owner Aug 1: no dimmed leftovers between photo and logo) */
body.cover .bleed{-webkit-mask-image:linear-gradient(180deg,#000 calc(100% - 160px),rgba(0,0,0,0) 100%);
                  mask-image:linear-gradient(180deg,#000 calc(100% - 160px),rgba(0,0,0,0) 100%)}
.shade{position:absolute;inset:0;z-index:1;
       background:linear-gradient(180deg,rgba(0,0,0,.25) 0%,rgba(0,0,0,0) 14%,
       rgba(0,0,0,0) 46%,rgba(5,5,5,.6) 62%,rgba(5,5,5,.9) 72%,rgba(5,5,5,.94) 100%)}
/* composed cover (owner gold standard Aug 1, @getintoai anatomy): blurred
   story-world backdrop, 1-2 big logo/text discs at head height, the REAL
   person CUT OUT on top overlapping the discs (background < discs < person),
   feathered into the black band at the wordmark. The face is never generated;
   disc text is typeset here so it can never garble. */
.bgblur.lite{filter:blur(34px) brightness(.5) saturate(1.05)}
.disc{position:absolute;top:110px;width:330px;height:330px;border-radius:50%;
      z-index:1;display:flex;align-items:center;justify-content:center;
      box-shadow:0 18px 60px rgba(0,0,0,.6)}
.disc.left{left:52px}.disc.right{right:52px}
.disc.dark{background:radial-gradient(circle at 35% 30%,#1a1a20 0%,#050507 80%);
           box-shadow:0 18px 60px rgba(0,0,0,.6),inset 0 0 0 2px rgba(255,255,255,.09)}
.disc.dark img{width:60%;filter:drop-shadow(0 6px 18px rgba(0,0,0,.6))}
.disc.cream{background:#EFE6D5}
.disc .dtxt{font-family:Anton;font-size:72px;color:#12100c;text-transform:uppercase;
            letter-spacing:.01em;text-align:center;line-height:1.05;padding:0 28px}
.cut{position:absolute;top:30px;left:0;right:0;height:900px;z-index:1;
     display:flex;justify-content:center;align-items:flex-end;
     -webkit-mask-image:linear-gradient(180deg,#000 calc(100% - 90px),rgba(0,0,0,0) 100%);
     mask-image:linear-gradient(180deg,#000 calc(100% - 90px),rgba(0,0,0,0) 100%)}
.cut img{max-width:100%;max-height:100%;object-fit:contain;
         filter:drop-shadow(0 24px 60px rgba(0,0,0,.55))}
/* content: photo edge-to-edge top (~58%) feathered into black, text below —
   one connected composition (@technology inner-slide anatomy, owner spec Jul 28) */
body.content .frame{position:relative;z-index:2;height:1350px;display:flex;
                    flex-direction:column;justify-content:flex-end;
                    padding:104px 44px 56px}
body.content .bleed{background-position:center}
body.content h1{margin-bottom:28px;text-shadow:0 4px 14px rgba(0,0,0,.9)}
body.content .body{text-shadow:0 3px 12px rgba(0,0,0,.85)}
body.content.nomedia .frame{justify-content:center;padding-top:60px}
/* profile-card content slide (owner example Aug 1, @techskills Mercor post):
   dark brand backdrop, the story told on TOP in short paragraphs, the REAL
   photo in a rounded card below — the photo is the proof artifact */
body.card .frame{position:relative;z-index:2;height:1350px;display:flex;
                 flex-direction:column;padding:170px 66px 78px;gap:48px}
body.card .body{font-size:43px;line-height:1.52;font-weight:600}
body.card .body em{font-style:normal;color:#D97757;font-weight:800}
body.card .photocard{flex:1;min-height:0;border-radius:30px;
                     background-size:cover;background-position:center top;
                     border:2px solid rgba(217,119,87,.45);
                     box-shadow:0 20px 60px rgba(0,0,0,.65)}
body.card.nomedia .frame{justify-content:center;padding-top:120px}
/* cta */
body.cta .frame{position:relative;z-index:2;height:1350px;display:flex;
                flex-direction:column;justify-content:center;text-align:center;
                padding:0 44px}
body.cta .masthead{margin-bottom:44px}
body.cta h1{margin-bottom:56px}
.pill{display:inline-block;background:#D97757;color:#FFF;font-family:Anton;
      font-size:52px;letter-spacing:.05em;text-transform:uppercase;
      padding:26px 70px;border-radius:999px}
.cta-sub{font-size:38px;line-height:1.45;font-weight:600;max-width:24ch;margin:48px auto 0}
.cta-sub b{font-weight:800}
/* photo CTA (@technology closing slide): cover anatomy + follow pill */
body.ctaphoto .ctarow{text-align:center;margin-top:38px}
"""

# the real wordmark (owner logo Yaffeai.PNG, extracted white-on-transparent):
# pure white like @technology's masthead — never tinted, never two-tone
MASTHEAD = f'<div class="masthead"><span><img src="{HERE}/art/wordmark.png"></span></div>'

# @technology signature: EVERY headline line runs edge-to-edge — line breaks
# are chosen by greedy wrap, then each line's font is scaled to fill the frame
# width. Two hard guards added Jul 29 after the Visa cover shipped with the
# headline towering over 60% of the canvas (owner: "the letters are hige"):
# 1. TOTAL BLOCK CAP — the whole headline block may not exceed MAXH px
#    (reference covers: headline top ~61.5%, block ~25% of canvas). Too many
#    lines -> the base font shrinks and re-wraps until the block fits.
# 2. UPSCALE CLAMP 1.18 (was 1.42) + orphan rebalance — a lone short word on
#    its own line ("TOUCH") used to blow up to fill the width; now words are
#    pulled down from the line above so no line needs a big upscale.
# Runs in-page before Chrome screenshots (--virtual-time-budget lets fonts
# load first). Subline never wraps: it shrinks to stay one line.
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
  var MAXH=400, LH=.87;             // 400px block ~= 30% of the 1350 canvas
  var lines=wrap();
  for(var i=0;i<4&&lines.length*base*LH>MAXH;i++){
    base=MAXH/(lines.length*LH);
    meas.style.fontSize=base+'px';
    lines=wrap();
  }
  // orphan rebalance: pull words down until the last line is >=55% of frame
  while(lines.length>1&&lines[lines.length-2].length>1
        &&width(lines[lines.length-1])<target*.55){
    lines[lines.length-1].unshift(lines[lines.length-2].pop());
  }
  // measure each line's natural width BEFORE the rebuild (block divs report
  // container width, not text width), then scale its font to fill the frame
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
/* scrim(): after text layout, size the photo band and anchor the dark
   gradient to the text. COVER (owner spec Aug 1: "the black background starts
   from the Yaffe AI logo", no dimmed leftovers): the photo stays bright until
   ~190px above the wordmark, then ONE tight fade lands on solid black exactly
   at the wordmark line — the logo sits on the seam like the reference covers.
   CONTENT keeps the Jul 31 spec: photo fades exactly into the first text
   line, zero dead band, for any caption length. */
function scrim(){
  var bleed=document.querySelector('.bleed'),shade=document.querySelector('.shade');
  var cut=document.querySelector('.cut');
  if(!(bleed||cut)||!shade)return;
  var mast=document.querySelector('body.cover .frame .masthead');
  if(mast){
    var edge=Math.max(420,Math.min(1350,Math.round(mast.getBoundingClientRect().top)+12));
    if(bleed)bleed.style.height=(edge+50)+'px';
    if(cut)cut.style.height=(edge+24)+'px';
    shade.style.background='linear-gradient(180deg,rgba(0,0,0,.25) 0px,rgba(0,0,0,0) 140px,'
      +'rgba(0,0,0,0) '+(edge-190)+'px,rgba(5,5,5,.6) '+(edge-70)+'px,'
      +'#050505 '+edge+'px,#050505 1350px)';
    return;
  }
  var anchor=document.querySelector('body.content .frame h1');
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
  scrim();
});
</script>"""

def art_bg(seed, heavy=False):
    """Canva-made brand backdrop (ig/art/*.jpg) instead of flat black."""
    import glob, zlib
    # backdrop-*.jpg only: art/ also holds avatar.jpg (reel-card logo), which must
    # never appear as a slide background (owner: the logo-as-backdrop looked terrible)
    arts = sorted(glob.glob(os.path.join(HERE, "art", "backdrop-*.jpg")))
    if not arts:
        return '<div class="glow"></div>'
    pick = arts[zlib.crc32(seed.encode()) % len(arts)]
    return (f'<div class="artbg" style="background-image:url(\'{pick}\')"></div>'
            f'<div class="artdim{" heavy" if heavy else ""}"></div>')

def slide_html(s, handle, total, fallback_media=None):
    css = (CSS.replace("FONTS", HERE + "/fonts").replace("ARTPATH", HERE + "/art")
              .replace("SIZE", str(s.get("hsize", 100))))
    media = os.path.join(HERE, s["media"]) if s.get("media") else None

    if s["type"] == "cover":
        # cover headline renders 1.7x the writer's hsize: 5-cover reference
        # AVERAGE glyph = 7.0% of canvas (94px@1350); x1.7 puts typical
        # hsize 72 at 6.5% and hsize 80 at 7.3% — matching the range
        css = css.replace(f"font-size:{s.get('hsize', 100)}px",
                          f"font-size:{int(s.get('hsize', 100) * 1.7)}px", 1)
        swipe = 'Full video next <em>→</em>' if s.get("video") else 'Swipe for more <em>→</em>'
        logos = ""
        if s.get("badge_logo") and os.path.exists(
                os.path.join(HERE, "logos", f'{s["badge_logo"]}.svg')):
            logos = (f'<div class="badge">'
                     f'<img src="{HERE}/logos/{s["badge_logo"]}.svg"></div>')
        elif s.get("logos"):
            imgs = '<span class="vs">×</span>'.join(
                f'<img src="{HERE}/logos/{l}.svg">' for l in s["logos"])
            logos = f'<div class="logorow">{imgs}</div>'
        if s.get("media_list"):  # daily_recap collage: 2-3 press photos side by side
            first = os.path.join(HERE, s["media_list"][0])
            cols = "".join(f'<div class="col" style="background-image:url(\'{os.path.join(HERE, m)}\')"></div>'
                           for m in s["media_list"])
            bg = (f'<div class="bgblur" style="background-image:url(\'{first}\')"></div>'
                  f'<div class="bleed collage">{cols}</div><div class="shade"></div>')
            cls = "cover"
        elif s.get("cutout") and os.path.exists(os.path.join(HERE, s["cutout"])):
            # composed cover (@getintoai anatomy): backdrop < discs < cutout
            cut = os.path.join(HERE, s["cutout"])
            discs = ""
            for di, d in enumerate(s.get("discs", [])[:2]):
                side = "left" if di == 0 else "right"
                if d.get("logo") and os.path.exists(
                        os.path.join(HERE, "logos", f'{d["logo"]}.svg')):
                    discs += (f'<div class="disc {side} dark">'
                              f'<img src="{HERE}/logos/{d["logo"]}.svg"></div>')
                elif d.get("text"):
                    discs += (f'<div class="disc {side} cream">'
                              f'<span class="dtxt">{d["text"]}</span></div>')
            back = (f'<div class="bgblur lite" style="background-image:url(\'{media}\')"></div>'
                    if media else art_bg(s["headline"]))
            bg = f'{back}{discs}<div class="cut"><img src="{cut}"></div><div class="shade"></div>'
            cls = "cover composed"
        elif media:
            bg = (f'<div class="bgblur" style="background-image:url(\'{media}\')"></div>'
                  f'<div class="bleed" style="background-image:url(\'{media}\')"></div><div class="shade"></div>')
            cls = "cover"
        else:
            bg = art_bg(s["headline"])
            cls = "cover nophoto"
        # no subline (owner Aug 1): under the big words only the small swipe
        # strip renders — all the hook lives in the headline
        return f'''<!doctype html><meta charset="utf-8"><style>{css}</style>
<body class="{cls}">{bg}{logos}
<div class="frame">{MASTHEAD}<h1>{s["headline"]}</h1></div>
<div class="ctastrip"><div class="swipe">{swipe}</div></div>{FIT_JS}</body>'''

    if s["type"] == "cta":
        if media:
            # photo CTA (@technology Codex Micro closing slide, owner Aug 1
            # "the last cta is amazing it shows sam altman"): the generated
            # CEO-with-product shot full-bleed, cover anatomy — photo bright to
            # the masthead, black band below with headline + follow pill
            bg = (f'<div class="bgblur" style="background-image:url(\'{media}\')"></div>'
                  f'<div class="bleed" style="background-image:url(\'{media}\')"></div><div class="shade"></div>')
            return f'''<!doctype html><meta charset="utf-8"><style>{css}</style>
<body class="cover ctaphoto">{bg}
<div class="frame">{MASTHEAD}<h1>{s["headline"]}</h1>
<div class="ctarow"><span class="pill">Follow {handle}</span></div></div>{FIT_JS}</body>'''
        return f'''<!doctype html><meta charset="utf-8"><style>{css}</style>
<body class="cta">{art_bg(s["headline"], heavy=True)}
<div class="frame">{MASTHEAD}
<h1>{s["headline"]}</h1>
<div><span class="pill">Follow {handle}</span></div>
<p class="cta-sub">{s["body"].replace(chr(10), "<br>")}</p>
</div></body>'''

    # profile-card content slide: story text on top, real photo in a rounded
    # card below (@techskills anatomy, owner example Aug 1) — no headline
    if s["type"] == "content" and s.get("layout") == "card":
        card = (f'<div class="photocard" style="background-image:url(\'{media}\')"></div>'
                if media else "")
        return f'''<!doctype html><meta charset="utf-8"><style>{css}</style>
<body class="card{"" if media else " nomedia"}">{art_bg(s.get("body", ""))}
<div class="mast-top">{MASTHEAD}</div>
<div class="frame">
<p class="body">{s["body"].replace(chr(10), "<br>")}</p>{card}</div></body>'''

    # content
    nomedia = "" if media else " nomedia"
    if media:  # full-bleed photo feathered into black — connected, never a cropped card
        bg = (f'<div class="bgblur" style="background-image:url(\'{media}\')"></div>'
              f'<div class="bleed" style="background-image:url(\'{media}\')"></div><div class="shade"></div>')
    elif fallback_media:  # no own photo: cover's photo blurred deep as texture, so the
        fm = os.path.join(HERE, fallback_media)   # slide is never a dead-black void (Jul 31)
        bg = f'<div class="bgblur" style="background-image:url(\'{fm}\')"></div>'
    else:
        bg = ""
    return f'''<!doctype html><meta charset="utf-8"><style>{css}</style>
<body class="content{nomedia}">
{bg}
<div class="mast-top">{MASTHEAD}</div>
<div class="frame">
<h1>{s["headline"]}</h1>
<p class="body">{s["body"].replace(chr(10), "<br>")}</p></div></body>'''

def to_jpeg(png):
    jpg = png[:-4] + ".jpg"
    if sys.platform == "darwin":
        subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "92",
                        png, "--out", jpg], check=True, capture_output=True)
    else:  # ubuntu runner: Pillow (installed in the workflow)
        from PIL import Image
        Image.open(png).convert("RGB").save(jpg, quality=92)
    os.remove(png)
    return jpg


def render(post_path, out_dir):
    post = json.load(open(post_path))
    slides = post["slides"]
    os.makedirs(out_dir, exist_ok=True)
    # image gate (Jul 31: covers shipped black because a media path silently
    # 404'd inside Chrome — CSS url() failures render as nothing). A referenced
    # photo that doesn't exist on disk is a pipeline bug: fail LOUD here, never
    # publish the void.
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
                        "--virtual-time-budget=4000",  # let fonts load + FIT_JS run
                        f"file://{f.name}"],
                       check=True, capture_output=True)
        os.unlink(f.name)
        out = to_jpeg(png)  # IG's API accepts JPEG only
        # output gate: a truncated Chrome shot or sips failure must not reach
        # Instagram. 15KB floor: even an all-black text slide compresses bigger.
        size = os.path.getsize(out) if os.path.exists(out) else 0
        if size < 15000 or open(out, "rb").read(2) != b"\xff\xd8":
            raise SystemExit(f"{out} looks broken ({size} bytes) — render failed")
        print("rendered", out)
    open(os.path.join(out_dir, "caption.txt"), "w").write(post["caption"])
    print("caption written")

if __name__ == "__main__":
    render(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "out")
