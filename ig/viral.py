#!/usr/bin/env python3
"""The viral agent (owner request Jul 29, after the Circle K post-mortem):
one place that owns PACKAGING — cover hooks, sublines, and reel titles — in
both languages. Born from two measured failures the old one-rubric system
caused:

1. It anchored hooks on "Circle K", a brand the audience doesn't know. An
   unknown actor is dead weight in the 4 words that decide the swipe.
2. Its judge double-weighted "information gap" for EVERY story, so "AN AI
   CHARGED SOMEONE $8.5 BILLION" (the actual story) lost to a vague teaser.
   The gap doctrine is right for corporate-bet stories and WRONG for absurd
   ones — there the insane TRUE specific IS the scroll-stopper and the gap
   moves to how/why.

So the agent classifies the story FIRST, then generates and judges with the
formula for that story type. Everything it decides is stored on the post
(classification, candidates, scores, the judge's written reason) so learn.py
can compare its choices against real likes.

English persona writes for @yaffeai; the Hebrew persona writes NATIVELY for
@ainews.israel (a hook is re-created from the classified story, never
translated — translation preserves words and kills tension)."""
import json, os, random, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))


JUDGE_MODEL = "claude-sonnet-4-6"  # different model breaks same-model taste bias


def _claude(prompt, schema):
    from write import call_claude  # lazy: write.py imports this module
    return call_claude(prompt, schema=schema)


def _judge_claude(prompt, schema):
    """Judge calls use a DIFFERENT model than the writer (owner audit Jul 29:
    same model writing + judging = closed taste loop). Sonnet judges what Opus
    wrote — genuinely different preferences, not a rewording of the same brain."""
    from write import call_claude
    return call_claude(prompt, schema=schema, model=JUDGE_MODEL)


def _no_dashes(t):
    from write import no_dashes
    return no_dashes(t)


# ---------------------------------------------------------------- classify

CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "story_type": {"type": "string",
                       "enum": ["corporate_move", "absurd_moment", "threat",
                                "money_win", "record"]},
        "actor": {"type": "string"},
        "actor_known": {"type": "boolean"},
        "anchor": {"type": "string"},
        "specifics": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["story_type", "actor", "actor_known", "anchor", "specifics"],
}

TYPES = """- corporate_move: a company/institution makes a strategic bet, layoff, pivot, ban, or acquisition. The drama is the DECISION.
- absurd_moment: an AI/machine/person did something insane, hilarious, or unbelievable (usually caught on camera or in a viral post). The drama is the MOMENT itself.
- threat: the story endangers the reader's own money, job, privacy, or safety (scams, leaks, layoff waves, AI replacing X). The drama is WHAT IT MEANS FOR YOU.
- money_win: an ordinary person or tiny team made/saved real money with AI. The drama is THE RESULT.
- record: a first-ever / biggest-ever / physically-unbelievable scale achievement. The drama is THE SCALE."""


def classify(story, material=""):
    """One cheap call that decides which hook formula applies. Fails open to
    corporate_move + known actor (= exactly the old system's behavior)."""
    prompt = f"""Classify this news story for Instagram packaging.

Title: {story['title']}
Material: {(material or '')[:1500]}

STORY TYPES (pick the ONE whose drama is the real reason people share this):
{TYPES}

Then:
- "actor": the named actor of the story (company/person/thing).
- "actor_known": would a random 16-year-old ANYWHERE instantly recognize this name? Be harsh. Apple/Tesla/ChatGPT/Visa/MrBeast yes; Circle K/Figure/Suno/Anthropic no.
- "anchor": what the hook should anchor on. If actor_known, the actor. If not, the most universal TRUE noun in the story (the machine, the AI, "a self-checkout", the famous counterparty, "your bank"). Never an unknown brand.
- "specifics": the 3-5 most shareable TRUE concrete details, most insane first (exact numbers, names, quotes). These are the hook's raw ammunition.

Return ONLY JSON with EXACTLY these keys:
{{"story_type": "<one of the type names above>", "actor": "...", "actor_known": true/false, "anchor": "...", "specifics": ["...", "..."]}}"""
    try:
        r = _claude(prompt, CLASSIFY_SCHEMA)
        # CLI fallback path has no schema enforcement — normalize before the
        # PLAYBOOK lookup can KeyError (caught live: model returned "type")
        r["story_type"] = r.get("story_type") or r.get("type") or ""
        if r["story_type"] not in PLAYBOOK:
            raise ValueError(f"bad story_type {r['story_type']!r}")
        for k, v in (("actor", ""), ("actor_known", True), ("anchor", ""),
                     ("specifics", [])):
            r.setdefault(k, v)
        return r
    except Exception as e:
        print(f"viral classify failed ({e}) — defaulting to corporate_move",
              file=sys.stderr)
        return {"story_type": "corporate_move", "actor": "", "actor_known": True,
                "anchor": "", "specifics": []}


# ------------------------------------------------------- per-type playbook

# Single source of truth: the SAME text steers generation AND judging, per
# story type. "lead" = what the headline leads with; "hook_rule" = the
# double-weighted judge criterion for this type.
PLAYBOOK = {
    "corporate_move": {
        "lead": ('INFORMATION GAP. Formula: [ACTOR] JUST [charged verb] '
                 '[withheld stake]. Name WHO, signal something big happened, '
                 'withhold WHAT/WHY/HOW MUCH. Model: "VISA JUST BET '
                 'EVERYTHING". A number only as bait ("FIRED 2,600 PEOPLE '
                 'FOR THIS..."), never as resolution.'),
        "hook_rule": ('GAP (0-2): sells curiosity WITHOUT delivering the '
                      'story — you cannot tell what actually happened and you '
                      'itch to know. A headline that summarizes the story '
                      'scores 0; one so vague it fits 100 stories also scores 0.'),
    },
    "absurd_moment": {
        "lead": ('LEAD WITH THE ABSURD SPECIFIC. The single most insane TRUE '
                 'detail (the exact number, the exact thing it did) goes IN '
                 'the headline — it is the scroll-stopper, hiding it kills '
                 'the post. The gap moves to HOW/WHY it happened. Model: "A '
                 'SELF-CHECKOUT TRIED TO DONATE $8.5 BILLION" (measured '
                 'failure: "WAIT UNTIL YOU SEE THE AMOUNT" teasing lost).'),
        "hook_rule": ('ABSURD (0-2): leads with the most insane TRUE concrete '
                      'specific from the story and still leaves a how/why '
                      'itch. Vague teasing that hides the specific ("wait '
                      'until you see...") scores 0. Delivering the specific '
                      'WITH its full explanation also scores 0 — the how/why '
                      'must stay open.'),
    },
    "threat": {
        "lead": ('SECOND PERSON STAKE. The reader must feel personally '
                 'exposed: YOUR money / YOUR chats / YOUR job. Formula: '
                 '[the threat] JUST [reached your world]. Model: "YOUR '
                 'PRIVATE AI CHATS JUST SHOWED UP ON GOOGLE". The gap is '
                 '"am I affected, and what do I do".'),
        "hook_rule": ('STAKE (0-2): a stranger instantly feels THEIR OWN '
                      'money/job/privacy is on the line. Abstract industry '
                      'threats ("AI disrupts sector") score 0.'),
    },
    "money_win": {
        "lead": ('ORDINARY PERSON + RESULT NUMBER. Formula: [relatable '
                 'person] JUST [made/saved $X] [with AI]. The result number '
                 'goes in the headline; HOW stays hidden. Model: "A '
                 ' 19-YEAR-OLD\'S AI SIDE PROJECT JUST HIT $1M".'),
        "hook_rule": ('PROOF (0-2): names a relatable person AND a true '
                      'result number, leaving HOW open. No number or no '
                      'person scores 0.'),
    },
    "record": {
        "lead": ('THE SCALE CLAIM. Formula: [subject] JUST [did the '
                 'physically unbelievable thing / broke the record]. The '
                 'record itself goes in the headline when it is instantly '
                 'graspable; the gap is what it looks like / what it means. '
                 'Model: "A ROBOT JUST RAN A FULL MARATHON".'),
        "hook_rule": ('SCALE (0-2): the claim is instantly graspable and '
                      'sounds impossible-but-true. Insider metrics nobody '
                      'can picture score 0.'),
    },
    "edu_value": {  # edu.py value posts (no news story behind them)
        "lead": ('COUNTABLE VALUE PROMISE. Formula: [N concrete things] '
                 '[the reader keeps: money saved / hours back] — the count '
                 'and the value go in the headline, the list itself stays '
                 'hidden. Model: "6 EXPENSIVE SERVICES AI REPLACES FOR FREE".'),
        "hook_rule": ('VALUE (0-2): promises specific countable value the '
                      'reader personally keeps (a number of tools/prompts, '
                      '$ saved), while the list stays hidden. Vague '
                      '"AI tips" promises score 0.'),
    },
}

ANCHOR_RULE = """ANCHOR RULE (hard): the hook may only anchor on a name a random 16-year-old instantly recognizes. This story's anchor: "{anchor}". Unknown brands are dead weight in the 4 words that decide the swipe — use the universal noun instead ("a self-checkout", "an AI", the famous counterparty)."""

SHARED_RULES = """- HARD CAP 9 words, aim 4-8. Short = giant letters = stops the scroll.
- ONE actor, ONE action. Never chain actions with "and".
- Charged verbs when true: BET, FIRED, WENT ROGUE, BANNED, LEAKED, TRIED TO. Threat/loss framing beats triumph when both are true.
- Simple words a 16-year-old gets instantly. Zero jargon, zero metaphors to decode. Only TRUE facts from the story.
- Mark the minimum accent words with <em>...</em>."""


def hook_block(ctx):
    """The COVER HOOK steering block write.py injects into the writer prompt —
    type formula + anchor, replacing the old one-size-fits-all formula."""
    pb = PLAYBOOK[ctx["story_type"]]
    spec = "\n".join(f"- {s}" for s in ctx.get("specifics", [])[:5])
    return f"""STORY TYPE: {ctx['story_type']} — hooks for this type follow this formula, it overrides any generic hook advice below:
{pb['lead']}
{ANCHOR_RULE.format(anchor=ctx.get('anchor') or ctx.get('actor') or 'the story subject')}
Hook ammunition (the most shareable TRUE specifics, best first):
{spec or '- (use the story facts)'}"""


# ----------------------------------------------------------- hook writing

CAND_SCHEMA = {
    "type": "object",
    "properties": {"hook_candidates": {"type": "array", "items": {
        "type": "object",
        "properties": {"headline": {"type": "string"},
                       "subline": {"type": "string"}},
        "required": ["headline"]}}},
    "required": ["hook_candidates"],
}

HE_INTRO = """You write cover hooks for @ainews.israel — the Hebrew Instagram page for Israeli AI news. Write NATIVELY in Hebrew a smart Israeli 16-year-old would say out loud — never translate English phrasing. Keep brand/product names in their original Latin script (AI, ChatGPT, Visa). GRAMMAR (kill rule): every line must be correct spoken Hebrew — read it aloud; nouns are not verbs ("הזיה עסקה" is broken, "המציא עסקה" is right). A line a native speaker would stumble on is disqualified."""
EN_INTRO = """You write cover hooks for @yaffeai — an AI/tech Instagram page in the style of @technology."""


def rival_hooks(story, ctx, material="", lang="en", n=5):
    """The independent second batch for the tournament — now steered by the
    story-type playbook instead of the generic gap formula."""
    intro = HE_INTRO if lang == "he" else EN_INTRO
    doctrine = ""
    if lang == "he":
        try:
            import he
            doctrine = he.doctrine()
        except Exception:
            pass
    prompt = f"""{intro}
Write {n} cover headlines for this story — {n} genuinely DIFFERENT attacks, not rewordings.

STORY: {story['title']}
FACTS (never invent): {(material or '')[:2000]}

{hook_block(ctx)}
{doctrine}
RULES:
{SHARED_RULES}
Each candidate: {{"headline": "...", "subline": "curiosity tease, ≤40 chars, ALL CAPS{' Hebrew' if lang == 'he' else ''}, never a summary. It must tease what's INSIDE the carousel — never re-tease a fact the headline already shows (headline says $8.5B -> subline can't be 'wait until you see the amount')"}}

Return ONLY JSON: {{"hook_candidates": [{n} objects]}}"""
    try:
        r = _claude(prompt, CAND_SCHEMA)
        return [c for c in r.get("hook_candidates", []) if c.get("headline")][:n]
    except Exception as e:
        print(f"viral rival hooks failed ({e})", file=sys.stderr)
        return []


# ---------------------------------------------------------------- judging

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {"scores": {"type": "array", "items": {"type": "integer"}},
                   "winner": {"type": "integer"},
                   "why": {"type": "string"}},
    "required": ["scores", "winner", "why"],
}


def _drop_unknown_anchor(cands, ctx):
    """Deterministic pre-filter: when the actor is unknown, candidates that
    still lead with the brand name are dropped before judging (the model was
    told; this is the gate). Falls open if it would empty the list."""
    if ctx.get("actor_known") or not ctx.get("actor"):
        return cands
    brand = re.escape(ctx["actor"].split()[0])
    kept = [c for c in cands
            if not re.search(rf"(?i)\b{brand}", re.sub(r"<[^>]+>", "", c["headline"]))]
    dropped = len(cands) - len(kept)
    if dropped:
        print(f"viral: dropped {dropped} candidate(s) anchored on unknown "
              f"brand '{ctx['actor']}'", file=sys.stderr)
    return kept or cands


def _pre_filter(cands):
    """Deterministic craft gates — rules that are yes/no checks, not taste.
    Run BEFORE the judge so it only sees candidates that already pass the
    craft floor. Falls open if it would empty the list."""
    def _words(c):
        return len(re.sub(r"<[^>]+>", "", c.get("headline", "")).split())
    kept = [c for c in cands if _words(c) <= 9]
    if not kept:
        kept = cands  # fall open
    else:
        dropped = len(cands) - len(kept)
        if dropped:
            print(f"viral: dropped {dropped} candidate(s) over 9 words",
                  file=sys.stderr)
    # subline re-teasing: if the headline shows a number and the subline
    # teases "the amount" / "the number" / "how much", it self-contradicts
    def _subline_retease(c):
        hl = re.sub(r"<[^>]+>", "", c.get("headline", ""))
        sub = c.get("subline", "")
        if not sub:
            return False
        has_number = bool(re.search(r"\$[\d.]+|\d{3,}", hl))
        teases = bool(re.search(r"(?i)\b(the amount|the number|how much|"
                                r"wait until you see)\b", sub))
        return has_number and teases
    no_retease = [c for c in kept if not _subline_retease(c)]
    if no_retease and len(no_retease) < len(kept):
        print(f"viral: dropped {len(kept) - len(no_retease)} candidate(s) "
              "with self-contradicting sublines", file=sys.stderr)
        kept = no_retease
    return kept


def judge(cands, ctx, lang="en"):
    """Blind taste judge (owner redesign Jul 29: rules are code gates, the
    judge's ONLY job is impact — would a stranger stop scrolling?). Returns
    (winner_dict, record) or (None, None)."""
    cands = _drop_unknown_anchor(cands, ctx)
    cands = _pre_filter(cands)
    if len(cands) < 2:
        return (cands[0] if cands else None), None
    order = list(range(len(cands)))
    random.shuffle(order)
    listing = "\n".join(
        f"[{i}] {cands[j]['headline']}"
        + (f"  (subline: {cands[j]['subline']})" if cands[j].get("subline") else "")
        for i, j in enumerate(order))
    lang_line = ("You read Hebrew natively. A line that sounds broken when "
                 "read aloud (a noun used as a verb, an unnatural sentence "
                 "a native Israeli would never say) scores 0 TOTAL."
                 if lang == "he" else "")
    facts = "\n".join(f"- {s}" for s in ctx.get("specifics", []))
    prompt = f"""You are a real person scrolling Instagram at 2am. You do NOT work in marketing. You know NOTHING about this story — you see only the cover text below, exactly like every real viewer. {lang_line} Ignore <em> markup.

TRUE FACTS (use ONLY for the truth kill rule below — you still react as a stranger):
{facts or '- (none listed)'}

Score each candidate 0-10 on ONE thing: IMPACT — would you stop scrolling, read it, and swipe? Trust your gut. A hook that makes you think "wait, WHAT?" beats one that sounds professionally crafted but doesn't make you feel anything.

KILL RULES (score 0 TOTAL, no matter how good it sounds):
- TRUTH: states as DONE something the facts say was only tried/almost/blocked ("SENT" when it only TRIED to send), or invents a claim the facts don't support
- CONTRADICTION: a subline that re-states what the headline already says (the headline shows the number, the subline teases "wait until you see the amount")

CANDIDATES:
{listing}

Return ONLY JSON: {{"scores": [score per candidate in order], "winner": <index of highest score>, "why": "2 blunt sentences: why the winner hits harder than the runner-up"}}"""
    try:
        r = _judge_claude(prompt, JUDGE_SCHEMA)
        win = cands[order[r["winner"]]]
    except Exception as e:
        print(f"viral judge failed ({e}) — keeping first candidate", file=sys.stderr)
        return cands[0], None
    record = {"story_type": ctx["story_type"],
              "candidates": [cands[j]["headline"] for j in order],
              "scores": r.get("scores", []), "winner": r["winner"],
              "why": r.get("why", "")}
    print(f"viral judge [{ctx['story_type']}]: "
          f"{re.sub('</?em>', '', win['headline'])[:70]} — {r.get('why', '')[:120]}",
          file=sys.stderr)
    return win, record


def tournament(post, story, ctx, material=""):
    """English tournament: writer's candidates + an independent playbook batch
    -> anchor filter -> per-type judge -> winner becomes the cover. Same
    storage shape as before (post['hook_tournament']) plus type + why."""
    cands = [c if isinstance(c, dict) else {"headline": c}
             for c in post.pop("hook_candidates", [])]
    cands = [c for c in cands if c.get("headline")]
    if story:  # edu posts have no news story — writer's candidates only
        cands += rival_hooks(story, ctx, material)
    win, record = judge(cands, ctx)
    if not win or "<em>" not in win["headline"]:
        print("viral tournament: no valid winner — keeping writer's cover",
              file=sys.stderr)
        return post
    post["hook_tournament"] = record or {"candidates": [win["headline"]],
                                         "scores": [], "winner": 0,
                                         "story_type": ctx["story_type"]}
    post["slides"][0]["headline"] = _no_dashes(win["headline"])
    if win.get("subline"):
        post["subline"] = _no_dashes(win["subline"])
    return post


# ----------------------------------------------------------------- hebrew

def hebrew_cover(out, story, ctx, material=""):
    """Replace the LOCALIZED cover hook with a NATIVELY-WRITTEN one: 5 Hebrew
    candidates from the classified story, judged in Hebrew. Localization keeps
    slides 2+ (they carry the facts); the hook is packaging and gets
    re-created, not translated. Fails open: the localized hook stays."""
    cands = rival_hooks(story, ctx, material, lang="he")
    # the localized translation competes too — sometimes it IS the best
    loc = {"headline": out["slides"][0].get("headline", "")}
    if out.get("slides") and loc["headline"]:
        if out["slides"][0].get("subline"):
            loc["subline"] = out["slides"][0]["subline"]
        cands.append(loc)
    win, record = judge(cands, ctx, lang="he")
    if not win:
        return out
    hl = _no_dashes(win["headline"])
    if "<em>" not in hl:  # accent is mandatory on covers
        hl = re.sub(r"^(\S+)", r"<em>\1</em>", hl)
    out["slides"][0]["headline"] = hl
    if win.get("subline"):
        out["slides"][0]["subline"] = _no_dashes(win["subline"])
    if record:
        out["hook_tournament_he"] = record
    return out


# ------------------------------------------------------------ reel titles

REEL_JUDGE = {"type": "object",
              "properties": {"winner": {"type": "integer"},
                             "why": {"type": "string"}},
              "required": ["winner", "why"]}


def reel_title_judge(cands, lang="en"):
    """Blind judge for reel overlay titles (EN + HE), carrying the two
    post-mortem rules: no unknown-brand anchors, and when the clip's wow IS a
    concrete specific, the title says it. Returns (title, why) or (None, None)."""
    cands = list(dict.fromkeys(t.strip() for t in cands if t and t.strip()))
    if len(cands) < 2:
        return (cands[0] if cands else None), None
    random.shuffle(cands)
    listing = "\n".join(f"[{i}] {t}" for i, t in enumerate(cands))
    lang_line = ("The titles are Hebrew; judge them as an Israeli 16-year-old "
                 "hears them." if lang == "he" else "")
    prompt = f"""You are a stranger scrolling Instagram Reels at 2am. Below are candidate one-line titles overlaid on the SAME video — you can't see the video, exactly like the split second before a viewer decides to keep watching. {lang_line}

Pick the ONE you'd stop for:
- It opens a curiosity gap about what you're seeing, understated, zero hype words.
- BUT if a candidate names an insane concrete specific (a number, the exact absurd thing) that another candidate only vaguely teases, the concrete one wins — "wait until you see" teasing loses to the specific itself.
- Never one anchored on a brand a 16-year-old wouldn't recognize — the universal noun ("this robot", "a self-checkout") beats the unknown name.
- Everyday words only.

{listing}

Return ONLY JSON: {{"winner": <index>, "why": "one blunt sentence"}}"""
    try:
        j = _judge_claude(prompt, REEL_JUDGE)
        return cands[j["winner"]], j.get("why", "")
    except Exception as e:
        print(f"viral reel judge failed ({e})", file=sys.stderr)
        return None, None
