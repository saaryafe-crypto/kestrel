#!/usr/bin/env python3
"""Educational save-magnet writer (ai_education container): Claude Code powers,
AI skills anyone can use tonight, TRUE stories of what people built. No news
dependency — Claude picks a fresh angle, deduped via edu-used.json.
Usage: python3 edu.py"""
import json, os, re, subprocess, sys, time
import xml.etree.ElementTree as ET
from datetime import date

import genimg
import viral
from fetch import get
from write import (HERE, art_direct, call_claude, image_score, principles,
                   qa, scrub_dashes, simpler_brief, slugify)

USED = os.path.join(HERE, "edu-used.json")
TIP_SUBS = ["ClaudeAI", "ChatGPTPro", "PromptEngineering",
            "ArtificialInteligence", "ChatGPTCoding", "ClaudeCode"]


def reddit_tips():
    """Top self-posts of the week from AI-tips subreddits — crowd-validated
    demand ("9 things every Claude user must do", "I let Claude analyze my
    company with Musk's principles"). Titles + snippets guide topic choice;
    text is never copied. Any failure -> empty string, edu still runs."""
    ns = {"a": "http://www.w3.org/2005/Atom"}
    found = []
    for i, sub in enumerate(TIP_SUBS):
        if i:
            time.sleep(61)  # unauthenticated RSS rate limit: ~1 request/min
        try:
            root = ET.fromstring(get(f"https://www.reddit.com/r/{sub}/top.rss?t=week&limit=10"))
        except Exception as e:
            print(f"  ! reddit r/{sub}: {e}", file=sys.stderr)
            continue
        for e in root.findall("a:entry", ns)[:10]:
            title = (e.findtext("a:title", "", ns) or "").strip()
            html = e.findtext("a:content", "", ns) or ""
            # self posts only: their [link] href points back at reddit itself;
            # external hrefs mean a news link post (edu wants tips, not news)
            m = re.search(r'href="([^"]+)">\[link\]', html)
            if not title or (m and not re.search(r"reddit\.com|redd\.it", m.group(1))):
                continue
            text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()[:280]
            found.append(f"- r/{sub} [{title}] {text}")
    # receipts first: a tip with a real number ($ saved, hours, %) beats a
    # generically cool tip (audit Jul 29 — proof-of-value ranking)
    found.sort(key=lambda t: 0 if re.search(
        r"\$\d|\d+ ?(hours?|hrs|%|days?|k\b)", t, re.I) else 1)
    print(f"reddit tips: {len(found)} threads", file=sys.stderr)
    return "\n".join(found)

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
                    "subline": {"type": "string"},
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


def build_prompt(used_topics, tips="", headlines=""):
    spec = json.load(open(os.path.join(HERE, "containers.json")))
    used = "\n".join(f"- {t}" for t in used_topics) or "(none yet)"
    vol = len(used_topics) + 1  # franchise volume number (audit Jul 29)
    tips_block = (f"""
PROVEN DEMAND — this week's top threads in AI-tips communities (top-of-week = thousands of upvotes = people are hungry for exactly this right now). Use them to pick which skills/angles people want TODAY. NEVER copy their text or trust their claims blindly — verify against what the tools actually do, or frame as a capability demo:
{tips}
""" if tips else "")
    tips_block += (f"""
TODAY'S NEWS — optional anchors: a guide that piggybacks a live story rides its wave ("GPT-5 dropped yesterday — 5 things it already does for your business"). Use one ONLY if you can build genuine utility on it; never force it:
{headlines}
""" if headlines else "")
    return f"""You write Instagram carousels for @yaffeai — an AI-news page in the style of @technology, funneling followers to an AI-consulting business. Today's post is the **ai_education** container: an educational save-magnet carousel. No news story — you pick the topic.

CONTAINER SPEC (ai_education): {json.dumps(spec['containers']['ai_education'])}
CAPTION BLOCKS: {json.dumps(spec['caption_blocks'])}
QA GATE: {json.dumps(spec['qa_gate'])}

TOPIC — pick ONE fresh angle from these pillars (NOT one already used, listed below). The reader to serve FIRST is a business owner / entrepreneur (the page's funnel audience): weight topics toward what saves a business money or hours, or makes it money — consumer angles are allowed but the business angle should win ties.
WHY-NOW RULE (owner doctrine Aug 1 — even a guide must be current or viral, never evergreen filler): every topic must have a nameable reason to exist TODAY — a tool/feature released or meaningfully updated in the last ~60 days, a live news story (see TODAY'S NEWS below when present), or this week's proven community demand (see PROVEN DEMAND). Novelty is measured against the AUDIENCE: a 3-week-old tool most people haven't heard of still counts as new; a generic tip list that could have run unchanged in 2023 ("10 ChatGPT productivity tips") is BANNED no matter how useful. State the why-now inside the "topic" label.
- Claude Code: the tool where you type plain English and it builds/fixes/automates entire things. Its wildest real abilities, explained like magic tricks anyone can try.
- Free AI powers: things ChatGPT/Claude/AI tools can do TODAY that most people have no idea about — for their money, their work, their business.
- True builder stories: real, widely-reported people (or a roundup of them) who couldn't code and still shipped real apps/businesses with AI.
- Prompt recipes: a famous thinking framework turned into ONE copy-paste prompt ("I had AI review my business with Elon Musk's 5-step algorithm" / "the prompt that finds what to automate first") — the slide TEACHES the exact prompt, short enough to retype from a screenshot. These are save-magnets: the reader keeps the post to use the prompt. Business-flavored recipes work great ("here are the 5 most common objections I hear on sales calls, list them. For each one give me a 2-sentence response that reframes it using a specific number or case study"). Cover flavor that crushes: the early-window analogy ("LEARNING CLAUDE RIGHT NOW IS LIKE BUYING BITCOIN IN 2016. HERE ARE 7 PROMPTS...").
- Free money tools: REAL, findable free things people use to make money or get hired — famous free GitHub projects ("PEOPLE ARE QUIETLY PRINTING CASH WITH FREE GITHUB REPOS", each slide names one real project and what people do with it) or free certifications/courses from big tech companies ("BIG TECH COMPANIES ARE GIVING AI CERTIFICATIONS AWAY FOR FREE", each slide: the cert, who gives it, where to get it). Every item must actually exist and actually be free.
- Hidden powers: true settings, modes, and prompts that unlock more from Claude/ChatGPT than the default experience ("SECRET CODES FOR CLAUDE THAT BREAK ITS LIMITS" register). Forbidden-knowledge framing is the hook, but every "secret" must be a real documented feature that works tonight.
ALREADY USED — never repeat or closely overlap:
{used}
{tips_block}

{principles()}

TRUTH RULE (absolute): every skill must genuinely work and every story must be real and widely reported. NEVER invent people, revenue numbers, or apps. If you are not certain a story is true, write a capability demo instead ("you can build X tonight — here's how"). Skills you demonstrate must be things the tools actually do.

OUTPUT — a single JSON object: {{"topic": "...", "slides": [...], "caption": "...", "pinned_comment": "..."}}
"pinned_comment": the first comment we plant the second the post publishes (hour-one comment velocity = distribution fuel). For this container: a question that makes readers pick ("Which one are you trying tonight? Slide 4 is the sleeper") or a bonus tip that didn't fit. 1-2 sentences, no hashtags, no links.
"topic": a 5-10 word label of the angle (goes in the dedupe log).
Slide structure:
Also "hook_candidates": FIVE genuinely different cover headlines (different angles — money saved, jobs replaced, scarcity subject, threat framing — not rewordings), each with <em> accents. Put your best on the cover slide AND among the five; a blind judge picks the winner.
1. type "cover": the N-promise hook per the container spec — a NUMBER in the headline, scarcity subject when true, everyday words only ("a tool where you type plain English and it writes the whole app" — never "CLI", "agentic", "repo"). HARD CAP 10 words, aim 5-8 (owner doctrine Jul 29: the cover sells curiosity, short = giant letters; the renderer caps total block height so long covers just shrink). The N-promise IS the information gap — promise the N things, never list any of them on the cover ("if someone can understand the whole story from the cover, you failed"). But specific: if the cover could describe 100 different posts, it also failed — anchor to ONE concrete tool/outcome. The reader must think "What are they?" / "How?" — the moment that question disappears, rewrite. Also "subline" (the FRANCHISE masthead — this format is a recognizable weekly series people subscribe to): ≤48 chars all-caps, MUST begin exactly "AI CHEAT CODES VOL. {vol} — " followed by the N-promise or proof detail the headline dropped ("AI CHEAT CODES VOL. {vol} — 7 PROMPTS INSIDE"). hsize 66-80 — the type must be HUGE, 3-5 edge-to-edge lines. Cover self-test: would a stranger scrolling at 2am save this for later? Below 8/10 shock+utility → rewrite.
COVER IMAGE (mandatory): the cover MUST set "image_brief" — an empty dark cover is dead in the feed; the image sells the promise before anyone reads. For N-thing posts the reference look is a CUT-OUT COLLAGE: 2-3 distinct large subjects layered and overlapping with depth (like three fighter jets stacked for "9 MOST EXPENSIVE AIRCRAFT"), filling the whole upper frame, mid-tone so white type pops against it. For a single-promise cover: one evidence subject large in frame (a fanned stack of hundred dollar bills, a stethoscope on a dark table). 15-40 words, subject FIRST, then action, then setting; NAME real devices/brands; end with ONE color key ("keyed to azure blue"). NEVER make a document, bill, letter, or chat screen the subject — Seedream fills them with garbled fake text and QA rejects the image; pick text-free objects (cash, devices, tools, faces). No text in the image except at most one short double-quoted phrase on a device screen when that phrase IS the claim.
2-. type "content", 4-7 slides, one skill or story each, per the container payload_rule:
   - SKILL slide: headline "N) IMPERATIVE VERB + the thing" (e.g. "1) TURN A NAPKIN SKETCH INTO A WORKING APP"), then body: FIRST a concrete proof line — a real dollar amount, hour count, or before/after a person actually got ("He pasted a $1,200 hospital bill into Claude. It dropped to $180") — never a generic "most people don't know" opener, and NEVER platform attribution (owner rule Jul 28: no "One Reddit user...", "a Twitter thread says" — "people want purely the story"; tell it directly with "a guy / he / a 60-year-old", the platform belongs only in the caption's Sources line); then THE PROMPT itself, verbatim in quotes (owner rule Jul 28: NO numbered steps, NO "open ChatGPT", NO "paste/upload your bill" instructions — everyone knows how to use a chatbot; the prompt IS the payload). Make the prompt SELF-CONTAINED so context lives inside it ("Here is my medical bill. Find every charge that looks inflated and write a dispute letter") and short enough to retype from a screenshot. Proof line + prompt, nothing else. Write it like a secret being handed over, not a manual. Content slides MAY set "image_brief" (same rules as the cover) when a vivid evidence scene exists for the claim — the 1-2 most visual slides should have one.
   - BUILT-IT slide: headline DNA — physical past-tense verb + number ("A 60-YEAR-OLD WHO CAN'T CODE SHIPPED AN APP TO 1,000 USERS"). Body: 2-3 sentences, every sentence a concrete number/name in <b>.
   Slide 2 doubles as SECOND COVER (Instagram re-serves skipped carousels with slide 2 up front) — it must hook standalone, so put the single most jaw-dropping skill/story there.
Last. type "cta": "SAVE THIS" utility register — saving is the whole point of this format ("You'll want these when you try it — save this post"). Plus the page-as-service line ("Daily AI news + real skills").

RULES
- LANGUAGE (hard requirement): a smart 16-year-old must get every line instantly. Say what things DO, never what they're called.
- <em>...</em> in headlines = the accent: ONE contiguous phrase, ideally a whole line (two groups max). Orange on entire lines creates rhythm; orange scattered across four single words is confetti — four focal points = zero. <b>...</b> in bodies = facts/steps keywords. No <em> in bodies.
- hsize: cover 66-80 (huge type, 2-4 edge-to-edge lines), inner short headlines 100-124, medium 90-105, long 76-88.
- Bodies never end with a period. No emojis in slides. Zero hype adjectives (insane/crazy/mind-blowing) — the facts carry it.
- Caption: all five blocks in order, blank-line separated. First sentence = the payoff (only ~125 chars show). Sources line: "Sources: Anthropic" plus any outlet a story came from. Exactly five hashtags. CTA utility-only ("save this"), never reaction-bait.
- Caption owner-CTA (mandatory): LAST line of the trend block, own line — business owners DM the word exactly "AI" ("Running a business? DM us "AI" and we'll show you what this could do for yours" — vary wording per post).

Return ONLY the JSON object, no markdown fences, no commentary."""


def main():
    used = json.load(open(USED)) if os.path.exists(USED) else []
    tips = reddit_tips()
    headlines = ""
    try:  # fresh stories.json exists when the workflow ran scout first
        stories = json.load(open(os.path.join(HERE, "stories.json")))
        headlines = "\n".join(f"- {s['title']}" for s in stories[:10])
    except Exception:
        pass
    prompt = build_prompt(used, tips, headlines)
    for attempt in range(3):
        post = call_claude(prompt, schema=SCHEMA)
        errs = qa(post)
        for i, s in enumerate(post.get("slides", [])):
            if re.search(r"(?i)\bhow to:|\bstep \d|\b(open|go to) (chatgpt|claude"
                         r"|chat\.com|claude\.ai)", s.get("body", "")):
                errs.append(f"slide {i+1}: app-navigation steps are banned — "
                            "give the self-contained prompt itself, in quotes")
        if not errs:
            break
        print(f"QA gate failed (attempt {attempt+1}):\n  " + "\n  ".join(errs),
              file=sys.stderr)
        prompt = (build_prompt(used, tips, headlines)
                  + "\n\nYOUR PREVIOUS ATTEMPT FAILED THESE QA CHECKS — fix every one:\n- "
                  + "\n- ".join(errs))
    else:
        raise SystemExit("QA gate failed after 3 attempts")

    post = viral.tournament(post, None, {  # value posts: fixed classification
        "story_type": "edu_value", "actor": "", "actor_known": True,
        "anchor": "", "specifics": []})
    topic = post.pop("topic", "untitled")
    print("topic:", topic, file=sys.stderr)
    post.update(handle="@yaffeai", container="ai_education")

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
    for i, s in enumerate(post["slides"]):
        brief = s.pop("image_brief", "").strip()
        s["media"] = None
        if s["type"] == "cta" or not brief or gen >= 3:
            continue
        tries = 3 if s["type"] == "cover" else 1
        for attempt in range(tries):
            path = genimg.generate(brief, os.path.join(post_dir, f"gen-{i}{'-r' * attempt}.jpg"))
            if not path:
                break
            ok, score, flaw = image_score(path, s["headline"])
            if ok:
                s["media"] = os.path.relpath(path, HERE)
                gen += 1
                break
            print(f"slide {i+1} image rejected (attempt {attempt+1}/{tries}, "
                  f"score {score}/10): {flaw}", file=sys.stderr)
            if s["type"] == "cover":
                pool.append((score, path))
            if attempt + 1 < tries:
                brief = simpler_brief(brief, s["headline"], flaw) or brief
    # cover last rung: best-of-rejected so the edu cover never ships imageless
    cover0 = post["slides"][0]
    if not cover0.get("media") and pool:
        score, best = max(pool, key=lambda t: t[0])
        cover0["media"] = os.path.relpath(best, HERE)
        post["cover_fallback"] = f"best-of-rejected ({score}/10)"
        print(f"EDU COVER: nothing passed QA — shipping the best reject "
              f"({os.path.basename(best)}, score {score}/10)", file=sys.stderr)
    elif not cover0.get("media"):
        post["cover_fallback"] = "no-image"
        print("EDU COVER HAS NO IMAGE — generation returned nothing; "
              "flagged for the daily report", file=sys.stderr)
    print(f"{gen} Seedream image(s) generated", file=sys.stderr)
    scrub_dashes(post)  # owner rule: dashes never reach a published slide
    json.dump(post, open(os.path.join(post_dir, "post.json"), "w"), indent=1)
    subprocess.run([sys.executable, os.path.join(HERE, "render.py"),
                    os.path.join(post_dir, "post.json"), post_dir], check=True)
    json.dump(used + [topic], open(USED, "w"), indent=1)
    print("post ready:", post_dir)
    return post_dir


if __name__ == "__main__":
    main()
