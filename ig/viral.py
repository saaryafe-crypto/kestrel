#!/usr/bin/env python3
"""The viral agent (owner request Jul 29, after the Circle K post-mortem):
one place that owns PACKAGING — cover hooks and reel titles — in
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
    # Owner flip Aug 1 (reference-page audit): every type now SUMMARIZES —
    # the full story with its specifics on the cover. What changes per type
    # is WHICH specific leads, not whether it appears.
    "corporate_move": {
        "lead": ('THE FULL DECISION + ITS NUMBERS. Formula: [ACTOR] JUST '
                 '[the move], [the number/stake that makes it wild]. Model: '
                 '"VISA JUST LAID OFF 2,600 WORKERS TO GO ALL IN ON A '
                 'TECHNOLOGY MOST BANKS REFUSE TO TOUCH". Say what they did '
                 'AND what it cost — the decision\'s audacity is the hook.'),
        "hook_rule": ('COMPLETE (0-2): tells the whole move with its real '
                      'numbers — a stranger gets what happened and why it\'s '
                      'wild from the cover alone. A withholding tease ("bet '
                      'everything" on an unnamed thing) scores 0.'),
    },
    "absurd_moment": {
        "lead": ('THE FULL ABSURD STORY. The most insane TRUE detail (the '
                 'exact number, the exact thing it did) plus what it means, '
                 'all in the headline. Model: "A SELF-CHECKOUT AI GLITCHED '
                 'AND TRIED TO DONATE $8.5 BILLION OF ITS OWNER\'S MONEY TO '
                 'THE RED CROSS". Never tease ("wait until you see the '
                 'amount") — the specific IS the scroll-stopper.'),
        "hook_rule": ('ABSURD (0-2): the insane TRUE specific and its '
                      'context both on the cover. Vague teasing that hides '
                      'the specific scores 0.'),
    },
    "threat": {
        "lead": ('SECOND PERSON STAKE, FULLY STATED. The reader must feel '
                 'personally exposed AND know exactly what happened: [the '
                 'threat] JUST [reached your world], [the concrete scope]. '
                 'Model: "YOUR PRIVATE AI CHATS JUST SHOWED UP IN GOOGLE '
                 'SEARCH RESULTS AND THOUSANDS ARE ALREADY READABLE".'),
        "hook_rule": ('STAKE (0-2): a stranger instantly feels THEIR OWN '
                      'money/job/privacy is on the line and knows the real '
                      'scope. Abstract industry threats score 0.'),
    },
    "money_win": {
        "lead": ('PERSON + RESULT + THE HOW, all on the cover. Formula: '
                 '[relatable person] JUST [made/saved $X] [doing the '
                 'concrete thing with AI]. Model: "A 19-YEAR-OLD JUST HIT '
                 '$1M A YEAR WITH AN AI TOOL HE BUILT IN HIS DORM IN TWO '
                 'WEEKS". The how makes it believable AND repeatable — '
                 'that\'s the share. When the cover photo will show the real '
                 'person or the thing they built, "THIS GUY JUST..." beats '
                 'the anonymous noun (reference: "THIS GUY JUST BUILT A 3D '
                 'RACING GAME WITH AI. IT COST HIM $863 AND 1.2 BILLION '
                 'TOKENS" — the photo completes the sentence).'),
        "hook_rule": ('PROOF (0-2): a relatable person, a true result '
                      'number, and what they actually did. Missing any of '
                      'the three scores 0.'),
    },
    "record": {
        "lead": ('THE SCALE CLAIM, FULLY SPECIFIED. Formula: [subject] JUST '
                 '[broke the record / did the unbelievable thing], [the '
                 'number that proves it]. Model: "A HUMANOID ROBOT JUST RAN '
                 'A FULL 26-MILE MARATHON ON ONE BATTERY CHARGE, THE FIRST '
                 'MACHINE EVER TO FINISH ONE".'),
        "hook_rule": ('SCALE (0-2): the record and its number are instantly '
                      'graspable and sound impossible-but-true. Insider '
                      'metrics nobody can picture score 0.'),
    },
    "edu_value": {  # edu.py value posts (no news story behind them)
        "lead": ('COUNTABLE VALUE PROMISE. Formula: [N concrete things] '
                 '[the reader keeps: money saved / hours back] — the count '
                 'and the value go in the headline; the list itself is the '
                 'carousel (an N-list cover can\'t hold N items — this is '
                 'the one type where the payload stays inside). Model: "6 '
                 'EXPENSIVE SERVICES AI NOW REPLACES FOR FREE". Add the '
                 'ENEMY CONTRAST clause when true — what the reader beats '
                 'by knowing it ("...THAN MOST PAID COURSES", "MOST PEOPLE '
                 'OVERLOOK", "SO GOOD THEY FEEL ILLEGAL").'),
        "hook_rule": ('VALUE (0-2): promises specific countable value the '
                      'reader personally keeps (a number of tools/prompts, '
                      '$ saved). Vague "AI tips" promises score 0.'),
    },
}

ANCHOR_RULE = """ANCHOR RULE (hard): the hook may only anchor on a name a random 16-year-old instantly recognizes. This story's anchor: "{anchor}". Unknown brands are dead weight in the 4 words that decide the swipe — use the universal noun instead ("a self-checkout", "an AI", the famous counterparty)."""

SHARED_RULES = """- LENGTH 12-25 words, aim 15-20: ONE complete sentence that SUMMARIZES the whole story with its wildest specifics ON the cover — the price, the count, the first-ever, the absurd detail. Model (owner Aug 1, the reference page): "OPENAI JUST LAUNCHED THEIR FIRST EVER HARDWARE PRODUCT, A $230 LIGHT UP KEYBOARD BUILT TO RUN YOUR AI CODING AGENTS".
- WITHHOLD NOTHING (owner doctrine Aug 1, reverses the Jul 29 gap rule): a riddle only works for pages with authority; a growing page earns the follow by DELIVERING on the cover. The reader should get the full story from the cover alone — the swipe is for the photos, the details and the fallout, which the wild content makes them want automatically.
- Structure: [ACTOR] JUST [charged verb + what happened], [the specific that makes it wild]. Front-load the actor and verb; the numbers ride in the second half.
- PERSON-FIRST (owner post-mortem Aug 1, the Situational-Awareness fund story): when ONE human drives the story, the PERSON is the actor — identity fact + rise + fall + the human scene ("THIS 24-YEAR-OLD BUILT A $45 BILLION AI FUND. THEN LOST 67% OF IT DURING HIS WEDDING" — the reference page's winner). Leading with the thing ("A $45 BILLION AI FUND COLLAPSED IN DAYS") is the failure model: people stop for people. A retellable human scene (a wedding, a courtroom) on the cover outranks any percentage.
- Charged verbs when true: BET, FIRED, WENT ROGUE, BANNED, LEAKED, TRIED TO. Threat/loss framing beats triumph when both are true.
- THE COLLISION: when two true facts contradict each other, put BOTH in the sentence joined by AND/YET/THEN ("A RECORD QUARTER AND THE STOCK STILL FELL 8%") — the contradiction is the reference page's strongest scroll-stopper.
- POINTING HOOKS (forensic Aug 2): for builder/absurd stories, "THIS GUY / THESE ARE / THIS IS HOW" openers weld the words to the cover photo — the image completes the sentence ("THIS GUY BUILT A WAY TO SEND FILES BETWEEN TWO PHONES WITH NO WI-FI, NO BLUETOOTH, AND NO NETWORK AT ALL"). Use only when the cover will show the exact pointed-at person or thing.
- NO HEDGE WORDS: may, might, could — never. "Reportedly" is allowed ONCE, mid-sentence, ONLY for a leak/rumor/patent story that cannot honestly be stated as fact (the reference runs "XBOX REPORTEDLY PLANNED...", "FERRARI REPORTEDLY HIT..."); never as the first word. Everything verified is stated hard; attribution lives in the credit line.
- Simple words a 16-year-old gets instantly. Zero jargon, zero metaphors to decode. Only TRUE facts from the story.
- Mark accents with <em>...</em>: the 1-2 phrases carrying the numbers/wildest specifics (2 groups max)."""


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
        "properties": {"headline": {"type": "string"}},
        "required": ["headline"]}}},
    "required": ["hook_candidates"],
}

HE_INTRO = """You write cover hooks for @ainews.israel — the Hebrew Instagram page for Israeli AI news. Write NATIVELY in Hebrew a smart Israeli 16-year-old would say out loud — never translate English phrasing. Keep brand/product names in their original Latin script (AI, ChatGPT, Visa). Hebrew is denser than English: the LENGTH rule below relaxes to 8-20 words — but the summary must still be COMPLETE, nothing withheld. GRAMMAR (kill rule): every line must be correct spoken Hebrew — read it aloud; nouns are not verbs ("הזיה עסקה" is broken, "המציא עסקה" is right). A line a native speaker would stumble on is disqualified."""
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
Each candidate: {{"headline": "..."}} — the headline is the big cover copy and must stand COMPLETELY alone (the only other cover text is a tiny pre-written kicker strip you don't control); every word of the hook must live in the headline itself.

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


def _pre_filter(cands, ctx=None, lo=10):
    """Deterministic craft gates — rules that are yes/no checks, not taste.
    Run BEFORE the judge so it only sees candidates that already pass the
    craft floor. Falls open if it would empty the list."""
    def _words(c):
        return len(re.sub(r"<[^>]+>", "", c.get("headline", "")).split())
    # summarizing-hook window (owner flip Aug 1: whole story on the cover —
    # under the floor = old withholding style, over 26 = unreadable wall).
    # edu N-promise hooks stay short by design ("6 SERVICES AI REPLACES FOR
    # FREE"), so they skip the length gate.
    if (ctx or {}).get("story_type") == "edu_value":
        kept = cands
    else:
        kept = [c for c in cands if lo <= _words(c) <= 26]
    if not kept:
        kept = cands  # fall open
    else:
        dropped = len(cands) - len(kept)
        if dropped:
            print(f"viral: dropped {dropped} candidate(s) outside the "
                  "10-26 word window", file=sys.stderr)
    # hedge gate (researched Aug 1; recalibrated Aug 2 to the reference page:
    # may/might/could/allegedly always die, but "reportedly" mid-sentence is
    # their standard license for leak/rumor stories — "XBOX REPORTEDLY
    # PLANNED..." — so it only dies as the FIRST word)
    hedge = re.compile(r"(?i)\b(may|might|could|allegedly)\b")
    def _hedged(c):
        t = re.sub(r"<[^>]+>", "", c["headline"]).strip()
        return bool(hedge.search(t)) or t.lower().startswith("reportedly")
    no_hedge = [c for c in kept if not _hedged(c)]
    if no_hedge and len(no_hedge) < len(kept):
        print(f"viral: dropped {len(kept) - len(no_hedge)} hedged candidate(s)",
              file=sys.stderr)
    return no_hedge or kept


def judge(cands, ctx, lang="en"):
    """Blind taste judge (owner redesign Jul 29: rules are code gates, the
    judge's ONLY job is impact — would a stranger stop scrolling?). Returns
    (winner_dict, record) or (None, None)."""
    cands = _drop_unknown_anchor(cands, ctx)
    # Hebrew packs prepositions/articles into words — a full summary can be
    # shorter, so the floor relaxes
    cands = _pre_filter(cands, ctx, lo=8 if lang == "he" else 10)
    if len(cands) < 2:
        return (cands[0] if cands else None), None
    order = list(range(len(cands)))
    random.shuffle(order)
    listing = "\n".join(
        f"[{i}] {cands[j]['headline']}" for i, j in enumerate(order))
    lang_line = ("You read Hebrew natively. A line that sounds broken when "
                 "read aloud (a noun used as a verb, an unnatural sentence "
                 "a native Israeli would never say) scores 0 TOTAL."
                 if lang == "he" else "")
    facts = "\n".join(f"- {s}" for s in ctx.get("specifics", []))
    prompt = f"""You are a real person scrolling Instagram at 2am. You do NOT work in marketing. You know NOTHING about this story — you see only the cover text below, exactly like every real viewer. {lang_line} Ignore <em> markup.

TRUE FACTS (use ONLY for the truth kill rule below — you still react as a stranger):
{facts or '- (none listed)'}

Score each candidate 0-10 on ONE thing: IMPACT — would you stop scrolling, read it, and swipe? Trust your gut. A hook that makes you think "wait, WHAT?" beats one that sounds professionally crafted but doesn't make you feel anything. You don't know this page, so a cover that TELLS you the full wild story with its real numbers beats a cryptic tease that hides what happened — you'd swipe for the photos and details of a story you already believe, not to solve a stranger's riddle.

KILL RULES (score 0 TOTAL, no matter how good it sounds):
- TRUTH: states as DONE something the facts say was only tried/almost/blocked ("SENT" when it only TRIED to send), or invents a claim the facts don't support

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


# ------------------------------------------------------- hook specialist

# Distilled from inspiration/principles.md (Nature Human Behaviour 105K
# headline tests, Upworthy archive, Berger & Milkman, practitioner corpora) —
# the levers the specialist attacks with. The writer prompt already carries
# the full doctrine; this is the fighting weight for one focused pass.
PSYCH = """HUMAN-PSYCHOLOGY LEVERS (each backed by large-scale headline studies):
1. THE 1.7-SECOND TEST: a scroller gives ~1.7s of half-attention. The first 3-4 words must already carry the wildest element — actor or absurd specific first, never setup.
2. NEGATIVITY WINS: each negative/threat/loss word adds ~+2.3% clicks; triumph framing loses to loss framing when both are true (FIRED > HIRED, LOST > MADE, BANNED > LAUNCHED).
3. HIGH-AROUSAL EMOTION ONLY: awe, anger, anxiety, amusement drive shares; "impressive/interesting" is not an emotion. If the hook doesn't make YOU feel one nameable spike, it's dead.
4. CONCRETENESS THAT STACKS (recalibrated Aug 2, forensic count of ~90 reference hooks): every number must ADD absurdity — odd precise numbers ($863, 682 tonnes, 335,000 signatures) create belief. A second number earns its place ONLY when the PAIR is the story ("IT COST HIM $863 AND 1.2 BILLION TOKENS"); a number that merely adds context dilutes. Zero numbers is wallpaper.
5. MORAL-EMOTIONAL VERBS: banned, exposed, refused, stole, betrayed, admitted add +17-20% each — ONLY when literally true.
6. SELF-REFERENCE: "your money / your job / your phone" lifts engagement massively, but only when the story genuinely touches the reader; fake relevance reads instantly.
7. REPEAT-TO-A-FRIEND: the ultimate test — one plain sentence a 16-year-old would say out loud to a friend, verbatim. If it can't be repeated from memory after one read, it fails.
8. PEOPLE STOP FOR PEOPLE: a named/relatable DOER ("a guy", "a 19-year-old", the famous CEO) beats an institution announcing, even when the institution's news is bigger.
9. BELIEVED-WILD BEATS WILDER-DOUBTED: real odd numbers ($317K, 9 days, 800 girls) create belief; round numbers and superlatives create doubt.
10. DIFFERENT DOORS: number-led, contrarian flip, before/after, authority-steal, admission, future-shock — rivals must walk through DIFFERENT doors, not reword the same one.
11. THE COLLISION (the reference page's most-used engine, forensic Aug 2): two TRUE facts that fight each other, welded into one sentence by AND / YET / THEN — "A RECORD $102.4 BILLION QUARTER AND THE STOCK STILL FELL 8%", "GROSS $1 BILLION AND STILL LOSE THE STUDIO MONEY", "SUING FOR JUST $1.50 — HE DOES NOT WANT THEIR MONEY". When the story holds a contradiction, the hook stating BOTH sides beats every single-fact hook."""

SHARPEN_SCHEMA = {
    "type": "object",
    "properties": {"weakness": {"type": "string"},
                   "hook_candidates": {"type": "array", "items": {
                       "type": "object",
                       "properties": {"headline": {"type": "string"},
                                      "lever": {"type": "string"}},
                       "required": ["headline"]}}},
    "required": ["weakness", "hook_candidates"],
}


def sharpen(win, ctx, material="", lang="en", news=True, payload=""):
    """The hook specialist (owner Aug 2: "create a specialised agent that
    creates an incredible hook, based on our research and human psychology").
    One adversarial pass AFTER the tournament: name the winner's biggest
    psychological weakness, then write rivals that each pull a different
    lever harder — the blind judge then re-runs winner vs rivals, so the
    original only loses to something that actually beats it. Fails open."""
    intro = HE_INTRO if lang == "he" else EN_INTRO
    rules = SHARED_RULES if news else (
        "- Keep the container's own length/format rules (an edu N-promise "
        "cover stays SHORT, 5-10 words, number first).")
    pay = f"\nWHAT THE INSIDE SLIDES ACTUALLY DELIVER (the hook must promise exactly this, never more):\n{payload}" if payload else ""
    prompt = f"""{intro}
You are the page's HOOK SPECIALIST — the last editor before publish. Below is the current winning cover hook. Your job: beat it, or prove it can't be beaten.

CURRENT WINNER: {win['headline']}

STORY FACTS (never invent, never exaggerate beyond them):
{(material or '')[:2000] or '- (use the hook ammunition below)'}
{pay}
{hook_block(ctx)}

{PSYCH}

THE JOB:
1. "weakness": in one blunt sentence, name the current winner's single biggest failure against the levers above (which lever it leaves on the table).
2. "hook_candidates": 3 rivals that each attack through a DIFFERENT lever (tag each with "lever"). Every rival: 100% true to the facts, every formatting rule below, and it must beat the current winner at the 1.7-second test — otherwise don't write it, fewer great rivals beat three weak ones.
{rules}
- Mark accents with <em>...</em> (1-2 phrases carrying the wildest specifics).

Return ONLY JSON: {{"weakness": "...", "hook_candidates": [...]}}"""
    try:
        r = _claude(prompt, SHARPEN_SCHEMA)
        rivals = [{"headline": c.get("headline") or c.get("hook")}
                  for c in r.get("hook_candidates", [])
                  if c.get("headline") or c.get("hook")][:4]  # model drifts
        # between "headline"/"hook" keys despite the schema
        if rivals:
            print(f"hook specialist: weakness = {r.get('weakness', '')[:120]}",
                  file=sys.stderr)
        return rivals
    except Exception as e:
        print(f"hook specialist failed ({e}) — keeping tournament winner",
              file=sys.stderr)
        return []


def sharpen_pass(post, win, ctx, material="", lang="en", news=True):
    """Run the specialist + a second blind judging round. Returns the final
    winner dict (the original unless a rival beat it blind)."""
    payload = "\n".join(
        f"- {re.sub('</?em>', '', s.get('headline') or '')}"
        for s in post.get("slides", [])[1:] if s.get("headline"))[:800]
    rivals = sharpen(win, ctx, material, lang=lang, news=news, payload=payload)
    if not rivals:
        return win
    win2, rec2 = judge([win] + rivals, ctx, lang=lang)
    if not win2 or "<em>" not in win2.get("headline", ""):
        return win
    if rec2:
        post["hook_sharpen"] = rec2
    if win2["headline"] != win["headline"]:
        print(f"hook specialist WON: "
              f"{re.sub('</?em>', '', win2['headline'])[:80]}", file=sys.stderr)
    return win2


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
    win = sharpen_pass(post, win, ctx, material, news=bool(story))
    post["slides"][0]["headline"] = _no_dashes(win["headline"])
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
        cands.append(loc)
    win, record = judge(cands, ctx, lang="he")
    if not win:
        return out
    win = sharpen_pass(out, win, ctx, material, lang="he")
    hl = _no_dashes(win["headline"])
    if "<em>" not in hl:  # accent is mandatory on covers
        hl = re.sub(r"^(\S+)", r"<em>\1</em>", hl)
    out["slides"][0]["headline"] = hl
    out["slides"][0].pop("subline", None)  # dead field (owner Aug 1)
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
    lang_line = ("The titles are Hebrew. You read Hebrew natively; judge them "
                 "as an Israeli 16-year-old hears them. KILL RULE: a title "
                 "with a grammar error (mismatched gender/number, singular "
                 "verb on plural subject) or that sounds translated from "
                 "English (a native would stumble reading it aloud) must "
                 "NEVER win, no matter how strong its content."
                 if lang == "he" else "")
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
