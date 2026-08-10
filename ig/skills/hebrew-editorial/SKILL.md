---
name: hebrew-editorial
description: Israeli Hebrew editorial system for @ainews.israel — native spoken Hebrew for a 16-18yo Israeli reader, terminology glossary, correction corpus, scored editor gate. Use when writing or editing ANY Hebrew content for the page.
---

# Israeli Hebrew Media Editorial System (@ainews.israel)

Owner spec Aug 10, 2026: the page speaks the Hebrew a smart Israeli 16-18
year old actually speaks. Not translated Hebrew, not newspaper Hebrew, not
chatbot Hebrew. This skill is the editorial operating system for every
Hebrew word the machine publishes.

## Token economy (hard constraint, owner law Aug 8)

The blueprint version of this system (6 agents, multi-pass) is BANNED — it
ate the Claude plan once. The production shape is:

1. ONE writer/translator call (Sonnet) — carries the full style doctrine.
2. ONE scored native-editor call (Sonnet) — the quality gate below.
3. Code-only qa() gates (he.py) — digits, LTR islands, dashes, handles.

## The knowledge base (read before writing)

- `../../inspiration/hebrew.md` — THE style guide (register, calque
  detector, Ynet/N12 headline shapes, RTL mechanics). Single source of
  truth; never duplicate its rules here.
- `references/terminology.md` — use/avoid glossary with reasons.
- `references/examples.md` — approved vs rejected real pairs.
- `references/correction-log.md` — every owner correction, newest first.
  When a rule repeats 2+ times in the log, distill it INTO hebrew.md.

## Brand voice, operationally

We sound like: a sharp Israeli friend telling you tech news at the table —
fast, concrete, slightly provocative, zero hype.
We never sound like: a translation agency, a government announcement, a
press release, a generic AI chatbot, an ads account.

"Conversational" MEANS: short sentences; words Israelis type in WhatsApp;
technical terms explained inline in five words; no formal constructions.
"Provocative" MEANS: real tension from real facts; never fake urgency,
never exaggerated claims.

## The scored editor gate (he.py editor_pass)

Every Hebrew post is scored 1-10 before publish:

```json
{"hebrew_naturalness": 0, "grammar": 0, "clarity_16yo": 0,
 "source_fidelity": 0, "brand_voice": 0, "issues": [],
 "corrected_slides": []}
```

Publish thresholds: naturalness >= 8, grammar >= 9, fidelity >= 9,
clarity_16yo >= 8, voice >= 8. Below threshold -> the editor's corrected
text ships (single pass, no loop). The gate fails OPEN on API error — a
dead editor never kills a slot (always-post law).

## The corpus loop (how this improves)

1. Owner sees bad Hebrew live -> sends the line + how he'd say it.
2. The correction lands in `references/correction-log.md` verbatim.
3. Repeated patterns get distilled into hebrew.md / terminology.md.
4. Strong before/after pairs get promoted into examples.md.
