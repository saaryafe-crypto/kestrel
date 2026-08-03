#!/usr/bin/env python3
"""Hebrew arm (@ainews.israel): retells a FINISHED English post natively in
Hebrew and re-renders it RTL. Runs after the English publish — the input
already survived the judge, the hook tournament, QA, and the dash scrub, so
this stage re-tells the same validated story, it never re-decides content
(owner Jul 29: same design, same everything, only the language changes).

Aug 2 rebuild (owner: translated Hebrew is "very bad... we need a proper
solution"): the old flow SHOWED the writer the English slides and asked it to
"forget them" — impossible; it shipped calques ("לא קיבל את ההודעה" for
"didn't get the memo") that the grammar-only polish pass can't see because
they're grammatically fine. New flow is the proven born-in-Hebrew pattern
(reel titles, feedback_hooks §4) extended to the whole carousel:
  1. extract_facts(): English post -> DRY fact sheet (no idioms, no prose)
  2. build_prompt(): Hebrew-language writer prompt, fact sheet only — the
     writer never sees an English sentence, so it cannot calque
  3. hebrew_cover() tournament + polish() editor, unchanged
  4. qa(): + owner digits rule (counts one-to-ten as Hebrew words, LTR-island
     cap on the cover — digits/Latin break the RTL reading flow)

Usage: python3 he.py [posts/<dir>]     (default: newest un-localized post)
Output: posts-he/<same name>/ with slide-*.jpg + caption.txt + post-he.json
Prints "post ready: posts-he/<name>" for the workflow, same contract as
write.py."""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import write  # call_claude, no_dashes — the shared craft helpers
import viral  # native Hebrew cover hook (packaging is re-created, not translated)

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


FACTS_SCHEMA = {"type": "object", "properties": {
    "slides": {"type": "array", "items": {"type": "object", "properties": {
        "claim": {"type": "string"},
        "facts": {"type": "array", "items": {"type": "string"}},
        "opens": {"type": "string"}},
        "required": ["claim"]}},
    "protagonist": {"type": "string"},
    "sources": {"type": "string"},
    "cta": {"type": "string"}},
    "required": ["slides"]}


def extract_facts(post):
    """Stage 1 — the calque firewall (owner Aug 2: translated Hebrew is 'very
    bad'; every fix that let the writer SEE the English sentences still
    shipped calques like 'לא קיבל את ההודעה' for 'didn't get the memo').
    Turn the English post into a DRY fact sheet; the Hebrew writer gets only
    this, never the English prose, so there is nothing to shadow."""
    src = {"slides": [{k: s.get(k) for k in ("type", "headline", "body", "kicker")
                       if s.get(k)} for s in post["slides"]],
           "caption": post["caption"],
           "pinned_comment": post.get("pinned_comment"),
           "validated_facts": (post.get("viral") or {}).get("specifics")}
    prompt = f"""You are preparing a language-neutral FACT SHEET from a published English
Instagram carousel, so a native Hebrew writer can retell the story WITHOUT
ever seeing the English sentences (translated Hebrew keeps English idioms;
this fact sheet is the firewall).

For each slide, in order:
- claim: the point this slide must land, stated DRY and telegraphic. Plain
  facts only — strip every idiom, pun, metaphor and stylistic choice. Write
  like an engineer's changelog, never like a copywriter. If the slide quotes
  an AI prompt, describe what the prompt asks the AI to do, don't copy its
  sentences.
- facts: the exact numbers, names, prices, URLs, button labels and quotes
  that MUST survive verbatim (e.g. "$1,200 -> $180",
  "myactivity.google.com/product/gemini", "Smart features and personalization").
- opens: the question this slide leaves open for the next one ("" for the last).

Also:
- protagonist: who drives the story + their identity facts, or "".
- sources: the source names from the caption, or "".
- cta: what the last slide asks the reader to do, dry.

THE ENGLISH POST:
{json.dumps(src, ensure_ascii=False, indent=1)}

Return ONLY the JSON object."""
    return write.call_claude(prompt, schema=FACTS_SCHEMA)


def build_prompt(post, facts):
    """Stage 2 — the native writer. Prompt is IN Hebrew (the polish pass
    proved that pushes the model into native mode) and contains zero English
    prose: only the skeleton (which fields each slide has) + the fact sheet."""
    skel = []
    fslides = facts.get("slides") or []
    for i, s in enumerate(post["slides"]):
        f = fslides[i] if i < len(fslides) else {}
        skel.append({"slide": i + 1, "type": s.get("type", "content"),
                     "fields": [k for k in ("headline", "body", "kicker")
                                if s.get(k)],
                     "claim": f.get("claim"), "facts": f.get("facts"),
                     "opens": f.get("opens")})
    return f"""אתה הכותב הראשי של @ainews.israel, עמוד חדשות AI באינסטגרם לקהל ישראלי צעיר.

לפניך דף עובדות של סיפור אמיתי. כתוב את הקרוסלה בעברית, מאפס. זו לא משימת תרגום: אין טקסט מקורי לחקות. יש עובדות, ואתה מספר אותן כמו שישראלי מספר סיפור מטורף לחבר ליד השולחן. כל מספר, שם ועובדה מדף העובדות חייבים לשרוד במדויק. כל השאר, הניסוח, הקצב, סדר המילים, נולד בעברית.

הסגנון: כותרות בצורות של ynet ו-N12, אבל פשוטות יותר, לקהל צעיר. עברית מדוברת של ישראלי חכם בן 16. אפס עברית של עיתון.

{doctrine()}

חוקי מבנה (קשיחים):
- בדיוק {len(post['slides'])} שקופיות, לפי השלד למטה, ובכל שקופית רק השדות שמופיעים ב-fields שלה. "kicker" הוא פס קטן מתחת לכותרת השער: 3-7 מילים, ביט שני של הסיפור.
- שקופית 1 היא השער: כותרת שעוצרת גלילה, בצורה של כותרת ישראלית אמיתית. היא מפעילה את הרגש הכי חזק שיש בסיפור, פחד, כסף, איום עליך אישית, או וואו, ומספרת את הסיפור המלא עם הפרט הכי מטורף בפנים. לא חידה ולא קליקבייט: הקורא מקבל הכל כבר בשער, והחלקה פנימה נותנת את הפירוט. כל שקופית עונה על השאלה שהקודמת פתחה ופותחת את הבאה.
- <em>...</em> סביב קבוצת המילים המינימלית שמעבירה את הטענה לבד (חובה בכותרת השער). <b>...</b> סביב אחת עד שלוש עובדות מפתח בכל body.
- מספרים: אחת עד עשר תמיד במילים, בהתאמת מין נכונה לשם העצם (שש בעיות, חמישה כלים, שני מסוקים). כמה שפחות ספרות ומילים באנגלית בכל שורה. בכותרות: מקסימום אי LTR אחד (מספר אחד או שם מותג אחד).
- caption: שורה ראשונה עם השורה התחתונה של הסיפור ומילים שישראלי היה מחפש, אחר כך הסיפור בקצרה, שורת מקורות ({facts.get('sources') or 'המקורות מדף העובדות'}), וקריאה לעקוב אחרי {HANDLE}. בלי האשטגים, הם מתווספים אוטומטית.
- pinned_comment: כתוב תגובה נעוצה קצרה בעברית (אם השדה קיים בפוסט המקורי).

השלד ודף העובדות:
{json.dumps({"slides": skel, "protagonist": facts.get("protagonist"),
             "cta": facts.get("cta")}, ensure_ascii=False, indent=1)}

החזר JSON בלבד: {{"slides": [{{"headline": "...", "body": "...", "kicker": "..."}}], "caption": "...", "pinned_comment": "..."}} — בדיוק {len(post['slides'])} שקופיות, באותו הסדר."""


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


POLISH_SCHEMA = {"type": "object", "properties": {
    "fixes": {"type": "array", "items": {"type": "object", "properties": {
        "id": {"type": "string"}, "text": {"type": "string"}},
        "required": ["id", "text"]}}},
    "required": ["fixes"]}


def polish_items(items):
    """Core of the native-editor pass: {{id: text}} in, {{id: fixed}} out —
    only ids that actually needed a fix. Fails open (empty dict). Shared by
    the carousel polish() below and reel_he.py captions (owner Jul 31: reels
    must get the same native line-edit, no inconsistency)."""
    prompt = f"""אתה עורך לשון ישראלי בכיר של עמוד חדשות טכנולוגיה באינסטגרם. הטקסטים למטה נכתבו מהר, ולפעמים נשארות בהם שגיאות. קרא כל שדה בקול רם: אם ישראלי היה נתקע או מרים גבה, תקן. עבור על כל שדה ותקן אך ורק שגיאות שפה:

מה לתקן:
- שגיאות דקדוק: התאמת מין ומספר (זכר/נקבה, יחיד/רבים), סמיכות, אותיות שימוש
- מילות יחס שגויות (הוכרז על, השתלט את...)
- תרגומית: משפט שנשמע כמו אנגלית במילים עבריות ("עשה היסטוריה", "לקח החלטה") — נסח כמו שישראלי באמת אומר
- מספרים מאחת עד עשר שנכתבו בספרות: החלף למילים בהתאמת מין נכונה ("6 בעיות" -> "שש בעיות", "5 כלים" -> "חמישה כלים")
- מבנה משפט מסורבל או סביל מיותר — הפוך לפעיל וישיר
- כתיב מלא תקני

מה לא לגעת:
- התוכן, העובדות, המספרים, השמות — נשארים בדיוק
- המשלב: עברית מדוברת של ישראלי צעיר וחכם, לא עברית של עיתון
- תגיות <em>...</em> ו-<b>...</b> נשארות סביב אותן מילים מקבילות
- אורך: כותרת נשארת קצרה באותו סדר גודל
- האשטגים, קישורים, שמות באנגלית — לא נוגעים

השדות (מזהה: טקסט):
{json.dumps(items, ensure_ascii=False, indent=1)}

החזר JSON בלבד: {{"fixes": [{{"id": "<מזהה>", "text": "<הטקסט המתוקן>"}}]}} — רק שדות שבאמת דורשים תיקון. אם הכול תקין, החזר רשימה ריקה."""
    try:
        r = write.call_claude(prompt, schema=POLISH_SCHEMA)
        fixed = {}
        for f in r.get("fixes", []):
            fid, txt = f.get("id", ""), (f.get("text") or "").strip()
            if not txt or fid not in items or not HEB.search(txt):
                continue
            fixed[fid] = write.no_dashes(txt.replace("\u05be", "-"))
        return fixed
    except Exception as e:
        print(f"hebrew polish failed ({e}) — keeping localized text", file=sys.stderr)
        return {}


def polish(out):
    """Agent 5 — the Hebrew language expert (owner Jul 31: 'translation from
    English causes many language errors'). A separate native-editor pass that
    reads every published field AFTER localization + the native cover and
    returns ONLY the fields that contain actual Hebrew errors, fixed. It fixes
    language, never content or style. Fails open: the localized text stands."""
    items = {}
    for i, s in enumerate(out["slides"]):
        for k in ("headline", "body"):
            if s.get(k):
                items[f"s{i}.{k}"] = s[k]
    items["caption"] = out["caption"]
    if out.get("pinned_comment"):
        items["pinned_comment"] = out["pinned_comment"]
    fixed = polish_items(items)
    for fid, txt in fixed.items():
        if fid == "caption":
            out["caption"] = txt
        elif fid == "pinned_comment":
            out["pinned_comment"] = txt
        else:
            i, k = fid[1:].split(".", 1)
            out["slides"][int(i)][k] = txt
    print(f"hebrew polish fixed {len(fixed)} field(s)", file=sys.stderr)
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


def main():
    if len(sys.argv) > 1:
        return localize(sys.argv[1])
    cands = backlog()
    if not cands:
        raise SystemExit("no un-localized post found")
    # fallback ladder (owner rule: a slot is never skipped) — newest first,
    # walk the backlog until one post localizes clean
    last = None
    for post_dir in cands[:3]:
        try:
            return localize(post_dir)
        # SystemExit = a gate said no; Exception = crash (e.g. issue #13:
        # call_claude RuntimeError "Request timed out"). Both fall through.
        except (SystemExit, Exception) as e:
            last = e
            print(f"{os.path.basename(post_dir)} failed ({e}) — "
                  "trying the next backlog post", file=sys.stderr)
    raise SystemExit(f"all {min(3, len(cands))} backlog posts failed; last: {last}")


def localize(post_dir):
    post_dir = post_dir.rstrip("/")
    post = json.load(open(os.path.join(post_dir, "post.json")))
    name = os.path.basename(post_dir)
    facts = extract_facts(post)   # stage 1: the calque firewall
    prompt = build_prompt(post, facts)
    r = write.call_claude(prompt, schema=HE_SCHEMA)
    if len(r.get("slides", [])) != len(post["slides"]):
        r = write.call_claude(prompt + f"\n\nYOUR LAST ATTEMPT returned "
                              f"{len(r.get('slides', []))} slides instead of "
                              f"{len(post['slides'])}. Fix it.", schema=HE_SCHEMA)
    def finalize(r):
        out = scrub(merge(post, r), post["caption"])
        # viral agent: the cover hook is PACKAGING — written natively in
        # Hebrew from the classified story, competing against the localized
        # translation (older posts without a classification keep the
        # translation). Runs before qa() so the final cover is validated.
        if (post.get("viral") and post.get("story")
                and not any(s.get("layout") == "card" for s in post["slides"])):
            # profile posts keep their long record-sentence cover (translated,
            # not re-hooked — the rival candidates don't know the card format)
            # img = the ENGLISH cover hook (audit Aug 3): the Hebrew post
            # inherits the English cover PHOTO, and that photo was
            # vision-validated against this exact claim — passing it keeps
            # the new Hebrew hook welded to what the photo actually shows
            en_hook = "" if not post["slides"][0].get("media") else \
                post["slides"][0].get("headline", "")
            out = viral.hebrew_cover(out, post["story"], post["viral"],
                                     post.get("caption", ""), img=en_hook)
        return polish(out)  # Agent 5: native line-editor pass, runs LAST

    out = finalize(r)
    errs = qa(out)
    if errs:  # one retry with the errors on the table, then fail loudly
        r = write.call_claude(prompt + "\n\nYOUR LAST ATTEMPT FAILED QA:\n- "
                              + "\n- ".join(errs) + "\nFix every issue.",
                              schema=HE_SCHEMA)
        out = finalize(r)
        errs = qa(out)
        if errs:
            raise SystemExit("Hebrew QA failed twice: " + "; ".join(errs))

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
