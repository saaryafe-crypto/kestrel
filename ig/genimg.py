#!/usr/bin/env python3
"""Claim-connected slide images via Replicate (ByteDance Seedream-4).
generate(brief, out_path) -> saved jpg path or None.

The reference page's craft: every image is a built VISUALIZATION of the
slide's exact claim (a phone showing "Device Locked" for a lock story) —
never a generic stock photo. Seedream-4 picked Jul 28 over the whole
Replicate catalog: the owner's examples demand brand-accurate real
devices PLUS a short readable screen phrase, Seedream's two strengths.
Near-NB2 quality at $0.03/img (NB2 $0.067 rejected on price; FLUX.2 dev
$0.015 loses the screen-text craft).

Aug 2 addition: gpt-image-2 (person=True) for images featuring FAMOUS PEOPLE.
Measured head-to-head (gangster gas-station test): Seedream rejects any prompt
naming a real person (E005), FLUX 1.1 Pro renders generic lookalikes — gpt-image-2
accepts names directly and nails all three billionaires' likenesses with zero
reference photos. Owner: "i prefer a model that allows that immediately, it
will be much less bugs." Quality: high for covers, medium inside (owner pick).

Hard budget guard (owner cap: $15/month, raised from $9 on Aug 2 for the
gpt-image-2 person covers): monthly AND daily spend tracked in genimg-used.json.
No key, budget out, or API failure -> None and the caller falls back to the
Seedream ref-photo route or article imagery — a posting slot is never blocked.
Stdlib only."""
import json, os, sys, time, urllib.request
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
USED = os.path.join(HERE, "genimg-used.json")
# owner cap is the MONTH number ($15 since Aug 2, gpt-image-2 person covers)
MONTH_BUDGET, DAY_BUDGET = 15.00, 0.30
# Covers get their own, higher daily ceiling (cover-first doctrine, Aug 1):
# inner-slide spend stops at DAY_BUDGET so there is always headroom left for
# every remaining post's cover. Raised Aug 2: a high-quality person cover is
# $0.17, so 3 person covers + Seedream retries must fit.
COVER_DAY_BUDGET = 0.80
COST = 0.03  # Seedream: flat per output image, any size
URL = "https://api.replicate.com/v1/models/bytedance/seedream-4/predictions"
# gpt-image-2 (person route): token-billed by OpenAI; measured ~$0.165/high and
# ~$0.041/medium at 2:3 portrait — booked with headroom so the cap never lies low
GPT_URL = "https://api.replicate.com/v1/models/openai/gpt-image-2/predictions"
GPT_COST = {"high": 0.17, "medium": 0.05}


def _key():
    if os.environ.get("REPLICATE_API_TOKEN"):
        return os.environ["REPLICATE_API_TOKEN"]
    env = os.path.join(HERE, "..", ".env")
    if os.path.exists(env):
        for line in open(env):
            if line.startswith("REPLICATE_API_TOKEN=") and line.split("=", 1)[1].strip():
                return line.split("=", 1)[1].strip()
    return None


def _spend(cost=None, cover=False):
    """Month total + per-lane day totals; with cost, records a new entry.

    Lanes matter (issue #18 post-mortem, Aug 2): the gate used to compare
    TOTAL day spend against the INNER cap, so every cover generated early in
    the day ate the inner allowance and afternoon posts shipped text-only
    inner slides. Entries now carry a "cover" flag; legacy entries without
    one are classified by price (gpt high covers book $0.17)."""
    used = json.load(open(USED)) if os.path.exists(USED) else []
    if cost is not None:
        used.append({"date": str(date.today()), "cost": cost, "cover": cover})
        json.dump(used, open(USED, "w"))
        return
    today = str(date.today())
    month = today[:7]
    is_cover = lambda u: u.get("cover", u["cost"] >= 0.17)
    return (sum(u["cost"] for u in used if u["date"][:7] == month),
            sum(u["cost"] for u in used if u["date"] == today and not is_cover(u)),
            sum(u["cost"] for u in used if u["date"] == today and is_cover(u)))


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
    # screen text crisp (1080-wide test garbled "Device Locked")
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


def _call_gpt(key, prompt, quality):
    """gpt-image-2: the names-allowed person model (Aug 2). No reference
    photos — the model knows famous faces natively, which is the whole point."""
    body = {"input": {"prompt": prompt, "quality": quality, "aspect_ratio": "2:3",
                      "moderation": "low", "output_format": "jpeg",
                      "number_of_images": 1}}
    req = urllib.request.Request(GPT_URL, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {key}",
                                          "Prefer": "wait"})
    with urllib.request.urlopen(req, timeout=180) as r:
        pred = json.loads(r.read())
    for _ in range(40):  # high quality can take ~1-2 min when cold
        if pred.get("status") in ("succeeded", "failed", "canceled"):
            break
        time.sleep(3)
        pred = json.loads(_get(pred["urls"]["get"], key))
    out = pred.get("output")
    if isinstance(out, list):
        out = out[0] if out else None
    if isinstance(out, str) and out.startswith("http"):
        return _get(out)
    print(f"genimg(gpt): prediction {pred.get('status')!r} "
          f"error={pred.get('error')!r}", file=sys.stderr)
    return None


def generate(brief, out_path, refs=None, cover=False, person=False):
    key = _key()
    if not key:
        return None
    month, day_inner, day_cover = _spend()
    # COVER-FIRST (owner Aug 1, Chrome-bugs post-mortem: the daily cap ran out
    # on inner slides of EARLIER posts, so a later post shipped a logo-on-dark
    # cover — "terrible logo and without a cover photo"). Each lane answers
    # only to its OWN daily ceiling (+ the monthly cap): covers can never be
    # starved by inner spend, and inner slides can never be starved by cover
    # spend (issue #18: total-vs-inner-cap comparison broke afternoon posts).
    day = day_cover if cover else day_inner
    day_cap = COVER_DAY_BUDGET if cover else DAY_BUDGET
    # person route (Aug 2): high quality on covers, medium inside — owner pick
    quality = "high" if cover else "medium"
    cost = GPT_COST[quality] if person else COST
    if month + cost > MONTH_BUDGET or day + cost > day_cap:
        print(f"genimg budget out (month ${month:.2f}, today ${day:.2f}, "
              f"{'cover' if cover else 'inner'} cap ${day_cap:.2f}) — skipping",
              file=sys.stderr)
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
              "in the upper two-thirds; the bottom third stays simple and "
              "uncluttered. Lighting: bright, high-contrast editorial lighting, "
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
              "skin, no purple-teal sci-fi glow. If the scene includes a "
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
    live_refs = [r for r in (refs or []) if os.path.exists(r)]
    if live_refs:
        # identity anchor (Aug 1, keypad post-mortem: from-scratch Altman and
        # an invented purple keypad both failed QA): the refs are REAL photos —
        # the model must copy them, not improvise variants
        prompt += (" The attached reference images are real photographs: "
                   "reproduce the device's exact industrial design, colors and "
                   "proportions from them, and keep any person's facial "
                   "identity exactly identical to their reference photo. "
                   "Never invent a different-looking device or face.")
    try:
        img = (_call_gpt(key, prompt, quality) if person
               else _call(key, prompt, refs=live_refs or None))
        if not img:
            # was silent — the Aug 2 bare-cover post-mortem couldn't see WHY
            print("genimg: model returned no image (failed/flagged prediction) "
                  "— skipping", file=sys.stderr)
            return None
        open(out_path, "wb").write(img)
        _spend(cost, cover=cover)
        return out_path
    except Exception as e:
        print(f"genimg failed ({e})", file=sys.stderr)
        return None
