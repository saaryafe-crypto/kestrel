#!/usr/bin/env python3
"""Daily pop-culture radar for the cover art director (ported Aug 9 from the
Creative Director build).

The Zendaya move — casting her for a Gemini-study story BECAUSE The
Odyssey is viral that week — needs knowledge of who is culturally hot
RIGHT NOW, which no model's training data has. get() keeps culture.json
fresh with ONE web-search Claude call per day (owner token rule: this is
the only recurring call the culture lane adds; Sonnet — the writer model,
Opus stays banned — because search+summarize needs no more than that).
Fails open to the stale file or an empty list — a posting slot is never
blocked by a dead radar. Stdlib only."""
import json, os, sys, time
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
FILE = os.path.join(HERE, "culture.json")
MAX_AGE = 24 * 3600

SCHEMA = {"type": "object", "properties": {
    "hot": {"type": "array", "items": {"type": "object", "properties": {
        "name": {"type": "string"},
        "why_hot_now": {"type": "string"},
        "typical_scene": {"type": "string"}},
        "required": ["name", "why_hot_now"]}},
    "memes": {"type": "array", "items": {"type": "string"}},
    "ai_flagships": {"type": "array", "items": {"type": "string"}}},
    "required": ["hot"]}

PROMPT = """Search the live web for what is culturally viral RIGHT NOW (this week) among 20-30 year olds in the US: celebrities having a moment (a #1 movie or show, a tour, an award, a viral clip), plus the biggest current memes/trends. Today is {today}.

Return 8-12 "hot" entries. Each:
- "name": the person (or show/movie ONLY if it's bigger than any person in it). Must be instantly recognizable to a random 20-year-old — if they'd need to google the name, leave it out.
- "why_hot_now": why THIS week, in one short sentence with the specific thing (the movie, the tour, the moment).
- "typical_scene": the visual situation people associate with them right now, 5-12 words (e.g. "studying epic poetry", "courtside in a suit").

Also "memes": 3-8 one-line descriptions of current viral memes/formats.
Also "ai_flagships": the CURRENT newest flagship AI model of each major lab (Anthropic, OpenAI, Google, xAI, Meta) as of today — exact released product names only, one string each. Training data is months stale here AND most articles lag: a flagship can be days old, so search each lab's latest announcement specifically (e.g. "Anthropic newest model {month_year}") rather than trusting roundup pages; if a brand-new name supersedes the one you expected, the new name is the answer.
Only include what is genuinely current — an entry from last year's news is worse than fewer entries. Return ONLY JSON."""


def get():
    """Hot-culture list for casting; refreshes at most once per 24h."""
    data = {}
    if os.path.exists(FILE):
        try:
            data = json.load(open(FILE))
        except Exception:
            data = {}
    if data and time.time() - data.get("ts", 0) < MAX_AGE:
        return data.get("hot", [])
    try:
        from write import call_claude, MODEL
        r = call_claude(PROMPT.format(today=date.today().strftime("%B %d, %Y"),
                                      month_year=date.today().strftime("%B %Y")),
                        schema=SCHEMA, model=MODEL, web=True)
        hot = [h for h in r.get("hot", []) if h.get("name", "").strip()][:12]
        # the model sometimes returns flagships as {"Anthropic": "..."}
        # despite the array schema — a dict[:6] here killed the whole
        # refresh (KeyError(slice)), taking the hot list down with it
        flags = r.get("ai_flagships") or []
        if isinstance(flags, dict):
            flags = list(flags.values())
        flags = [str(x).strip() for x in flags if str(x).strip()][:6]
        if hot:
            json.dump({"ts": time.time(), "updated": str(date.today()),
                       "hot": hot, "memes": r.get("memes", [])[:8],
                       "ai_flagships": flags},
                      open(FILE, "w"), indent=1, ensure_ascii=False)
            print(f"culture radar refreshed: {len(hot)} entries", file=sys.stderr)
            return hot
    except Exception as e:
        print(f"culture radar refresh failed ({e}) — using stale/empty",
              file=sys.stderr)
    return data.get("hot", [])


def flagships():
    """Today's flagship AI model names (owner lesson Aug 16: the cigar-meme
    reel copied 'Opus 4.8' from a 2.6-month-old tweet when the flagship was
    already Fable — old clips carry superseded model names, and no model's
    training data knows today's lineup). Fails open to []."""
    get()  # refresh at most once per 24h; fails open to the stale file
    try:
        return [f for f in json.load(open(FILE)).get("ai_flagships", [])
                if f.strip()]
    except Exception:
        return []


if __name__ == "__main__":
    if "--fresh" in sys.argv and os.path.exists(FILE):
        try:  # expire, don't delete — the stale file stays as the fail-open floor
            d = json.load(open(FILE)); d["ts"] = 0; json.dump(d, open(FILE, "w"))
        except Exception:
            os.remove(FILE)
    for h in get():
        print(f"- {h.get('name')}: {h.get('why_hot_now')} "
              f"[{h.get('typical_scene', '')}]")
