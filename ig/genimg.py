#!/usr/bin/env python3
"""Cover images via Replicate (grok-imagine-image-2 primary; sunburst,
nano-banana, Seedream-4 fallback rungs). generate(brief, out_path) -> jpg
or None.

GROK REGIME (owner verdict Sep 14, closing the 12-way Mamdani-prompt
shootout — his exact words on the grok2-medium render of his verbatim
prompt: "this picture was the best to be honest", minutes after the
sunburst render "wasnt good at all"): every normal cover renders on
xai/grok-imagine-image-2 at quality "medium", 2k, NO reference images —
the winning picture was drawn purely from the full name in the prompt
(grok has no multi-ref input; its single "image" field is edit-mode and
ignores aspect ratio). The old gpt-image burn ($0.17/cover killed the $45
August cap by Aug 29) was the HIGH tier of a different model. The cover
is still the ONLY generated image (Aug 30 regime). Fallback ladder when
grok fails or refuses: sunburst -> nano-banana (both WITH the real press
photo + logo refs) -> Seedream — a cover is never forfeited to one bad
prediction. Recap MONTAGE covers skip grok entirely: a montage is
defined as cutouts of real photos, which grok cannot take.

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
# GROK REGIME (owner verdict Sep 14): generated imagery is the COVER
# ONLY, on grok-imagine-image-2 quality "medium" 2k.
# Realistic run rate: ~9 posts/day x 2-4 QA-gated tries x ~$0.07 =
# ~$1.10-2.20/day => ~$35-65/mo. The MONTH cap is a pure RUNAWAY BRAKE,
# sized so it can never bind under normal operation (Sep 1 post-mortem: the
# $12 cap + $0.90 cover lane starved covers mid-day and posts shipped
# pictureless — the owner's #1 forbidden failure, flagged three times).
# Covers book with floor=True (month brake only); retry counts in the
# callers, not dollars, are what bound spend.
# START: gpt-era ledger entries before this date don't count against the new
# caps (August's $45.31 would otherwise block covers until Sep 1).
START = "2026-08-30"
MONTH_BUDGET, DAY_BUDGET = 100.00, 0.60
COVER_DAY_BUDGET = 3.00  # only binds for non-floor bookings (none today)
COST = 0.03  # Seedream: flat per output image, any size — last fallback rung
URL = "https://api.replicate.com/v1/models/bytedance/seedream-4/predictions"
# nano-banana (primary Aug 30 - Sep 14, now first fallback rung): copies
# likeness from real press photos in faces/ + renders logo refs exactly.
# Billed $0.039, booked with headroom.
NANO_URL = "https://api.replicate.com/v1/models/google/nano-banana/predictions"
NANO_COST = 0.04
# gpt-image-2.5-sunburst (first fallback rung): strong likeness + logo
# accuracy, and it accepts input_images — the real press photo + logo
# marks ride along, so this rung covers the ref lanes grok can't.
# Quality "medium" only; HIGH ($0.21) is what burned August and stays
# banned. Token-billed ~$0.05/img; booked with headroom. moderation
# "low" cuts false refusals on politicians.
SUN_URL = ("https://api.replicate.com/v1/models/"
           "openai/gpt-image-2.5-sunburst/predictions")
SUN_COST = 0.06
# grok-imagine-image-2 (PRIMARY, owner verdict Sep 14: "this picture was
# the best to be honest" on his verbatim Mamdani prompt): best faces and
# logos drawn purely from full names, no refs. quality "medium" is its
# max; 2k keeps the 1080-wide cover window sharp. $0.06 billed at
# medium/2k, booked with headroom.
GROK_URL = ("https://api.replicate.com/v1/models/"
            "xai/grok-imagine-image-2/predictions")
GROK_COST = 0.07

# OWNER FORMAT (Sep 14, doubling down on Sep 10: the owner's own briefs —
# "mamdani banning 600,000 students from using AI (use chatgpt logo), no
# text" and "Sam Altman and Dario agree to slow down ai with claude and
# chatgpt logo no text" — beat our staged-scene prompts cold BOTH times.
# His verdict on our Altman-Dario prompt: "you give him 95% of unnecessary
# bullshit... never assume and tell ai anything. nano banana knows great
# how to create the pictures." So the prompt is the story in plain words
# plus the bare survival rules, NOTHING about colors, drama, lighting or
# composition — the model invents the scene better than we describe it.
# The wrapper is the owner's own prompt, verbatim (Sep 14 pm, his FOURTH
# correction — he showed the old bloated prompt calling it "a very bad
# prompt" and wrote the perfect one himself: "a realistic picture of
# Donald trump is mad screaimng continue showing all ai ceos afraid and
# listeing to him, no text, with relevant ai logos" — and the resulting
# picture WAS perfect: Trump mid-scream, every CEO afraid at the table,
# logos on the wall). Everything we ever added around his words was cut
# on his orders: the "I am going to post a story" preamble, "each at
# most once", "only logos", "no borders, no cartoons", the faceless
# tail, the upper-60% clause. DOCTRINE: never add a clause he didn't
# write — the judge in write.image_score catches borders/cartoons/
# garbled text for free; prompt bloat CAUSES flaws. Emotions and
# reactions in plain words ARE the brief ("mad screaming", "afraid and
# listening") — that is his style, not staging language.
# Covers generate 4:3 to match the photo window they display in.
INTRO = "a realistic picture of "
GUARD = " No text anywhere in the picture."
PERSON_LINE = (
    " The person in the attached reference photo is the story's "
    "protagonist: copy the exact face and hair from the photo, never "
    "redrawn from memory.")
# FACELESS_LINE is DEAD (owner Sep 14: "this is unnecessary... stop
# adding things"). With no reference photo the prompt gets NO tail — the
# judge's face gates in write.image_score still reject wax faces.
FACELESS_LINE = ""
# RECAP MONTAGE (owner Sep 5, Bernie-recap post-mortem: raw tweet images
# glued side by side by CSS — "it looks SO SO bad")
MONTAGE_LINE = (
    " Build the scene ONLY from the attached reference photos: cut each "
    "photo's main subject out — faces and clothing copied exactly, each "
    "photo's own background and lettering discarded — and overlap the "
    "cutouts like a poster, the first photo's subject largest and most "
    "central, each appearing exactly once.")


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
    # 4:3 LANDSCAPE (owner Sep 14, "the way we post them most of the time
    # followers cant really see the picture... where we cut it in half"):
    # since the Sep 9 getintoai band the cover photo displays in a
    # 1080x~800 LANDSCAPE window above the title block — but generation
    # stayed 4:5 portrait (a Sep 7 decision made for the OLD full-bleed
    # display), so every cover lost its bottom ~40% to the window crop.
    # Generate the shape we actually display.
    body = {"input": {"prompt": prompt, "size": "custom",
                      "width": 2048, "height": 1536, "max_images": 1}}
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
    # 4:3 landscape (owner Sep 14): covers display in the 1080x~800
    # landscape photo window above the title block — see _call's comment
    body = {"input": {"prompt": prompt, "aspect_ratio": "4:3",
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


def _call_grok(key, prompt):
    """xai/grok-imagine-image-2 (PRIMARY, owner Sep 14): quality "medium"
    (its max), 2k, 4:3, NO refs — likeness and logos are drawn from the
    full names in the prompt, exactly the configuration that won."""
    body = {"input": {"prompt": prompt, "quality": "medium",
                      "resolution": "2k", "aspect_ratio": "4:3"}}
    req = urllib.request.Request(GROK_URL, data=json.dumps(body).encode(),
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
    print(f"genimg(grok): prediction {pred.get('status')!r} "
          f"error={pred.get('error')!r}", file=sys.stderr)
    return None


def _call_sunburst(key, prompt, refs):
    """openai/gpt-image-2.5-sunburst (PRIMARY, owner Sep 14): quality
    "medium" matches the ChatGPT app's look at ~$0.05; refs (press photo +
    real logo mark) ride as input_images so faces/logos are copied, not
    memory-drawn. moderation "low" cuts false refusals on politicians."""
    body = {"input": {"prompt": prompt, "quality": "medium",
                      "aspect_ratio": "4:3", "output_format": "jpeg",
                      "moderation": "low"}}
    if refs:
        body["input"]["input_images"] = [_data_uri(r) for r in refs[:3]]
    req = urllib.request.Request(SUN_URL, data=json.dumps(body).encode(),
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
    print(f"genimg(sunburst): prediction {pred.get('status')!r} "
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
             collage=False, montage=False, named_brief=None):
    key = _key()
    if not key:
        return None
    # COVER-FIRST (owner Aug 1, Chrome-bugs post-mortem: the daily cap ran out
    # on inner slides of EARLIER posts, so a later post shipped a logo-on-dark
    # cover — "terrible logo and without a cover photo"). Each lane answers
    # only to its OWN daily ceiling (+ the monthly cap, both enforced inside
    # _book): covers can never be starved by inner spend, and inner slides can
    # never be starved by cover spend (issue #18 post-mortem).
    # GROK REGIME (owner verdict Sep 14): the COVER is the only generated
    # image (Aug 30 rule stands). Ladder: grok (bare prompt, no refs — the
    # winning configuration) -> sunburst -> nano (both with refs) ->
    # Seedream, refunding each dead rung. Montage covers skip grok: they
    # are DEFINED as cutouts of real photos, which grok can't take.
    if not cover:
        return None
    live_refs = [r for r in (refs or []) if os.path.exists(r)]
    if montage and not live_refs:
        # with no refs a montage would memory-draw every face (the exact
        # Bernie-wax failure)
        print("genimg: montage with no live refs — refusing", file=sys.stderr)
        return None
    # OWNER FORMAT (Sep 10): one prompt path for every cover, every lane.
    # The collage flag no longer branches — the edu lane never passed it and
    # shipped the old 300-word scaffold on the NYC-ban cover. Person line
    # ONLY when a real reference photo actually rides along on a ref rung;
    # the grok rung sends no photo, so its prompt gets NO tail (owner Sep
    # 14) — the judge still rejects wax faces.
    if montage:
        tail = MONTAGE_LINE
    else:
        tail = PERSON_LINE if (person and live_refs) else FACELESS_LINE
    core = f"{INTRO}{brief.strip().rstrip('.')}."
    bare = f"{core}{GUARD}"
    tailed = f"{core}{tail}{GUARD}"
    # GROK NAME LAW (run 34920134374 post-mortem, Sep 15: a stranger-face
    # 2/10 cover shipped): grok takes NO reference photos — its likeness
    # comes ONLY from full names in the prompt (the owner's winning Trump
    # config). Callers scrub names to "the person in the reference photo"
    # for the E005/ref rungs, so grok must get the UNSCRUBBED brief via
    # named_brief. A scrubbed brief that points at a photo grok can't see
    # is a stranger factory — skip the grok rung entirely in that case.
    if named_brief:
        grok_prompt = f"{INTRO}{named_brief.strip().rstrip('.')}.{GUARD}"
    else:
        grok_prompt = bare if "reference photo" not in brief else None
    rungs = [] if (montage or not grok_prompt) else [
        ("grok", GROK_COST, lambda: _call_grok(key, grok_prompt), grok_prompt)]
    rungs += [
        ("sunburst", SUN_COST, lambda: _call_sunburst(key, tailed, live_refs),
         tailed),
        ("nano", NANO_COST, lambda: _call_nano(key, tailed, live_refs),
         tailed)]
    if not montage:
        rungs.append(("seedream", COST,
                      lambda: _call(key, tailed, refs=live_refs or None),
                      tailed))
    for name, cost, call, prompt in rungs:
        # floor=True: covers are NEVER starved by a daily dollar cap (Sep 1
        # post-mortem: the cover lane died mid-day under QA retries and 4
        # posts shipped pictureless — the owner's #1 forbidden failure).
        # Spend is bounded structurally: the callers cap attempts per
        # cover, so only the month backstop can stop a booking.
        if not _book(cost, cover=True, floor=True):
            print("genimg: skipping (budget out)", file=sys.stderr)
            return None
        # the sidecar always shows the prompt of the rung that actually
        # rendered (owner monitor email quotes it)
        _save_prompt(out_path, prompt)
        try:
            img = call()
        except Exception as e:
            img = None
            print(f"genimg({name}) failed ({e})", file=sys.stderr)
        if img:
            open(out_path, "wb").write(img)
            _grade(out_path)
            return out_path
        _refund(cost, cover=True)
        print(f"genimg: {name} returned no image — next rung", file=sys.stderr)
    return None
