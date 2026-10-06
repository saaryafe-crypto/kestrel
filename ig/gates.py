"""Selection gates (owner-approved 2026-10-05). One Claude call clusters the
candidate posts into stories and judges them; every rule after that is
mechanical, in this order:
  1. topic whitelist (AI labs/models, big-tech products, chips, robots and
     self-driving, major launches, big deals/funding/IPOs, AI law/lawsuits)
  2. the 12-word test: a non-tech friend gets the story in <=12 plain words
  3. discovery-only stories need an official or outlet post (two sources),
     or a real news organization's account among the discovery posts
  4. 14-day dedupe (same entity + same event), unless a new hard fact
  5. Musk-world (main subject only): max 1 per page per 7 days (new-system posts), and only if it moves >=3x faster
     than the best other story (the page is NOT about any person)
  6. the story's subject (main company / person in story12) not in 2+ of
     the page's last 10 posts (headline + lead)
  7. max 1 story per company per day
Nothing passes = the slot stays empty (better skip than filler)."""
import json, os, re, sys
from datetime import datetime, timedelta

import llm
from pages import PAGES

HERE = os.path.dirname(os.path.abspath(__file__))
POLITICS = re.compile(r"\b(trump|biden|election|senat|congress|democrat|republican|"
                      r"immigra|deport|migrant|shooting|war|iran|gaza|ukraine|russia|"
                      r"usaid|regime)\b", re.I)
TOPICS = ["ai_lab_or_model", "big_tech_product", "chips", "robots_or_self_driving",
          "major_launch", "big_deal_funding_ipo", "ai_law_or_lawsuit", "off"]


def history(lang, days=14, extra_dirs=()):
    """The page's own posts, newest last: [{date, text, dir}] from the
    committed post dirs (cards + reels, old and new formats)."""
    root = os.path.join(HERE, PAGES[lang]["posts"])
    since = str((datetime.now() - timedelta(days=days)).date())
    dirs = [os.path.join(root, d) for d in os.listdir(root)] if os.path.isdir(root) else []
    dirs += list(extra_dirs)
    out = []
    for d in dirs:
        name = os.path.basename(d.rstrip("/"))
        if name[:10] < since or not os.path.isdir(d):
            continue
        text, when, il, musk = "", name[:10], False, False
        pj = os.path.join(d, "post.json")
        if os.path.exists(pj):
            try:
                p = json.load(open(pj))
                text = p.get("headline") or ""
                when = p.get("slot_time") or when
                il = bool(p.get("israeli"))
                # Musk cap counts only NEW-system posts (post.json "kind",
                # since 2026-10-05) whose story the editor marked musk_world;
                # old posts and side mentions never block (owner 2026-10-06)
                musk = bool(p.get("kind") and p.get("musk") and when >= "2026-10-05")
            except Exception:
                pass
        for f in ("caption.txt",):
            if os.path.exists(os.path.join(d, f)):
                text += "\n" + open(os.path.join(d, f)).read()[:600]
        if os.path.exists(os.path.join(d, "reel.json")):
            try:
                r = json.load(open(os.path.join(d, "reel.json")))
                text += "\n" + (r.get("title") or "") + "\n" + (r.get("caption") or "")[:600]
            except Exception:
                pass
        if text.strip():
            out.append({"date": when, "text": text.strip(), "dir": name, "israeli": il, "musk": musk})
    return sorted(out, key=lambda h: (h["date"], h["dir"]))


JUDGE_SCHEMA_HINT = """Return ONLY a JSON list, one object per ON-TOPIC STORY:
[{"ids": ["<every candidate id about this same story>"],
  "story12": "<the story in 12 plain words or fewer that a friend who does not follow tech instantly gets, or null if that needs jargon>",
  "topic": "<one of: TOPICS>",
  "entities": [{"name": "<person or company named in the story, in ENGLISH spelling>", "aliases": ["<other spellings, including the Hebrew one>"]}],
  "company": "<the ONE main company, or null>",
  "musk_world": <true only if the story's MAIN subject is Musk, Tesla, SpaceX, xAI, Grok, Starlink or Neuralink; false when one is only a side mention (another company's satellite rides a SpaceX rocket, an airline uses Starlink Wi-Fi)>,
  "dupe_of": <number of the RECENT POSTS line this repeats (same entity AND same event), or null>,
  "new_hard_fact": <true only if dupe_of is set AND this adds a new number, date or verdict>,
  "newsroom": <true only if one of the [D] posts on this story is from a real news organization's own account (a TV station, newspaper, wire service). Employees, fans, influencers and aggregators do NOT count>,
  "israeli_angle": <true if an Israeli company, founder, exit, TASE, IDF tech or direct Israeli consumer impact>,
  "video_is_news": <true only if a candidate's VIDEO itself shows the news or a real wow moment (product demo, robot or self-driving footage, a real event); false for talking heads, keynotes, slides, memes, B-roll>
}]"""


def judge(cands, lang, recent, reels=False):
    lines = []
    for c in cands:
        tag = c.get("tag", "")
        lines.append(f"[{c['id']}] {tag} {c['text'][:400]}")
    # only ask for the fields this lane needs: shorter output, faster call
    drop = set()
    if not reels:
        drop.add('"video_is_news"')
    if lang != "he":
        drop.add('"israeli_angle"')
    if not any(c.get("lane") == "discovery" for c in cands):
        drop.add('"newsroom"')
    hint = "\n".join(l for l in JUDGE_SCHEMA_HINT.replace("TOPICS", ", ".join(TOPICS)).split("\n")
                     if not any(l.strip().startswith(d) for d in drop))
    rec = "\n".join(f"{i + 1}. {h['date']} {h['text'][:160]}".replace("\n", " ")
                    for i, h in enumerate(recent))
    prompt = f"""You are the news editor of {PAGES[lang]['handle']}, an Instagram page of viral AI and tech NEWS for ordinary people.

CANDIDATES (id, source tag, text). Tags: [O] official company/CEO account, [N] news outlet or reporter, [D] discovery (random account), [V] has video, [IL xN] Hebrew Israeli press, N outlets.
{chr(10).join(lines)}

RECENT POSTS on this page (last 14 days):
{rec or "(none)"}

Group the candidates into stories (several candidates can be one story). SKIP clearly off-topic stories (politics, war, crime, sports, memes) completely. List the best 12 to 15 stories, best first, when the candidates allow: include borderline tech stories too with honest fields (the mechanical gates after you decide; a short list leaves the slot empty). Judge each listed story honestly:
- topic "off" for politics, war, crime and police cases (even when AI was the tool, unless a famous company is on trial), local incidents (a first-of-its-kind law or rule is NOT local), macro markets, culture-war, memes, jokes, random people's opinions, analysis or opinion columns ("X is nothing like Y", "why X matters"), vague teasers, personal musings, sports, nature, generic wow clips. A CEO's one-line joke or musing is "off". But a famous tech leader's notable statement in a real interview, hearing or announcement IS news (topic ai_lab_or_model or ai_law_or_lawsuit).
- story12 must be a real news event (something happened or was announced), told in plain words AND accurately: never swap the real product for a more famous one (a coding-tool or API change is not "ChatGPT"). If it only matters to developers, or needs words like "tokens", "inference", "Codex", "API", "SI", "benchmarks", return null.
- dupe_of: compare with RECENT POSTS. Same entity and same event = dupe, even from another angle.
{hint}
Keep it compact: no prose, no code fences, short strings."""
    # the editor call must finish in ~8 min (a 140-item Hebrew batch hung 18+
    # min on 2026-10-05); on timeout retry once with the top half
    try:
        out = llm.call(prompt, max_s=480, tries=1)
    except Exception as e:
        if len(cands) <= 20:
            raise
        print(f"editor call failed ({e}), retrying with the top {len(cands) // 2}", file=sys.stderr)
        return judge(cands[:len(cands) // 2], lang, recent, reels)
    return out if isinstance(out, list) else out.get("stories", [])


def mentions(text, ent):
    names = [ent.get("name") or ""] + list(ent.get("aliases") or [])
    return any(n and len(n) > 2 and re.search(r"(?<!\w)" + re.escape(n) + r"(?!\w)", text, re.I)
               for n in names)


def apply(stories, cands, lang, recent, today, reels=False, log=print):
    """Mechanical gates over judged stories. Returns passing stories, best
    first, each with .score and .members."""
    by_id = {c["id"]: c for c in cands}
    last10 = recent[-10:]
    week = str((datetime.fromisoformat(today) - timedelta(days=7)).date())
    musk_week = any(h["date"][:10] >= week and h.get("musk") for h in recent)
    todays = [h for h in recent if h["date"][:10] == today]
    for s in stories:
        s["members"] = [by_id[i] for i in s.get("ids", []) if i in by_id]
        s["score"] = sum(m.get("score", 0) for m in s["members"])
    best_other = max([s["score"] for s in stories if not s.get("musk_world")] or [0])
    ok = []
    for s in sorted(stories, key=lambda s: -s["score"]):
        why = None
        lanes = {m.get("lane") for m in s["members"]}
        if not s["members"]:
            why = "no members"
        elif s.get("topic") not in TOPICS or s.get("topic") == "off":
            why = f"off-topic ({s.get('topic')})"
        elif not s.get("story12") or len(s["story12"].split()) > 12:
            why = "fails the 12-word friend test"
        elif lanes <= {"discovery"} and not s.get("newsroom"):
            why = "discovery only, no official/outlet confirmation"
        elif s.get("dupe_of") and not s.get("new_hard_fact"):
            why = f"dupe of recent post {s['dupe_of']}"
        elif s.get("musk_world") and musk_week:
            why = "Musk-world already posted this week"
        elif s.get("musk_world") and s["score"] < 3 * best_other:
            why = "Musk-world but not 3x bigger than the best other story"
        elif reels and not s.get("video_is_news"):
            why = "video is not the news"
        else:
            # cap only the story's SUBJECT (its main company or a name in
            # story12), counted in past headlines/leads: the editor also lists
            # side entities, which killed an Anthropic story as "Nvidia already
            # in 2 of the last 10" (2026-10-06)
            co = s.get("company") or ""
            subj = [e for e in s.get("entities") or []
                    if (co and (e.get("name") or "").lower() == co.lower()) or mentions(s.get("story12") or "", e)]
            for e in subj:
                n = sum(mentions(h["text"][:300], e) for h in last10)
                if n >= 2:
                    why = f"{e.get('name')} already in {n} of the last 10 posts"
                    break
            co = s.get("company")
            if not why and co and any(mentions(h["text"], {"name": co, "aliases": next(
                    (e.get("aliases") for e in s.get("entities") or [] if e.get("name") == co), [])})
                    for h in todays):
                why = f"{co} already posted today"
        log(f"  {'PASS' if not why else 'kill'} {s['score']:>7} {s.get('story12') or s['members'][0]['text'][:60] if s['members'] else s.get('ids')}"
            + (f"  <- {why}" if why else ""))
        if not why:
            ok.append(s)
    return ok
