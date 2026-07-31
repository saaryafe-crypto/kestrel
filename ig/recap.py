#!/usr/bin/env python3
"""Daily anchor: "WHAT JUST HAPPENED IN AI IN THE LAST 24 HOURS?"
Usage: python3 recap.py [stories.json]
Fixed cover every day (only the 3-photo collage changes), one payload slide per
story, one builder/inspiration slot whenever a story qualifies, CTA.
Renders into posts/<date>-ai-24h/. Reuses write.py's Claude caller."""
import json, os, re, sys
from datetime import date

from fetch import get
from write import call_claude, article_text, inspiration, principles, scrub_dashes

HERE = os.path.dirname(os.path.abspath(__file__))
N_STORIES = 12  # candidates offered to the writer
N_SLIDES = (5, 9)  # payload slides wanted — 10-slide carousels measurably outperform short ones

COVER = {
    "type": "cover", "hsize": 62,
    "headline": "WHAT JUST HAPPENED IN <em>AI</em> IN THE LAST <em>24 HOURS?</em>",
    "subline": "TRENDING IN AI & TECH",
}


def pick_candidates(stories):
    direct = [s for s in stories if "news.google.com" not in s["link"]]
    return sorted(direct, key=lambda s: (not s.get("image"), -s["score"]))[:N_STORIES]


def build_prompt(cands):
    spec = json.load(open(os.path.join(HERE, "containers.json")))
    lines = []
    for i, s in enumerate(cands):
        excerpt = article_text(s["link"], cap=600)
        lines.append(f"[{i}] {'(has press image) ' if s.get('image') else ''}{s['title']}\n    {excerpt or '(no article text — use title only)'}")
    stories_block = "\n".join(lines)
    return f"""You write Instagram carousels for @yaffeai — an AI-news page in the style of @technology, funneling followers to an AI-consulting business. Today's post is the **daily_recap** anchor: "WHAT JUST HAPPENED IN AI IN THE LAST 24 HOURS?" The cover is fixed (I render it myself) — you write ONLY the payload slides, the cta slide, and the caption.

{principles()}
{inspiration()}
CONTAINER SPEC: {json.dumps(spec['containers']['daily_recap'])}
CAPTION BLOCKS: {json.dumps(spec['caption_blocks'])}

CANDIDATE STORIES (last 24h, ranked):
{stories_block}

Pick the {N_SLIDES[0]}-{N_SLIDES[1]} strongest, most DIFFERENT stories (don't take two angles on the same story). Strongest = what a NORMAL person cares about: touches their money/phone/job/apps, or names everyone knows (Apple, Tesla, ChatGPT...) — an obscure-but-technical story loses to a smaller story the reader can feel. Prefer ones with a press image. Two slots outrank everything when a candidate qualifies:
- BUSINESS-VALUE story (a business used AI and got a result — money saved, hours cut, customers won, a real case study with numbers): MUST be included, written with the $100M Offers rules (section 5 of the principles) — pain first, then the outcome number, then how little effort it took. The reader-owner should think "I want this in MY business"
- BUILDER story (someone built something impressive with AI, Claude Code, tiny team, big numbers): MUST be included — write it so the viewer thinks "wow, I want to do the same" ("WHILE YOU SCROLLED, SOMEONE BUILT..." register)

OUTPUT — a single JSON object: {{"slides": [...], "caption": "..."}}
Each payload slide: {{"type": "content", "idx": <candidate number>, "hsize": <px>, "headline": "...", "body": "..."}}
Last slide: {{"type": "cta", "hsize": 96, "headline": "...", "body": "..."}} — FOMO follow slide ("Daily AI news..." register).

RULES
- LANGUAGE (hard requirement): write for a smart 16-year-old. Everyday words only, short sentences. No industry jargon — say what things DO, not what they're called. If a technical term is unavoidable, explain it in plain words in the same sentence.
- Slide order: strongest story first.
- Headline = the story's wild claim, compressed JUST-formula (6-12 words). <em>...</em> marks the accent words — the minimum set that communicates the claim standalone; every headline needs at least one <em>.
- Each payload slide is a standalone mini-story. The headline withholds exactly one detail that the body's FIRST sentence resolves. Body = 2-3 sentences, EVERY sentence carries a concrete number/name/date in <b>...</b>; frame facts as ranks/records when TRUE (first, biggest, Xth-largest ever) and anchor to famous names the reader knows. No <em> in bodies. Bodies never end with a period. No emojis.
- hsize: short headline (≤5 words) → 105-120; medium → 88-100; long → 76-86.
- Never invent facts not in the titles/excerpts.
- Caption: all five blocks in order, separated by blank lines; hook mentions it's the daily 24-hour AI recap. Sources line names the actual outlets. Exactly five hashtags.
- Caption owner-CTA (mandatory): the LAST line of the trend block, on its own line, invites business owners to DM — pain + tiny ask ("Running a business? DM us "AI" and we'll show you which of these you could use this week"). Vary the wording per day, keep the DM word exactly "AI"

Return ONLY the JSON object, no markdown fences, no commentary."""


def qa(post, n_cands):
    slides, caption, errs = post["slides"], post["caption"], []
    payload = [s for s in slides if s["type"] == "content"]
    if not (N_SLIDES[0] <= len(payload) <= N_SLIDES[1]):
        errs.append(f"{len(payload)} payload slides (want {N_SLIDES[0]}-{N_SLIDES[1]})")
    if slides[-1]["type"] != "cta":
        errs.append("last slide must be cta")
    for i, s in enumerate(slides):
        if "<em>" not in s["headline"]:
            errs.append(f"slide {i+1}: headline has no <em> accent")
        if s["type"] == "content" and not (0 <= s.get("idx", -1) < n_cands):
            errs.append(f"slide {i+1}: bad candidate idx")
    if "Sources:" not in caption:
        errs.append("caption missing Sources line")
    if len(re.findall(r"#\w+", caption)) != 5:
        errs.append("caption must have exactly 5 hashtags")
    return errs


def main(stories_path):
    post_dir = os.path.join(HERE, "posts", f"{date.today()}-ai-24h")
    if os.path.isdir(post_dir) and os.path.exists(os.path.join(post_dir, "slide-1.jpg")):
        raise SystemExit("today's recap already exists: " + post_dir)
    cands = pick_candidates(json.load(open(stories_path)))
    if len(cands) < N_SLIDES[0]:
        raise SystemExit(f"only {len(cands)} direct-link stories — not enough for a recap")
    for s in cands:
        print(f"  cand: {s['title'][:70]}", file=sys.stderr)

    prompt = build_prompt(cands)
    for attempt in range(3):
        post = call_claude(prompt)
        errs = qa(post, len(cands))
        if not errs:
            break
        print(f"QA gate failed (attempt {attempt+1}):\n  " + "\n  ".join(errs),
              file=sys.stderr)
        prompt = (build_prompt(cands)
                  + "\n\nYOUR PREVIOUS ATTEMPT FAILED THESE QA CHECKS — fix every one:\n- "
                  + "\n- ".join(errs))
    else:
        raise SystemExit("QA gate failed after 3 attempts")

    os.makedirs(post_dir, exist_ok=True)
    # download press images for the chosen stories, attach to slides
    for n, s in enumerate(post["slides"]):
        s["media"] = None
        if s["type"] != "content":
            continue
        img = cands[s.pop("idx")].get("image")
        if not img:
            continue
        try:
            path = os.path.join(post_dir, f"media-{n}.jpg")
            open(path, "wb").write(get(img))
            s["media"] = os.path.relpath(path, HERE)
        except Exception as e:
            print(f"  image failed ({e}) — big-type slide", file=sys.stderr)

    cover = dict(COVER)
    cover["media_list"] = [s["media"] for s in post["slides"] if s.get("media")][:3]
    post["slides"].insert(0, cover)
    post.update(handle="@yaffeai", container="daily_recap")

    scrub_dashes(post)  # owner rule: dashes never reach a published slide
    json.dump(post, open(os.path.join(post_dir, "post.json"), "w"), indent=1)
    import subprocess
    subprocess.run([sys.executable, os.path.join(HERE, "render.py"),
                    os.path.join(post_dir, "post.json"), post_dir], check=True)
    print("post ready:", post_dir)
    return post_dir


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "stories.json"))
