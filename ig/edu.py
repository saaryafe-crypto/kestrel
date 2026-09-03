#!/usr/bin/env python3
"""Educational save-magnet writer (ai_education container): Claude Code powers,
AI skills anyone can use tonight, TRUE stories of what people built.
TOPIC SOURCE (owner order Aug 4, "find the viral guides on twitter"): the
most viral guide/how-to threads from the approved X watchlist (radar_x flags
them + mines the author's thread into radar.json) come FIRST — proven demand.
No fresh guide on the radar -> Claude picks a pillar angle itself, so there
is still no hard news dependency. Deduped via edu-used.json (topics + [x:ID]).
Owner order Aug 3 (X watchlist only): the reddit_tips() topic-demand miner is
DELETED — no Reddit data anywhere. Topic anchors come only from stories.json,
which is itself X-watchlist-only.
Usage: python3 edu.py"""
import glob, json, os, re, subprocess, sys
from datetime import date

import genimg
import viral
from write import (HERE, art_direct, call_claude, doctrine, face_riders,
                   image_score, is_dupe, logo_ref, pick_face, principles, qa,
                   qa_repair, scrub_dashes, simpler_brief, slugify,
                   split_faces)

USED = os.path.join(HERE, "edu-used.json")

SCHEMA = {
    "type": "object",
    "properties": {
        "topic": {"type": "string"},
        "slides": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["cover", "content", "cta"]},
                    "hsize": {"type": "integer", "minimum": 54, "maximum": 124},
                    "headline": {"type": "string"},
                    "body": {"type": "string"},
                    "image_brief": {"type": "string"},
                },
                "required": ["type", "hsize", "headline"],
            },
        },
        "caption": {"type": "string"},
        "hook_candidates": {
            "type": "array", "minItems": 5,
            "items": {"type": "object",
                      "properties": {"headline": {"type": "string"}},
                      "required": ["headline"]},
        },
    },
    "required": ["topic", "slides", "caption", "hook_candidates"],
}


def viral_guides(used_topics):
    """Owner order Aug 4 ("find the viral guides on twitter as well, it is
    much better and more viral") + Aug 8 token diet: the ONLY topic source is
    the 7-day rolling pool of viral guide tweets (ig/guides.json, maintained
    by radar.py) — most viral unused wins. The old radar.json snapshot only
    held 0-3 guides at a time, so the slot self-picked pillar topics and
    repeated itself ("6 prompts"...). Deduped via the [x:ID] tag the writer
    copies into its topic label. Fails open: pool missing -> radar.json
    snapshot -> [] (pillar self-pick keeps the slot alive)."""
    used_blob = " ".join(used_topics)
    try:
        cands = json.load(open(os.path.join(HERE, "guides.json")))["guides"]
    except Exception as e:
        print(f"no guides.json pool ({e}), falling back to radar.json",
              file=sys.stderr)
        try:
            r = json.load(open(os.path.join(HERE, "radar.json")))
            cands = [m for m in r.get("moments", []) if m.get("guide")]
        except Exception as e:
            print(f"no radar.json for guides ({e})", file=sys.stderr)
            return []
    out = [m for m in cands if f"x:{m['id']}" not in used_blob]
    out.sort(key=lambda m: -m.get("score", 0))
    return out[:3]


def real_tag(topic, guides):
    """True only when the topic carries a [x:ID] tag whose id exists in the
    live pool. Born Aug 13: one day after the [x:] enforcement shipped, the
    writer defeated the substring check with a literal '[x:none]' tag on two
    self-invented prompt-listicle posts — the tag must be a REAL guide id."""
    m = re.search(r"\[x:([^\]]+)\]", topic or "")
    return bool(m) and m.group(1) in {str(g.get("id")) for g in guides}


def build_prompt(used_topics, headlines="", guides=(), must_anchor=False,
                 mode="skills"):
    spec = json.load(open(os.path.join(HERE, "containers.json")))
    used = "\n".join(f"- {t}" for t in used_topics) or "(none yet)"
    vol = len(used_topics) + 1  # franchise volume number (audit Jul 29)
    guide_block = ""
    if guides:
        cands = []
        for g in guides:
            body = g.get("selftext") or g.get("title", "")
            if g.get("thread"):
                body += "\n" + "\n".join(g["thread"])
            cands.append(f"[x:{g['id']}] by {g['sub']} — {g.get('score', 0):,}"
                         f" likes on X:\n{body}")
        guide_block = ("\nVIRAL GUIDES ON X RIGHT NOW (owner GROUND RULE "
                       "Aug 12: everything this page posts rides an "
                       "ALREADY-VIRAL X wave — we never invent a topic and "
                       "test virality ourselves. When guides are listed here, "
                       "using one is MANDATORY, not preferred):\n"
                       + "\n---\n".join(cands) + "\n"
                       # owner order Aug 8 (REVERSES the Aug 4 'substance not
                       # words' rule): "copy very similar what they do and
                       # say. theres a reason it is viral"
                       "Rules for using one — COPY CLOSE (owner order Aug 8: "
                       "this guide is already viral, the crowd voted on these "
                       "exact items in this exact order with this exact "
                       "phrasing — do not 'improve' what already won): mirror "
                       "the guide's structure, its items, its order, its "
                       "names/numbers/tool picks, and keep its punchy phrasing "
                       "wherever it is already tight — one thread item per "
                       "slide. Do NOT re-invent the list, generalize it, swap "
                       "in your own favorite tools, or add items they didn't "
                       "have. Only these three things get adapted:\n"
                       "1. THE HOOK — a tweet opener is not an Instagram "
                       "cover. Start from THEIR hook line and refit it to "
                       "this container's cover format (the N-promise rules "
                       "below), their promise + their numbers carried over "
                       "intact. The tweet's angle IS the viral asset — every "
                       "hook_candidate must keep it, they compete on fit not "
                       "on new angles.\n"
                       "2. FORMAT — our slide/caption/CTA structure, our "
                       "design, our QA rules (no dashes, plain-name credits).\n"
                       "3. TRUTH — verify every claim against what the tools "
                       "actually do (TRUTH RULE); fix or drop ONLY what you "
                       "cannot stand behind, keep the rest verbatim-close.\n"
                       "Credit: the author's X ACCOUNT NAME exactly as given "
                       "in the 'by ...' line above, minus any @ (account "
                       "godofprompt -> \"Sources: godofprompt\") — the same "
                       "plain-name Sources style as every other post. Never "
                       "their real name, never an @tag, never on slides — "
                       "the bottom Sources line is the only credit. "
                       "Append the [x:ID] tag of the guide you "
                       "used to your \"topic\" label — a topic without the "
                       "tag is treated as a failed attempt and re-rolled. "
                       "SKIP a candidate only if it is not genuinely "
                       "teachable (a bare promise with no substance) or "
                       "overlaps ALREADY USED — then take the next candidate. "
                       "Self-inventing a topic while candidates sit here gets "
                       "the post flagged to the owner.\n")
    if must_anchor:
        # Aug 15 fix (3 self-invented posts Aug 13-15 while the pool was
        # exhausted): an empty guide pool must NOT mean invention — the
        # news stories below are all watchlist-viral, so riding one keeps
        # the owner's ground rule alive. Optional became MANDATORY.
        # Exec editions (Aug 18) are ALWAYS mandatory-anchor: the pool is
        # mostly beginner prompt-guides, so "pool non-empty" must not open
        # a self-invention door for this lane.
        reason = ("this edition NEVER invents a topic — an executive-grade "
                  "guide from the pool above or one of these live stories is "
                  "the only legal anchor"
                  if mode == "exec" else
                  "the viral-guide pool is empty, and this page NEVER "
                  "invents a topic")
        tips_block = f"""
TODAY'S NEWS — MANDATORY anchor ({reason} — owner GROUND RULE Aug 12: everything rides an ALREADY-VIRAL X wave): build the guide ON one of these live stories — real utility a business owner can use tonight, born from the story ("GPT-5 dropped yesterday — 5 things it already does for your business"). Name the story inside your "topic" label as the why-now. If a story cannot carry genuine utility, take the next one; picking a pillar topic with no story anchor gets the post flagged to the owner.
{headlines}
"""
    else:
        tips_block = (f"""
TODAY'S NEWS — optional anchors: a guide that piggybacks a live story rides its wave ("GPT-5 dropped yesterday — 5 things it already does for your business"). Use one ONLY if you can build genuine utility on it; never force it:
{headlines}
""" if headlines else "")
    exec_block = ""
    if mode == "exec":
        exec_block = """
EXECUTIVE LANE — TODAY'S EDITION (owner order Aug 18; where this conflicts with the pillar list or skill-slide rules below, THIS block wins): this slot serves a DIFFERENT reader — a founder, CEO, executive or investor who already understands AI at a user level. NOT a beginner, NOT an engineer. BANNED for this reader: prompt listicles, "AI prompts that save you thousands", chatbot tips, beginner explainers ("this is not interesting" — owner). What they stop for: strategy and capital plays backed by hard numbers.
- SOURCE (the ground rule still stands — everything rides an already-viral X wave): anchor on the single most business-consequential item available — a listed guide ONLY if it is genuinely executive-grade (capital, hiring, margins, pricing, strategy), otherwise the most consequential TODAY'S NEWS story. Name it in your "topic" label, prefixed "EXEC:".
- THE FRAMEWORK RULE (Jack Butcher / Visualize Value — executives save FRAMEWORKS, not tips): distill the source into ONE named framework and put the NAME on the cover ("THE 2,600-DESK RULE", "THE $20K BOOTSTRAP PLAYBOOK"). One framework per post, never two. The cover = framework name + its wildest number, 6-10 words.
- REGISTER: minimum words, oversized numbers, one idea per slide carried by type, not paragraphs. Each content slide = ONE move of the framework: headline = the move as a 4-8 word factual claim with its number; body in 1/3/1 and ≤20 words — the punch, the real number behind it, one open line teeing the next move. "You" lines address THEIR operation ("your payroll", "your board", "your margin").
- THE READER TEST per slide: would a bored billionaire on a plane screenshot this? Zero motivational-poster lines, zero generic advice — every claim carries a number or name from the source material.
"""
    return f"""{doctrine()}You write Instagram carousels for @yaffeai — an AI-news page in the style of @technology, funneling followers to an AI-consulting business. Today's post is the **ai_education** container: {'a high-signal executive intelligence carousel' if mode == 'exec' else 'an educational save-magnet carousel'}. No news story — you pick the topic.

CONTAINER SPEC (ai_education): {json.dumps(spec['containers']['ai_education'])}
CAPTION BLOCKS: {json.dumps(spec['caption_blocks'])}
QA GATE: {json.dumps(spec['qa_gate'])}
{exec_block}{guide_block}
TOPIC — when no viral guide above fits, pick ONE fresh angle from these pillars (NOT one already used, listed below). The reader to serve FIRST is a business owner / entrepreneur (the page's funnel audience): weight topics toward what saves a business money or hours, or makes it money — consumer angles are allowed but the business angle should win ties.
WHY-NOW RULE (owner doctrine Aug 1 — even a guide must be current or viral, never evergreen filler): every topic must have a nameable reason to exist TODAY — a tool/feature released or meaningfully updated in the last ~60 days, or a live news story (see TODAY'S NEWS below when present). Novelty is measured against the AUDIENCE: a 3-week-old tool most people haven't heard of still counts as new; a generic tip list that could have run unchanged in 2023 ("10 ChatGPT productivity tips") is BANNED no matter how useful. State the why-now inside the "topic" label.
- Claude Code: the tool where you type plain English and it builds/fixes/automates entire things. Its wildest real abilities, explained like magic tricks anyone can try.
- Free AI powers: things ChatGPT/Claude/AI tools can do TODAY that most people have no idea about — for their money, their work, their business.
- True builder stories: real, widely-reported people (or a roundup of them) who couldn't code and still shipped real apps/businesses with AI.
- Prompt recipes: a famous thinking framework turned into ONE copy-paste prompt ("I had AI review my business with Elon Musk's 5-step algorithm" / "the prompt that finds what to automate first") — the slide TEACHES the exact prompt, short enough to retype from a screenshot. These are save-magnets: the reader keeps the post to use the prompt. Business-flavored recipes work great ("here are the 5 most common objections I hear on sales calls, list them. For each one give me a 2-sentence response that reframes it using a specific number or case study"). Cover flavor that crushes: the early-window analogy ("LEARNING CLAUDE RIGHT NOW IS LIKE BUYING BITCOIN IN 2016. HERE ARE 7 PROMPTS...").
- Free money tools: REAL, findable free things people use to make money or get hired — famous free GitHub projects ("PEOPLE ARE QUIETLY PRINTING CASH WITH FREE GITHUB REPOS", each slide names one real project and what people do with it) or free certifications/courses from big tech companies ("BIG TECH COMPANIES ARE GIVING AI CERTIFICATIONS AWAY FOR FREE", each slide: the cert, who gives it, where to get it). Every item must actually exist and actually be free.
- Hidden powers: true settings, modes, and prompts that unlock more from Claude/ChatGPT than the default experience ("SECRET CODES FOR CLAUDE THAT BREAK ITS LIMITS" register). Forbidden-knowledge framing is the hook, but every "secret" must be a real documented feature that works tonight.
ALREADY USED — never repeat or closely overlap:
{used}
FORMAT ROTATION (owner order Sep 1 — the page shipped a day of near-identical "5 prompts" listicles and the owner called the repetition the #1 content failure): look at the most recent entries in ALREADY USED. If they are prompt-recipe listicles, this post must NOT be another one — pick a different pillar (a new feature demonstrated, builder stories, free money tools, hidden powers) and a different cover formula. Two same-shaped listicles in a row is a failed post even if the topics differ.
{tips_block}

{principles()}

TRUTH RULE (absolute): every skill must genuinely work and every story must be real and widely reported. NEVER invent people, revenue numbers, or apps. If you are not certain a story is true, write a capability demo instead ("you can build X tonight — here's how"). Skills you demonstrate must be things the tools actually do.

OUTPUT — a single JSON object: {{"topic": "...", "slides": [...], "caption": "...", "pinned_comment": "..."}}
"pinned_comment": the first comment we plant the second the post publishes (hour-one comment velocity = distribution fuel). For this container: a question that makes readers pick ("Which one are you trying tonight? Slide 4 is the sleeper") or a bonus tip that didn't fit. 1-2 sentences, no hashtags, no links.
"topic": a 5-10 word label of the angle (goes in the dedupe log).
Slide structure:
Also "hook_candidates": FIVE cover headlines, each with <em> accents. {'When you used a viral guide above: ALL FIVE keep that guide\'s own hook angle and promise (owner rule Aug 8 — the tweet\'s angle is the viral asset, never trade it for a "better" one); they compete on Instagram FIT — wording, rhythm, which number leads, what the <em> accent lands on — not on new angles.' if guides else 'FIVE genuinely different angles — money saved, jobs replaced, scarcity subject, threat framing — not rewordings.'} Put your best on the cover slide AND among the five; a blind judge picks the winner.
1. type "cover": the N-promise hook per the container spec — a NUMBER in the headline, scarcity subject when true, everyday words only ("a tool where you type plain English and it writes the whole app" — never "CLI", "agentic", "repo"). HARD CAP 10 words, aim 5-8 (owner doctrine Jul 29: the cover sells curiosity, short = giant letters; the renderer caps total block height so long covers just shrink). The N-promise IS the information gap — promise the N things, never list any of them on the cover ("if someone can understand the whole story from the cover, you failed"). But specific: if the cover could describe 100 different posts, it also failed — anchor to ONE concrete tool/outcome. The reader must think "What are they?" / "How?" — the moment that question disappears, rewrite. THE KICKER (forensic Aug 2 — the reference pages put a second hook beat in the tiny strip under the headline: "NONE OF THESE NEED A NEW ROUTER", "HERE ARE 10 WILD EXAMPLES"): the cover MAY set "kicker": 3-7 words, the enemy-contrast or bonus promise NOT already in the headline; omit it if there is no true second beat (the strip then says "Swipe for more"). No other subline exists — the whole hook lives in the big words (put the franchise "AI CHEAT CODES VOL. {vol}" tag in the caption's first block instead, it is still the series people subscribe to). hsize 66-80 — the type must be HUGE, 3-5 edge-to-edge lines. Cover self-test: would a stranger scrolling at 2am save this for later? Below 8/10 shock+utility → rewrite.
COVER IMAGE (mandatory): the cover MUST set "image_brief" — an empty dark cover is dead in the feed; the image sells the promise before anyone reads. FAMOUS-PERSON FIRST (owner rule Aug 2, "this should be a rule"; CAST TRUTH limit Aug 10 after the Sam Altman content-vendor cover): ONLY when the topic IS a famous company's or famous person's own thing — their product, their tool, their courses, their move — the cover subject IS that recognizable person CAST IN THE PROMISE'S ROLE. "The topic is AI" is NOT a tie for a story naming NO tool — but THE VENDOR CAST (owner's reference wall Aug 12, the page's signature move and the DEFAULT for every prompts/guide cover): a guide about USING a named famous tool IS that vendor's story, so cast the vendor's famous CEO as the tool's own delighted USER — mid-performing the READER's exact action with the guide's real prop at one peak emotion (Dario Amodei proudly holding HIS OWN resume for an "upload your resume to Claude" guide; Dario in a Hawaiian shirt grinning over a discount-stamped boarding pass for a cheap-flights guide; Sundar Pichai leaning from a helicopter showering Gemini sparks onto reaching hands for "Gemini Pro free for students"). Tool→face: ChatGPT→Sam Altman, Claude→Dario Amodei, Gemini→Sundar Pichai, Grok→Elon Musk, Copilot→Satya Nadella, Llama→Mark Zuckerberg; the model your prompts run on counts even when the headline only says "AI prompts" — write the FULL NAME in the brief AND in "face". The PROP IS THE PROMISE (the resume, the bill, the boarding pass) held large; the CEO's hands DO the promise's verb. Only a topic naming NO tool at all goes faceless — and then just as BIG: the logo/mascot ACTING the promise at theatrical scale, the payoff object at impossible scale mid-action, never a calm product shot. ICONIC-MOMENT EXCEPTION (owner Aug 10): on an inspirational/entrepreneurial promise, a famous founder's KNOWN iconic real moment that EMBODIES the title is legal (young Zuckerberg coding in his dorm for a build-from-nothing promise) — the stranger must instantly read why THIS person in THIS scene proves THIS title, mid-performance with the role's real props — write their FULL NAME in the brief (up to 3 people) AND return "face" listing the same names (the brief then routes to a premium model that knows famous faces natively). BREAK THE PATTERN (owner Aug 2: "we must break the normal thoughts when users see the images... not necessarily gangsters, but change the thinking pattern and make it unique"): the scene must be one the viewer has NEVER seen that person in, still literally connected to the promise — Google tricks → Sundar Pichai as a street-market vendor handing out tricks like fruit. Any never-seen staging works (a workshop, a heist, a kitchen, a street market) as long as the props ARE the promise; vary it post to post, never repeat one costume gimmick. A boardroom, desk or stage keynote is a FAILURE — the viewer scrolls past what they have seen before. A recognizable face in an impossible scene stands out harder than any object. Only when NO famous person fits the topic, fall back to objects: for N-thing posts the reference look is a CUT-OUT COLLAGE: 2-3 distinct large subjects layered and overlapping with depth (like three fighter jets stacked for "9 MOST EXPENSIVE AIRCRAFT"), filling the whole upper frame, mid-tone so white type pops against it. For a single-promise cover: one evidence subject large in frame (a fanned stack of hundred dollar bills, a stethoscope on a dark table). 15-40 words, subject FIRST, then action, then setting; NAME real devices/brands; end with ONE color key ("keyed to azure blue"). NEVER make a document, bill, letter, or chat screen the subject — Seedream fills them with garbled fake text and QA rejects the image; pick text-free objects (cash, devices, tools, faces). No text in the image except at most one short double-quoted phrase on a device screen when that phrase IS the claim.
2-. type "content", 4-7 slides, one skill or story each, per the container payload_rule:
   - SKILL slide: headline "N) IMPERATIVE VERB + the thing" (e.g. "1) TURN A NAPKIN SKETCH INTO A WORKING APP"), then body FORMATTED FOR SCANNABILITY (owner order Aug 22 — dense walls of text are a failure; reference: @getintoai's organized, breathing prompt slides):
     FIRST a concrete proof line — a real dollar amount, hour count, or before/after a person actually got ("He pasted a $1,200 hospital bill into Claude. It dropped to $180") — never a generic "most people don't know" opener, and NEVER platform attribution (owner rule Jul 28: no "One Reddit user...", "a Twitter thread says" — "people want purely the story"; tell it directly with "a guy / he / a 60-year-old", the platform belongs only in the caption's Sources line).
     Then a BLANK LINE (\n\n) as a visual separator.
     Then THE PROMPT itself, verbatim in quotes (owner rule Jul 28: NO numbered steps, NO "open ChatGPT", NO "paste/upload your bill" instructions — everyone knows how to use a chatbot; the prompt IS the payload), structured for readability:
     • Paragraph breaks (\n\n) between distinct instructions within the prompt
     • When the prompt asks for MULTIPLE THINGS (features, checks, items), list them as bullet points on separate lines (\n• Item 1\n• Item 2\n• Item 3) — never inline a list as one long sentence
     • Each major ask on its own line — a reader should understand the prompt's structure at a glance without reading every word
     • If the prompt has a closing instruction after the list, put it on its own line after a blank line
     Make the prompt SELF-CONTAINED so context lives inside it ("Here is my medical bill. Find every charge that looks inflated and write a dispute letter") and short enough to retype from a screenshot. Write it like a secret being handed over, not a manual. A body that looks like one dense paragraph is a failed slide — rewrite it with structure. Content slides MAY set "image_brief" (same rules as the cover) when a vivid evidence scene exists for the claim — the 1-2 most visual slides should have one.
   - BUILT-IT slide: headline DNA — physical past-tense verb + number ("A 60-YEAR-OLD WHO CAN'T CODE SHIPPED AN APP TO 1,000 USERS"). Body: 2-3 sentences, every sentence a concrete number/name in <b>.
   Slide 2 doubles as SECOND COVER (Instagram re-serves skipped carousels with slide 2 up front) — it must hook standalone, so put the single most jaw-dropping skill/story there.
   COVER CONTRACT (owner rule Aug 1, "5 whole jobs" post-mortem: a reader "just didn't understand the connection" between the cover and the slides): whatever frame the cover promises (JOBS, EMPLOYEES, SERVICES, SECRET CODES...), EVERY skill slide must cash that exact frame in its proof line — say the connection out loud, never leave it for the reader to infer. If the cover says "5 WHOLE JOBS HANDED TO AI", each proof line opens by naming the human job replaced and what it costs: "A billing advocate charges $150 an hour to fight bills like this. He let Claude do it: $1,200 dropped to $180". Self-test per slide: if this slide would read fine under a completely different cover, the thread is broken — rewrite the proof line so cover → slide 2 → slide 3 reads as ONE continuous story, obvious even to a reader whose English is weak.
Last. type "cta": THE SAVE CLOSE (owner order Aug 18 — the last slide is built to be SAVED, never a generic closer): headline = a save-command mirroring the cover's N-promise, 6-11 words ("SAVE THIS: ALL 6 SERVICES AI DOES FREE"). Body = the recap CHECKLIST: the N promised items as newline-separated lines, one per item, each ≤6 words (just the item's name/verb, no prompts), in slide order — this one-screen recap is WHY people tap save. Final line: the page-as-service line ("Daily AI news + real skills"). The renderer draws the checkmarks and a "Send this to a friend" pill — never write a follow or send ask into your text.

RULES
- LANGUAGE (hard requirement): a smart 16-year-old must get every line instantly. Say what things DO, never what they're called.
- <em>...</em> in headlines = the accent: ONE contiguous phrase, ideally a whole line (two groups max). Orange on entire lines creates rhythm; orange scattered across four single words is confetti — four focal points = zero. <b>...</b> in bodies = facts/steps keywords. No <em> in bodies.
- hsize: cover 66-80 (huge type, 2-4 edge-to-edge lines), inner short headlines 100-124, medium 90-105, long 76-88.
- Bodies never end with a period. No emojis in slides. Zero hype adjectives (insane/crazy/mind-blowing) — the facts carry it.
- Caption: all five blocks in order, blank-line separated. First sentence = the payoff (only ~125 chars show). Sources line: "Sources: Anthropic" plus any outlet a story came from. Exactly five hashtags. CTA utility-only ("save this"), never reaction-bait.
- Caption owner-CTA (mandatory): LAST line of the trend block, own line — business owners DM the word exactly "AI" ("Running a business? DM us "AI" and we'll show you what this could do for yours" — vary wording per post).

Return ONLY the JSON object, no markdown fences, no commentary."""


def main():
    # EDU_MODE=exec (owner order Aug 18): the hour-13 slot alternates between
    # the skills save-magnet and the executive intelligence edition — high-
    # signal framework posts for founders/CEOs/investors, set in the workflow
    mode = os.environ.get("EDU_MODE", "skills")
    print(f"edu lane mode: {mode}", file=sys.stderr)
    # LISTICLE OVERFLOW (owner audit Aug 27): the owner's core complaint was
    # "every time it is '6 things you can do with AI'" — Aug 13-27 EVERY slot
    # fell to this floor (71/71 listicles). One listicle/day is the designed
    # 13:00 slot; a 2nd+ means the news ladder collapsed again. Count BEFORE
    # this run creates its own dir; the flag rides post.json so the daily
    # report names every overflow day.
    listicle_overflow = bool(
        glob.glob(os.path.join(HERE, "posts", f"{date.today()}-edu-*")))
    if listicle_overflow:
        print("WARNING: LISTICLE OVERFLOW — an edu post already exists today; "
              "this slot fell through the news ladder to the listicle floor "
              "(check story supply / gate A kills)", file=sys.stderr)
    used = json.load(open(USED)) if os.path.exists(USED) else []
    headlines = ""
    try:  # fresh stories.json exists when the workflow ran scout first
        stories = json.load(open(os.path.join(HERE, "stories.json")))
        headlines = "\n".join(f"- {s['title']}" for s in stories[:10])
    except Exception:
        pass
    guides = viral_guides(used)
    # pool empty + live viral stories -> anchoring on one is mandatory
    # (Aug 15: self-inventing is the LAST rung, not the first fallback).
    # Exec mode: anchoring is ALWAYS mandatory when stories exist — the
    # guide pool is mostly beginner material, so its mere presence must
    # not let an exec edition self-invent (owner Aug 18: real recent X
    # data, never invented content).
    must_anchor = bool(headlines) and (not guides or mode == "exec")
    if guides:
        print(f"viral X guides on the radar: "
              + ", ".join(f"@{g['sub']} ({g.get('score', 0):,} likes)"
                          for g in guides), file=sys.stderr)
    else:
        # owner Aug 10: an empty pool forcing a self-invented topic is
        # UNACCEPTABLE — the wide guide net (radar_x) should keep guides.json
        # deep. Ship the slot (always-post law) but scream so the daily
        # report names it and the pool starvation gets fixed at the source.
        print("WARNING: guide pool EMPTY — "
              + ("writer must anchor on a viral news story"
                 if must_anchor else "writer will self-invent a topic "
                 "(owner: unacceptable; check radar wide guide net / "
                 "guides.json)"),
              file=sys.stderr)
    prompt = build_prompt(used, headlines, guides, must_anchor, mode)
    # 2 rolls, not 3 (token diet Aug 8): the workflow ladder re-runs edu.py
    # fresh as its last rung anyway, so a third in-process roll is redundant.
    def edu_qa(p):  # shared qa + this container's own gate, one verdict
        e = qa(p)
        for i, s in enumerate(p.get("slides", [])):
            if re.search(r"(?i)\bhow to:|\bstep \d|\b(open|go to) (chatgpt|claude"
                         r"|chat\.com|claude\.ai)", s.get("body", "")):
                e.append(f"slide {i+1}: app-navigation steps are banned — "
                         "give the self-contained prompt itself, in quotes")
        # COVER HARD CAP made mechanical (Aug 19 post-mortem: two 19-20 word
        # covers shipped despite the prompt's "HARD CAP 10 words" — prompt
        # rules without a gate are suggestions). The cover sells curiosity;
        # short = giant letters. Cap 12 (10 + slack for $-amounts counting
        # as words) so the gate rejects runaways, not near-misses.
        cov = (p.get("slides") or [{}])[0]
        cwords = len(re.sub(r"<[^>]+>", " ", cov.get("headline") or "").split())
        if cwords > 12:
            e.append(f"cover headline is {cwords} words — HARD CAP is 10 "
                     "(aim 5-8): cut it to the N-promise itself, move the "
                     "story detail to slide 2")
        # save-close recap (owner order Aug 18): the CTA is a one-screen
        # checklist of the N promised items, never a generic closer
        slides = p.get("slides") or [{}]
        if slides[-1].get("type") == "cta":
            head = re.sub(r"<[^>]+>", "", slides[-1].get("headline") or "")
            if not re.search(r"(?i)\bsave\b", head):
                e.append('cta headline must be a save-command ("SAVE THIS: '
                         '...") mirroring the cover promise')
            lines = [l for l in (slides[-1].get("body") or "").split("\n")
                     if l.strip()]
            if len(lines) < 3:
                e.append(f"cta body has {len(lines)} line(s) — the save close "
                         "is a recap CHECKLIST: the promised items as "
                         "newline-separated lines (≤6 words each) plus the "
                         "page-as-service line")
        return e

    for attempt in range(2):
        post = call_claude(prompt, schema=SCHEMA)
        errs = edu_qa(post)
        if errs:
            print(f"QA gate failed (attempt {attempt+1}):\n  " + "\n  ".join(errs),
                  file=sys.stderr)
            # REPAIR PASS (Aug 8, run 31259996256 post-mortem: this ladder's
            # LAST rung died at attempt 2 on ONE leftover error — "slide 7:
            # headline has no <em> accent" — because edu never inherited the
            # Aug 2 surgical-repair pass that write.py's loop has. A copy-edit
            # of only the flagged lines converges; full regeneration is a
            # fresh dice roll on 20+ gates.)
            fixed = qa_repair(post, errs)
            if fixed:
                left = edu_qa(fixed)
                # SECOND REPAIR ROUND (Aug 28, run 33171169866: the forced
                # guide-copy attempt died with the first repair shrinking 12
                # errors to 6 formatting-only leftovers. Same fix as write.py's
                # loop — repair once more while the list is shrinking.)
                if left and len(left) < len(errs):
                    again = qa_repair(fixed, left)
                    if again and not edu_qa(again):
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
        # GUIDE-POOL ENFORCEMENT (owner ground rule Aug 12 — ride the wave,
        # never invent): the prompt's escape hatch was abused — only 9/51 edu
        # posts ever used a guide, the last 4 self-invented while 7 viral
        # guides sat in the pool. A tag-less topic with a live pool is a
        # failed roll. Last attempt ships anyway (always-post law) and gets
        # flagged ignored-pool below.
        # exec mode is exempt (owner Aug 18): a beginner prompt-guide must
        # never be forced on the executive edition — its prompt block already
        # mandates riding the most business-consequential viral item instead
        if (attempt == 0 and guides and mode != "exec"
                and not real_tag(post.get("topic"), guides)):
            g = guides[0]
            errs.append(f"you IGNORED the viral guide pool — using a listed "
                        f"guide is MANDATORY (owner ground rule). Build this "
                        f"post FROM the guide by {g['sub']} "
                        f"({g.get('score', 0):,} likes), COPY IT CLOSE, and "
                        f"append its [x:{g['id']}] tag to your \"topic\" label. "
                        f"A made-up tag like [x:none] does NOT count — the tag "
                        f"must be the exact id of a guide listed above")
            print(f"guide-pool enforcement: roll {attempt+1} ignored the pool "
                  f"— re-rolling on @{g['sub']}", file=sys.stderr)
        # UNIQUENESS GATE (owner Aug 14: "every post is by itself and unique
        # — if we repeat ourselves no one will follow". The 1-star-reviews
        # guide published near-identically twice in 2 days; the Claude-leak
        # story twice in ONE day: the same viral guide re-enters the pool
        # under a new X id, and the topic-label list can't catch wording-level
        # repeats). write.py's semantic dupe judge now guards this lane too.
        # A duped guide gets its tag consumed so no later run re-offers it.
        if not errs:
            cover_h = re.sub(r"</?em>", "", next(
                (s.get("headline", "") for s in post.get("slides", [])), ""))
            plain_topic = re.sub(r"\s*\[x:[^\]]+\]", "", post.get("topic", ""))
            if is_dupe(f"{plain_topic} — cover: {cover_h}"):
                if real_tag(post.get("topic"), guides):
                    used.append(f"(dupe suppressed) {post['topic']}")
                    json.dump(used, open(USED, "w"), indent=1)
                    guides = viral_guides(used)
                errs.append(
                    "DUPLICATE POST: this is the same underlying story/guide "
                    "as one ALREADY PUBLISHED on the page (see ALREADY USED). "
                    "Pick a DIFFERENT guide from the pool, or a different "
                    "pillar angle, with a genuinely different promise")
                print("uniqueness gate: post duplicates an already-published "
                      "one — re-rolling", file=sys.stderr)
        if not errs:
            break
        must_anchor = must_anchor or (not guides and bool(headlines))
        prompt = (build_prompt(used, headlines, guides, must_anchor, mode)
                  + "\n\nYOUR PREVIOUS ATTEMPT FAILED THESE QA CHECKS — fix every one:\n- "
                  + "\n- ".join(errs))
    else:
        raise SystemExit("QA gate failed after 2 attempts")

    # the tournament swaps its winner onto the cover AFTER the qa loop —
    # drop over-cap candidates first or the 10-word gate above is bypassed
    # by the very mechanism meant to pick the best hook (Aug 19 post-mortem)
    # (all over-cap -> empty list -> tournament keeps the qa-approved cover
    # and flags "no-valid-winner" for the daily report — never a bypass)
    def _cwords(c):
        head = c.get("headline") if isinstance(c, dict) else c
        return len(re.sub(r"<[^>]+>", " ", head or "").split())
    post["hook_candidates"] = [
        c for c in post.get("hook_candidates", []) if _cwords(c) <= 12]
    post = viral.tournament(post, None, {  # value posts: fixed classification
        "story_type": "edu_value", "actor": "", "actor_known": True,
        "anchor": "", "specifics": []})
    topic = post.pop("topic", "untitled")
    print("topic:", topic, file=sys.stderr)
    post.update(handle="@yaffeai", container="ai_education", edu_mode=mode)
    if listicle_overflow:
        post["listicle_overflow"] = True  # 2nd+ listicle today (Aug 27)

    post_dir = os.path.join(HERE, "posts", f"{date.today()}-edu-{slugify(topic)}")
    os.makedirs(post_dir, exist_ok=True)

    art_direct(post)  # optimal image prompts before generation

    # Seedream evidence images (owner verdict Jul 28: an imageless edu cover is
    # "the same template running at 40% capacity" — the cover image is mandatory,
    # the 1-2 most visual content slides optional). Budget guard caps spend.
    # Upgraded Jul 29: scored judging + flaw-steered retry + best-of-rejected
    # pool so the cover NEVER ships imageless.
    gen = 0
    pool = []  # rejected cover candidates as (score, path)
    cover_face = None  # real press photo kept as the cover's last-resort floor
    cover_brief = ""  # the cover's final brief, kept for the <=4 rescue rung
    for i, s in enumerate(post["slides"]):
        brief = s.pop("image_brief", "").strip()
        s["media"] = None
        # PERSON ROUTE (rebuilt Sep 3): under the Aug 30 nano-only regime the
        # cover model is nano-banana, which copies likeness from PRESS PHOTOS
        # — with no refs it draws famous faces from memory. This route was
        # still calling with no refs (a gpt-image-2 era leftover: "names in
        # the prompt, no refs"), so every vendor-cast likeness failed QA and
        # the retries degraded the owner's signature CEO covers into faceless
        # object collages (the Sep 1-3 run). Now: press photos ride as refs,
        # exactly like write.py's news lane.
        face_field = s.pop("gen_face", None)
        if not face_field and s.get("face"):
            # owner audit Aug 10 (GPT-5 birthday cover): the WRITER cast a
            # legal famous face but the art brief dropped it, so the cover
            # silently went faceless — the writer's cast rides as fallback
            wf = s["face"]
            face_field = ", ".join(wf) if isinstance(wf, list) else wf
        person = bool(face_field)
        face_refs = []
        if not person:
            # incidental names in a no-face brief still kill Seedream (E005)
            brief, face_refs = face_riders(brief, None)
        brand = s.pop("gen_logo", None)
        brand_ref = logo_ref(brand.replace(" ", "")) if brand else None
        if s["type"] == "cover" and face_field:
            # real press photo as the cover's last-resort floor
            fp = face_riders("", face_field)[1]
            cover_face = fp[0] if fp else None
        if s["type"] == "cta" or not brief or gen >= 3:
            continue
        # cover tries 3 -> 2 (token diet Aug 8): each extra try = a vision
        # judge + a brief rewrite + Replicate spend; best-reject floor remains
        tries = 2 if s["type"] == "cover" else 1
        for attempt in range(tries):
            out_jpg = os.path.join(post_dir, f"gen-{i}{'-r' * attempt}.jpg")
            # audit trail (owner Aug 10): every attempted brief is logged,
            # the winning one is persisted into post.json
            print(f"slide {i+1} brief (attempt {attempt+1}): {brief}",
                  file=sys.stderr)
            path = None
            if person:
                # nano-with-refs rung: identity comes from the press photo.
                # Requires a photo for EVERY named person — no photo, no rung
                # (face_riders would silently strip a photo-less name to
                # "a person" and ship a stranger).
                names = split_faces(face_field)
                if names and all(pick_face(n.lower().replace(" ", "-"))
                                 for n in names):
                    nb, nrefs = face_riders(brief, face_field)
                    nrefs = [r for r in nrefs + [brand_ref] if r]
                    if nrefs:
                        path = genimg.generate(nb, out_jpg,
                                               cover=(s["type"] == "cover"),
                                               person=True, nano=True,
                                               refs=nrefs)
                if not path:
                    # no photo held for this cast (or nano flaked): names in
                    # the prompt, from-memory rung
                    path = genimg.generate(brief, out_jpg,
                                           cover=(s["type"] == "cover"),
                                           person=True)
                if not path:
                    # FALLBACK RUNG: Seedream + ref photos, names stripped (E005)
                    person = False
                    brief, face_refs = face_riders(brief, face_field)
            if not path:
                refs = face_refs + ([brand_ref] if brand_ref else [])
                path = genimg.generate(brief, out_jpg, refs=refs or None,
                                       cover=(s["type"] == "cover"))
            if not path:
                # keep trying: one flaky prediction must not forfeit the cover
                # (Aug 2 bare cover, issue #16); budget-out retries are free
                # local no-ops so continue is safe either way
                continue
            ok, score, flaw = image_score(path, s["headline"], generated=True,
                                          person=person,
                                          cover=(s["type"] == "cover"))
            if ok:
                s["media"] = os.path.relpath(path, HERE)
                s["image_prompt"] = brief
                gen += 1
                break
            print(f"slide {i+1} image rejected (attempt {attempt+1}/{tries}, "
                  f"score {score}/10): {flaw}", file=sys.stderr)
            if s["type"] == "cover":
                pool.append((score, path))
            if attempt + 1 < tries:
                # person-route covers retry concept-preserving (Aug 9): keep
                # the staged scene + cast, fix only the judge's named flaw
                brief = simpler_brief(brief, s["headline"], flaw,
                                      mode="concept" if person else "simpler") or brief
                if not person:
                    # the rewrite sees the headline, which may name real
                    # people — re-scrub or the Seedream retry dies to E005
                    brief = face_riders(brief, None)[0]
        if s["type"] == "cover":
            cover_brief = brief
    # cover last rung: best-of-rejected so the edu cover never ships imageless
    cover0 = post["slides"][0]
    if not cover0.get("media") and pool:
        score, best = max(pool, key=lambda t: t[0])
        # RESCUE RUNG (owner audit Aug 10): a <=4/10 best reject is wallpaper —
        # one cheap faceless Seedream attempt via the no-face playbook before
        # settling for it. Always-post intact: best reject stays the floor.
        if score <= 4 and cover_brief:
            rb = simpler_brief(
                cover_brief, cover0.get("headline", ""),
                flaw=f"best attempt scored {score}/10 — rebuild as a FACELESS "
                     "scene per the no-face playbook: the famous logo or the "
                     "story's object mid-action at theatrical scale, no human "
                     "faces anywhere")
            if rb:
                rb = face_riders(rb, None)[0]
                rp = genimg.generate(rb, os.path.join(post_dir,
                                                      "gen-0-rescue.jpg"),
                                     cover=True)
                if rp:
                    ok2, s2, _ = image_score(rp, cover0.get("headline", ""),
                                             generated=True, cover=True)
                    if ok2:
                        cover0["media"] = os.path.relpath(rp, HERE)
                        cover0["image_prompt"] = rb
                        post["cover_fallback"] = "no-face rescue"
                        print(f"EDU COVER rescued by the no-face rung "
                              f"({s2}/10)", file=sys.stderr)
                    elif s2 > score:
                        pool.append((s2, rp))
                        score, best = max(pool, key=lambda t: t[0])
    if not cover0.get("media") and pool:
        cover0["media"] = os.path.relpath(best, HERE)
        if cover_brief:
            cover0["image_prompt"] = cover_brief
        post["cover_fallback"] = f"best-of-rejected ({score}/10)"
        print(f"EDU COVER: nothing passed QA — shipping the best reject "
              f"({os.path.basename(best)}, score {score}/10)", file=sys.stderr)
    elif not cover0.get("media") and cover_face:
        # real-photo floor (owner rule Aug 2, bare billionaire cover: a cover
        # NEVER ships imageless — the person's real press photo beats nothing)
        cover0["media"] = os.path.relpath(cover_face, HERE)
        post["cover_fallback"] = "real-face-photo"
        print("EDU COVER: generation failed every rung — shipping the real "
              "press photo of the topic's person instead", file=sys.stderr)
    elif not cover0.get("media"):
        post["cover_fallback"] = "no-image"
        print("EDU COVER HAS NO IMAGE — generation returned nothing; "
              "flagged for the daily report", file=sys.stderr)
    print(f"{gen} Seedream image(s) generated", file=sys.stderr)
    scrub_dashes(post)  # owner rule: dashes never reach a published slide

    # GATE B — editor-in-chief final review (owner order Aug 4). edu.py is the
    # workflow ladder's LAST rung, so unlike write.py it never exits nonzero
    # on a final REJECT: it takes one surgical repair, and if the editor still
    # objects it ships FLAGGED (editor_override) so the daily report screams —
    # the 7/day rule beats the standard only at the very bottom of the ladder.
    import editor
    cm = post["slides"][0].get("media")
    cover_path = os.path.join(HERE, cm) if cm else None
    ok, reasons = editor.gate_b(post, cover_path)
    if not ok:
        fixed = qa_repair(post, ["editor reject: " + r for r in reasons])
        if fixed and len(fixed.get("slides", [])) == len(post["slides"]):
            # THE REPAIR IS NOT A QA BYPASS (Aug 19 "6-bleed" post-mortem:
            # this repair rewrote the cover to 14 words and the kicker to 10
            # — both over mechanical caps — and shipped, because nothing
            # re-checked qa after the merge; the cover rendered with the
            # headline printed over the kicker strip). Merge, re-run the
            # mechanical gates, and revert the whole repair if it introduced
            # NEW violations — the pre-repair post ships flagged instead.
            keep = json.loads(json.dumps(post))
            for s_old, s_new in zip(post["slides"], fixed["slides"]):
                for k in ("headline", "body", "kicker"):
                    if s_new.get(k):
                        s_old[k] = s_new[k]
            if fixed.get("caption"):
                post["caption"] = fixed["caption"]
            scrub_dashes(post)
            base = edu_qa(keep)
            broke = [e for e in edu_qa(post) if e not in base]
            if broke:
                print("gate B repair broke mechanical qa — reverting the "
                      "repair:\n  " + "\n  ".join(broke), file=sys.stderr)
                post.clear()
                post.update(keep)
            else:
                ok, reasons = editor.gate_b(post, cover_path)
        if not ok:
            post["editor_override"] = "; ".join(reasons)[:400]
            print("EDITOR OVERRIDE: gate B still rejects after repair but this "
                  "is the ladder's last rung — shipping flagged for the daily "
                  "report: " + "; ".join(reasons), file=sys.stderr)

    if not guides:  # flag rides in post.json so daily.py names the post
        # news-anchored = still riding a viral wave (compliant, informational);
        # self-invented = both sources empty, the true last rung (flagged)
        post["topic_source"] = "news-anchored" if must_anchor else "self-invented"
    elif mode == "exec" and not real_tag(topic, guides):
        # exec edition legitimately rides the most consequential news story
        # instead of a beginner guide — informational, never a warning
        post["topic_source"] = "exec-news"
    elif not real_tag(topic, guides):
        # survived the re-roll and still ignored the pool — ship it
        # (always-post law) but the daily report names it to the owner
        post["topic_source"] = "ignored-pool"
        print(f"WARNING: post ships guide-less while {len(guides)} viral "
              "guides sat in the pool — flagged ignored-pool for the daily "
              "report", file=sys.stderr)
    json.dump(post, open(os.path.join(post_dir, "post.json"), "w"), indent=1)
    subprocess.run([sys.executable, os.path.join(HERE, "render.py"),
                    os.path.join(post_dir, "post.json"), post_dir], check=True)
    json.dump(used + [topic], open(USED, "w"), indent=1)
    print("post ready:", post_dir)
    return post_dir


if __name__ == "__main__":
    main()
