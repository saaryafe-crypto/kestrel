#!/usr/bin/env python3
"""News pipeline for both pages (owner-approved redesign 2026-10-05).

  python3 news.py card en|he [--date YYYY-MM-DD]   build one news card
  python3 news.py reel en|he [--date YYYY-MM-DD]   build one reel
  python3 news.py preview en|he --out DIR          dry-run day: 3 cards + 2 reels

A build prints "post ready: <dir>" (cards: slide-1.jpg + caption.txt +
post.json; reels: reel.mp4 + reel.json + post.json), or "SKIP: ..." when no
story passes the gates. Publishing is post.py's job (workflow, after slot.py
waits for the slot time). Nothing here posts."""
import html, json, os, re, shutil, subprocess, sys, tempfile, urllib.parse, urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

import gates, llm, news_card
from pages import PAGES

HERE = os.path.dirname(os.path.abspath(__file__))
UA = {"User-Agent": "Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/120 Safari/537.36",
      "Accept-Language": "en,he"}
ACRONYMS = {"AI", "CEO", "TASE", "IPO", "USA", "US", "UK", "EU", "GPU", "CPU", "FDA",
            "NASA", "IBM", "AMD", "TSMC", "OK", "TV", "VR", "AR", "IDF", "AGI", "LLM",
            "BYD", "API", "IOS", "NBA", "NFL", "FBI", "SEC", "FTC", "DOJ", "AWS", "HBO"}
TECH = re.compile(r"\b(AI|robots?|humanoid|robotaxi|waymo|self-driving|driverless|openai|chatgpt|"
                  r"claude|gemini|sora|veo|kling|nvidia|apple|google|tesla|optimus|unitree|figure 0\d)\b", re.I)
BANNED = re.compile(r"\b(dm us|dm me|follow us|follow @|link in bio|feel illegal|"
                    r"you won'?t believe|insane|mind-?blowing|game-?changer|crazy|wild)\b", re.I)


def log(*a):
    print(*a, file=sys.stderr)


# Wikimedia rate-limits browser-like agents; its policy wants a bot UA
WIKI_UA = {"User-Agent": "KestrelNewsCards/1.0 (https://github.com/saaryafe-crypto/kestrel)"}


def get(url, timeout=20):
    h = WIKI_UA if "wikimedia.org" in url or "wikipedia.org" in url else UA
    return urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout).read()


def article(url):
    """(og:image, text) of an article page; ("", "") on failure."""
    try:
        raw = get(url).decode("utf8", "ignore")
    except Exception as e:
        log(f"  article fetch failed {url[:70]}: {e}")
        return "", ""
    meta = lambda p: html.unescape((re.search(
        r'<meta[^>]+(?:property|name)=["\']%s["\'][^>]+content=["\']([^"\']+)' % p, raw)
        or re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']%s["\']' % p, raw)
        or [None, ""])[1])
    paras = [html.unescape(re.sub(r"<[^>]+>", "", p)).strip()
             for p in re.findall(r"<p[^>]*>(.*?)</p>", raw, re.S)]
    body = " ".join(p for p in paras if len(p) > 60)[:3500]
    return meta("og:image"), (meta("og:title") + ". " + meta("og:description") + "\n" + body).strip()


def gnews_url(link):
    """Google News RSS links are redirects; resolve to the real article URL
    (signature + timestamp from the article page, then Google's own
    batchexecute call). None on any failure."""
    try:
        aid = link.split("/articles/")[1].split("?")[0]
        h = get("https://news.google.com/articles/" + aid).decode("utf8", "ignore")
        sg = re.search(r'data-n-a-sg="([^"]+)"', h).group(1)
        ts = int(re.search(r'data-n-a-ts="([^"]+)"', h).group(1))
        req = [[["Fbv4je", json.dumps(["garturlreq", [["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1,
                 None, None, None, None, None, 0, 1], "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0],
                 aid, ts, sg]), None, "generic"]]]
        body = urllib.parse.urlencode({"f.req": json.dumps(req)}).encode()
        r = urllib.request.urlopen(urllib.request.Request(
            "https://news.google.com/_/DotsSplashUi/data/batchexecute", data=body,
            headers={**UA, "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"}),
            timeout=20).read().decode()
        return re.search(r'garturlres\\",\\"(https?://[^"\\]+)', r).group(1)
    except Exception as e:
        log(f"  google news link not resolved: {e}")
        return None


# ---------- candidates ----------

def en_candidates(reels):
    import news_pool
    rows = news_pool.pool()["rows"]
    if reels:
        seen = {r["id"] for r in rows}
        rows = sorted(rows + [r for r in news_pool.pool(videos=True)["rows"] if r["id"] not in seen],
                      key=lambda r: -r["score"])
    out = []
    for r in rows:
        if gates.POLITICS.search(r["text"]) or re.fullmatch(r"\S*https?://\S+", r["text"]):
            continue
        v = r.get("video")
        if reels and r["lane"] == "discovery" and not TECH.search(r["text"]):
            continue  # random viral clips: only when the post itself is about tech
        if reels:
            if not v or not v.get("ms") or not (8_000 <= v["ms"] <= 180_000):
                continue
            if min(v.get("w") or 0, v.get("h") or 0) < 640:
                continue
        tag = {"official": "[O]", "outlets": "[N]", "discovery": "[D]"}[r["lane"]]
        out.append({**r, "tag": tag + (" [V]" if v else "") + f" @{r['author']}",
                    "text": r["text"] + (f" (quoting: {r['quoted']})" if r.get("quoted") else "")})
    return out[:40 if reels else 45]


def he_candidates():
    import il_news
    items = il_news.harvest()["items"]
    # cap the editor batch (140 items hung the call): newest first, one per title
    seen, uniq = set(), []
    for i in sorted(items, key=lambda i: i["age_h"]):
        k = re.sub(r"\W+", "", i["title"])[:40]
        if k not in seen:
            seen.add(k)
            uniq.append(i)
    # direct-feed articles first (they carry photos and full text), then the
    # newest Google News items (they add outlet counts) up to 40
    direct = [i for i in uniq if "news.google." not in i["link"]]
    items = direct[:28] + [i for i in uniq if "news.google." in i["link"]][:40 - len(direct[:28])]
    return [{**i, "lane": "outlets", "score": 100, "tag": f"[IL {i['outlet']}]",
             "text": i["title"] + (f" | {i['desc'][:160]}" if i.get("desc") else "")}
            for i in items]


def he_score(stories, recent, today):
    """Hebrew virality = distinct Israeli outlets on the story. Mix rule:
    about half Israeli-angle, so the angle the day is short of gets +1."""
    todays = [h for h in recent if h["date"][:10] == today]
    il_today = sum(1 for h in todays if h.get("israeli"))
    want_il = il_today * 2 <= len(todays)
    for s in stories:
        outlets = {m["outlet"] for m in s["members"]}
        s["score"] = len(outlets) * 100 + (100 if bool(s.get("israeli_angle")) == want_il else 0)


# ---------- writing ----------

WRITE_HINT = """Return ONLY JSON:
{"headline": "<the white-box headline, one plain news sentence, max LIMIT characters>",
 "kicker": "<optional 1-3 word label above the headline, or empty>",
 "lead": "<caption line 1: the headline as one full sentence>",
 "lines": ["<2 to 4 short plain lines: what happened, the key number or quote, why it matters>"],
 "source": "<outlet or official account names, comma separated>",
 "hashtags": ["#a", "#b", "#c"]}
RULES: "kicker" is usually empty; use it only for a strong label the headline lacks (like a date or "first in Israel"), never the company name.
"source" = the original outlet or company named in the material (e.g. "Politico", "OpenAI"), plain names, no @. Never an aggregator account (Polymarket, MarioNawfal, unusual_whales, TheInsiderPaper, kimmonismus, rowancheung, tsarnick, testingcatalog); if they quote an outlet, name that outlet.
"source" names at most 2 outlets, the best-known ones in the material.
Never repeat the lead in other words; if the material is thin, write just 2 lines.
Each caption line is one short sentence (max 110 characters) stating a fact from the material. No commentary, no "one of the most", no predictions, nothing the material does not say."""


def write(story, lang, reel=False, extra=""):
    facts = []
    for m in story["members"][:5]:
        facts.append(f"- {m.get('tag', '')} {m['text'][:600]}")
    if story.get("article"):
        facts.append("ARTICLE: " + story["article"][:3500])
    he = lang == "he"
    prompt = f"""{open(os.path.join(HERE, 'doctrine.md')).read()}

You write one {'reel' if reel else 'news card'} for {PAGES[lang]['handle']} in {'HEBREW, natively (not a translation; plain Israeli Hebrew)' if he else 'English'}.
THE STORY (in plain words): {story['story12']}
SOURCE MATERIAL (the only facts you may use):
{chr(10).join(facts)}
{"The video credit is the ORIGINAL uploader: " + story['video']['orig_user'] + " on X. The headline must describe exactly what the clip shows." if reel else ""}
{extra}
{WRITE_HINT.replace('LIMIT', '55' if he else '70')}
{"Hashtags in Hebrew (Latin brand names like #OpenAI are fine). Source line names the Israeli outlets." if he else ""}"""
    for attempt in range(3):
        w = llm.call(prompt)
        w = {k: (llm.clean(v) if isinstance(v, str) else [llm.clean(x) for x in v] if isinstance(v, list) else v)
             for k, v in w.items()}
        errs = qa(w, lang)
        if not errs:
            return w
        log(f"  writer QA failed: {errs}")
        prompt += "\n\nYOUR LAST ANSWER FAILED THESE CHECKS, fix them:\n- " + "\n- ".join(errs)
    return None


def qa(w, lang):
    errs = []
    limit = 60 if lang == "he" else 78
    if not w.get("headline") or len(w["headline"]) > limit:
        errs.append(f"headline must be 1-{limit} characters")
    if not (2 <= len(w.get("lines") or []) <= 4):
        errs.append("2 to 4 caption lines")
    tags = w.get("hashtags") or []
    if len(tags) != 3 or not all(t.startswith("#") and " " not in t for t in tags):
        errs.append("exactly 3 hashtags, each starting with #, no spaces")
    allt = " ".join([w.get("headline", ""), w.get("lead", ""), *(w.get("lines") or [])])
    # shouting = 2+ all-caps words in a row; single acronyms (CNBC, NVIDIA) are fine
    caps = re.findall(r"\b[A-Z]{2,}(?:\s+[A-Z]{2,}\b)+", allt)
    if any(set(c.split()) - ACRONYMS for c in caps):
        errs.append(f"no all-caps shouting: {caps}")
    if BANNED.search(allt):
        errs.append(f"banned phrase: {BANNED.search(allt).group(0)}")
    if any(len(x) > 120 for x in w.get("lines") or []):
        errs.append("each caption line max 110 characters")
    if re.search(r"@|polymarket|marionawfal|unusual_whales|insiderpaper", w.get("source", ""), re.I):
        errs.append("source must be the original outlet or company, plain name, no aggregator")
    if "?" in w.get("headline", ""):
        errs.append("headline is a statement, not a question")
    if re.search(r"[\U0001F300-\U0001FAFF]", allt):
        errs.append("no emojis")
    if lang == "he" and not re.search("[֐-׿]", w.get("headline", "")):
        errs.append("headline must be Hebrew")
    return errs


def caption(w, lang):
    src = ("מקור: " if lang == "he" else "Source: ") + w["source"]
    return "\n".join([w["lead"], "", *w["lines"], "", src, " ".join(w["hashtags"])])


# ---------- photos ----------

PHOTO_PICK = """Candidate photos for a news card are attached (if not attached, use your Read tool on: FILES).
The story: STORY
Pick the best one to show under the headline, the way a news site would. Best: a photo of the actual event or product; next: the person the story is about; next: the company's building, sign or store. It must be a real photograph (not an AI-generated or rendered illustration, even if the article used one; not a screenshot of text, not a slide, not a logo on a plain background, not a chart), not blurry, without big baked-in text or another news page's watermark. Never a photo of a different person or company than the story's. A photo filed under the story's company or person name IS that company or person (its building, sign, product or face), and that is fine. Return ONLY JSON: {"pick": <index from 0, or -1 if none qualifies>, "focus_y": <0.0-1.0, vertical position in the picked photo of the most important thing to keep visible (a person's FACE if there is one; 0 = top edge)>, "reason": "<short>"}"""


def wiki_images(name, n=2):
    """Free-license photos of a person/company: the Wikipedia lead image plus
    Commons search hits, JPEGs at least 900px wide, at most 1600px."""
    out = []
    if not name:
        return out
    api = lambda host, **q: json.loads(get(f"https://{host}/w/api.php?" + urllib.parse.urlencode(
        {"action": "query", "format": "json", "prop": "imageinfo", "iiprop": "url|size|mime",
         "iiurlwidth": 1600, **q})))
    try:
        for host, q in (("en.wikipedia.org", {"titles": name, "prop": "pageimages|imageinfo",
                                               "piprop": "name", "redirects": 1}),
                        ("commons.wikimedia.org", {"generator": "search", "gsrsearch": f"{name} filetype:bitmap",
                                                   "gsrnamespace": 6, "gsrlimit": 6})):
            d = api(host, **q)
            pages = d.get("query", {}).get("pages", {}).values()
            if host.startswith("en."):
                files = [p["pageimage"] for p in pages if p.get("pageimage")]
                if not files:
                    continue
                pages = api("commons.wikimedia.org", titles="File:" + files[0]).get("query", {}).get("pages", {}).values()
            last = name.split()[-1].lower()
            for p in sorted(pages, key=lambda p: p.get("index", 0)):
                if host.startswith("commons") and last not in p.get("title", "").lower():
                    continue  # search hits must be filed under the name itself
                ii = (p.get("imageinfo") or [{}])[0]
                if ii.get("mime") == "image/jpeg" and ii.get("width", 0) >= 900:
                    out.append(ii.get("thumburl") or ii["url"])
                if len(out) >= n:
                    return out
    except Exception as e:
        log(f"  wiki images failed for {name}: {e}")
    return out


def logo(story, workdir):
    """(path, credit, name) of the story's main company logo: the repo's own
    ig/logos/<name>.svg, else the Wikipedia infobox image when it is a logo
    file (Wikimedia Commons); (None, "", name) when there is none."""
    names = [n for n in [story.get("company")] + [e.get("name") for e in story.get("entities") or []] if n]
    for n in names[:2]:
        local = os.path.join(HERE, "logos", re.sub(r"[^a-z0-9]", "", n.lower()) + ".svg")
        if os.path.exists(local):
            return local, "", n
        try:
            d = json.loads(get("https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(
                {"action": "query", "format": "json", "titles": n, "prop": "pageimages",
                 "piprop": "thumbnail|name", "pithumbsize": 900, "redirects": 1})))
            for pg in d.get("query", {}).get("pages", {}).values():
                if "logo" in (pg.get("pageimage") or "").lower() and pg.get("thumbnail"):
                    p = os.path.join(workdir, "logo.png")
                    open(p, "wb").write(get(pg["thumbnail"]["source"]))
                    return p, "Logo: Wikimedia Commons", n
        except Exception as e:
            log(f"  logo lookup failed for {n}: {e}")
    return None, "", (names[0] if names else "")


def photo(story, workdir):
    urls = []
    for m in story["members"]:
        if m.get("img"):
            urls.append((m["img"], m.get("name") or m.get("author") or m.get("outlet"), "image attached to the news post"))
    if story.get("og_image"):
        urls.append((story["og_image"], story.get("article_outlet") or "the article", "the news article's main image"))
    # fallback: free-license lead photo of the story's people/companies
    # (Wikipedia/Commons); the vision pick below rejects logos
    for e in (story.get("entities") or [])[:2]:
        urls += [(u, "Wikimedia Commons", f"free photo filed under '{e.get('name')}'")
                 for u in wiki_images(e.get("name") or "")]
    files = []
    from PIL import Image
    for u, who, what in urls:
        if len(files) >= 5 or any(u == f[2] for f in files):
            continue
        try:
            data = get(u)
            p = os.path.join(workdir, f"cand{len(files)}.jpg")
            open(p, "wb").write(data)
            im = Image.open(p)
            if im.width < 600 or im.height < 400:
                continue
            im.convert("RGB").save(p, "JPEG", quality=92)
            files.append((p, who, u, what))
        except Exception as e:
            log(f"  photo fetch failed {u[:60]}: {e}")
    if not files:
        log("  no photo candidates at all")
        return None
    r = llm.call(PHOTO_PICK.replace("FILES", ", ".join(f"{f[0]} (cand{i}: {f[3]})" for i, f in enumerate(files)))
                 .replace("STORY", story["story12"]), model=llm.JUDGE, images=[f[0] for f in files])
    i = r.get("pick", -1)
    if not isinstance(i, int) or not 0 <= i < len(files):
        log(f"  no usable photo: {r.get('reason')}")
        return None
    fy = min(max(float(r.get("focus_y") or 0.3), 0.0), 1.0)
    if Image.open(files[i][0]).height > Image.open(files[i][0]).width:
        fy = min(fy, 0.25)  # portraits: heads live near the top, never crop them off
    return {"path": files[i][0], "who": files[i][1], "focus": (0.5, fy)}


# ---------- reels ----------

def clip_ok(src, story):
    frames = []
    for frac in (0.15, 0.5, 0.85):
        fp = src + f".f{int(frac * 100)}.jpg"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss",
                        str(story["video"]["ms"] / 1000 * frac), "-i", src, "-frames:v", "1", fp])
        if os.path.exists(fp):
            frames.append(fp)
    if len(frames) < 2:
        return False, "no frames"
    r = llm.call(
        f"Frames from one video clip are attached (if not attached, use your Read tool on {', '.join(frames)}). "
        f"We will post it as a news reel about: {story['story12']}. usable:true only if (1) the frames really show "
        "that (the video itself is the news or a real wow moment, not a talking head, slide, keynote stage or meme), "
        "(2) it is not blurry, and (3) there is no OTHER social page's handle or watermark baked in (the original "
        "company's own logo is fine). Also return what the clip literally shows in one plain sentence. "
        'Return ONLY JSON: {"usable": true/false, "shows": "...", "reason": "..."}',
        model=llm.JUDGE, images=frames)
    for f in frames:
        os.remove(f)
    return bool(r.get("usable")), r.get("shows") or r.get("reason") or ""


def black_bars(src, dur_s):
    """crop=W:H:X:Y that removes dark bars baked into the source (a vertical
    phone clip inside a 16:9 frame), or "" when there are none. Scans three
    frames: a row/column is a bar if it is dark in all of them."""
    from PIL import Image, ImageStat
    frames = []
    for k, frac in enumerate((0.2, 0.5, 0.8)):
        fp = f"{src}.bar{k}.png"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(dur_s * frac), "-i", src,
                        "-frames:v", "1", fp])
        if os.path.exists(fp):
            frames.append(Image.open(fp).convert("L"))
            os.remove(fp)
    if not frames:
        return ""
    w, h = frames[0].size
    dark_col = lambda x: all(ImageStat.Stat(f.crop((x, 0, x + 1, h))).mean[0] < 32 for f in frames)
    x0 = next((x for x in range(0, w // 2, 2) if not dark_col(x)), 0)
    x1 = next((x for x in range(w - 1, w // 2, -2) if not dark_col(x)), w - 1)
    # rows are judged inside the picture's columns only (side bars would darken every row)
    dark_row = lambda y: all(ImageStat.Stat(f.crop((x0, y, x1, y + 1))).mean[0] < 32 for f in frames)
    y0 = next((y for y in range(0, h // 2, 2) if not dark_row(y)), 0)
    y1 = next((y for y in range(h - 1, h // 2, -2) if not dark_row(y)), h - 1)
    cw, ch = (x1 - x0 + 1) // 2 * 2, (y1 - y0 + 1) // 2 * 2
    if cw * ch > 0.9 * w * h or cw < 200 or ch < 200:
        return ""
    return f"crop={cw}:{ch}:{x0}:{y0},"


def build_reel_video(src, overlay_png, top, out, dur_s):
    """Clip fills the transparent area under the headline box: fit inside
    (never zoomed/cropped), blurred copy of itself behind it. Black bars
    baked into the source are cropped off first."""
    ah = 1920 - top
    clip = min(dur_s, 59)
    vf = (f"[0:v]{black_bars(src, dur_s)}split[a][b];"
          f"[a]scale=1080:{ah}:force_original_aspect_ratio=increase,crop=1080:{ah},"
          f"boxblur=24:2,eq=brightness=-0.18[bg];"
          f"[b]scale=1080:{ah - 340}:force_original_aspect_ratio=decrease[fg];"
          f"[bg][fg]overlay=(W-w)/2:max(0\\,({ah}-340-h)/2)[mid];"
          f"[mid]pad=1080:1920:0:{top}:color=black[base];"
          f"[base][1:v]overlay=0:0,format=yuv420p[v]")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-t", str(clip), "-i", src,
                    "-i", overlay_png, "-filter_complex", vf, "-map", "[v]", "-map", "0:a?",
                    "-c:v", "libx264", "-preset", "medium", "-b:v", "6M", "-r", "30",
                    "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", out], check=True)


# ---------- build ----------

def slug(t):
    s = re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")[:48].strip("-")
    return s or "story"


def slot_taken(kind, lang, day, slot):
    """Post dir already reserved for this page/kind/day/slot (by a cron run or
    by the backup dispatch, backup_dispatch.py): never build a second one."""
    root = os.path.join(HERE, PAGES[lang]["posts"])
    for d in os.listdir(root) if os.path.isdir(root) else []:
        pj = os.path.join(root, d, "post.json")
        if d.startswith(day) and os.path.exists(pj):
            try:
                p = json.load(open(pj))
            except Exception:
                continue
            if p.get("kind") == kind and p.get("slot_time") == day and str(p.get("slot")) == str(slot):
                return d
    return None


def build(kind, lang, day, out_root=None, extra_hist=(), slot=None):
    reels = kind == "reel"
    if slot not in (None, "now"):
        taken = slot_taken(kind, lang, day, slot)
        if taken:
            print(f"SKIP: {lang} {kind} slot {slot} already has {taken}")
            return None
        import slot as slotmod
        late = (datetime.now(ZoneInfo(PAGES[lang]["tz"])) - slotmod.target(lang, kind, slot)).total_seconds()
        if late > slotmod.MAX_LATE_S or late < -5 * 3600:  # < -5h: the run crossed local midnight
            print(f"SKIP: {lang} {kind} slot {slot} is {late / 60:.0f} min past (the next slot covers it)")
            return None
    recent = gates.history(lang, extra_dirs=extra_hist)
    if lang == "he" and not reels:
        cands = he_candidates()
    else:
        cands = en_candidates(reels)
    log(f"{kind} {lang} {day}: {len(cands)} candidates, {len(recent)} recent posts")
    stories = gates.judge(cands, lang, recent, reels=reels)
    by_id = {c["id"]: c for c in cands}
    for s in stories:
        s["members"] = [by_id[i] for i in s.get("ids", []) if i in by_id]
    ok = gates.apply(stories, cands, lang, recent, day, reels=reels, log=log)
    if lang == "he" and not reels:
        # a global story needs one established Israeli newsroom (il_news.REPUTABLE)
        # or 2+ outlets; small sites alone are not enough (2026-10-06: the old
        # "2+ outlets" rule killed nearly every Hebrew slot)
        from il_news import REPUTABLE
        thin = [s for s in ok if not s.get("israeli_angle")
                and len({m["outlet"] for m in s["members"]}) < 2
                and not any(m["outlet"] in REPUTABLE for m in s["members"])]
        for s in thin:
            log(f"  kill (1 small outlet, no Israeli angle) {s['story12']}")
        ok = [s for s in ok if s not in thin]
        he_score(ok, recent, day)
        ok.sort(key=lambda s: -s["score"])
        # hard quota (owner target ~half Israeli): the day's last card slot
        # must be Israel-angle if none ran yet and one passed the gates
        todays = [h for h in recent if h["date"][:10] == day and h["dir"].count("-reel-") == 0]
        il = [s for s in ok if s.get("israeli_angle")]
        if len(todays) >= 2 and not any(h.get("israeli") for h in todays) and il:
            log("  Israeli quota: last card slot goes to an Israel-angle story")
            ok = il
    root = out_root or os.path.join(HERE, PAGES[lang]["posts"])
    for s in ok[:10]:  # owner 2026-10-06: keep going down the list (8+ tries)
        log(f"  building: {s['story12']}")
        s["slot"] = slot
        work = tempfile.mkdtemp()
        try:
            res = (make_reel if reels else make_card)(s, lang, day, root, work)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        if res:
            print("post ready:", res)
            return res
    print(f"SKIP: no {kind} story passed the gates for {lang}")
    return None


def enrich(s):
    """Article text + main image for the writer and the photo pick."""
    links = [l for m in s["members"] for l in (m.get("links") or [m.get("link")]) if l]
    # direct article links first, then resolved Google News links
    links = sorted(links, key=lambda l: "news.google." in l)
    for l in links[:4]:
        if "news.google." in l:
            l = gnews_url(l)
            if not l:
                continue
        img, text = article(l)
        # a bot-check page (ynet blocks CI runners) has no og tags and no
        # paragraphs: text is just "." -> not an article, try the next link
        if len(text) < 150:
            log(f"  no article text at {l[:70]} (blocked?)")
            continue
        s["article"], s["og_image"] = text, img
        s["article_outlet"] = next((m.get("outlet") for m in s["members"] if m.get("link") == l), None) \
            or re.sub(r"^www\.", "", urllib.parse.urlparse(l).netloc)
        break


def finish(post_dir, w, s, lang, day, kind, extra):
    meta = {"lang": lang, "kind": kind, "headline": w["headline"], "story12": s["story12"],
            "entities": s.get("entities"), "company": s.get("company"),
            "musk": bool(s.get("musk_world")), "israeli": bool(s.get("israeli_angle")),
            "slot_time": day, "slot": s.get("slot"), "sources": [m.get("url") or m.get("link") for m in s["members"]],
            "story": {"link": (s["members"][0].get("url") or s["members"][0].get("link"))}, **extra}
    json.dump(meta, open(os.path.join(post_dir, "post.json"), "w"), indent=1, ensure_ascii=False)


def make_card(s, lang, day, root, work):
    enrich(s)
    ph = photo(s, work)
    if not ph:
        # owner 2026-10-06: never drop a passing story for lack of a photo;
        # real photo first, else the company logo / typographic brand card
        lg, credit, name = logo(s, work)
        log(f"  photo fallback: {'logo ' + lg if lg else 'typographic card'} ({name})")
        fb = news_card.render_fallback(lang, name or PAGES[lang]["handle"], lg,
                                       os.path.join(work, "fallback.png"))
        ph = {"path": fb, "who": "", "focus": (0.5, 0.5), "credit": credit}
    w = write(s, lang)
    if not w:
        log("  writer failed QA 3 times")
        return None
    post_dir = os.path.join(root, f"{day}-{slug(w['headline'] if lang == 'en' else s['story12'])}")
    os.makedirs(post_dir, exist_ok=True)
    news_card.render_card({"lang": lang, "headline": w["headline"], "kicker": w.get("kicker") or "",
                           "photo": ph["path"], "focus": ph["focus"],
                           "credit": ph.get("credit", f"Photo: {ph['who']}")},
                          os.path.join(post_dir, "slide-1.jpg"))
    open(os.path.join(post_dir, "caption.txt"), "w").write(caption(w, lang))
    finish(post_dir, w, s, lang, day, "card", {"photo_credit": ph["who"]})
    return post_dir


def make_reel(s, lang, day, root, work):
    # every distinct video on the story, best member first: one clip failing
    # QA (e.g. a promo ad) falls back to the next one (owner 2026-10-06)
    vids = list({m["video"]["mp4"]: m["video"] for m in s["members"] if m.get("video")}.values())
    src, ok = os.path.join(work, "src.mp4"), False
    for v in vids[:3]:
        s["video"] = v
        try:
            open(src, "wb").write(get(v["mp4"], timeout=180))
        except Exception as e:
            log(f"  video download failed: {e}")
            continue
        ok, shows = clip_ok(src, s)
        log(f"  clip QA: {ok} ({shows})")
        if ok:
            break
    if not ok:
        return None
    w = write(s, lang, reel=True, extra=f"WHAT THE CLIP LITERALLY SHOWS (checked by a viewer): {shows}")
    if not w:
        return None
    post_dir = os.path.join(root, f"{day}-reel-{slug(w['headline'] if lang == 'en' else s['story12'])}")
    os.makedirs(post_dir, exist_ok=True)
    card = {"format": "reel", "lang": lang, "headline": w["headline"], "kicker": w.get("kicker") or "",
            "credit": f"Video: {v['orig_user']} on X"}
    ov = os.path.join(post_dir, "overlay.png")
    top = news_card.render_overlay(card, ov)
    out = os.path.join(post_dir, "reel.mp4")
    build_reel_video(src, ov, top, out, v["ms"] / 1000)
    if os.path.getsize(out) < 200_000:
        shutil.rmtree(post_dir)
        return None
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "1", "-i", out,
                    "-frames:v", "1", os.path.join(post_dir, "frame.jpg")])
    import bundle
    cap = caption({**w, "source": f"{v['orig_user']} on X"}, lang).replace(
        "Source:", "Video:").replace("מקור:", "וידאו:")
    json.dump({"title": w["headline"], "caption": cap,
               "source": v.get("orig_url") or s["members"][0]["url"], "channel": v["orig_user"],
               # bundle.social workspace = the EN account only; HE reels use the HE Make route
               "publish": "bundle" if lang == "en" and bundle.budget_left() else "make"},
              open(os.path.join(post_dir, "reel.json"), "w"), indent=1, ensure_ascii=False)
    finish(post_dir, w, s, lang, day, "reel", {"video": v})
    return post_dir


def main():
    sys.stdout.reconfigure(line_buffering=True)
    a = sys.argv[1:]
    kind, lang = a[0], a[1]
    tz = ZoneInfo(PAGES[lang]["tz"])
    day = a[a.index("--date") + 1] if "--date" in a else str(datetime.now(tz).date())
    if kind == "preview":
        out = a[a.index("--out") + 1]
        made = []
        for k in ("card", "card", "card", "reel", "reel"):
            d = build(k, lang, day, out_root=out, extra_hist=made)
            if d:
                made.append(d)
        return
    slot = a[a.index("--slot") + 1] if "--slot" in a else None
    if not build(kind, lang, day, slot=slot):
        sys.exit(0)


if __name__ == "__main__":
    main()
