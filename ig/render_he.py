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
import html, json, os, re, subprocess, sys, tempfile

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
        filter:blur(50px) brightness(.65) saturate(1.4);z-index:0}
.glow{position:absolute;left:50%;top:58%;width:1400px;height:1400px;z-index:0;
      transform:translate(-50%,-50%);
      background:radial-gradient(circle,rgba(217,119,87,.22) 0%,rgba(0,0,0,0) 60%)}
.artbg{position:absolute;inset:0;z-index:0;background-size:cover;background-position:center}
.artdim{position:absolute;inset:0;z-index:1;
        background:linear-gradient(180deg,rgba(5,5,5,.2) 0%,rgba(5,5,5,.3) 40%,
        rgba(5,5,5,.7) 76%,rgba(5,5,5,.78) 100%)}
.artdim.heavy{background:rgba(5,5,5,.65)}
/* masthead is the English brand line — LTR island inside the RTL page */
.masthead{display:flex;align-items:center;justify-content:center;gap:30px;
          direction:ltr;font-family:HebHead;font-size:27px;letter-spacing:.42em;
          color:#FFF;text-transform:uppercase;white-space:nowrap;text-indent:.42em;
          text-shadow:-1px -1px 0 rgba(0,0,0,.7),1px -1px 0 rgba(0,0,0,.7),
          -1px 1px 0 rgba(0,0,0,.7),1px 1px 0 rgba(0,0,0,.7),0 2px 8px rgba(0,0,0,.8)}
.masthead img{height:32px;filter:drop-shadow(0 2px 6px rgba(0,0,0,.7))}
.masthead:before,.masthead:after{content:"";height:2px;width:130px;background:rgba(255,255,255,.45)}
.mast-top{position:absolute;top:38px;left:0;right:0;z-index:3}
h1{font-family:HebHead;font-weight:400;font-size:SIZEpx;
   line-height:1.06;letter-spacing:0;color:#FFF}
h1 em{font-style:normal;color:#D97757;
      text-shadow:none;filter:drop-shadow(0 4px 12px rgba(0,0,0,.95)) drop-shadow(0 0 3px rgba(0,0,0,.8))}
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
              text-shadow:-2px -2px 0 rgba(0,0,0,.85),2px -2px 0 rgba(0,0,0,.85),
              -2px 2px 0 rgba(0,0,0,.85),2px 2px 0 rgba(0,0,0,.85),
              0 4px 20px rgba(0,0,0,.9),0 0 40px rgba(0,0,0,.5);
              -webkit-text-stroke:2.5px rgba(0,0,0,.55)}
.ctastrip{position:absolute;bottom:56px;left:0;right:0;z-index:3;text-align:center}
/* flex row, LTR: arrow ALWAYS renders at the RIGHT end of the strip, like the
   English covers (owner Jul 31: swipe arrows live on the right, period) */
.swipe{font-family:HebBody;font-weight:800;font-size:30px;letter-spacing:.04em;
       color:#FFF;direction:ltr;display:flex;justify-content:center;
       align-items:center;gap:14px;
       text-shadow:-1px -1px 0 rgba(0,0,0,.8),1px -1px 0 rgba(0,0,0,.8),
       -1px 1px 0 rgba(0,0,0,.8),1px 1px 0 rgba(0,0,0,.8),0 2px 10px rgba(0,0,0,.9)}
.swipe em{font-style:normal;color:#D97757}
/* badge: story-brand logo as a circular cover chip (owner example Aug 1) */
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
/* cover: full-frame image — the photo extends to the bottom of the slide
   with a gentle fade so text reads on the colorful scene (Wealth-style
   thumbnail covers, owner order Aug 22) */
body.cover .bleed{-webkit-mask-image:linear-gradient(180deg,#000 40%,rgba(0,0,0,.45) 75%,rgba(0,0,0,.25) 100%);
                  mask-image:linear-gradient(180deg,#000 40%,rgba(0,0,0,.45) 75%,rgba(0,0,0,.25) 100%)}
.shade{position:absolute;inset:0;z-index:1;
       background:linear-gradient(180deg,rgba(0,0,0,.15) 0%,rgba(0,0,0,0) 14%,
       rgba(0,0,0,0) 46%,rgba(5,5,5,.45) 62%,rgba(5,5,5,.68) 72%,rgba(5,5,5,.74) 100%)}
/* composed cover (@getintoai anatomy, owner Aug 1): backdrop < discs < cutout */
.bgblur.lite{filter:blur(34px) brightness(.65) saturate(1.2)}
.disc{position:absolute;top:110px;width:330px;height:330px;border-radius:50%;
      z-index:1;display:flex;align-items:center;justify-content:center;
      box-shadow:0 18px 60px rgba(0,0,0,.6)}
.disc.left{left:52px}.disc.right{right:52px}
.disc.dark{background:radial-gradient(circle at 35% 30%,#1a1a20 0%,#050507 80%);
           box-shadow:0 18px 60px rgba(0,0,0,.6),inset 0 0 0 2px rgba(255,255,255,.09)}
.disc.dark img{width:60%;filter:drop-shadow(0 6px 18px rgba(0,0,0,.6))}
.disc.cream{background:#EFE6D5}
.disc .dtxt{font-family:HebHead;font-size:72px;color:#12100c;text-transform:uppercase;
            text-align:center;line-height:1.05;padding:0 28px}
.cut{position:absolute;top:30px;left:0;right:0;height:900px;z-index:1;
     display:flex;justify-content:center;align-items:flex-end;
     -webkit-mask-image:linear-gradient(180deg,#000 calc(100% - 90px),rgba(0,0,0,0) 100%);
     mask-image:linear-gradient(180deg,#000 calc(100% - 90px),rgba(0,0,0,0) 100%)}
.cut img{max-width:100%;max-height:100%;object-fit:contain;
         filter:drop-shadow(0 24px 60px rgba(0,0,0,.55))}
body.content .frame{position:relative;z-index:2;height:1350px;display:flex;
                    flex-direction:column;justify-content:flex-end;
                    padding:104px 44px 56px}
/* center top (Aug 14): briefs now compose top-heavy for the square
   window, so the crop must always come off the BOTTOM, never the face */
body.content .bleed{background-position:center top}
body.content h1{margin-bottom:28px;text-shadow:0 4px 14px rgba(0,0,0,.9)}
body.content .body{text-shadow:0 3px 12px rgba(0,0,0,.85)}
body.content.nomedia .frame{justify-content:center;padding-top:60px}
/* profile-card content slide (@techskills anatomy, owner example Aug 1) */
body.card .frame{position:relative;z-index:2;height:1350px;display:flex;
                 flex-direction:column;padding:170px 66px 78px;gap:48px}
body.card .body{font-size:43px;line-height:1.55;font-weight:600}
body.card .body em{font-style:normal;color:#D97757;font-weight:800}
body.card .photocard{flex:1;min-height:0;border-radius:30px;
                     background-size:cover;background-position:center top;
                     border:2px solid rgba(217,119,87,.45);
                     box-shadow:0 20px 60px rgba(0,0,0,.65)}
body.card.nomedia .frame{justify-content:center;padding-top:120px}
/* pattern-break slide (owner order Aug 18, ported from render.py): solid
   brand orange, huge dark type — the mid-carousel visual interrupt */
body.break{background:#D97757}
body.break .frame{position:relative;z-index:2;height:1350px;display:flex;
                  flex-direction:column;justify-content:center;
                  text-align:center;padding:0 44px}
body.break h1{color:#0E0E10;text-shadow:none;-webkit-text-stroke:0;
              line-height:.98;margin-bottom:44px}
body.break .body{color:#0E0E10;text-shadow:none;font-weight:700}
body.break .masthead{color:#0E0E10}
body.break .masthead img{filter:brightness(0)}
body.break .masthead:before,body.break .masthead:after{background:rgba(14,14,16,.55)}
/* save-close recap (owner order Aug 18): checklist beats with orange ticks */
.recap{display:inline-block;text-align:right;margin:0 auto 48px;
       font-size:40px;line-height:1.42;font-weight:600;color:#FFF;
       text-shadow:0 3px 12px rgba(0,0,0,.85)}
.recap .row{display:flex;gap:24px;align-items:flex-start;margin-bottom:22px}
.recap .row:last-child{margin-bottom:0}
.recap .tick{color:#D97757;font-weight:800;flex-shrink:0}
.recap b{font-weight:800}
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
/* photo CTA (@technology closing slide): cover anatomy + follow pill */
body.ctaphoto .ctarow{text-align:center;margin-top:38px}
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
  function push(w,em){
    // punctuation-only token (comma stranded after an </em> boundary) glues
    // onto the previous word — a floating "," renders as " . " (Aug 3 bug)
    if(/^[,.!?:;]+$/.test(w)&&words.length)words[words.length-1].t+=w;
    else words.push({t:w,em:em});
  }
  h.childNodes.forEach(function(n){
    if(n.nodeType===3)n.textContent.trim().split(/\\s+/).filter(Boolean)
      .forEach(function(w){push(w,false)});
    else if(n.tagName==='EM')n.textContent.trim().split(/\\s+/).filter(Boolean)
      .forEach(function(w){push(w,true)});
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
  var divs=lines.map(function(ln,i){
    var d=document.createElement('div');
    d.style.whiteSpace='nowrap';
    d.style.fontSize=(base*scales[i])+'px';
    d.innerHTML=ln.map(function(w){return w.em?'<em>'+w.t+'</em>':w.t}).join(' ');
    h.appendChild(d);
    return d;
  });
  /* INK GUARD (ported from render.py, Aug 19 post-mortem: descenders printed
     ON TOP of the next line on long multi-line covers — Hebrew has real
     descenders too: ך ן ף ץ ק). The tight stack stays; real glyph ink,
     measured via canvas TextMetrics, must never collide — push a line down
     by exactly the overlap (plus 2px air) only when the pair would touch. */
  var cvs=document.createElement('canvas').getContext('2d');
  var prevInk=null,prevBox=null;
  divs.forEach(function(d){
    var f=parseFloat(d.style.fontSize),cs=getComputedStyle(d);
    cvs.font=cs.fontWeight+' '+f+'px '+cs.fontFamily;
    var m=cvs.measureText(d.textContent);
    if(m.fontBoundingBoxAscent===undefined)return; // old engine: no guard
    var box=d.getBoundingClientRect().height;
    var half=(box-(m.fontBoundingBoxAscent+m.fontBoundingBoxDescent))/2;
    var baseline=half+m.fontBoundingBoxAscent;
    if(prevInk!==null){
      var over=prevInk+2-prevBox-(baseline-m.actualBoundingBoxAscent);
      if(over>0)d.style.marginTop=over+'px';
    }
    prevInk=baseline+m.actualBoundingBoxDescent;
    prevBox=box;
  });
}
/* scrim(): same engine as render.py. COVER (owner Aug 1): black band starts
   AT the wordmark, one tight fade above it, no dimmed leftovers. CONTENT:
   photo fades exactly into the first text line — zero dead band. */
function scrim(){
  var bleed=document.querySelector('.bleed'),shade=document.querySelector('.shade');
  var cut=document.querySelector('.cut');
  /* ALL bleeds get the same height: the person_layer overlay is a second
     .bleed that must keep the exact crop+fade of the base scene */
  var bleeds=document.querySelectorAll('.bleed');
  function setH(h){bleeds.forEach(function(b){b.style.height=h+'px'})}
  if(!(bleed||cut)||!shade)return;
  var mast=document.querySelector('body.cover .frame .masthead');
  if(mast){
    var edge=Math.max(420,Math.min(1350,Math.round(mast.getBoundingClientRect().top)+12));
    if(bleed)setH(1350);
    if(cut)cut.style.height=(edge+24)+'px';
    shade.style.background='linear-gradient(180deg,rgba(0,0,0,.08) 0px,rgba(0,0,0,0) 140px,'
      +'rgba(0,0,0,0) '+(edge-190)+'px,rgba(0,0,0,.3) '+(edge-70)+'px,'
      +'rgba(0,0,0,.48) '+edge+'px,rgba(0,0,0,.52) 1350px)';
    return;
  }
  var anchor=document.querySelector('body.content .frame h1');
  if(!anchor)return;
  var top=anchor.getBoundingClientRect().top;
  var edge=Math.max(420,Math.min(1350,Math.round(top)+120));
  setH(edge);
  shade.style.background='linear-gradient(180deg,rgba(0,0,0,.25) 0px,rgba(0,0,0,0) 140px,'
    +'rgba(0,0,0,0) '+Math.max(140,edge-330)+'px,rgba(5,5,5,.55) '+Math.max(200,edge-150)+'px,'
    +'rgba(5,5,5,.72) '+edge+'px,rgba(5,5,5,.78) 1350px)';
}
/* fitSwipe (ported from render.py, Aug 19): the strip is physically ONE
   line, shrinking its font to fit, so its height can never grow into the
   bottom-anchored headline's zone. */
function fitSwipe(){
  var s=document.querySelector('.ctastrip .swipe');
  if(!s)return;
  s.style.whiteSpace='nowrap';
  var avail=s.parentNode.clientWidth-48;
  var f=parseFloat(getComputedStyle(s).fontSize);
  while(s.scrollWidth>avail&&f>15){f-=1;s.style.fontSize=f+'px'}
}
document.fonts.ready.then(function(){
  var h=document.querySelector('body.cover h1');
  if(h)fitLines(h);
  fitSwipe();
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

# brand-accurate disc colors (owner Aug 3: "Tesla is red... they both look
# exactly the same and are boring") — mirrors render.py
DISC_BG = {"tesla": "#E31937", "spacex": "#005288", "nvidia": "#76B900",
           "meta": "#0064E0", "reddit": "#FF4500", "ycombinator": "#FB651E"}


def discs_html(s):
    """1-2 logo/text discs for a cover (composed OR full-bleed situation)."""
    out = ""
    for di, d in enumerate(s.get("discs", [])[:2]):
        side = "left" if di == 0 else "right"
        if d.get("logo") and os.path.exists(
                os.path.join(HERE, "logos", f'{d["logo"]}.svg')):
            tint = DISC_BG.get(d["logo"])
            style = f' style="background:{tint}"' if tint else ""
            out += (f'<div class="disc {side} dark"{style}>'
                    f'<img src="{HERE}/logos/{d["logo"]}.svg"></div>')
        elif d.get("text"):
            out += (f'<div class="disc {side} cream">'
                    f'<span class="dtxt">{d["text"]}</span></div>')
    return out


def slide_html(s, handle, total, fallback_media=None):
    css = (CSS.replace("FONTS", HERE + "/fonts")
              .replace("SIZE", str(s.get("hsize", 100))))
    media = os.path.join(HERE, s["media"]) if s.get("media") else None

    if s["type"] == "cover":
        css = css.replace(f"font-size:{s.get('hsize', 100)}px",
                          f"font-size:{int(s.get('hsize', 100) * 1.7)}px", 1)
        # arrow on the RIGHT side pointing right, same as the English covers
        # (owner Jul 31: the left-pointing arrow read as reversed)
        # kicker (forensic Aug 2): the strip carries the story's second beat
        # when the writer supplied one, else the generic swipe prompt
        if s.get("video"):
            swipe = '<span>הסרטון המלא בתמונה הבאה</span><em>&#8594;</em>'
        elif (s.get("kicker") or "").strip():
            kick = html.escape(re.sub(r"<[^>]+>", "", s["kicker"]).strip())
            swipe = f'<span>{kick}</span><em>&#8594;</em>'
        else:
            swipe = '<span>החליקו לעוד</span><em>&#8594;</em>'
        logos = ""
        if s.get("badge_logo") and os.path.exists(
                os.path.join(HERE, "logos", f'{s["badge_logo"]}.svg')):
            logos = (f'<div class="badge">'
                     f'<img src="{HERE}/logos/{s["badge_logo"]}.svg"></div>')
        elif s.get("logos"):
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
        elif s.get("cutout") and os.path.exists(os.path.join(HERE, s["cutout"])):
            # composed cover (@getintoai anatomy): backdrop < discs < cutout;
            # disc text stays as-authored (usually Latin product names)
            cut = os.path.join(HERE, s["cutout"])
            discs = discs_html(s)
            back = (f'<div class="bgblur lite" style="background-image:url(\'{media}\')"></div>'
                    if media else art_bg(s["headline"]))
            bg = f'{back}{discs}<div class="cut"><img src="{cut}"></div><div class="shade"></div>'
            cls = "cover composed"
        elif media:
            # situation cover (owner Aug 3): generated scene full-bleed,
            # brand discs may ride on top. person_layer (owner Aug 3, $750B
            # cover: disc clipped the hair): person from the SAME image
            # re-draws OVER the discs with identical .bleed CSS — logos sit
            # behind the person, the person wins collisions.
            discs = discs_html(s)
            person = ""
            pl = s.get("person_layer")
            if pl and os.path.exists(os.path.join(HERE, pl)):
                person = (f'<div class="bleed" style="background-image:'
                          f'url(\'{os.path.join(HERE, pl)}\')"></div>')
            bg = (f'<div class="bgblur" style="background-image:url(\'{media}\')"></div>'
                  f'<div class="bleed" style="background-image:url(\'{media}\')"></div>'
                  f'{discs}{person}<div class="shade"></div>')
            cls = "cover"
        else:
            bg = art_bg(s["headline"])
            cls = "cover nophoto"
        # no subline (owner Aug 1): headline + swipe strip only
        return f'''<!doctype html><meta charset="utf-8"><style>{css}</style>
<body class="{cls}">{bg}{logos}
<div class="frame">{masthead()}<h1>{s["headline"]}</h1></div>
<div class="ctastrip"><div class="swipe">{swipe}</div></div>{FIT_JS}</body>'''

    if s["type"] == "cta":
        # save-close recap (owner order Aug 18, ported from render.py): a body
        # of 3+ lines renders as a checklist + the last line as send-line
        lines = [l.strip() for l in (s.get("body") or "").split("\n")
                 if l.strip()]
        if len(lines) >= 3:
            rows = "".join(f'<div class="row"><span class="tick">✓</span>'
                           f'<span>{bidi(l)}</span></div>' for l in lines[:-1])
            recap = f'<div><div class="recap">{rows}</div></div>'
            sub = f'<p class="cta-sub">{bidi(lines[-1])}</p>'
        else:
            recap = ""
            sub = (f'<p class="cta-sub">{bidi(s["body"]).replace(chr(10), "<br>")}</p>'
                   if lines else "")
        if media:
            # photo CTA (@technology closing slide, owner Aug 1): the generated
            # CEO-with-product shot full-bleed with cover anatomy
            bg = (f'<div class="bgblur" style="background-image:url(\'{media}\')"></div>'
                  f'<div class="bleed" style="background-image:url(\'{media}\')"></div><div class="shade"></div>')
            return f'''<!doctype html><meta charset="utf-8"><style>{css}</style>
<body class="cover ctaphoto">{bg}
<div class="frame">{masthead()}<h1>{s["headline"]}</h1>{recap}
<div class="ctarow"><span class="pill">עקבו אחרי <bdi>{handle}</bdi></span></div>{sub}</div>{FIT_JS}</body>'''
        return f'''<!doctype html><meta charset="utf-8"><style>{css}</style>
<body class="cta">{art_bg(s["headline"], heavy=True)}
<div class="frame">{masthead()}
<h1>{s["headline"]}</h1>{recap}
<div><span class="pill">עקבו אחרי <bdi>{handle}</bdi></span></div>
{sub}
</div></body>'''

    # pattern-break slide (owner order Aug 18): solid orange, huge dark type
    if s["type"] == "content" and s.get("layout") == "break":
        body = (f'<p class="body">{bidi(s["body"]).replace(chr(10), "<br>")}</p>'
                if (s.get("body") or "").strip() else "")
        return f'''<!doctype html><meta charset="utf-8"><style>{css}</style>
<body class="break">
<div class="mast-top">{masthead()}</div>
<div class="frame">
<h1>{s["headline"]}</h1>{body}</div></body>'''

    # profile-card content slide (@techskills anatomy, owner example Aug 1)
    if s["type"] == "content" and s.get("layout") == "card":
        card = (f'<div class="photocard" style="background-image:url(\'{media}\')"></div>'
                if media else "")
        return f'''<!doctype html><meta charset="utf-8"><style>{css}</style>
<body class="card{"" if media else " nomedia"}">{art_bg(s.get("body", ""))}
<div class="mast-top">{masthead()}</div>
<div class="frame">
<p class="body">{bidi(s["body"]).replace(chr(10), "<br>")}</p>{card}</div></body>'''

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
