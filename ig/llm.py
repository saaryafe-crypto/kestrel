"""The one place the pipeline talks to Claude. CI and the Mac both use the
Claude Code CLI on the Max plan (CLAUDE_CODE_OAUTH_TOKEN in CI), no API key.
Trimmed flags keep each call ~3k tokens of overhead (measured Aug 8)."""
import json, os, re, select, subprocess, sys, time

WRITER = "claude-sonnet-4-6"   # same models as before: no cost change
JUDGE = "claude-haiku-4-5-20251001"


def call(prompt, model=WRITER, images=None, max_s=1800, tries=2):
    """Return the JSON object Claude answers with. Opus stays banned
    (token-diet lock, owner Aug 8)."""
    if "opus" in model.lower():
        raise RuntimeError("token-diet lock: Opus is banned")
    cmd = ["claude", "--model", model, "-p", prompt.replace("\x00", ""),
           "--setting-sources", "", "--disable-slash-commands",
           "--no-session-persistence"]
    if images:
        cmd += ["--tools", "Read", "--allowedTools", "Read"]
        for d in sorted({os.path.dirname(os.path.abspath(p)) for p in images}):
            cmd += ["--add-dir", d]
    else:
        cmd += ["--tools", "", "--system-prompt",
                "You are the writing and judging engine of an automated news "
                "pipeline. Follow the instructions exactly and return only "
                "the requested JSON."]
    for attempt in range(tries):
        try:
            last = _stream(cmd, max_s)
            obj = _json(last)
        except subprocess.TimeoutExpired:
            last, obj = "(timed out)", None
        if obj is not None:
            return obj
        print(f"claude -p reply had no JSON; first 300 chars: {last[:300]!r}", file=sys.stderr)
        if attempt < tries - 1:
            print("claude -p gave no JSON, retrying once", file=sys.stderr)
            time.sleep(60)
    raise RuntimeError("claude -p returned no JSON")


def _stream(cmd, max_s=1800):
    """Idle watchdog: 4 min of silence = stall; max_s hard cap."""
    cmd = cmd + ["--output-format", "stream-json", "--include-partial-messages", "--verbose"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    fd, buf, result, end = p.stdout.fileno(), b"", "", time.time() + max_s
    try:
        while True:
            left = end - time.time()
            if left <= 0 or not select.select([fd], [], [], min(240, left))[0]:
                raise subprocess.TimeoutExpired(cmd, 240)
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if isinstance(ev, dict) and ev.get("type") == "result":
                    result = ev.get("result") or ""
    finally:
        if p.poll() is None:
            p.kill()
        p.wait()
    return result


def _json(out):
    dec, best = json.JSONDecoder(), None
    for m in re.finditer(r"[\[{]", out or ""):
        try:
            obj, end = dec.raw_decode(out[m.start():])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, (dict, list)) and (best is None or end > best[1]):
            best = (obj, end)
    return best[0] if best else None


def clean(t):
    """Published-text scrub (owner rules): no em/en dashes, no spaced
    hyphens, no markdown bold."""
    t = re.sub(r"[^\S\n]*[—–][^\S\n]*", ", ", t or "")
    t = re.sub(r"(?<=\w) - (?=\w)", ", ", t)
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", t)
    return re.sub(r",\s*,", ",", t).strip()
