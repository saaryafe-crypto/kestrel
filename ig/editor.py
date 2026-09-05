"""editor.py — the editor-in-chief (owner order Aug 4 2026).

Born from the Queen Elizabeth / Mario Lopez post-mortem: ten specialist
Claude calls each judged one narrow thing, nobody owned "should this exist?",
and the one generalist verdict (scout interest 4/10) was advisory. This
module is the missing decision-maker. It judges ONLY against ig/doctrine.md
(the single owner-approved definition of a winning post) and its verdicts
are BINDING:

  GATE A (story) — runs inside pick_story before a cent is spent. KILL means
  the picker takes the next candidate. Cheap: one text call per candidate.

  GATE B (final product) — runs on the finished post: hook, every slide, the
  actual cover image (vision). REJECT returns specific fixable reasons that
  feed the repair pass; exhausted retries fall down the workflow's existing
  always-post ladder (write.py exits nonzero -> edu.py fills the slot).

Fail-open discipline (owner rule: 7/day is a MUST — a dead editor must not
starve the page): if the Claude call itself errors, the gate approves but
flags the post (editor_down) so the daily report names it. A working editor
saying KILL is binding; a broken editor never blocks the slot.

Every verdict is appended to editor-log.json — the audit trail that answers
"who decided this post goes out and why" for any post, forever.
"""
import glob
import json
import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "editor-log.json")
# gate A verdicts arrive from parallel threads (pick_story batches, Aug 12):
# the audit log's read-modify-write must be atomic or verdicts get lost
_LOG_LOCK = threading.Lock()

GATE_A_SCHEMA = {
    "type": "object",
    "properties": {"verdict": {"type": "string", "enum": ["APPROVE", "KILL"]},
                   "reason": {"type": "string"}},
    "required": ["verdict", "reason"],
}
GATE_B_SCHEMA = {
    "type": "object",
    "properties": {"verdict": {"type": "string", "enum": ["APPROVE", "REJECT"]},
                   "reasons": {"type": "array", "items": {"type": "string"}}},
    "required": ["verdict", "reasons"],
}


def doctrine():
    return open(os.path.join(HERE, "doctrine.md")).read()


def _log(gate, subject, verdict, reason):
    with _LOG_LOCK:
        try:
            rows = json.load(open(LOG)) if os.path.exists(LOG) else []
        except Exception:
            rows = []
        rows.append({"t": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                     "gate": gate, "subject": subject[:120], "verdict": verdict,
                     "reason": reason})
        json.dump(rows[-300:], open(LOG, "w"), indent=1, ensure_ascii=False)


def _guides_today():
    """How many slots already fell to edu guides today (committed archive)."""
    day = time.strftime("%Y-%m-%d", time.gmtime())
    return len(glob.glob(os.path.join(HERE, "posts", f"{day}-edu-*")))


def gate_a(story, material=""):
    """Story-level verdict BEFORE any writing/images. (approved, reason)."""
    from write import call_claude, CHEAP  # lazy: write.py imports this module
    radar = story.get("radar") or {}
    # NEWS PAGE FIRST mechanics (owner order Sep 3 — the Sep 1 doctrine
    # calibration note alone did NOT move the needle: 244/246 kills since
    # Aug 27 and a guide flood). A top-scored non-evergreen story from the
    # watchlist skips the kill question entirely: the scout already ranked
    # it the day's best news, and a wrong KILL costs more than a wrong pass
    # (Gate B still reviews the finished product).
    try:
        interest = float(story.get("interest", 0) or 0)
    except (TypeError, ValueError):
        interest = 0.0
    if interest >= 8 and not story.get("evergreen"):
        _log("A", story.get("title", ""), "AUTO_APPROVE",
             f"scout interest {interest:g}/10 — news-first fast lane")
        print(f"editor gate A: AUTO_APPROVE — interest {interest:g}/10",
              file=sys.stderr)
        return True, "auto-approved: top-scored news story"
    facts = [f"TITLE: {story.get('title', '')}",
             f"SCOUT INTEREST SCORE: {story.get('interest', '?')}/10"]
    if story.get("evergreen"):
        # goats-on-Etna hardening (owner Aug 28): wide-net evergreen picks
        # are the lane that shipped an off-lens nature story — name the lane
        # so the editor applies §1's STAR test at full strictness.
        facts.append("LANE: evergreen wow-fact/story-arc from the wide X net "
                     "— apply STORY LAW's off-lens kill STRICTLY: the "
                     "subject must BE AI, tech, a company/founder, "
                     "investing, or space technology. A story that merely "
                     "mentions or defeats technology is a KILL, however "
                     "viral.")
    if radar.get("sub"):
        facts.append(f"SOURCE: @{radar['sub']} on X"
                     + (f", {radar.get('score', 0):,} likes" if radar.get("score") else ""))
    if story.get("consensus"):
        facts.append(f"CONSENSUS: {story['consensus']} different watchlist "
                     f"accounts ran this same story independently — the "
                     f"strongest available signal that it is the day's real "
                     f"news.")
    if material:
        facts.append(f"SOURCE MATERIAL ({len(material)} chars):\n{material[:900]}")
    guides = _guides_today()
    if guides:
        facts.append(f"PAGE STATE: {guides} slot(s) already fell to edu-guide "
                     f"listicles TODAY. Every KILL you issue pushes this slot "
                     f"toward yet another guide — the repetition the owner "
                     f"named the page's #1 content failure. Weigh that real "
                     f"cost before killing a famous-actor news event.")
    prompt = f"""{doctrine()}

----

You are THE EDITOR-IN-CHIEF. The pipeline wants to spend real money writing a full Instagram carousel about the candidate story below. Judge it against STORY LAW (section 1) and THE STANDARD (section 0) above. You own the one question no other stage asks: is this actually a story worth posting?

Be strict on the INSTANT KILL list — reaction-bait and no-substance stories are exactly how this page shipped its two worst posts ever. But a KILL is not free either: when every candidate dies, the slot falls to the edu-listicle floor, and on Sep 1 this gate killed 39 of 40 candidates (including "Sony sues Anthropic") and the page shipped a day of repetitive listicles — the exact failure the owner flagged as the page's #1 content problem. Apply §1's CALIBRATION: judge the EVENT, not the tweet's length. Both wrong verdicts cost the page; own the one you choose.

CANDIDATE:
{chr(10).join(facts)}

Return JSON: {{"verdict": "APPROVE" or "KILL", "reason": "<one plain sentence>"}}"""
    try:
        r = call_claude(prompt, schema=GATE_A_SCHEMA, model=CHEAP)
        ok = r["verdict"] == "APPROVE"
        _log("A", story.get("title", ""), r["verdict"], r["reason"])
        print(f"editor gate A: {r['verdict']} — {r['reason']}", file=sys.stderr)
        return ok, r["reason"]
    except Exception as e:
        _log("A", story.get("title", ""), "EDITOR_DOWN", str(e)[:200])
        print(f"editor gate A DOWN ({e}) — failing open", file=sys.stderr)
        return True, "editor_down"


def gate_b(post, cover_path=None):
    """Final-product verdict on the finished post. (approved, reasons)."""
    from write import call_claude
    view = {"container": post.get("container"),
            "hook": post["slides"][0].get("headline"),
            "kicker": post["slides"][0].get("kicker"),
            "cover_has_image": bool(post["slides"][0].get("media")),
            "slides": [{"type": s.get("type"), "headline": s.get("headline"),
                        "body": s.get("body"),
                        "has_image": bool(s.get("media") or s.get("image_brief"))}
                       for s in post["slides"]],
            "caption": post.get("caption", "")[:400]
                       + (" [...caption trimmed for review — do not judge its"
                          " ending]" if len(post.get("caption", "")) > 400
                          else "")}
    img_line = (f"The post's ACTUAL COVER IMAGE is attached — judge it against "
                f"IMAGE LAW with your own eyes (if no image is attached to "
                f"this message, use your Read tool on {cover_path} to look at "
                f"it). CAST TRUTH: if a recognizable famous person is the "
                f"cover subject but that person has no role in this story, "
                f"REJECT — a celebrity as decoration breaks image-headline "
                f"connection. EXCEPTION — THE VENDOR CAST (the owner's "
                f"signature move, order Aug 12, and the DEFAULT for every "
                f"guide/education cover): on a post teaching the use of a "
                f"named famous tool, that tool's own famous CEO cast as the "
                f"tool's delighted user (Dario Amodei for a Claude guide, "
                f"Sam Altman for ChatGPT, Sundar Pichai for Gemini) is "
                f"LEGAL — never reject it as cast-truth. Cast truth still "
                f"kills the WRONG company's face (Sam Altman fronting an "
                f"Anthropic story is a REJECT)." if cover_path else
                "WARNING: the cover has NO image file — that alone violates "
                "IMAGE LAW unless zero images existed anywhere.")
    # container-blind judging post-mortem (Aug 27 audit): Gate B rejected
    # 67/71 ai_education posts on the story-post shuffle test — a numbered
    # list IS that container's legal structure — and edu.py's override shipped
    # them all flagged. Two weeks of REJECT-everything killed the alarm's
    # signal. Tell the editor which law applies so a real REJECT means
    # something again.
    container_note = ""
    if post.get("container") == "ai_education":
        container_note = (
            "\n\nCONTAINER NOTE: this post is the ai_education container — a "
            "save-magnet listicle. A numbered list of independent items is its "
            "LEGAL structure: do NOT reject it for failing section 4's shuffle "
            "test or story-arc rules, which are story-post law. Everything "
            "else fully applies: language law, truth law, image law, the "
            "cover contract, and the save-close.")
    elif post.get("container") == "daily_recap":
        container_note = (
            "\n\nCONTAINER NOTE: this post is the daily_recap container — the "
            "day's-biggest-stories roundup the owner turned ON Aug 27 (the "
            "competitor audit measured recap at 2,555 median likes/1M; "
            "@technology's two biggest posts ever are roundups). Independent "
            "story slides ARE its legal structure: do NOT reject it for "
            "failing section 4's shuffle test, story-arc rules, or section "
            "1's roundup/already-published kills — covering the day's stories "
            "again IS the format. A payload slide with NO image renders as a "
            "big-type slide — legal here when that story has no press photo "
            "(image law's own no-image-beats-bad-image rule), so never "
            "reject solely for a missing slide image. Everything else fully "
            "applies: language law, truth law, image law on the images that "
            "DO exist, hook law per slide, and the save-close.")
    prompt = f"""{doctrine()}

----

You are THE EDITOR-IN-CHIEF doing the final pre-publish review. This finished carousel is minutes from going live to the page's real audience. Judge the WHOLE product against sections 2-5 above (hook, images, storytelling, truth). {img_line}{container_note}

The bar is section 0: would the owner look at this and post it himself? You are the last line — every earlier gate already passed this post, and the two worst posts in the page's history passed every earlier gate too.

REJECT reasons must be SPECIFIC and FIXABLE ("slide 3 body repeats the cover's $2B figure", "hook's payoff is a like-count"), because they drive a surgical repair pass. Do not invent nitpicks on a post that meets the law: a clean APPROVE is a valid verdict.

THE FINISHED POST:
{json.dumps(view, ensure_ascii=False, indent=1)}

Return JSON: {{"verdict": "APPROVE" or "REJECT", "reasons": ["..."]}} (reasons empty on APPROVE)."""
    try:
        r = call_claude(prompt, schema=GATE_B_SCHEMA,
                        images=[cover_path] if cover_path else None)
        ok = r["verdict"] == "APPROVE"
        _log("B", post["slides"][0].get("headline") or "", r["verdict"],
             "; ".join(r["reasons"])[:400])
        print(f"editor gate B: {r['verdict']}"
              + ("" if ok else " — " + "; ".join(r["reasons"])), file=sys.stderr)
        return ok, r["reasons"]
    except Exception as e:
        _log("B", post["slides"][0].get("headline") or "", "EDITOR_DOWN",
             str(e)[:200])
        print(f"editor gate B DOWN ({e}) — failing open", file=sys.stderr)
        post["editor_down"] = True  # daily report names it
        return True, []


GATE_R_SCHEMA = {
    "type": "object",
    "properties": {"slides": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "n": {"type": "integer"},
            "verdict": {"type": "string", "enum": ["PASS", "FAIL"]},
            "action": {"type": "string",
                       "enum": ["none", "drop_image", "retext"]},
            "reason": {"type": "string"}},
        "required": ["n", "verdict", "action", "reason"]}}},
    "required": ["slides"],
}


def _shrink(jpg, out):
    """Downscale a slide to 540px wide for judging — same verdict quality,
    ~4x fewer image tokens (Gate R budget: cents per post, not dimes)."""
    import subprocess
    if sys.platform == "darwin":
        subprocess.run(["sips", "--resampleWidth", "540", jpg, "--out", out],
                       check=True, capture_output=True)
    else:
        from PIL import Image
        im = Image.open(out if os.path.exists(out) else jpg)
        im.thumbnail((540, 10000))
        im.convert("RGB").save(out, quality=85)
    return out


def gate_r(post, post_dir):
    """GATE R — reference-level review of the RENDERED slides (owner order
    Sep 5, Bernie-recap post-mortem: a text screenshot shipped as half a
    cover and NOBODY had ever looked at a finished inner slide — Gate B is
    text + cover-only). Every slide JPEG goes to the vision judge, judged
    against the owner's reference wall standard. Returns the list of FAIL
    dicts ({n, action, reason}); callers apply drop_image/retext, re-render
    once, and ship FLAGGED if still failing — a slot is never skipped.
    Fail-open like every editor gate: a dead judge never blocks the page."""
    from write import call_claude
    jpgs = sorted(glob.glob(os.path.join(post_dir, "slide-*.jpg")),
                  key=lambda p: int(p.split("-")[-1][:-4]))
    if not jpgs:
        return []
    import tempfile
    tmp = tempfile.mkdtemp()
    small = []
    for j in jpgs:
        try:
            small.append(_shrink(j, os.path.join(tmp, os.path.basename(j))))
        except Exception:
            small.append(j)  # judge full-size rather than skip the slide
    prompt = f"""You are the visual quality gate of a top tech news Instagram page. Attached are ALL {len(small)} rendered slides of a finished carousel, in order (image 1 = slide 1 = the cover). If no images are attached to this message, use your Read tool to look at every one of these files in order: {json.dumps(small)}. The page's standard is @technology-level: every slide must look like it came from a professional news channel.

JUDGE EVERY SLIDE against this rubric:
- THE RECEIPT LAW: an inner slide's picture must PROVE that slide's own claim (real press moment of the slide's actor, source footage on a card, a typeset X card, or the story's object). A picture that is unrelated decoration for its slide's words is a FAIL.
- SCREENSHOT LAW: a raw screenshot of text/UI/a webpage as a full-bleed background or as any part of the cover is an instant FAIL (action drop_image). A screenshot framed on a rounded card is legal.
- LEGIBILITY: the headline and body must read clearly against the image. Text drowning in a busy or bright photo zone = FAIL.
- PHOTO QUALITY: murky/dark/blurry photos, garbled AI text, cartoon or wax-figure faces, amputated heads = FAIL. Bright saturated press-photo energy = the standard.
- EMOTIONAL REGISTER: the photo's mood must match the slide's claim (a grinning photo on a death/lawsuit slide = FAIL).
- MOOD FLOOR: dark text-only slides are legal (big-type slides). Judge only what is actually wrong; a clean PASS is a valid verdict. Never invent nitpicks invisible at phone size.

ACTIONS: drop_image = the slide reads better with no image (text-only) than with this image. retext = the image is fine, the TEXT placement/content is the problem. none = PASS.

THE POST (container: {post.get('container')}): slide headlines in order:
{json.dumps([{"n": i + 1, "type": s.get("type"), "headline": s.get("headline", "")[:80]} for i, s in enumerate(post.get("slides", []))], ensure_ascii=False)}

Return JSON: {{"slides": [{{"n": <slide number>, "verdict": "PASS" or "FAIL", "action": "none"/"drop_image"/"retext", "reason": "<specific, one sentence>"}}]}} — one entry per slide, all {len(small)} of them."""
    try:
        r = call_claude(prompt, schema=GATE_R_SCHEMA, images=small)
        fails = [x for x in r.get("slides", [])
                 if x.get("verdict") == "FAIL"]
        _log("R", post["slides"][0].get("headline") or "",
             "FAIL" if fails else "PASS",
             "; ".join(f"s{x['n']}: {x['reason']}" for x in fails)[:400])
        print("editor gate R: " + ("PASS" if not fails else "FAIL — "
              + "; ".join(f"slide {x['n']}: {x['reason']}" for x in fails)),
              file=sys.stderr)
        return fails
    except Exception as e:
        _log("R", post["slides"][0].get("headline") or "", "EDITOR_DOWN",
             str(e)[:200])
        print(f"editor gate R DOWN ({e}) — failing open", file=sys.stderr)
        post["editor_down"] = True
        return []


def apply_gate_r(post, fails):
    """Apply Gate R's mechanical repairs. drop_image strips the slide's
    image (doctrine's own no-image-beats-bad-image rule — a clean big-type
    slide beats a murky/garbled/wrong-mood picture). Everything else is
    recorded on the post for the daily report — the slot always ships.
    Returns True when a slide changed and the caller must re-render."""
    changed = False
    for f in fails:
        i = f.get("n", 0) - 1
        if f.get("action") == "drop_image" and 0 <= i < len(post["slides"]):
            s = post["slides"][i]
            s["media"] = None
            for k in ("layout", "cutout", "person_layer"):
                s.pop(k, None)
            changed = True
    if fails:
        post["gate_r"] = "; ".join(
            f"s{f['n']}: {f['reason']}" for f in fails)[:400]
    return changed
