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
- CTA slide: exactly one CTA (the SEND pill — sends/reach is IG's top
  discovery signal per Mosseri Jan 2025; follow asks banned owner Aug 18/27).
- Safe zone: critical type inside middle 80% vertically."""
import html, json, os, re, subprocess, sys, tempfile

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
        filter:blur(50px) brightness(.65) saturate(1.4);z-index:0}
.glow{position:absolute;left:50%;top:58%;width:1400px;height:1400px;z-index:0;
      transform:translate(-50%,-50%);
      background:radial-gradient(circle,rgba(217,119,87,.22) 0%,rgba(0,0,0,0) 60%)}
.artbg{position:absolute;inset:0;z-index:0;background-size:cover;background-position:center}
.artdim{position:absolute;inset:0;z-index:1;
        background:linear-gradient(180deg,rgba(5,5,5,.2) 0%,rgba(5,5,5,.3) 40%,
        rgba(5,5,5,.7) 76%,rgba(5,5,5,.78) 100%)}
.artdim.heavy{background:rgba(5,5,5,.65)}
.masthead{display:flex;align-items:center;justify-content:center;gap:30px;
          font-family:Anton;font-size:27px;letter-spacing:.42em;color:#FFF;
          text-transform:uppercase;white-space:nowrap;text-indent:.42em;
          text-shadow:-1px -1px 0 rgba(0,0,0,.7),1px -1px 0 rgba(0,0,0,.7),
          -1px 1px 0 rgba(0,0,0,.7),1px 1px 0 rgba(0,0,0,.7),0 2px 8px rgba(0,0,0,.8)}
.masthead img{height:32px;filter:drop-shadow(0 2px 6px rgba(0,0,0,.7))}
.masthead:before,.masthead:after{content:"";height:2px;width:130px;background:rgba(255,255,255,.45)}
.mast-top{position:absolute;top:38px;left:0;right:0;z-index:3}
h1{font-family:Anton;font-weight:400;text-transform:uppercase;font-size:SIZEpx;
   line-height:1.03;letter-spacing:.004em;color:#FFF}
/* accent words: brand orange (owner call Jul 28 evening: "I prefer the
   orange and white" — sky-blue texture retired same day it arrived) */
h1 em{font-style:normal;color:#D97757;
      text-shadow:none;filter:drop-shadow(0 4px 12px rgba(0,0,0,.95)) drop-shadow(0 0 3px rgba(0,0,0,.8))}
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
              text-shadow:-2px -2px 0 rgba(0,0,0,.85),2px -2px 0 rgba(0,0,0,.85),
              -2px 2px 0 rgba(0,0,0,.85),2px 2px 0 rgba(0,0,0,.85),
              0 4px 20px rgba(0,0,0,.9),0 0 40px rgba(0,0,0,.5);
              -webkit-text-stroke:2.5px rgba(0,0,0,.55)}
.ctastrip{position:absolute;bottom:56px;left:0;right:0;z-index:3;text-align:center}
.swipe{font-family:Poppins;font-weight:800;font-size:27px;letter-spacing:.18em;
       color:#FFF;text-transform:uppercase;text-indent:.18em;
       text-shadow:-1px -1px 0 rgba(0,0,0,.8),1px -1px 0 rgba(0,0,0,.8),
       -1px 1px 0 rgba(0,0,0,.8),1px 1px 0 rgba(0,0,0,.8),0 2px 10px rgba(0,0,0,.9)}
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
/* cover: full-frame image — the photo extends to the bottom of the slide
   with a gentle fade so text reads on the colorful scene (Wealth-style
   thumbnail covers, owner order Aug 22) */
body.cover .bleed{-webkit-mask-image:linear-gradient(180deg,#000 40%,rgba(0,0,0,.45) 75%,rgba(0,0,0,.25) 100%);
                  mask-image:linear-gradient(180deg,#000 40%,rgba(0,0,0,.45) 75%,rgba(0,0,0,.25) 100%)}
.shade{position:absolute;inset:0;z-index:1;
       background:linear-gradient(180deg,rgba(0,0,0,.15) 0%,rgba(0,0,0,0) 14%,
       rgba(0,0,0,0) 46%,rgba(5,5,5,.45) 62%,rgba(5,5,5,.68) 72%,rgba(5,5,5,.74) 100%)}
/* composed cover (owner gold standard Aug 1, @getintoai anatomy): blurred
   story-world backdrop, 1-2 big logo/text discs at head height, the REAL
   person CUT OUT on top overlapping the discs (background < discs < person),
   feathered into the black band at the wordmark. The face is never generated;
   disc text is typeset here so it can never garble. */
.bgblur.lite{filter:blur(34px) brightness(.65) saturate(1.2)}
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
/* center top (Aug 14): briefs now compose top-heavy for the square
   window, so the crop must always come off the BOTTOM, never the face */
body.content .bleed{background-position:center top}
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
/* reaction-receipt slide (owner order Sep 5, @technology Valve-post anatomy:
   mid-carousel the story's real viral post renders as an X card centered on
   a dark blurred backdrop — proof the internet is living the story, often
   the comedy beat. Typeset here so nothing can garble; data injected by
   write.py from the radar moment, never written by the model). */
body.tweet .frame{position:relative;z-index:2;height:1350px;display:flex;
                  align-items:center;justify-content:center;padding:0 64px}
.tweetcard{width:100%;background:#080809;border:2px solid rgba(255,255,255,.14);
           border-radius:28px;padding:46px 50px 40px;
           box-shadow:0 30px 90px rgba(0,0,0,.75)}
.tweetcard .thead{display:flex;align-items:center;gap:24px;margin-bottom:30px}
.tweetcard .avatar{width:84px;height:84px;border-radius:50%;flex:none;
           display:flex;align-items:center;justify-content:center;
           font-family:Anton;font-size:44px;color:#fff;
           background:radial-gradient(circle at 32% 28%,#3a3a44 0%,#141419 80%)}
.tweetcard .tname{font-size:33px;font-weight:800;color:#fff;line-height:1.15}
.tweetcard .thandle{font-size:28px;font-weight:600;color:#71767b}
.tweetcard .ttext{font-size:41px;line-height:1.34;font-weight:600;color:#fff}
.tweetcard .tmeta{margin-top:34px;font-size:27px;font-weight:600;color:#71767b}
.tweetcard .tmeta b{color:#d6d9db;font-weight:800}
/* pattern-break slide (owner order Aug 18): full visual interrupt mid-
   carousel — solid brand orange, huge dark type, ONE giant number or ≤6-word
   statement. The inversion IS the re-hook; no photo, no texture. */
body.break{background:#D97757}
body.break .frame{position:relative;z-index:2;height:1350px;display:flex;
                  flex-direction:column;justify-content:center;
                  text-align:center;padding:0 44px}
body.break h1{color:#0E0E10;text-shadow:none;-webkit-text-stroke:0;
              line-height:.92;margin-bottom:44px}
body.break .body{color:#0E0E10;text-shadow:none;font-weight:700}
body.break .masthead{color:#0E0E10}
body.break .masthead img{filter:brightness(0) drop-shadow(0 0 0 transparent)}
body.break .masthead:before,body.break .masthead:after{background:rgba(14,14,16,.55)}
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
/* save-close recap (owner order Aug 18): the last slide is a one-screen
   checklist built to be SAVED — story beats with orange ticks, sub-line
   below the pill; the pill alone carries the SEND ask (owner Aug 27:
   Mosseri names sends-per-reach the #1 discovery signal, and the Aug 18
   follow-ban finally reaches the renderer — this pill was the last
   hard-coded follow ask in the system) */
.recap{display:inline-block;text-align:left;margin:0 auto 48px;
       font-size:40px;line-height:1.4;font-weight:600;color:#FFF;
       text-shadow:0 3px 12px rgba(0,0,0,.85)}
.recap .row{display:flex;gap:24px;align-items:flex-start;margin-bottom:22px}
.recap .row:last-child{margin-bottom:0}
.recap .tick{color:#D97757;font-weight:800;flex-shrink:0}
.recap b{font-weight:800}
/* photo CTA (@technology closing slide): cover anatomy + send pill */
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
  function push(w,em){
    // a token that is ONLY punctuation (the comma stranded after an </em>
    // boundary) glues onto the previous word — a floating "," renders as
    // a mystery " . " on the slide (Elon $750B bug, Aug 3)
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
  var divs=lines.map(function(ln,i){
    var d=document.createElement('div');
    d.style.whiteSpace='nowrap';
    d.style.fontSize=(base*scales[i])+'px';
    d.innerHTML=ln.map(function(w){return w.em?'<em>'+w.t+'</em>':w.t}).join(' ');
    h.appendChild(d);
    return d;
  });
  /* INK GUARD (Aug 19 post-mortem: two long edu covers shipped with "$10,000"
     and comma descenders printed ON TOP of the next line): line-height .87 is
     the designed tight tabloid stack and stays, but real glyph ink — measured
     via canvas TextMetrics — must never collide. Push a line down by exactly
     the overlap (plus 2px air) only when the pair would actually touch, so
     clean all-caps stacks keep the tight look unchanged. */
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
  shade.style.background='linear-gradient(180deg,rgba(0,0,0,.15) 0px,rgba(0,0,0,0) 140px,'
    +'rgba(0,0,0,0) '+Math.max(140,edge-330)+'px,rgba(5,5,5,.45) '+Math.max(200,edge-150)+'px,'
    +'rgba(5,5,5,.72) '+edge+'px,rgba(5,5,5,.78) 1350px)';
}
/* fitSwipe (Aug 19 "6-bleed" post-mortem: a 10-word kicker wrapped the strip
   to TWO lines, lifting its top into the bottom-anchored headline's zone —
   the headline printed over the kicker): the strip is physically ONE line,
   shrinking its font to fit, so its height can never grow into the h1. */
function fitSwipe(){
  var s=document.querySelector('.ctastrip .swipe');
  if(!s)return;
  s.style.whiteSpace='nowrap';
  var avail=s.parentNode.clientWidth-48;
  var f=parseFloat(getComputedStyle(s).fontSize);
  while(s.scrollWidth>avail&&f>15){f-=1;s.style.fontSize=f+'px'}
}
document.fonts.ready.then(function(){
  var h=document.querySelector('body.cover h1')||document.querySelector('body.break h1');
  if(h)fitLines(h);
  fitSwipe();
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

# brand-accurate disc colors (owner Aug 3, the $750B cover: "the logos aren't
# accurate either (Tesla is red), and they both look exactly the same and are
# boring") — brands with one unmistakable color get it as the disc background;
# everyone else keeps the dark disc.
DISC_BG = {"tesla": "#E31937", "spacex": "#005288", "nvidia": "#76B900",
           "meta": "#0064E0", "reddit": "#FF4500", "ycombinator": "#FB651E"}


def discs_html(s):
    """1-2 logo/text discs for a cover (composed cutout OR full-bleed
    situation cover)."""
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


def slide_html(s, total):
    css = (CSS.replace("FONTS", HERE + "/fonts").replace("ARTPATH", HERE + "/art")
              .replace("SIZE", str(s.get("hsize", 100))))
    media = os.path.join(HERE, s["media"]) if s.get("media") else None

    if s["type"] == "cover":
        # cover headline renders 1.7x the writer's hsize: 5-cover reference
        # AVERAGE glyph = 7.0% of canvas (94px@1350); x1.7 puts typical
        # hsize 72 at 6.5% and hsize 80 at 7.3% — matching the range
        css = css.replace(f"font-size:{s.get('hsize', 100)}px",
                          f"font-size:{int(s.get('hsize', 100) * 1.7)}px", 1)
        # kicker (forensic Aug 2, the reference strip anatomy): the strip
        # carries the story's second beat when the writer supplied one —
        # "WITHOUT SONY LIFTING A FINGER" — else the generic swipe prompt
        if s.get("video"):
            swipe = 'Full video next <em>→</em>'
        elif (s.get("kicker") or "").strip():
            kick = html.escape(re.sub(r"<[^>]+>", "", s["kicker"]).strip().upper())
            swipe = f'{kick} <em>→</em>'
        else:
            swipe = 'Swipe for more <em>→</em>'
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
            discs = discs_html(s)
            back = (f'<div class="bgblur lite" style="background-image:url(\'{media}\')"></div>'
                    if media else art_bg(s["headline"]))
            bg = f'{back}{discs}<div class="cut"><img src="{cut}"></div><div class="shade"></div>'
            cls = "cover composed"
        elif media:
            # situation cover (owner Aug 3): a generated scene of the person
            # LIVING the story ships full-bleed; brand discs may ride on top.
            # person_layer (owner Aug 3, $750B cover: disc clipped the hair):
            # the person cut from the SAME image re-draws OVER the discs with
            # identical .bleed CSS (same cover-crop = pixel-perfect overlay),
            # so logos sit behind the person and the person wins collisions.
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
        # no subline (owner Aug 1): under the big words only the small swipe
        # strip renders — all the hook lives in the headline
        return f'''<!doctype html><meta charset="utf-8"><style>{css}</style>
<body class="{cls}">{bg}{logos}
<div class="frame">{MASTHEAD}<h1>{s["headline"]}</h1></div>
<div class="ctastrip"><div class="swipe">{swipe}</div></div>{FIT_JS}</body>'''

    if s["type"] == "cta":
        # save-close recap (owner order Aug 18): a body of 3+ lines renders as
        # a checklist (beats with orange ticks) + the last line as send-line;
        # shorter bodies keep the old single-sub rendering (edu/back-compat)
        lines = [l.strip() for l in (s.get("body") or "").split("\n")
                 if l.strip()]
        if len(lines) >= 3:
            rows = "".join(f'<div class="row"><span class="tick">✓</span>'
                           f'<span>{l}</span></div>' for l in lines[:-1])
            recap = f'<div><div class="recap">{rows}</div></div>'
            sub = f'<p class="cta-sub">{lines[-1]}</p>'
        else:
            recap = ""
            sub = (f'<p class="cta-sub">{"<br>".join(lines)}</p>'
                   if lines else "")
        if media:
            # photo CTA (@technology Codex Micro closing slide, owner Aug 1
            # "the last cta is amazing it shows sam altman"): the generated
            # CEO-with-product shot full-bleed, cover anatomy — photo bright to
            # the masthead, black band below with headline + recap + pill
            bg = (f'<div class="bgblur" style="background-image:url(\'{media}\')"></div>'
                  f'<div class="bleed" style="background-image:url(\'{media}\')"></div><div class="shade"></div>')
            return f'''<!doctype html><meta charset="utf-8"><style>{css}</style>
<body class="cover ctaphoto">{bg}
<div class="frame">{MASTHEAD}<h1>{s["headline"]}</h1>{recap}
<div class="ctarow"><span class="pill">Send this to a friend</span></div>{sub}</div>{FIT_JS}</body>'''
        return f'''<!doctype html><meta charset="utf-8"><style>{css}</style>
<body class="cta">{art_bg(s["headline"], heavy=True)}
<div class="frame">{MASTHEAD}
<h1>{s["headline"]}</h1>{recap}
<div><span class="pill">Send this to a friend</span></div>
{sub}
</div></body>'''

    # pattern-break slide (owner order Aug 18): solid orange, huge dark type —
    # ONE giant number or a ≤6-word statement, one short open body line. The
    # headline renders 1.6x the writer's hsize; no photo, no texture.
    if s["type"] == "content" and s.get("layout") == "break":
        css = css.replace(f"font-size:{s.get('hsize', 100)}px",
                          f"font-size:{int(s.get('hsize', 100) * 1.6)}px", 1)
        body = (f'<p class="body">{s["body"].replace(chr(10), "<br>")}</p>'
                if (s.get("body") or "").strip() else "")
        return f'''<!doctype html><meta charset="utf-8"><style>{css}</style>
<body class="break">
<div class="mast-top">{MASTHEAD}</div>
<div class="frame">
<h1>{s["headline"]}</h1>{body}</div>{FIT_JS}</body>'''

    # reaction-receipt slide (owner order Sep 5): the story's REAL source post
    # typeset as an X card, centered on the dark art backdrop. write.py fills
    # s["tweet"] from the radar moment; a tweet slide without data was already
    # demoted upstream, so this branch only fires with real text.
    if s["type"] == "content" and s.get("layout") == "tweet" and s.get("tweet"):
        t = s["tweet"]
        handle = html.escape(t.get("handle") or "")
        text = html.escape(t.get("text") or "").replace(chr(10), "<br>")
        views = int(t.get("views") or 0)
        vfmt = (f"{views / 1e6:.1f}M" if views >= 1e6 else
                f"{views / 1e3:.1f}K" if views >= 1000 else str(views))
        meta = html.escape(t.get("when") or "")
        if views:
            meta += (" · " if meta else "") + f"<b>{vfmt}</b> Views"
        meta_html = f'<div class="tmeta">{meta}</div>' if meta else ""
        initial = html.escape((handle[:1] or "X").upper())
        return f'''<!doctype html><meta charset="utf-8"><style>{css}</style>
<body class="tweet">{art_bg(text, heavy=True)}
<div class="mast-top">{MASTHEAD}</div>
<div class="frame"><div class="tweetcard">
<div class="thead"><div class="avatar">{initial}</div>
<div><div class="tname">{handle}</div><div class="thandle">@{handle}</div></div></div>
<p class="ttext">{text}</p>
{meta_html}</div></div></body>'''

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
    else:
        # plain crisp black card (owner Sep 4, Bernie post-mortem: FIVE inner
        # slides recycled the cover photo as the same murky orange blur — the
        # reference page's no-photo slides are clean dark text cards, and the
        # old "never a dead-black void" blur read as one long smear)
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
    for n, s in enumerate(slides, 1):
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False) as f:
            f.write(slide_html(s, len(slides)))
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
