"""Selection gates (owner-approved 2026-10-05). One Claude call clusters the
candidate posts into stories and judges them; every rule after that is
mechanical, in this order:
  1. topic whitelist (AI labs/models, big-tech products, chips, robots and
     self-driving, major launches, big deals/funding/IPOs, AI law/lawsuits)
  2. the 12-word test: a non-tech friend gets the story in <=12 plain words
  3. discovery-only stories need an official or outlet post (two sources),
     or a real news organization's account among the discovery posts
  4. dedupe (same entity + same event) vs the page's posts: 14 days, or 30
     days and STRICT (no new-hard-fact exception) for EN, whose stories now
     come from a 14-day pool; X posts already used by any old or new post
     never come back (used_ids, applied before the editor)
  5. Musk-world (main subject only): max 1 per page per 7 days (new-system posts), and only if it moves >=3x faster
     than the best other story (the page is NOT about any person)
  6. the story's subject (main company / person in story12) not in 2+ of
     the page's last 10 posts (headline + lead)
  7. max 1 story per company per day
Nothing passes = the slot stays empty (better skip than filler).

Ranking (owner 2026-10-06, "viral first"): the editor scores each story's
shareability 1-10 (would normal people talk about it and share it?); the
story's engagement is multiplied by (share/5)^2, so a share-9 story needs
1/3 the likes of a share-5 one and a share-2 tech release needs 6x."""
import json, os, re, sys
from datetime import datetime, timedelta

import llm
from pages import PAGES

HERE = os.path.dirname(os.path.abspath(__file__))
POLITICS = re.compile(r"\b(trump|biden|newsom|white house|election|senat|congress|democrat|republican|"
                      r"immigra|deport|migrant|shooting|war|iran|gaza|ukraine|russia|"
                      r"usaid|regime)\b", re.I)
# politicians' own accounts: their AI posts are politics (Newsom's "AI stays AI"
# executive order troll reached the 2026-10-06 preview); lowercase handles
POLITICIANS = {"gavinnewsom", "realdonaldtrump", "potus", "whitehouse", "jdvance", "vp",
               "speakerjohnson", "senschumer", "aoc", "berniesanders", "kamalaharris"}
TOPICS = ["ai_lab_or_model", "big_tech_product", "chips", "robots_or_self_driving",
          "major_launch", "big_deal_funding_ipo", "ai_law_or_lawsuit", "ai_and_people", "off"]
X_ID = re.compile(r"(?:x|twitter)\.com/\w+/status/(\d+)|-reel-(\d{15,})")


def used_ids(lang):
    """Every X post id any post on this page ever used (old system: reel dir
    names, post.json/reel.json links; new system: post.json sources/video)."""
    root = os.path.join(HERE, PAGES[lang]["posts"])
    ids = set()
    for d in os.listdir(root) if os.path.isdir(root) else []:
        ids.update(x for m in X_ID.finditer(d) for x in m.groups() if x)
        for f in ("post.json", "reel.json"):
            p = os.path.join(root, d, f)
            if os.path.exists(p):
                ids.update(x for m in X_ID.finditer(open(p, errors="ignore").read())
                           for x in m.groups() if x)
    return ids


# real newsrooms for the Google News confirmation of discovery-only stories
MAJOR = {"the new york times", "reuters", "ap news", "associated press", "bloomberg", "bloomberg.com",
         "cnbc", "the guardian", "bbc", "bbc.com", "the wall street journal", "financial times",
         "the washington post", "los angeles times", "cnn", "nbc news", "cbs news", "abc news",
         "fox news", "fox business", "usa today", "new york post", "politico", "axios", "the verge",
         "techcrunch", "wired", "engadget", "ars technica", "fortune", "business insider", "forbes",
         "the information", "futurism", "fast company", "gizmodo", "mashable", "techradar",
         "tom's guide", "pcmag", "zdnet", "cnet", "the independent", "sky news", "time", "newsweek",
         "variety", "the hollywood reporter", "rolling stone", "people.com", "404 media", "semafor",
         "yahoo finance", "yahoo news", "yahoo tech", "marketwatch", "the atlantic", "npr",
         "global news", "daily mail", "the telegraph", "9to5mac", "9to5google", "macrumors"}
GN_UA = {"User-Agent": "Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/120 Safari/537.36"}


def gnews_confirm(query, days=14):
    """Articles from MAJOR newsrooms on Google News (free, no X reads) whose
    title shares 2+ (long queries: a third) of the query's content words. Confirms a
    discovery-only story the way an outlet post on X would (2026-10-06: the
    14-day pool has many viral stories the X outlet lane never caught)."""
    import html as h, urllib.parse, urllib.request
    words = (query or "").split()
    out = []
    # the editor's query, then its first 4 words (long queries often match nothing)
    for q in dict.fromkeys([" ".join(words), " ".join(words[:4])]):
        if not q or out:
            continue
        try:
            url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
                {"q": f"{q} when:{days}d", "hl": "en-US", "gl": "US", "ceid": "US:en"})
            x = urllib.request.urlopen(urllib.request.Request(url, headers=GN_UA), timeout=20).read().decode()
        except Exception as e:
            print(f"  google news check failed: {e}", file=sys.stderr)
            continue
        want = _stems(q)
        for it in re.findall(r"<item>(.*?)</item>", x, re.S)[:20]:
            src = re.search(r"<source[^>]*>(.*?)</source>", it)
            title = re.search(r"<title>(.*?)</title>", it, re.S)
            link = re.search(r"<link>(.*?)</link>", it)
            if not (src and title and link):
                continue
            outlet, title = h.unescape(src.group(1)).strip(), h.unescape(title.group(1))
            if outlet.lower().split(" - ")[0].strip() not in MAJOR or any(o["outlet"] == outlet for o in out):
                continue
            # the title must be about it: 2+ shared content words, 3+ for long queries
            if len(want & _stems(title)) < min(max(2, -(-len(want) // 3)), len(want)):
                continue
            out.append({"id": "gn:" + link.group(1)[-24:], "lane": "outlets", "outlet": outlet,
                        "link": link.group(1), "text": title, "tag": f"[N {outlet}]", "score": 0})
    return out


VERSIONED = re.compile(r"\b[a-z]?[A-Z][\w-]*(?: [A-Z][\w-]*)? v?\d+(?:\.\d+)?(?: [A-Z][a-z]+)?\b")


def versioned_repeat(s, recent):
    """A versioned product name ("Gemini 4 Argon", "Mistral Large 4", "Claude
    5.5") already in a past post = the same launch. The editor's dupe_of missed
    "Gemini 4 Argon" on 2026-10-06 (posted 10-02 from another angle)."""
    names = set(VERSIONED.findall(s.get("story12") or ""))
    names |= {e.get("name") for e in s.get("entities") or [] if VERSIONED.fullmatch(e.get("name") or "")}
    for n in names:
        if any(re.search(r"(?<!\w)" + re.escape(n) + r"(?!\w)", h["text"], re.I) for h in recent):
            return n
    return None


def share_mult(s):
    try:
        share = min(max(float(s.get("share") or 5), 1), 10)
    except (TypeError, ValueError):
        share = 5
    return (share / 5) ** 2


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
  "share": <1-10: how much ORDINARY people would talk about and share this. 8-10 = shocking capability anyone gets, big money, jobs lost or won, a famous person or brand everyone knows, drama or a fight, funny or weird, "this affects my phone/job/kids". 4-6 = solid tech news with a clear everyday angle. 1-3 = model releases, benchmarks, parameters, developer tools, policy compliance, partnerships, unless truly huge (a new ChatGPT everyone will use is 7+)>,
  "why": "<max 12 words: why normal people would share it>",
  "search": "<3-6 keywords a news search would find this story with, e.g. 'Pope AI art human soul'>",
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
    rec = "\n".join(f"{i + 1}. {h['date']} {h['text'][:130]}".replace("\n", " ")
                    for i, h in enumerate(recent))
    prompt = f"""You are the news editor of {PAGES[lang]['handle']}, an Instagram page of viral AI and tech NEWS for ordinary people.

CANDIDATES (id, source tag, text). Tags: [O] official company/CEO account, [N] news outlet or reporter, [D] discovery (random account), [V] has video, [IL xN] Hebrew Israeli press, N outlets.
{chr(10).join(lines)}

RECENT POSTS on this page (last 14 days):
{rec or "(none)"}

Group the candidates into stories (several candidates can be one story). SKIP clearly off-topic stories (politics, war, crime, sports, memes) completely. List the best 12 to 15 stories, best first, when the candidates allow: include borderline tech stories too with honest fields (the mechanical gates after you decide; a short list leaves the slot empty). Judge each listed story honestly:
- topic "off" for politics, war, crime and police cases (even when AI was the tool, unless a famous company is on trial), local incidents (a first-of-its-kind law or rule is NOT local), macro markets, culture-war, memes, jokes, random people's opinions, analysis or opinion columns ("X is nothing like Y", "why X matters"), vague teasers, personal musings, sports, nature, generic wow clips. A CEO's one-line joke or musing is "off". But a famous tech leader's notable statement in a real interview, hearing or announcement IS news (topic ai_lab_or_model or ai_law_or_lawsuit).
- story12 must be a real news event (something happened or was announced), told in plain words AND accurately: never swap the real product for a more famous one (a coding-tool or API change is not "ChatGPT"). If it only matters to developers, or needs words like "tokens", "inference", "Codex", "API", "SI", "benchmarks", return null.
- topic "ai_and_people" = AI in everyday life: jobs and layoffs, money and scams, celebrities or famous brands using or refusing AI, AI in schools/dating/health, weird or funny AI moments that really happened (reported by an outlet or the company). These are often the MOST shareable stories: list them.
- Candidates may be up to 14 days old (age and engagement are in the tag). Prefer what normal people share over what engineers care about.
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


def apply(stories, cands, lang, recent, today, reels=False, log=print, strict=False):
    """Mechanical gates over judged stories. Returns passing stories, best
    first, each with .score and .members."""
    by_id = {c["id"]: c for c in cands}
    last10 = recent[-10:]
    week = str((datetime.fromisoformat(today) - timedelta(days=7)).date())
    musk_week = any(h["date"][:10] >= week and h.get("musk") for h in recent)
    todays = [h for h in recent if h["date"][:10] == today]
    for s in stories:
        s["members"] = [by_id[i] for i in s.get("ids", []) if i in by_id]
        s["score"] = round(sum(m.get("score", 0) for m in s["members"]) * share_mult(s))
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
        elif lanes <= {"discovery"} and not s.get("newsroom") and not (
                gn := gnews_confirm(s.get("search") or "")):
            why = f"discovery only, no official/outlet confirmation (news search: {s.get('search')!r})"
        elif s.get("dupe_of") and (strict or not s.get("new_hard_fact")):
            why = f"dupe of recent post {s['dupe_of']}"
        elif strict and (v := versioned_repeat(s, recent)):
            why = f"'{v}' was already posted (strict dedupe)"
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
        log(f"  {'PASS' if not why else 'kill'} {s['score']:>7} s{s.get('share', '?')} {s.get('story12') or s['members'][0]['text'][:60] if s['members'] else s.get('ids')}"
            + (f"  <- {why}" if why else ""))
        if not why:
            if lanes <= {"discovery"} and not s.get("newsroom") and gn:
                s["members"] = s["members"] + gn[:3]  # confirmed on Google News
                s["gnews"] = [g["outlet"] for g in gn[:3]]
            ok.append(s)
    return ok


# ---------- reel hook (owner 2026-10-06) ----------
# The on-screen reel hook describes the visual moment the viewer is about to
# see, curious/shocking, max ~8 words. Company, country, place and source go
# in the caption only; no "AI" jargon on screen.
HOOK_MAX_WORDS = 9  # prompt asks for 8; one word of slack
PLACES_EN = ("israel|usa|america|united states|china|japan|korea|taiwan|india|russia|ukraine|"
             "germany|france|britain|uk|england|europe|eu|italy|spain|finland|sweden|norway|"
             "denmark|netherlands|switzerland|canada|mexico|brazil|australia|singapore|dubai|uae|"
             "saudi|iran|turkey|egypt|africa|asia|silicon valley|california|texas|new york|"
             "san francisco|london|paris|berlin|tokyo|beijing|shanghai|shenzhen|seoul|"
             "tel aviv|jerusalem|haifa|helsinki|moscow|washington")
PLACES_HE = ("ישראל|ארה\"ב|ארצות הברית|אמריקה|סין|יפן|קוריאה|טייוואן|הודו|רוסיה|אוקראינה|"
             "גרמניה|צרפת|בריטניה|אנגליה|אירופה|איטליה|ספרד|פינלנד|שוודיה|נורבגיה|דנמרק|הולנד|"
             "שווייץ|קנדה|מקסיקו|ברזיל|אוסטרליה|סינגפור|דובאי|אמירויות|סעודיה|איראן|טורקיה|מצרים|"
             "אפריקה|אסיה|עמק הסיליקון|קליפורניה|טקסס|ניו יורק|סן פרנסיסקו|לונדון|פריז|ברלין|"
             "טוקיו|בייג'ינג|שנגחאי|סיאול|תל אביב|ירושלים|חיפה|הלסינקי|מוסקבה|וושינגטון")
# plain "AI" is allowed when it IS the twist ("No engineer touched this");
# jargon (model names are caught as names below) is not (owner 2026-10-06)
JARGON = re.compile(r"\bAGI\b|\bLLMs?\b|\bGPT|\bbenchmark|\bparameters?\b|\btokens?\b|\bprompt engineering|"
                    r"מודל שפה|בנצ'מרק|פרמטרים", re.I)


STOP = set("with into from that this their them they what when where which while about after "
           "before over under onto just very then than have been were will your into "
           "real says said people today viral".split())


def _stems(text):
    """Content-word stems: Latin words >=4 letters (minus plural/verb endings),
    Hebrew words >=3 letters with one leading prefix letter dropped."""
    out = set()
    for w in re.findall(r"[\w']+", text.lower()):
        if re.match(r"^[a-z']+$", w):
            if len(w) >= 4 and w not in STOP:
                out.add(re.sub(r"(ing|ed|es|s)$", "", w)[:6])
        elif re.search("[\u0590-\u05ff]", w) and len(w) >= 3:
            out.add(w[1:] if w[0] in "בלמהושכ" and len(w) >= 4 else w)
    return out


def hook_errors(hook, story, payoff=""):
    """Reasons a reel hook breaks the owner rules ([] = ok)."""
    errs = []
    if not payoff.strip():
        errs.append('return "payoff" (the climax the hook hides)')
    else:
        hs = _stems(hook)
        # hook word matches a payoff word (Hebrew: either contains the other, for prefixes)
        leak = [p for p in _stems(payoff) if any(p == h or (len(p) >= 3 and len(h) >= 3 and
                                                             re.search("[\u0590-\u05ff]", p) and (p in h or h in p))
                                                 for h in hs)]
        if leak:
            errs.append(f"reel hook reveals the payoff ({leak}); build anticipation, never say what happens")
    words = [w for w in re.split(r"\s+", hook.strip()) if w]
    if len(words) > HOOK_MAX_WORDS:
        errs.append(f"reel hook max 8 words (has {len(words)})")
    names = [story.get("company") or ""]
    for e in story.get("entities") or []:
        names += [e.get("name") or "", *(e.get("aliases") or [])]
    # "Figure AI" also catches a bare "Figure"; drop suffixes like AI / Inc / Labs
    names += [re.sub(r"\s+(AI|Inc\.?|Labs?|Robotics|Technologies)$", "", n, flags=re.I) for n in names]
    for n in {n.strip() for n in names if len(n.strip()) >= 3}:
        latin = re.match(r"^[\x00-\x7f]+$", n)
        # Hebrew takes one-letter prefixes (ב/ל/מ/ה/ו/ש/כ), so no word boundary there
        pat = rf"(?<![\w]){re.escape(n)}(?![\w])" if latin else re.escape(n)
        if re.search(pat, hook, re.I):
            errs.append(f"reel hook names '{n}' (company/person names go in the caption only)")
    # brand/product names the entity list missed (Claude, Optimus, Gemini):
    # a capitalized word after the first one in English, any Latin word in Hebrew
    if re.search("[\u0590-\u05ff]", hook):
        latin = [w for w in re.findall(r"\b[A-Za-z][\w.'-]*", hook) if w != "AI"]
    else:
        # the first word of each sentence may be capitalized ("...by hand. Watch closely")
        latin = [w for sent in re.split(r"[.!?:]\s+", hook)
                 for w in re.findall(r"\b[A-Za-z][\w'-]*", sent)[1:]
                 if w[0].isupper() and w not in ("I", "AI")]
    if latin:
        errs.append(f"reel hook has name-like words {latin} (names go in the caption only)")
    place = (re.search(rf"\b({PLACES_EN})\b", hook, re.I) or re.search(rf"({PLACES_HE})", hook))
    if place:
        errs.append(f"reel hook names a place '{place.group(0)}' (places go in the caption only)")
    if JARGON.search(hook):
        errs.append(f"reel hook uses jargon '{JARGON.search(hook).group(0)}' (no AI jargon on screen)")
    return errs
