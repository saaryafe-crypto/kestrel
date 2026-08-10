#!/usr/bin/env python3
"""Hebrew arm (@ainews.israel): translates a FINISHED English post into
natural Hebrew and re-renders it RTL. Runs after the English publish — the
input already survived the judge, QA and the editor, so this stage only
changes the language.

TOKEN DIET (owner order Aug 8: "to the hebrew one just translate" — the IG
system ate the whole Claude plan): the Aug 2 born-in-Hebrew multi-agent flow
(fact sheet -> native writer -> cover tournament -> polish editor, 4-6 calls
per post) is replaced by ONE translation call. The single prompt carries the
whole Hebrew craft: spoken-Israeli register, the anti-calque rule, the owner
digits rule (counts one-to-ten as Hebrew words, LTR-island cap on the
cover). Deterministic scrub + code-only qa() still gate the output; one
retry call max on QA failure.

Usage: python3 he.py [posts/<dir>]     (default: newest un-localized post)
Output: posts-he/<same name>/ with slide-*.jpg + caption.txt + post-he.json
Prints "post ready: posts-he/<name>" for the workflow, same contract as
write.py."""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import write  # call_claude, no_dashes — the shared craft helpers

HANDLE = "@ainews.israel"
HEB = re.compile(r"[\u0590-\u05FF]")

HE_SCHEMA = {"type": "object", "properties": {
    "slides": {"type": "array", "items": {"type": "object", "properties": {
        "headline": {"type": "string"},
        "body": {"type": "string"},
        "kicker": {"type": "string"},
        "subline": {"type": "string"}}}},
    "caption": {"type": "string"},
    "pinned_comment": {"type": "string"}},
    "required": ["slides", "caption"]}


def doctrine():
    p = os.path.join(HERE, "inspiration", "hebrew.md")
    return open(p).read() if os.path.exists(p) else ""


def skill_refs():
    """hebrew-editorial skill knowledge base (owner blueprint Aug 10):
    terminology glossary + approved/rejected pairs ride into every Hebrew
    call. hebrew.md stays the master style guide (doctrine())."""
    base = os.path.join(HERE, "skills", "hebrew-editorial", "references")
    parts = []
    for f in ("terminology.md", "examples.md"):
        p = os.path.join(base, f)
        if os.path.exists(p):
            parts.append(open(p).read())
    return "\n\n".join(parts)


def backlog():
    """Every English post dir with rendered slides and no Hebrew twin, newest
    first. Reel dirs are reel_he.py territory. A LIST, not one dir (Jul 31
    audit: trying only the newest meant one failed localization killed the
    slot and the backlog never drained — 29 of 37 EN posts had no Hebrew
    twin). The slot runner walks the list until one post succeeds."""
    dirs = []
    root = os.path.join(HERE, "posts")
    for d in os.listdir(root):
        full = os.path.join(root, d)
        if not os.path.exists(os.path.join(full, "post.json")):
            continue
        if os.path.exists(os.path.join(full, "reel.json")):
            continue
        if not os.path.exists(os.path.join(full, "slide-1.jpg")):
            continue
        if os.path.exists(os.path.join(HERE, "posts-he", d, "slide-1.jpg")):
            continue
        # RETIRED marker (Aug 3, run 191d24e post-mortem): the billionaire
        # post was rebuilt as -v2 after its cover failed, but the OLD folder
        # stayed here and this picker localized it — @ainews.israel got the
        # rejected waxy-Musk cover AND the same story twice in one day. A
        # rebuild must now drop a "retired" file in the superseded folder.
        if os.path.exists(os.path.join(full, "retired")):
            continue
        dirs.append(full)
    # newest first BY NAME (dirs start with the date) — mtime is useless on a
    # fresh CI clone, where every file gets checkout time
    return sorted(dirs, key=os.path.basename, reverse=True)


def build_prompt(post):
    """The ONE translation prompt (token diet Aug 8). In Hebrew — the polish
    era proved a Hebrew-language prompt pushes the model into native mode —
    and it shows the English post but bans word-for-word calques."""
    src = {"slides": [{k: s.get(k) for k in ("type", "headline", "body", "kicker")
                       if s.get(k)} for s in post["slides"]],
           "caption": post["caption"],
           "pinned_comment": post.get("pinned_comment")}
    return f"""אתה המתרגם והעורך של @ainews.israel, עמוד חדשות AI באינסטגרם לקהל ישראלי צעיר.

לפניך פוסט באנגלית שכבר פורסם. תרגם אותו לעברית טבעית: לא תרגום מילולי — ישראלי שקורא את התוצאה לא אמור לנחש שהמקור באנגלית. כל מספר, שם, מחיר וציטוט חייבים לשרוד במדויק. ניסוח שנשמע כמו אנגלית במילים עבריות ("עשה היסטוריה", "לא קיבל את ההודעה") פסול — כתוב איך שישראלי באמת אומר את זה.

הסגנון: עברית מדוברת של ישראלי חכם בן 16, כותרות בצורות של ynet ו-N12 אבל פשוטות יותר. אפס עברית של עיתון. המבחן הקשיח (הבעלים, 10.8): בן 16 קורא בלי להאט. אם הוא מאט, לכתוב פשוט יותר.

{doctrine()}

{skill_refs()}

חוקי מבנה (קשיחים):
- בדיוק {len(post["slides"])} שקופיות, באותו סדר, ובכל שקופית רק השדות שקיימים בה במקור.
- <em>...</em> נשאר סביב קבוצת המילים המקבילה בעברית (חובה בכותרת השער). <b>...</b> סביב אותן עובדות מפתח בכל body.
- מספרים: אחת עד עשר תמיד במילים, בהתאמת מין נכונה לשם העצם (שש בעיות, חמישה כלים). כמה שפחות ספרות ומילים באנגלית; בכותרת השער מקסימום שני איי LTR ועדיף אחד. שמות מותגים נשארים באנגלית.
- בלי מקף מכל סוג בטקסט המפורסם.
- caption: שורה ראשונה עם השורה התחתונה של הסיפור, אחר כך הסיפור בקצרה, שורת המקורות מהמקור, וקריאה לעקוב אחרי {HANDLE}. בלי האשטגים — הם מתווספים אוטומטית.
- pinned_comment: תרגם אם קיים.

הפוסט באנגלית:
{json.dumps(src, ensure_ascii=False, indent=1)}

החזר JSON בלבד: {{"slides": [{{"headline": "...", "body": "...", "kicker": "..."}}], "caption": "...", "pinned_comment": "..."}} — בדיוק {len(post["slides"])} שקופיות, באותו הסדר."""


def merge(post, r):
    """Model text onto the English post skeleton — media/layout untouched."""
    out = json.loads(json.dumps(post))  # deep copy
    out["handle"] = HANDLE
    for s, h in zip(out["slides"], r["slides"]):
        for k in ("headline", "body", "kicker"):
            if s.get(k) and h.get(k):
                s[k] = h[k]
    out["caption"] = r["caption"]
    if r.get("pinned_comment"):
        out["pinned_comment"] = r["pinned_comment"]
    return out


def scrub(out, en_caption):
    """Deterministic gates — never trust the prompt alone (English-arm rule)."""
    # dash ban incl. Hebrew maqaf (compound maqaf -> plain hyphen, allowed)
    def clean(t):
        if not isinstance(t, str):
            return t
        # the EN handle must never survive anywhere (run 30623475851: it leaked
        # into a slide, and the old caption-only replace let qa() hard-fail)
        t = t.replace("@yaffeai", HANDLE)
        t = write.no_dashes(t.replace("\u05be", "-"))
        # owner rule Jul 29: "$X מיליארד" must also say "דולר" — some
        # Israelis don't parse the $ symbol at scroll speed
        t = re.sub(r"(\$[\d.]+\s*מיליארד)(?!\s*דולר)", r"\1 דולר", t)
        t = re.sub(r"([\d.]+\s*מיליארד)(?!\s*דולר)", r"\1 דולר", t)
        return t
    for s in out["slides"]:
        for k in ("headline", "body", "kicker", "subline"):
            if s.get(k):
                s[k] = clean(s[k])
    cap = clean(out["caption"])
    if out.get("pinned_comment"):
        out["pinned_comment"] = clean(out["pinned_comment"].replace("#", ""))
    # hashtags: whatever the model wrote, the published tags ARE the English
    # ones (owner: hashtags stay in English)
    en_tags = re.findall(r"#\w+", en_caption)
    cap = re.sub(r"#[\w\u0590-\u05FF]+", "", cap).rstrip()
    if en_tags:
        cap += "\n\n" + " ".join(en_tags)
    out["caption"] = cap
    return out


# a "count digit" is 1-10 standing alone before a Hebrew word ("6 בעיות").
# Exempt: $ amounts, percentages, decimals, dates (7/10), Latin product names
# (GPT-5, Gemini 3 escapes via the Hebrew-follower requirement when suffixed)
COUNT_DIGIT = re.compile(r"(?<![A-Za-z0-9$#.,:/%])(?<![A-Za-z]-)"
                         r"(10|[1-9])(?=\s+[\u0590-\u05FF])")
LTR_RUN = re.compile(r"[A-Za-z0-9$%][A-Za-z0-9$%.,'&/+-]*")


def qa(out):
    errs = []
    if not HEB.search(out["slides"][0].get("headline", "")):
        errs.append("cover headline is not Hebrew")
    # owner hard rule Aug 2: as few digits as possible — counts one-to-ten
    # are Hebrew words; every digit/Latin run is an LTR island that breaks
    # the RTL reading flow, so the cover headline gets an island cap
    strip = lambda t: re.sub(r"</?(em|b)>", "", t or "")
    bad = []
    for i, s in enumerate(out["slides"]):
        for k in ("headline", "body"):
            t = re.sub(r"^\s*\d{1,2}\)", "", strip(s.get(k)))  # list markers OK
            bad += [f"שקופית {i+1}: '{m.group(1)}'"
                    for m in COUNT_DIGIT.finditer(t)]
    if bad:
        errs.append("מספרים מאחת עד עשר נכתבים במילים בהתאמת מין (שש בעיות, "
                    "חמישה כלים), לא בספרות: " + "; ".join(bad[:5]))
    islands = LTR_RUN.findall(strip(out["slides"][0].get("headline", "")))
    if len(islands) > 2:
        errs.append(f"כותרת השער מכילה {len(islands)} איי LTR "
                    f"({', '.join(islands)}), המקסימום 2 ועדיף אחד: העבר "
                    "מספרים או שמות לעברית או ל-body")
    if not HEB.search(out["caption"][:200]):
        errs.append("caption payoff line is not Hebrew")
    heb_fields = tot = 0
    for s in out["slides"]:
        for k in ("headline", "body"):
            if s.get(k):
                tot += 1
                heb_fields += bool(HEB.search(s[k]))
    if tot and heb_fields / tot < 0.7:
        errs.append(f"only {heb_fields}/{tot} text fields are Hebrew")
    if HANDLE not in out["caption"]:
        errs.append(f"caption missing follow handle {HANDLE}")
    if "@yaffeai" in json.dumps(out, ensure_ascii=False):
        errs.append("@yaffeai leaked into the Hebrew post")
    return errs


REL_SCHEMA = {"type": "object", "properties": {
    "relevant": {"type": "boolean"}, "why": {"type": "string"}},
    "required": ["relevant", "why"]}


def israel_relevant(post):
    """Owner gate (Aug 10): "if the post is relevant for israel so write it
    in hebrew (big news, ai, openai, musk, anthropic, nvidia, etc..) if not,
    you dont have to post. we gotta be careful with that." — an EXPLICIT
    exception to the always-post law: an HE carousel slot MAY stay empty.
    One Haiku call per candidate; fails OPEN (a dead judge must never kill
    the whole HE lane)."""
    txt = "\n".join(f"{s.get('headline', '')} — {(s.get('body') or '')[:150]}"
                    for s in post.get("slides", [])[:4])
    prompt = f"""You gate what gets translated for @ainews.israel, an Instagram AI-news page for young Israelis.

PASS (relevant=true):
- big AI news: OpenAI, Musk, Anthropic, Nvidia, Google, Meta — major model/product/deal stories
- anything involving Israel, Israelis or Israeli companies
- guides/prompt lists that work IDENTICALLY for an Israeli reader (universal tools, no US-only context)

SKIP (relevant=false):
- US-specific stories or guides (US prices, US laws, US-only services, US small-business framing)
- small/niche news a young Israeli would not care about

The post:
{txt}

Return JSON only: {{"relevant": true/false, "why": "one short line"}}"""
    try:
        r = write.call_claude(prompt, schema=REL_SCHEMA, model=write.CHEAP)
        return bool(r.get("relevant", True)), r.get("why", "")
    except Exception as e:
        return True, f"relevance judge down ({e}) — failing open"


ED_SCHEMA = {"type": "object", "properties": {
    "hebrew_naturalness": {"type": "number"}, "grammar": {"type": "number"},
    "clarity_16yo": {"type": "number"}, "source_fidelity": {"type": "number"},
    "brand_voice": {"type": "number"},
    "issues": {"type": "array", "items": {"type": "string"}},
    "corrected_slides": {"type": "array", "items": {"type": "object",
        "properties": {"headline": {"type": "string"},
                       "body": {"type": "string"},
                       "kicker": {"type": "string"}}}}},
    "required": ["hebrew_naturalness", "grammar", "clarity_16yo",
                 "source_fidelity", "brand_voice"]}

ED_BAR = {"hebrew_naturalness": 8, "grammar": 9, "clarity_16yo": 8,
          "source_fidelity": 9, "brand_voice": 8}


def editor_pass(out, post):
    """Scored native-editor gate (owner blueprint Aug 10, hebrew-editorial
    skill): ONE Sonnet call scores the Hebrew 1-10; any score below the bar
    ships the editor's corrected slides. Single pass, no loop (token diet).
    Fails OPEN — a dead editor never kills a slot. Scores persist in
    post-he.json (he_editor) so the daily report can watch the trend."""
    heb = json.dumps({"slides": [{k: s.get(k) for k in
                     ("headline", "body", "kicker") if s.get(k)}
                     for s in out["slides"]]}, ensure_ascii=False, indent=1)
    en = json.dumps([{k: s.get(k) for k in ("headline", "body") if s.get(k)}
                     for s in post["slides"]], ensure_ascii=False)
    prompt = f"""אתה עורך לשוני ישראלי בכיר של @ainews.israel. לפניך פוסט בעברית שעומד להתפרסם, והמקור האנגלי לבדיקת נאמנות לעובדות.

תן ציון 1 עד 10 לכל קטגוריה, בקשיחות של עורך אמיתי:
- hebrew_naturalness: זו עברית שישראלי אומר בקול, או אנגלית במילים עבריות?
- grammar: התאמות מין ומספר, זמנים, סמיכויות. טעות דקדוק אחת = מקסימום 7.
- clarity_16yo: בן 16 קורא בלי להאט? מילה שהוא לא מכיר = להוריד ציון.
- source_fidelity: כל מספר, שם ועובדה מהמקור שרדו במדויק?
- brand_voice: חבר חכם שמספר חדשות בשולחן, לא סוכנות תרגום ולא צ'אטבוט.

אם ציון כלשהו מתחת לרף (naturalness 8, grammar 9, clarity 8, fidelity 9, voice 8) — כתוב corrected_slides: אותו מבנה בדיוק ({len(out["slides"])} שקופיות, אותם שדות), עם התיקונים שלך. מותר לשכתב משפט שלם, אסור לשנות עובדות. שמור על תגי <em> ו-<b>. בלי מקפים.

{doctrine()}

{skill_refs()}

המקור האנגלי (לבדיקת עובדות בלבד):
{en}

הפוסט בעברית:
{heb}

החזר JSON בלבד."""
    try:
        r = write.call_claude(prompt, schema=ED_SCHEMA)
        scores = {k: r.get(k, 10) for k in ED_BAR}
        low = [k for k in ED_BAR if scores.get(k, 10) < ED_BAR[k]]
        print("hebrew editor: "
              + ", ".join(f"{k}={scores[k]}" for k in ED_BAR)
              + (f" — below bar {low}, adopting corrections" if low
                 else " — pass"), file=sys.stderr)
        for issue in r.get("issues", [])[:5]:
            print(f"  editor issue: {issue}", file=sys.stderr)
        if low and len(r.get("corrected_slides", [])) == len(out["slides"]):
            for s, c in zip(out["slides"], r["corrected_slides"]):
                for k in ("headline", "body", "kicker"):
                    if s.get(k) and c.get(k):
                        s[k] = write.no_dashes(c[k])
        out["he_editor"] = scores
    except Exception as e:
        print(f"hebrew editor down ({e}) — failing open", file=sys.stderr)
    return out


def main():
    if len(sys.argv) > 1:
        return localize(sys.argv[1])   # explicit dispatch = owner's pick, no gate
    cands = backlog()
    if not cands:
        raise SystemExit("no un-localized post found")
    # fallback ladder — newest first, walk the backlog until one post BOTH
    # passes the Israel-relevance gate AND localizes clean. Up to 6 judged
    # (cheap Haiku calls), up to 3 real localization attempts (token diet).
    last, attempts = None, 0
    for post_dir in cands[:6]:
        name = os.path.basename(post_dir)
        try:
            post = json.load(open(os.path.join(post_dir, "post.json")))
            ok, why = israel_relevant(post)
        except Exception as e:
            ok, why = True, f"gate crashed ({e}) — failing open"
        if not ok:
            print(f"{name} skipped — not Israel-relevant: {why} "
                  "(owner rule Aug 10)", file=sys.stderr)
            continue
        attempts += 1
        try:
            return localize(post_dir)
        # SystemExit = a gate said no; Exception = crash (e.g. issue #13:
        # call_claude RuntimeError "Request timed out"). Both fall through.
        except (SystemExit, Exception) as e:
            last = e
            print(f"{name} failed ({e}) — trying the next backlog post",
                  file=sys.stderr)
        if attempts >= 3:
            break
    if last is None:  # everything skipped by the gate — a legal empty slot.
        # Same sentinel the workflow greps for a clean skip (substring match).
        raise SystemExit("no un-localized post found (none Israel-relevant)")
    raise SystemExit(f"all {attempts} attempted backlog posts failed; last: {last}")


def localize(post_dir):
    post_dir = post_dir.rstrip("/")
    post = json.load(open(os.path.join(post_dir, "post.json")))
    name = os.path.basename(post_dir)
    prompt = build_prompt(post)   # the ONE translate call (token diet Aug 8)
    r = write.call_claude(prompt, schema=HE_SCHEMA)
    out = scrub(merge(post, r), post["caption"])
    errs = qa(out)
    if len(r.get("slides", [])) != len(post["slides"]):
        errs.append(f"returned {len(r.get('slides', []))} slides instead of "
                    f"{len(post['slides'])}")
    if errs:  # one retry with the errors on the table, then fail loudly
        r = write.call_claude(prompt + "\n\nYOUR LAST ATTEMPT FAILED QA:\n- "
                              + "\n- ".join(errs) + "\nFix every issue.",
                              schema=HE_SCHEMA)
        out = scrub(merge(post, r), post["caption"])
        errs = qa(out)
        if errs:
            raise SystemExit("Hebrew QA failed twice: " + "; ".join(errs))

    out = editor_pass(out, post)   # scored native-editor gate (skill, Aug 10)

    # owner-dictated cover headline (Aug 10, Decart deal: "use the exact
    # headline i sent you"): a headline-he.txt in the EN post dir overrides
    # the translated cover headline VERBATIM. Applied after QA on purpose —
    # the digit/LTR-island rules yield to the owner's wording; only the
    # deterministic dash scrub touches it.
    forced = os.path.join(post_dir, "headline-he.txt")
    if os.path.exists(forced):
        out["slides"][0]["headline"] = write.no_dashes(
            open(forced).read().strip())
        print("cover headline forced from headline-he.txt", file=sys.stderr)

    out_dir = os.path.join(HERE, "posts-he", name)
    os.makedirs(out_dir, exist_ok=True)
    pj = os.path.join(out_dir, "post-he.json")
    json.dump(out, open(pj, "w"), ensure_ascii=False, indent=1)
    # carousel videos travel with the post unchanged (video needs no translation)
    import shutil
    for f in os.listdir(post_dir):
        if re.fullmatch(r"video-\d+\.mp4", f):
            shutil.copy(os.path.join(post_dir, f), os.path.join(out_dir, f))
    import render_he
    render_he.render(pj, out_dir)
    print(f"post ready: {os.path.relpath(out_dir, os.getcwd())}")


if __name__ == "__main__":
    main()
