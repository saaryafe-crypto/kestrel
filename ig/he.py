#!/usr/bin/env python3
"""Hebrew arm (@ainews.israel): localizes a FINISHED English post into proper
Hebrew and re-renders it RTL. Runs after the English publish — the input
already survived the judge, the hook tournament, QA, and the dash scrub, so
this stage translates craft, it never re-decides content (owner Jul 29: same
design, same everything, only the language and direction change; the English
system stays frozen — this arm only ADDS files).

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
        dirs.append(full)
    # newest first BY NAME (dirs start with the date) — mtime is useless on a
    # fresh CI clone, where every file gets checkout time
    return sorted(dirs, key=os.path.basename, reverse=True)


def build_prompt(post):
    src = {"slides": [{k: s.get(k) for k in ("type", "headline", "body")
                       if s.get(k)} for s in post["slides"]],
           "caption": post["caption"],
           "pinned_comment": post.get("pinned_comment")}
    return f"""You are the Hebrew editor of @ainews.israel, the Hebrew twin of a viral
English AI-news Instagram page. Below is a published English carousel that
already won its hook tournament and QA. Localize it into Hebrew.

This is LOCALIZATION, not translation: carry the hook's tension, the
information gap between slides, and the emotional register into Hebrew that a
smart Israeli 16-year-old would actually say out loud. If a literal
translation sounds stiff, rewrite the sentence Israeli-style.

{doctrine()}

STRUCTURE RULES (hard):
- Return EXACTLY {len(post['slides'])} slides, same order. For each slide
  localize only the text fields it has (headline / body). Never add
  or drop a slide.
- Keep the <em>...</em> accent markup: wrap the minimum set of Hebrew words
  that still communicates the claim standalone (same craft as the English).
- Keep <b>...</b> bold markup in bodies where the English used it.
- The caption keeps the same block structure (payoff first line with Hebrew
  search words, story, sources, follow CTA, hashtags). Hashtags: copy the
  English hashtags UNCHANGED. Sources keep their English names. Follow handle
  is {HANDLE}.
- pinned_comment: localize it too (if present).

THE ENGLISH POST:
{json.dumps(src, ensure_ascii=False, indent=1)}

Return ONLY the JSON object."""


def merge(post, r):
    """Model text onto the English post skeleton — media/layout untouched."""
    out = json.loads(json.dumps(post))  # deep copy
    out["handle"] = HANDLE
    for s, h in zip(out["slides"], r["slides"]):
        for k in ("headline", "body"):
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
        for k in ("headline", "body", "subline"):
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
    prompt = f"""אתה עורך לשון ישראלי בכיר של עמוד חדשות טכנולוגיה באינסטגרם. הטקסטים למטה תורגמו מאנגלית, ותרגום משאיר שגיאות. עבור על כל שדה ותקן אך ורק שגיאות שפה:

מה לתקן:
- שגיאות דקדוק: התאמת מין ומספר (זכר/נקבה, יחיד/רבים), סמיכות, אותיות שימוש
- מילות יחס שגויות (הוכרז על, השתלט את...)
- תרגומית: משפט שנשמע כמו אנגלית במילים עבריות ("עשה היסטוריה", "לקח החלטה") — נסח כמו שישראלי באמת אומר
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


def qa(out):
    errs = []
    if not HEB.search(out["slides"][0].get("headline", "")):
        errs.append("cover headline is not Hebrew")
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
    prompt = build_prompt(post)
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
            # not re-hooked — the ≤9-word Hebrew candidates would destroy it)
            out = viral.hebrew_cover(out, post["story"], post["viral"],
                                     post.get("caption", ""))
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
