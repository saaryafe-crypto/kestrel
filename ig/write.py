#!/usr/bin/env python3
"""Writer agent: turns the top story in stories.json into a daily_item post.
Usage: python3 write.py [stories.json]
Picks the best direct-link story (prefers one with a press image), fetches the
article text, asks Claude for the post JSON (daily_item container spec), runs
the QA gate, then renders slides into posts/<date>-<slug>/.
Uses the anthropic SDK if ANTHROPIC_API_KEY is set, else falls back to
`claude -p` (Claude Code CLI) so it's testable with zero keys."""
import json, os, re, subprocess, sys, threading, time
from datetime import date, datetime, timedelta

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
                    # "break" was missing from this enum while the prompt
                    # mandated it — structured output silently forbade the
                    # break slide on the API path (latent bug, fixed Sep 5)
                    "layout": {"type": "string",
                               "enum": ["card", "break", "tweet"]},
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


# parallel slide workers (Aug 12) may ask for the SAME slug at once — the
# cached svg/html/png files are shared, so the fetch+raster is serialized
_LOGO_LOCK = threading.Lock()


def logo_ref(slug):
    """Real logo SVG -> raster reference for the generator (owner Aug 1
    courtroom verdict: the model's from-memory 'pink OpenAI flower' reads
    instantly fake — the EXACT mark must ride along as a reference image,
    same doctrine as faces and products). Rendered on black in the brand's
    OFFICIAL color (owner Aug 4) — white for black-mark brands. Cached."""
    with _LOGO_LOCK:
        return _logo_ref(slug)


def _logo_ref(slug):
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


def _image_brightness(path):
    """Return mean pixel brightness 0-255.  Falls back to -1 if Pillow is
    unavailable so the gate is skipped, never blocking."""
    try:
        from PIL import Image
        img = Image.open(path).convert("L")  # greyscale
        pixels = list(img.getdata())
        return sum(pixels) / len(pixels) if pixels else -1
    except Exception:
        return -1


def _brighten(path, floor):
    """Lift a too-dark generated image IN PLACE (free) before rejecting it —
    a brightness reject costs a whole $0.04 regeneration (Sep 1 post-mortem:
    QA retries burned the cover budget mid-day and posts shipped pictureless).
    Autocontrast + a capped brightness lift; the cap (1.8x) keeps a genuinely
    black-void image failing the gate so a regen still happens when deserved.
    Returns the new mean brightness (or -1)."""
    try:
        from PIL import Image, ImageEnhance, ImageOps
        img = Image.open(path).convert("RGB")
        img = ImageOps.autocontrast(img, cutoff=1)
        grey = img.convert("L").getdata()
        mean = sum(grey) / len(grey)
        if 0 < mean < floor:
            img = ImageEnhance.Brightness(img).enhance(min((floor + 8) / mean, 1.8))
        img.save(path, "JPEG", quality=92)
        return _image_brightness(path)
    except Exception:
        return -1


def image_score(path, headline, generated=False, person=False, cover=False,
                collage=False):
    """Vision judge for slide images. Returns (usable, score 0-10, flaw).
    usable = publish as-is; the score ranks sibling attempts (owner rule
    Jul 29: never generate forever — cap the spend and take the BEST of what
    exists, a slot never ships imageless); the flaw feeds the brief rewrite.
    Judged at phone-feed size: a flaw nobody can see at that size is not a
    flaw (Circle K post-mortem: strong covers died for tiny garbled UI
    pixels while the post shipped with NO image — the rubric punished the
    best option). Fails closed: (False, 0, "")."""
    # BRIGHTNESS GATE (owner Aug 22 root-cause: 80% of covers shipped with
    # mean brightness < 80/255 — the vision judge was rubber-stamping them).
    # A cover whose average pixel is below 80 is too dark to stop a scroll;
    # the brief must be rewritten brighter.  Inner slides get a softer floor.
    if generated:
        # collage covers (Sep 4-5 brutal format) run dark saturated backdrops
        # behind a bright cutout subject — the reference page's Bernie cover
        # meters ~77 and a black-palette Nvidia comparison ~64; "red and
        # black" is a legal palette in the archetype vocabulary. Mean
        # brightness is the wrong murk metric for collages; keep a low floor
        # so only genuinely void-black failures die here (the collage judge
        # separately fails unreadable props).
        floor = 55 if collage and cover else 80 if cover else 60
        brightness = _image_brightness(path)
        if 0 <= brightness < floor:
            # free salvage first — only images that stay dark after a real
            # lift are void enough to deserve a paid regeneration
            lifted = _brighten(path, floor)
            if lifted >= floor:
                print(f"genimg brightness gate: {brightness:.0f}/255 lifted to "
                      f"{lifted:.0f} in place — no regen", file=sys.stderr)
            brightness = lifted
        if 0 <= brightness < floor:
            print(f"genimg brightness gate: {brightness:.0f}/255 < {floor} — auto-reject",
                  file=sys.stderr)
            return False, 1, f"too dark (brightness {brightness:.0f}/255, need {floor}+)"
    clean = re.sub(r"</?em>", "", headline)
    # BRUTAL COLLAGE MODE (owner order Sep 4, measured from the reference
    # page's Bernie cover): news covers are graded breaking-news COLLAGES —
    # real-photo cutout subject over oversized symbolic props. The photograph
    # gate would kill exactly that format ("not a photo of a real place"), so
    # collage covers swap it for a photoreal-elements gate; the real-world
    # gate (anti-floating-symbols) is likewise the format now and drops.
    photo_gate = (
        'COLLAGE GATE (owner order Sep 4-5, FIRST CHECK — news covers are breaking-news COLLAGES built like the biggest viral tech pages: a cutout subject or hero object over oversized props with a heavy saturated grade; the archetype varies — person+symbols, CEO+giant logo+product, side-by-side comparison, evidence scene with a circular inset, symbolic object drama): the frame being a COMPOSED collage with props floating behind the subject is CORRECT — never fail it for being a composite or non-literal. Small boxed LABEL chips of 1-3 words (comparison side names, a name chip, a data chip) and ONE circular inset bubble with a white arrow are house style and CORRECT — never fail them as "added text" or "collage clutter" IF crisp and correctly spelled; garbled, misspelled or invented words = usable:false, flaw "garbled label text". What else DOES fail: any element drawn as cartoon, anime, illustration, 3D render or concept art instead of photorealistic = usable:false, flaw "cartoon element, not photoreal"; a waxy AI-invented likeness sold as a real person = usable:false; props too small, cluttered or ambiguous to read at phone-thumbnail size = usable:false. Grade the collage on: crisp cutout edges, ONE dominant subject (a briefed side-by-side comparison counts as one subject), 2-3 oversized props each readable in half a second, very high saturation and contrast. '
        if collage else
        'PHOTOGRAPH GATE (owner order Sep 3, FIRST CHECK, GENERATED images only — an illustrated knight and a cartoon game-world background both shipped in one day and the owner called them "the baddest quality ever"): this page publishes PHOTOGRAPHS. If the frame — outside the display of a real screen shown inside the scene — reads as illustration, cartoon, anime, 3D game render, concept art, or a fantasy/digital world instead of a photograph of a real physical place, it is usable:false, score 1-2, flaw "illustration, not a photograph". No concept, no composition, and no brand mark can save a non-photograph. ')
    face_gate = (
        photo_gate +
        'FACE GATE (owner rule Aug 1, GENERATED images only — unfamiliar AI faces convert badly): if a human face is prominent, it must read as a RECOGNIZABLE famous person; a generic invented face nobody would recognize = usable:false, flaw "unfamiliar generated face". Faceless people (from behind, silhouette, hands) are fine. '
        'CAST TRUTH GATE (owner post-mortem Aug 10, the Sam Altman content-vendor cover): if the prominent face IS a recognizable famous person but that person has NO role in this exact headline\'s story — their company or product is not what the headline is about, they are decoration on a generic topic = usable:false, flaw "famous face unrelated to the story". EXCEPTION 1: on an inspirational or entrepreneurial claim, a famous founder shown in their KNOWN iconic moment that embodies the headline (young Zuckerberg coding in a dorm for a build-from-nothing promise) IS connected and passes. EXCEPTION 2 — THE VENDOR CAST (owner references Aug 12, the page\'s signature move): on a guide/how-to about using a famous tool, that tool vendor\'s famous CEO shown AS THE TOOL\'S OWN USER — mid-doing the guide\'s exact action with its real prop (Dario Amodei holding his own resume for a Claude-resume guide, Sundar Pichai showering Gemini sparks for a free-Gemini story) — IS connected and passes; grade it on shock and craft, not on the cast. '
        'CLICK GATE (owner order Aug 3, GENERATED images only — a retry is cheap, wallpaper is not): the image alone must make a scroller feel they NEED to know what is happening — a caught moment, visible tension, peak emotion. A calm, posed, or neutral scene that raises no question = usable:false, flaw "no pull, nothing happening". '
        'BACKGROUND THUMB TEST (owner Aug 3, GENERATED images only): mentally cover the main subject with a thumb — the background alone should still hint what the story is about (its world, its stakes). A background that is an empty void, generic decoration, or a world that belongs to a DIFFERENT story than the headline = subtract points and name it as the flaw. '
        + ('' if collage else 'REAL WORLD GATE (owner Aug 3, the Mario emoji-wall cover): the scene must be a plausible photographic world. A background built from floating emoji, cartoon icons, logos, or symbol wallpaper reads as cheap AI slop = usable:false, flaw "cartoon prop background". ')
        +
        'MISREAD GATE (owner audit Aug 10, the coffin cover that read as leather violin cases): describe to yourself what each key prop ACTUALLY looks like at phone size, not what it was meant to be — if the scene\'s central symbolic object would be mistaken for something mundane, the concept FAILED on screen = usable:false, flaw names the misread ("coffins read as luggage"). A symbol only counts when it is UNMISTAKABLE in half a second. '
        'STOCK-WALLPAPER GATE (owner Aug 10, the falling-money laptop cover): if the image could be sold as a generic stock photo for its topic — cash raining on a desk, anonymous hands typing, a glowing brain, abstract chart art — it stops nobody = usable:false, flaw "stock wallpaper". '
        'CROP-SURVIVAL GATE (owner Aug 14 — published slides looked "cut in the middle"): the slide displays roughly the TOP SQUARE of this image and fades its bottom fifth into black under the text. Mentally hide the bottom quarter: if the scene still reads complete — faces, key prop and stakes all live in the upper two-thirds — it passes. If anything essential sits in the bottom quarter, or the composition is a full-body/tall scene that needs its lower half to make sense = usable:false, flaw "composed too tall, dies in the crop". '
        if generated else "")
    try:
        r = call_claude(
            f'An AI-generated image is attached (if not attached to this message, use your Read tool on {path} to look at it). It would fill the photo band of an Instagram news slide with this headline: "{clean}". Judge it AT PHONE FEED SIZE — a flaw a follower cannot see at that size does not count against it. '
            'SCORE against the scroll-stopper formula (each worth points): ONE dominant focal subject, brightest and sharpest thing in frame (no competing focal points); the image dramatizes THIS exact headline claim — moment, stakes or consequence visible in half a second (not generic topical art), and a deliberately STAGED SYMBOLIC scene that transmits the story\'s outcome in one look (a funeral for a discontinued product, a knockout between two brands, a famous logo cast in the story\'s role) COUNTS as dramatizing the claim — judge it on whether a stranger gets the story, not on literalness. BUT (owner law Aug 10): a correct concept earns ZERO points by itself — you are grading the RENDERED PICTURE, and the bar is SHOCK FACTOR: put this next to the best viral tech pages\' covers and ask if a stranger would physically stop scrolling; a clever idea rendered as a quiet, dark, or ambiguous scene is a FAILURE;THE PULL — the image alone makes you need to know what is happening (a caught moment, visible tension, peak emotion beats any calm posed scene); bright saturated colors with one punchy accent (not murky, not pastel, not white-dominant); if a person is central, the face is large and radiates one clear strong emotion; looks like a real press photo (texture, grain, candid light), not plastic AI art. '
            + face_gate +
            'Score 0-10: 10 = a professional photo editor would run it AND it nails the formula; 7 = publishable; 4 = clearly flawed but recognizable and on-claim; 0 = unusable garbage. usable:true means publish as-is — set false for flaws a scrolling follower would actually notice: garbled text large enough to read, warped hands/faces, obvious AI plastic look, watermark, no connection to the claim, a dark/murky frame with no focal subject, or a SCREENSHOT of an app or social-media post (baked-in meme captions, interface elements like hearts, like counts, usernames, buttons — a screenshot is someone else\'s content and never our cover). flaw: the single biggest problem in 12 words or less (empty string if none). Return ONLY JSON: {{"usable": true/false, "score": 0-10, "flaw": "..."}}',
            # person AND cover judging runs on the WRITER model (owner audit
            # Aug 10): Haiku cannot verify famous likenesses (it called a
            # reference-level Altman render "unfamiliar generated face") and it
            # passed the coffins-as-luggage cover — it cannot make the holistic
            # "would a stranger stop scrolling" call either. Covers are 6/day ×
            # ≤2 attempts, so the upgrade costs a few vision calls exactly
            # where the image money is spent. Inner slides stay on Haiku.
            schema=IMG_QA_SCHEMA, images=[path],
            model=MODEL if (person or cover) else CHEAP)
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
- CULTURE CAST (the Zendaya move — owner reference: Zendaya cast studying for a Gemini-exam story BECAUSE The Odyssey was viral that week): cast someone from the hot list below performing the story's action. Only when the fit is instant and natural — never force a celebrity into a story that isn't theirs. SECOND LEGAL SOURCE, THE DOMAIN ICON (the Wolf of Wall Street move — owner reference Aug 12: a stocks guide covered with DiCaprio's Jordan Belfort mid-pitch on the trading floor, because stocks→Wall Street→The Wolf of Wall Street is the chain everyone's brain runs by itself): when the story's DOMAIN has ONE timeless movie/culture icon that IS its symbol in a 20-year-old's head, cast that iconic character in their signature scene, living THIS story. The test is INTUITION SPEED — say the topic and the icon must appear unprompted (stocks→Wolf of Wall Street, heists→Ocean's Eleven, genius outsider→The Social Network dorm). If the link needs explaining, it fails. A domain icon needs no current-week heat: being the domain's permanent symbol IS the fit. HARD LIMIT (owner, Aug 12): the domain icon is for TOPIC/DOMAIN posts (guides, roundups, trend pieces) with no real protagonist. A NEWS story about a named real person or company casts ITS OWN actors under cast truth — never a movie character over their story (a Leopold Aschenbrenner / Situational Awareness fund story shows Leopold or his fund's world, NEVER the Wolf of Wall Street just because funds smell like Wall Street).{culture_note}
- LOGO AS HERO (fame-bar fallback, owner Aug 9): when the story's company is world-famous but NO person clears the famous-face bar, the famous LOGO itself becomes the staged scene's HERO, cast in the story's role — GitHub repos printing money → the golden Octocat on a throne of hundred-dollar stacks. Return "logo" so the real mark rides as reference; every human in that scene is faceless or absent.
- Or the existing lanes below (the story's own absurd visual, ROLE-CAST, PRODUCT-HERO, CLASH-CAST, THE SITUATION PORTRAIT) when they are stronger. All craft rules, the fame bar, and the logo rules still apply to every lane.
CAST TRUTH (owner post-mortem Aug 10, the Sam Altman content-vendor cover — a great Altman likeness on a "people are making a week of content" story he had NOTHING to do with): a named famous face is legal ONLY when that person or their company is an ACTOR in THIS story — named in the topic or headlines, or the story is about their product or their move. "The topic is AI" is NOT a connection: never cast a famous AI face (Altman, Musk, anyone) as decoration on a story that names no company AND no tool. THE VENDOR CAST (owner's reference wall, Aug 12 — this is the page's signature move and the DEFAULT for every guide): a guide or story about USING a named famous tool IS that vendor's story, so its famous CEO is LEGAL — cast the CEO as the tool's own delighted USER, mid-performing the READER's exact action with the guide's real prop, at one peak emotion. The references: Dario Amodei proudly holding HIS OWN resume for an "upload your resume to Claude" guide; Dario in a Hawaiian shirt grinning with a discount-stamped boarding pass for a "Claude finds cheap flights" guide; Sundar Pichai leaning out of a helicopter showering glowing Gemini sparks onto a crowd of reaching hands for "Google giving Gemini Pro away free". Tool→face map: ChatGPT→Sam Altman, Claude→Dario Amodei, Gemini→Sundar Pichai, Grok→Elon Musk, Copilot→Satya Nadella, Llama→Mark Zuckerberg. A guide whose prompts run on a model named anywhere in the slides qualifies even when the headline only says "AI prompts" — cast that model's CEO. The PROP IS THE PROMISE: the reader's object (the resume, the boarding pass, the bill, the exam sheet) held large and unmistakable; the CEO's hands DO the guide's verb. CULTURE CAST is the one exception and only under its own rule: the fit must be instant and natural. THE FLIP SIDE (owner audit Aug 10, the GPT-5 birthday cover that went faceless coffins while Altman was legal): when cast truth PASSES — the story IS a famous company's own product or move and its famous CEO qualifies on the fame bar — casting that face is the DEFAULT, and going faceless instead is the exception you must be able to justify; a legal famous face at peak emotion beats any object scene. If the writer already cast a legal face, keep it in your brief (recast the scene, not the person).
A PRODUCT-EXPERIENCE STORY IS THE VENDOR'S STORY (owner verification Sep 3 — a Tesla-robotaxi rides story staged an anonymous woman in the back seat because the real rider wasn't famous, and the slot shipped a 3/10 best-reject): when the story is a non-famous person USING, riding, or testing a FAMOUS company's product, the cover does NOT stage an anonymous stand-in for them — DEIXIS LOCK yields here, because an unknown generated face is banned and a faceless nobody is weak. Instead cast that company's famous CEO as the product's own delighted user mid-doing the story's exact action (Elon Musk grinning in the back seat of his own driverless robotaxi, no one at the wheel), or go PRODUCT-HERO on the product itself. The vendor cast is the DEFAULT whenever the fame bar leaves the story's human anonymous but its product famous.
ICONIC-MOMENT EXCEPTION (owner, Aug 10): on inspirational / entrepreneurial stories, a famous founder IS legal even when the news isn't about them — IF the scene is their KNOWN iconic real moment and that moment EMBODIES the title's exact meaning: young Mark Zuckerberg coding in his dorm room for a "built it from nothing overnight" promise, garage-era Jobs and Wozniak for a two-people-and-an-idea story. The test: a stranger instantly reads WHY this person in THIS scene proves THIS title. A famous face merely signaling "AI" or "tech" still fails cast truth.
NO-FACE PLAYBOOK (owner order Aug 10 — cast truth is NOT a license for boring covers; a no-face cover goes just as big and provocative):
- LOGO AS HERO is the default: the famous mark ACTING the story at theatrical scale — the Octocat mascot raking in poker chips, a giant glowing logo craned onto (or torn off) a building, the mark painted on a boxing-ring floor under falling confetti. The logo performs the verb; it never just sits there.
- SYMBOLIC SCENE, FACELESS: the funeral / knockout / retirement party staged with faceless humans — mourners from behind, silhouettes, hands lowering the coffin. The staging and props carry the drama, no likeness needed.
- IMPOSSIBLE SCALE: the story's real object at absurd physical size in a real place — a server rack towering over a city intersection, a mountain of cash burying an office desk, a phone the size of a billboard being hauled by crane.
- CAUGHT EVIDENCE: the forbidden backstage moment with objects only — a contract mid-signature shot over a faceless shoulder, a vault door ajar with the goods glowing inside, a wall of screens mid-crash in an empty room.
Every no-face cover still passes THE STOP TEST; "objects" NEVER means a calm product shot — if the object isn't mid-action or at impossible scale, escalate the scene.

THE MISREAD TEST (owner audit Aug 10 — the "7 coffins" cover rendered as seven leather violin cases in a dark shop and nobody could tell): before writing the brief, name what each symbolic prop could be MISTAKEN for at phone size, and write the context that makes it unmistakable INTO the brief. A coffin is only a coffin at a funeral — mourners, flowers, a grave, a hearse; a trophy needs a podium; a tombstone needs a cemetery. One unmistakable symbol with its full scene beats seven ambiguous ones in a void. And prefer a human REACTING in frame even in faceless scenes (a silhouetted mourner, hands gripping the coffin edge) — emotion is what stops thumbs; empty object arrangements read as furniture catalogs.

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

COVER OUTPUT — THE COVER ARCHETYPES (owner order Sep 4-5, measured across THIRTY reference covers, not one: the page does NOT run a single image formula — it picks the picture by asking WHAT WOULD PROVE THIS HEADLINE IN HALF A SECOND, then builds that proof as a saturated composite. The picture is always the story's PROOF or its CONSEQUENCE staged — never decoration): the COVER brief is NOT freeform prose. The generator holds a frozen craft scaffold; your cover brief fills slots. FIRST pick the archetype by story type, THEN fill the slots. The frozen slot form:
SUBJECT: <who/what fills the frame>, <one peak emotion or state in 1-3 words>. BACKDROP PROPS: <prop 1>, <prop 2>[, <prop 3>]. PALETTE: <color 1> and <color 2>.[ LABELS: "<1-3 words>" on <target>[, ...].][ INSET: circular bubble of <one concrete detail>.]
THE ARCHETYPES — story type decides, this order of questions:
A) POLICY/BAN/THREAT by a famous actor (a senator bans AI, a city bans X in schools) → the person mid-action + the ban made physical. SUBJECT: the actor. BACKDROP PROPS: a giant red prohibition circle over the banned thing, plus one consequence prop (steel bars, gavel, the affected crowd as a small inset). WHY: the reader must see the power AND the thing being killed in one frame. Reference: NYC schools ban = official at podium + red circle over "AI" + circular inset of students.
B) COMPANY/PRODUCT story with a famous CEO, or a BUILDER story → the vendor cast: the person WITH their creation's world. SUBJECT: the CEO/builder (holding or presenting the real product when the story is the product). BACKDROP PROPS: the brand's giant glossy dimensional logo + the real product(s) oversized. WHY: face = trust + recognition, giant logo = instant brand read, product = the news itself. References: Cook holding AirPods under a chrome Apple mark; Pichai in front of a giant Gmail M with the real UI behind; the Flappy Bird creator inside his own game world with a LABELS name chip.
C) HUMAN MOMENT (resignation, farewell, tears, a person's turning point) → NO props, NO symbols: the person's single most emotional real-photo moment fills the frame. SUBJECT: the person at the exact emotion. BACKDROP PROPS: only their brand's mark, ghosted dim. WHY: when the story IS a feeling, any added prop dilutes it. Reference: Tim Cook wiping his eye on his last day — nothing else in frame.
D) PRODUCT HERO (a launch where the product is the shock and no person is needed) → SUBJECT: the product at giant scale in its real world (set "ref" so the real product photo rides). BACKDROP PROPS: its environment + at most one symbol. WHY: a jaw-dropping object needs zero staging. Reference: the Cybercab with doors up on a real street.
E) LABELED COMPARISON / VS (benchmark, A vs B, before/after, leak vs release) → staging depends on WHAT is compared. DIGITAL content (game graphics, video output, app results): the content itself fills the ENTIRE frame edge-to-edge as a split — top/bottom or left/right halves of the same scene at the two quality levels, a thin dividing line, NO monitors, NO desk, NO room around it (reference: the DLSS covers are pure game imagery corner to corner). PHYSICAL products (phones, consoles, cars): the 2-3 real objects themselves huge, same size and angle, a flaming or electric VS mark between them. Either way LABELS: one 1-3 word boxed chip naming each side ("DLSS 5 Off"/"DLSS 5 On", "ORIGINAL"), arrow chips when before→after. WHY: the labels do the arguing — the eye plays spot-the-difference before reading. This is the ONE archetype where LABELS are mandatory. Make the difference VIOLENT — the weak side visibly broken/blurry, the strong side startling; a polite comparison is wallpaper.
F) EVIDENCE / CAUGHT-ON-CAMERA (a real place did X, a photographer caught Y) → SUBJECT: the real evidence scene itself, as documentary as possible. INSET: one circular bubble with the secondary proof (the flag, the photographer, the app screen) + a thin white arrow. WHY: "this actually happened" is the whole sell — staging would break it.
G) FACELESS SYMBOLIC DRAMA (abstract or scary claim, fame bar fails, no product to show) → SUBJECT: the story's hero object mid-drama at giant scale (a Bitcoin coin cracking open in flames). BACKDROP PROPS: may include ONE number-prop making the headline's number physical (a digital clock reading "09:00" for a 9-minute claim). WHY: no face, no product — so the metaphor must be violent enough to carry alone.
SLOT RULES (all archetypes):
- Name every prop concretely and physically ("a giant glowing red prohibition circle over a blue AI microchip", never "symbols of regulation"). 2-3 props max, each oversized to read at phone-thumbnail size.
- PALETTE by the story's emotion: threat/ban → red and deep blue; money → green and gold; win/launch → orange and white; crash/scandal → red and black. Two colors, no more.
- LABELS are legal on covers ONLY as briefed chips: 1-3 words each, max 3 chips, quoted exactly in the brief (comparison sides, a builder's name chip, one data chip like "$5 MILLION"). Never a sentence, never decorative text — the headline system carries all other words.
- INSET: at most one, circular, in an upper corner, one concrete detail a thumb can read.
- Still return "face" and "logo" fields on the cover exactly as the rules below describe — the real photo and real mark ride as references.
FORMAT — every INNER-SLIDE and CTA prompt contains these five parts in order (20-45 words total; the cover uses the archetype slot form above instead):
1. HERO: ONE focal subject, concretely named (the real device/brand/person from the headline — or the CLASH-CAST pair as one unit), frozen at the peak of the exact moment — mid-fall, mid-launch, mid-signature. One focal point only; it is the brightest, sharpest thing in frame.
2. EMOTION — when the story's person is FAMOUS, the hero IS that person's recognizable likeness at 40%+ of frame height, named explicitly, eyes to camera or locked on the story's object, radiating ONE nameable exaggerated emotion (shock, awe, dread, triumph). Name the emotion in the prompt. FAMOUS FACES ONLY (owner rule Aug 1: generated unfamiliar faces = low conversion, no good outcome): if the story's person is not famous enough for a viewer to recognize, NEVER generate a face — show them from behind, as a silhouette, hands-and-props only, or cut them out of frame entirely and let the objects and stakes carry the drama.
3. STAKES IN FRAME: make the money/scale/damage physically visible — the pile of cash, the wreckage, the crowd, the giant object beside a person for scale. Stakes a viewer can read in half a second. DATA MADE PHYSICAL (18-slide reference audit Sep 5, the gold-record slide: real gold bars stacked huge under a wall of glowing golden candlestick charts — object and data ONE scene): when the slide's claim IS a number or a market move and no person carries it, the environment ITSELF is the data — the chart as a glowing physical wall behind the story's real object, the palette pulled from the object (gold on gold, red on crashing red). Never a floating graph, never a screenshot of a chart.
4. WORLD: the background is the story's real world (the factory floor, the launchpad, the brand's storefront) carrying context — softer and simpler than the hero, but COLORFUL AND WELL-LIT (the background must read as vibrant and alive, never dim or murky). Never an empty void, never white, never dark.
5. ACCENT: end with ONE saturated accent color pulled from the subject, set against a rich complementary surround ("accent: signal red against vivid cobalt blue"). Warm saturated accents stop scrolls; whole-frame murk, dim surrounds, and pastels do not.

CRAFT (bake into every prompt):
- Real press photograph, never digital art: include "documentary news photo, 35mm, harsh on-camera flash, natural skin texture, slight film grain". This is the #1 lever that keeps generated images from looking like cheap AI.
- PHYSICAL WORLD LAW (owner order Sep 3 — two shipped covers broke it in one day: a "colossal 3D game world floating mid-air" behind Sundar Pichai rendered the whole frame as a cartoon, and a "cinematic game still" armored warrior shipped as pure illustration; his verdict: "the baddest quality ever... doesn't look even realistic"): EVERY square inch of the frame is the real, physical, photographable world — a real room, street, stage, classroom, funeral home, office. Anything DIGITAL in the story (a game, an app, a video, a website, an AI output) may appear ONLY on the real screen of a real device inside the scene, or as a real physical prop (a printed poster, a figurine on the desk) — never floating in the air, never "conjured", never filling the background, never AS the scene. BANNED words in any brief: "game still", "game world", "render", "rendered", "illustration", "concept art", "anime", "fantasy", "3D world", "floats mid-air". The owner's 8 reference covers are the spec: a funeral, a classroom, a helicopter, a trading floor — real places, real props, real light, and the wit lives in WHAT the famous person is doing there, not in impossible physics. If the story is about a digital thing, a real famous person REACTS to it on a real screen — the human action carries the story.
- ZERO readable words anywhere in frame (measured on our own runs: the model garbles every rendered sentence — 5 of 6 images died to this one flaw). Screens, signs and papers speak in SYMBOLS ONLY, named concretely: "a giant red $ symbol", "a warning triangle", "a crashing red chart line". COVER-ONLY EXCEPTION (owner references Aug 12 — the "RIP CLAUDE" coffin plaque, the red DISCOUNTED stamp on the boarding pass): covers render on a model that writes short text cleanly, so ONE prop on the COVER may carry ONE bold text element of 1-3 words when that text IS the story's punchline — quote it exactly in the brief ('a wooden plaque engraved "RIP CLAUDE"'). One element max, never a sentence, never on inner slides; QA still kills it if it garbles.
- GAZE IS AN ARROW (Netflix artwork research + fixation studies): the hero's eyes go to camera by default, or lock onto the story's object so the viewer's eye follows. MAX 2 people visible in frame — engagement measurably drops at 3+.
- THE BRAND LIVES IN THE SCENE: when the story's company matters to the frame, its real logo appears as a physical object — the default treatment (owner's reference, Aug 1): a LARGE GLOWING backlit mark on the colorful, saturated wall behind the hero, soft warm-white halo, dimensional like a lit acrylic sign. Alternatives: the mark ON the device, a storefront sign, an illuminated screen with visible glow. NEVER a flat printed graphic, never drawn from memory — return "logo" so the real mark rides as a reference. The renderer will NOT stamp a flat logo overlay on generated covers, so if the brand isn't in the scene it isn't on the cover.
- EVERY IMAGE UNIQUE + A CURIOSITY ENGINE (owner Aug 1): no two slides in the post may share a composition, angle, or setting — each image is its own scene. IMAGE-CLAIM LOCK (the Reddit post-mortem: slide 2 claimed a 23% stock crash yet showed the same phone-with-logo as the cover): each inner brief's HERO is that slide's OWN claim — the crash slide gets the collapsing red chart line, the payout slide the money, the fallout slide the next victim — never the story's mascot object repeated. And each image is built on viewer psychology: it shows a moment that RAISES a question only the headline (or the next slide) answers — an unresolved instant, a reaction to something just out of frame, stakes mid-collapse. If an image would feel complete without its headline, it's wallpaper — rewrite it.
- FRAME LAW (owner Aug 14 — "the best pages design the picture FOR the top half; ours look cut in the middle"): the image fills a roughly SQUARE window at the TOP of the slide, and the window's bottom fifth feathers into black under the headline. Compose the scene to read COMPLETE inside that window: subjects WAIST-UP or tighter, faces and the key prop in the UPPER two-thirds, stakes readable without the bottom quarter, nothing essential touching the side edges. NEVER stage full-body figures, tall vertical scenes, or anything that needs legs, feet, or a floor to make sense — if it does, re-stage it tighter (say "waist-up", "close on hands and prop", "tight three-quarter shot"). The finished slide must look like the photo was SHOT for that window, never cropped into it. STAGE IT AS A COMPOSITE (measured from every reference cover, Aug 14 — Elon chest-up + giant Tesla logo disc + memo icon; the MacBook floating over huge "PRO" letters): ONE complete subject — the whole device, the whole prop, the person waist-up — arranged with 1-2 supporting elements (the brand's glowing mark, one story icon) on a COLORFUL, SATURATED backdrop that fades toward the bottom edge; nothing amputated by any edge. A complete object on a vivid backdrop reads designed; a cropped photo reads broken.
- BANNED looks: purple-teal "AI glow", glowing holograms, circuit-board brains, waxy plastic skin, sci-fi concept art, moody dark murk, dark/dim/shadowy backgrounds, night scenes unless the story is literally about nighttime, white backgrounds, two competing focal points, two emotions. If the brief uses words like "dark", "dim", "shadowy", "night", "vault", "murky", or "tungsten" to describe the background or lighting, REWRITE IT BRIGHTER.
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


def recent_posts(n=60, reels=True):
    """Headlines of the last n published posts, derived from posts/ folder
    names (no separate state file to drift). Reel folder names carry video
    ids, not headlines, so reel titles come from reels-used.json instead
    (owner Aug 16, "make sure also we never repost the same thing": a
    carousel duping last week's reel is still a repost — every lane's dupe
    judge must see the other lane's stories). reels=False lets reel.py
    fetch just the carousel side without echoing its own list back.
    HARD RULE hardening (owner Sep 5, "we dont post the same things twice.
    never."): memory extended 30->60 posts and reels 14->30 days, and recap
    SLIDE headlines are included — a recap folder is just 'ai recap', so
    without this the stories inside recaps were invisible to every lane's
    dupe judge."""
    posts = os.path.join(HERE, "posts")
    if not os.path.isdir(posts):
        return []
    dirs = sorted(d for d in os.listdir(posts)
                  if re.match(r"\d{4}-\d{2}-\d{2}-", d) and "-reel-" not in d)
    out = [re.sub(r"^\d{4}-\d{2}-\d{2}-", "", d).replace("-", " ").strip()
           for d in dirs[-n:]]
    for d in dirs[-n:]:
        if "ai-recap" not in d:
            continue
        try:
            rp = json.load(open(os.path.join(posts, d, "post.json")))
            for s in rp.get("slides", [])[1:-1]:  # skip cover + CTA
                h = re.sub(r"<[^>]+>", "", s.get("headline", "")).strip()
                if h:
                    out.append(f"(recap slide) {h[:90]}")
        except Exception:
            pass
    if reels:
        try:
            ru = json.load(open(os.path.join(HERE, "reels-used.json")))
            horizon = str(date.today() - timedelta(days=30))
            out += [f"(reel) {u['title'][:90]}" for u in ru
                    if u.get("date", "") >= horizon
                    and u.get("title", "").strip()
                    and not u["title"].startswith("http")]
        except Exception:
            pass
    return out


DUPE_SCHEMA = {"type": "object", "properties": {"dupe": {"type": "boolean"}},
               "required": ["dupe"]}


def _dupe_fallback(title, recent):
    """Mechanical dupe check for when the semantic judge is down (owner
    Sep 5 hard rule: a dead judge must never wave stories through). Two
    titles sharing 3+ meaningful words (4+ chars) are treated as the same
    story. Crude on purpose — false positives just skip one candidate,
    false negatives are what the hard rule forbids."""
    words = {w for w in re.findall(r"[a-z]{4,}", title.lower())}
    for t in recent:
        if len(words & {w for w in re.findall(r"[a-z]{4,}", t.lower())}) >= 3:
            return True
    return False


def is_dupe(title, recent=None):
    """Semantic dedupe — the same story worded differently is still the same
    story (Jul 28: the Threads/Meta-AI news published twice 2h apart because
    two feeds worded it differently and the slug check passed both). If the
    judge call breaks, falls back to the mechanical word-overlap check —
    never fails open (owner Sep 5: 'we dont post the same things twice.
    never.')."""
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
        fb = _dupe_fallback(title, recent)
        print(f"dupe judge failed ({e}) — mechanical fallback says "
              f"{'DUPE' if fb else 'clear'}", file=sys.stderr)
        return fb


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
    # GATE A — editor-in-chief (owner order Aug 4, Queen/Mario post-mortem):
    # the ranker only answers "best of this pool"; the editor owns "worth
    # posting at ALL" against doctrine.md. KILL is binding — the next
    # candidate competes, the slot never dies (always-post intact).
    import editor
    from concurrent.futures import ThreadPoolExecutor

    def _judge(s):
        """3-state verdict (Aug 27): 'dupe' is a hard ban (owner ground rule
        Aug 14 — never the same story twice), 'kill' is a Gate A taste call
        that STORY_RELAX may override."""
        if is_dupe(s["title"], recent):
            print(f"semantic dupe of a published post — skipping: {s['title']}",
                  file=sys.stderr)
            return "dupe"
        ok = editor.gate_a(s, (s.get("radar") or {}).get("selftext", ""))[0]
        return "ok" if ok else "kill"

    # exhaust EVERY candidate before declaring the slot dead (owner rule:
    # every slot must fill — a 3-try cap killed the Jul 28 test run when the
    # top 3 were all dupes while story #4 was fine). Candidates are judged in
    # PARALLEL batches of 4 (run diet Aug 12: the Aug 11 23:00 run burned ~8
    # min on ten sequential KILLs before falling to edu). The batch is scanned
    # in viral-rank order, so the pick is identical to the sequential walk;
    # the only cost is up to 3 wasted Haiku judgments when an early candidate
    # in a batch approves — cents next to the minutes saved.
    relax = []  # Gate-A kills in viral order, dupes excluded
    while fresh:
        batch = fresh[:4]
        with ThreadPoolExecutor(max_workers=len(batch)) as ex:
            verdicts = list(ex.map(_judge, batch))
        for s, v in zip(batch, verdicts):
            if v == "ok":
                return s
            if v == "kill" and not s.get("evergreen"):
                # goats-on-Etna hardening (owner Aug 28): the relax rung
                # exists to rescue NEWS narratives from a too-strict gate A —
                # never to force back an evergreen wow-fact the editor killed
                # as off-lens. Evergreen monsters out-viral news by design,
                # so relax.append here would make the off-lens kill decorative.
                relax.append(s)
        fresh = fresh[len(batch):]
    # STORY_RELAX rung (owner audit Aug 27): every story slot since Aug 13
    # died right here and fell to the edu listicle floor — 71/71 carousels
    # were listicles, the exact repetition the owner flagged. On the relaxed
    # rung (ladder step 2 in ig-post.yml) the most viral NON-DUPE story runs
    # even if Gate A was lukewarm: a real news narrative beats yet another
    # listicle. Dupes stay banned, and Gate B still reviews the finished
    # post — the quality floor holds.
    if os.environ.get("STORY_RELAX") and relax:
        s = relax[0]
        s["gate_a_relaxed"] = True
        print(f"STORY_RELAX: overriding gate A kill for most viral non-dupe "
              f"story: {s['title']}", file=sys.stderr)
        return s
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
    compound-word hyphens (first-sale, AI-written) are untouched.
    Uses [^\\S\\n] (horizontal whitespace only) so newlines around dashes
    are never collapsed."""
    if not isinstance(t, str):
        return t
    t = re.sub(r"[^\S\n]*[—–][^\S\n]*", ", ", t)
    t = re.sub(r"(?<=\w) - (?=\w)", ", ", t)
    return re.sub(r",\s*,", ",", t)


def fix_numbered_lines(t):
    """Ensure numbered list items (1. / 2. / 1) / 2)) each start on their
    own line.  Only fires when the text contains what looks like a sequential
    numbered list (both '1.' and '2.' present).  Replaces inline spaces
    before a numbered item with a newline; already-correct text passes
    through unchanged."""
    if not isinstance(t, str):
        return t
    # Guard: only act when the text contains a numbered sequence
    if not re.search(r"1[.)]\s.*2[.)]\s", t, re.S):
        return t
    # Replace horizontal whitespace before a numbered item with \n
    return re.sub(r"[ \t]+(\d{1,2}[.)]\s)", r"\n\1", t)


def no_markdown(text, html=True):
    """Writers sometimes emit markdown bold despite the <em>/<b> instruction
    (Sep 6 recap: literal **Elon Musk** shipped on 5 slides — Gate R caught
    it but retext is not auto-applied, so the mechanical scrub must kill it
    before render). Slides speak HTML: convert to <b>. Captions and comments
    are plain text: strip the markers."""
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>" if html else r"\1", text)


def scrub_dashes(post):
    """Applies no_dashes, no_markdown and fix_numbered_lines to every field
    that reaches the published slides or caption.  Records (story title,
    tournament candidates) stay untouched."""
    for s in post.get("slides", []):
        for k in ("headline", "body", "kicker"):
            if s.get(k):
                s[k] = no_dashes(s[k])
                s[k] = no_markdown(s[k])
                s[k] = fix_numbered_lines(s[k])
    if post.get("caption"):
        post["caption"] = no_dashes(post["caption"])
        post["caption"] = no_markdown(post["caption"], html=False)
        post["caption"] = fix_numbered_lines(post["caption"])
    if post.get("pinned_comment"):
        post["pinned_comment"] = no_dashes(post["pinned_comment"])
        post["pinned_comment"] = no_markdown(post["pinned_comment"], html=False)
        post["pinned_comment"] = fix_numbered_lines(post["pinned_comment"])
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


# slides generate in parallel threads (run-time diet Aug 12): the rotation
# ledger's read-modify-write must be atomic or concurrent picks lose entries
_FACES_LOCK = threading.Lock()


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
    with _FACES_LOCK:
        try:
            used = json.load(open(ledger))
        except Exception:
            used = {}
        pick = min(cands, key=lambda c: used.get(os.path.basename(c), ""))
        # full timestamp, not the day (Aug 12: two same-day posts tied on the
        # date and both got sam-altman.jpg) — old date-only entries sort fine
        used[os.path.basename(pick)] = datetime.now().isoformat()
        json.dump(used, open(ledger, "w"), indent=1)
    return os.path.relpath(pick, HERE)


def fetch_face(name):
    """Wikipedia portrait fetcher (Sep 4 Bernie post-mortem: 'Bernie Sanders'
    wasn't in the faces/ pool — all 21 photos are tech CEOs — so the cover
    fell to a dead no-ref rung and nano DREW Bernie from memory: the waxy
    fake that started the whole @technology comparison). Any famous person
    the art director casts now gets their REAL photo from their Wikipedia
    page image (public figures' lead portraits are freely licensed), cached
    into faces/<slug>.jpg so pick_face finds it forever after. Identity must
    come from a real photograph or not at all: any failure here -> None and
    the caller goes FACELESS — never a memory-drawn face. Requires Pillow
    (the raw download is normalized to JPEG); no Pillow -> None."""
    slug = re.sub(r"[^a-z0-9-]", "", name.lower().strip().replace(" ", "-"))
    if not slug:
        return None
    dest = os.path.join(HERE, "faces", f"{slug}.jpg")
    if os.path.exists(dest):
        return os.path.relpath(dest, HERE)
    try:
        import io
        import urllib.parse
        import urllib.request
        from PIL import Image
        hdrs = {"User-Agent": "kestrel-ig/1.0 (cover reference fetcher)"}
        url = ("https://en.wikipedia.org/api/rest_v1/page/summary/"
               + urllib.parse.quote(name.strip().replace(" ", "_")))
        with urllib.request.urlopen(urllib.request.Request(url, headers=hdrs),
                                    timeout=20) as r:
            data = json.loads(r.read())
        src = (data.get("originalimage") or data.get("thumbnail") or {}).get("source")
        # disambiguation/redirect pages carry no trustworthy portrait
        if not src or data.get("type") != "standard":
            print(f"face fetch: no Wikipedia portrait for {name}", file=sys.stderr)
            return None
        with urllib.request.urlopen(urllib.request.Request(src, headers=hdrs),
                                    timeout=30) as r:
            raw = r.read()
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        img.thumbnail((1600, 1600))
        tmp = dest + ".tmp"
        img.save(tmp, "JPEG", quality=90)
        os.replace(tmp, dest)  # atomic — parallel slides may fetch the same name
        print(f"face fetch: Wikipedia portrait for {name} -> faces/{slug}.jpg",
              file=sys.stderr)
        return os.path.relpath(dest, HERE)
    except Exception as e:
        print(f"face fetch failed for {name} ({e}) — going faceless",
              file=sys.stderr)
        return None


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
        # pool first, then the Wikipedia fetcher (Sep 4 Bernie fix: the pool
        # is all tech CEOs — any other famous cast used to lose their photo
        # here and ship scrubbed to "a person" or a memory-drawn face)
        fp = pick_face(nm.lower().replace(" ", "-")) or fetch_face(nm)
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
- EMOTIONAL REGISTER MATCH (18-slide reference audit Sep 5: for a death story the page ran a black-and-white portrait of the person with her keepsake — the MOOD of the photo carried the slide): the photo's emotional temperature must match the slide's claim — grief gets somber, a win gets bright, a fight gets tense. A cheerful photo under a grim claim is a WRONG photo even when the subject matches.
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
        if m.get("selftext") and "on X" in (m.get("where") or ""):
            proof += (
                "\nTHE REACTION RECEIPT (owner order Sep 5, measured on the reference "
                "page — mid-carousel it renders the story's viral post ITSELF as a real "
                "X card on a dark backdrop: proof the internet is living this story "
                "right now, and often the comedy beat): ONE mid-chain content slide "
                "(never slide 2, never the last two) MAY set \"layout\": \"tweet\" with "
                "\"headline\": \"\" and no body, no media_idx, no image_brief — the "
                "pipeline typesets the REAL source post (its exact words, handle and "
                "view count) as the whole slide; you never write the tweet text "
                "yourself. Use it ONLY when the post's own words carry punch, absurdity "
                "or comedy the retelling can't match — a dry tweet (a bare link, a "
                "plain claim) makes a wasted slide, skip it. This card is the ONE "
                "exception to the never-quote rule: the artifact renders whole, it is "
                "never retyped into a body.\n")
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
THE KICKER (forensic upgrade Aug 2 — the reference pages use the tiny strip under the headline for a SECOND hook beat, not a generic swipe prompt: "WITHOUT SONY LIFTING A FINGER", "HE DOES NOT WANT THEIR MONEY", "BUILT WITH CLAUDE CODE, OPEN SOURCE", "5 SETTINGS TO SWITCH OFF"): the cover slide MAY set "kicker": 3-7 words, TRUE facts only, carrying the story's twist, consequence or bonus promise that is NOT already worded in the headline. It renders tiny in the strip — the headline must still work with the kicker covered. The 30-cover reference audit (Sep 5) found the strip carrying a real second fact on ~90% of news covers — treat the kicker as DEFAULT-ON for news: a real story almost always has a second beat ("ONE TRIP CAME OUT 44% CHEAPER", "NEARLY 600,000 STUDENTS WILL BE AFFECTED"). Only if the story truly has no real second beat, OMIT it (the strip then says "Swipe for more") — a filler kicker is worse than none. There is NO other subline (owner rule Aug 1): every word of the main hook lives in the big headline itself.

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
- THE TWIST: one mid-carousel slide (around slide 4) is a pattern interrupt — the most contrarian or absurd TRUE fact in the story, the "wait, WHAT?" moment that re-hooks tired swipers. This is the slide that carries "layout": "break" (see THE BREAK SLIDE below) — the visual interrupt and the story interrupt land together.
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
2. type "content": THE SECOND HOOK (owner order Aug 18 — inner slides read "plain, flat and boring", this is where it starts). Slide 2 is NOT the first answer, it is a SECOND COVER: Instagram re-serves skipped carousels with slide 2 up front, so its headline must stop the scroll standalone — never "Here's how" or "The details". Its job is to RE-SELL the swipe: escalate the cover's question (the human scale, the belief that was about to break) WITHOUT spending the payoff.
3+. type "content": the rest of the chain. Each headline = a 5-9 word standalone factual CLAIM someone could disagree with — NEVER a label ("THE DETAILS", "THE REAL STORY", "WHAT THIS MEANS FOR X") and NEVER an aphorism/motivational line ("X BEATS Y"). Use physical past-tense verbs (parked, gutted, handed, escaped — never "is using", "means", "finds") and put a number in the headline whenever the story has one. Body = SPOKEN VOICE in 1/3/1 RHYTHM (owner order Aug 18): one short PUNCH line the way you'd say it across a table → the meat, 1-2 plain-words sentences → one OPEN line that creates the exact itch the next headline scratches ("Then the numbers came in"). The open line is mandatory on every content slide except the last — a body that closes its own fact kills the swipe (SHUFFLE TEST: if the middle slides still make sense read in any order, the chain is fake — rewrite until each slide NEEDS the one before). Numbers and names still land in <b>, but a sentence may carry ZERO numbers; voice beats stat density, and a body that reads like a market wrap ("the S&P was green, Nasdaq up 1%") is a failed slide. Ranks and records when TRUE (first, biggest, worst day ever) beat raw figures. Each body delivers a NEW fact — never a re-say of its own headline.
BODY FORMATTING (owner order Aug 22 — organized, scannable text): use blank lines (\n\n) between distinct beats of the 1/3/1 rhythm so the body breathes. When a body references multiple items, comparisons, or a list, break them into separate lines (\n• Item) — never inline a list as one long run-on sentence. A body that looks like one dense unbroken paragraph is a failed slide — rewrite with structure. The reader should grasp the shape of the text at a glance before reading a word.
THE "YOU" CADENCE (owner order Aug 18): every 2-3 slides, ONE body sentence speaks straight to the reader in second person, tying the story to THEIR money, job, or day ("Your $1,000 of Reddit stock was $770 by dinner", "Your accountant should be nervous"). Built from true facts only. Three consecutive slides with zero "you/your" fail QA.
THE BREAK SLIDE (owner order Aug 18, mandatory on every post of 6+ slides): the TWIST slide (~slide 4-5) sets "layout": "break" — a full visual pattern interrupt the renderer inverts (solid orange, huge dark type). Its headline is ONE giant figure or a ≤6-word statement — the story's single wildest number ("$45,000,000,000 GONE") — hsize 100-124, NO <em> (the whole line is the accent on a break slide). Body: ONE short line of context ending open, ≤12 words. No image_brief — the type IS the visual. Exactly one break slide per post; never slides 1-2, never the last two.
Second-to-last. type "content": THE VALUE SLIDE — the consulting-funnel slide, built with the $100M Offers rules (section 5 of the principles). Open with the business owner's PAIN this story touches, then the escape: what a normal business can DO with this, with a concrete number, and why it's now fast/effortless ("without hiring anyone"). Its headline is a factual claim with a number too — never a lesson or a "what this means" label. The reader-owner should finish it thinking "I want this in MY business". Same visual style, no selling tone, no price ever. NEVER a moral or an aphorism (owner comparison Aug 1: "The businesses making real money put AI to work, they don't bet on it" shipped as a sermon that broke the story's spell) — the value slide is still a STORY slide: a concrete number and a real capability, zero preaching.
Last. type "cta": THE SAVE CLOSE (owner order Aug 18 — SUPERSEDES the Aug 1 follow-conversion closer; a generic "follow us" slide is now a FAILURE): the last slide is built to be SAVED. Headline: a save-command that MIRRORS the cover's claim, 6-11 words ("SAVE THIS: THE WEEK AI COST VISA $2 BILLION") — hsize 54-64. Body: the story's 3-5 beats as a one-screen recap CHECKLIST — one line per beat, each ≤8 words, newline-separated, in story order, numbers in <b> (the renderer draws the checkmarks; this recap is WHY people tap save — saves are a top ranking signal). Then one final line: a specific SEND line naming the exact person-type this story hits ("Send this to the friend who still types every email himself") — a send-line is utility; "tag a friend" is banned bait. The renderer adds a "Send this to a friend" pill (sends are IG's top discovery signal) — never write a follow ask or a send ask into your text; your send-line names the person, the pill gives the command. The CTA image is the story's famous person (the art direction handles it): the person the reader just spent six slides with is the one asking them to save it.
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
        # 529/overload backoff (run 32695956904, Aug 24: instant retry into
        # the same Anthropic incident window re-failed both ladder rungs —
        # same lesson as the stall-retry above: give the incident time to pass)
        if "API Error" in out:
            time.sleep(120)
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
- body too long: cut to the best 2 sentences, 30 words max — keep the <b> tags and the concrete facts, drop the weakest sentence; if the kept text runs past 120 characters, separate the sentences with a paragraph break (\\n\\n)
- body is a dense wall with zero line breaks: keep the words, just insert a paragraph break (\\n\\n) between the distinct beats (or \\n• bullets if it lists items) — this is a formatting fix, not a rewrite
- body repeats its own headline's number: replace that sentence with a NEW true fact from the post's other text, or the plain-words consequence — never re-say the headline
- number repeated across slides: keep it on the earlier slide, rewrite the later mention into a different true specific
- cta save-close failures: headline becomes a save-command mirroring the cover's claim, 6-11 words ("SAVE THIS: THE WEEK AI COST VISA $2 BILLION" register, never a follow line); body becomes 3-5 newline-separated recap lines (the story's beats in order, ≤8 words each, numbers in <b>) plus one final send-line
- three slides with zero second person: rewrite ONE body sentence on the middle flagged slide into a true "you/your" consequence line ("Your $1,000 stake was $770 by dinner") — keep every other sentence
- missing/misplaced break slide: convert the twist slide (~slide 4-5) to "layout": "break" — headline = the story's single wildest number or a ≤6-word statement (no <em>), body = one short open line ≤12 words, remove its image_brief
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
    # shapeless-reply guard (run 33189373845 post-mortem: qa_repair on the
    # CLI path has no schema and returned JSON without a 'slides' key; the
    # KeyError here crashed the final ladder rung — same disease as recap.py
    # Aug 27; a malformed post is a QA error for the repair pass, never a
    # crash)
    if not isinstance(post, dict) or not post.get("slides"):
        return ["reply is not a post JSON with a slides array — return the "
                "FULL corrected post object, same shape as the original"]
    slides, caption = post["slides"], post.get("caption", "")
    # profile-card format (@techskills anatomy, owner example Aug 1): card
    # slides carry the story in the body (no headline), and the cover is a
    # longer record-sentence — several gates relax for it
    profile = any(s.get("layout") == "card" for s in slides)
    errs = []
    # caption must be a plain string (run 32756234189 post-mortem: writer
    # returned caption as an object and the AI-tell join crashed the whole
    # ladder with a TypeError — a malformed field is a QA error for the
    # repair pass, never a crash)
    if not isinstance(caption, str):
        errs.append("caption is not a plain string — return caption as one "
                    "text string, not an object or list")
        caption = json.dumps(caption, ensure_ascii=False)
    if not (4 <= len(slides) <= 10):
        errs.append(f"{len(slides)} slides (want 4-10)")
    # NEWS CAP (owner Sep 4, Bernie post-mortem: our 8 slides vs the
    # reference page's 4 on the SAME story — every extra slide is a place to
    # lose the swipe; the chain must earn each one)
    elif post.get("container") and not profile and len(slides) > 7:
        errs.append(f"{len(slides)} slides — news posts cap at 7 (aim 4-6): "
                    "merge the weakest beats, keep only slides that answer "
                    "the chain's question with a NEW fact")
    if slides[0]["type"] != "cover" or slides[-1]["type"] != "cta":
        errs.append("must open with cover, close with cta")
    for i, s in enumerate(slides):
        if s.get("layout") == "card":
            if not (s.get("body") or "").strip():
                errs.append(f"slide {i+1}: card slide has no body — the body IS "
                            "the story on card slides")
            continue
        if s.get("layout") == "break":
            # pattern-break slide (owner Aug 18): the whole line is the accent
            # — the renderer inverts it orange; <em> would fight the inversion
            if "<em>" in s["headline"]:
                errs.append(f"slide {i+1}: break slide headline has <em> — the "
                            "break slide's whole line is the accent, no <em>")
            continue
        if s.get("layout") == "tweet":
            # REACTION RECEIPT (owner Sep 5): the real source post typeset as
            # an X card — no headline, no body; the pipeline injects the data
            if i < 2 or i >= len(slides) - 2:
                errs.append(f"slide {i+1}: tweet receipt must sit mid-chain — "
                            "never slide 1-2, never the last two")
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
    # NAME-FIRST LAW (owner Sep 4, the Bernie post-mortem: the cover riddled
    # "THE MAN WHO RAN FOR PRESIDENT TWICE..." while the reference page led
    # with the name). Mechanical backstop to viral.judge's gate: a famous
    # actor's name must appear in the cover headline. Only fires once the
    # classifier ran (post["viral"] lands right before the tournament).
    v = post.get("viral") or {}
    if post.get("container") and v.get("actor_known") and v.get("actor"):
        toks = [t for t in re.split(r"\W+", v["actor"]) if len(t) > 2]
        if toks and not any(re.search(rf"\b{re.escape(t.lower())}",
                                      cover_plain.lower()) for t in toks):
            errs.append(f'cover headline never names the famous actor '
                        f'"{v["actor"]}" — the name IS the scroll-stopper; '
                        "put it in the first 6 words (name-first law)")
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
        if (s["type"] == "content"
                and s.get("layout") not in ("break", "tweet")
                and not s.get("media_idx")
                and not (s.get("image_brief") or "").strip()):
            errs.append(f"slide {i+1}: no media_idx and no image_brief — every "
                        "content slide needs a real photo or an image brief")
    # HUMAN VOICE gate (owner order Aug 10: "our english writing looks ai"):
    # tier-1 AI-tell vocabulary is a hard fail wherever it appears — doctrine
    # §7 tells the writer, this regex makes sure. Deterministic, zero calls.
    ai_tells = re.compile(
        r"(?i)\bdelve|\btapestry\b|\bparadigm\b|\bleverag(e|ing)\b"
        r"|\bharness(es|ing)?\b|\bmyriad\b|\bplethora\b|\bmultifaceted\b"
        r"|\bseamless|\bgroundbreaking\b|\brevolutioniz|\bsynergy\b"
        r"|\bcutting[- ]edge\b|\btransformative\b|\bunprecedented\b"
        r"|\bgame[- ]chang(er|ing)\b|\bin the (evolving )?world of\b"
        r"|\bit'?s important to note|\bmoreover\b|\bfurthermore\b"
        r"|\bthe future (looks|is) bright|\btime will tell\b|\bstay tuned\b"
        r"|\bexciting times\b|marks a pivotal|is a testament|underscores the")
    all_text = " ".join(
        [re.sub(r"<[^>]+>", "", f"{s.get('headline') or ''} "
                                f"{s.get('body') or ''} {s.get('kicker') or ''}")
         for s in slides] + [caption])
    tells = sorted({m.group(0).lower() for m in ai_tells.finditer(all_text)})
    if tells:
        errs.append(f"AI-tell vocabulary ({', '.join(tells)}) — doctrine §7: "
                    "these words smell machine-written; state the specific "
                    "fact in plain spoken English instead")
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
            if s["type"] != "content" or s.get("layout") in ("card", "tweet"):
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
    # storytelling law Aug 18 (owner: inner slides "plain, flat and boring") —
    # mechanical checks for the "you" cadence and the pattern-break slide.
    # Story flow only (container key); card-format biographies exempt
    if post.get("container") and not profile:
        content = [(i, s) for i, s in enumerate(slides)
                   if s["type"] == "content"
                   and s.get("layout") != "tweet"]  # card has no own text
        # "you" cadence: no 3 consecutive content slides without second person
        run = 0
        for i, s in content:
            text = re.sub(r"<[^>]+>", "", f"{s.get('headline') or ''} "
                                          f"{s.get('body') or ''}")
            run = 0 if re.search(r"(?i)\byou\b|\byour\b|\byou'", text) else run + 1
            if run >= 3:
                errs.append(f"slides {i-1}-{i+1}: three slides in a row with "
                            "zero second person — every 2-3 slides one sentence "
                            "must hit the READER's money/job/day ('your "
                            "accountant should be nervous')")
                break
        # break slide: exactly one on 6+ slide posts, mid-carousel only
        breaks = [i for i, s in enumerate(slides) if s.get("layout") == "break"]
        if len(slides) >= 6 and not breaks:
            errs.append("no break slide — every 6+ slide post needs ONE "
                        'pattern-break slide (~slide 4-5): "layout": "break", '
                        "headline = the story's wildest number or a ≤6-word "
                        "statement, one short open body line")
        if len(breaks) > 1:
            errs.append("more than one break slide — the pattern interrupt "
                        "works exactly once per post")
        for b in breaks:
            if b < 2 or b >= len(slides) - 2:
                errs.append(f"slide {b+1}: break slide sits at the edge — it "
                            "belongs mid-carousel (never the first two or "
                            "last two slides)")
            bw = len(re.sub(r"<[^>]+>", "",
                            slides[b].get("headline") or "").split())
            if bw > 7:
                errs.append(f"slide {b+1}: break headline is {bw} words — one "
                            "giant number or a ≤6-word statement, nothing else")
    # THE FACTS STACK (owner Sep 4, @technology anatomy: their Bernie post
    # carried one slide that stacked the bill's hard numbers as short
    # scannable lines — the save-worthy slide ours never had). Every news
    # post carries exactly one: an inner slide whose body is 3-4 stacked
    # lines (own line each via \n), each ONE hard fact, max 8 words.
    if post.get("container") and not profile:
        def _stack(s):
            lines = [l.strip() for l in
                     re.sub(r"<[^>]+>", "", s.get("body") or "").split("\n")
                     if l.strip()]
            return (len(lines) >= 3
                    and all(len(l.lstrip("•- ").split()) <= 8 for l in lines))
        if not any(_stack(s) for s in slides[1:-1]
                   if s["type"] == "content" and s.get("layout") not in
                   ("break", "card", "tweet")):
            errs.append("no facts-stack slide — ONE inner content slide must "
                        "stack the story's 3-4 hardest facts as short lines "
                        "(\\n between them, max 8 words each, the number in "
                        "each line accented); it is the slide people save")
    # BODY STRUCTURE (owner order Aug 22): bodies must be organized and
    # scannable — a dense unbroken wall of text with no line breaks is a
    # failure. Skill slides (proof + prompt) need at least one blank line;
    # story slides with 100+ chars of body need at least one line break.
    for i, s in enumerate(slides):
        if s["type"] != "content" or s.get("layout") in ("break", "card",
                                                         "tweet"):
            continue
        body = s.get("body") or ""
        if len(body) > 120 and "\n" not in body:
            errs.append(f"slide {i+1}: body is {len(body)} chars with zero "
                        "line breaks — a dense wall of text is a failed slide; "
                        "add paragraph breaks (\\n\\n) between distinct beats "
                        "and use bullet points (\\n• Item) for any list")
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
    # SAVE-CLOSE CTA (owner order Aug 18 — SUPERSEDES the Aug 1 follow-
    # conversion closer): the last slide is a one-screen recap built to be
    # SAVED, never a generic "follow us" (the renderer's pill carries the
    # send ask since Aug 27 — sends/reach is IG's top discovery signal).
    # container key only exists in the story flow — edu gates its own CTA
    if post.get("container"):
        cta = slides[-1]
        cta_head = re.sub(r"<[^>]+>", "", cta.get("headline", ""))
        if re.search(r"(?i)\bfollow", cta_head):
            errs.append("cta headline is a follow line — the closer is now the "
                        "SAVE CLOSE (owner Aug 18): a save-command mirroring "
                        "the cover's claim; follow asks are banned everywhere")
        if not re.search(r"(?i)\bsave\b", cta_head):
            errs.append('cta headline must open with a save-command ("SAVE '
                        'THIS: ...") mirroring the cover\'s claim, 6-11 words')
        cta_lines = [l for l in (cta.get("body") or "").split("\n") if l.strip()]
        if len(cta_lines) < 3:
            errs.append(f"cta body has {len(cta_lines)} line(s) — the save "
                        "close is a recap CHECKLIST: 3-5 newline-separated "
                        "story beats (≤8 words each) plus the send-line")
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
                # SECOND REPAIR ROUND (Aug 28, runs 33171169866 + 33137611952:
                # three slots died in 12h with the first repair shrinking the
                # list to pure-formatting leftovers — "zero line breaks, insert
                # \n\n" — and then giving up. Repair the repaired post once
                # more while the list is still shrinking; one small call only
                # on the failure path.)
                if left and len(left) < len(errs):
                    again = qa_repair(fixed, left)
                    if again and not qa(again):
                        print("second repair round cleared QA — using it",
                              file=sys.stderr)
                        fixed, left = again, []
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

    # REACTION RECEIPT (owner order Sep 5, the reference-page anatomy): the
    # writer may flag ONE slide "layout": "tweet" — the PIPELINE injects the
    # real source post's text/handle/views here, so nothing can be fabricated.
    # No real X data -> the flag is stripped and the slide becomes a normal
    # content slide (qa already required nothing tweet-specific of its text).
    m = story.get("radar") or {}
    for s in post["slides"]:
        if s.get("layout") != "tweet":
            continue
        if m.get("selftext") and "on X" in (m.get("where") or ""):
            posted = datetime.fromtimestamp(
                time.time() - float(m.get("age_h") or 0) * 3600)
            s["tweet"] = {"handle": m.get("sub") or "",
                          "text": m["selftext"][:290],
                          "views": int(m.get("views") or 0),
                          "when": posted.strftime("%b %d, %Y")}
            s.pop("image_brief", None)  # the card IS the visual — never gen
            s["media"] = None
        else:
            s.pop("layout", None)

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
    genlock = threading.Lock()  # guards gen counter + cover reject pool

    def render_slide(i, s):
        nonlocal gen, cover_scored, cover_brief
        if s.get("layout") == "tweet":
            return  # reaction receipt: typeset X card, no image ever
        brief = s.pop("image_brief", "").strip()
        want_ref = s.pop("gen_ref", False) and ref_photo
        # PERSON ROUTE — REF-PHOTO LAW (Sep 4, Bernie post-mortem): a face
        # renders ONLY from a real photograph. Ladder: 1) nano-banana with a
        # press photo for EVERY named person — pool first, Wikipedia fetch
        # second -> 2) FACELESS rebuild (never a memory-drawn likeness). The
        # old middle rung called the retired gpt-image-2 route, which since
        # Aug 30 silently fell to nano TEXT-TO-IMAGE — nano drew Bernie from
        # memory and shipped the waxy fake. That rung is deleted: no photo
        # anywhere means no face, period.
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
        # LOGO ONCE (owner order Sep 6, the Astra cover shipped the OpenAI
        # mark three times — corner disc + giant backdrop copy: "even if you
        # put the logo in the picture that ai generated you dont need
        # another one and vice versa"): each brand's logo appears ONCE on
        # the finished slide, from ONE source. Discs are the exact official
        # mark, so when discs will be stamped the scene gets no logo at all.
        if logo_slug and s["type"] == "cover" and s.get("discs"):
            print(f"logo-once: cover has discs — dropping gen_logo "
                  f"'{logo_slug}' from the scene", file=sys.stderr)
            logo_slug = None
        if logo_slug:
            brand_ref = logo_ref(logo_slug.replace(" ", ""))
            if brand_ref and s["type"] == "cover":
                s["scene_logo"] = logo_slug  # renderer must not re-stamp it
        if s["type"] == "cover" and s.get("discs"):
            brief += (" SCENE LOGO BAN: render no brand logos or logo marks "
                      "anywhere in this scene — the layout stamps the "
                      "official logo badge on top of the picture separately, "
                      "and each logo may appear only once on the finished "
                      "slide.")
        # cta generates when it has a real anchor: the product photo (product-
        # hero second pose) or the story person's face ref (owner Aug 1: the
        # Tim Cook closer — the story's person says "follow us"). No anchor ->
        # art bg, never a from-scratch face
        if s["type"] == "cta" and not (want_ref or face_refs or person):
            return
        with genlock:
            if not brief or gen >= 4:
                return
        if s.get("media") and s["type"] not in ("cover", "cta"):
            return
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
                return
            print(f"cover candidate rejected (score {score}/10): {flaw} "
                  "— falling through to generation", file=sys.stderr)
            with genlock:
                pool.append((score, cand))
            s["media"] = None
        # cover ladder (owner rules Jul 29: capped attempts — each image costs
        # money — the brief rewritten around the judge's named flaw between
        # attempts, and the post NEVER ships imageless: if nothing passes, the
        # best-scoring reject wins). Inner slides keep one shot; genimg's
        # budget guard caps total spend either way.
        # cover tries 2 -> 3 (Sep 4 post-mortem: two full story rungs died at
        # Gate B because both cover attempts came back as cartoon/render and
        # the best-REJECT shipped to the editor — a third $0.04 nano attempt
        # is the cheapest insurance against losing a 40-min rung. The Aug 8
        # diet's 3->2 cut priced tries at gpt-image $0.17; nano changed the
        # math.)
        tries = 3 if s["type"] == "cover" else 1
        for attempt in range(tries):
            out_jpg = os.path.join(post_dir, f"gen-{i}{'-r' * attempt}.jpg")
            # audit trail (owner Aug 10: "what was the prompt?" was
            # unanswerable — briefs died with the process): every attempted
            # brief goes to the log, the winning one into post.json below
            print(f"slide {i+1} brief (attempt {attempt+1}): {brief}",
                  file=sys.stderr)
            path = None
            if person:
                # NANO ROUTE — PRIMARY person model (owner order Aug 14,
                # "change to nano banana if its 4 times cheaper"; head-to-head
                # on the fake-Sam brief: likeness copied from our REAL press
                # photo + the real logo ref rendered exactly, $0.04 vs gpt's
                # $0.17). Requires a press photo for EVERY named person —
                # identity comes from the photo, so no photo means no route.
                names = split_faces(face_field)
                if names and all((pick_face(n.lower().replace(" ", "-"))
                                  or fetch_face(n)) for n in names):
                    nb, nrefs = face_riders(brief, face_field)
                    nrefs = [r for r in nrefs + [brand_ref] if r]
                    if nrefs:
                        path = genimg.generate(nb, out_jpg,
                                               cover=(s["type"] == "cover"),
                                               person=True, nano=True,
                                               refs=nrefs,
                                               collage=(s["type"] == "cover"))
                if not path:
                    # FALLBACK RUNG (always-post ladder): no real photo exists
                    # for someone in the cast (pool + Wikipedia both empty),
                    # or nano/budget failed -> FACELESS rebuild (owner Aug 14,
                    # the fake-Sam cover; Sep 4 ref-photo law: a face with no
                    # photograph never renders — a WRONG face is worse than no
                    # face). face_riders then strips any residual name (E005).
                    person = False
                    if s["type"] == "cover":
                        fb_flaw = ("no real photo exists for the named person "
                                   "— keep the exact 'SUBJECT: ... BACKDROP "
                                   "PROPS: ... PALETTE: ...' slot format, but "
                                   "replace the SUBJECT with the story's "
                                   "single hero object at giant scale; no "
                                   "people anywhere, no faces")
                    else:
                        fb_flaw = ("the person model is unavailable — rebuild "
                                   "this EXACT scene for a model that cannot "
                                   "render real faces: same setting, props, "
                                   "logo and story, but the named person "
                                   "appears ONLY from behind or as a "
                                   "silhouette (face never visible), or is "
                                   "replaced by the story's object at "
                                   "theatrical scale. Never ask for a "
                                   "recognizable face")
                    fb = simpler_brief(brief, s.get("headline", ""), flaw=fb_flaw)
                    brief, face_refs = face_riders(fb or brief, None)
            if not path:
                refs = [r for r in [ref_photo if want_ref else None]
                        + face_refs + [brand_ref] if r]
                # face_refs on a cover force the nano route (Aug 15 post-mortem,
                # the paint-roller "Dario": art_direct named him in the brief
                # text only, the E005 scrub rewrote it to "the person in the
                # reference photo" + attached his real photo — then the cover
                # went to gpt, which IGNORES reference photos, so it invented
                # a stranger from that phrase. Only photo-capable models may
                # render a brief that points at a reference person.)
                path = genimg.generate(
                    brief, out_jpg, refs=refs or None,
                    cover=(s["type"] == "cover"),
                    nano=bool(face_refs and s["type"] == "cover"),
                    collage=(s["type"] == "cover"))
            if not path:
                # keep trying: one flaky prediction must not forfeit the cover
                # (Aug 2 bare edu cover, issue #16); budget-out retries are
                # free local no-ops so continue is safe either way
                continue
            ok, score, flaw = image_score(path, s.get("headline")
                                          or (s.get("body") or "")[:90],
                                          generated=True, person=person,
                                          cover=(s["type"] == "cover"),
                                          collage=(s["type"] == "cover"))
            if ok:
                s["media"] = os.path.relpath(path, HERE)
                s["image_prompt"] = brief
                with genlock:
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
                with genlock:
                    pool.append((score, path))
            if attempt + 1 < tries:
                # person-route covers retry concept-preserving (Aug 9): keep
                # the staged scene + cast, fix only the judge's named flaw.
                # Collage covers (Sep 4 brutal format) must come back in slot
                # form — the frozen scaffold only works on slot briefs.
                if s["type"] == "cover":
                    flaw = (flaw + " — KEEP the exact 'SUBJECT: ... BACKDROP "
                            "PROPS: ... PALETTE: ...' slot format, change "
                            "only the slot contents").lstrip(" —")
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

    # PARALLEL slide generation (run-time diet Aug 12): the sequential
    # gen+judge chain was ~12 min of the 50-64 min run. Slides are independent
    # of each other — shared state is the gen cap, the cover reject pool
    # (genlock) and the spend/face ledgers (locked in genimg._book/pick_face,
    # which also books budget atomically so parallel checks can't overspend).
    # max_workers matches the gen cap of 4, so the cap check at worker start
    # keeps the sequential semantics: a queued slide only starts after another
    # finishes, and skips once four images have landed. A worker crash
    # re-raises here — the same failure mode as the old in-line loop.
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = [ex.submit(render_slide, i, s)
                for i, s in enumerate(post["slides"])]
    for f in futs:
        f.result()
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
                                      cover0.get("headline", ""), cover=True)
        if not ok:
            print(f"cover candidate rejected in final audit (score {score}/10):"
                  f" {flaw}", file=sys.stderr)
            pool.append((score, os.path.join(HERE, cover0["media"])))
            cover0["media"] = None
    if not cover0.get("media"):
        for mi, m in enumerate(media_files, 1):
            if mi in used:
                continue
            ok, score, flaw = image_score(m, cover0["headline"], cover=True)
            if ok:
                cover0["media"] = os.path.relpath(m, HERE)
                post["cover_style"] = "photo"
                print(f"cover fell back to article image {os.path.basename(m)}",
                      file=sys.stderr)
                break
            pool.append((score, m))
        if not cover0.get("media") and pool:
            score, best = max(pool, key=lambda t: t[0])
            # RESCUE RUNG (owner audit Aug 10): a <=5/10 best reject is
            # wallpaper — one cheap faceless Seedream attempt via the no-face
            # playbook before settling for it. Always-post intact: the best
            # reject stays the floor if the rescue also fails. (Threshold was
            # 4; the Aug 14 fake-Sam cover shipped as a 5/10 best reject, one
            # point above the rescue — a wrong famous face must never win.)
            if score <= 5 and cover_brief:
                rb = simpler_brief(
                    cover_brief, cover0.get("headline", ""),
                    flaw=f"best attempt scored {score}/10 — rebuild FACELESS "
                         "in the exact 'SUBJECT: ... BACKDROP PROPS: ... "
                         "PALETTE: ...' slot format: SUBJECT becomes the "
                         "story's single hero object at giant scale, no "
                         "human faces anywhere")
                if rb:
                    rb = face_riders(rb, None)[0]
                    rp = genimg.generate(
                        rb, os.path.join(post_dir, "gen-0-rescue.jpg"),
                        cover=True, collage=True)
                    if rp:
                        ok2, s2, _ = image_score(rp, cover0.get("headline", ""),
                                                 generated=True, cover=True,
                                                 collage=True)
                        if ok2:
                            cover0["media"] = os.path.relpath(rp, HERE)
                            cover0["image_prompt"] = rb
                            post["cover_style"] = "photo"
                            post["cover_fallback"] = "no-face rescue"
                            print(f"COVER rescued by the no-face rung "
                                  f"({s2}/10)", file=sys.stderr)
                        elif s2 > score:
                            pool.append((s2, rp))
                            score, best = max(pool, key=lambda t: t[0])
        if not cover0.get("media") and pool:
            cover0["media"] = os.path.relpath(best, HERE)
            if cover_brief:
                cover0["image_prompt"] = cover_brief
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
    # LOGO ONCE, other direction (owner order Sep 6): the generated scene
    # already carries the brand mark (gen_logo ref was attached) — the
    # renderer must not add a second copy as a flat logo overlay or badge
    # chip. One logo per brand per finished slide, from either source.
    if cover.pop("scene_logo", None) and \
            os.path.basename(cover.get("media") or "").startswith("gen"):
        post["logos"] = []
        post["badge_logo"] = None
        print("logo-once: scene carries the logo — renderer overlays off",
              file=sys.stderr)
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
    if story.get("gate_a_relaxed"):
        # STORY_RELAX rung shipped this over a Gate A kill (Aug 27) — the
        # daily report must be able to name it and learn.py can compare
        # relaxed picks' real performance against clean approvals
        post["gate_a_relaxed"] = True

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
    for _ in range(2):  # up to two surgical repair rounds (Aug 10: a repair
        # can clear round-1 flaws while the editor finds new ones in round 2 —
        # one bounded extra cheap call beats losing a finished post)
        if ok:
            break
        fixed = qa_repair(post, ["editor reject: " + r for r in reasons])
        if fixed and len(fixed.get("slides", [])) == len(post["slides"]):
            # THE REPAIR IS NOT A QA BYPASS (Aug 19 "6-bleed" edu post-mortem:
            # a Gate B repair rewrote the cover past the word cap and the
            # kicker to 10 words, nothing re-checked qa after the merge, and
            # the headline rendered printed over the kicker strip). Merge,
            # re-run the mechanical gates, revert if the repair introduced
            # NEW violations — a dead repair means Gate B's reject stands.
            keep = json.loads(json.dumps(post))
            for s_old, s_new in zip(post["slides"], fixed["slides"]):
                for k in ("headline", "body", "kicker"):
                    if s_new.get(k):
                        s_old[k] = s_new[k]
            if fixed.get("caption"):
                post["caption"] = fixed["caption"]
            scrub_dashes(post)
            base = qa(keep)
            broke = [e for e in qa(post) if e not in base]
            if broke:
                print("gate B repair broke mechanical qa — reverting the "
                      "repair:\n  " + "\n  ".join(broke), file=sys.stderr)
                post.clear()
                post.update(keep)
                break  # repair unusable — Gate B's reject stands
            ok, reasons = editor.gate_b(post, os.path.join(HERE, cm) if cm else None)
        else:
            break  # repair itself failed — retrying with the same input won't help
    if not ok:
        if os.environ.get("STORY_FORCE"):
            # NEWS PAGE FIRST floor (owner order Sep 3): on the last story
            # rung a Gate B reject ships FLAGGED instead of falling to yet
            # another edu guide — mirrors edu.py's editor_override. The
            # mechanical qa gates above stayed BINDING (wording is the
            # owner's top priority); only the editor's judgment call is
            # advisory here. daily.py names every override.
            post["editor_override"] = "; ".join(reasons)[:400]
            print("STORY_FORCE: shipping over gate B reject — "
                  + "; ".join(reasons), file=sys.stderr)
        else:
            # preserve the finished text for post-mortem/salvage — a killed
            # post cost real money; only publishing is blocked, not the
            # evidence
            json.dump(post, open(os.path.join(post_dir, "post-rejected.json"),
                                 "w"), indent=1)
            raise SystemExit("editor gate B rejected the post after repair: "
                             + "; ".join(reasons))

    json.dump(post, open(os.path.join(post_dir, "post.json"), "w"), indent=1)
    subprocess.run([sys.executable, os.path.join(HERE, "render.py"),
                    os.path.join(post_dir, "post.json"), post_dir], check=True)

    # GATE R (owner order Sep 5): eyes on EVERY rendered slide — Gate B sees
    # text + the cover only; nobody had ever LOOKED at a finished inner
    # slide. drop_image repairs apply + one re-render; ships flagged, never
    # skipped (always-post).
    fails = editor.gate_r(post, post_dir)
    if fails:
        editor.apply_gate_r(post, fails)
        json.dump(post, open(os.path.join(post_dir, "post.json"), "w"),
                  indent=1)
        subprocess.run([sys.executable, os.path.join(HERE, "render.py"),
                        os.path.join(post_dir, "post.json"), post_dir],
                       check=True)
    print("post ready:", post_dir)
    return post_dir


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "stories.json"))
