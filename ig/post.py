#!/usr/bin/env python3
"""Sends a rendered post to the Make.com webhook, which publishes the
carousel to Instagram (Make's approved Meta app does the Graph API work).
Usage: MAKE_WEBHOOK_URL=... python3 post.py posts/<dir> <base_url>
base_url = public URL prefix where the slide PNGs are reachable, e.g.
https://raw.githubusercontent.com/saaryafe-crypto/kestrel-media/main/<name>
Payload: {"caption": str, "images": [url, ...]}  (slide order preserved)"""
import json, os, re, sys, time, urllib.request

GMAIL = "saaryafe@gmail.com"  # owner monitor address (order Sep 8)


def urls_live(urls, min_bytes=15000):
    """Refuse to publish media Meta can't fetch (Jul 31 root-cause: posts went
    live with missing covers because the webhook fired while the media-repo
    push hadn't landed — raw.githubusercontent 404'd and the scenario shipped
    what it had). Retries cover CDN propagation lag; a final miss aborts the
    publish so the workflow fails loud instead of posting broken."""
    for u in urls:
        for attempt in range(6):
            try:
                # Full GET, not HEAD (Aug 11 root-cause: 8 valid JPEGs passed
                # HEAD, then IG's own fetch hit a cold raw.githubusercontent
                # edge and errored 9004 "Only photo or video can be accepted").
                # A real GET warms the CDN edge and lets us verify the bytes.
                with urllib.request.urlopen(u, timeout=60) as r:
                    body = r.read()
                    if u.endswith(".jpg") and body[:2] != b"\xff\xd8":
                        raise SystemExit(f"{u}: served {len(body)} bytes that "
                                         "are NOT a JPEG — refusing to publish")
                    if len(body) >= min_bytes:
                        break
                    print(f"{u}: live but suspiciously small "
                          f"({len(body)} bytes)", file=sys.stderr)
            except Exception as e:
                print(f"{u}: not live yet ({e}), attempt {attempt + 1}/6",
                      file=sys.stderr)
            if attempt == 5:
                raise SystemExit(f"media never became reachable: {u} — "
                                 "refusing to publish without its image")
            time.sleep(20)


def alert_bare_cover(post_dir):
    """Never-silent rule (owner Aug 1, Chrome-bugs post-mortem: 'i wasnt even
    notifed'): a cover with no photo — bare type or logo-on-dark — still
    publishes (7/day is a must) but ALWAYS opens a GitHub issue so the owner
    can pull it and we can fix the starved rung. Fails open: an alert failure
    never blocks the publish."""
    try:
        # HE post dirs carry post-he.json (he.py output) — before this
        # fallback the whole HE channel silently skipped the alarm.
        pj = os.path.join(post_dir, "post.json")
        if not os.path.exists(pj):
            pj = os.path.join(post_dir, "post-he.json")
        p = json.load(open(pj))
        cover = (p.get("items") or p.get("slides") or [{}])[0]
        problem = ("no cover image at all" if not cover.get("media") else
                   f"cover fallback: {p['cover_fallback']}" if p.get("cover_fallback")
                   else None)
        if not problem:
            return
        import subprocess
        name = os.path.basename(post_dir.rstrip("/"))
        subprocess.run(
            ["gh", "issue", "create", "-R", "saaryafe-crypto/kestrel",
             "-t", f"IG post shipped with BARE COVER: {name}",
             "-b", f"{problem}\n\nHeadline: {cover.get('headline')}\n"
                   "The post published (7/day rule) but the cover has no real "
                   "photo — likely genimg budget/API starvation or zero "
                   "article images. Owner may want to delete it from the grid."],
            timeout=60, check=False)
        print(f"BARE COVER ALERT raised for {name}: {problem}", file=sys.stderr)
    except Exception as e:
        print(f"bare-cover alert failed ({e}) — publishing anyway", file=sys.stderr)


def notify_owner(post_dir, base_url=None):
    """Owner monitor email (owner order Sep 8: "everytime you post something
    new i get an email... 1. what was posted? reel/carousel and what was the
    prompt and the journey of why you did what you did", then "colorful and
    easy to read" — color-coded HTML, banner first, the shipped cover
    embedded). Sent AFTER a successful publish, to saaryafe@gmail.com via
    Gmail SMTP. Fails open: a mail hiccup never fails a publish."""
    try:
        pw = re.sub(r"\s+", "", os.environ.get("GMAIL_APP_PASSWORD", ""))
        if not pw:
            print("notify: GMAIL_APP_PASSWORD not set, skipping", file=sys.stderr)
            return
        import html as H
        name = os.path.basename(post_dir.rstrip("/"))
        base = (base_url or "").rstrip("/")
        # sections = (label, text, color); rendered as colored cards + plain text
        sections, title = [], name
        kind, img_url = "carousel", (f"{base}/slide-1.jpg" if base else None)
        rj = os.path.join(post_dir, "reel.json")
        if os.path.exists(rj):
            r = json.load(open(rj))
            kind, img_url = "reel", None
            title = (r.get("caption") or "").split("\n")[0][:80]
            sections.append(("CAPTION", (r.get("caption") or "")[:600], "#2563eb"))
            sections.append(("SOURCE", str(r.get("source") or r.get("credit")
                             or r.get("link") or "not recorded"), "#64748b"))
            sections.append(("JOURNEY", "Clip picked from the viral X pool, "
                             "cut and captioned by reel.py, published via "
                             + ("native IG audio bundle" if r.get("publish") == "bundle"
                                else "Make webhook") + ". Reels carry no "
                             "generated image, so there is no image prompt.",
                             "#16a34a"))
        else:
            pj = os.path.join(post_dir, "post.json")
            if not os.path.exists(pj):
                pj = os.path.join(post_dir, "post-he.json")
            p = json.load(open(pj))
            slides = p.get("items") or p.get("slides") or [{}]
            cover = slides[0]
            title = re.sub(r"<[^>]+>", "", cover.get("headline") or "")[:80]
            kind = f"carousel ({p.get('container', '?')}, {len(slides)} slides)"
            sections.append(("COVER HEADLINE", title, "#2563eb"))
            story = p.get("story") or {}
            if story:
                sections.append(("SOURCE STORY",
                                 str(story.get("title", ""))[:200] + "\n"
                                 + str(story.get("link", "")), "#64748b"))
            # the EXACT prompt sent to the model (genimg sidecar); the brief
            # from post.json is the fallback for older posts
            prompt = None
            media = cover.get("media") or ""
            sidecar = os.path.join(post_dir, os.path.basename(media) + ".prompt.txt")
            if media and os.path.exists(sidecar):
                prompt = open(sidecar).read()
            if prompt:
                sections.append(("FULL IMAGE PROMPT (exactly as sent to the "
                                 "model)", prompt, "#7c3aed"))
            elif cover.get("image_prompt"):
                sections.append(("IMAGE BRIEF (writer's cover brief; the "
                                 "frozen scaffold in genimg.py rides on top)",
                                 cover["image_prompt"], "#7c3aed"))
            else:
                sections.append(("IMAGE PROMPT", "None. The cover is "
                                 + ("a real article/press photo, not generated."
                                    if media else "BARE (no picture). Check "
                                    "the bare-cover alert issue."),
                                 "#7c3aed" if media else "#dc2626"))
            journey, clean = [], True
            if p.get("cover_fallback"):
                clean = False
                journey.append("Cover fallback: " + str(p["cover_fallback"]))
            if p.get("editor_override"):
                clean = False
                journey.append("Editor gate B rejected, but the never-skip "
                               "floor shipped it flagged: "
                               + str(p["editor_override"])[:500])
            if p.get("gate_r"):
                clean = False
                journey.append("Vision gate R dropped or flagged images: "
                               + str(p["gate_r"])[:500])
            if clean:
                journey.append("Clean run: passed the text gate and the "
                               "vision gate with no overrides.")
            sections.append(("JOURNEY", "\n".join(journey),
                             "#16a34a" if clean else "#ea580c"))
        # build both bodies from the same sections
        text = f"POSTED: {kind}\n{title}\n\n" + "\n\n".join(
            f"{label}:\n{body}" for label, body, _ in sections)
        cards = "".join(
            f'<div style="border-left:6px solid {c};background:#f8fafc;'
            f'border-radius:8px;padding:12px 16px;margin:12px 0">'
            f'<div style="font-weight:bold;color:{c};font-size:13px;'
            f'letter-spacing:.5px">{H.escape(label)}</div>'
            f'<div style="color:#0f172a;font-size:15px;white-space:pre-wrap;'
            f'line-height:1.5">{H.escape(body)}</div></div>'
            for label, body, c in sections)
        img = (f'<img src="{H.escape(img_url)}" alt="cover" style="width:100%;'
               'max-width:420px;border-radius:12px;display:block;margin:14px 0">'
               if img_url else "")
        htm = (f'<div style="font-family:Arial,Helvetica,sans-serif;'
               f'max-width:640px;margin:auto">'
               f'<div style="background:#16a34a;color:#fff;border-radius:10px;'
               f'padding:14px 18px;font-size:18px;font-weight:bold">'
               f'POSTED: {H.escape(kind)}</div>'
               f'<div style="font-size:20px;font-weight:bold;color:#0f172a;'
               f'margin:14px 0 4px">{H.escape(title)}</div>'
               f'{img}{cards}</div>')
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(text))
        msg.attach(MIMEText(htm, "html"))
        msg["Subject"] = f"[yaffeai] posted: {title}"
        msg["From"] = msg["To"] = GMAIL
        last = None
        for attempt in range(3):
            try:
                if attempt % 2 == 0:
                    s = smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60)
                else:
                    s = smtplib.SMTP("smtp.gmail.com", 587, timeout=60)
                    s.starttls()
                with s:
                    s.login(GMAIL, pw)
                    s.send_message(msg)
                print("notify: owner email sent", file=sys.stderr)
                return
            except Exception as e:
                last = e
        print(f"notify: email failed after retries ({last})", file=sys.stderr)
    except Exception as e:
        print(f"notify failed ({e}) — publish already succeeded", file=sys.stderr)


def main(post_dir, base_url):
    reel = os.path.join(post_dir, "reel.json")
    if os.path.exists(reel):
        r = json.load(open(reel))
        urls_live([f"{base_url.rstrip('/')}/reel.mp4"], min_bytes=100000)
        if r.get("publish") == "bundle":  # native IG audio route
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import bundle
            try:
                post = bundle.publish_reel(r["caption"],
                                           f"{base_url.rstrip('/')}/reel.mp4",
                                           audio_id=r.get("audio_id"))
                print("bundle post:", post.get("id"), "| audio:", r.get("audio_title"))
                notify_owner(post_dir, base_url)
                return
            except Exception as e:
                print(f"bundle publish failed ({e}) — falling back to Make",
                      file=sys.stderr)
        # Make reel route RESTORED Aug 1 (owner: "we can use make.com like we
        # always did" — free, unlimited, feeds the 4/day cadence). Safe now:
        # the scenario's CreateAReelPost module was patched via the Make API
        # to share_to_feed=false and verified — reels stay OFF the main grid.
        payload = {
            "type": "reel",
            "caption": r["caption"],
            "video_url": f"{base_url.rstrip('/')}/reel.mp4",
            "thumb_offset": 0,
        }
        send(payload)
        notify_owner(post_dir, base_url)
        return
    slides = sorted((f for f in os.listdir(post_dir)
                     if re.fullmatch(r"slide-\d+\.jpg", f)),
                    key=lambda f: int(re.search(r"\d+", f).group()))
    if len(slides) < 2:  # IG carousels need >=2 — a lone/missing slide is a broken render
        raise SystemExit(f"only {len(slides)} slide jpg(s) in {post_dir} — not publishing")
    alert_bare_cover(post_dir)
    base = base_url.rstrip("/")
    # video-in-carousel (owner Jul 31): a video-N.mp4 in the post dir becomes
    # a VIDEO child right after slide N (that slide's swipe hint says "Full
    # video next"). The Make scenario maps media_type per item.
    files, vids = [], []
    for f in slides:
        files.append({"media_type": "IMAGE", "image_url": f"{base}/{f}"})
        n = int(re.search(r"\d+", f).group())
        v = f"video-{n}.mp4"
        if os.path.exists(os.path.join(post_dir, v)) and len(files) < 10:
            files.append({"media_type": "VIDEO", "video_url": f"{base}/{v}"})
            vids.append(f"{base}/{v}")
    urls_live([f["image_url"] for f in files if "image_url" in f])
    if vids:
        urls_live(vids, min_bytes=100000)
    payload = {
        "caption": open(os.path.join(post_dir, "caption.txt")).read(),
        "files": files[:10],  # IG carousel hard cap
    }
    send(payload)
    notify_owner(post_dir, base_url)


def send(payload, tries=3):
    """Retry ladder on Make/IG 5xx (Aug 10 16:31 + Aug 11 18:52: two slots
    died on transient IG-side errors at the carousel module). Safe to re-fire:
    the scenario's error branch only answers 500 when the IG module errored
    and rolled back — nothing was published. Non-5xx errors don't retry."""
    for attempt in range(tries):
        try:
            return _send_once(payload)
        except SystemExit as e:
            retryable = "HTTP 5" in str(e) or "publish failed" in str(e)
            if attempt == tries - 1 or not retryable:
                raise
            print(f"publish attempt {attempt + 1}/{tries} failed ({e}) — "
                  "retrying in 120s", file=sys.stderr)
            time.sleep(120)


def _send_once(payload):
    headers = {"Content-Type": "application/json"}
    if os.environ.get("MAKE_API_KEY"):
        headers["x-make-apikey"] = os.environ["MAKE_API_KEY"]
    req = urllib.request.Request(
        os.environ["MAKE_WEBHOOK_URL"], data=json.dumps(payload).encode(),
        headers=headers)
    # Once the Make scenario ends with a "Webhook response" module, this reply
    # arrives AFTER the IG publish and carries its real result. Non-2xx raises
    # (workflow fails -> alert issue); an error-ish body fails the same way.
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            body = r.read().decode()
            print("webhook response:", body[:300])
    except urllib.error.HTTPError as e:
        # Make's error branch answers 500 with the REAL Instagram error in
        # the body ("Error: IG carousel publish failed: <message>"). The Aug
        # 10 16:31 failure died as a bare "HTTP Error 500" because urllib
        # discards the body on raise — surface it or we debug blind.
        detail = ""
        try:
            detail = e.read().decode()[:500]
        except Exception:
            pass
        raise SystemExit(f"Make webhook HTTP {e.code}: {detail or e.reason}")
    if re.search(r"error|exception|invalid|denied", body, re.I):
        raise SystemExit(f"Make reported a publish error: {body[:500]}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
