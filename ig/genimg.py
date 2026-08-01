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

Hard budget guard (owner cap: $9/month, raised from $5 on Jul 28 — "nine
dollars is fine"): monthly AND daily spend tracked in genimg-used.json. No key,
budget out, or API failure -> None and the caller falls back to article
imagery — a posting slot is never blocked. Stdlib only."""
import json, os, sys, time, urllib.request
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
USED = os.path.join(HERE, "genimg-used.json")
# $0.50/day (raised from $0.35 Aug 1: the cap cut the keypad post's
# product-hero cover + CTA mid-run; owner cap is the MONTH number)
MONTH_BUDGET, DAY_BUDGET = 9.00, 0.50
COST = 0.03  # flat per output image, any size
URL = "https://api.replicate.com/v1/models/bytedance/seedream-4/predictions"


def _key():
    if os.environ.get("REPLICATE_API_TOKEN"):
        return os.environ["REPLICATE_API_TOKEN"]
    env = os.path.join(HERE, "..", ".env")
    if os.path.exists(env):
        for line in open(env):
            if line.startswith("REPLICATE_API_TOKEN=") and line.split("=", 1)[1].strip():
                return line.split("=", 1)[1].strip()
    return None


def _spend(cost=None):
    """Month/day totals; with cost, records a new entry."""
    used = json.load(open(USED)) if os.path.exists(USED) else []
    if cost is not None:
        used.append({"date": str(date.today()), "cost": cost})
        json.dump(used, open(USED, "w"))
        return
    today = str(date.today())
    month = today[:7]
    return (sum(u["cost"] for u in used if u["date"][:7] == month),
            sum(u["cost"] for u in used if u["date"] == today))


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
    return None


def generate(brief, out_path, refs=None):
    key = _key()
    if not key:
        return None
    month, day = _spend()
    if month + COST > MONTH_BUDGET or day + COST > DAY_BUDGET:
        print(f"genimg budget out (month ${month:.2f}, today ${day:.2f}) — skipping",
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
              "murky, never moody-dark; background softer and darker than the "
              "subject, never white. Realism: real documentary press photograph, "
              "natural skin texture, slight film grain, ultra detailed — never "
              "concept art, never a sci-fi render, never waxy AI-smooth plastic "
              "skin, no purple-teal sci-fi glow. If the scene includes a "
              "quoted phrase on a device screen, render that exact phrase crisply "
              "in a clean system font, perfectly spelled; otherwise the image "
              "contains no text anywhere. Documents, bills, letters, and chat "
              "screens must never show readable text: any paperwork is blank, "
              "turned away, or defocused beyond reading. No watermarks, no "
              "captions, no logos beyond those on the real product.")
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
        img = _call(key, prompt, refs=live_refs or None)
        if not img:
            return None
        open(out_path, "wb").write(img)
        _spend(COST)
        return out_path
    except Exception as e:
        print(f"genimg failed ({e})", file=sys.stderr)
        return None
