#!/usr/bin/env python3
"""Writer agent: turns the top story in stories.json into a daily_item post.
Usage: python3 write.py [stories.json]
Picks the best direct-link story (prefers one with a press image), fetches the
article text, asks Claude for the post JSON (daily_item container spec), runs
the QA gate, then renders slides into posts/<date>-<slug>/.
Uses the anthropic SDK if ANTHROPIC_API_KEY is set, else falls back to
`claude -p` (Claude Code CLI) so it's testable with zero keys."""
import json, os, re, subprocess, sys, time
from datetime import date

from fetch import get  # same dir; shared HTTP helper with UA
import genimg
import viral  # the packaging agent: classify -> per-type hooks -> blind judge

HERE = os.path.dirname(os.path.abspath(__file__))
# TOKEN DIET (owner order Aug 8, overrides the Jul 27 "Opus, cost is fine"
# call): the IG system ate ~15% of the WEEKLY Claude plan in one day and
# "You've hit your weekly limit" killed the Aug 7 slots. Writers run Sonnet
# (top-tier writer, ~5x cheaper on the plan); judges/vision-QA/gates run
# Haiku (~25x cheaper). ZERO Opus anywhere — PERMANENT (owner re-ordered
# Aug 8: "make sure now the token plan cost is permanent and always").
# call_claude() hard-rejects any Opus model at runtime; a quality-driven
# flip back is owner-only and means deliberately removing that gate too.
MODEL = "claude-sonnet-4-6"
CHEAP = "claude-haiku-4-5-20251001"

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
                    "kicker": {"type": "string"},
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
                    "face": {"type": "string"},
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
            schema=SHOT_QA_SCHEMA, images=[png], model=CHEAP)
        if r.get("usable"):
            return png
        print("product screenshot rejected by vision QA", file=sys.stderr)
    except Exception as e:
        print(f"product screenshot failed ({e})", file=sys.stderr)
    return None


def brands():
    """Brand book: official colors + simple-icons fetch slugs (owner order
    Aug 4: right logo, right colors, for each company)."""
    try:
        b = json.load(open(os.path.join(HERE, "brands.json")))
        b.pop("_doc", None)
        return b
    except Exception:
        return {}


def _lum(hexcolor):
    try:
        h = hexcolor.lstrip("#")
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
        return 0.299 * r + 0.587 * g + 0.114 * b
    except Exception:
        return 255


def logo_svg(slug):
    """Local SVG for a brand, fetching the OFFICIAL mark from the
    simple-icons CDN on first use (official brand color baked into fill).
    Near-black marks are recolored WHITE at save time — they'd vanish in
    our dark scenes and on the dark cover discs. Fails soft to None."""
    svg = os.path.join(HERE, "logos", f"{slug}.svg")
    if os.path.exists(svg):
        return svg
    info = brands().get(slug)
    if not info or info.get("si", slug) is None:
        return None
    import urllib.request
    try:
        # CDN 403s python's default urllib UA — send a browser one
        req = urllib.request.Request(
            f"https://cdn.simpleicons.org/{info.get('si', slug)}",
            headers={"User-Agent": "Mozilla/5.0"})
        data = urllib.request.urlopen(req, timeout=20).read().decode()
        m = re.search(r'fill="(#[0-9a-fA-F]{6})"', data)
        if m and _lum(m.group(1)) < 60:
            data = data.replace(m.group(1), "#FFFFFF")
        open(svg, "w").write(data)
        return svg
    except Exception as e:
        print(f"logo fetch failed for {slug}: {e}", file=sys.stderr)
        return None


def logo_ref(slug):
    """Real logo SVG -> raster reference for the generator (owner Aug 1
    courtroom verdict: the model's from-memory 'pink OpenAI flower' reads
    instantly fake — the EXACT mark must ride along as a reference image,
    same doctrine as faces and products). Rendered on black in the brand's
    OFFICIAL color (owner Aug 4) — white for black-mark brands. Cached."""
    slug = slug.lower()
    svg = logo_svg(slug)
    if not svg:
        return None
    out = os.path.join(HERE, "logos", f"_ref-{slug}.png")
    if os.path.exists(out):
        return out
    chrome = os.environ.get("CHROME",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    html = os.path.join(HERE, "logos", f"_ref-{slug}.html")
    # inline the SVG recolored to the brand's true color (legacy local SVGs
    # are all-white fills; the ref must teach the generator the REAL color)
    body = open(svg).read()
    color = brands().get(slug, {}).get("color")
    if color and _lum(color) >= 60:
        body = re.sub(r'fill="#[0-9a-fA-F]{3,8}"', f'fill="{color}"', body)
    body = body.replace("<svg ", '<svg style="width:100%;height:auto" ', 1)
    open(html, "w").write(
        '<body style="margin:0;background:#000;display:flex;align-items:center;'
        'justify-content:center;width:1024px;height:1024px">'
        f'<div style="width:70%">{body}</div></body>')
    try:
        subprocess.run([chrome, "--headless", "--disable-gpu", "--hide-scrollbars",
                        "--window-size=1024,1024", f"--screenshot={out}",
                        f"file://{html}"], capture_output=True, timeout=60, check=True)
    except Exception as e:
        print(f"logo ref raster failed ({e})", file=sys.stderr)
        return None
    finally:
        os.unlink(html)
    return out if os.path.exists(out) and os.path.getsize(out) > 5000 else None


IMG_QA_SCHEMA = {"type": "object",
                 "properties": {"usable": {"type": "boolean"},
                                "score": {"type": "integer"},
                                "flaw": {"type": "string"}},
                 "required": ["usable", "score"]}


def image_score(path, headline, generated=False, person=False):
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
        'CAST TRUTH GATE (owner post-mortem Aug 10, the Sam Altman content-vendor cover): if the prominent face IS a recognizable famous person but that person has NO role in this exact headline\'s story — their company or product is not what the headline is about, they are decoration on a generic topic = usable:false, flaw "famous face unrelated to the story". EXCEPTION: on an inspirational or entrepreneurial claim, a famous founder shown in their KNOWN iconic moment that embodies the headline (young Zuckerberg coding in a dorm for a build-from-nothing promise) IS connected and passes. '
        'CLICK GATE (owner order Aug 3, GENERATED images only — a retry is cheap, wallpaper is not): the image alone must make a scroller feel they NEED to know what is happening — a caught moment, visible tension, peak emotion. A calm, posed, or neutral scene that raises no question = usable:false, flaw "no pull, nothing happening". '
        'BACKGROUND THUMB TEST (owner Aug 3, GENERATED images only): mentally cover the main subject with a thumb — the background alone should still hint what the story is about (its world, its stakes). A background that is an empty void, generic decoration, or a world that belongs to a DIFFERENT story than the headline = subtract points and name it as the flaw. '
        'REAL WORLD GATE (owner Aug 3, the Mario emoji-wall cover): the scene must be a plausible photographic world. A background built from floating emoji, cartoon icons, logos, or symbol wallpaper reads as cheap AI slop = usable:false, flaw "cartoon prop background". '
        if generated else "")
    try:
        r = call_claude(
            f'An AI-generated image is attached (if not attached to this message, use your Read tool on {path} to look at it). It would fill the photo band of an Instagram news slide with this headline: "{clean}". Judge it AT PHONE FEED SIZE — a flaw a follower cannot see at that size does not count against it. '
            'SCORE against the scroll-stopper formula (each worth points): ONE dominant focal subject, brightest and sharpest thing in frame (no competing focal points); the image dramatizes THIS exact headline claim — moment, stakes or consequence visible in half a second (not generic topical art), and a deliberately STAGED SYMBOLIC scene that transmits the story\'s outcome in one look (a funeral for a discontinued product, a knockout between two brands, a famous logo cast in the story\'s role) COUNTS as dramatizing the claim — judge it on whether a stranger gets the story, not on literalness;THE PULL — the image alone makes you need to know what is happening (a caught moment, visible tension, peak emotion beats any calm posed scene); bright saturated colors with one punchy accent (not murky, not pastel, not white-dominant); if a person is central, the face is large and radiates one clear strong emotion; looks like a real press photo (texture, grain, candid light), not plastic AI art. '
            + face_gate +
            'Score 0-10: 10 = a professional photo editor would run it AND it nails the formula; 7 = publishable; 4 = clearly flawed but recognizable and on-claim; 0 = unusable garbage. usable:true means publish as-is — set false for flaws a scrolling follower would actually notice: garbled text large enough to read, warped hands/faces, obvious AI plastic look, watermark, no connection to the claim, a dark/murky frame with no focal subject, or a SCREENSHOT of an app or social-media post (baked-in meme captions, interface elements like hearts, like counts, usernames, buttons — a screenshot is someone else\'s content and never our cover). flaw: the single biggest problem in 12 words or less (empty string if none). Return ONLY JSON: {{"usable": true/false, "score": 0-10, "flaw": "..."}}',
            # person covers are judged on the WRITER model (owner audit Aug 10):
            # Haiku cannot verify famous likenesses — it called a
            # reference-level Altman render "unfamiliar generated face", so the
            # $0.17 gpt cover shipped as best-reject. Sonnet IDs faces
            # reliably; person covers are <=3/day so the upgrade costs a few
            # vision calls, exactly where the image money is spent.
            schema=IMG_QA_SCHEMA, images=[path],
            model=MODEL if person else CHEAP)
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


def simpler_brief(brief, headline, flaw="", mode="simpler"):
    """Ladder rung between generation attempts (Circle K post-mortem: the old
    retry re-ran the SAME brief and failed the same way). Rewrites the
    rejected brief into a cleaner, harder-to-botch shot — fewer elements =
    fewer artifacts — steered by the judge's named flaw. Fails open to the
    original brief. mode="concept" (Aug 9, person-route covers): the staged
    concept and the named cast ARE the cover — keep the scene and every
    famous name, strip only the flaw's cause; never let the retry dissolve
    the funeral into a plain portrait."""
    clean = re.sub(r"</?em>", "", headline)
    flaw_line = f'The judge named the biggest flaw: "{flaw}". Remove its cause first.\n' if flaw else ""
    if mode == "concept":
        task = ('Rewrite the brief keeping the SAME staged scene and every '
                'named famous person EXACTLY as they are — the concept and the '
                'cast are the cover\'s whole value. Fix ONLY the named flaw: '
                'simplify the background, cut clutter or extra props, drop any '
                'readable text (symbols only), sharpen the one emotion. Never '
                'replace the scene with a plainer portrait or a generic setting. '
                'ONE EXCEPTION: if the flaw says the famous face is UNRELATED '
                'to the story, the cast IS the flaw — rebuild the same staged '
                'scene around the story\'s real actor, its famous logo, or '
                'faceless humans, and name no unrelated celebrity.')
    else:
        task = ('Rewrite the brief SIMPLER so the next attempt survives: ONE '
                'subject, ONE action, ZERO readable text anywhere (screens show '
                'SYMBOLS only: a $ symbol, a warning triangle, a red cross — '
                'symbols never garble), no crowds, no close-up hands or faces, '
                'plainer setting, keep the color key.')
    try:
        r = call_claude(
            f'An AI image generator produced an UNUSABLE image (artifacts, garbled text, or stock look) from this brief:\n"{brief}"\n{flaw_line}The image must still be evidence for this headline: "{clean}". {task} 15-35 words, subject first. Return ONLY JSON: {{"brief": "..."}}',
            schema=BRIEF_SCHEMA, model=CHEAP)
        b = r.get("brief", "").strip()
        if b:
            print(f"brief rewritten: {b[:90]}", file=sys.stderr)
        return b
    except Exception as e:
        print(f"brief rewrite failed ({e}) — retrying the original", file=sys.stderr)
        return ""


ART_SCHEMA = {"type": "object", "properties": {"briefs": {
    "type": "array", "items": {"type": "object", "properties": {
        "idx": {"type": "integer"}, "brief": {"type": "string"},
        "ref": {"type": "boolean"}, "face": {"type": "string"},
        "logo": {"type": "string"}},
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
              "concept": s.get("image_brief", ""),
              **({"slide_role": s["type"]} if s["type"] in ("cta", "cover") else {}),
              **({"has_real_photo": True} if s.get("media") else {})}
             for i, s in enumerate(post["slides"])
             if s.get("image_brief") or s["type"] == "cta"]
    if not items:
        return
    has_product_photo = any(s.get("media") for s in post["slides"])
    ref_note = ('A real photo of the product is attached to the generator as a '
                'visual reference — say "the exact device from the reference '
                'image" in the brief and set "ref": true on it so the generated '
                'device matches reality.' if has_product_photo else
                "No real product photo exists — describe the product's exact "
                "look from the story instead.")
    cta_ref_note = ' and set "ref": true on it too' if has_product_photo else ""
    # (faces/ pool still feeds face_riders — the Seedream FALLBACK rung —
    # but the art director now writes names directly; premium model Aug 2)
    face_note = (
        "\nFAMOUS PEOPLE (switched Aug 2 to a premium model that KNOWS famous "
        "faces natively — measured: it nailed Musk, Buffett and Bezos in one "
        "frame from names alone): whenever a brief features a famous person, "
        "write their FULL NAME directly in the brief text (up to 3 people per "
        'scene) AND return "face": "Name One, Name Two" listing the same '
        "names — that field routes the brief to the person model. FAMOUS "
        "means a random 16-year-old would recognize the face (Musk, Altman, "
        "Zuckerberg, a sitting president); a researcher or VP nobody "
        "recognizes must NOT get a generated stand-in face (owner ban Aug 1: "
        'a fake "Aschenbrenner" shipped on the SA-fund cover and read '
        "instantly false) — show them from behind, silhouette, or rewrite to "
        "the story's objects/scene with no face in frame."
        "\nNO GENERIC PEOPLE (hard rule Aug 9 — three cover-fallback days in "
        "a row: every image the judge killed as 'unfamiliar generated face' "
        "traced back to an unnamed person in the brief, and the slot shipped "
        "a bare or reject cover): a person may appear in a brief ONLY as a "
        "written famous full name per the rule above. Never write 'a worker', "
        "'an engineer', 'a student', 'a person at a desk' or any other "
        "unnamed human whose face would be visible. If the scene needs a "
        "human presence, design it people-free or face-free: hands-and-props "
        "close-ups, a figure from behind, a silhouette, or let the story's "
        "objects and screens carry the drama."
        '\nBREAK THE PATTERN (owner rule Aug 2 — "we must break the normal '
        'thoughts when users see the images... not necessarily gangsters, '
        'but change the thinking pattern and make it unique"): the viewer '
        "must see something they have never seen before, and the BEST source "
        "is the story itself. Priority order: (1) THE STORY'S OWN ABSURD "
        "VISUAL — the reference page's biggest covers photograph the story's "
        "real weirdness straight (two phones taped together for a no-network "
        "file transfer; a man watching a movie through a receipt printer; "
        "wedding guests arriving mid-collapse). If the material holds a "
        "scene like that, THAT is the image — never replace it with an "
        "invented one. (2) Only when the story has no inherent visual: "
        "invent an UNEXPECTED staging for the famous person — a place, "
        "outfit or role the viewer has never seen them in, still literally "
        "connected to the claim (three billionaires as 1970s gangsters "
        "splitting a briefcase of cash worked because the story WAS their "
        "money). Either way: a boardroom, an office desk, a stage keynote "
        "or a suit-at-a-table is a FAILURE unless the story's event "
        "literally happened there (a courtroom for a lawsuit). Ask: has the "
        "viewer seen this exact scene before? If yes, dig deeper.")
    # brand book (owner Aug 4): every fetchable brand, WITH its official
    # color, so briefs use the right mark AND the right color per company
    book = brands()
    local = {os.path.splitext(f)[0].lstrip("_") for f in
             os.listdir(os.path.join(HERE, "logos")) if f.endswith(".svg")}
    have = sorted(local | {s for s, i in book.items()
                           if i.get("si", s) is not None})
    logo_list = [f"{s} ({book[s]['color']})" if s in book else s
                 for s in have]
    logo_note = ((
        "\nLOGO REFERENCES (owner Aug 1: the model's from-memory logos come "
        "out wrong — a pink not-quite-OpenAI flower reads instantly fake): we "
        "hold the REAL vector logos, listed here with each brand's OFFICIAL "
        "color: " + ", ".join(logo_list) + '. Whenever '
        'a brief places one of these brands\' marks in the scene, return '
        '"logo": "<exact name from that list, without the color>" on that '
        'brief — the real mark rides to the generator as a reference — and '
        'write into the brief: "the company logo exactly as in the reference '
        'image". Never let the model draw a listed brand\'s logo from memory. '
        "BRAND COLOR TRUTH (owner Aug 4): when a scene lives in a company's "
        "world, the color key and the brand's props use that company's REAL "
        "color from the list — a Telegram story is keyed to Telegram sky "
        "blue #26A5E4, an Nvidia story to Nvidia green #76B900; never an "
        "invented palette. Black-mark brands (Apple, X, GitHub, SpaceX, "
        "OpenAI) appear as glowing WHITE marks in our dark scenes.")
        if logo_list else "")
    # CULTURE CAST feed (Aug 9 Creative Director port): zero extra calls here —
    # culture.get() reads the day's cached hot list (one Sonnet web-search call
    # per day, lazy 24h refresh, fails open inside culture.py)
    hot = []
    try:
        import culture
        hot = culture.get()[:10]
    except Exception:
        pass
    culture_note = (("\nWHO IS CULTURALLY HOT RIGHT NOW (refreshed from the "
                     "live web within 24h — feeds the CULTURE CAST lane):\n" +
                     "\n".join(f"- {h['name']}: {h.get('why_hot_now', '')} "
                               f"[{h.get('typical_scene', '')}]" for h in hot))
                    if hot else "")
    prompt = f"""{doctrine()}You are the cover-image director of a viral news Instagram page. You write the final image-generation prompts for the Seedream photo model. The doctrine below is distilled from published research on scroll-stopping feed imagery (thumbnail CTR studies: emotional faces +42%, image-headline synergy up to +154%; MrBeast-school single-focal analysis; 2026 anti-AI-slop guides) — follow it exactly. The image fills the top two-thirds of the frame above the headline and gets ~0.4 seconds at phone size.

STORY: {story_title}
SLIDES (index, final headline, the writer's rough concept):
{json.dumps(items, ensure_ascii=False, indent=1)}

THE JOB: the image DRAMATIZES the exact claim of that slide's headline — the peak moment, the consequence, or the stakes — so the image raises the question and the headline answers it. A stranger seeing image + headline together gets the claim in one second. Never the topic in general, never stock wallpaper. A metaphor is legal ONLY on the cover under the concept rules below — INNER slides stay literal evidence of their own claim.

THINK CONCEPT FIRST, PROMPT SECOND (owner doctrine Aug 9 — COVER ONLY): before writing the cover brief, name the story's emotional core in your head — who wins, who dies, who is humiliated, what era just ended — then stage that meaning as ONE scene a stranger decodes in one second without reading a word. The strongest lane wins (vary the lane across posts):
- SYMBOLIC SCENE: the story's meaning acted out as one theatrical, photographically REAL moment. A product replaced → its FUNERAL (owner's gold standard: Anthropic's CEO comforting a sobbing Bill Gates at PowerPoint's funeral, the PowerPoint logo framed on the coffin); a company beaten → the knockout over the ropes; an old era over → its retirement party. Staged, but shot as a documentary press photo — never illustration, never surrealism for its own sake.
- CULTURE CAST (the Zendaya move — owner reference: Zendaya cast studying for a Gemini-exam story BECAUSE The Odyssey was viral that week): cast someone from the hot list below performing the story's action. Only when the fit is instant and natural — never force a celebrity into a story that isn't theirs.{culture_note}
- LOGO AS HERO (fame-bar fallback, owner Aug 9): when the story's company is world-famous but NO person clears the famous-face bar, the famous LOGO itself becomes the staged scene's HERO, cast in the story's role — GitHub repos printing money → the golden Octocat on a throne of hundred-dollar stacks. Return "logo" so the real mark rides as reference; every human in that scene is faceless or absent.
- Or the existing lanes below (the story's own absurd visual, ROLE-CAST, PRODUCT-HERO, CLASH-CAST, THE SITUATION PORTRAIT) when they are stronger. All craft rules, the fame bar, and the logo rules still apply to every lane.
CAST TRUTH (owner post-mortem Aug 10, the Sam Altman content-vendor cover — a great Altman likeness on a "people are making a week of content" story he had NOTHING to do with): a named famous face is legal ONLY when that person or their company is an ACTOR in THIS story — named in the topic or headlines, or the story is about their product or their move. "The topic is AI" is NOT a connection: never cast a famous AI face (Altman, Musk, anyone) as decoration on a generic how-to / prompts / edu story that names no company. When only the TOOL is famous (ChatGPT, Claude, Gemini), the tool's LOGO AS HERO or an evidence-object scene with faceless humans carries the cover instead. CULTURE CAST is the one exception and only under its own rule: the fit must be instant and natural.
ICONIC-MOMENT EXCEPTION (owner, Aug 10): on inspirational / entrepreneurial stories, a famous founder IS legal even when the news isn't about them — IF the scene is their KNOWN iconic real moment and that moment EMBODIES the title's exact meaning: young Mark Zuckerberg coding in his dorm room for a "built it from nothing overnight" promise, garage-era Jobs and Wozniak for a two-people-and-an-idea story. The test: a stranger instantly reads WHY this person in THIS scene proves THIS title. A famous face merely signaling "AI" or "tech" still fails cast truth.
NO-FACE PLAYBOOK (owner order Aug 10 — cast truth is NOT a license for boring covers; a no-face cover goes just as big and provocative):
- LOGO AS HERO is the default: the famous mark ACTING the story at theatrical scale — the Octocat mascot raking in poker chips, a giant glowing logo craned onto (or torn off) a building, the mark painted on a boxing-ring floor under falling confetti. The logo performs the verb; it never just sits there.
- SYMBOLIC SCENE, FACELESS: the funeral / knockout / retirement party staged with faceless humans — mourners from behind, silhouettes, hands lowering the coffin. The staging and props carry the drama, no likeness needed.
- IMPOSSIBLE SCALE: the story's real object at absurd physical size in a real place — a server rack towering over a city intersection, a mountain of cash burying an office desk, a phone the size of a billboard being hauled by crane.
- CAUGHT EVIDENCE: the forbidden backstage moment with objects only — a contract mid-signature shot over a faceless shoulder, a vault door ajar with the goods glowing inside, a wall of screens mid-crash in an empty room.
Every no-face cover still passes THE STOP TEST; "objects" NEVER means a calm product shot — if the object isn't mid-action or at impossible scale, escalate the scene.

THE STOP TEST (owner order Aug 3: every cover must be "controversial / eye-opening and make people want to click"): the cover scene must feel like a moment the viewer SHOULDN'T be seeing — caught, not posed. It passes only if it holds at least one of: (a) visible conflict or confrontation mid-happening, (b) one famous face at a PEAK raw emotion no press photo would ever show (devastation, fury, panic — not a composed press smile), (c) something mid-going-wrong (mid-fall, mid-crash, mid-escape), (d) an impossible-but-real sight that makes the viewer doubt their eyes, or (e) a forbidden/backstage moment (a leaked-memo table, a deal being signed behind closed doors). A scene that is merely unusual staging is NOT enough — ask "would a stranger feel they need to know what's happening here?" If the honest answer is no, escalate the moment. Everything else stays true: the scene dramatizes THIS story's real claim, never a fabricated event presented as news.

THE HOOK-IMAGE CONTRACT (forensic audit of the reference pages, Aug 2 — the hook-image connection is their #1 craft; every rule below is measured from their covers):
- DIVISION OF LABOR: the image shows what words cannot (what the thing or person actually LOOKS like — proof the noun is real); the headline says what the image cannot (the price, the count, the consequence). The image never restates the headline's numbers — it proves the headline's NOUN. Exception: when the number counts a small visible object (2 phones, 3 jets, a 4-phone color lineup), show exactly that count.
- DEIXIS LOCK: when the headline points — "THIS GUY...", "THESE ARE THE...", "THIS IS HOW..." — the image IS the missing half of the sentence: it must show exactly the pointed-at person or thing, dominant in frame, or the cover reads broken.
- HANDS DO THE VERB: the hero's hands and gesture perform the headline's verb — holding the launched product to camera, shushing for a secret, signing for a deal, taping the two phones together. A person merely standing near the topic is wallpaper.

ROLE-CAST (owner's gold standard, Aug 1): when the claim is about what a product or company CAN DO, cast the story's famous face IN THE ROLE the claim describes, mid-performance with that role's real props. Reference: "Claude has an unlimited personal tutor mode" → Anthropic's CEO AS the tutor — leaning over a desk in a warm home library, pen in hand, teaching a student whose shoulder frames the foreground. The person doesn't react to the claim, they ACT IT OUT; the scene props (pen, notebook, bookshelves) and the story-world background make the metaphor literal. Prefer this over a reaction face whenever the story has a doer + a capability.

PRODUCT-HERO (owner's gold standard, Aug 1 — the @technology Codex Micro reference; MANDATORY for the COVER whenever the story is a famous company's physical product or gadget): the company's famous CEO (full name in the brief text AND in "face" — see the famous-people rule) HOLDS the product chest-high toward the camera with both hands, chest-up, eyes to camera, and the company's logo glows on the dark wall behind them as a large neon sign (describe the logo's shape: "the glowing OpenAI flower-knot logo in warm white neon"). {ref_note} The person presents, the logo brands, the device IS the story — all three connected. ALSO write a brief for the final CTA slide (marked slide_role "cta") in this case: the same named CEO with the same device, a clearly DIFFERENT pose and angle than the cover (e.g. holding it up in one hand, three-quarter view, a different room of the same story-world){cta_ref_note}.

THE CTA CLOSER (owner doctrine Aug 1, the reference page's last slide: Tim Cook holding a phone after an Apple story — the story's OWN person is the one saying "follow us"): for EVERY story whose main actor is famous, write a brief for the cta slide — that person chest-up, relaxed and confident, eyes to camera, warm inviting energy (never tense, never mid-crisis — the drama is over, this is the goodbye), the story's world softened behind them, their company's logo glowing on the wall, a story prop in hand if one exists. Different pose and setting than every other slide. Return "face" (and "logo" when listed) on it. Only when the story has NO famous person return no cta brief.

CLASH-CAST (owner's gold standard, Aug 1): when the story is a clash or a deal between TWO named famous people — a buyer and a seller, a winner and a loser, a hunter and the hunted — put BOTH recognizable likenesses in ONE composed scene that acts out the power dynamic: the winner looming calm and in command, the loser cornered mid-loss, faces large and close together, one clearly dominant. The story's world rages behind them (a trading floor of crashing red chart lines, a courtroom, a launchpad). Reference: the $45B fire-sale story → the young founder slumped at the deal table while the older billionaire stands over him signing, walls of red crashing charts behind. The pair reads as ONE unit; this beats a lone reaction face whenever the story has two famous sides. Write BOTH full names directly in the brief text AND return them comma-separated in "face" (that field routes to the person model — see the famous-people rule below). If a side is not famous enough to recognize, that person appears FACELESS (from behind, silhouette, or hands only), and if neither side is famous, drop CLASH-CAST entirely and dramatize with objects and stakes instead.

THE SITUATION PORTRAIT (owner order Aug 3 — his exact formula, written after the $750B failure shipped a bare press-photo crop of Musk with two identical black logo discs on an empty blurred background; his verdict: "a picture of the SITUATION!!!!"): when the cover story is one famous person winning or losing something big, write the cover brief the way the owner writes it: "Elon Musk with a devastated look like he just lost $750 billion, red crashing stock charts covering the wall of screens behind him". Two halves, both mandatory: the FACE carries the story's emotion (devastated for a loss, triumphant for a win, 40%+ of frame), and the BACKGROUND makes the situation itself visible — crashing red charts for a wipeout, raining cash for a windfall, a cheering crowd for a victory. LOUD AND COLORFUL (owner Aug 3, after the $750B cover shipped its charts as near-black murk: "we need to make the background a lot more colorful... more dramatic"): write the background as BRIGHT, saturated and glowing — "a floor-to-ceiling wall of glowing screens ablaze with crashing red stock charts", not "dark screens behind him" — it fills every pixel behind the person with vivid story imagery. THE THUMB TEST (owner Aug 3: "if viewers watch it once they should be able to guess what it's about"): cover the person with your thumb — the background alone must still say what THIS story is about (a yacht story gets the marina of superyachts, a lawsuit the courtroom, a wipeout the wall of red charts); a background that could belong to any other story is the wrong background. A neutral portrait, an empty background, a blurred nothing, or a dim barely-there backdrop is a FAILED cover, no matter how good the likeness is. The renderer stamps brand discs in the upper corners afterward with the person layered OVER them, so keep the person's head centered and the corners clear — the scene itself must still tell the story without the discs.

{face_note}
{logo_note}

THE CLAIM BEATS THE TEMPLATE (owner's verdict Aug 1, the courtroom cover): PRODUCT-HERO stages a presentation — but when the winning cover headline claims an EVENT (sued, banned, fired, crashed, copied, leaked, banned), the cover stages THAT EVENT as a literal scene instead, with the named famous person inside it and the product as a prop. Reference: "OPENAI COPIED THE COMPANY SUING THEM" → Sam Altman in a dark suit at the defendant's table of a US courtroom, tense, the white keypad and its white box on the table before him, the OpenAI logo on the courtroom evidence screen behind, American flag at the edge. Think like the viewer: the picture must make them say "that is exactly what the headline says" — person, event-world, product and brand all connected in one intuitive frame.

FORMAT — every prompt contains these five parts in order (20-45 words total):
1. HERO: ONE focal subject, concretely named (the real device/brand/person from the headline — or the CLASH-CAST pair as one unit), frozen at the peak of the exact moment — mid-fall, mid-launch, mid-signature. One focal point only; it is the brightest, sharpest thing in frame.
2. EMOTION — when the story's person is FAMOUS, the hero IS that person's recognizable likeness at 40%+ of frame height, named explicitly, eyes to camera or locked on the story's object, radiating ONE nameable exaggerated emotion (shock, awe, dread, triumph). Name the emotion in the prompt. FAMOUS FACES ONLY (owner rule Aug 1: generated unfamiliar faces = low conversion, no good outcome): if the story's person is not famous enough for a viewer to recognize, NEVER generate a face — show them from behind, as a silhouette, hands-and-props only, or cut them out of frame entirely and let the objects and stakes carry the drama.
3. STAKES IN FRAME: make the money/scale/damage physically visible — the pile of cash, the wreckage, the crowd, the giant object beside a person for scale. Stakes a viewer can read in half a second.
4. WORLD: the background is the story's real world (the factory floor, the launchpad, the brand's storefront) carrying context — softer, darker and simpler than the hero. Never an empty void, never white.
5. ACCENT: end with ONE saturated accent color pulled from the subject, set against a darker complementary surround ("accent: signal red against deep blue dusk"). Warm saturated accents stop scrolls; whole-frame murk and pastels do not.

CRAFT (bake into every prompt):
- Real press photograph, never digital art: include "documentary news photo, 35mm, harsh on-camera flash, natural skin texture, slight film grain". This is the #1 lever that keeps generated images from looking like cheap AI.
- ZERO readable words anywhere in frame (measured on our own runs: the model garbles every rendered sentence — 5 of 6 images died to this one flaw). Screens, signs and papers speak in SYMBOLS ONLY, named concretely: "a giant red $ symbol", "a warning triangle", "a crashing red chart line".
- GAZE IS AN ARROW (Netflix artwork research + fixation studies): the hero's eyes go to camera by default, or lock onto the story's object so the viewer's eye follows. MAX 2 people visible in frame — engagement measurably drops at 3+.
- THE BRAND LIVES IN THE SCENE: when the story's company matters to the frame, its real logo appears as a physical object — the default treatment (owner's reference, Aug 1): a LARGE GLOWING backlit mark on the dark wall behind the hero, soft warm-white halo, dimensional like a lit acrylic sign. Alternatives: the mark ON the device, a storefront sign, an illuminated screen with visible glow. NEVER a flat printed graphic, never drawn from memory — return "logo" so the real mark rides as a reference. The renderer will NOT stamp a flat logo overlay on generated covers, so if the brand isn't in the scene it isn't on the cover.
- EVERY IMAGE UNIQUE + A CURIOSITY ENGINE (owner Aug 1): no two slides in the post may share a composition, angle, or setting — each image is its own scene. IMAGE-CLAIM LOCK (the Reddit post-mortem: slide 2 claimed a 23% stock crash yet showed the same phone-with-logo as the cover): each inner brief's HERO is that slide's OWN claim — the crash slide gets the collapsing red chart line, the payout slide the money, the fallout slide the next victim — never the story's mascot object repeated. And each image is built on viewer psychology: it shows a moment that RAISES a question only the headline (or the next slide) answers — an unresolved instant, a reaction to something just out of frame, stakes mid-collapse. If an image would feel complete without its headline, it's wallpaper — rewrite it.
- KEEP THE HERO PRODUCT CLEAR OF THE BOTTOM THIRD: the headline band covers the bottom ~35% — a device held "chest-high" must sit in the MIDDLE of the frame (say "at chest height, centered in the middle of the frame"), or it gets cropped by the text.
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
                if b.get("ref"):  # product-hero: real product photo goes to the
                    post["slides"][i]["gen_ref"] = True  # generator as reference
                if b.get("face", "").strip():  # real press photo = identity ref
                    post["slides"][i]["gen_face"] = b["face"].strip()
                if b.get("logo", "").strip():  # real vector mark = logo ref
                    post["slides"][i]["gen_logo"] = b["logo"].strip().lower()
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
Return ONLY JSON: {{"dupe": true or false}}""", schema=DUPE_SCHEMA, model=CHEAP)
        return bool(r.get("dupe"))
    except Exception as e:
        print(f"dupe judge failed ({e}) — allowing story", file=sys.stderr)
        return False


def pick_story(stories):
    """MOST VIRAL WINS (owner token-diet order Aug 8): stories.json arrives
    already score-sorted by scout — real X like counts re-ranked by the
    interest judge. The old Claude ranking tournament (_rank, one fat Opus
    call per pick) is DELETED: 'most viral of the day' is a sort, not a
    judgment. Dupe check + editor Gate A still stand between the top story
    and the slot."""
    direct = [s for s in stories if "news.google.com" not in s["link"]]
    fresh = [s for s in direct if not already_posted(slugify(s["title"]))]
    # interest ladder (Aug 3 Queen post-mortem): low-interest stories stay in
    # the pool (always-post) but only get a turn after every interest>=5
    # candidate is exhausted.
    fresh = ([s for s in fresh if s.get("interest", 5) >= 5]
             + [s for s in fresh if s.get("interest", 5) < 5])
    recent = recent_posts()
    # exhaust EVERY candidate before declaring the slot dead (owner rule:
    # every slot must fill — a 3-try cap killed the Jul 28 test run when the
    # top 3 were all dupes while story #4 was fine)
    while fresh:
        s = fresh[0]  # most viral candidate standing
        if is_dupe(s["title"], recent):
            print(f"semantic dupe of a published post — skipping: {s['title']}",
                  file=sys.stderr)
            fresh = [x for x in fresh if x is not s]
            continue
        # GATE A — editor-in-chief (owner order Aug 4, Queen/Mario post-mortem):
        # the ranker only answers "best of this pool"; the editor owns "worth
        # posting at ALL" against doctrine.md. KILL is binding — the next
        # candidate competes, the slot never dies (always-post intact).
        import editor
        ok, _ = editor.gate_a(s, (s.get("radar") or {}).get("selftext", ""))
        if ok:
            return s
        fresh = [x for x in fresh if x is not s]
    return None


def doctrine():
    """THE LAW (ig/doctrine.md, owner order Aug 4): the single definition of a
    winning post, injected into EVERY pipeline Claude call — judge, picker,
    writer, tournament, art director, image judge, QA, editor. Rules scattered
    across ten private prompts is how the Queen/Mario disasters shipped; one
    file binding everyone is the fix. It self-declares that it outranks
    everything else in any prompt it appears in."""
    p = os.path.join(HERE, "doctrine.md")
    if not os.path.exists(p):
        return ""
    return open(p).read() + "\n\n----\n\n"


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
        for k in ("headline", "body", "kicker"):
            if s.get(k):
                s[k] = no_dashes(s[k])
    if post.get("caption"):
        post["caption"] = no_dashes(post["caption"])
    if post.get("pinned_comment"):
        post["pinned_comment"] = no_dashes(post["pinned_comment"])
    return post


LOOKUP_SCHEMA = {"type": "object", "properties": {
    "look_up": {"type": "boolean"}, "why": {"type": "string"}},
    "required": ["look_up", "why"]}


PREP_SCHEMA = {"type": "object", "properties": {
    "retell": {"type": "string"},
    "facts": {"type": "array", "items": {"type": "string"}},
    "spine": {"type": "object", "properties": {
        "irony": {"type": "string"}, "belief": {"type": "string"},
        "event": {"type": "string"}, "twist": {"type": "string"},
        "fallout": {"type": "string"}, "protagonist": {"type": "string"},
        "dinner_detail": {"type": "string"}},
        "required": ["irony", "belief", "event", "twist", "fallout",
                     "protagonist", "dinner_detail"]},
    "story_type": {"type": "string",
                   "enum": ["corporate_move", "absurd_moment", "threat",
                            "money_win", "record"]},
    "actor": {"type": "string"},
    "actor_known": {"type": "boolean"},
    "anchor": {"type": "string"},
    "specifics": {"type": "array", "items": {"type": "string"}}},
    "required": ["retell", "facts", "spine", "story_type"]}


def prep_story(story, body_text):
    """ONE story-prep call (token diet, owner order Aug 8): merges the old
    retell_story + story_spine + viral.classify — three fat sequential calls
    that all read the SAME material — into a single call. Each part keeps its
    craft doctrine: the 19-year-old retell (owner Jul 28 anti-news-speak),
    the narrative spine (owner Aug 1 arc directive), and the packaging
    classification (Circle K post-mortem). The look-up gate still judges the
    retell on Haiku with one harder-angle retry. Fails open per part:
    (None, None, default_ctx) keeps every old fallback path alive."""
    src = body_text or story["title"]
    base = f"""Here is a news story.
Title: {story['title']}
Article: {src[:6000]}

Do THREE jobs on this one story. Return a single JSON object.

JOB 1 — RETELL. You are 19. You just read this. Your friend sits across the table, scrolling their phone. You have 10 seconds to make them look up.
- "retell": the story in 2-3 sentences EXACTLY as you'd SAY it out loud. Lead with the consequence for a normal person — their money, their phone, their job, their feed — never with the announcement. No word a 16-year-old wouldn't use out loud. No company-speak ("announced", "unveiled", "platform", "capabilities").
- "facts": every name, number, quote, date, and concrete detail from the article worth using later, as short bullets — the accuracy net. Only things actually in the article.

JOB 2 — SPINE. You are a story editor for a viral page. Extract the NARRATIVE SPINE. Hunt hardest for the IRONY — the one TRUE fact that makes the story poetic, absurd, or cruel (usually buried mid-article, almost never in the headline). Return in "spine":
- "irony": the single most ironic/absurd TRUE line, one sentence — empty string ONLY if the story truly has none
- "belief": what everyone believed the morning before this happened, one sentence
- "event": what actually happened, at human scale (a person's money, job, screen — never index points or corporate abstractions), 1-2 sentences
- "twist": the 'wait, WHAT?' fact — the beat that re-hooks a tired reader, one sentence
- "fallout": who gets hit next / what changes now, one sentence
- "protagonist": IF one human being drives this story: their name plus the one identity fact that makes them a character (age, 'ex-OpenAI', 'college dropout') — else empty string. A company is never a protagonist
- "dinner_detail": the one human SCENE a person would retell at dinner tonight — a moment, never a statistic; empty string only if the story truly has none
Every spine field built ONLY from facts in the material — never invented.

JOB 3 — CLASSIFY for Instagram packaging:
{viral.TYPES}
- "story_type": the ONE type whose drama is the real reason people share this
- "actor": the named actor of the story (company/person/thing)
- "actor_known": would a random 16-year-old ANYWHERE instantly recognize this name? Be harsh. Apple/Tesla/ChatGPT/Visa/MrBeast yes; Circle K/Figure/Suno/Anthropic no.
- "anchor": what the hook should anchor on. If actor_known, the actor. If not, the most universal TRUE noun in the story (the machine, the AI, "a self-checkout", the famous counterparty, "your bank"). Never an unknown brand.
- "specifics": the 3-5 most shareable TRUE concrete details, most insane first (exact numbers, names, quotes) — the hook's raw ammunition.

Return ONLY JSON: {{"retell": "...", "facts": ["..."], "spine": {{...}}, "story_type": "...", "actor": "...", "actor_known": true/false, "anchor": "...", "specifics": ["..."]}}"""
    default_ctx = {"story_type": "corporate_move", "actor": "",
                   "actor_known": True, "anchor": "", "specifics": []}
    try:
        r = call_claude(base, schema=PREP_SCHEMA)
        g = call_claude(f"""Your friend at the table looks up from their phone and says this to you, out of nowhere:
"{r['retell']}"
Are you genuinely hooked — do you say "wait, what?" and want the rest? Answer honestly; most news retellings fail this. Return ONLY JSON: {{"look_up": true or false, "why": "one blunt sentence"}}""",
                       schema=LOOKUP_SCHEMA, model=CHEAP)
        if not g.get("look_up"):
            print(f"boring retell ({g.get('why', '?')}) — hunting a harder angle",
                  file=sys.stderr)
            r2 = call_claude(base + f"""

YOUR FIRST TRY FAILED — a listener said: "{g.get('why', 'boring')}". Find a different angle: the money, the fear, or the absurdity in this story. Say the single most shocking consequence FIRST, as a claim about the listener's own life if you honestly can.""",
                             schema=PREP_SCHEMA)
            r = r2 or r
        retold = {"retell": r["retell"], "facts": r.get("facts", [])}
        spine = r.get("spine") or None
        ctx = {k: r.get(k, d) for k, d in default_ctx.items()}
        if ctx["story_type"] not in viral.PLAYBOOK:
            ctx = default_ctx
        return retold, spine, ctx
    except Exception as e:
        print(f"story prep failed ({e}) — falling back to article text",
              file=sys.stderr)
        return None, None, default_ctx


def pick_face(face):
    """Faces pool with photo rotation (owner Aug 1: recurring people are fine,
    the same PICTURE repeating is not). Each person has 1-3 stored press
    photos (faces/<id>.jpg, <id>-2.jpg, ...); the least-recently-used one
    wins, ledgered in faces-used.json so runs never repeat back-to-back."""
    import glob
    cands = sorted(glob.glob(os.path.join(HERE, "faces", f"{face}*.jpg")))
    if not cands:
        return None
    ledger = os.path.join(HERE, "faces-used.json")
    try:
        used = json.load(open(ledger))
    except Exception:
        used = {}
    pick = min(cands, key=lambda c: used.get(os.path.basename(c), ""))
    used[os.path.basename(pick)] = date.today().isoformat()
    json.dump(used, open(ledger, "w"), indent=1)
    return os.path.relpath(pick, HERE)


def split_faces(field):
    """gen_face may carry several people ("Elon Musk, Warren Buffett and Jeff
    Bezos" for a group cover) — split into individual names."""
    return [n.strip() for n in re.split(r",|&|/|\+|\band\b", field) if n.strip()]


def face_riders(brief, face_field):
    """-> (safe_brief, face_ref_paths). E005 doctrine (measured Aug 2, the
    bare billionaire-cover post-mortem): Seedream flags ANY real person's
    name in the prompt as sensitive and fails the whole prediction — named
    alone, named WITH a reference photo, one person or three, always E005.
    The same brief with the name replaced by "the person in the reference
    photo" + the real press photo riding as a ref generates fine with perfect
    likeness. So: identity lives in the reference photo, NEVER in the prompt
    text. This also auto-attaches refs for pool people the art director named
    in the text without returning a "face" field."""
    import glob
    refs, ref_names, loose = [], [], []
    for nm in split_faces(face_field or ""):
        fp = pick_face(nm.lower().replace(" ", "-"))
        if fp:
            refs.append(os.path.join(HERE, fp))
            ref_names.append(nm)
        else:
            loose.append(nm)  # no photo held — name must STILL leave the brief
    pool = sorted({re.sub(r"-\d+$", "", os.path.splitext(os.path.basename(p))[0])
                   for p in glob.glob(os.path.join(HERE, "faces", "*.jpg"))})
    for slug in pool:
        disp = slug.replace("-", " ").title()
        if disp.lower() in [n.lower() for n in ref_names + loose]:
            continue
        if len(refs) < 3 and re.search(rf"\b{re.escape(disp)}\b", brief, re.I):
            fp = pick_face(slug)
            if fp:
                refs.append(os.path.join(HERE, fp))
                ref_names.append(disp)
    for i, n in enumerate(ref_names):
        who = ("the person in the reference photo" if len(ref_names) == 1
               else f"person {i + 1} in the reference photos")
        brief = re.sub(rf"\b{re.escape(n)}\b", who, brief, flags=re.I)
        sur = n.split()[-1]
        if len(sur) > 3:  # skip risky short/common surnames (Cook...)
            brief = re.sub(rf"\b{re.escape(sur)}\b", who, brief, flags=re.I)
    for n in loose:
        brief = re.sub(rf"\b{re.escape(n)}\b", "a person", brief, flags=re.I)
        sur = n.split()[-1]
        if len(sur) > 3:
            brief = re.sub(rf"\b{re.escape(sur)}\b", "a person", brief, flags=re.I)
    return brief, refs


def build_prompt(story, body_text, media_files, retold=None, steer="", spine=None):
    spec = json.load(open(os.path.join(HERE, "containers.json")))
    logos = sorted(f[:-4] for f in os.listdir(os.path.join(HERE, "logos"))
                   if f.endswith(".svg"))
    faces_dir = os.path.join(HERE, "faces")
    face_list = ", ".join(sorted(
        f[:-4] for f in os.listdir(faces_dir) if f.endswith(".jpg")
    )) if os.path.isdir(faces_dir) else ""
    if media_files:
        names = ", ".join(os.path.basename(m) for m in media_files)
        img_block = f"""{len(media_files)} candidate images from the article are ATTACHED, in order (image 1 = {os.path.basename(media_files[0])}, ...): {names}. If no images are attached to this message, use your Read tool to look at these files in {os.path.dirname(media_files[0])} before writing.
IMAGE ASSIGNMENT — every slide may set "media_idx": N (1-based, matching that order); omit it for no image:
- LOOK at each candidate first. Reject any that is stock-looking, blurry, watermarked, a logo, or emotionally flat — a bad image is worse than none.
- COVER: the most emotionally matching image — a human face or the product/scene in action. A face-only headshot is allowed only when the story IS about that person.
- INNER slides — IMAGE-CLAIM LOCK (owner audit Aug 1, the Reddit post-mortem: slide 2 claimed "stock crashed 23%" but showed ANOTHER phone-with-logo, nearly identical to the cover): the image must show THAT slide's exact claim, never the story's topic again — the crash slide shows the crash, the lawsuit slide the courtroom, the payout slide the money. If no candidate depicts the slide's claim, do NOT assign one — write an image_brief that does. An image whose subject or composition repeats the cover's image is banned.
- MEDIA ON EVERY SLIDE (owner audit Aug 1 — the reference carousels carry real media on ALL slides; our shipped text-only slides were the visible gap): every content slide must end with media_idx OR an image_brief. A real photo always beats a generated scene; a naked text slide is a broken slide.
- PERSON STORY (Situational-Awareness post-mortem Aug 1 — the reference page ran FOUR different real photos of the same man, one per story beat, while we showed his real face once and shipped two near-black slides): when the story has a protagonist, spread every DIFFERENT real photo of that person across the slides — podcast shot on the backstory slide, portrait on the bet slide — each matched to its beat. Same person, new photo each swipe.
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
    spine_block = ""
    if spine:
        spine_block = f"""
THE SPINE — the story's narrative skeleton, extracted by a story editor before you write. BUILD THE SLIDE CHAIN ON THESE BEATS, IN THIS ORDER — this is the difference between telling a story and listing statistics (they slot straight into the RETENTION DOCTRINE arc below):
- THE BELIEF (slide 2 territory — what everyone thought the morning before): {spine['belief']}
- THE EVENT, at human scale: {spine['event']}
- THE TWIST — gets its OWN slide, around slide 4, the "wait, WHAT?" beat: {spine['twist']}
- THE FALLOUT (the payoff slide): {spine['fallout']}"""
        if spine.get("irony", "").strip():
            spine_block += f"""
- THE IRONY (the buried gold — this goes ON a slide, in the twist or the stance; NEVER waste it on the pinned comment alone): {spine['irony']}"""
        if spine.get("dinner_detail", "").strip():
            spine_block += f"""
- THE DINNER DETAIL (owner doctrine Aug 1, the Situational-Awareness post-mortem — the giant reference page put the wedding in the HOOK and gave it a full cinematic slide; we buried it in half a clause and lost): {spine['dinner_detail']}
  This is the one moment people will retell tonight. It goes IN THE COVER HOOK (it beats any percentage) AND gets its OWN scene-slide written like a movie cross-cut ("HIS GUESTS WERE ARRIVING AS THE FUND WAS FALLING APART"). Burying it in a trailing clause is the failure mode."""
        if spine.get("protagonist", "").strip():
            spine_block += f"""
- THE PROTAGONIST (same post-mortem — people follow PEOPLE, not funds): {spine['protagonist']}
  PERSON-FIRST RULES: (1) the cover hook leads with the PERSON — identity fact + rise + fall ("THIS 24-YEAR-OLD BUILT A $45 BILLION AI FUND. THEN LOST 67% OF IT DURING HIS WEDDING" is the reference; "A $45 BILLION AI FUND COLLAPSED IN DAYS" — thing-first, hero unnamed — is the shipped failure). (2) For a rise-and-fall story the chain runs CHRONOLOGICALLY like a movie: who they are → the rise → the bet → the collapse SCENE (dinner detail) → the spiral → the takeaway. Backstory lives on slide 2-3, never parachuted in late. (3) Their real face should appear on most slides (image rules below)."""
    return f"""You write Instagram carousels for @yaffeai — a page covering AI, technology, space, business, investing, and money in the style of @technology, funneling followers to an AI-consulting business. Turn this story into a **daily_item** post.

STORY
Title: {story['title']}
Source: {story['link']}
{story_block}
{spine_block}
{proof}
COVER VISUAL
{img_block}
IMAGE BRIEFS (mandatory) — besides article images we have an AI image generator. EVERY cover and content slide must ALSO set "image_brief": 15-40 words, subject FIRST, then action, then setting (the generator needs that order). The image must be EVIDENCE of that slide's exact claim, frozen at the exact moment it happens — the test: could a lawyer submit it as an exhibit for the headline? (claim "touch screen" → a real hand physically touching the screen; claim "device lock" → the phone showing it; claim "books destroyed" → the blade mid-cut through the page stack). NEVER a generic person-at-laptop or "a robot" for a robot story. NAME real devices and brands ("a silver MacBook Pro", not "a laptop") — the generator renders them accurately. End the brief with ONE color key tied to the subject ("keyed to deep orange") — one bright saturated accent, never a dark or moody scene. Include a real human face when a person or a reaction is the story — one person, mid-action, face expressive and visible. HARD BAN (owner comparison Aug 1: our SA-fund cover showed a generated angry man standing in for Leopold Aschenbrenner — fake, and weaker than the real famous portrait the reference page used): NEVER generate a face to REPRESENT a real named person. A real person appears only via their real photo (article image or faces pool); if none exists, the brief shows the story's objects/scene with NO face standing in for them. Generated faces are allowed only for anonymous archetypes the story never names ("a trader", "a student"). The image may include AT MOST one short on-screen phrase, ONLY when that phrase IS the claim: write it in double quotes and say where it appears (a phone screen showing "Device Locked"); otherwise the scene has zero text — never signs, menus, or paragraphs, generators garble them. Slides that get a real article image keep it (real beats generated); the brief is the fallback for slides without one.
Pick "cover_style":
- "photo" — STRONGLY PREFERRED whenever the press photo exists AND passes the rule above. The photo fills the top ~60% of the cover; the headline sits on a solid black band below it (like the big news pages)
- "logos" — 1-2 company logos rendered big on the dark cover, only when there is no usable photo (X vs Y or company stories). Available logo names: {', '.join(logos)}. Only these names.
- "type" — big-headline-only dark cover (last resort)
"logos" array may ALSO be set together with "photo": the logo(s) are overlaid on top of the photo (one logo max in that case — pick the company the story is about). NEVER overlay a flat logo when the photo shows a person's face — it lands on top of them and looks amateur; for a famous person's photo use the COMPOSED COVER discs instead (below) and leave logos empty
THE KICKER (forensic upgrade Aug 2 — the reference pages use the tiny strip under the headline for a SECOND hook beat, not a generic swipe prompt: "WITHOUT SONY LIFTING A FINGER", "HE DOES NOT WANT THEIR MONEY", "BUILT WITH CLAUDE CODE, OPEN SOURCE", "5 SETTINGS TO SWITCH OFF"): the cover slide MAY set "kicker": 3-7 words, TRUE facts only, carrying the story's twist, consequence or bonus promise that is NOT already worded in the headline. It renders tiny in the strip — the headline must still work with the kicker covered. If the story has no real second beat, OMIT it (the strip then says "Swipe for more") — a filler kicker is worse than none. There is NO other subline (owner rule Aug 1): every word of the main hook lives in the big headline itself.

{doctrine()}
{principles()}
{inspiration()}
CONTAINER SPEC (daily_item): {json.dumps(spec['containers']['daily_item'])}
CONTAINER SPEC (builder_story): {json.dumps(spec['containers']['builder_story'])}
CAPTION BLOCKS: {json.dumps(spec['caption_blocks'])}
QA GATE: {json.dumps(spec['qa_gate'])}

Pick "container": "builder_story" ONLY if this story is about a tiny team / solo founder building something outsized with AI (follow its spec); otherwise "daily_item".
For builder_story: if the article names the product's own website, set top-level "product_url" to it and set "product_shot": true on the PROOF slide — the pipeline will screenshot the real page and put it on that slide (the honest proof artifact). Only one slide may set it.
For ANY story about a specific product or gadget (any container): set top-level "product_url" to the maker's official product page if the article names or links it — the pipeline pulls the OFFICIAL press photos from that page, and only the real product may ever be shown.

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
FELT SCALE (owner directive Aug 1 — "millions of users must understand and it must be fun to read"): every number gets translated into what a PERSON feels, never what an index did. The moves: absolute dollars ("$3 billion gone by lunch"), the reader's own stake ("$1,000 of Reddit stock on Monday was $770 by dinner"), a record ("its worst day ever"), a comparison a teenager knows ("more than a Superbowl ad every hour"). Finance-wire vocabulary is BANNED on slides — index names (S&P 500, Nasdaq, Dow), tickers (RDDT, $RDDT), "shares", "the market", "market cap", "trading session", "intraday", "closed up/down X%". A 16-year-old never says those words, so we never write them.
The model to copy (updated Aug 1 for summarizing covers — the Visa story done right):
  Cover: "VISA JUST LAID OFF 2,600 WORKERS <em>TO GO ALL IN ON A TECHNOLOGY MOST BANKS REFUSE TO TOUCH</em>" — the WHOLE story, reader swipes for the details
  Slide 2: "THE <em>2,600 JOBS</em> WERE CUT IN ONE MORNING" — the human scale of the move → reader thinks: why so brutal?
  Slide 3: "EVERY DOLLAR SAVED GOES INTO <em>AI</em>" — billions moved from salaries into one technology → reader thinks: isn't that risky?
  Slide 4: "MOST BANKS <em>REFUSE TO TOUCH IT</em>" — why the rest of the industry is scared → reader thinks: so what does Visa know?
  Slide 5: "HERE'S WHAT VISA KNOWS <em>THAT BANKS DON'T</em>" — the payoff
The cover summarizes; the inner slides go DEEPER than the cover ever could — the how, the why, the fallout, the picture. Every inner slide answers one question while creating the next one. Before writing each slide, name the question the previous slide planted — if the slide doesn't answer it, rewrite the slide.
Structure:
1. type "cover": THE HOOK — the single most important thing in the whole post (see COVER HOOK below). No body.
2. type "content": first chain answer. Doubles as the SECOND COVER — Instagram re-serves skipped carousels with slide 2 as the cover, so its headline must hook standalone, never "Here's how" or "The details".
3+. type "content": the rest of the chain. Each headline = a 5-9 word standalone factual CLAIM someone could disagree with — NEVER a label ("THE DETAILS", "THE REAL STORY", "WHAT THIS MEANS FOR X") and NEVER an aphorism/motivational line ("X BEATS Y"). Use physical past-tense verbs (parked, gutted, handed, escaped — never "is using", "means", "finds") and put a number in the headline whenever the story has one. Body = SPOKEN VOICE (owner directive Aug 1 — the stat-dump bodies read "so not interesting"): 2-3 sentences the way you'd SAY them across a table — a punch, then the plain-words explanation, then a kicker that tees up the next slide. Numbers and names still land in <b>, but a sentence may carry ZERO numbers; voice beats stat density, and a body that reads like a market wrap ("the S&P was green, Nasdaq up 1%") is a failed slide. Ranks and records when TRUE (first, biggest, worst day ever) beat raw figures. Each body delivers a NEW fact — never a re-say of its own headline.
Second-to-last. type "content": THE VALUE SLIDE — the consulting-funnel slide, built with the $100M Offers rules (section 5 of the principles). Open with the business owner's PAIN this story touches, then the escape: what a normal business can DO with this, with a concrete number, and why it's now fast/effortless ("without hiring anyone"). Its headline is a factual claim with a number too — never a lesson or a "what this means" label. The reader-owner should finish it thinking "I want this in MY business". Same visual style, no selling tone, no price ever. NEVER a moral or an aphorism (owner comparison Aug 1: "The businesses making real money put AI to work, they don't bet on it" shipped as a sermon that broke the story's spell) — the value slide is still a STORY slide: a concrete number and a real capability, zero preaching.
Last. type "cta": THE FOLLOW CONVERSION (owner doctrine Aug 1, copied from the reference page's closer — REPLACES the Jul 29 story-FOMO formula): the headline is a DIRECT follow line in one of two registers, wording freshly varied every post: LOSS AVERSION ("YOU MAY NEVER FIND OUR PAGE AGAIN IF YOU DON'T FOLLOW US") or DAILY VALUE ("WE SHARE DAILY UPDATES ON WHAT'S HAPPENING IN AI"). These run 8-11 words — hsize 54-64 so the block still fits. Body: ONE sentence with a specific SEND line naming the exact person-type this story hits ("Send this to the friend who still types every email himself") — a send-line is utility; "tag a friend" is banned bait. The CTA image is the story's famous person (the art direction handles it): the person the reader just spent six slides with is the one telling them to follow.
For builder_story follow its container spec slide order instead (same question-chain style).

PROFILE CARD FORMAT (owner gold-standard example Aug 1 — the @techskills Mercor post; optional, use it ONLY when the story is ONE PERSON'S RISE — a founder/inventor profile with a record or a huge number — AND at least 3 real article photos exist; never for company/product news):
- Every content slide sets "layout": "card" and "headline": "" — the story lives in the BODY: 2-3 tiny paragraphs (blank line between), each 1-2 micro-sentences, ONE fact per sentence. The register is a biography told in flashcards: "His name is Surya Midha.\n\nIndian-origin. Parents from Delhi.\n\nBorn in Mountain View. Raised in San Jose." Numbers/names in <b>; the ONE money/record phrase per slide in <em> (this is the only place <em> is allowed in a body).
- Every card slide gets a REAL photo (media_idx) — childhood/early shots, the team, the product; the photo renders in a rounded card under the text and is the proof artifact. image_brief only as a last-resort fallback.
- Slide order = a life arc: who he is → the early feat → the founding → what the thing does + the money number → the growth numbers → the record + the stance. Same open-loop rule at every boundary.
- The COVER for this format: one 12-24 word record-sentence that tells the WHOLE claim, structured [record] + [how, in plain words] ("A 22 year old just became the youngest self made billionaire in history. He built an AI recruiting tool with 2 college friends"), hsize 54-58, <em> on the record phrase. The absurd true claim IS the hook; there is no hidden twist to protect.
- If the story's company logo exists in our logo set, set top-level "badge_logo" to it and make sure the cover image puts the person RIGHT of center (the badge chip renders top-left).

COMPOSED COVER (owner gold standard Aug 1 — the @getintoai anatomy; STRONGLY PREFERRED whenever eligible): when the cover's real article photo (media_idx) shows the story's FAMOUS person — one person, chest-up, face clear — set "discs" on the cover slide: 1-2 elements that complete the story equation beside the face. First disc = the story company's logo (only names from the logo list). Second disc = the exact product/object the headline claims, as SHORT typeset text, 12 characters max ("OPUS 5", "CODEX", "$45B MEMO") — or a second logo when the story pairs two brands. The pipeline cuts the person out of the photograph, blurs the photo's own world into the backdrop, floats the discs at head height and layers the person OVER them — face, logos and background all connected to the claim (reference: Sam Altman shushing between the OpenAI badge and a terminal icon; Anthropic's CEO between the Claude disc and an "Opus 5" disc). Rules: ONLY on a real press photo of a famous person — never on a generated image, never an unknown face; every disc must be RELATIONAL (the brand of the story + the thing the headline claims — a disc that could sit on any post is banned); skip discs when the photo has multiple people or the person is a tiny part of the frame. If the cutout fails, the pipeline falls back to the plain photo cover automatically.
FACES POOL — we keep real press photos on file for: {face_list}. If the story's main famous actor is on that list and NO article photo shows them, STILL do the composed cover: set "face" on the cover slide to that exact id (e.g. "sam-altman") together with "discs", and omit media_idx — the pipeline uses our stored press photo. A cover should NEVER ship as logo-on-artwork when the story's actor is in this pool; the face is what stops the scroll. Only use a face when the story is genuinely about that person or their company.

COVER HOOK — the #1 priority. The cover decides whether anyone swipes. OWNER DOCTRINE (Aug 1, the reference-page audit — REVERSES the Jul 29 information-gap rule and overrides everything older): the cover TELLS THE WHOLE STORY with its wildest specifics. A cryptic tease only works for pages with authority; a growing page earns the swipe by delivering a complete wild claim the reader already believes — they swipe for the photos, the details and the fallout. Built ONLY from true facts in the story.
{steer}
General craft (the STORY TYPE formula above decides which specific leads; these rules shape it):
- LENGTH 12-25 words, aim 15-20: ONE complete sentence summarizing the story — actor, what happened, and the numbers/specifics that make it wild. NOTHING is withheld.
- Reference craft (the pages we model — @technology): "OPENAI JUST LAUNCHED THEIR FIRST EVER HARDWARE PRODUCT, A $230 LIGHT UP KEYBOARD BUILT TO RUN YOUR AI CODING AGENTS" (19 words, full story + price + first-ever); "APPLE'S FIRST HIGH END MACBOOK REDESIGN IN FIVE YEARS IS REPORTEDLY BRINGING 12 NEW FEATURES". The old style — "VISA JUST BET EVERYTHING" (4 words, total gap) — is now the FAILURE model: a riddle from an unknown page gets scrolled past.
- Charged verbs and power words when true: BET, FIRED, DECLARED WAR, ROGUE, SECRET, QUIETLY, BANNED, LEAKED, EXPOSED, ON PURPOSE. Threat/loss framing beats triumph framing when both are true. Second person ("YOUR") when the story touches the reader. Simple 8th-grade words only.
- Banned on covers: neutral news-title phrasing, hedging (may/could/reportedly), company-PR framing, and any brand name a random 16-year-old wouldn't recognize (use the universal noun the STORY TYPE block names instead).
- Self-test before finalizing (all must pass): (1) does the headline follow THIS story type's formula above? (2) Does a stranger get the FULL story — who, what, the wild number — from the cover alone? If any specific got held back for slide 2, put it on the cover. (3) Is the claim wild enough that they'd swipe for proof and details? If the summary reads like a neutral newspaper headline, the problem is the angle, not the length — find the wilder true framing.
- HOOK TOURNAMENT (mandatory): write FIVE genuinely different cover candidates in "hook_candidates" — different angles (threat vs record vs money vs scarcity subject), not rewordings. Each: {{"headline": "... with <em> accents ..."}}. Put your best one on the cover slide AND include it among the five. A separate blind judge will pick the winner.

RULES
- LANGUAGE (hard requirement): write for a smart 16-year-old. Everyday words only, short sentences. No industry jargon anywhere — headlines, bodies, caption. Say what things DO ("runs powerful AI on your own computer"), not what they're called ("an agentic runtime"). If a technical term is unavoidable, explain it in plain words in the same sentence.
- <em>...</em> in headlines marks the accent: ONE contiguous phrase, ideally a WHOLE LINE of the headline (two groups absolute max). Orange-on-entire-lines creates rhythm and a reading order; orange scattered across four single words is confetti — four competing focal points = zero focal points (owner verdict Jul 28). Connectives stay white. Every headline needs at least one <em>.
- <b>...</b> in bodies marks facts (names, numbers). No <em> in bodies.
- hsize: headline font px. Cover headlines (12-25 words) → 58-70 so the sentence breaks edge-to-edge into 4-6 tight condensed lines like the reference page (the renderer caps total block height, so oversizing just shrinks it back). Inner-slide headlines: short (≤5 words) → 110-124; medium → 90-105; long → 76-88.
- Bodies never end with a period (house style). No emojis in slides.
- Caption: all five blocks in order, separated by blank lines. Sources line names the actual outlet(s). Exactly five hashtags (topic keywords for search — hashtags don't add reach). The FIRST sentence carries the payoff AND the search keywords — IG is a search engine in 2026 and the first line drives Explore/search reach: name the company and the topic noun in plain words ("Visa is replacing 2,600 jobs with AI" — searchable; "They just bet everything 👀" — invisible). Only ~125 chars show before "...more". CTA must be utility ("save this", "send this to..."), NEVER reaction-bait ("tag a friend", "comment YES") — Meta penalizes bait.
- "pinned_comment" (mandatory): the first comment we plant under the post the second it publishes — hour-one comment velocity is distribution fuel. ONE of: a debatable fault line from the story people must answer ("Would you let it run your payroll? Half of you are lying") or the juiciest fact that didn't fit the slides ("The part we couldn't fit: ..."). 1-2 sentences, no hashtags, no links, never a summary of the post.
- Caption owner-CTA (mandatory): the LAST line of the trend block, on its own line, invites business owners to DM — pain + tiny ask, tied to this story's value. Register: "Running a business? DM us "AI" and we'll show you what this could do for yours". Vary the wording per post, keep the DM word exactly "AI"
- Never invent facts not present in the STORY material above.
- If cover_style is "photo" the headline sits over the photo — keep it short.

Return ONLY the JSON object, no markdown fences, no commentary."""


def call_claude(prompt, schema=None, images=None, model=None, web=False):
    # scraped article text can carry null bytes — they crash subprocess exec
    # (embedded null byte) and are invalid in API JSON anyway
    prompt = prompt.replace("\x00", "")
    use_model = model or MODEL
    # TOKEN-DIET LOCK (owner order Aug 8: "make sure now the token plan cost
    # is permanent and always"): this is the ONLY function in the pipeline
    # that talks to Claude, and Opus is banned here forever. Any future edit
    # that routes a call to Opus dies loudly instead of silently burning the
    # plan. Undoing the diet is an owner-only decision and requires
    # deleting this gate on purpose — never work around it.
    if "opus" in use_model.lower():
        raise RuntimeError(f"token-diet lock: Opus is banned ({use_model}) — "
                           "owner order Aug 8; writers=Sonnet, judges=Haiku")
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
        kwargs = {}
        if web:  # culture radar (Aug 9): live web search inside the one call
            kwargs["tools"] = [{"type": "web_search_20250305",
                                "name": "web_search", "max_uses": 5}]
        with client.messages.stream(
            model=use_model, max_tokens=8000,
            thinking={"type": "adaptive"},
            output_config={"format": {"type": "json_schema", "schema": schema or SCHEMA}},
            messages=[{"role": "user", "content": content}], **kwargs,
        ) as stream:
            msg = stream.get_final_message()
        return json.loads("".join(b.text for b in msg.content if b.type == "text"))
    # fallback: Claude Code CLI, no key needed. Image prompts say "use your
    # Read tool on <path>" — grant Read + the images' dirs or the CLI stalls
    # asking for permission (seen Jul 28 on /tmp QA frames).
    # Token diet part 2 (measured Aug 8): a bare `claude -p` loads the Claude
    # Code system prompt + all tool schemas + CLAUDE.md + auto-memory =
    # ~53.5k input tokens PER CALL before our prompt. The flags below cut
    # that to ~3k (text calls) / ~21k (vision calls, which keep the Read
    # tool) with identical outputs — the prompts here are self-contained.
    cmd = ["claude", "--model", use_model, "-p", prompt,
           "--setting-sources", "", "--disable-slash-commands",
           "--no-session-persistence"]
    if images:
        cmd += ["--tools", "Read", "--allowedTools", "Read"]
        for d in sorted({os.path.dirname(os.path.abspath(p)) for p in images}):
            cmd += ["--add-dir", d]
    elif web:  # culture radar: WebSearch only, same trimmed system prompt
        cmd += ["--tools", "WebSearch", "--allowedTools", "WebSearch",
                "--system-prompt",
                "You are the research engine of an automated content "
                "pipeline. Use web search, then follow the instructions in "
                "the message exactly and return only the requested output."]
    else:
        cmd += ["--tools", "", "--system-prompt",
                "You are the writing and judging engine of an automated "
                "content pipeline. Follow the instructions in the message "
                "exactly and return only the requested output."]
    # PULSE watchdog, not a stopwatch (Aug 9 post-mortem, runs 31316462087
    # through 31324772418): the doctrine writer call takes 6-7 min on a QUIET
    # plan — measured 385s locally on the exact failing prompt — and longer
    # when the shared subscription is throttled. Every total-time timeout we
    # tried (20 min Aug 8, 8 min Aug 9) killed healthy calls mid-generation
    # and the whole day's carousel runs died while small HE calls sailed
    # through. _stream_claude leaves a slow-but-pulsing call alone and kills
    # only true silence. One patient retry: a real stall is the plan refusing
    # to start the stream, and an instant retry re-stalls almost every time.
    try:
        out = _stream_claude(cmd)
    except subprocess.TimeoutExpired:
        print("claude -p stream went silent — waiting 10 min, then retrying "
              "once with a fresh process", file=sys.stderr)
        time.sleep(600)
        out = _stream_claude(cmd)
    obj = _extract_json(out)
    if obj is None:
        # Same transient family as the stall, different symptom: the CLI
        # returns an error string instead of JSON ("API Error: Stream idle
        # timeout - partial response received" killed the Aug 2 morning reel,
        # issue #13). One fresh call, then give up.
        print(f"claude -p returned no JSON ({out[:120]!r}) — retrying once",
              file=sys.stderr)
        out = _stream_claude(cmd)
        obj = _extract_json(out)
    if obj is None:
        # RuntimeError, NOT SystemExit: callers with fail-open except-Exception
        # handlers (dupe judge, scout judge, vision QA) must be able to catch it
        raise RuntimeError(f"claude -p returned no JSON:\n{out[:500]}")
    return obj


def _stream_claude(cmd):
    """Run `claude -p` in stream-json mode with an IDLE watchdog: every
    output chunk is a pulse, so a slow-but-alive call (throttled plan) runs
    to completion, while 4 minutes of total silence — a true stall, the
    server never streaming — kills it fast. 40-min hard cap as a safety
    net so a pathological call can never eat the 90-min CI job alone.
    Returns the final result text ("" if the CLI died without one)."""
    import select
    cmd = cmd + ["--output-format", "stream-json",
                 "--include-partial-messages", "--verbose"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL)
    fd = proc.stdout.fileno()
    result, buf = None, b""
    hard_deadline = time.time() + 2400
    try:
        while True:
            wait = min(240.0, hard_deadline - time.time())
            if wait <= 0:
                raise subprocess.TimeoutExpired(cmd, 2400)
            ready, _, _ = select.select([fd], [], [], wait)
            if not ready:
                raise subprocess.TimeoutExpired(cmd, 240)
            chunk = os.read(fd, 65536)
            if not chunk:
                break  # EOF — process finished (or died; retry path handles it)
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if isinstance(ev, dict) and ev.get("type") == "result":
                    result = ev.get("result") or ""
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait()
    return result if result is not None else ""


def _extract_json(out):
    """Pull the response JSON object out of CLI chatter. The old greedy
    regex + naked json.loads CRASHED the whole process when Sonnet wrapped
    the JSON in prose (run 31259996256, Aug 8: 'Extra data: line 1 column
    20' killed the edu ladder rung mid-slot). raw_decode from every '{'
    tolerates leading/trailing text; the largest valid dict wins (chatter
    can contain tiny brace snippets before the real payload)."""
    dec = json.JSONDecoder()
    best = None
    for m in re.finditer(r"\{", out):
        try:
            obj, end = dec.raw_decode(out[m.start():])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and (best is None or end > best[1]):
            best = (obj, end)
    return best[0] if best else None


def qa_repair(post, errs):
    """Copy-editor pass: fix ONLY the QA failures on an otherwise-passing
    post (see the Aug 2 repair-pass note in main's QA loop). Fails open:
    None -> the caller falls through to full regeneration as before."""
    err_list = "\n- ".join(errs)
    prompt = f"""You are the copy editor of a finished Instagram carousel. Below is the post JSON and the exact list of quality-gate failures. Fix ONLY the listed problems, changing the minimum text needed — every word not implicated by a failure stays EXACTLY as it is, and the JSON structure, field names, and slide order stay identical.

How to fix the common failures:
- body too long: cut to the best 2 sentences, 30 words max — keep the <b> tags and the concrete facts, drop the weakest sentence
- body repeats its own headline's number: replace that sentence with a NEW true fact from the post's other text, or the plain-words consequence — never re-say the headline
- number repeated across slides: keep it on the earlier slide, rewrite the later mention into a different true specific
- cta headline register: replace with a DIRECT follow line, 8-11 words, loss-aversion ("YOU MAY NEVER FIND OUR PAGE AGAIN IF YOU DON'T FOLLOW") or daily-value ("WE SHARE DAILY UPDATES ON WHAT'S HAPPENING IN AI") register, freshly worded
- missing image_brief: write one — 15-40 words, subject first then action then setting, evidence of THAT slide's exact claim, no readable text in scene, end with one color key
- quotes/cites an internet user: delete the attribution, state the fact directly

THE POST:
{json.dumps(post, ensure_ascii=False)}

FIX EXACTLY THESE:
- {err_list}

Return ONLY the complete corrected JSON object, same shape."""
    try:
        return call_claude(prompt)
    except Exception as e:
        print(f"qa_repair failed ({e}) — falling back to regeneration",
              file=sys.stderr)
        return None


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
    # summarizing cover (owner flip Aug 1, reference-page audit — REVERSES
    # the Jul 29 information-gap cap): the cover tells the whole story with
    # its specifics in 12-25 words. Profile covers were already there (12-24).
    cover_cap = 24 if profile else 26
    cover_words = len(re.sub(r"<[^>]+>", "", slides[0]["headline"]).split())
    if cover_words > cover_cap:
        errs.append(f"cover headline is {cover_words} words (max {cover_cap}) — "
                    "one complete sentence, cut connective fat, keep the numbers")
    # floor only for news-story posts (container key) — edu N-promise covers
    # ("6 SERVICES AI REPLACES FOR FREE") are short by design
    if post.get("container") and not profile and cover_words < 10:
        errs.append(f"cover headline is only {cover_words} words — the cover "
                    "SUMMARIZES the whole story (12-25 words: actor, what "
                    "happened, and the wild numbers), it never withholds")
    if len(re.findall(r"<em>", slides[0]["headline"])) > 2:
        errs.append("cover has >2 <em> groups — accent ONE contiguous phrase or "
                    "whole line (two max), scattered single-word accents are "
                    "confetti with zero focal point")
    # reaction-metric ban (Aug 3 Queen/Mario post-mortem: both disasters
    # closed the cover with ", AND 40K LIKES" / "69K LIKES" — a like count
    # is coverage of a post, not a story; it also proves the story class is
    # reaction-bait). Mirrors the tournament intake filter in viral.py.
    cover_plain = re.sub(r"<[^>]+>", "", slides[0]["headline"])
    if re.search(r"(?i)\b\d[\d.,]*\s*(?:K|M|MILLION|THOUSAND)?\s*"
                 r"(?:LIKES?|REPLIES|RETWEETS?|REPOSTS?|UPVOTES?|SHARES|"
                 r"VIEWS|COMMENTS)\b", cover_plain):
        errs.append("cover headline cites a reaction metric (likes/views/"
                    "replies) — that's coverage of a post, not the story; "
                    "rewrite the beat with a real-world fact (money, scale, "
                    "who did what)")
    # kicker strip (forensic Aug 2): one tiny second beat, plain text only
    kick = re.sub(r"<[^>]+>", "", slides[0].get("kicker") or "").strip()
    if kick and not (3 <= len(kick.split()) <= 8):
        errs.append(f"cover kicker is {len(kick.split())} words (want 3-8) — "
                    "the strip fits one short second beat, or omit it")
    # storytelling gates (owner directive Jul 31: the story itself, not the
    # coverage — no newsreader hedges, no random-user quotes, no slide walls)
    for i, s in enumerate(slides):
        text = re.sub(r"<[^>]+>", "", " ".join(
            filter(None, (s.get("headline", ""), s.get("body", "")))))
        # "reportedly" is licensed on the COVER only, for leak/rumor claims
        # (forensic Aug 2: the reference page runs "XBOX REPORTEDLY PLANNED",
        # "FERRARI REPORTEDLY HIT" constantly) — inner slides still ban it
        hedge_pat = (r"(?i)\b(allegedly|according to|sources say|is said to)\b"
                     if i == 0 else
                     r"(?i)\b(reportedly|allegedly|according to|sources say|is said to)\b")
        if re.search(hedge_pat, text):
            errs.append(f"slide {i+1}: newsreader hedge (reportedly/according to...) — "
                        "state what happened or cut the claim; sources live in the caption")
        if re.search(r"(?i)\b(a|an|one|another) (reddit|x|twitter|instagram|internet)? ?"
                     r"(user|commenter|redditor)\b|\bviral post (claims|says)|\busers? (say|said|claim)", text):
            errs.append(f"slide {i+1}: quotes/cites a random internet user — cut it, "
                        "people want the story, not who said it")
        # felt-scale (owner directive Aug 1, the Reddit-crash post-mortem:
        # "the market was green, S&P up 0.70%" is a Bloomberg wire, not a
        # story) — finance jargon banned on slides, translate to human scale
        if re.search(r"(?i)\b(S&P *500?|Nasdaq|Dow Jones|market cap|trading "
                     r"session|premarket|after[- ]hours trading|intraday|the "
                     r"market)\b|\$[A-Z]{2,5}\b|\bshares\b", text):
            errs.append(f"slide {i+1}: finance-wire jargon (index names, tickers, "
                        "'shares', 'the market') — translate to FELT SCALE: absolute "
                        "dollars, the reader's $1,000 stake, or a record ('worst day ever')")
        body_cap = 60 if s.get("layout") == "card" else 34
        body_words = len(re.sub(r"<[^>]+>", "", s.get("body") or "").split())
        if body_words > body_cap:
            errs.append(f"slide {i+1}: body is {body_words} words (max {body_cap}) — "
                        "a slide is a beat, not a paragraph: keep the one detail that "
                        "answers the question, move or cut the rest")
        # media on every slide (owner audit Aug 1: reference carousels never
        # ship a naked text slide). image_brief counts — the gen ladder and
        # its budget guard decide later; a slide may still RENDER text-only
        # if generation fails, so the always-post rule is never at risk
        if (s["type"] == "content" and not s.get("media_idx")
                and not (s.get("image_brief") or "").strip()):
            errs.append(f"slide {i+1}: no media_idx and no image_brief — every "
                        "content slide needs a real photo or an image brief")
    # new-fact-per-slide (owner audit Aug 1: the Reddit post's slides 3 and 4
    # told the same fact, and slide 2's body restated its own headline): a
    # meaty number (>12, not a year) lives on the cover plus AT MOST one
    # content slide, and a body never repeats its own headline's number.
    # Story flow only (container key); card layouts (biography format) exempt
    if post.get("container"):
        def _nums(t):
            out = set()
            for m in re.findall(r"\d[\d,.]*", re.sub(r"<[^>]+>", "", t or "")):
                v = m.replace(",", "").rstrip(".")
                try:
                    f = float(v)
                except ValueError:
                    continue
                if f > 12 and not (1900 <= f <= 2100 and "." not in v):
                    out.add(v)
            return out
        seen_nums = {}
        for i, s in enumerate(slides):
            if s["type"] != "content" or s.get("layout") == "card":
                continue
            dup = _nums(s.get("headline")) & _nums(s.get("body"))
            if dup:
                errs.append(f"slide {i+1}: body repeats its own headline's number "
                            f"({', '.join(sorted(dup))}) — the body ADDS new facts, "
                            "it never re-says the headline")
            for n in _nums(s.get("headline")) | _nums(s.get("body")):
                if n in seen_nums:
                    errs.append(f"slide {i+1}: repeats the number {n} from slide "
                                f"{seen_nums[n] + 1} — one fact lives on ONE slide; "
                                "go deeper with a NEW fact instead of repeating")
                else:
                    seen_nums[n] = i
    if "Sources:" not in caption:
        errs.append("caption missing Sources line")
    else:
        # owner rule (Aug 8, re-confirmed): credit is a plain name at the
        # bottom, never a tag. Reels had this gate (reel.py qa) since Aug 2;
        # carousels leaked "@Ayzacoder on X" through the prompt-only rule.
        src_line = next((l for l in caption.split("\n") if "Sources:" in l), "")
        if re.search(r"@\w|(?:^|\s)u/", src_line):
            errs.append('Sources line must credit plain names only — no '
                        '@handles or u/ prefixes ("Ayzacoder" not "@Ayzacoder")')
    if len(re.findall(r"#\w+", caption)) != 5:
        errs.append("caption must have exactly 5 hashtags")
    # follow-conversion CTA (owner doctrine Aug 1, the reference page's closer:
    # loss-aversion "you may never find our page again" / daily-value "we
    # share daily updates" — reverses the Jul 29 story-FOMO rule, which the
    # Aug 1 audit found converts worse than the direct follow ask).
    # container key only exists in the story flow — edu's save-CTA is exempt
    if post.get("container"):
        cta_head = re.sub(r"<[^>]+>", "", slides[-1].get("headline", ""))
        if not re.search(r"(?i)\bfollow", cta_head):
            errs.append("cta headline must be a DIRECT follow line (loss-"
                        "aversion or daily-value register per the spec), not "
                        "a story tease")
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
        body_text = story["radar"]["selftext"]  # X-native story: the tweet IS the article
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

    # ONE merged prep call (token diet Aug 8): retell + spine + classify
    retold, spine, ctx = prep_story(story, body_text)
    if retold:
        print(f"retell: {retold['retell'][:120]}", file=sys.stderr)
    # hook ammunition for the tournament (restored Aug 10: the Aug 8 prep_story
    # merge deleted this line but the tournament call kept using it — every
    # news story that survived gate A since then crashed write.py into the
    # edu fallback, zero news carousels shipped)
    material = (retold["retell"] + "\n" + "\n".join(retold.get("facts", []))
                if retold else body_text)
    print(f"viral classify: {ctx['story_type']}, actor '{ctx.get('actor')}' "
          f"{'known' if ctx.get('actor_known') else 'UNKNOWN -> anchor: ' + str(ctx.get('anchor'))}",
          file=sys.stderr)
    if spine:
        print(f"spine twist: {spine['twist'][:110]}", file=sys.stderr)

    steer = viral.hook_block(ctx)
    prompt = build_prompt(story, body_text, media_files, retold, steer, spine)
    # 2 full regenerations, not 3 (token diet Aug 8): qa_repair's surgical pass
    # converges most failures cheaply; the workflow's edu fallback ladder still
    # guarantees the slot posts if both rolls fail.
    for attempt in range(2):
        post = call_claude(prompt, images=media_files)
        errs = qa(post)
        if errs:
            print(f"QA gate failed (attempt {attempt+1}):\n  " + "\n  ".join(errs),
                  file=sys.stderr)
            # REPAIR PASS (Aug 2: two slots died in 24h to QA-exhaustion —
            # each retry regenerated the WHOLE post, a fresh dice roll on 20+
            # gates that fixed old errors while minting new ones. A surgical
            # edit of only the flagged lines converges; regeneration doesn't.)
            fixed = qa_repair(post, errs)
            if fixed:
                left = qa(fixed)
                if not left:
                    print("repair pass cleared QA — using repaired post",
                          file=sys.stderr)
                    post, errs = fixed, []
                else:
                    print("repair left errors:\n  " + "\n  ".join(left),
                          file=sys.stderr)
        if not errs:
            break
        prompt = (build_prompt(story, body_text, media_files, retold, steer, spine)
                  + "\n\nYOUR PREVIOUS ATTEMPT FAILED THESE QA CHECKS — fix every one:\n- "
                  + "\n- ".join(errs))
    else:
        raise SystemExit("QA gate failed after 2 attempts")

    if any(s.get("layout") == "card" for s in post["slides"]):
        # profile format: the record-sentence cover IS the hook — rival
        # candidates don't know the card format and would replace it with
        # a generic news hook, destroying the format
        print("profile format: hook tournament skipped", file=sys.stderr)
        post.pop("hook_candidates", None)
    else:
        post = viral.tournament(post, story, ctx, material)
    # duplicated-strip check moved into viral.drop_stale_kicker (Aug 3) —
    # tournament runs it itself; this call covers the card path that skips it
    viral.drop_stale_kicker(post)
    post["viral"] = ctx  # he.py re-creates the Hebrew hook from this

    art_direct(post, story["title"])  # optimal image prompts for the FINAL cover

    shot = None
    if post.get("container") == "builder_story" and post.get("product_url", "").startswith("http"):
        shot = product_screenshot(post["product_url"], post_dir)
        print(f"product screenshot: {'ok' if shot else 'unusable'}", file=sys.stderr)

    # official product photos (owner Aug 1: "we only can show the real product
    # — you can source the official pictures online"): the maker's own page
    # carries the true press shots. They join the candidate pool (leftovers can
    # fill imageless slides) and become the PREFERRED generator reference.
    official_files = []
    if post.get("product_url", "").startswith("http"):
        for u, data in article_images(post["product_url"], max_out=3):
            ext = ("png" if data[:8] == b"\x89PNG\r\n\x1a\n"
                   else "webp" if data[8:12] == b"WEBP" else "jpg")
            p = os.path.join(post_dir, f"cand-{len(media_files) + 1}.{ext}")
            open(p, "wb").write(data)
            media_files.append(p)
            official_files.append(p)
        print(f"{len(official_files)} official product photo(s) sourced",
              file=sys.stderr)

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
    cover_scored = False  # a candidate cover judged once is not judged again
    cover_brief = ""  # the cover's final brief, kept for the <=4 rescue rung
    # product-hero reference (@technology Codex Micro anatomy, owner Aug 1):
    # the real product photo rides along to Seedream so the generated device
    # matches reality — the cover's assigned article photo, else the first one
    ref_photo = None
    if any(s.get("gen_ref") for s in post["slides"]):
        cm = post["slides"][0].get("media")
        ref_photo = (official_files[0] if official_files else
                     os.path.join(HERE, cm) if cm and not
                     os.path.basename(cm).startswith("gen") else
                     (media_files[0] if media_files else None))
    for i, s in enumerate(post["slides"]):
        brief = s.pop("image_brief", "").strip()
        want_ref = s.pop("gen_ref", False) and ref_photo
        # PERSON ROUTE (owner Aug 2: "i prefer a model that allows that
        # immediately, it will be much less bugs"): briefs featuring famous
        # people go to gpt-image-2 with the names IN the prompt — no reference
        # photos, no name-stripping, no E005. Measured head-to-head: it nailed
        # all three billionaires' likenesses; FLUX rendered lookalikes. The old
        # Seedream ref-photo route (face_riders) survives as the fallback rung.
        face_field = s.pop("gen_face", None)
        person = bool(face_field)
        face_refs = []
        if not person:
            # incidental names in a no-face brief still kill Seedream (E005)
            brief, face_refs = face_riders(brief, None)
        # brand reference (owner Aug 1, courtroom cover: from-memory logos come
        # out wrong): the real SVG rasterized rides along as the third ref
        brand_ref = None
        logo_slug = s.pop("gen_logo", None)
        if logo_slug:
            brand_ref = logo_ref(logo_slug.replace(" ", ""))
        # cta generates when it has a real anchor: the product photo (product-
        # hero second pose) or the story person's face ref (owner Aug 1: the
        # Tim Cook closer — the story's person says "follow us"). No anchor ->
        # art bg, never a from-scratch face
        if s["type"] == "cta" and not (want_ref or face_refs or person):
            continue
        if not brief or gen >= 4:
            continue
        if s.get("media") and s["type"] not in ("cover", "cta"):
            continue
        # COMPOSITE-FIRST (owner verdict Aug 1: "this isn't their actual
        # product"): when the cover already holds a REAL article photo, a
        # generated replica never replaces it — generation only competes if
        # it is a TRUE product-hero with BOTH references (real product photo
        # + the CEO's real face photo). Otherwise the real photo ships —
        # but ONLY after the judge approves it (Aug 3 Queen Elizabeth
        # post-mortem: this branch shipped a scraped X meme screenshot with
        # baked-in caption and a 21K-heart UI as the cover, unscored — the
        # judge only ever saw generated images). A failing candidate loses
        # the slot and generation runs exactly like a coverless post.
        if (s["type"] == "cover" and s.get("media")
                and not os.path.basename(s["media"]).startswith("gen")
                and not (want_ref and (face_refs or person))):
            cand = os.path.join(HERE, s["media"])
            ok, score, flaw = image_score(cand, s.get("headline", ""))
            cover_scored = True
            if ok:
                continue
            print(f"cover candidate rejected (score {score}/10): {flaw} "
                  "— falling through to generation", file=sys.stderr)
            pool.append((score, cand))
            s["media"] = None
        # cover ladder (owner rules Jul 29: capped attempts — each image costs
        # money — the brief rewritten around the judge's named flaw between
        # attempts, and the post NEVER ships imageless: if nothing passes, the
        # best-scoring reject wins). Inner slides keep one shot; genimg's
        # budget guard caps total spend either way.
        # cover tries 3 -> 2 (token diet Aug 8): each extra try = a vision
        # judge + a brief rewrite + Replicate spend; best-reject floor remains
        tries = 2 if s["type"] == "cover" else 1
        for attempt in range(tries):
            out_jpg = os.path.join(post_dir, f"gen-{i}{'-r' * attempt}.jpg")
            path = None
            if person:
                path = genimg.generate(brief, out_jpg,
                                       cover=(s["type"] == "cover"), person=True)
                if not path:
                    # FALLBACK RUNG (always-post ladder): gpt failed/budget-out
                    # -> Seedream with ref photos, names stripped (E005)
                    person = False
                    brief, face_refs = face_riders(brief, face_field)
            if not path:
                refs = [r for r in [ref_photo if want_ref else None]
                        + face_refs + [brand_ref] if r]
                path = genimg.generate(brief, out_jpg, refs=refs or None,
                                       cover=(s["type"] == "cover"))
            if not path:
                # keep trying: one flaky prediction must not forfeit the cover
                # (Aug 2 bare edu cover, issue #16); budget-out retries are
                # free local no-ops so continue is safe either way
                continue
            ok, score, flaw = image_score(path, s.get("headline")
                                          or (s.get("body") or "")[:90],
                                          generated=True, person=person)
            if ok:
                s["media"] = os.path.relpath(path, HERE)
                gen += 1
                if s["type"] == "cover":
                    post["cover_style"] = "photo"  # a generated cover is a photo cover
                    # owner Aug 1 ("why is that logo?"): a generated scene
                    # brands ITSELF (neon logo, product mark) — the flat
                    # overlay stamp on top reads as a cheap edit. Never both.
                    s.pop("logos", None)
                    if person:
                        # person-route cover: accurate famous likeness in the
                        # story's SITUATION — the faces-pool composite must
                        # never replace it (owner Aug 3, the $750B failure)
                        s["gen_person"] = True
                break
            print(f"slide {i+1} image rejected (attempt {attempt+1}/{tries}, "
                  f"score {score}/10): {flaw}", file=sys.stderr)
            if s["type"] == "cover":
                pool.append((score, path))
            if attempt + 1 < tries:
                # person-route covers retry concept-preserving (Aug 9): keep
                # the staged scene + cast, fix only the judge's named flaw
                brief = simpler_brief(brief, s.get("headline")
                                      or (s.get("body") or "")[:90], flaw,
                                      mode="concept" if person else "simpler") or brief
                if not person:
                    # the rewrite sees the headline, which may name real
                    # people — re-scrub or the Seedream retry dies to E005
                    # (the gpt person route KEEPS names, that's its point)
                    brief = face_riders(brief, None)[0]
        if s["type"] == "cover":
            cover_brief = brief
    if gen:
        print(f"{gen} Seedream image(s) generated", file=sys.stderr)

    # cover ladder, last rungs (owner rule Jul 29: "we can never post without
    # an image"): unused article images join the scored pool; if nothing
    # passed outright, the BEST-SCORING candidate ships — flagged in
    # post.json so the daily report names it for owner review. A bare type
    # cover is legal only when zero images exist at all.
    # NO logos exemption (owner Aug 1, Chrome-bugs post: "terrible logo and
    # without a cover photo" — a bare logo-on-dark cover is never acceptable):
    # when generation starves, a logos cover falls back to a real article
    # photo exactly like every other style.
    cover0 = post["slides"][0]
    # FINAL COVER AUDIT (Aug 3 Queen Elizabeth post-mortem, second hole): a
    # cover whose candidate photo arrived WITHOUT an image_brief never enters
    # the generation loop above, so the composite-first judging there never
    # runs — this was the actual path that shipped the meme screenshot. Every
    # non-generated cover is judged exactly once before it may ship.
    if (cover0.get("media") and not cover_scored
            and not os.path.basename(cover0["media"]).startswith("gen")):
        ok, score, flaw = image_score(os.path.join(HERE, cover0["media"]),
                                      cover0.get("headline", ""))
        if not ok:
            print(f"cover candidate rejected in final audit (score {score}/10):"
                  f" {flaw}", file=sys.stderr)
            pool.append((score, os.path.join(HERE, cover0["media"])))
            cover0["media"] = None
    if not cover0.get("media"):
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
            # RESCUE RUNG (owner audit Aug 10): a <=4/10 best reject is
            # wallpaper — one cheap faceless Seedream attempt via the no-face
            # playbook before settling for it. Always-post intact: the best
            # reject stays the floor if the rescue also fails.
            if score <= 4 and cover_brief:
                rb = simpler_brief(
                    cover_brief, cover0.get("headline", ""),
                    flaw=f"best attempt scored {score}/10 — rebuild as a "
                         "FACELESS scene per the no-face playbook: the famous "
                         "logo or the story's object mid-action at theatrical "
                         "scale, no human faces anywhere")
                if rb:
                    rb = face_riders(rb, None)[0]
                    rp = genimg.generate(
                        rb, os.path.join(post_dir, "gen-0-rescue.jpg"),
                        cover=True)
                    if rp:
                        ok2, s2, _ = image_score(rp, cover0.get("headline", ""),
                                                 generated=True)
                        if ok2:
                            cover0["media"] = os.path.relpath(rp, HERE)
                            post["cover_style"] = "photo"
                            post["cover_fallback"] = "no-face rescue"
                            print(f"COVER rescued by the no-face rung "
                                  f"({s2}/10)", file=sys.stderr)
                        elif s2 > score:
                            pool.append((s2, rp))
                            score, best = max(pool, key=lambda t: t[0])
        if not cover0.get("media") and pool:
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
    raw_discs = [d if isinstance(d, dict) else {"logo": d}
                 for d in (cover.get("discs") or []) if d]
    discs = [d for d in raw_discs
             if (d.get("logo") and os.path.exists(
                     os.path.join(HERE, "logos", f'{d["logo"]}.svg')))
             or (d.get("text") and len(d["text"]) <= 12)]
    cover.pop("discs", None)
    # faces pool (owner Aug 1: "cover picture is missing" — a cover must never
    # ship faceless when the story's actor is famous): no usable article photo
    # -> fall back to our stored real press photo of the person
    face = cover.pop("face", None)
    # a person-route generated cover (gen_person) counts as a REAL photo:
    # it shows the accurate famous face inside the story's situation — the
    # owner's preferred cover (Aug 3). Only faceless/Seedream gen images
    # still yield to the stored press photo.
    no_photo = not cover.get("media") or \
        (os.path.basename(cover.get("media", "")).startswith("gen")
         and not cover.get("gen_person"))
    if discs and face and no_photo:
        fp = pick_face(face)
        if fp:
            cover["media"] = fp
            print(f"faces pool: using stored press photo {os.path.basename(fp)}",
                  file=sys.stderr)
    if discs and cover.get("gen_person"):
        # owner formula Aug 3 ("a picture of the SITUATION!!!!... then you
        # also add the logos and it looks so much better"): the generated
        # scene already shows the person living the story — the brand discs
        # ride over the full-bleed image, no cutout, no blur.
        # LAYERING (owner Aug 3, the $750B cover — the SpaceX disc clipped
        # Musk's hair): the person from the SAME image re-draws on top of
        # the discs, so logos sit BEHIND the person and the person wins any
        # collision. rembg failure -> discs on top as before, never fatal.
        import composite
        pl = composite.person_layer(
            os.path.join(HERE, cover["media"]),
            os.path.join(post_dir, "person-layer.png"))
        if pl:
            cover["person_layer"] = os.path.relpath(pl, HERE)
        cover["discs"] = discs
        cover.pop("logos", None)
        print("situation cover: discs over generated scene"
              + (" (person re-drawn on top)" if pl else "") + " — "
              + ", ".join(d.get("logo") or f'"{d["text"]}"' for d in discs),
              file=sys.stderr)
    elif discs and cover.get("media") and \
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

    # GATE B — editor-in-chief final review (owner order Aug 4): the finished
    # product (hook + slides + the ACTUAL cover image) judged against
    # doctrine.md minutes before publish. REJECT drives one surgical text
    # repair (structural fields never touched — only headline/body/kicker/
    # caption merge back); a post that still fails exits nonzero and the
    # workflow ladder's next rung fills the slot (always-post intact).
    import editor
    cm = post["slides"][0].get("media")
    ok, reasons = editor.gate_b(post, os.path.join(HERE, cm) if cm else None)
    if not ok:
        fixed = qa_repair(post, ["editor reject: " + r for r in reasons])
        if fixed and len(fixed.get("slides", [])) == len(post["slides"]):
            for s_old, s_new in zip(post["slides"], fixed["slides"]):
                for k in ("headline", "body", "kicker"):
                    if s_new.get(k):
                        s_old[k] = s_new[k]
            if fixed.get("caption"):
                post["caption"] = fixed["caption"]
            scrub_dashes(post)
            ok, reasons = editor.gate_b(post, os.path.join(HERE, cm) if cm else None)
        if not ok:
            raise SystemExit("editor gate B rejected the post after repair: "
                             + "; ".join(reasons))

    json.dump(post, open(os.path.join(post_dir, "post.json"), "w"), indent=1)
    subprocess.run([sys.executable, os.path.join(HERE, "render.py"),
                    os.path.join(post_dir, "post.json"), post_dir], check=True)
    print("post ready:", post_dir)
    return post_dir


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "stories.json"))
