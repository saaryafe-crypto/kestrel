#!/usr/bin/env python3
"""Writer agent: turns the top story in stories.json into a daily_item post.
Usage: python3 write.py [stories.json]
Picks the best direct-link story (prefers one with a press image), fetches the
article text, asks Claude for the post JSON (daily_item container spec), runs
the QA gate, then renders slides into posts/<date>-<slug>/.
Uses the anthropic SDK if ANTHROPIC_API_KEY is set, else falls back to
`claude -p` (Claude Code CLI) so it's testable with zero keys."""
import json, os, re, subprocess, sys
from datetime import date

from fetch import get  # same dir; shared HTTP helper with UA
import genimg
import viral  # the packaging agent: classify -> per-type hooks -> blind judge

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = "claude-opus-4-6"  # newest Opus (owner call Jul 27: best writer runs the page; cost is fine — CI uses the subscription token)

SCHEMA = {
    "type": "object",
    "properties": {
        "container": {"type": "string", "enum": ["daily_item", "builder_story"]},
        "product_url": {"type": "string"},
        "cover_style": {"type": "string", "enum": ["photo", "logos", "type"]},
        "logos": {"type": "array", "items": {"type": "string"}, "maxItems": 2},
        "badge_logo": {"type": "string"},
        "slides": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["cover", "content", "cta"]},
                    "hsize": {"type": "integer", "minimum": 54, "maximum": 124},
                    "headline": {"type": "string"},
                    "body": {"type": "string"},
                    "media_idx": {"type": "integer"},
                    "product_shot": {"type": "boolean"},
                    "image_brief": {"type": "string"},
                    "layout": {"type": "string", "enum": ["card"]},
                    "discs": {
                        "type": "array", "maxItems": 2,
                        "items": {
                            "type": "object",
                            "properties": {"logo": {"type": "string"},
                                           "text": {"type": "string"}},
                        },
                    },
                },
                "required": ["type", "hsize", "headline"],
            },
        },
        "caption": {"type": "string"},
        "pinned_comment": {"type": "string"},
        "hook_candidates": {
            "type": "array", "minItems": 5,
            "items": {
                "type": "object",
                "properties": {"headline": {"type": "string"}},
                "required": ["headline"],
            },
        },
    },
    "required": ["slides", "caption", "hook_candidates"],
}


def article_text(url, cap=4000):
    try:
        html = get(url).decode("utf-8", "ignore")
    except Exception:
        return ""
    paras = re.findall(r"<p[^>]*>(.*?)</p>", html, re.S)
    text = " ".join(re.sub(r"<[^>]+>", "", p) for p in paras)
    return re.sub(r"\s+", " ", text).strip()[:cap]


SHOT_QA_SCHEMA = {"type": "object", "properties": {"usable": {"type": "boolean"}},
                  "required": ["usable"]}


def product_screenshot(url, post_dir):
    """Headless-Chrome screenshot of the builder's actual product page — the
    honest proof artifact the reference example uses on its proof slide.
    Vision-QA'd: loading screens, cookie walls, captchas and blanks return
    None, and the slide falls back to article imagery."""
    chrome = os.environ.get("CHROME",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    png = os.path.join(post_dir, "product.png")
    try:
        subprocess.run([chrome, "--headless", "--disable-gpu", "--hide-scrollbars",
                        "--window-size=1080,1350", "--timeout=20000",
                        f"--screenshot={png}", url],
                       capture_output=True, timeout=90, check=True)
        if os.path.getsize(png) < 30000:  # blank pages compress to almost nothing
            return None
        r = call_claude(
            f'A screenshot is attached (if not attached to this message, use your Read tool on {png} to look at it). Is it a REAL, fully-loaded product/website page that a news post could show as proof the product exists? Answer usable:false if it is a loading screen/spinner, cookie or consent wall, error page, captcha, login wall, or mostly empty. Return ONLY JSON: {{"usable": true/false}}',
            schema=SHOT_QA_SCHEMA, images=[png])
        if r.get("usable"):
            return png
        print("product screenshot rejected by vision QA", file=sys.stderr)
    except Exception as e:
        print(f"product screenshot failed ({e})", file=sys.stderr)
    return None


IMG_QA_SCHEMA = {"type": "object",
                 "properties": {"usable": {"type": "boolean"},
                                "score": {"type": "integer"},
                                "flaw": {"type": "string"}},
                 "required": ["usable", "score"]}


def image_score(path, headline, generated=False):
    """Vision judge for slide images. Returns (usable, score 0-10, flaw).
    usable = publish as-is; the score ranks sibling attempts (owner rule
    Jul 29: never generate forever — cap the spend and take the BEST of what
    exists, a slot never ships imageless); the flaw feeds the brief rewrite.
    Judged at phone-feed size: a flaw nobody can see at that size is not a
    flaw (Circle K post-mortem: strong covers died for tiny garbled UI
    pixels while the post shipped with NO image — the rubric punished the
    best option). Fails closed: (False, 0, "")."""
    clean = re.sub(r"</?em>", "", headline)
    face_gate = (
        'FACE GATE (owner rule Aug 1, GENERATED images only — unfamiliar AI faces convert badly): if a human face is prominent, it must read as a RECOGNIZABLE famous person; a generic invented face nobody would recognize = usable:false, flaw "unfamiliar generated face". Faceless people (from behind, silhouette, hands) are fine. '
        if generated else "")
    try:
        r = call_claude(
            f'An AI-generated image is attached (if not attached to this message, use your Read tool on {path} to look at it). It would fill the photo band of an Instagram news slide with this headline: "{clean}". Judge it AT PHONE FEED SIZE — a flaw a follower cannot see at that size does not count against it. '
            'SCORE against the scroll-stopper formula (each worth points): ONE dominant focal subject, brightest and sharpest thing in frame (no competing focal points); the image dramatizes THIS exact headline claim — moment, stakes or consequence visible in half a second (not generic topical art); bright saturated colors with one punchy accent (not murky, not pastel, not white-dominant); if a person is central, the face is large and radiates one clear strong emotion; looks like a real press photo (texture, grain, candid light), not plastic AI art. '
            + face_gate +
            'Score 0-10: 10 = a professional photo editor would run it AND it nails the formula; 7 = publishable; 4 = clearly flawed but recognizable and on-claim; 0 = unusable garbage. usable:true means publish as-is — set false for flaws a scrolling follower would actually notice: garbled text large enough to read, warped hands/faces, obvious AI plastic look, watermark, no connection to the claim, or a dark/murky frame with no focal subject. flaw: the single biggest problem in 12 words or less (empty string if none). Return ONLY JSON: {{"usable": true/false, "score": 0-10, "flaw": "..."}}',
            schema=IMG_QA_SCHEMA, images=[path])
        return bool(r.get("usable")), int(r.get("score", 0)), r.get("flaw", "")
    except Exception as e:
        print(f"genimg QA failed ({e}) — scoring 0", file=sys.stderr)
        return False, 0, ""


def image_ok(path, headline):
    """Boolean wrapper kept for callers that only need pass/fail."""
    ok, _, _ = image_score(path, headline)
    return ok


BRIEF_SCHEMA = {"type": "object", "properties": {"brief": {"type": "string"}},
                "required": ["brief"]}


def simpler_brief(brief, headline, flaw=""):
    """Ladder rung between generation attempts (Circle K post-mortem: the old
    retry re-ran the SAME brief and failed the same way). Rewrites the
    rejected brief into a cleaner, harder-to-botch shot — fewer elements =
    fewer artifacts — steered by the judge's named flaw. Fails open to the
    original brief."""
    clean = re.sub(r"</?em>", "", headline)
    flaw_line = f'The judge named the biggest flaw: "{flaw}". Remove its cause first.\n' if flaw else ""
    try:
        r = call_claude(
            f'An AI image generator produced an UNUSABLE image (artifacts, garbled text, or stock look) from this brief:\n"{brief}"\n{flaw_line}The image must still be evidence for this headline: "{clean}". Rewrite the brief SIMPLER so the next attempt survives: ONE subject, ONE action, ZERO readable text anywhere (screens show SYMBOLS only: a $ symbol, a warning triangle, a red cross — symbols never garble), no crowds, no close-up hands or faces, plainer setting, keep the color key. 15-35 words, subject first. Return ONLY JSON: {{"brief": "..."}}',
            schema=BRIEF_SCHEMA)
        b = r.get("brief", "").strip()
        if b:
            print(f"brief rewritten: {b[:90]}", file=sys.stderr)
        return b
    except Exception as e:
        print(f"brief rewrite failed ({e}) — retrying the original", file=sys.stderr)
        return ""


ART_SCHEMA = {"type": "object", "properties": {"briefs": {
    "type": "array", "items": {"type": "object", "properties": {
        "idx": {"type": "integer"}, "brief": {"type": "string"}},
        "required": ["idx", "brief"]}}},
    "required": ["briefs"]}


def art_direct(post, story_title=""):
    """The image prompt generator (owner directive Jul 29: don't only reject
    bad images — engineer prompts that produce great ones, every image costs
    money). One call rewrites the writer's slide image concepts into
    Seedream-optimal briefs, built on the measured failure pattern from the
    Circle K run: 5 of 6 images died to ONE flaw — the model garbles any real
    sentence it must render (screens, signs, tape), while SYMBOLS render
    perfectly. Runs after the hook tournament so it directs for the FINAL
    cover headline. Fails open: writer's briefs stay."""
    items = [{"idx": i,
              "headline": re.sub(r"</?em>", "",
                                 s.get("headline") or (s.get("body") or "")[:90]),
              "concept": s.get("image_brief", "")}
             for i, s in enumerate(post["slides"]) if s.get("image_brief")]
    if not items:
        return
    prompt = f"""You are the cover-image director of a viral news Instagram page. You write the final image-generation prompts for the Seedream photo model. The doctrine below is distilled from published research on scroll-stopping feed imagery (thumbnail CTR studies: emotional faces +42%, image-headline synergy up to +154%; MrBeast-school single-focal analysis; 2026 anti-AI-slop guides) — follow it exactly. The image fills the top two-thirds of the frame above the headline and gets ~0.4 seconds at phone size.

STORY: {story_title}
SLIDES (index, final headline, the writer's rough concept):
{json.dumps(items, ensure_ascii=False, indent=1)}

THE JOB: the image DRAMATIZES the exact claim of that slide's headline — the peak moment, the consequence, or the stakes — so the image raises the question and the headline answers it. A stranger seeing image + headline together gets the claim in one second. Never the topic in general, never a metaphor, never stock wallpaper.

ROLE-CAST (owner's gold standard, Aug 1): when the claim is about what a product or company CAN DO, cast the story's famous face IN THE ROLE the claim describes, mid-performance with that role's real props. Reference: "Claude has an unlimited personal tutor mode" → Anthropic's CEO AS the tutor — leaning over a desk in a warm home library, pen in hand, teaching a student whose shoulder frames the foreground. The person doesn't react to the claim, they ACT IT OUT; the scene props (pen, notebook, bookshelves) and the story-world background make the metaphor literal. Prefer this over a reaction face whenever the story has a doer + a capability.

CLASH-CAST (owner's gold standard, Aug 1): when the story is a clash or a deal between TWO named famous people — a buyer and a seller, a winner and a loser, a hunter and the hunted — put BOTH recognizable likenesses in ONE composed scene that acts out the power dynamic: the winner looming calm and in command, the loser cornered mid-loss, faces large and close together, one clearly dominant. The story's world rages behind them (a trading floor of crashing red chart lines, a courtroom, a launchpad). Reference: the $45B fire-sale story → the young founder slumped at the deal table while the older billionaire stands over him signing, walls of red crashing charts behind. The pair reads as ONE unit; this beats a lone reaction face whenever the story has two famous sides. NAME both people explicitly in the prompt ("Ken Griffin", never "a silver-haired billionaire" — measured Aug 1: unnamed archetypes drift into the WRONG famous face); if a side is not famous enough for the model to know, that person appears FACELESS (from behind, silhouette, or hands only — see the faces rule below), and if neither side is famous, drop CLASH-CAST entirely and dramatize with objects and stakes instead.

FORMAT — every prompt contains these five parts in order (20-45 words total):
1. HERO: ONE focal subject, concretely named (the real device/brand/person from the headline — or the CLASH-CAST pair as one unit), frozen at the peak of the exact moment — mid-fall, mid-launch, mid-signature. One focal point only; it is the brightest, sharpest thing in frame.
2. EMOTION — when the story's person is FAMOUS, the hero IS that person's recognizable likeness at 40%+ of frame height, named explicitly, eyes to camera or locked on the story's object, radiating ONE nameable exaggerated emotion (shock, awe, dread, triumph). Name the emotion in the prompt. FAMOUS FACES ONLY (owner rule Aug 1: generated unfamiliar faces = low conversion, no good outcome): if the story's person is not famous enough for a viewer to recognize, NEVER generate a face — show them from behind, as a silhouette, hands-and-props only, or cut them out of frame entirely and let the objects and stakes carry the drama.
3. STAKES IN FRAME: make the money/scale/damage physically visible — the pile of cash, the wreckage, the crowd, the giant object beside a person for scale. Stakes a viewer can read in half a second.
4. WORLD: the background is the story's real world (the factory floor, the launchpad, the brand's storefront) carrying context — softer, darker and simpler than the hero. Never an empty void, never white.
5. ACCENT: end with ONE saturated accent color pulled from the subject, set against a darker complementary surround ("accent: signal red against deep blue dusk"). Warm saturated accents stop scrolls; whole-frame murk and pastels do not.

CRAFT (bake into every prompt):
- Real press photograph, never digital art: include "documentary news photo, 35mm, harsh on-camera flash, natural skin texture, slight film grain". This is the #1 lever that keeps generated images from looking like cheap AI.
- ZERO readable words anywhere in frame (measured on our own runs: the model garbles every rendered sentence — 5 of 6 images died to this one flaw). Screens, signs and papers speak in SYMBOLS ONLY, named concretely: "a giant red $ symbol", "a warning triangle", "a crashing red chart line".
- BANNED looks: purple-teal "AI glow", glowing holograms, circuit-board brains, waxy plastic skin, sci-fi concept art, moody dark murk, white backgrounds, two competing focal points, two emotions.
- BANNED subjects: any invented/generic human face ("a young founder", "an office worker", "a scientist"). Every visible face must be a NAMED famous likeness; everyone else is faceless (behind / silhouette / hands) or absent.

Return ONLY JSON: {{"briefs": [{{"idx": <slide index>, "brief": "..."}}]}}"""
    try:
        r = call_claude(prompt, schema=ART_SCHEMA)
        n = 0
        for b in r.get("briefs", []):
            i = b.get("idx")
            if isinstance(i, int) and 0 <= i < len(post["slides"]) and b.get("brief", "").strip():
                post["slides"][i]["image_brief"] = b["brief"].strip()
                n += 1
        print(f"art director rewrote {n} image brief(s)", file=sys.stderr)
    except Exception as e:
        print(f"art director failed ({e}) — keeping writer's briefs", file=sys.stderr)


IMG_ATTRS = re.compile(r'<img[^>]+?src=["\']([^"\']+)["\']', re.I)


def article_images(url, max_out=5, max_try=12):
    """Candidate images from the article page (og/twitter meta + body <img>),
    junk-filtered, width-verified from bytes. The reference page puts a proof
    image on nearly every slide — one og:image per story isn't enough."""
    try:
        html = get(url).decode("utf-8", "ignore")
    except Exception:
        return []
    cands = []
    for pat in (r'property=["\']og:image["\'][^>]*content=["\']([^"\']+)',
                r'content=["\']([^"\']+)["\'][^>]*property=["\']og:image["\']',
                r'name=["\']twitter:image(?::src)?["\'][^>]*content=["\']([^"\']+)'):
        cands += re.findall(pat, html)
    cands += IMG_ATTRS.findall(html)
    out, seen, tried = [], set(), 0
    from fetch import jpeg_width
    for u in cands:
        u = u.replace("&amp;", "&")
        if not u.startswith("http"):
            from urllib.parse import urljoin
            u = urljoin(url, u)
        if not u.startswith("http") or u.split("?")[0] in seen:
            continue
        if re.search(r"\.(svg|gif)(\?|$)|logo|icon|avatar|sprite|badge|1x1|pixel|placeholder", u, re.I):
            continue
        seen.add(u.split("?")[0])
        if tried >= max_try or len(out) >= max_out:
            break
        tried += 1
        try:
            data = get(u, timeout=10)
        except Exception:
            continue
        w = 0
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            w = int.from_bytes(data[16:20], "big")
        elif data[:3] == b"\xff\xd8\xff":
            w = jpeg_width(data)
        elif data[:4] == b"RIFF" and data[8:12] == b"WEBP" and len(data) > 80_000:
            w = 1000  # width not parsed; large webp is almost always a real photo
        if w >= 900 and len(data) < 8_000_000 and not any(data == d for _, d in out):
            out.append((u, data))
    return out


def slugify(title):
    return re.sub(r"\W+", "-", title.lower()).strip("-")[:40]


def already_posted(slug):
    posts = os.path.join(HERE, "posts")
    return os.path.isdir(posts) and any(d.endswith(slug) for d in os.listdir(posts))


def recent_posts(n=30):
    """Headlines of the last n published posts, derived from posts/ folder
    names (no separate state file to drift). Reel folders are skipped — their
    names carry video ids, not headlines."""
    posts = os.path.join(HERE, "posts")
    if not os.path.isdir(posts):
        return []
    dirs = sorted(d for d in os.listdir(posts)
                  if re.match(r"\d{4}-\d{2}-\d{2}-", d) and "-reel-" not in d)
    return [re.sub(r"^\d{4}-\d{2}-\d{2}-", "", d).replace("-", " ").strip()
            for d in dirs[-n:]]


DUPE_SCHEMA = {"type": "object", "properties": {"dupe": {"type": "boolean"}},
               "required": ["dupe"]}


def is_dupe(title, recent=None):
    """Semantic dedupe — the same story worded differently is still the same
    story (Jul 28: the Threads/Meta-AI news published twice 2h apart because
    two feeds worded it differently and the slug check passed both). Fails
    open: if the judge call breaks, don't block publishing."""
    recent = recent_posts() if recent is None else recent
    if not recent:
        return False
    listing = "\n".join(f"- {t}" for t in recent)
    try:
        r = call_claude(f"""ALREADY PUBLISHED on our Instagram page (recent posts, titles slug-shortened):
{listing}

CANDIDATE NEW STORY: "{title}"

Is the candidate the SAME underlying story as any already-published post — same event, announcement, or fact, even if worded completely differently? A genuinely NEW development in an ongoing saga counts as a different story; the same news re-reported does not.
Return ONLY JSON: {{"dupe": true or false}}""", schema=DUPE_SCHEMA)
        return bool(r.get("dupe"))
    except Exception as e:
        print(f"dupe judge failed ({e}) — allowing story", file=sys.stderr)
        return False


PICK_SCHEMA = {"type": "object", "properties": {"pick": {"type": "integer"}},
               "required": ["pick"]}


def pick_story(stories):
    """Claude picks the story a NORMAL person would care most about — not the most
    technically impressive one. Measured from the reference page: reader-impact
    stories (your money/phone/job) and famous names beat obscure tech every time."""
    direct = [s for s in stories if "news.google.com" not in s["link"]]
    fresh = [s for s in direct if not already_posted(slugify(s["title"]))]
    recent = recent_posts()
    # exhaust EVERY candidate before declaring the slot dead (owner rule:
    # 7/day is a must — a 3-try cap killed the Jul 28 test run when the top 3
    # were all dupes of that morning's posts while story #4 was fine)
    while fresh:
        s = _rank(fresh[:12], recent)  # rank in windows of 12 to keep the prompt tight
        if not is_dupe(s["title"], recent):
            return s
        print(f"semantic dupe of a published post — skipping: {s['title']}",
              file=sys.stderr)
        fresh = [x for x in fresh if x is not s]
    return None


def scoreboard_block():
    """Own-page engagement (market.py's daily Mac scrape, rows sorted by
    likes). Deliberately labeled a WEAK signal until ~30 posts exist —
    Owner call Jul 28: the audience is too small yet to trust; wire the
    loop now, let it gain weight as volume arrives."""
    try:
        rows = json.load(open(os.path.join(HERE, "scoreboard.json")))
    except Exception:
        return ""
    if len(rows) < 5:
        return ""
    n = len(rows)
    strength = ("STRONG signal" if n >= 30 else
                f"WEAK signal — only {n} posts measured, use as a light tiebreak only")
    lines = [f"OUR OWN page's measured results ({strength}). Best performers:"]
    lines += [f"- {r['likes']} likes: {r['hook']}" for r in rows[:3]]
    lines.append("Worst performers:")
    lines += [f"- {r['likes']} likes: {r['hook']}" for r in rows[-2:]]
    return "\n".join(lines) + "\n\n"


def _rank(fresh, recent=()):
    if len(fresh) == 1:
        return fresh[0]
    def _tag(s):
        t = "(has press image) " if s.get("image") else ""
        if s.get("radar"):  # live breakout — real crowd velocity, right now
            m = s["radar"]
            t += (f"(LIVE: {m['score']:,} {m.get('unit', 'upvotes')} on "
                  f"{m.get('where', 'r/' + m['sub'])} in {m['age_h']:.0f}h) ")
        return t
    lines = "\n".join(f"[{i}] {_tag(s)}{s['title']}" for i, s in enumerate(fresh))
    published = ("ALREADY PUBLISHED on our page (recent posts, slug-shortened):\n"
                 + "\n".join(f"- {t}" for t in recent)
                 + "\nA candidate that is the SAME underlying story as any of these — even "
                 "worded completely differently — is DISQUALIFIED. Never pick it.\n\n"
                 if recent else "")
    # money-proof slot (slot mix Aug 1): the 20:00 UTC slot prefers a case
    # study — a real business used AI and got a measurable result. Preference,
    # not a hard filter: if no candidate qualifies, normal ranking decides
    # (the always-post ladder stays intact).
    pref = ""
    if os.environ.get("STORY_PREF") == "money":
        pref = ("PRIORITY OVERRIDE for this slot: STRONGLY prefer a MONEY-PROOF "
                "case study — a real, named business (or named person running "
                "one) that used AI and got a measurable result (money made or "
                "saved, hours cut, customers won). Only if NO candidate has a "
                "business-result-with-a-number do the normal rules below "
                "decide.\n\n")
    prompt = f"""{published}{scoreboard_block()}{pref}Pick the ONE story below that our audience would care most about. The page's paying audience is US small-business OWNERS — the goal is that an owner reads the post and books a meeting. Ranking rules, in order:
1. Gives a business owner real value: a result, tool, or number they could use in their own business (AI that saved a company money, replaced hours of work, brought customers — a case study with numbers is gold)
2. Touches the reader's own life: their money, their phone, their job, apps everyone uses
3. Names everyone knows (Apple, Tesla, Musk, ChatGPT, Netflix...) beat unknown startups and GitHub projects
4. Jaw-drop factor for a YOUNG scroller (19, not a newspaper reader): would they say "wait, WHAT?" out loud. A PERSON doing something outrageous ("a 19-year-old built an app that...") beats an institutional announcement ("company released a feature that...") of similar weight — companies announce, people DO things.
5. A press image is a small tiebreak bonus
A technically impressive but obscure story LOSES to a smaller story the reader can feel or USE. A dry corporate announcement LOSES to a person-driven story with a concrete outcome.

STORIES:
{lines}

Return ONLY a JSON object: {{"pick": <index>}}"""
    try:
        r = call_claude(prompt, schema=PICK_SCHEMA)
        return fresh[r["pick"]] if 0 <= r.get("pick", -1) < len(fresh) else fresh[0]
    except Exception as e:
        print(f"story pick failed ({e}) — falling back to first", file=sys.stderr)
        return fresh[0]


def inspiration():
    """Style DNA distilled from posts the owner liked (ig/inspiration/learned.md)."""
    p = os.path.join(HERE, "inspiration", "learned.md")
    if not os.path.exists(p):
        return ""
    return ("\nOWNER'S TASTE — distilled from posts he loved. Imitate the patterns, NEVER copy text:\n"
            + open(p).read()[:6000] + "\n")


def principles():
    """Evidence-backed virality rulebook (ig/inspiration/principles.md). Outranks style imitation."""
    p = os.path.join(HERE, "inspiration", "principles.md")
    if not os.path.exists(p):
        return ""
    # cap raised Aug 1: the 16000 slice was silently cutting the last third of
    # the file (incl. the whole $100M Offers funnel section) out of every prompt
    return ("\nVIRALITY PRINCIPLES — research-backed rules. When style imitation and a [STRONG] rule conflict, the rule wins:\n"
            + open(p).read()[:32000] + "\n")


def no_dashes(t):
    """Owner rule (Jul 28): dashes are BANNED in published text (the em dash
    is the #1 AI-writing tell). Em/en dashes and spaced hyphens become commas;
    compound-word hyphens (first-sale, AI-written) are untouched."""
    if not isinstance(t, str):
        return t
    t = re.sub(r"\s*[—–]\s*", ", ", t)
    t = re.sub(r"(?<=\w) - (?=\w)", ", ", t)
    return re.sub(r",\s*,", ",", t)


def scrub_dashes(post):
    """Applies no_dashes to every field that reaches the published slides or
    caption. Records (story title, tournament candidates) stay untouched."""
    for s in post.get("slides", []):
        for k in ("headline", "body"):
            if s.get(k):
                s[k] = no_dashes(s[k])
    if post.get("caption"):
        post["caption"] = no_dashes(post["caption"])
    if post.get("pinned_comment"):
        post["pinned_comment"] = no_dashes(post["pinned_comment"])
    return post


RETELL_SCHEMA = {"type": "object", "properties": {
    "retell": {"type": "string"},
    "facts": {"type": "array", "items": {"type": "string"}}},
    "required": ["retell", "facts"]}
LOOKUP_SCHEMA = {"type": "object", "properties": {
    "look_up": {"type": "boolean"}, "why": {"type": "string"}},
    "required": ["look_up", "why"]}


def retell_story(story, body_text):
    """The anti-news-speak step (owner Jul 28: 'we cant write FROM the article
    ...this is the biggest killer'). The slide writer never sees raw article
    prose again — it gets (a) the story retold OUT LOUD by a 19-year-old,
    which locks the register, and (b) a bullet list of verified facts, which
    keeps accuracy without carrying the article's newspaper voice (bullets
    are fragments; prose register can't survive them). A gate judges the
    retell alone — 'does your friend look up from their phone?' — and one
    retry hunts a harder angle. Fails open: None -> old article-text path."""
    src = body_text or story["title"]
    base = f"""Here is a news story.
Title: {story['title']}
Article: {src}

You are 19. You just read this. Your friend sits across the table, scrolling their phone. You have 10 seconds to make them look up. Give:
1. "retell": the story in 2-3 sentences EXACTLY as you'd SAY it out loud. Lead with the consequence for a normal person — their money, their phone, their job, their feed — never with the announcement. No word a 16-year-old wouldn't use out loud. No company-speak ("announced", "unveiled", "platform", "capabilities"). If you can't say it without sounding like the news, you haven't found the story yet.
2. "facts": every name, number, quote, date, and concrete detail from the article worth using later, as short bullets — the accuracy net. Only things actually in the article.

Return ONLY JSON: {{"retell": "...", "facts": ["...", ...]}}"""
    try:
        r = call_claude(base, schema=RETELL_SCHEMA)
        for attempt in range(2):
            g = call_claude(f"""Your friend at the table looks up from their phone and says this to you, out of nowhere:
"{r['retell']}"
Are you genuinely hooked — do you say "wait, what?" and want the rest? Answer honestly; most news retellings fail this. Return ONLY JSON: {{"look_up": true or false, "why": "one blunt sentence"}}""",
                           schema=LOOKUP_SCHEMA)
            if g.get("look_up") or attempt:
                break
            print(f"boring retell ({g.get('why', '?')}) — hunting a harder angle",
                  file=sys.stderr)
            r2 = call_claude(base + f"""

YOUR FIRST TRY FAILED — a listener said: "{g.get('why', 'boring')}". Find a different angle: the money, the fear, or the absurdity in this story. Say the single most shocking consequence FIRST, as a claim about the listener's own life if you honestly can.""",
                             schema=RETELL_SCHEMA)
            r = r2 or r
        return r
    except Exception as e:
        print(f"retell failed ({e}) — falling back to article text", file=sys.stderr)
        return None


def build_prompt(story, body_text, media_files, retold=None, steer=""):
    spec = json.load(open(os.path.join(HERE, "containers.json")))
    logos = sorted(f[:-4] for f in os.listdir(os.path.join(HERE, "logos"))
                   if f.endswith(".svg"))
    if media_files:
        names = ", ".join(os.path.basename(m) for m in media_files)
        img_block = f"""{len(media_files)} candidate images from the article are ATTACHED, in order (image 1 = {os.path.basename(media_files[0])}, ...): {names}. If no images are attached to this message, use your Read tool to look at these files in {os.path.dirname(media_files[0])} before writing.
IMAGE ASSIGNMENT — every slide may set "media_idx": N (1-based, matching that order); omit it for no image:
- LOOK at each candidate first. Reject any that is stock-looking, blurry, watermarked, a logo, or emotionally flat — a bad image is worse than none.
- COVER: the most emotionally matching image — a human face or the product/scene in action. A face-only headshot is allowed only when the story IS about that person.
- INNER slides: an image is a PROOF artifact for THAT slide's claim (screenshot, demo photo, video still). The reference page puts one on nearly every slide — assign whenever one genuinely fits the slide's specific claim.
- Never assign the same image to two slides."""
    else:
        img_block = "No usable article images were found."
    proof = ""
    if story.get("ig_proof"):
        p = story["ig_proof"]
        proof = (f"\nPROVEN ON INSTAGRAM — a giant tech page (millions of followers) already "
                 f"posted this exact story and got {p['likes']:,} likes ({p['ratio']}x their own "
                 f"median). Their hook:\n\"{p['hook']}\"\nSteal the ANGLE that made it win — "
                 "which emotion it leads with, which single detail it makes concrete — "
                 "NEVER copy the wording.\n")
    if story.get("radar"):
        m = story["radar"]
        cm = "\n".join(f'- "{c}"' for c in (m.get("top_comments") or [])[:5])
        proof += (f"\nBREAKING OUT RIGHT NOW — {m['score']:,} "
                  f"{m.get('unit', 'upvotes')} on {m.get('where', 'r/' + m['sub'])} "
                  f"in {m['age_h']:.0f} hours."
                  + (f" {m['views']:,} views." if m.get("views") else ""))
        if cm:
            proof += (" The TOP COMMENTS below are thousands of real people voting on which "
                      "EMOTION this moment triggers — the winning hook angle is IN them. Write "
                      "the cover to the exact feeling the crowd already voted for; never quote "
                      f"or copy a comment.\n{cm}")
        proof += ("\nSOURCE DISCIPLINE: a social post is a CLAIM, not verified journalism. "
                  "Write only what the post itself SHOWS — describe the event, never the "
                  "coverage. Attribution phrases are BANNED from slides (\"a Reddit user "
                  "says\", \"a viral post claims\", \"according to\", \"reportedly\") — "
                  "they are newsreader hedges that kill the story. If a claim is only "
                  "someone's word and the footage doesn't show it, CUT the claim instead "
                  "of hedging it. The source gets credited once, in the caption's Sources "
                  "line, never on a slide.\n")
    if retold:
        facts = "\n".join(f"- {f}" for f in retold["facts"])
        story_block = f"""THE STORY — as a 19-year-old told it to a friend. This is your REGISTER: the post must sound like this person talking, never like the news article underneath:
{retold['retell']}

RAW MATERIAL — verified facts from the article, the ONLY place you may pull names, numbers, and specifics from:
{facts}"""
    else:
        story_block = f"Article text (may be partial): {body_text or '(unavailable — write from the title only, no invented specifics)'}"
    return f"""You write Instagram carousels for @yaffeai — a page covering AI, technology, space, business, investing, and money in the style of @technology, funneling followers to an AI-consulting business. Turn this story into a **daily_item** post.

STORY
Title: {story['title']}
Source: {story['link']}
{story_block}
{proof}
COVER VISUAL
{img_block}
IMAGE BRIEFS (mandatory) — besides article images we have an AI image generator. EVERY cover and content slide must ALSO set "image_brief": 15-40 words, subject FIRST, then action, then setting (the generator needs that order). The image must be EVIDENCE of that slide's exact claim, frozen at the exact moment it happens — the test: could a lawyer submit it as an exhibit for the headline? (claim "touch screen" → a real hand physically touching the screen; claim "device lock" → the phone showing it; claim "books destroyed" → the blade mid-cut through the page stack). NEVER a generic person-at-laptop or "a robot" for a robot story. NAME real devices and brands ("a silver MacBook Pro", not "a laptop") — the generator renders them accurately. End the brief with ONE color key tied to the subject ("keyed to deep orange") — one bright saturated accent, never a dark or moody scene. Include a real human face when a person or a reaction is the story — one person, mid-action, face expressive and visible. The image may include AT MOST one short on-screen phrase, ONLY when that phrase IS the claim: write it in double quotes and say where it appears (a phone screen showing "Device Locked"); otherwise the scene has zero text — never signs, menus, or paragraphs, generators garble them. Slides that get a real article image keep it (real beats generated); the brief is the fallback for slides without one.
Pick "cover_style":
- "photo" — STRONGLY PREFERRED whenever the press photo exists AND passes the rule above. The photo fills the top ~60% of the cover; the headline sits on a solid black band below it (like the big news pages)
- "logos" — 1-2 company logos rendered big on the dark cover, only when there is no usable photo (X vs Y or company stories). Available logo names: {', '.join(logos)}. Only these names.
- "type" — big-headline-only dark cover (last resort)
"logos" array may ALSO be set together with "photo": the logo(s) are overlaid on top of the photo (one logo max in that case — pick the company the story is about). NEVER overlay a flat logo when the photo shows a person's face — it lands on top of them and looks amateur; for a famous person's photo use the COMPOSED COVER discs instead (below) and leave logos empty
NO SUBLINE (owner rule Aug 1): under the cover headline the design shows only a small "SWIPE FOR MORE" strip — nothing else. Every word of the hook must live in the big headline itself.

{principles()}
{inspiration()}
CONTAINER SPEC (daily_item): {json.dumps(spec['containers']['daily_item'])}
CONTAINER SPEC (builder_story): {json.dumps(spec['containers']['builder_story'])}
CAPTION BLOCKS: {json.dumps(spec['caption_blocks'])}
QA GATE: {json.dumps(spec['qa_gate'])}

Pick "container": "builder_story" ONLY if this story is about a tiny team / solo founder building something outsized with AI (follow its spec); otherwise "daily_item".
For builder_story: if the article names the product's own website, set top-level "product_url" to it and set "product_shot": true on the PROOF slide — the pipeline will screenshot the real page and put it on that slide (the honest proof artifact). Only one slide may set it.

OUTPUT — a single JSON object: {{"container": "...", "cover_style": "...", "logos": [...], "slides": [...], "caption": "...", "pinned_comment": "..."}}
Slides for daily_item — THE QUESTION CHAIN. This is how the reference page tells stories, measured word-for-word from their posts:
The cover plants a question in the reader's head. Every next slide answers EXACTLY that question — one big statement (the headline) + the precise details (the body) — and the answer plants the NEXT question. The chain ends when the reader has no questions left: 4-10 slides total. A tight 4-slide chain beats a padded 9. NEVER pad, never repeat a fact across slides.
RETENTION DOCTRINE (research-backed, 2026 carousel studies — high swipe-through earns 3-5x non-follower reach and a 24-48h re-serve):
- STORY ARC, not a list: stakes → escalation → TWIST → consequence → payoff. Slides must depend on each other in order; if a reader could read them shuffled, it's a listicle and it dies.
- PAYOFF PLACEMENT: the answer to the cover's question NEVER lands before slide 4 (in the shortest chains: on the last content slide). If the hook resolves on slide 2, swiping stops. Slides 2-3 escalate the stakes and deepen the question instead.
- THE TWIST: one mid-carousel slide (around slide 4) is a pattern interrupt — the most contrarian or absurd TRUE fact in the story, the "wait, WHAT?" moment that re-hooks tired swipers.
- OPEN LOOP AT EVERY BOUNDARY: each body's final line creates the exact itch the next headline scratches ("Then the numbers came in"). No slide ends settled except the last.
- SHARE TRIGGER (name it before writing): every post must fire at least one — awe, outrage, amusement, usefulness ("save this"), or identity ("people like me send this"). A merely-informative post gets zero shares; pick the angle that fires the trigger hardest.
- THE STANCE (owner directive Aug 1 — we don't report, we ARGUE): the payoff slide's final sentence is a TAKE, one blunt sentence saying what this MEANS ("This is the first time AI cost someone $45 billion in a week", "Your accountant should be nervous"). It must be sharp enough that a reader could comment "wrong" — a post that ends on a neutral fact is a news wire, not a page people follow. The take is built from the story's true facts, never invented.
- SENTENCE RHYTHM: short-short-long. Two punches, then one sentence that builds and lands on a 3-5 word hammer. Bodies target 25 words or less; every sentence's only job is to get the next one read.
KEEP/CUT — what belongs in the story (owner directive Jul 31: "people want the story itself", the retellings drowned in names and quotes):
KEEP: what physically happened, in order; the money and the numbers; the one consequence that touches the reader; names ONLY if a random 16-year-old already knows them (Musk, Apple, OpenAI) or the story is literally about that person becoming known.
CUT: every other name (a researcher, a VP, a spokesperson — say "the engineers", "the company"); quotes from random internet users or commenters (NEVER quote a Reddit/X user on a slide); job titles; the outlet that reported it; how the news spread ("went viral", "the internet reacted"); anything a reader would skim. Every sentence must advance what HAPPENED — if it only adds who said it, cut it.
The model to copy (owner-written, Jul 29 — the Visa story done right):
  Cover: "VISA JUST BET <em>EVERYTHING</em>" → reader thinks: bet everything on WHAT?
  Slide 2: "VISA LAID OFF <em>2,600 EMPLOYEES</em>" — the first concrete fact lands HERE, never on the cover → reader thinks: why?
  Slide 3: "THE MONEY GOES INTO <em>AI</em>" — billions moved from salaries into one technology → reader thinks: isn't that risky?
  Slide 4: "MOST BANKS <em>REFUSE TO TOUCH IT</em>" — why the rest of the industry is scared → reader thinks: so what does Visa know?
  Slide 5: "HERE'S WHAT VISA KNOWS <em>THAT BANKS DON'T</em>" — the payoff
Every slide answers one question while creating the next one. Before writing each slide, name the question the previous slide planted — if the slide doesn't answer it, rewrite the slide.
Structure:
1. type "cover": THE HOOK — the single most important thing in the whole post (see COVER HOOK below). No body.
2. type "content": first chain answer. Doubles as the SECOND COVER — Instagram re-serves skipped carousels with slide 2 as the cover, so its headline must hook standalone, never "Here's how" or "The details".
3+. type "content": the rest of the chain. Each headline = a 5-9 word standalone factual CLAIM someone could disagree with — NEVER a label ("THE DETAILS", "THE REAL STORY", "WHAT THIS MEANS FOR X") and NEVER an aphorism/motivational line ("X BEATS Y"). Use physical past-tense verbs (parked, gutted, handed, escaped — never "is using", "means", "finds") and put a number in the headline whenever the story has one. Body = 2-3 short sentences, EVERY sentence a concrete number/name/date in <b>; ranks/records when TRUE (first, biggest, Xth-largest ever); famous-name anchors.
Second-to-last. type "content": THE VALUE SLIDE — the consulting-funnel slide, built with the $100M Offers rules (section 5 of the principles). Open with the business owner's PAIN this story touches, then the escape: what a normal business can DO with this, with a concrete number, and why it's now fast/effortless ("without hiring anyone"). Its headline is a factual claim with a number too — never a lesson or a "what this means" label. The reader-owner should finish it thinking "I want this in MY business". Same visual style, no selling tone, no price ever.
Last. type "cta": THE FOLLOW CONVERSION — must extend THIS story's open loop into the future, never a generic service pitch (audit Jul 29: story-specific FOMO converts several times better; "Daily AI news" register now FAILS QA). Formula: [this story's consequence continues] + the follow ("Visa won't be the last. Follow — you'll want to see who's next" / "This robot doubles in ability every year. Follow and watch it happen"). Body: ONE sentence containing a specific SEND line naming the exact person-type this story hits ("Send this to the friend who still types every email himself") — a send-line is utility; "tag a friend" is banned bait.
For builder_story follow its container spec slide order instead (same question-chain style).

PROFILE CARD FORMAT (owner gold-standard example Aug 1 — the @techskills Mercor post; optional, use it ONLY when the story is ONE PERSON'S RISE — a founder/inventor profile with a record or a huge number — AND at least 3 real article photos exist; never for company/product news):
- Every content slide sets "layout": "card" and "headline": "" — the story lives in the BODY: 2-3 tiny paragraphs (blank line between), each 1-2 micro-sentences, ONE fact per sentence. The register is a biography told in flashcards: "His name is Surya Midha.\n\nIndian-origin. Parents from Delhi.\n\nBorn in Mountain View. Raised in San Jose." Numbers/names in <b>; the ONE money/record phrase per slide in <em> (this is the only place <em> is allowed in a body).
- Every card slide gets a REAL photo (media_idx) — childhood/early shots, the team, the product; the photo renders in a rounded card under the text and is the proof artifact. image_brief only as a last-resort fallback.
- Slide order = a life arc: who he is → the early feat → the founding → what the thing does + the money number → the growth numbers → the record + the stance. Same open-loop rule at every boundary.
- The COVER for this format is the exception to the 9-word cap: one 12-24 word record-sentence that tells the WHOLE claim, structured [record] + [how, in plain words] ("A 22 year old just became the youngest self made billionaire in history. He built an AI recruiting tool with 2 college friends"), hsize 54-58, <em> on the record phrase. The absurd true claim IS the hook; there is no hidden twist to protect.
- If the story's company logo exists in our logo set, set top-level "badge_logo" to it and make sure the cover image puts the person RIGHT of center (the badge chip renders top-left).

COMPOSED COVER (owner gold standard Aug 1 — the @getintoai anatomy; STRONGLY PREFERRED whenever eligible): when the cover's real article photo (media_idx) shows the story's FAMOUS person — one person, chest-up, face clear — set "discs" on the cover slide: 1-2 elements that complete the story equation beside the face. First disc = the story company's logo (only names from the logo list). Second disc = the exact product/object the headline claims, as SHORT typeset text, 12 characters max ("OPUS 5", "CODEX", "$45B MEMO") — or a second logo when the story pairs two brands. The pipeline cuts the person out of the photograph, blurs the photo's own world into the backdrop, floats the discs at head height and layers the person OVER them — face, logos and background all connected to the claim (reference: Sam Altman shushing between the OpenAI badge and a terminal icon; Anthropic's CEO between the Claude disc and an "Opus 5" disc). Rules: ONLY on a real press photo of a famous person — never on a generated image, never an unknown face; every disc must be RELATIONAL (the brand of the story + the thing the headline claims — a disc that could sit on any post is banned); skip discs when the photo has multiple people or the person is a tiny part of the frame. If the cutout fails, the pipeline falls back to the plain photo cover automatically.

COVER HOOK — the #1 priority. The cover decides whether anyone swipes. OWNER DOCTRINE (Jul 29, restated verbatim after approving the Visa v2 cover — overrides everything older): "Your job is NOT to explain. Your job is to make someone incapable of not swiping." Built ONLY from true facts in the story.
{steer}
General craft (the STORY TYPE formula above decides what leads; these rules shape it):
- HARD CAP 9 words, aim for 4-8. Short = giant letters = stops the scroll. Anything the STORY TYPE formula doesn't put on the cover belongs on slide 2 instead.
- Reference craft (a corporate_move story done right — for OTHER types the lead changes but the compression lesson holds): the winner was "VISA JUST BET <em>EVERYTHING</em>" (4 words, total gap); the failure was "VISA JUST LAID OFF 2,600 WORKERS TO INVEST IN A TECHNOLOGY MOST BANKS REFUSE TO TOUCH" — the whole story on slide 1, 17 words rendering as a wall of text.
- Charged verbs and power words when true: BET, FIRED, DECLARED WAR, ROGUE, SECRET, QUIETLY, BANNED, LEAKED, EXPOSED, ON PURPOSE. Threat/loss framing beats triumph framing when both are true. Second person ("YOUR") when the story touches the reader. Simple 8th-grade words only.
- Banned on covers: neutral news-title phrasing, hedging (may/could/reportedly), company-PR framing, anything a newspaper would print unchanged, and any brand name a random 16-year-old wouldn't recognize (use the universal noun the STORY TYPE block names instead).
- Self-test before finalizing (all must pass): (1) does the headline follow THIS story type's formula above? (2) Could the cover describe 100 different stories? If yes → too vague — anchor to ONE specific event. (3) Is the reader left with a burning question (what/why/how) the next slide must answer? If not → the cover closed the loop, rewrite it.
- HOOK TOURNAMENT (mandatory): write FIVE genuinely different cover candidates in "hook_candidates" — different angles (threat vs record vs money vs scarcity subject), not rewordings. Each: {{"headline": "... with <em> accents ..."}}. Put your best one on the cover slide AND include it among the five. A separate blind judge will pick the winner.

RULES
- LANGUAGE (hard requirement): write for a smart 16-year-old. Everyday words only, short sentences. No industry jargon anywhere — headlines, bodies, caption. Say what things DO ("runs powerful AI on your own computer"), not what they're called ("an agentic runtime"). If a technical term is unavoidable, explain it in plain words in the same sentence.
- <em>...</em> in headlines marks the accent: ONE contiguous phrase, ideally a WHOLE LINE of the headline (two groups absolute max). Orange-on-entire-lines creates rhythm and a reading order; orange scattered across four single words is confetti — four competing focal points = zero focal points (owner verdict Jul 28). Connectives stay white. Every headline needs at least one <em>.
- <b>...</b> in bodies marks facts (names, numbers). No <em> in bodies.
- hsize: headline font px. Cover headlines (4-9 words) → 66-80 so the type is HUGE, breaking edge-to-edge in 2-4 tight lines like the reference page (the renderer caps total block height, so overly long covers just shrink — keep them short instead). Inner-slide headlines: short (≤5 words) → 110-124; medium → 90-105; long → 76-88.
- Bodies never end with a period (house style). No emojis in slides.
- Caption: all five blocks in order, separated by blank lines. Sources line names the actual outlet(s). Exactly five hashtags (topic keywords for search — hashtags don't add reach). The FIRST sentence carries the payoff AND the search keywords — IG is a search engine in 2026 and the first line drives Explore/search reach: name the company and the topic noun in plain words ("Visa is replacing 2,600 jobs with AI" — searchable; "They just bet everything 👀" — invisible). Only ~125 chars show before "...more". CTA must be utility ("save this", "send this to..."), NEVER reaction-bait ("tag a friend", "comment YES") — Meta penalizes bait.
- "pinned_comment" (mandatory): the first comment we plant under the post the second it publishes — hour-one comment velocity is distribution fuel. ONE of: a debatable fault line from the story people must answer ("Would you let it run your payroll? Half of you are lying") or the juiciest fact that didn't fit the slides ("The part we couldn't fit: ..."). 1-2 sentences, no hashtags, no links, never a summary of the post.
- Caption owner-CTA (mandatory): the LAST line of the trend block, on its own line, invites business owners to DM — pain + tiny ask, tied to this story's value. Register: "Running a business? DM us "AI" and we'll show you what this could do for yours". Vary the wording per post, keep the DM word exactly "AI"
- Never invent facts not present in the STORY material above.
- If cover_style is "photo" the headline sits over the photo — keep it short.

Return ONLY the JSON object, no markdown fences, no commentary."""


def call_claude(prompt, schema=None, images=None, model=None):
    # scraped article text can carry null bytes — they crash subprocess exec
    # (embedded null byte) and are invalid in API JSON anyway
    prompt = prompt.replace("\x00", "")
    use_model = model or MODEL
    if os.environ.get("ANTHROPIC_API_KEY"):
        import anthropic, base64
        client = anthropic.Anthropic()
        content = []
        for path in images or []:
            data = open(path, "rb").read()
            mt = ("image/png" if data[:8] == b"\x89PNG\r\n\x1a\n"
                  else "image/webp" if data[8:12] == b"WEBP" else "image/jpeg")
            content.append({"type": "image", "source": {
                "type": "base64", "media_type": mt,
                "data": base64.b64encode(data).decode()}})
        content.append({"type": "text", "text": prompt})
        with client.messages.stream(
            model=use_model, max_tokens=8000,
            thinking={"type": "adaptive"},
            output_config={"format": {"type": "json_schema", "schema": schema or SCHEMA}},
            messages=[{"role": "user", "content": content}],
        ) as stream:
            msg = stream.get_final_message()
        return json.loads("".join(b.text for b in msg.content if b.type == "text"))
    # fallback: Claude Code CLI, no key needed. Image prompts say "use your
    # Read tool on <path>" — grant Read + the images' dirs or the CLI stalls
    # asking for permission (seen Jul 28 on /tmp QA frames).
    cmd = ["claude", "--model", use_model, "-p", prompt]
    if images:
        cmd += ["--allowedTools", "Read"]
        for d in sorted({os.path.dirname(os.path.abspath(p)) for p in images}):
            cmd += ["--add-dir", d]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=1200).stdout
    m = re.search(r"\{.*\}", out, re.S)
    if not m:
        # RuntimeError, NOT SystemExit: callers with fail-open except-Exception
        # handlers (dupe judge, scout judge, vision QA) must be able to catch it
        raise RuntimeError(f"claude -p returned no JSON:\n{out[:500]}")
    return json.loads(m.group(0))


def qa(post):
    slides, caption = post["slides"], post["caption"]
    # profile-card format (@techskills anatomy, owner example Aug 1): card
    # slides carry the story in the body (no headline), and the cover is a
    # longer record-sentence — several gates relax for it
    profile = any(s.get("layout") == "card" for s in slides)
    errs = []
    if not (4 <= len(slides) <= 10):
        errs.append(f"{len(slides)} slides (want 4-10)")
    if slides[0]["type"] != "cover" or slides[-1]["type"] != "cta":
        errs.append("must open with cover, close with cta")
    for i, s in enumerate(slides):
        if s.get("layout") == "card":
            if not (s.get("body") or "").strip():
                errs.append(f"slide {i+1}: card slide has no body — the body IS "
                            "the story on card slides")
            continue
        if "<em>" not in s["headline"]:
            errs.append(f"slide {i+1}: headline has no <em> accent")
    # cover legibility + information gap (owner doctrine Jul 29: the cover
    # sells curiosity in 4-9 giant words; the facts live on slide 2+).
    # Profile covers instead tell the whole record-claim: up to 24 words.
    cover_cap = 24 if profile else 9
    cover_words = len(re.sub(r"<[^>]+>", "", slides[0]["headline"]).split())
    if cover_words > cover_cap:
        errs.append(f"cover headline is {cover_words} words (max {cover_cap})"
                    + ("" if profile else " — the cover creates the information "
                       "gap, the facts move to slide 2"))
    if len(re.findall(r"<em>", slides[0]["headline"])) > 2:
        errs.append("cover has >2 <em> groups — accent ONE contiguous phrase or "
                    "whole line (two max), scattered single-word accents are "
                    "confetti with zero focal point")
    # storytelling gates (owner directive Jul 31: the story itself, not the
    # coverage — no newsreader hedges, no random-user quotes, no slide walls)
    for i, s in enumerate(slides):
        text = re.sub(r"<[^>]+>", "", " ".join(
            filter(None, (s.get("headline", ""), s.get("body", "")))))
        if re.search(r"(?i)\b(reportedly|allegedly|according to|sources say|is said to)\b", text):
            errs.append(f"slide {i+1}: newsreader hedge (reportedly/according to...) — "
                        "state what happened or cut the claim; sources live in the caption")
        if re.search(r"(?i)\b(a|an|one|another) (reddit|x|twitter|instagram|internet)? ?"
                     r"(user|commenter|redditor)\b|\bviral post (claims|says)|\busers? (say|said|claim)", text):
            errs.append(f"slide {i+1}: quotes/cites a random internet user — cut it, "
                        "people want the story, not who said it")
        body_cap = 60 if s.get("layout") == "card" else 34
        body_words = len(re.sub(r"<[^>]+>", "", s.get("body") or "").split())
        if body_words > body_cap:
            errs.append(f"slide {i+1}: body is {body_words} words (max {body_cap}) — "
                        "a slide is a beat, not a paragraph: keep the one detail that "
                        "answers the question, move or cut the rest")
    if "Sources:" not in caption:
        errs.append("caption missing Sources line")
    if len(re.findall(r"#\w+", caption)) != 5:
        errs.append("caption must have exactly 5 hashtags")
    # story-specific follow CTA (audit Jul 29): the generic service pitch died.
    # container key only exists in the story flow — edu's save-CTA is exempt
    if post.get("container"):
        cta = " ".join(filter(None, (slides[-1].get("headline", ""),
                                     slides[-1].get("body", ""))))
        if re.search(r"(?i)daily (ai |tech )?news", cta):
            errs.append("cta slide is the generic 'daily AI news' pitch — it "
                        "must extend THIS story's open loop into a reason to "
                        "follow")
    if not post.get("pinned_comment", "").strip():
        errs.append("missing pinned_comment — one debatable question or "
                    "left-out fact to seed the comment thread")
    return errs


def main(stories_path):
    stories = json.load(open(stories_path))
    story = pick_story(stories)
    if not story:
        raise SystemExit("no usable story in stories.json")
    print("story:", story["title"], file=sys.stderr)

    body_text = article_text(story["link"])
    if not body_text and (story.get("radar") or {}).get("selftext"):
        body_text = story["radar"]["selftext"]  # reddit-native story: the post IS the article
    print(f"article text: {len(body_text)} chars", file=sys.stderr)

    post_dir = os.path.join(HERE, "posts", f"{date.today()}-{slugify(story['title'])}")
    os.makedirs(post_dir, exist_ok=True)

    media_files = []
    for i, (u, data) in enumerate(article_images(story["link"])):
        ext = ("png" if data[:8] == b"\x89PNG\r\n\x1a\n"
               else "webp" if data[8:12] == b"WEBP" else "jpg")
        path = os.path.join(post_dir, f"cand-{i+1}.{ext}")
        open(path, "wb").write(data)
        media_files.append(path)
    print(f"{len(media_files)} candidate images saved", file=sys.stderr)

    retold = retell_story(story, body_text)
    if retold:
        print(f"retell: {retold['retell'][:120]}", file=sys.stderr)

    # the viral agent classifies the story FIRST — the classification steers
    # the writer's hooks, the rival batch, and the judge's rubric (Circle K
    # post-mortem: one rubric for all story types picked the wrong hook)
    material = (retold["retell"] + "\n" + "\n".join(retold["facts"])
                if retold else body_text)
    ctx = viral.classify(story, material)
    print(f"viral classify: {ctx['story_type']}, actor '{ctx.get('actor')}' "
          f"{'known' if ctx.get('actor_known') else 'UNKNOWN -> anchor: ' + str(ctx.get('anchor'))}",
          file=sys.stderr)

    steer = viral.hook_block(ctx)
    prompt = build_prompt(story, body_text, media_files, retold, steer)
    for attempt in range(3):
        post = call_claude(prompt, images=media_files)
        errs = qa(post)
        if not errs:
            break
        print(f"QA gate failed (attempt {attempt+1}):\n  " + "\n  ".join(errs),
              file=sys.stderr)
        prompt = (build_prompt(story, body_text, media_files, retold, steer)
                  + "\n\nYOUR PREVIOUS ATTEMPT FAILED THESE QA CHECKS — fix every one:\n- "
                  + "\n- ".join(errs))
    else:
        raise SystemExit("QA gate failed after 3 attempts")

    if any(s.get("layout") == "card" for s in post["slides"]):
        # profile format: the long record-sentence cover IS the hook — the
        # tournament's 9-word pre-filter would kill it and rivals would
        # replace it with a short gap hook, destroying the format
        print("profile format: hook tournament skipped", file=sys.stderr)
        post.pop("hook_candidates", None)
    else:
        post = viral.tournament(post, story, ctx, material)
    post["viral"] = ctx  # he.py re-creates the Hebrew hook from this

    art_direct(post, story["title"])  # optimal image prompts for the FINAL cover

    shot = None
    if post.get("container") == "builder_story" and post.get("product_url", "").startswith("http"):
        shot = product_screenshot(post["product_url"], post_dir)
        print(f"product screenshot: {'ok' if shot else 'unusable'}", file=sys.stderr)

    used = set()
    for s in post["slides"]:
        mi = s.pop("media_idx", None)
        if s.pop("product_shot", False) and shot:
            s["media"] = os.path.relpath(shot, HERE)
            shot = None  # one slide only
            continue
        s["media"] = None
        if isinstance(mi, int) and 1 <= mi <= len(media_files) and mi not in used:
            used.add(mi)
            s["media"] = os.path.relpath(media_files[mi - 1], HERE)

    # FLUX claim-visualization images (owner call Jul 28, $3/mo): the COVER is
    # always generated — it decides the swipe and generic press photos were the
    # weak point. Inner slides: real article image wins, generated fills gaps.
    # Budget guard in genimg caps spend, vision QA fails closed, article
    # imagery is the floor.
    gen = 0
    pool = []  # every rejected COVER candidate as (score, path) — best-of floor
    for i, s in enumerate(post["slides"]):
        brief = s.pop("image_brief", "").strip()
        if s["type"] == "cta" or not brief or gen >= 3:
            continue
        if s.get("media") and s["type"] != "cover":
            continue
        # cover ladder (owner rules Jul 29: capped attempts — each image costs
        # money — the brief rewritten around the judge's named flaw between
        # attempts, and the post NEVER ships imageless: if nothing passes, the
        # best-scoring reject wins). Inner slides keep one shot; genimg's
        # budget guard caps total spend either way.
        tries = 3 if s["type"] == "cover" else 1
        for attempt in range(tries):
            path = genimg.generate(brief, os.path.join(post_dir, f"gen-{i}{'-r' * attempt}.jpg"))
            if not path:  # budget out / API down — retrying can't help
                break
            ok, score, flaw = image_score(path, s.get("headline")
                                          or (s.get("body") or "")[:90],
                                          generated=True)
            if ok:
                s["media"] = os.path.relpath(path, HERE)
                gen += 1
                if s["type"] == "cover":
                    post["cover_style"] = "photo"  # a generated cover is a photo cover
                break
            print(f"slide {i+1} image rejected (attempt {attempt+1}/{tries}, "
                  f"score {score}/10): {flaw}", file=sys.stderr)
            if s["type"] == "cover":
                pool.append((score, path))
            if attempt + 1 < tries:
                brief = simpler_brief(brief, s.get("headline")
                                      or (s.get("body") or "")[:90], flaw) or brief
    if gen:
        print(f"{gen} Seedream image(s) generated", file=sys.stderr)

    # cover ladder, last rungs (owner rule Jul 29: "we can never post without
    # an image"): unused article images join the scored pool; if nothing
    # passed outright, the BEST-SCORING candidate ships — flagged in
    # post.json so the daily report names it for owner review. A bare type
    # cover is legal only when zero images exist at all.
    cover0 = post["slides"][0]
    if not cover0.get("media") and post.get("cover_style") != "logos":
        for mi, m in enumerate(media_files, 1):
            if mi in used:
                continue
            ok, score, flaw = image_score(m, cover0["headline"])
            if ok:
                cover0["media"] = os.path.relpath(m, HERE)
                post["cover_style"] = "photo"
                print(f"cover fell back to article image {os.path.basename(m)}",
                      file=sys.stderr)
                break
            pool.append((score, m))
        if not cover0.get("media") and pool:
            score, best = max(pool, key=lambda t: t[0])
            cover0["media"] = os.path.relpath(best, HERE)
            post["cover_style"] = "photo"
            post["cover_fallback"] = f"best-of-rejected ({score}/10)"
            print(f"COVER: nothing passed QA — shipping the best reject "
                  f"({os.path.basename(best)}, score {score}/10; flagged for "
                  "the daily report)", file=sys.stderr)
        elif not cover0.get("media"):
            post["cover_fallback"] = "no-image"
            print("COVER HAS NO IMAGE AT ALL — generation returned nothing "
                  "(budget/API) and the article had no images; shipping a "
                  "type cover (flagged for the daily report)", file=sys.stderr)

    # every slide pictured, zero-budget version (owner Aug 1: "every post,
    # carousel or page should have a picture" — but caps stay at $9/mo until
    # the page grows): leftover REAL article photos fill still-bare content
    # slides, gated by the same vision QA so junk never ships. A real photo
    # beats the blurred-cover texture the renderer falls back to.
    assigned = {s.get("media") for s in post["slides"] if s.get("media")}
    leftovers = [m for m in media_files
                 if os.path.relpath(m, HERE) not in assigned]
    for s in post["slides"]:
        if s["type"] != "content" or s.get("media") or not leftovers:
            continue
        claim = s.get("headline") or (s.get("body") or "")[:90]  # card slides have no headline
        for m in list(leftovers):
            try:
                ok, score, flaw = image_score(m, claim)
            except Exception:
                break  # vision QA down — keep the texture fallback
            if ok:
                s["media"] = os.path.relpath(m, HERE)
                leftovers.remove(m)
                print(f"bare slide filled with article image "
                      f"{os.path.basename(m)} ({score}/10)", file=sys.stderr)
                break

    cover = post["slides"][0]
    style = post.pop("cover_style", "photo" if cover.get("media") else "type")
    if style != "photo":
        cover["media"] = None  # logos/type cover: no photo band
    valid = [l for l in post.pop("logos", [])
             if os.path.exists(os.path.join(HERE, "logos", f"{l}.svg"))]
    if valid and (style == "logos" or cover.get("media")):
        cover["logos"] = valid[:1] if cover.get("media") else valid
    badge = post.pop("badge_logo", None)
    if badge and cover.get("media") and os.path.exists(
            os.path.join(HERE, "logos", f"{badge}.svg")):
        cover["badge_logo"] = badge  # circular brand chip on the cover photo

    # composed cover (owner gold standard Aug 1, @getintoai anatomy): cut the
    # famous person out of the REAL press photo; renderer stacks backdrop <
    # discs < person. Never on generated images (unfamiliar-faces rule) —
    # every failure falls back to the plain photo cover, a slot never dies.
    discs = [d for d in (cover.get("discs") or [])
             if (d.get("logo") and os.path.exists(
                     os.path.join(HERE, "logos", f'{d["logo"]}.svg')))
             or (d.get("text") and len(d["text"]) <= 12)]
    cover.pop("discs", None)
    if discs and cover.get("media") and \
            not os.path.basename(cover["media"]).startswith("gen"):
        import composite
        cut = composite.cutout(os.path.join(HERE, cover["media"]),
                               os.path.join(post_dir, "cutout.png"))
        if cut:
            cover["cutout"] = os.path.relpath(cut, HERE)
            cover["discs"] = discs
            cover.pop("logos", None)  # discs replace the flat logo overlay
            print("composed cover: cutout + "
                  + ", ".join(d.get("logo") or f'"{d["text"]}"' for d in discs),
                  file=sys.stderr)
    post.pop("subline", None)  # dead field (owner Aug 1): covers render headline + swipe strip only
    post.update(handle="@yaffeai",
                container=post.pop("container", "daily_item"),
                story={"title": story["title"], "link": story["link"],
                       # judge-calibration loop (learn.py): prediction vs reality
                       "judge_interest": story.get("interest"),
                       "scout_score": story.get("score")})

    scrub_dashes(post)  # hard gate: no dash survives, whatever the model wrote
    json.dump(post, open(os.path.join(post_dir, "post.json"), "w"), indent=1)
    subprocess.run([sys.executable, os.path.join(HERE, "render.py"),
                    os.path.join(post_dir, "post.json"), post_dir], check=True)
    print("post ready:", post_dir)
    return post_dir


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "stories.json"))
