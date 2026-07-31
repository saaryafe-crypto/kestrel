#!/usr/bin/env python3
"""Hebrew arm (@ainews.israel) reels: takes a FINISHED English reel (it already
won the pick, the title tournament, and clip QA), localizes the overlay title +
caption into Hebrew, and rebuilds the SAME clip (reel.json stores source /
start_s / clip_s) with the Hebrew card: name "AI News Israel", handle
@ainews.israel, avatar art/avatar-he.jpg. Owner spec Jul 29: the profile card
stays on the LEFT exactly like the English one (blue check, LTR), only the
name/pic/handle change; the title text itself is proper RTL Hebrew.

Runs on the Mac (video sources are blocked from CI, same as reel.py), then
triggers ig-reel-he.yml which publishes via the Hebrew Make webhook.
The English system stays frozen — this file only ADDS.

Usage: .venv/bin/python reel_he.py [posts/<name>] [--dry]
  no arg -> newest English reel without a Hebrew twin
  --dry  -> build posts-he/<name>/reel.mp4 but don't push or publish"""
import html, json, os, re, shutil, subprocess, sys, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import he      # HANDLE, HEB, doctrine() — the Hebrew craft, single source
import reel    # OVERLAY geometry, build_video, push_media, yt, sh
import write   # call_claude, no_dashes
from render import CHROME

HANDLE = he.HANDLE
AVATAR = os.path.join(HERE, "art", "avatar-he.jpg")

# Same layout as reel.OVERLAY — only the card identity changes and the title
# becomes RTL (Heebo; Poppins has zero Hebrew glyphs). Card stays LTR left.
OVERLAY_HE = """<!doctype html><meta charset=utf-8><style>
@font-face{{font-family:Poppins;src:url("FONTS/Poppins-SemiBold.ttf");font-weight:600}}
@font-face{{font-family:Poppins;src:url("FONTS/Poppins-ExtraBold.ttf");font-weight:800}}
@font-face{{font-family:HebBody;src:url("FONTS/Heebo-Variable.ttf");font-weight:100 900}}
*{{margin:0;box-sizing:border-box}}
body{{width:1080px;height:1920px;background:transparent;font-family:Poppins;
     position:relative;overflow:hidden}}
.hole{{position:absolute;left:{vx}px;top:{vy}px;width:{vw}px;height:{vh}px;
      border-radius:26px;box-shadow:0 0 0 2200px #050505}}
.card{{position:absolute;left:70px;top:175px;display:flex;align-items:center;gap:28px}}
.card img{{width:130px;height:130px;border-radius:50%;display:block}}
.name{{display:flex;align-items:center;gap:12px;
      font-weight:800;font-size:48px;color:#FFF;line-height:1.15}}
.name svg{{width:46px;height:46px;flex:none}}
.handle{{font-weight:600;font-size:40px;color:#8B98A5;margin-top:4px}}
.title{{position:absolute;left:70px;top:365px;width:950px;direction:rtl;
       text-align:right;font-family:HebBody;font-weight:600;font-size:48px;
       color:#FFF;line-height:1.35}}
</style><body>
<div class=hole></div>
<div class=card><img src="ART/avatar-he.jpg"><div>
  <div class=name>AI News Israel <svg viewBox="0 0 24 24" fill="#1d9bf0"><path d="M22.25 12c0-1.43-.88-2.67-2.19-3.34.46-1.39.2-2.9-.81-3.91s-2.52-1.27-3.91-.81c-.66-1.31-1.91-2.19-3.34-2.19s-2.67.88-3.33 2.19c-1.4-.46-2.91-.2-3.92.81s-1.26 2.52-.8 3.91c-1.31.67-2.2 1.91-2.2 3.34s.89 2.67 2.2 3.34c-.46 1.39-.21 2.9.8 3.91s2.52 1.26 3.91.81c.67 1.31 1.91 2.19 3.34 2.19s2.68-.88 3.34-2.19c1.39.45 2.9.2 3.91-.81s1.27-2.52.81-3.91c1.31-.67 2.19-1.91 2.19-3.34zm-11.71 4.2L6.8 12.46l1.41-1.42 2.26 2.26 4.8-5.23 1.47 1.36-6.2 6.77z"/></svg></div>
  <div class=handle>@ainews.israel</div>
</div></div>
<div class=title>TITLE</div>
</body>""".format(vx=reel.VID_X, vy=reel.VID_Y, vw=reel.VID_W, vh=reel.VID_H)

HE_SCHEMA = {"type": "object",
             "properties": {"title": {"type": "string"},
                            "title_candidates": {"type": "array",
                                                 "items": {"type": "string"}},
                            "caption": {"type": "string"}},
             "required": ["title", "caption"]}


def backlog():
    """English reel dirs without a Hebrew twin, newest first (Jul 31 audit:
    trying only the newest meant one dead source link killed the slot forever
    — @ainews.israel got 2 reels total). The runner walks the list."""
    dirs = []
    root = os.path.join(HERE, "posts")
    for d in os.listdir(root):
        full = os.path.join(root, d)
        if not os.path.exists(os.path.join(full, "reel.json")):
            continue
        if os.path.exists(os.path.join(HERE, "posts-he", d, "reel.mp4")):
            continue
        dirs.append(full)
    # newest first BY NAME (dirs start with the date; mtime lies on fresh clones)
    return sorted(dirs, key=os.path.basename, reverse=True)


def build_prompt(r):
    return f"""You are the Hebrew editor of @ainews.israel, the Hebrew twin of a viral
English AI-news Instagram page. Below is a published English reel (overlay
title + caption) that already won its title tournament and QA. Localize it
into Hebrew. This is LOCALIZATION, not translation: carry the curiosity gap
and the understated register into Hebrew a smart Israeli 16-year-old would
say out loud. If a literal translation sounds stiff, rewrite it Israeli-style.

{he.doctrine()}

STRUCTURE RULES (hard):
- "title": the overlay line on the video. Max 70 characters, Hebrew, opens
  the same information gap the English title opens, never resolves it. No
  hype words, no emojis.
- "title_candidates": 4 MORE native Hebrew overlay lines for the same video,
  written from scratch (not re-translations) and genuinely different from
  each other: one leading with the most insane concrete specific, one pure
  curiosity gap, one with a second-person stake, one free. Same hard limits
  as "title" (max 70 chars, no hype words, no emojis). A blind judge picks
  the winner, so make each one the best of its kind.
- "caption": keep the same block structure as the English — the explainer
  paragraphs in Hebrew (first sentence carries the payoff), then the follow
  line with {HANDLE}, then the Credits block, then the hashtags.
- Credits: keep "Credits:" and the creator's name EXACTLY as in English
  (plain name, never an @ handle, # hashtag, or u/ prefix — drop any such
  prefix). The "DM for credit or removal" sentence gets localized to Hebrew.
- Hashtags: copy the 5 English hashtags UNCHANGED.

THE ENGLISH REEL:
title: {r["title"]}
caption:
{r["caption"]}

Return ONLY the JSON object."""


TITLES_SCHEMA = {"type": "object",
                 "properties": {"titles": {"type": "array",
                                           "items": {"type": "string"}}},
                 "required": ["titles"]}


def native_titles(r):
    """Dedicated NATIVE Hebrew title generation (owner order Aug 1: the HE
    reel hook must improve significantly). The localizer's side-task
    candidates were flat translated lines with grammar slips; this call is
    born-in-Hebrew, steered by the hook craft doctrine, and its output
    competes in the same judge. Fails open (empty list)."""
    facts = r["caption"].split("Credits:")[0].strip()[:1200]
    prompt = f"""אתה כותב הכותרות של @ainews.israel, עמוד רילס ויראלי בעברית על AI.
על הסרטון יושבת שורת טקסט אחת. היא מחליטה אם צופה עוצר או ממשיך לגלול.

הסרטון (העובדות, אל תמציא כלום):
כותרת באנגלית: {r["title"]}
תיאור: {facts}

{he.doctrine()}

כתוב 6 כותרות עבריות שנולדו בעברית, לא תרגום. כל אחת התקפה שונה באמת:
1. מובילה עם הפרט הכי מטורף והכי קונקרטי בסרטון (מספר מדויק, הדבר עצמו)
2. פער סקרנות טהור: מה אני רואה פה בכלל
3. פנייה ישירה לצופה (אתה/שלך)
4. פתיחה ב"מה ש..." שמקדימה את הפאנץ'
5. הרגע-שלפני או הניסוח היבש שנותן לעובדה לצרוח לבד
6. חופשית, הכי טובה שלך

חוקים קשיחים:
- עד 70 תווים. עברית מדוברת של ישראלי צעיר וחכם. אפס מילות באזז, אפס אימוג'ים.
- מבחן הקול: תקרא בקול רם. שגיאת דקדוק או משפט שנשמע מתורגם = פסול.
- שמות מותגים נשארים באנגלית. בלי מקף מכל סוג.

החזר JSON בלבד: {{"titles": ["...", "...", "...", "...", "...", "..."]}}"""
    try:
        out = write.call_claude(prompt, schema=TITLES_SCHEMA)
        return [write.no_dashes(t.replace("\u05be", "-").strip())
                for t in out.get("titles", [])
                if isinstance(t, str) and he.HEB.search(t) and len(t) <= 75]
    except Exception as e:
        print(f"native HE titles failed ({e}) — localized candidates only",
              file=sys.stderr)
        return []


def scrub(out, en_caption):
    """Deterministic gates — never trust the prompt alone."""
    def clean(t):
        # EN handle must never survive in ANY field (same bug class as the
        # carousel run 30623475851 failure — qa checks title + caption)
        return write.no_dashes(t.replace("@yaffeai", HANDLE)
                                .replace("\u05be", "-"))
    out["title"] = clean(out["title"])
    cap = clean(out["caption"])
    # published hashtags ARE the English ones (owner rule)
    en_tags = re.findall(r"#\w+", en_caption)
    cap = re.sub(r"#[\w\u0590-\u05FF]+", "", cap).rstrip()
    if en_tags:
        cap += "\n\n" + " ".join(en_tags)
    out["caption"] = cap
    return out


def qa(out):
    errs = []
    if not he.HEB.search(out["title"]):
        errs.append("overlay title is not Hebrew")
    if len(out["title"]) > 75:
        errs.append("title over 75 chars")
    if not he.HEB.search(out["caption"][:200]):
        errs.append("caption payoff line is not Hebrew")
    if HANDLE not in out["caption"]:
        errs.append(f"caption missing follow handle {HANDLE}")
    if "Credits:" not in out["caption"]:
        errs.append("caption missing Credits line")
    else:  # owner rule: credits are plain names
        cred = out["caption"].split("Credits:", 1)[1].splitlines()[0]
        if re.search(r"[@#]|\bu/", cred):
            errs.append("Credits line must be a plain name (no @, #, or u/)")
    if "@yaffeai" in out["title"] + out["caption"]:
        errs.append("@yaffeai leaked into the Hebrew reel")
    return errs


def make_overlay(title, out_png):
    page = (OVERLAY_HE.replace("FONTS", "file://" + os.path.join(HERE, "fonts"))
                      .replace("ART", "file://" + os.path.join(HERE, "art"))
                      .replace("TITLE", html.escape(title)))
    hp = out_png.replace(".png", ".html")
    open(hp, "w").write(page)
    reel.sh(CHROME, "--headless", "--disable-gpu",
            "--default-background-color=00000000", f"--screenshot={out_png}",
            "--window-size=1080,1920", "file://" + hp)


def fetch_source(source, dst):
    """Re-fetch the exact clip the English reel used. X clips are bare mp4
    URLs (urllib, no extractor to go stale); everything else goes through
    yt-dlp like reel.py."""
    if os.path.exists(dst):
        os.remove(dst)
    if "video.twimg.com" in source or source.split("?")[0].endswith(".mp4"):
        req = urllib.request.Request(source, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=180) as resp, open(dst, "wb") as f:
            shutil.copyfileobj(resp, f)
    else:
        reel.yt("-f", "bv*[height<=1080]+ba/b", "--merge-output-format", "mp4",
                "-o", dst, source)
    if not os.path.exists(dst):
        raise SystemExit(f"could not re-fetch source clip: {source}")


def main():
    dry = "--dry" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--dry"]
    if not os.path.exists(AVATAR):
        raise SystemExit(f"missing {AVATAR} — drop the @ainews.israel profile "
                         "pic there first (owner TODO)")
    if args:
        return localize(args[0].rstrip("/"), dry)
    cands = backlog()
    if not cands:
        raise SystemExit("no un-localized reel found")
    last = None
    for post_dir in cands[:3]:  # fallback ladder: a dead source link falls through
        try:
            return localize(post_dir, dry)
        # SystemExit = a gate said no; Exception = crash (e.g. issue #13:
        # call_claude RuntimeError "Request timed out"). Both fall through.
        except (SystemExit, Exception) as e:
            last = e
            print(f"{os.path.basename(post_dir)} failed ({e}) — "
                  "trying the next backlog reel", file=sys.stderr)
    raise SystemExit(f"all {min(3, len(cands))} backlog reels failed; last: {last}")


def localize(post_dir, dry):
    r = json.load(open(os.path.join(post_dir, "reel.json")))
    name = os.path.basename(post_dir)

    prompt = build_prompt(r)
    out = scrub(write.call_claude(prompt, schema=HE_SCHEMA), r["caption"])
    errs = qa(out)
    if errs:  # one retry with the errors on the table, then fail loudly
        out = scrub(write.call_claude(
            prompt + "\n\nYOUR LAST ATTEMPT FAILED QA:\n- " + "\n- ".join(errs)
            + "\nFix every issue.", schema=HE_SCHEMA), r["caption"])
        errs = qa(out)
        if errs:
            raise SystemExit("Hebrew reel QA failed twice: " + "; ".join(errs))
    # viral agent: born-in-Hebrew candidates (dedicated craft call) + the
    # localizer's side candidates compete against the localized title; the
    # QA'd localization stays the fallback if the judge fails or the winner
    # breaks a hard limit.
    import viral
    cands = native_titles(r) \
        + [t for t in out.get("title_candidates", [])
           if isinstance(t, str) and he.HEB.search(t)] + [out["title"]]
    win, why = viral.reel_title_judge(cands, lang="he")
    if win and he.HEB.search(win) and len(win) <= 75:
        out["title"] = write.no_dashes(win.replace("\u05be", "-"))
        if why:
            print(f"title judge: {why}", file=sys.stderr)
    # native line-edit, same as carousels (owner Jul 31: no reel/carousel
    # inconsistency). Fails open; hard limits + handle/credits must survive.
    fixed = he.polish_items({"title": out["title"], "caption": out["caption"]})
    if fixed.get("title") and len(fixed["title"]) <= 75:
        out["title"] = fixed["title"]
    if fixed.get("caption") and HANDLE in fixed["caption"] \
            and "Credits:" in fixed["caption"]:
        out["caption"] = fixed["caption"]
    print(f"overlay HE: {out['title']}", file=sys.stderr)

    out_dir = os.path.join(HERE, "posts-he", name)
    os.makedirs(out_dir, exist_ok=True)
    src = "/tmp/reel-he-src.mp4"
    fetch_source(r["source"], src)
    make_overlay(out["title"], os.path.join(out_dir, "overlay.png"))
    reel.build_video(src, os.path.join(out_dir, "overlay.png"),
                     os.path.join(out_dir, "reel.mp4"),
                     r.get("start_s", 0), r["clip_s"])
    os.remove(src)
    # output gate (Jul 31, same as reel.py): never push a broken encode
    mp4 = os.path.join(out_dir, "reel.mp4")
    if not os.path.exists(mp4) or os.path.getsize(mp4) < 200_000:
        shutil.rmtree(out_dir, ignore_errors=True)
        raise SystemExit("HE reel.mp4 came out broken — not publishing")
    json.dump({"title": out["title"], "caption": out["caption"],
               "start_s": r.get("start_s", 0), "clip_s": r["clip_s"],
               "source": r["source"], "channel": r.get("channel"),
               "publish": "make", "localized_from": name},
              open(os.path.join(out_dir, "reel.json"), "w"),
              ensure_ascii=False, indent=1)
    print("reel ready:", os.path.join(out_dir, "reel.mp4"))
    if dry:
        return

    reel.push_media(out_dir, f"{name}-he")
    reel.sh("git", "add", "posts-he", cwd=HERE)
    subprocess.run(["git", "commit", "-m", f"IG reel HE: {name}"], cwd=HERE)
    subprocess.run(["git", "pull", "--rebase", "--autostash"], cwd=HERE)
    subprocess.run(["git", "push"], cwd=HERE)
    # HE webhook key lives only in GitHub secrets -> publish via workflow
    reel.sh("gh", "workflow", "run", "ig-reel-he.yml", "-f", f"post={name}",
            cwd=HERE)
    print("publish workflow triggered for", name)


if __name__ == "__main__":
    main()
