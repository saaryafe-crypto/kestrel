# Visual doctrine — forensic audit of the reference page's slides
Audited Jul 28 2026 from 9 owner-supplied screenshots of @technology posts
(Desktop/"example post ig"). These are the rules our slides and generated
images follow EVERY time. Operative copies of these rules live inside
write.py's IMAGE BRIEFS prompt block and genimg.py's Seedream wrapper —
if you change a rule here, change it there too.

## 1. What images they choose (and WHY)

**Evidence, not decoration.** Every image is PROOF of the headline's exact
claim, never "related imagery":
- Claim "touch screen MacBook" → a real hand physically touching the screen.
- Claim "he built an app" → the actual app UI, on a real monitor, running.
- Claim "Sony patented controllers" → the patent line-drawing overlaid on the photo.
- Claim "financed iPhones could be locked" → a phone showing "Device Locked".
The test: could a lawyer submit this image as an exhibit for the headline?
If it's just "a robot" for a robot story, it fails.

**The exact moment.** The image freezes the claim mid-action (hand ON the
screen, blade IN the page stack), not the aftermath and not the general topic.

**Real humans when a person IS the story.** The builder's smiling face on the
cover, a real hand for a touch feature. Faces stop thumbs.

**Two image classes, two treatments:**
- PHOTOS (products, people, scenes): edge-to-edge bleed, feathered into the
  black text band. One connected canvas — never a cropped card.
- SCREENSHOTS / receipts (UI, landing pages, patents, DMs): rounded-corner
  card floating on a dark ambient bokeh/glow background. Receipts must LOOK
  like receipts — crisp, rectangular, unmistakably real.

## 2. How their images are built (composition forensics)

- **Hero-product photography:** dramatic 3/4 angles, low-key dark background,
  rim/neon lighting, shallow depth of field, glossy-surface reflections.
  Never flat catalog shots, never bright-white stock.
- **One dominant color key per slide.** The background echoes the subject's
  own color (orange iPhone → orange light trails; Sony controller →
  blue/purple neon). Color harmony reads as premium; rainbow reads as cheap.
- **Layered depth:** giant typography BEHIND the product ("PRO" behind the
  MacBook), brand-silhouette shadows, badge chips (M5 MAX), sketch overlays,
  diagonal multi-photo collages for "top N" lists. At least two depth planes.
- **Dark-canvas survival:** every image must sit on / melt into #050505.
  Edges go dark; the bottom of the frame falls off into black so the feather
  into the text band is invisible.
- **NO EMPTY CANVASES (owner verdict Jul 28):** a cover whose top 65% is
  backdrop-only is "the same template running at 40% capacity" — the feed
  crop favors the top of the image, so an empty top = a black rectangle with
  zero stopping power. Every cover gets a subject. The image must also carry
  MID-TONES: pure black/white/accent with nothing in between reads flat;
  white type needs a mid-tone photograph behind it to pop against.
- **N-list covers = cut-out collage:** for "N things" promises the reference
  stacks 2-3 distinct cutout subjects, layered and overlapping with depth
  (three fighter jets for "9 MOST EXPENSIVE AIRCRAFT") — the collage IS the
  promise of N items. Single-story covers get one hero subject; list covers
  get multiple.
- **On-image text only when it IS the claim** ("Device Locked", one incoming
  message notification): 1-3 words, on a device screen, clean system font.
  Otherwise ZERO text in the image.

## 3. Seedream-4 prompt craft (model-specific, sourced Jul 28)
Sources: ByteDance/BytePlus prompt guide, Segmind, Atlabs, WaveSpeed guides.

- **Order matters:** subject → action → setting → composition → lighting →
  lens → style. Subject first, always.
- **Length:** 30-100 words total. Concise precise natural language.
- **No conflicting adjectives** ("soft yet harsh light"), no stacked ornate
  vocabulary — Seedream follows precise plain English better than word salad.
- **Text rendering (Seedream's superpower):** put the exact phrase in
  DOUBLE QUOTES and say where and how it appears: `its screen shows the
  words "Device Locked" in a clean white system font`. Never paraphrase the
  phrase, never ask for more than ~3 words.
- **Brand accuracy (Seedream's other superpower):** NAME the real device
  ("a silver MacBook Pro", "an orange iPhone"), don't say "a laptop".
- **Photorealism vocabulary that works:** cinematic rim lighting, 85mm lens,
  macro detail, shallow depth of field, ultra detailed, photorealistic.
- **Our layout constraint, stated in-prompt:** subject large in the upper
  two-thirds; the lower third falls off into pure black (the text band
  feathers over it).
- **Never make paperwork the subject (learned Jul 28):** documents, bills,
  letters, and chat threads come out filled with garbled fake text — 4/4
  such images QA-rejected in one run. Choose text-free evidence objects
  (cash, stethoscope, gavel, devices, faces); any paper in frame must be
  blank, turned away, or defocused. The one-short-quoted-phrase rule is the
  ONLY exception, and only on a device screen.

## 4. Design forensics — typography & color (added Jul 28, owner request)

Measured from the same 9 screenshots plus the @techskills money-post reference.

- **Type system:** one condensed ultra-heavy caps sans for every headline
  (our Anton). No second display face, no italic, no lowercase headlines.
  Small tracked-out caps masthead top-center with rule lines either side.
- **Two-color alternation BY LINE, not by word (owner verdict Jul 28):** the
  reference puts blue on ENTIRE lines ("THE 9 MOST" white / "EXPENSIVE
  MILITARY" blue / "AIRCRAFT EVER BUILT" mixed-block) — that creates rhythm
  and a reading order. Accent = ONE contiguous phrase, ideally a whole line,
  two groups absolute max. Blue scattered across four single words is
  confetti: four competing focal points = zero focal points.
- **Cover word budget (owner flip Aug 1, reference-page audit — reverses
  the Jul 29 gap cap):** 12-25 words, one complete summarizing sentence
  breaking edge-to-edge into 4-6 tight condensed lines (hsize 58-70; the
  renderer's 400px block cap keeps it from towering). The whole story with
  its numbers goes ON the cover, @technology style; the slides deliver
  the photos, depth and fallout.
- **Brand color (FINAL owner call Jul 28 evening, reversing the same-day
  blue switch): white + orange #D97757 on black.** Accents are SOLID orange
  (no glyph texture); masthead is the real white wordmark (art/wordmark.png),
  never tinted. The blue-sky texture era lasted less than a day.
- **Measured cover geometry (Jul 29, AVERAGE of 5 owner screenshots in
  Desktop/ig/technology ig):** headline glyphs 7.0% of canvas height (range
  5-10.7% — short lines render BIGGER), line pitch 7.7%, side margins 1-3%
  of width, photo hard edge 45-54% down, headline top ~61.5%, last text
  bottom ~92%, substrip glyphs 3.0-3.2% centered (~70% width), swipe pill
  center 94%. Encoded in render.py CSS + FIT_JS.
- **EVERY headline line runs edge-to-edge** — their signature. The renderer
  (FIT_JS) greedy-wraps at base size then scales each line's font to fill
  the frame width, clamped at 1.18x with orphan-word rebalance and a total
  block cap of ~25% canvas height (guards added Jul 29 after a 6-line cover
  towered over 60% of the canvas). The substrip never wraps: it shrinks to
  stay one centered line.
- **Comment-gate CTA (seen on their app posts):** "COMMENT "APP" TO GET THE
  FULL SET UP!" as huge type over the receipt screenshot — a comment-keyword
  gate that farms comments. Candidate pattern for our edu/prompt posts.
- **List inner slide:** photo top + huge 2-line header + TWO-COLUMN italic
  bullet list ("EVERY FEATURE REPORTED SO FAR") — how they fit 10 short
  facts on one slide without mush.
- **All-caps simplicity sells the story:** the @techskills reference ("A
  20-YEAR-OLD CHINESE STUDENT SPENT $20 ON CLAUDE, BUILT AN AI SPEED RADAR
  IN 9 DAYS, AND SOLD IT FOR $317K") is one plain-English sentence, all caps,
  zero jargon — the typography does the shouting, the words stay simple.
- **Celebrity-still composite covers** (the "PEOPLE ARE LETTING CLAUDE TRADE
  FOR THEM" pattern): a world-famous movie still that embodies the emotion
  (Wolf of Wall Street holding cash = money) + the AI tool's logo + the
  product's logo placed cleanly beside it. Borrowed fame + real logos =
  instant story. Use when the story is "people are using X to do Y" and no
  literal photo of the doer exists. Logos must be the real marks, composited
  cleanly, never distorted.
- **Authority-face covers:** for company-secrets stories, a stylized cool
  cinematic portrait of the famous founder/CEO (reference: "SECRET CODES FOR
  CLAUDE..." over an Anthropic-CEO hero shot). The face must belong to the
  company in the claim — a real, recognizable person, shot like a movie
  poster (low-key, rim light, dark canvas), never a generic stock human.

## 4b. Attention science — researched Aug 1 2026 (primary sources)
Sources: Netflix published artwork A/B research (82% of browse attention on
imagery, ~1.8s/title), leaked MrBeast production doc, Paddy Galloway
3-element rule, thumbnail CTR corpora. Operative copies live in write.py's
art_direct prompt.

- **One focal point per cover.** The eye must land in under 1 second; two
  competing subjects = zero subjects. Max 3 elements total: subject,
  secondary prop, headline block.
- **Max 2 people in frame** (Netflix: engagement drops at 3+).
- **Faces earn ~47% more clicks — but only expressive ones.** When a person
  is the story their face fills 30-45% of cover width, emotion exaggerated
  ONE notch past realistic (shock, glee, dread). Neutral reads as nothing at
  feed size. Villain/polarizing framings over-index (Netflix).
- **Gaze is an arrow.** Direct eye contact by default (first fixation for
  ~65% of 18-34s); break it only to aim the subject's gaze AT the headline.
- **Complementary contrast at thumbnail size:** subject lit warm (orange)
  against cool/dark ground, ≥4.5:1 contrast — decisions happen
  preconsciously in 100-150ms, single-source rim-light drama reads fastest.
- **Three cover anatomies, rotated** (never the same twice in a row):
  (a) person-holds-product — waist-up, product chest-high angled to camera;
  (b) glowing-logo backdrop — real cutout centered, brand mark huge and
  softly glowing behind the head; (c) absurd-object hero — the thing itself
  at 50-60% of frame, slightly low-angle, no humans.
- **Generation is iterative, never one-shot.** Famous faces/branded devices:
  pass the REAL photo as reference (image_input) and demand identity match;
  regenerate on mismatch. Likeness/logo failures kill credibility.
- **Inner-slide variety sustains swipes:** alternate media types (real photo
  → screenshot/receipt → generated scene), never two identical layouts
  back-to-back; 70%+ slide-viewed rate earns 3-5x non-follower distribution.
- **Slide 2 gets its own strong image** — Instagram re-serves the post
  opening on slide 2, so it must work as a second cover, not a text slab.

## 5. Division of labor
The writer's `image_brief` = subject + action + setting + one color key
(15-40 words, the evidence scene). genimg.py's wrapper appends the fixed
composition / lighting / lens / text-rule block so every prompt lands in
Seedream's optimal 5-part structure without the writer repeating boilerplate.

## 6. Concept-first covers — the Creative Director doctrine (Aug 9 2026, ported from the owner's build)

Built on the owner's two reference covers, which ARE the spec:
1. **PowerPoint's funeral** — Dario Amodei comforting a sobbing Bill Gates
   beside a coffin with the PowerPoint logo framed on it, for a "Claude
   replaces PowerPoint" story. A staged symbolic scene that transmits the
   story with zero reading, cast with the real leaders of the two companies.
2. **Zendaya studying** — for a "Gemini predicts exam questions" story,
   cast BECAUSE The Odyssey was viral that week (the culture-cast move).

**The reversal:** metaphor is LEGAL on COVERS ONLY (owner order Aug 9 —
the old "never a metaphor" rule buried both reference covers). Inner
slides stay literal evidence of their own claim, faces stay famous-only.

**The lanes** (art_direct picks the strongest, varies across posts):
- **SYMBOLIC SCENE** — the story's meaning staged as ONE theatrical,
  photographically real moment: product replaced → its funeral; company
  beaten → the knockout; era over → the retirement party. Shot as a
  documentary press photo, never illustration.
- **CULTURE CAST** — a currently-hot celebrity performing the story's
  action. Fed by `culture.py`: ONE web-search Sonnet call per day (lazy
  24h refresh into culture.json, fails open to stale/empty — a slot is
  never blocked by a dead radar). Cast only on instant natural fit.
- **LOGO AS HERO** — fame-bar fallback: famous company, no famous face →
  the famous logo itself is cast in the story's role (golden Octocat on a
  throne of cash for a GitHub-repos-make-money story). Humans faceless.
- The pre-existing lanes (story's own absurd visual, ROLE-CAST,
  PRODUCT-HERO, CLASH-CAST, SITUATION PORTRAIT) stay and win when stronger.

**The fame bar** (owner, Aug 9): cast a human ONLY if a random 20-year-old
recognizes the FACE without a caption (Musk/Gates/Altman tier). A famous
company does NOT make its CEO famous. No qualifying face → no generated
face at all.

**Retry rule:** person-route covers rewrite between attempts with
`simpler_brief(mode="concept")` — keep the staged scene and every named
face, strip only the judge's named flaw. The retry must never dissolve
the funeral into a plain portrait. The judge (`image_score`) counts a
symbolic staging that transmits the story as ON-claim.

**Token rule** (owner: "token economy is EXTREMELY important"): zero new
per-post calls — all concept thinking happens inside the single existing
art_direct call. The only recurring addition is the one culture-refresh
web call per day.

**Cast truth** (owner post-mortem, Aug 10 — the Sam Altman content-vendor
cover): passing the fame bar is NOT enough. A famous face is legal only
when that person or their company is an ACTOR in THIS story — named in
the topic/headlines, or the story is about their product or move. "The
topic is AI" is not a connection: generic how-to / prompts / edu stories
that name no company get NO celebrity. When only the tool is famous
(ChatGPT, Claude, Gemini), its LOGO AS HERO or an evidence-object scene
with faceless humans carries the cover. Enforced in three places:
art_direct doctrine, image_score's cast-truth gate ("famous face
unrelated to the story" → concept retry RECASTS instead of preserving
the cast), and editor gate B, which now receives the actual cover image
path so the editor judges the rendered cover with its own eyes.

**No-face playbook** (owner order, Aug 10 — the "what TO DO" twin of cast
truth): when no famous person belongs to the story, the cover goes just as
big and provocative through four lanes: LOGO AS HERO acting the story's
verb at theatrical scale (Octocat raking in poker chips — never a logo
just sitting there); SYMBOLIC SCENE staged faceless (mourners from
behind, hands lowering the coffin); IMPOSSIBLE SCALE (the story's real
object at absurd size in a real place); CAUGHT EVIDENCE (the forbidden
backstage moment, objects only, faceless shoulders). Every no-face cover
still passes the stop test. "Fall back to objects" NEVER means a calm
product shot — if the object isn't mid-action or at impossible scale,
escalate the scene.
