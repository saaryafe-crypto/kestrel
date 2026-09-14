#!/usr/bin/env python3
"""Daily recap: "WHAT JUST HAPPENED IN AI TODAY?"
Usage: python3 recap.py [stories.json]

Turned back ON Aug 27 under the owner's match-the-data order ("did they post
mostly news? post mostly news" — align the machine to the measured competitor
numbers). The Aug 27 audit (134 posts, 14 accounts): recap = 2,555 median
likes/1M (3rd-strongest content type), @technology runs 3 roundups per 12
posts and their two biggest posts EVER are roundups (88K/84K likes vs their
36K median). The Jul 31 removal predates this data.

Runs at the 01:00 UTC slot (~9pm ET — a measured competitor posting peak we
used to skip entirely). Sources = stories.json: the day's viral X stories,
scout-ranked. Re-covering a story that already ran solo IS the roundup format
(gate B carries a daily_recap container note for exactly this).

Modern pipeline parity: doctrine law() in the writer prompt, mechanical QA,
editor Gate B on the RENDERED cover, surgical qa_repair rounds, dash scrub.
Failure exits nonzero -> the workflow ladder's next rung (write.py news)
fills the slot — always-post law intact.

SINGLE-PICTURE POSTS (owner order Sep 14, round 2: inner slides "never reach
Instagram... this is stupid" — production killed, not just publishing): the
writer picks the stories and writes the CAPTION (one line per story — the
caption IS the roundup); the only rendered slide is the fixed cover. Press
photos are still downloaded — the montage cover is built from them.
"""
import json, os, re, subprocess, sys
from datetime import date, timedelta

from fetch import get
from viral import law
from write import (call_claude, scrub_dashes, qa_repair, image_score,
                   is_dupe, emergency_cover, CHEAP)

HERE = os.path.dirname(os.path.abspath(__file__))
N_CANDS = 12        # candidates offered to the writer
N_STORIES = (5, 8)  # roundup stories wanted (one caption line each)

COVER = {
    "type": "cover", "hsize": 62,
    "headline": "WHAT JUST HAPPENED IN <em>AI</em> TODAY?",
    "kicker": "THE DAILY RECAP",
}

RECAP_SCHEMA = {
    "type": "object",
    "properties": {
        # single-picture posts (Sep 14): no slides from the writer. "stories"
        # = the picked roundup items — they steer the cover montage, feed the
        # dupe memory, and never render; only the cover + caption publish.
        "stories": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "idx": {"type": "integer"},
                    "headline": {"type": "string"},
                },
                "required": ["idx", "headline"],
            },
        },
        "caption": {"type": "string"},
        "pinned_comment": {"type": "string"},
    },
    "required": ["stories", "caption", "pinned_comment"],
}


def is_photo(path):
    """SCREENSHOT FILTER (owner Sep 5, Bernie-recap post-mortem: a raw text
    screenshot shipped as half the cover — doctrine already said screenshots
    are never a cover, but nothing ENFORCED it on downloaded tweet images).
    True = a real photograph of people/places/things, legal on covers and
    full-bleed. False = a screenshot of text/UI/a tweet/a chart — evidence
    material only, framed small, never the face of anything. Fails open as
    NOT-photo: an unclassifiable image must not become a cover."""
    try:
        r = call_claude(
            "Classify the attached image (if none is attached to this "
            f"message, use your Read tool on {path} to look at it). "
            "PHOTOGRAPH = a camera picture of people, places or physical "
            "things. SCREENSHOT = text, app UI, a tweet, a chat, a chart, "
            "a webpage. An image that is mostly readable text or interface "
            "is a SCREENSHOT even if it contains a small photo. Return "
            'ONLY JSON: {"kind": "PHOTOGRAPH"} or {"kind": "SCREENSHOT"}',
            images=[path], model=CHEAP,
            schema={"type": "object", "properties": {"kind": {
                        "type": "string",
                        "enum": ["PHOTOGRAPH", "SCREENSHOT"]}},
                    "required": ["kind"]})
        return r.get("kind") == "PHOTOGRAPH"
    except Exception as e:
        print(f"  is_photo failed ({e}) — treating as screenshot",
              file=sys.stderr)
        return False


def prev_recap_slides(days=7):
    """Slide headlines from PREVIOUS recaps (last `days` days, excluding
    today's). HARD RULE (owner Sep 5): recap may re-cover stories that ran
    SOLO — that's the roundup format (owner Aug 27) — but it must never
    repeat a story from an earlier recap. So the dupe filter compares
    candidates against past recap slides ONLY, not against solo posts."""
    posts = os.path.join(HERE, "posts")
    if not os.path.isdir(posts):
        return []
    horizon = str(date.today() - timedelta(days=days))
    today = str(date.today())
    out = []
    for d in sorted(os.listdir(posts)):
        if "ai-recap" not in d or d[:10] < horizon or d[:10] >= today:
            continue
        try:
            rp = json.load(open(os.path.join(posts, d, "post.json")))
            # old carousel recaps: inner slides (skip cover + CTA);
            # single-picture recaps (Sep 14+): the "stories" picks
            heads = [s.get("headline", "")
                     for s in rp.get("slides", [])[1:-1]]
            heads += [s.get("headline", "") for s in rp.get("stories", [])]
            for h in heads:
                h = re.sub(r"<[^>]+>", "", h).strip()
                if h:
                    out.append(h[:90])
        except Exception:
            pass
    return out


def pick_candidates(stories):
    ranked = sorted(stories, key=lambda s: (not s.get("image"), -s["score"]))
    prev = prev_recap_slides()
    if prev:
        kept = []
        for s in ranked:
            if len(kept) >= N_CANDS:
                break
            if is_dupe(s["title"], recent=prev):
                print(f"  recap dupe (ran in earlier recap): {s['title'][:70]}",
                      file=sys.stderr)
                continue
            kept.append(s)
        return kept
    return ranked[:N_CANDS]


def build_prompt(cands):
    spec = json.load(open(os.path.join(HERE, "containers.json")))
    lines = []
    for i, s in enumerate(cands):
        r = s.get("radar") or {}
        proof = f" [{r['score']:,} likes on X]" if r.get("score") else ""
        body = r.get("selftext") or ""
        lines.append(f"[{i}] {'(has press image) ' if s.get('image') else ''}"
                     f"{s['title']}{proof}\n    "
                     f"{body[:500] or '(no tweet text — use title only)'}")
    stories_block = "\n".join(lines)
    return f"""{law()}You write single-picture Instagram posts for @yaffeai. Today's post is the **daily_recap** container: "WHAT JUST HAPPENED IN AI TODAY?" — the day's biggest stories in ONE post. The cover is fixed (rendered separately) and THE CAPTION IS THE POST (owner order Sep 14: no inner slides exist) — you write ONLY the story picks, the caption, and the pinned comment.

CONTAINER SPEC: {json.dumps(spec['containers'].get('daily_recap', {}))}
CAPTION BLOCKS: {json.dumps(spec['caption_blocks'])}

CANDIDATE STORIES (today's most viral, ranked; likes = real X engagement):
{stories_block}

Pick the {N_STORIES[0]}-{N_STORIES[1]} strongest, most DIFFERENT stories (never two angles on the same story). Strongest = what a normal person feels: their money, phone, job, apps they use, or names everyone knows. Prefer candidates with a press image. Strongest story first.

OUTPUT — a single JSON object: {{"stories": [...], "caption": "...", "pinned_comment": "..."}}
Each story pick: {{"idx": <candidate number>, "headline": "..."}} — headline = the story's wild claim in 6-12 words, PLAIN TEXT, no markup (it steers the cover montage and the dupe log; it never renders on a slide).

RULES
- LANGUAGE: write for a smart 12-year-old (owner Sep 9). Everyday words, short sentences, no jargon. Section 7 of the law fully applies. The editor's three most common kills, banned outright: hedge words (may/might/could/reportedly), news-agency verbs (announced/unveiled/revealed — say what happened in spoken words), and "-ing" consequence padding tacked onto a sentence (give the consequence its own short sentence).
- Never invent facts beyond the titles/tweet texts above.
- Caption: first line keeps the MEASURED winner shape (@technology's 67K-like roundup, ~2x their median; audit Aug 27) MINUS the swipe (single-picture posts — nothing to swipe): "Here's what happened in AI in the last 24 hours, from <teaser A> to <teaser B> 👇" — keep the last-24-hours + from-X-to-Y shape, vary the wording, teasers = the two wildest stories; then the story block: ONE SHORT LINE PER PICKED STORY, strongest first, every key number and name kept — the caption alone delivers the whole day; the trend block's LAST line invites business owners to DM — pain + tiny ask. Register: "Running a business? DM us "AI" and we'll show you what this could do for yours". Vary the wording per post, keep the DM word exactly "AI" IN DOUBLE QUOTES. Sources line names the X accounts as plain names (never @). Exactly five hashtags. The caption is plain text — no <em>/<b> markup anywhere in it.
- pinned_comment: ONE debatable question about the day's biggest story, 1-2 sentences, no hashtags, no links.

Return ONLY the JSON object."""


def qa(post, n_cands, pre_render=True):
    # .get, never [] — the CLI path enforces no schema, and a shapeless reply
    # must fail QA (feeding the retry loop) instead of crashing the run
    # (test 2, Aug 27: KeyError 'slides' killed attempt 1 outright)
    stories = post.get("stories") or []
    caption, errs = post.get("caption", ""), []
    if not (N_STORIES[0] <= len(stories) <= N_STORIES[1]):
        errs.append(f"{len(stories)} story picks (want "
                    f"{N_STORIES[0]}-{N_STORIES[1]})")
    for i, s in enumerate(stories):
        if not (s.get("headline") or "").strip():
            errs.append(f"story {i + 1}: empty headline")
        # idx exists only pre-render (main pops it when downloading images),
        # so the post-repair re-check passes pre_render=False — an
        # unconditional idx check made every successful Gate B repair revert
        # (test 3, Aug 27)
        if pre_render and not (0 <= s.get("idx", -1) < n_cands):
            errs.append(f"story {i + 1}: bad candidate idx")
    # free regex gates for the editor's most common text-law kills, now on
    # the CAPTION — it is the post (test 4, Aug 27: Gate B burned both
    # repair rounds on exactly these)
    if re.search(r"(?i)\b(allegedly|according to|sources say|is said to)\b",
                 caption):
        errs.append("caption: hedge phrase (allegedly/according to/sources "
                    "say...) — state the fact straight or cut it")
    if re.search(r"(?i)\b(announced|unveiled|revealed|stated)\b", caption):
        errs.append("caption: news-agency register (announced/unveiled...) "
                    "— say what actually happened in spoken words")
    if "<em>" in caption or "<b>" in caption:
        errs.append("caption contains markup — the caption is plain text")
    if "Sources:" not in caption:
        errs.append("caption missing Sources line")
    if len(re.findall(r"#\w+", caption)) != 5:
        errs.append("caption must have exactly 5 hashtags")
    # curly-quote tolerant: writers often render "AI" as “AI” (test Aug 27:
    # a straight-quote-only check failed 3/3 attempts on the same caption)
    if not re.search(r'[\"“”\']AI[\"“”\']', caption):
        errs.append('caption missing the owner DM-CTA line: it must invite a '
                    'DM of the word "AI" in quotes, e.g. DM us "AI"')
    if not post.get("pinned_comment", "").strip():
        errs.append("missing pinned_comment")
    return errs


def build_cover(post_dir, photos, headlines):
    """MONTAGE COVER (owner Sep 5, Bernie-recap post-mortem: raw tweet
    images glued side by side by CSS shipped a text screenshot as half the
    cover — "it looks SO SO bad"). The reference roundup cover is a composed
    poster: each story's subject razor-cut from its real press photo,
    arranged at varying scales on one loud backdrop, headline zone clean
    (golden example, owner Sep 8: the @technology aircraft-roundup cover —
    the subjects of the list ARE the cover, headline accent color pulled
    from the picture's own palette).
    Ladder: nano-banana montage from the day's verified press PHOTOS (2
    tries, judged) -> strongest single photo IF it passes the cover judge ->
    generated faceless objects-montage from the day's headlines -> bare art
    cover. The CSS strip collage is dead — it can never ship again."""
    import genimg
    cover = dict(COVER)
    plain = lambda h: re.sub(r"<[^>]+>", "", h)
    if len(photos) >= 2:
        # 2 refs max: the Sep 5 smoke test with 3 face refs duplicated one
        # identity and dropped another — two is nano's reliable ceiling
        refs = [p for _, p in photos[:2]]
        brief = ("Montage of today's biggest AI news stories, one subject "
                 "cut from each attached photo. Stories in order of size: "
                 + "; ".join(plain(h) for h, _ in photos[:2])
                 + ". Backdrop palette: electric blue and orange, "
                   "AI-datacenter energy")
        out = os.path.join(post_dir, "cover-montage.jpg")
        for attempt in range(2):
            path = genimg.generate(brief, out, refs=refs, cover=True,
                                   montage=True)
            if not path:
                break  # budget/model out — don't burn a second booking
            ok, score, flaw = image_score(path, plain(COVER["headline"]),
                                          generated=True, person=True,
                                          cover=True, collage=True)
            print(f"  montage try {attempt + 1}: ok={ok} score={score} "
                  f"{flaw}", file=sys.stderr)
            if ok:
                cover["media"] = os.path.relpath(path, HERE)
                return cover
        print("  montage failed judge — falling back to strongest photo",
              file=sys.stderr)
    # FALLBACK PHOTOS MUST PASS THE COVER JUDGE (owner Sep 8, forest-floor
    # post-mortem: the day's only "photograph" was a mossy forest frame off
    # a story tweet; it became the cover UNJUDGED, Gate B rejected it twice
    # in plain words, but recap repairs are text-only and the never-skip
    # floor shipped it — "we can not get any picture of green weird things
    # from twitter as a cover picture"). is_photo() answers "is it a
    # photograph", never "does it belong on THIS cover".
    for h, p in photos[:2]:
        ok, score, flaw = image_score(p, plain(COVER["headline"]), cover=True)
        if ok:
            cover["media"] = os.path.relpath(p, HERE)
            return cover
        print(f"  fallback photo rejected ({score}/10 {flaw})", file=sys.stderr)
    # GENERATED OBJECTS MONTAGE — no usable press photo at all: stage the
    # day's hero OBJECTS as one scene (faceless scaffold bans people, so
    # nothing is memory-drawn) so the cover still SUMMARIZES the day the way
    # the golden roundup reference does. Palette locked to the brand so the
    # orange headline accent belongs to the picture.
    heads = [plain(h) for h in headlines if plain(h).strip()][:2]
    if heads:
        # genimg prefixes "a realistic picture of " itself (owner format Sep 14) —
        # the brief is just the plain statement, no scene dressing
        brief = ("the hero objects of today's biggest AI news stories "
                 "together in one scene, no people. The stories: "
                 + "; ".join(heads))
        out = os.path.join(post_dir, "cover-gen.jpg")
        for attempt in range(2):
            path = genimg.generate(brief, out, cover=True, collage=True)
            if not path:
                break
            ok, score, flaw = image_score(path, plain(COVER["headline"]),
                                          generated=True, cover=True,
                                          collage=True)
            print(f"  objects-montage try {attempt + 1}: ok={ok} "
                  f"score={score} {flaw}", file=sys.stderr)
            if ok:
                cover["media"] = os.path.relpath(path, HERE)
                return cover
    # EMERGENCY RUNG (owner Sep 10: the Sep 10 recap shipped bare AGAIN —
    # the Sep 9 bare-cover ban wired write.py and edu.py but this lane
    # builds its own cover and never got the rung). Built from the DAY'S
    # BIGGEST STORY, not the container headline ("what happened in AI
    # today?" generates exactly the stock wallpaper the judge kills —
    # that day's gate B said it itself: "one of the day's named subjects
    # must anchor the cover"). Judged, accepted down to 4/10. Only a true
    # API/budget death still ships the bare art cover below.
    for h in ([plain(x) for x in headlines if plain(x).strip()][:2]
              or [plain(COVER["headline"])]):
        em = emergency_cover({"headline": h}, post_dir)
        if em:
            cover["media"] = em
            return cover
    print("RECAP COVER HAS NO IMAGE AT ALL — every rung failed (flagged "
          "for the daily report)", file=sys.stderr)
    return cover  # bare art cover — never an off-topic photo, never a screenshot


def main(stories_path):
    post_dir = os.path.join(HERE, "posts", f"{date.today()}-ai-recap")
    if os.path.exists(os.path.join(post_dir, "slide-1.jpg")):
        raise SystemExit("today's recap already exists: " + post_dir)
    cands = pick_candidates(json.load(open(stories_path)))
    if len(cands) < N_STORIES[0]:
        raise SystemExit(f"only {len(cands)} stories — not enough for a recap")
    for s in cands:
        print(f"  cand: {s['score']:6.1f}  {s['title'][:70]}", file=sys.stderr)

    prompt = build_prompt(cands)
    for attempt in range(3):
        post = call_claude(prompt, schema=RECAP_SCHEMA)
        errs = qa(post, len(cands))
        if not errs:
            break
        print(f"QA gate failed (attempt {attempt + 1}):\n  "
              + "\n  ".join(errs), file=sys.stderr)
        prompt = (build_prompt(cands)
                  + "\n\nYOUR PREVIOUS ATTEMPT FAILED THESE QA CHECKS — fix "
                    "every one:\n- " + "\n- ".join(errs))
    else:
        raise SystemExit("QA gate failed after 3 attempts")

    os.makedirs(post_dir, exist_ok=True)
    # press images from the picked stories' tweets — downloaded ONLY to feed
    # the montage cover (Sep 14: the cover is the post's single picture).
    # Every download is classified: only real photographs may reach the
    # cover; text/UI screenshots are dropped (owner Sep 5, Bernie-recap).
    photos = []  # (headline, path) of verified photographs, story order
    for n, s in enumerate(post["stories"]):
        img = cands[s.pop("idx")].get("image")
        if not img:
            continue
        try:
            path = os.path.join(post_dir, f"media-{n}.jpg")
            open(path, "wb").write(get(img))
            if is_photo(path):
                photos.append((s.get("headline", ""), path))
        except Exception as e:
            print(f"  image failed ({e}) — skipping", file=sys.stderr)

    # the cover is the ONLY slide (single-picture posts, Sep 14)
    post["slides"] = [build_cover(
        post_dir, photos,
        [s.get("headline", "") for s in post["stories"]])]
    post.update(handle="@yaffeai", container="daily_recap")
    scrub_dashes(post)  # owner rule: dashes never reach a published slide

    def render():
        json.dump(post, open(os.path.join(post_dir, "post.json"), "w"),
                  indent=1)
        subprocess.run([sys.executable, os.path.join(HERE, "render.py"),
                        os.path.join(post_dir, "post.json"), post_dir],
                       check=True)

    render()

    # GATE B — editor-in-chief on the RENDERED cover (write.py parity):
    # REJECT drives up to THREE surgical text repairs (one more than write.py
    # — test 4, Aug 27: round 1 fixes landed but a second read found new
    # text-law kills; the recap is a daily franchise, a third round is
    # cheaper than losing the anchor slot); still failing = exit nonzero,
    # the ladder's next rung (write.py news) fills the slot.
    import editor
    cover_jpg = os.path.join(post_dir, "slide-1.jpg")
    ok, reasons = editor.gate_b(
        post, cover_jpg if os.path.exists(cover_jpg) else None)
    for _ in range(3):
        if ok:
            break
        fixed = qa_repair(post, ["editor reject: " + r for r in reasons])
        if not (fixed and len(fixed.get("slides", [])) == len(post["slides"])):
            # never break silently (test 3, Aug 27: a shape mismatch skipped
            # both repair rounds with no trace in the log)
            print(f"repair unusable: got {len((fixed or {}).get('slides', []))}"
                  f" slides, post has {len(post['slides'])} — giving up",
                  file=sys.stderr)
            break
        keep = json.loads(json.dumps(post))
        for s_old, s_new in zip(post["slides"], fixed["slides"]):
            for k in ("headline", "body", "kicker"):
                if s_new.get(k):
                    s_old[k] = s_new[k]
        if fixed.get("caption"):
            post["caption"] = fixed["caption"]
        if fixed.get("pinned_comment"):
            post["pinned_comment"] = fixed["pinned_comment"]
        scrub_dashes(post)
        broke = qa(post, len(cands), pre_render=False)
        if broke:  # repair broke a mechanical gate — revert
            print("repair broke mechanical QA (" + "; ".join(broke)
                  + ") — reverting", file=sys.stderr)
            post.clear()
            post.update(keep)
            break
        render()
        ok, reasons = editor.gate_b(
            post, cover_jpg if os.path.exists(cover_jpg) else None)
    if not ok:
        # NEWS PAGE FIRST (owner order Sep 3): the recap is the measured
        # winner format (2,555 median likes/1M) and its slot has NO other
        # news rung — a Gate B reject ships FLAGGED (edu.py pattern) rather
        # than starving the slot. Mechanical qa above stayed binding;
        # daily.py names every override.
        post["editor_override"] = "; ".join(reasons)[:400]
        print("recap: shipping over gate B reject — " + "; ".join(reasons),
              file=sys.stderr)

    render()

    # GATE R (owner order Sep 5): eyes on EVERY rendered slide before
    # publish — the gate that would have caught the Bernie-recap cover.
    # drop_image repairs apply mechanically + one re-render; the post ships
    # regardless (always-post), flagged in post.json for the daily report.
    fails = editor.gate_r(post, post_dir)
    if fails:
        if editor.apply_gate_r(post, fails):
            render()
        else:  # flag-only fails: persist the gate_r note for the report
            json.dump(post, open(os.path.join(post_dir, "post.json"), "w"),
                      indent=1)

    print("post ready:", post_dir)
    return post_dir


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1
         else os.path.join(HERE, "stories.json"))
