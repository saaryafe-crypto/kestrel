#!/usr/bin/env python3
"""Cover images via Replicate (google/nano-banana, Seedream-4 fallback).
generate(brief, out_path) -> saved jpg path or None.

NANO-ONLY REGIME (owner order Aug 30 "this should be the cheapest possible
with nano banana ... only for the cover image"): the cover is the ONLY
generated image — inner slides use article imagery or ship bare — and every
cover renders on nano-banana ($0.04). gpt-image-2 is retired: its $0.17
covers burned the whole $45 August cap by Aug 29 and posts shipped
pictureless. nano copies likenesses from real press photos in faces/ and
renders logo refs exactly (head-to-head win, Aug 14); with no refs it runs
plain text-to-image. Seedream-4 survives only as the nano-flake fallback
rung ($0.03) so a cover is never forfeited to one bad prediction.

The reference page's craft: every image is a built VISUALIZATION of the
slide's exact claim (a phone showing "Device Locked" for a lock story) —
never a generic stock photo.

Hard budget guard: monthly AND daily spend tracked in genimg-used.json.
No key, budget out, or API failure -> None and the caller falls back to
article imagery — a posting slot is never blocked. Stdlib only."""
import json, os, sys, threading, time, urllib.request
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
USED = os.path.join(HERE, "genimg-used.json")
# NANO-ONLY REGIME (owner order Aug 30 "this should be the cheapest possible
# with nano banana ... only for the cover image"): generated imagery is the
# COVER ONLY on nano-banana ($0.04); gpt-image-2 is retired — its $0.17 covers
# burned the whole $45 August cap by Aug 29 and posts shipped pictureless.
# Realistic run rate (Sep 1 measurement): ~9 posts/day x 2-4 QA-gated tries
# x $0.04 = ~$0.90/day => ~$25-30/mo. The MONTH cap is a pure RUNAWAY BRAKE,
# sized so it can never bind under normal operation (Sep 1 post-mortem: the
# $12 cap + $0.90 cover lane starved covers mid-day and posts shipped
# pictureless — the owner's #1 forbidden failure, flagged three times).
# Covers book with floor=True (month brake only); retry counts in the
# callers, not dollars, are what bound spend.
# START: gpt-era ledger entries before this date don't count against the new
# caps (August's $45.31 would otherwise block covers until Sep 1).
START = "2026-08-30"
MONTH_BUDGET, DAY_BUDGET = 60.00, 0.60
COVER_DAY_BUDGET = 3.00  # only binds for non-floor bookings (none today)
COST = 0.03  # Seedream: flat per output image, any size — nano-flake fallback
URL = "https://api.replicate.com/v1/models/bytedance/seedream-4/predictions"
# nano-banana (primary since Aug 14 for persons, ALL covers since Aug 30):
# copies likeness from real press photos in faces/ + renders logo refs exactly.
# Billed $0.039, booked with headroom.
NANO_URL = "https://api.replicate.com/v1/models/google/nano-banana/predictions"
NANO_COST = 0.04

# ONE SIMPLE PROMPT (owner order Sep 9, the umbrella post-mortem: the shipped
# cover prompt was ~600 words of stacked rule boilerplate and the owner read
# the sidecar — "Why the prompt is so complicated?... you are just ai
# slopping every prompt. there is no thinking behind the prompt... think
# like a viral youtube thumbnail creator. MRbeast for example". His spec,
# shape verbatim: "a picture of a self driving umbrella following (someone
# famous) without him holding it - showing a futuristic umbrella and make it
# extremely realistic and shocking". So the BRIEF — one vivid sentence from
# art_direct — IS the prompt, and the scaffold below is the only boilerplate
# that survives. Every line kept earns its place with a shipped failure:
# title zone (Sep 8: heads under the headline), color pop (Sep 7: flat
# orange wash), text ban (Circle K: 5 of 6 images died to garbled text),
# label-once (Sep 6: a "$230" chip rendered twice), logo-once (Sep 6: same
# logo three times), full bleed (Sep 6: nano baked a black frame),
# press-photo realism (Sep 3: cartoon covers). Everything else the old
# 600-word scaffold policed (stop test, chiaroscuro recipes, cutout-edge
# styling, cliche bans) is enforced by the image judge in write.image_score
# instead — the judge catches flaws for free, prompt bloat causes them.
_TAIL = (
    " Compose EVERYTHING that matters — faces, key prop, stakes — in the "
    "upper 60% of the frame; the bottom 40% is sacrificial background, a "
    "solid headline band covers it completely, so anything placed there "
    "is lost (owner Sep 9, getintoai anatomy). Bright, loud, saturated "
    "colors true to the story; "
    "the main subject keeps its natural real-life colors so it pops — "
    "never one flat color wash over the whole picture. No words, text, "
    "captions or lettering anywhere; only if the brief quotes exact label "
    "words, render each quoted label exactly once as one small clean "
    "caption chip in the upper two-thirds. A brand's real logo may appear "
    "at most once, as one physical object inside the scene — never as "
    "wallpaper. The picture fills the whole frame edge to edge, no "
    "borders. Extremely realistic and shocking.")
COLLAGE_PERSON = (
    " Ultra-realistic vertical 4:5 photograph, shot like a real press "
    "photo — never an illustration, cartoon or 3D render. The person is "
    "the exact person in the attached reference photo: same face, same "
    "hair, copied faithfully, never redrawn from memory." + _TAIL)
COLLAGE_FACELESS = (
    " Ultra-realistic vertical 4:5 photograph, shot like a real press "
    "photo — never an illustration, cartoon or 3D render. Any people "
    "appear only from behind, as silhouettes or as hands — never a "
    "visible recognizable face." + _TAIL)
# RECAP MONTAGE (owner Sep 5, Bernie-recap post-mortem: raw tweet images
# glued side by side by CSS — "it looks SO SO bad". Smoke-tests that shaped
# the rules: a rally banner leaked in misspelled; one ref rendered twice
# while another vanished; the story list rendered as misspelled chips.)
COLLAGE_MONTAGE = (
    " Photorealistic vertical 4:5 montage poster built ONLY from the "
    "attached reference photographs: cut the main subject out of EACH "
    "photo — faces, hair and clothing identical to their photographs, "
    "never redrawn from memory — and completely discard each photo's own "
    "background, signs and lettering. Arrange the cutouts as an "
    "overlapping poster at varying scales, the first photo's subject "
    "largest and most central, each photo's subject appearing exactly "
    "once, all of them filling the upper two-thirds of the frame. Behind "
    "them one loud saturated environment from the biggest story's world. "
    "The briefed story lines exist only to pick and size the subjects — "
    "never render them as text." + _TAIL)


def _key():
    if os.environ.get("REPLICATE_API_TOKEN"):
        return os.environ["REPLICATE_API_TOKEN"]
    env = os.path.join(HERE, "..", ".env")
    if os.path.exists(env):
        for line in open(env):
            if line.startswith("REPLICATE_API_TOKEN=") and line.split("=", 1)[1].strip():
                return line.split("=", 1)[1].strip()
    return None


# write.py generates slides in PARALLEL threads (run-time diet Aug 12): every
# ledger touch is one atomic read-modify-write under this lock, or concurrent
# generates lose each other's entries and the budget silently leaks.
_LOCK = threading.Lock()


def _sums(used):
    today = str(date.today())
    month = today[:7]
    used = [u for u in used if u["date"] >= START]  # gpt-era spend excluded
    is_cover = lambda u: u.get("cover", u["cost"] >= 0.17)
    return (sum(u["cost"] for u in used if u["date"][:7] == month),
            sum(u["cost"] for u in used if u["date"] == today and not is_cover(u)),
            sum(u["cost"] for u in used if u["date"] == today and is_cover(u)))


def _book(cost, cover=False, floor=False):
    """Atomic budget check + spend record. Booking BEFORE the API call (not
    after, like the old check-then-spend) closes the parallel-generation race
    where two threads both pass the check with headroom for only one. A
    failed generation refunds via _refund. Returns True when booked.
    floor=True (Aug 12 post-mortem: two posts shipped the SAME stock
    sam-altman.jpg because the $0.03 Seedream degrade rung was refused by the
    already-blown cover cap): the cheap last generated rung ignores the DAY
    cap — only the month cap can kill it. A generated cover always beats the
    static press-photo floor."""
    with _LOCK:
        used = json.load(open(USED)) if os.path.exists(USED) else []
        month, day_inner, day_cover = _sums(used)
        day = day_cover if cover else day_inner
        day_cap = COVER_DAY_BUDGET if cover else DAY_BUDGET
        if month + cost > MONTH_BUDGET or (not floor and day + cost > day_cap):
            print(f"genimg budget out (month ${month:.2f}, today ${day:.2f}, "
                  f"{'cover' if cover else 'inner'} cap ${day_cap:.2f})",
                  file=sys.stderr)
            return False
        used.append({"date": str(date.today()), "cost": cost, "cover": cover})
        json.dump(used, open(USED, "w"))
        return True


def _refund(cost, cover=False):
    """Remove one booked entry (the generation it paid for returned nothing)."""
    with _LOCK:
        used = json.load(open(USED)) if os.path.exists(USED) else []
        for j in range(len(used) - 1, -1, -1):
            if (used[j]["date"] == str(date.today()) and used[j]["cost"] == cost
                    and used[j].get("cover", False) == cover):
                used.pop(j)
                break
        json.dump(used, open(USED, "w"))


def _get(url, key=None, timeout=60):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"} if key else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _data_uri(path):
    """Local image -> data URI for Replicate image_input. Downscaled to ~1024px
    (Pillow when available) to keep the request body small; reference images
    guide composition/product identity, they don't need full res."""
    import base64
    data = None
    try:
        from PIL import Image
        import io
        img = Image.open(path).convert("RGB")
        img.thumbnail((1024, 1024))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=85)
        data = buf.getvalue()
    except Exception:
        data = open(path, "rb").read()
    return "data:image/jpeg;base64," + base64.b64encode(data).decode()


def _call(key, prompt, refs=None):
    # 2K, same flat price as 1K — the extra resolution is what keeps short
    # screen text crisp (1080-wide test garbled "Device Locked").
    # 4:5 PORTRAIT (owner Sep 7): generation is covers-only since Aug 30 and
    # covers display FULL-BLEED 1080x1350 (render.py .bleed cover). The Aug 14
    # square decision was made for the old content-slide window; on covers a
    # square gen lost ~20% of its width to the crop — the GPT-6 cover shipped
    # with its stopwatch chip amputated to "…:59". Generate the shape we
    # actually display.
    body = {"input": {"prompt": prompt, "size": "custom",
                      "width": 2048, "height": 2560, "max_images": 1}}
    if refs:
        # product-hero covers (owner Aug 1, @technology Codex Micro anatomy):
        # the REAL product photo rides along so the generated device matches
        # reality instead of an invented gadget
        body["input"]["image_input"] = [_data_uri(r) for r in refs[:3]]
    req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {key}",
                                          "Prefer": "wait"})  # block until done (~10s)
    with urllib.request.urlopen(req, timeout=120) as r:
        pred = json.loads(r.read())
    for _ in range(20):  # Prefer:wait caps at ~60s; poll if the model was cold
        if pred.get("status") in ("succeeded", "failed", "canceled"):
            break
        time.sleep(3)
        pred = json.loads(_get(pred["urls"]["get"], key))
    out = pred.get("output")
    if isinstance(out, list):
        out = out[0] if out else None
    if isinstance(out, str) and out.startswith("http"):
        return _get(out)
    # surface WHY (Aug 2 bare-cover post-mortem: the prediction's error was
    # swallowed here, so the log only ever said "returned no image")
    print(f"genimg: prediction {pred.get('status')!r} error={pred.get('error')!r}",
          file=sys.stderr)
    return None


def _call_nano(key, prompt, refs):
    """google/nano-banana: identity-from-photo person model (Aug 14). The
    press photo(s) + real logo mark ride as image_input — likeness is copied
    from the actual photograph, not drawn from memory."""
    body = {"input": {"prompt": prompt, "aspect_ratio": "4:5",
                      "output_format": "jpg"}}
    if refs:  # no-ref briefs (faceless concepts) are plain text-to-image
        body["input"]["image_input"] = [_data_uri(r) for r in refs[:3]]
    req = urllib.request.Request(NANO_URL, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {key}",
                                          "Prefer": "wait"})
    with urllib.request.urlopen(req, timeout=120) as r:
        pred = json.loads(r.read())
    for _ in range(20):
        if pred.get("status") in ("succeeded", "failed", "canceled"):
            break
        time.sleep(3)
        pred = json.loads(_get(pred["urls"]["get"], key))
    out = pred.get("output")
    if isinstance(out, list):
        out = out[0] if out else None
    if isinstance(out, str) and out.startswith("http"):
        return _get(out)
    print(f"genimg(nano): prediction {pred.get('status')!r} "
          f"error={pred.get('error')!r}", file=sys.stderr)
    return None


def _grade(path):
    """Deterministic post-grade (brutal format, Sep 4): the @technology look
    is half prompt, half GRADE — autocontrast + saturation + unsharp applied
    in code so every cover ships punchy even when the model renders flat.
    Pillow missing or failure -> the ungraded cover ships (never blocks)."""
    try:
        from PIL import Image, ImageEnhance, ImageFilter, ImageOps
        img = Image.open(path).convert("RGB")
        img = ImageOps.autocontrast(img, cutoff=1)
        img = ImageEnhance.Color(img).enhance(1.22)
        img = ImageEnhance.Contrast(img).enhance(1.06)
        img = img.filter(ImageFilter.UnsharpMask(radius=2, percent=80, threshold=3))
        img.save(path, "JPEG", quality=92)
    except Exception as e:
        print(f"genimg: grade skipped ({e})", file=sys.stderr)


def _save_prompt(out_path, prompt):
    """Owner monitor (Sep 8 order: "i want an email with the full prompt for
    the image and i will gradually correct you"): the EXACT prompt sent to
    the model rides beside the image as <image>.prompt.txt, committed with
    the post dir, quoted in the publish email. Fails open."""
    try:
        open(out_path + ".prompt.txt", "w").write(prompt)
    except Exception:
        pass


def generate(brief, out_path, refs=None, cover=False, person=False, nano=False,
             collage=False, montage=False):
    key = _key()
    if not key:
        return None
    # COVER-FIRST (owner Aug 1, Chrome-bugs post-mortem: the daily cap ran out
    # on inner slides of EARLIER posts, so a later post shipped a logo-on-dark
    # cover — "terrible logo and without a cover photo"). Each lane answers
    # only to its OWN daily ceiling (+ the monthly cap, both enforced inside
    # _book): covers can never be starved by inner spend, and inner slides can
    # never be starved by cover spend (issue #18 post-mortem).
    # nano-only regime (owner order Aug 30): the COVER is the only generated
    # image — inner slides use article imagery or ship bare — and every cover
    # renders on nano-banana. Seedream survives only as the nano-flake rung.
    if not cover:
        return None
    cost = NANO_COST
    # floor=True: covers are NEVER starved by a daily dollar cap (Sep 1
    # post-mortem: the $0.90 cover lane died mid-day under QA retries and 4
    # posts shipped pictureless AGAIN — the exact failure the owner already
    # flagged twice). Spend is bounded structurally instead: the callers cap
    # attempts per cover, so only the month backstop can stop a booking.
    if not _book(cost, cover=True, floor=True):
        print("genimg: skipping (budget out)", file=sys.stderr)
        return None
    live_refs = [r for r in (refs or []) if os.path.exists(r)]
    if montage and not live_refs:
        # montage is DEFINED as cutouts of real press photos — with no refs
        # it would memory-draw every face (the exact Bernie-wax failure)
        _refund(cost, cover=True)
        print("genimg: montage with no live refs — refusing", file=sys.stderr)
        return None
    if collage or montage:
        # BRUTAL FORMAT (owner Sep 4): frozen scaffold, brief fills slots only.
        # Person scaffold ONLY when a real reference photo actually rides
        # along — a named person with no photo must go faceless, never a
        # memory-drawn face (the Bernie wax post-mortem).
        if montage:
            scaffold = COLLAGE_MONTAGE
        else:
            scaffold = COLLAGE_PERSON if (person and live_refs) else COLLAGE_FACELESS
        prompt = f"{brief}.{scaffold}"
        _save_prompt(out_path, prompt)
        try:
            img = _call_nano(key, prompt, live_refs)
            if not img:
                _refund(cost, cover=True)
                print("genimg: nano returned no image — retrying brief on "
                      "Seedream", file=sys.stderr)
                if not _book(COST, cover=True, floor=True):
                    return None
                cost = COST
                img = _call(key, prompt, refs=live_refs or None)
            if not img:
                _refund(cost, cover=True)
                print("genimg: model returned no image (failed/flagged "
                      "prediction) — skipping", file=sys.stderr)
                return None
            open(out_path, "wb").write(img)
            _grade(out_path)
            return out_path
        except Exception as e:
            _refund(cost, cover=True)
            print(f"genimg failed ({e})", file=sys.stderr)
            return None
    # Seedream-optimal 5-part structure (subject/action/setting come from the
    # brief; we append composition -> lighting -> lens -> style in that order —
    # the model's documented preference; full doctrine in inspiration/visual.md)
    # Jul 31 rebuild from the @technology reference set: their images are BRIGHT
    # saturated news photos (sunlight, neon pops, vivid product color), never
    # moody low-key dark. The renderer's scrim now does all darkening — the
    # old "lower third falls into pure black" baked dead space into the image.
    prompt = (f"{brief}. "
              "Composition: vertical frame, the subject large, sharp and dominant "
              "in the upper 60%; the bottom 40% stays simple and uncluttered — "
              "a solid headline band covers it completely, so nothing that "
              "matters may live there. Lighting: bright, high-contrast editorial lighting, "
              "colors vivid and saturated with ONE punchy accent color echoing "
              "the subject — energetic like a breaking-news press photo, never "
              "murky, never moody-dark. Background (owner order Aug 3, the $750B "
              "cover shipped near-black murk behind the face): the background is "
              "LOUD and it TELLS THE STORY — it fills the frame edge to edge "
              "with saturated, glowing, colorful imagery of exactly the world "
              "this scene describes (never a different world, never generic "
              "decoration), softly defocused so the subject stays the sharpest "
              "thing in frame. A viewer covering the subject with a thumb must "
              "still guess what the story is about from the background alone. "
              "A dark empty wall, a black void, or a barely-visible backdrop "
              "is a failure. Never white. "
              "Realism: real documentary press photograph, "
              "natural skin texture, slight film grain, ultra detailed — never "
              "concept art, never a sci-fi render, never waxy AI-smooth plastic "
              "skin, no purple-teal sci-fi glow. ONE single photographic frame "
              "of the real physical world: never a comic strip, never multiple "
              "panels, never a cartoon, drawing or illustration of any kind "
              "(Sep 4: a comic-strip cover and a neon-render backdrop each "
              "killed a full posting run at the editor gate). If the scene includes a "
              "quoted phrase on a device screen, render that exact phrase crisply "
              "in a clean system font, perfectly spelled; otherwise the image "
              "contains no text anywhere. Documents, bills, letters, and chat "
              "screens must never show readable text: any paperwork is blank, "
              "turned away, or defocused beyond reading. No watermarks, no "
              "captions, no logos beyond those on the real product.")
    if person and cover:
        # disc clearance (owner Aug 3, the $750B cover: the SpaceX disc
        # clipped Musk's hair): the renderer stamps ~330px logo discs in the
        # two upper corners — the head must never reach them. The person
        # re-draws over the discs anyway (person_layer), but a clean frame
        # beats a repaired one.
        prompt += (" Framing: the person is centered with their head in the "
                   "middle of the upper half; both upper corners of the frame "
                   "stay clear of the person — only background there.")
    if live_refs:
        # identity anchor (Aug 1, keypad post-mortem: from-scratch Altman and
        # an invented purple keypad both failed QA): the refs are REAL photos —
        # the model must copy them, not improvise variants
        prompt += (" The attached reference images are real photographs: "
                   "reproduce the device's exact industrial design, colors and "
                   "proportions from them, and keep any person's facial "
                   "identity exactly identical to their reference photo. "
                   "Never invent a different-looking device or face.")
    _save_prompt(out_path, prompt)
    try:
        img = _call_nano(key, prompt, live_refs)
        if not img:
            # nano flaked: Seedream renders the same brief for $0.03 —
            # always-post rung (E005 can still refuse real names; the outer
            # ladder retries with a rewritten brief in that case)
            _refund(cost, cover=True)
            print("genimg: nano returned no image — retrying brief on Seedream",
                  file=sys.stderr)
            if not _book(COST, cover=True, floor=True):
                return None
            cost = COST
            img = _call(key, prompt, refs=live_refs or None)
        if not img:
            _refund(cost, cover=cover)
            # was silent — the Aug 2 bare-cover post-mortem couldn't see WHY
            print("genimg: model returned no image (failed/flagged prediction) "
                  "— skipping", file=sys.stderr)
            return None
        open(out_path, "wb").write(img)
        return out_path
    except Exception as e:
        _refund(cost, cover=cover)
        print(f"genimg failed ({e})", file=sys.stderr)
        return None
