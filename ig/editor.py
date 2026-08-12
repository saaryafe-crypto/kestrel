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


def gate_a(story, material=""):
    """Story-level verdict BEFORE any writing/images. (approved, reason)."""
    from write import call_claude, CHEAP  # lazy: write.py imports this module
    radar = story.get("radar") or {}
    facts = [f"TITLE: {story.get('title', '')}",
             f"SCOUT INTEREST SCORE: {story.get('interest', '?')}/10"]
    if radar.get("sub"):
        facts.append(f"SOURCE: @{radar['sub']} on X"
                     + (f", {radar.get('score', 0):,} likes" if radar.get("score") else ""))
    if material:
        facts.append(f"SOURCE MATERIAL ({len(material)} chars):\n{material[:900]}")
    prompt = f"""{doctrine()}

----

You are THE EDITOR-IN-CHIEF. The pipeline wants to spend real money writing a full Instagram carousel about the candidate story below. Judge it against STORY LAW (section 1) and THE STANDARD (section 0) above. You own the one question no other stage asks: is this actually a story worth posting?

Be strict on the INSTANT KILL list — reaction-bait and no-substance stories are exactly how this page shipped its two worst posts ever. A KILL costs nothing: the next candidate gets the slot. An APPROVE of junk costs the page its reputation.

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
    view = {"hook": post["slides"][0].get("headline"),
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
                f"connection." if cover_path else
                "WARNING: the cover has NO image file — that alone violates "
                "IMAGE LAW unless zero images existed anywhere.")
    prompt = f"""{doctrine()}

----

You are THE EDITOR-IN-CHIEF doing the final pre-publish review. This finished carousel is minutes from going live to the page's real audience. Judge the WHOLE product against sections 2-5 above (hook, images, storytelling, truth). {img_line}

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
