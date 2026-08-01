#!/usr/bin/env python3
"""Automated reel, @technology-style: find the day's most viral AI/tech clip
on Reddit (upvotes = crowd-validated virality; viral TikTok/IG clips get
reposted there, so Reddit is the open door to all of them), Claude picks the
scroll-stopper and writes the overlay title + caption, ffmpeg brands it
(9:16 blur-pad, profile card + title overlay, original audio), then it's
pushed to the public media repo and published via the Make reel route.

Usage: .venv/bin/python reel.py [video-url] [--dry]
  no url  -> auto-pick from SUBS (top video posts of the day)
  --dry   -> build posts/<name>/reel.mp4 but don't push or publish"""
import html, json, os, re, shutil, subprocess, sys, time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone

import bundle
import reelscout
from fetch import get
from write import call_claude, no_dashes, principles
from render import CHROME

HERE = os.path.dirname(os.path.abspath(__file__))
SUBS = ["singularity", "robotics", "artificial", "ChatGPT", "ClaudeAI", "OpenAI",
        "interestingasfuck", "nextfuckinglevel", "Damnthatsinteresting"]
# Crowd-qualification floors, per sub size (owner verdict Jul 28: "a lot more
# upvotes, not just a few hundred"). AI subs are small ponds — 500 is a real
# hit there (today's best on-topic clip: 728). In the huge general subs only
# mega-viral qualifies; the topic gate then decides if it's ours.
AI_FLOOR, GENERAL_FLOOR = 500, 5000
FLOOR = {s: AI_FLOOR for s in
         ("singularity", "robotics", "artificial", "ChatGPT", "ClaudeAI", "OpenAI")}
USED = os.path.join(HERE, "reels-used.json")
MEDIA_REPO = "git@github.com:saaryafe-crypto/kestrel-media.git"
RAW = "https://raw.githubusercontent.com/saaryafe-crypto/kestrel-media/main"

# Video hole geometry — build_video() must place the clip exactly here.
# 4:5 portrait container (owner spec Jul 29, matching the reference layout):
# full width minus 60px margins, height = 960/0.8; 16:9 sources center-crop
# into it (force_original_aspect_ratio=increase + crop), never letterboxed.
# Content spans y 175-1745 -> centered with 175px top/bottom at 1080x1920.
VID_X, VID_Y, VID_W, VID_H = 60, 545, 960, 1200

OVERLAY = """<!doctype html><meta charset=utf-8><style>
@font-face{{font-family:Poppins;src:url("FONTS/Poppins-SemiBold.ttf");font-weight:600}}
@font-face{{font-family:Poppins;src:url("FONTS/Poppins-ExtraBold.ttf");font-weight:800}}
*{{margin:0;box-sizing:border-box}}
body{{width:1080px;height:1920px;background:transparent;font-family:Poppins;
     position:relative;overflow:hidden}}
/* transparent rounded hole punched into a solid-black frame */
.hole{{position:absolute;left:{vx}px;top:{vy}px;width:{vw}px;height:{vh}px;
      border-radius:26px;box-shadow:0 0 0 2200px #050505}}
/* tweet-embed header, left-aligned like @technology */
.card{{position:absolute;left:70px;top:175px;display:flex;align-items:center;gap:28px}}
.card img{{width:130px;height:130px;border-radius:50%;display:block}}
.name{{display:flex;align-items:center;gap:12px;
      font-weight:800;font-size:48px;color:#FFF;line-height:1.15}}
.name svg{{width:46px;height:46px;flex:none}}
.handle{{font-weight:600;font-size:40px;color:#8B98A5;margin-top:4px}}
.title{{position:absolute;left:70px;top:365px;width:950px;text-align:left;
       font-weight:600;font-size:48px;color:#FFF;line-height:1.35}}
</style><body>
<div class=hole></div>
<div class=card><img src="ART/avatar.jpg"><div>
  <div class=name>Yaffe AI <svg viewBox="0 0 24 24" fill="#1d9bf0"><path d="M22.25 12c0-1.43-.88-2.67-2.19-3.34.46-1.39.2-2.9-.81-3.91s-2.52-1.27-3.91-.81c-.66-1.31-1.91-2.19-3.34-2.19s-2.67.88-3.33 2.19c-1.4-.46-2.91-.2-3.92.81s-1.26 2.52-.8 3.91c-1.31.67-2.2 1.91-2.2 3.34s.89 2.67 2.2 3.34c-.46 1.39-.21 2.9.8 3.91s2.52 1.26 3.91.81c.67 1.31 1.91 2.19 3.34 2.19s2.68-.88 3.34-2.19c1.39.45 2.9.2 3.91-.81s1.27-2.52.81-3.91c1.31-.67 2.19-1.91 2.19-3.34zm-11.71 4.2L6.8 12.46l1.41-1.42 2.26 2.26 4.8-5.23 1.47 1.36-6.2 6.77z"/></svg></div>
  <div class=handle>@yaffeai</div>
</div></div>
<div class=title>TITLE</div>
</body>""".format(vx=VID_X, vy=VID_Y, vw=VID_W, vh=VID_H)


def sh(*cmd, **kw):
    return subprocess.run(cmd, check=True, **kw)


def yt(*args, timeout=300):
    # hard timeout (Jul 31 audit: a stalled yt-dlp hung the launchd slot
    # silently for hours — the slot must fail fast and fall down the ladder)
    try:
        r = subprocess.run(["yt-dlp", "--no-update", *args],
                           capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"yt-dlp timed out after {timeout}s", file=sys.stderr)
        return ""
    if r.returncode:
        print(r.stderr[-400:], file=sys.stderr)
    return r.stdout


def probe_mp4(url):
    """Direct-mp4 probe (X clips). yt-dlp's generic extractor returns NO
    duration/width for a bare mp4 URL, which silently rejected every X video
    at the 8s/720p gates (audit Jul 29 — verified live on a 4K SpaceX clip).
    ffprobe reads the headers over HTTP and is exact. Returns (dur_s, w, h)."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height:format=duration",
             "-of", "json", url],
            capture_output=True, text=True, timeout=60)
        d = json.loads(r.stdout)
        s = d["streams"][0]
        return float(d["format"]["duration"]), int(s["width"]), int(s["height"])
    except Exception as e:
        print(f"  ffprobe {url[:60]}: {e}", file=sys.stderr)
        return 0, 0, 0


def candidates(used, t="day"):
    """Top VIDEO posts from viral subs over window t ("day"; "week" as the
    wider fallback rung — 7 posts/day is a must, the ladder widens instead of
    skipping). Viral TikTok/IG clips get reposted to Reddit; upvotes are the
    crowd-validated virality signal."""
    ns = {"a": "http://www.w3.org/2005/Atom"}
    rows = []
    for i, sub in enumerate(SUBS):
        if i:
            time.sleep(61)  # unauthenticated Reddit RSS: ~1 req/min or it 429s
        try:
            root = ET.fromstring(get(f"https://www.reddit.com/r/{sub}/top.rss?t={t}&limit=15"))
        except Exception as e:
            print(f"  r/{sub} rss failed ({e})", file=sys.stderr)
            continue
        for rank, e in enumerate(root.findall("a:entry", ns)):
            # every entry has a [link] anchor; only video/link posts point it
            # off-reddit — v.redd.it is the video host
            m = re.search(r'href="([^"]+)">\[link\]', e.findtext("a:content", "", ns))
            if not m or "v.redd.it" not in m.group(1):
                continue
            link = html.unescape(m.group(1))
            vid = link.rstrip("/").rsplit("/", 1)[-1]
            if vid in used:
                continue
            author = e.findtext("a:author/a:name", "", ns).lstrip("/")
            rows.append({"id": vid, "url": link,
                         "title": html.unescape(e.findtext("a:title", "", ns)),
                         "channel": author or "unknown", "sub": sub, "rank": rank})
    rows.sort(key=lambda c: c["rank"])  # probe best-ranked first
    cands = []
    for c in rows[:30]:  # probe budget; each yt-dlp -J call is a few seconds
        if len(cands) >= 10:
            break
        try:
            d = json.loads(yt("-J", "--no-download", c["url"]))
        except Exception:
            continue
        dur, likes = d.get("duration") or 0, d.get("like_count") or 0
        # resolution = SHORT side (a 480x854 portrait clip is tall, not sharp)
        res = min(d.get("width") or 0, d.get("height") or 0)
        if not (8 <= dur <= 300) or likes < FLOOR.get(c["sub"], GENERAL_FLOOR) or res < 720:
            continue
        c.update(duration=int(dur), likes=int(likes), res=int(res),
                 comments=int(d.get("comment_count") or 0))
        cands.append(c)
    # crowd qualification: real upvotes across ALL subs, not rank inside one
    cands.sort(key=lambda c: (-c["likes"], -c["res"]))
    for i, c in enumerate(cands):
        print(f"  cand [{i}] r/{c['sub']} {c['likes']:,}up {c['comments']}c "
              f"{c['res']}p {c['duration']}s: {c['title'][:55]}", file=sys.stderr)
    return cands


def radar_candidates(used):
    """Video moments from radar.json (the Demand Radar on the Mac, every 2h):
    Reddit breakouts caught in their FIRST HOURS — a video exploding right now
    is the freshest reel source there is, and its top comments are the crowd's
    vote on which emotion the moment triggers. Probes the reddit permalink
    with yt-dlp (gives uploader + duration + res). Fails open: no/stale radar
    -> [] and the ladder falls to the platform scout."""
    try:
        r = json.load(open(os.path.join(HERE, "radar.json")))
        upd = datetime.fromisoformat(r["updated"])
        if (datetime.now(timezone.utc) - upd).total_seconds() > 24 * 3600:
            return []
    except Exception:
        return []
    cands = []
    for m in r.get("moments", []):
        if not m.get("video") or len(cands) >= 8:
            continue
        vid = m.get("id") or m["video"].split("?")[0].rstrip("/").rsplit("/", 1)[-1]
        if vid in used:
            continue
        if "reddit" in m["permalink"]:
            # reddit: yt-dlp probes the permalink (also gives the uploader)
            try:
                d = json.loads(yt("-J", "--no-download", m["permalink"]))
            except Exception:
                continue
            dur = d.get("duration") or 0
            res = min(d.get("width") or 0, d.get("height") or 0)
            src_url, direct, channel = (m["permalink"], None,
                                        d.get("uploader") or m["sub"])
        else:
            # X: the moment carries a direct mp4 — ffprobe it and download it
            # directly (yt-dlp can't read bare mp4 metadata and its twitter
            # route is flaky)
            dur, w, h = probe_mp4(m["video"])
            res = min(w, h)
            src_url, direct, channel = m["video"], m["video"], m["sub"]
        if not (8 <= dur <= 300) or res < 720:
            continue
        cands.append({
            "id": vid, "url": src_url, "direct_mp4": direct, "title": m["title"],
            "channel": channel, "sub": m["sub"],
            "where": m.get("where", f"r/{m['sub']}"),
            "unit": m.get("unit", "upvotes"),
            "likes": m["score"], "comments": m["comments_n"],
            "duration": int(dur), "res": int(res),
            "vph": m["vph"], "age_h": m["age_h"],
            "top_comments": m.get("top_comments") or []})
    cands.sort(key=lambda c: -c["vph"])
    for i, c in enumerate(cands):
        print(f"  cand [{i}] {c['where']} {c['vph']:,.0f}/hr {c['likes']:,} "
              f"{c['age_h']}h {c['res']}p {c['duration']}s: {c['title'][:55]}",
              file=sys.stderr)
    return cands


def cline(i, c):
    if c.get("platform"):  # reelscout candidate (ig/tiktok/youtube)
        pop = (f"{c['platform']} @{c['channel']} | {c.get('views', 0):,} views"
               f" in {(c.get('age_h') or 0) / 24:.1f} days")
    elif c.get("vph"):     # radar breakout (hours old, exploding right now)
        pop = (f"{c.get('where', 'r/' + str(c.get('sub', '?')))} | BREAKING OUT"
               f" NOW: {c.get('likes', 0):,} {c.get('unit', 'upvotes')} in"
               f" {c.get('age_h', 0):.0f}h ({c['vph']:,.0f}/hr),"
               f" {c.get('comments', 0):,} comments")
    else:                  # reddit fallback candidate
        pop = (f"r/{c.get('sub', '?')} | {c.get('likes', 0):,} upvotes,"
               f" {c.get('comments', 0):,} comments today | posted by {c['channel']}")
    line = f"[{i}] {pop} | {c.get('res', '?')}p | {c['duration']}s\n    {c['title']}"
    if c.get("top_comments"):
        quotes = " / ".join(f'"{t[:90]}"' for t in c["top_comments"][:2])
        line += f"\n    crowd: {quotes}"
    return line


def build_prompt(cands, recent=()):
    lines = [cline(i, c) for i, c in enumerate(cands)]
    recent_block = ""
    if recent:
        recent_block = ("\n\nALREADY POSTED (last 7 days — reels we published):\n"
                        + "\n".join(f"- {t}" for t in recent) + "\n")
    return f"""You run @yaffeai, an AI/tech Instagram page modeled on @technology (8.7M followers). Below are the most viral AI/tech clips found across Reddit breakouts, Instagram, TikTok and YouTube — real view counts, the crowd already voted. Pick ONE to repost as a branded reel, exactly in their register.

CANDIDATES:
{chr(10).join(lines)}{recent_block}

Their reel formula (copy the FORM, never the text): a one-line curiosity title over the video — "In case you've ever wondered how a spring was made", "The efficiency of a robot vacuum cleaner". Understated, curious, zero hype words. The caption is a calm 2-3 short-paragraph explainer of what you're seeing and why it matters, then a follow line, then credits.
{principles()}
OUTPUT — one JSON object only:
{{"pick": <index>, "title": "<overlay line, max 70 chars, sentence case>",
 "title_candidates": ["<FIVE genuinely different overlay lines for the picked clip — different curiosity angles (how it works / a scale number / what it replaces / the unsettling twist / who built it), each max 70 chars, sentence case — not rewordings; include your best (the one in \\"title\\") among them>"],
 "caption": "<explainer>\\n\\nLove AI? Follow @yaffeai for daily AI news\\n\\nCredits: <original creator if named in the post title, else the poster's username>. DM for credit or removal\\n\\n<exactly 5 hashtags>",
The Credits name is a PLAIN name — never an @ handle, # hashtag, or u/ prefix (write "SpaceX", not "@SpaceX"; write "HenryGCase", not "u/HenryGCase").
 "start_s": <int, skip intro/logo seconds>, "clip_s": <int 15-60, the most impressive stretch>}}

RULES
- TOPIC IS A HARD GATE: only pick a clip about AI, robots, or futuristic tech. If NO candidate qualifies, return exactly {{"pick": -1}} and nothing else — skipping the slot beats posting off-topic.
- ENTERTAINMENT IS A HARD GATE (the newspaper test): picture a 19-year-old who does not care about tech news, scrolling with the SOUND OFF. Would they stop for the video itself? Corporate product demos, keynote/press-conference clips, talking heads, screen recordings, slideshows, news-segment energy = FAIL no matter how big the numbers. Pick a MOMENT someone caught on camera — a machine doing something absurd or unbelievable, a spectacular failure, scale that makes you say "wait, WHAT?". The clip must trigger ONE clear emotion in 3 seconds: awe, fear, or laughter. If every candidate fails this test, return {{"pick": -1}} — the ladder has more sources.
- VIRALITY IS THE PRIMARY SIGNAL: candidates are listed by real total views (best first) and everything shown already cleared a hard virality floor. A clip's age does NOT matter — a monster clip from three weeks ago we never posted beats a modest clip from today. Only skip a stronger candidate if it fails the topic gate, the entertainment gate, or the story-dedupe gate.
- STORY DEDUPE IS A HARD GATE (owner rule Aug 1): if a candidate shows the same event, stunt, or story as ANYTHING in the ALREADY POSTED list — even a different angle, a different channel's copy, or a re-edit — treat it as already posted and skip it. Same robot doing the same demo, same launch, same fail = same story. If every candidate is a dupe, return {{"pick": -1}} — the ladder has more sources.
- Where a "crowd:" line appears, those are the top-voted comments on the source post — thousands of real people voting on which EMOTION the moment triggers. Aim your title at that emotion. NEVER quote or copy a comment.
- FIRST 3 SECONDS ARE A HARD GATE: start_s must land ON the most impressive moment — no build-up, no intro, no logo. If the wow moment is at 0:42, start there.
- COMPLETION over length: prefer clip_s 15-30. Cut BEFORE the clip gets boring; a fully-watched 18s reel outranks a half-watched 50s one.
- The title opens an information gap (what you're seeing / why it works), it never resolves it. Simple words, no hype.
- THE TITLE MUST EXPLAIN THE VIDEO (hard gate, Aug 1 Mad Max post-mortem): the viewer sees ONLY the footage + your line. If the clip is a MEME — a movie scene, game footage, or a skit standing in for a tech story — the line must carry the meme's framing so the metaphor lands (the source post's title usually holds the joke: "AI companies in 2028 after finding out that your grandma's diary is handwritten"). A factual news claim floating over footage it doesn't literally show is banned: "Your handwriting might be the last thing AI can't read" over a desert car chase reads as random chaos.
- LANGUAGE (hard requirement): title and caption written for a smart 16-year-old. Everyday words, short sentences, zero industry jargon — say what the thing DOES, not what it's called.
- The caption's FIRST sentence carries the payoff (~125 chars show before "...more"). Explainer commentary adds original context beyond the post title — this is also what makes the repost a transformation, not a raw repost.
- start_s + clip_s must fit inside the clip's duration.
- Never invent facts not in the post title. No emojis in the title."""


def qa(r, cands):
    errs = []
    if not (0 <= r.get("pick", -1) < len(cands)):
        errs.append("bad pick index")
        return errs
    dur = cands[r["pick"]]["duration"]
    if len(r["title"]) > 75: errs.append("title over 75 chars")
    if "@yaffeai" not in r["caption"] or "Credits:" not in r["caption"]:
        errs.append("caption missing follow line or Credits")
    else:  # owner rule: credits are plain names — no @handle / #tag / u/ prefix
        cred = r["caption"].split("Credits:", 1)[1].splitlines()[0]
        if re.search(r"[@#]|\bu/", cred):
            errs.append("Credits line must be a plain name (no @, #, or u/)")
    if len(re.findall(r"#\w+", r["caption"])) != 5: errs.append("need exactly 5 hashtags")
    if not (10 <= r.get("clip_s", 0) <= 60): errs.append("clip_s must be 10-60")
    if r.get("start_s", 0) + r.get("clip_s", 0) > dur:
        errs.append(f"start_s+clip_s exceeds duration ({dur}s)")
    return errs


def make_overlay(title, out_png):
    page = (OVERLAY.replace("FONTS", "file://" + os.path.join(HERE, "fonts"))
                   .replace("ART", "file://" + os.path.join(HERE, "art"))
                   .replace("TITLE", html.escape(title)))
    hp = out_png.replace(".png", ".html")
    open(hp, "w").write(page)
    sh(CHROME, "--headless", "--disable-gpu", "--default-background-color=00000000",
       f"--screenshot={out_png}", "--window-size=1080,1920", "file://" + hp)


def build_video(src, overlay, out, start, clip):
    # @technology tweet-embed layout: 4:5 video inside the black frame,
    # center-cropped to fill the rounded hole punched in the overlay PNG.
    # Audio = the clip's OWN sound only (owner rule Jul 29: never add music).
    vf = (f"[0:v]scale={VID_W}:{VID_H}:force_original_aspect_ratio=increase,"
          f"crop={VID_W}:{VID_H},pad=1080:1920:{VID_X}:{VID_Y}:color=0x050505[base];"
          "[base][1:v]overlay=0:0,format=yuv420p[v]")
    sh("ffmpeg", "-y", "-loglevel", "error", "-ss", str(start), "-t", str(clip),
       "-i", src, "-i", overlay, "-filter_complex", vf, "-map", "[v]", "-map", "0:a?",
       "-c:v", "libx264", "-preset", "medium", "-b:v", "5M",
       "-r", "30", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", out)


def push_media(post_dir, name):
    # network git ops retry: transient SSH resets killed whole reel slots
    # (issue #18: clone "Connection reset by peer"; #14: push timed out)
    def net(fn, what):
        for attempt in range(3):
            try:
                return fn()
            except Exception as e:
                if attempt == 2:
                    raise
                print(f"git {what} failed ({e}) — retry {attempt + 2}/3",
                      file=sys.stderr)
                time.sleep(20)

    tmp = "/tmp/media-reel"

    def clone():
        shutil.rmtree(tmp, ignore_errors=True)  # partial clone from a failed try
        sh("git", "clone", "--depth", "1", MEDIA_REPO, tmp)
    net(clone, "clone")
    os.makedirs(f"{tmp}/{name}", exist_ok=True)
    shutil.copy(os.path.join(post_dir, "reel.mp4"), f"{tmp}/{name}/reel.mp4")
    sh("git", "add", "-A", cwd=tmp)
    sh("git", "-c", "user.name=ig-bot", "-c", "user.email=bot@users.noreply.github.com",
       "commit", "-m", name, cwd=tmp)
    net(lambda: sh("git", "push", cwd=tmp), "push")


def title_tournament(r):
    """Same MrBeast packaging discipline as the carousel hook tournament,
    judged by the viral agent (post-mortem rules baked in: a concrete absurd
    specific beats vague teasing; unknown-brand anchors lose). Candidates +
    winner stay in reel.json so learn.py can compare picks against real
    plays later."""
    import viral
    cands = [t for t in r.get("title_candidates", []) + [r.get("title", "")]
             if t and t.strip() and len(t.strip()) <= 75]
    win, why = viral.reel_title_judge(cands)
    if win:
        r["title"] = win
        print("title tournament:", win, "—", why or "", file=sys.stderr)
    else:
        print("title tournament: no winner — keeping writer's title", file=sys.stderr)
    return r


CLIP_QA = {"type": "object", "properties": {"usable": {"type": "boolean"}},
           "required": ["usable"]}

TITLE_FIT = {"type": "object",
             "properties": {"fits": {"type": "boolean"},
                            "better_title": {"type": "string"}},
             "required": ["fits"]}


def title_fits(src, dur, title, source_title):
    """Coherence gate (owner Aug 1, the Mad Max reel post-mortem: a news claim
    over meme footage reads as random chaos). Watches 2 frames WITH the title
    and either approves it or rewrites it to carry the framing that makes the
    video make sense. Fails open — the clip itself already passed clip_ok."""
    frames = []
    for frac in (0.15, 0.6):
        fp = src.replace(".mp4", f"-tf{int(frac * 10)}.jpg")
        try:
            sh("ffmpeg", "-y", "-loglevel", "error", "-ss",
               str(max(0, int(dur * frac))), "-i", src, "-frames:v", "1", fp)
            frames.append(fp)
        except Exception:
            pass
    if not frames:
        return title
    try:
        r = call_claude(
            "Two frames from a video are attached. It posts as an Instagram "
            f'reel with this line above the video:\n"{title}"\n'
            f'The original post was titled: "{source_title}"\n\n'
            "A stranger sees ONLY the video + the line. fits:true only if the "
            "line frames what the viewer is literally watching. If the video "
            "is a MEME (a movie scene, game footage, or a skit standing in "
            "for a tech story), the line must carry the meme's framing (like "
            "'AI companies in 2028 when...') so the metaphor lands; a factual "
            "claim floating over footage it doesn't show is fits:false. When "
            "fits:false, write better_title: max 70 chars, sentence case, "
            "simple words a 16-year-old gets, keeping the joke or framing "
            "that connects the line to the footage, no invented facts, no "
            'dashes. Return ONLY JSON: {"fits": true/false, "better_title": "..."}',
            schema=TITLE_FIT, images=frames)
        if not r.get("fits") and r.get("better_title", "").strip():
            fixed = r["better_title"].strip()[:75]
            print(f"title coherence gate rewrote: {fixed}", file=sys.stderr)
            return fixed
        return title
    except Exception as e:
        print(f"title coherence gate failed ({e}) — keeping title", file=sys.stderr)
        return title
    finally:
        for fp in frames:
            if os.path.exists(fp):
                os.remove(fp)


def clip_ok(src, dur, channel):
    """Vision QA on 2 extracted frames — rejects clips with another page's
    handle / watermark / app logo baked into the video (owner Jul 28: "ig
    video can have a credit in it" — a repost-of-a-repost look kills the
    premium feel). Fails closed, like image_ok."""
    frames = []
    for frac in (0.2, 0.7):
        fp = src.replace(".mp4", f"-qa{int(frac*10)}.jpg")
        try:
            sh("ffmpeg", "-y", "-loglevel", "error", "-ss",
               str(max(0, int(dur * frac))), "-i", src, "-frames:v", "1", fp)
            frames.append(fp)
        except Exception:
            pass
    if not frames:
        return False
    try:
        r = call_claude(
            "Frames from a video clip are attached (if not attached, use your "
            f"Read tool on {' and '.join(frames)}). We want to repost this clip "
            "on our own branded Instagram page. Answer usable:false if any frame "
            "has a social-media username/handle (like @somepage), another news/"
            "meme page's watermark, a TikTok/CapCut/other app logo, or "
            "subscribe/follow graphics baked into the video — that "
            "repost-of-a-repost look is banned. ALLOWED and usable:true: the "
            "original manufacturer's or lab's own brand logo or spec captions "
            "in its own demo footage (a Boston Dynamics logo on a Boston "
            "Dynamics video is credit, not a repost mark), and small natural "
            "in-scene text (street signs, product screens). "
            'Also usable:false if the footage is blurry or heavily compressed. '
            'Return ONLY JSON: {"usable": true/false}',
            schema=CLIP_QA, images=frames)
        return bool(r.get("usable"))
    except Exception as e:
        print(f"clip QA failed ({e}) — rejecting clip", file=sys.stderr)
        return False
    finally:
        for fp in frames:
            if os.path.exists(fp):
                os.remove(fp)


def pick(cands, recent=()):
    """Claude pick + QA loop. Returns the validated response, or None when no
    candidate passes the topic gate / QA — caller widens the ladder."""
    prompt = build_prompt(cands, recent)
    for attempt in range(3):
        r = call_claude(prompt)
        if r.get("pick") == -1:
            print("topic gate: no AI/tech clip in this batch", file=sys.stderr)
            return None
        errs = qa(r, cands)
        if not errs:
            return r
        print(f"QA gate failed (attempt {attempt+1}): " + "; ".join(errs), file=sys.stderr)
        prompt = build_prompt(cands, recent) + "\n\nYOUR PREVIOUS ATTEMPT FAILED — fix:\n- " + "\n- ".join(errs)
    return None


def main():
    dry = "--dry" in sys.argv
    urls = [a for a in sys.argv[1:] if a.startswith("http")]
    used = json.load(open(USED)) if os.path.exists(USED) else []

    # The ladder (owner rule Jul 28: 7 posts/day is a MUST — a slot is never
    # skipped, it falls back): radar breakouts (hours-old Reddit rockets with
    # the crowd's emotional angle) -> platform scout (IG/TikTok/YouTube view
    # counts) -> today's viral Reddit clips -> this week's -> fill the slot
    # with an extra carousel instead.
    used_ids = {u["id"] for u in used}
    # owner rule Aug 1: never repost a story we ran in the last 7 days, even a
    # different angle/re-edit of the same event — the judge gets these titles
    week_ago = str(date.today() - timedelta(days=7))
    recent = [u["title"] for u in used
              if u.get("title") and u.get("date", "") >= week_ago]
    r = cands = None
    if urls:
        d = json.loads(yt("-J", "--no-download", urls[0]))
        cands = [{"id": d["id"], "url": urls[0], "title": d["title"],
                  "channel": d.get("uploader") or d.get("channel", ""),
                  "duration": int(d.get("duration") or 0)}]
        r = pick(cands, recent)
    else:
        for rung, fn in (("radar", lambda: radar_candidates(used_ids)),
                         ("scout", lambda: reelscout.scout(used_ids)),
                         ("reddit day", lambda: candidates(used_ids, "day")),
                         ("reddit week", lambda: candidates(used_ids, "week"))):
            try:
                cands = fn()
            except Exception as e:
                print(f"{rung} sourcing failed ({e})", file=sys.stderr)
                cands = []
            if cands:
                r = pick(cands, recent)
            if r:
                break
            print(f"no publishable reel from {rung}", file=sys.stderr)

    # download + frame QA loop: a clip with another page's credit baked in
    # (owner Jul 28) or mushy footage gets dropped and the pick reruns on the
    # remaining pool. src lives in /tmp because the post dir is named after
    # the final pick.
    src = "/tmp/reel-src.mp4"
    for _ in range(3):
        if not r:
            break
        c = cands[r["pick"]]
        if os.path.exists(src):
            os.remove(src)
        if c.get("direct_mp4"):
            # X clip: fetch the mp4 straight from video.twimg.com — no
            # extractor involved, nothing to go stale
            try:
                req = urllib.request.Request(
                    c["direct_mp4"], headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=180) as resp, \
                        open(src, "wb") as f:
                    shutil.copyfileobj(resp, f)
            except Exception as e:
                print(f"direct mp4 download failed: {e}", file=sys.stderr)
        else:
            dl = ["-f", "bv*[height<=1080]+ba/b",  # v.redd.it audio isn't m4a-tagged
                  "--merge-output-format", "mp4", "-o", src]
            if c.get("platform") == "instagram" and os.path.exists(reelscout.COOKIES):
                dl += ["--cookies", reelscout.COOKIES]
            yt(*dl, c["url"], timeout=600)
        if os.path.exists(src) and clip_ok(src, c["duration"], c["channel"]):
            break
        print(f"clip rejected ({'download failed' if not os.path.exists(src) else 'frame QA'}):"
              f" {c['channel']} {c['id']} — re-picking", file=sys.stderr)
        cands = cands[:r["pick"]] + cands[r["pick"] + 1:]
        r = pick(cands, recent) if cands else None
    else:
        r = None

    if not r:
        if not dry:
            sh("gh", "workflow", "run", "ig-post.yml", "-f", "kind=auto", cwd=HERE)
        raise SystemExit("no viral AI/tech clip available — slot filled with an extra carousel")

    r = title_tournament(r)
    c = cands[r["pick"]]
    name = f"{date.today()}-reel-{c['id']}"
    post_dir = os.path.join(HERE, "posts", name)
    os.makedirs(post_dir, exist_ok=True)
    print(f"picked {c['channel']}: {c['title']}\noverlay: {r['title']}", file=sys.stderr)

    # owner rule Jul 29: reels keep the clip's own sound, NEVER add music.
    # bundle.social stays the preferred publisher while budget lasts: its API
    # guarantees shareToFeed=false (reels off the main grid).
    # HARD BLOCK Aug 1: the Make scenario's IG module ignores our
    # share_to_feed field and posts reels to the MAIN GRID (owner told us
    # multiple times: never). Until the owner sets Share to Feed = No in the
    # Make UI and confirms, a reel slot without bundle budget becomes an
    # extra carousel — the slot still fills, the grid stays clean.
    publish = "bundle"
    if not dry and not bundle.budget_left():
        sh("gh", "workflow", "run", "ig-post.yml", "-f", "kind=auto", cwd=HERE)
        raise SystemExit("bundle budget out and Make posts reels to the main "
                         "grid — slot filled with an extra carousel instead")

    # coherence gate (Aug 1): the title must make the FOOTAGE make sense
    r["title"] = title_fits(src, c["duration"], r["title"], c["title"])

    # owner rule: dashes never reach the overlay or the caption
    r["title"] = no_dashes(r["title"])
    r["caption"] = no_dashes(r["caption"])

    make_overlay(r["title"], os.path.join(post_dir, "overlay.png"))
    out_mp4 = os.path.join(post_dir, "reel.mp4")
    build_video(src, os.path.join(post_dir, "overlay.png"),
                out_mp4, r.get("start_s", 0), r["clip_s"])
    os.remove(src)
    # output gate (Jul 31): a truncated/near-empty encode must never reach the
    # publish workflow — fall back to an extra carousel, the slot still fills
    if not os.path.exists(out_mp4) or os.path.getsize(out_mp4) < 200_000:
        shutil.rmtree(post_dir, ignore_errors=True)
        if not dry:
            sh("gh", "workflow", "run", "ig-post.yml", "-f", "kind=auto", cwd=HERE)
        raise SystemExit("reel.mp4 came out broken — slot filled with an extra carousel")
    json.dump({**r, "source": c["url"], "channel": c["channel"],
               "publish": publish},
              open(os.path.join(post_dir, "reel.json"), "w"), indent=1)
    print("reel ready:", os.path.join(post_dir, "reel.mp4"))
    if dry:
        return

    push_media(post_dir, name)
    used.append({"id": c["id"], "date": str(date.today()), "title": c["title"]})
    json.dump(used, open(USED, "w"), indent=1)
    if publish == "bundle":
        bundle.log_use(name)
    sh("git", "add", "posts", os.path.basename(USED),
       *(["bundle-used.json"] if os.path.exists(bundle.USED) else []), cwd=HERE)
    subprocess.run(["git", "commit", "-m", f"IG reel: {name}"], cwd=HERE)
    subprocess.run(["git", "pull", "--rebase", "--autostash"], cwd=HERE)
    subprocess.run(["git", "push"], cwd=HERE)
    # webhook key lives only in GitHub secrets -> publish via the ig-reel workflow
    sh("gh", "workflow", "run", "ig-reel.yml", "-f", f"post={name}", cwd=HERE)
    print("publish workflow triggered for", name)


if __name__ == "__main__":
    main()
