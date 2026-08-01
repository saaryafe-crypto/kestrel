#!/usr/bin/env python3
"""Sends a rendered post to the Make.com webhook, which publishes the
carousel to Instagram (Make's approved Meta app does the Graph API work).
Usage: MAKE_WEBHOOK_URL=... python3 post.py posts/<dir> <base_url>
base_url = public URL prefix where the slide PNGs are reachable, e.g.
https://raw.githubusercontent.com/saaryafe-crypto/kestrel-media/main/<name>
Payload: {"caption": str, "images": [url, ...]}  (slide order preserved)"""
import json, os, re, sys, time, urllib.request


def urls_live(urls, min_bytes=15000):
    """Refuse to publish media Meta can't fetch (Jul 31 root-cause: posts went
    live with missing covers because the webhook fired while the media-repo
    push hadn't landed — raw.githubusercontent 404'd and the scenario shipped
    what it had). Retries cover CDN propagation lag; a final miss aborts the
    publish so the workflow fails loud instead of posting broken."""
    for u in urls:
        for attempt in range(6):
            try:
                req = urllib.request.Request(u, method="HEAD")
                with urllib.request.urlopen(req, timeout=30) as r:
                    if int(r.headers.get("Content-Length") or 0) >= min_bytes:
                        break
                    print(f"{u}: live but suspiciously small "
                          f"({r.headers.get('Content-Length')} bytes)", file=sys.stderr)
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
        p = json.load(open(os.path.join(post_dir, "post.json")))
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


def send(payload):
    headers = {"Content-Type": "application/json"}
    if os.environ.get("MAKE_API_KEY"):
        headers["x-make-apikey"] = os.environ["MAKE_API_KEY"]
    req = urllib.request.Request(
        os.environ["MAKE_WEBHOOK_URL"], data=json.dumps(payload).encode(),
        headers=headers)
    # Once the Make scenario ends with a "Webhook response" module, this reply
    # arrives AFTER the IG publish and carries its real result. Non-2xx raises
    # (workflow fails -> alert issue); an error-ish body fails the same way.
    with urllib.request.urlopen(req, timeout=300) as r:
        body = r.read().decode()
        print("webhook response:", body[:300])
    if re.search(r"error|exception|invalid|denied", body, re.I):
        raise SystemExit(f"Make reported a publish error: {body[:500]}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
