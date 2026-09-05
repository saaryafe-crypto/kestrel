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
  **Second legal source — THE DOMAIN ICON (owner reference, Aug 12):**
  a stocks guide covered with DiCaprio's Wolf of Wall Street, because
  stocks→Wall Street→that movie is the chain a 20-year-old's brain runs
  unprompted. When the story's DOMAIN has one timeless movie/culture icon
  that IS its symbol, cast the iconic character in their signature scene
  living this story. Test = INTUITION SPEED: say the topic, the icon must
  appear by itself; a link that needs explaining fails. Domain icons need
  no current-week heat — permanence IS the fit (culture.json not required).
  HARD LIMIT (owner, Aug 12): domain icons cover TOPIC posts (guides,
  roundups) with no real protagonist ONLY. A news story about a named
  person/company casts its own actors — a Leopold Aschenbrenner fund
  story never gets the Wolf of Wall Street because funds smell like
  Wall Street. Cast truth always outranks the domain icon.
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

**Iconic-moment exception** (owner, Aug 10, same conversation as cast
truth): inspirational / entrepreneurial stories MAY cast a famous founder
even when the news isn't about them — if the scene is that person's KNOWN
iconic real moment and the moment embodies the title's exact meaning
(young Zuckerberg coding in his dorm room for a "built from nothing"
promise; garage-era Jobs and Wozniak for a two-people-and-an-idea story).
The test: a stranger instantly reads why THIS person in THIS scene proves
THIS title. A famous face merely signaling "AI"/"tech" still fails.

**THE VENDOR CAST** (owner's reference wall, Aug 12 2026 — 7 screenshots in
~/Desktop/"Great cover images", studied one by one; this superseded the
Aug 10 reading of cast truth that had banned faces on prompts/edu guides
and collapsed covers into rejected symbol-on-background briefs):
a guide about USING a named famous tool IS that vendor's story. The
vendor's famous CEO is legal and casting them is the DEFAULT for guide
covers — as the tool's own delighted USER, mid-performing the READER's
exact action with the guide's real prop, one peak emotion:
- Dario Amodei proudly holding HIS OWN resume ("upload your resume to
  Claude, it will uncover positions..." guide) — the prop carries the
  story, his own name on the CV is the wit.
- Dario, Hawaiian shirt, grinning over a boarding pass with a red
  DISCOUNTED stamp ("Claude changed the game in buying airline tickets").
- Sundar Pichai leaning out of a helicopter showering Gemini sparks onto
  a crowd of reaching hands ("Google giving Gemini Pro away free") — the
  scene ACTS the headline's verb (giving away) at theatrical scale.
- Zendaya writing exam notes (Gemini-predicts-exams story) — CULTURE CAST
  when the celebrity is viral that week and the fit is instant.
- Eight tech CEOs as mourners around a "RIP CLAUDE" plaque — group
  symbolic scene; the plaque is a legal 1-3 word text prop.
Tool→face map: ChatGPT→Sam Altman, Claude→Dario Amodei, Gemini→Sundar
Pichai, Grok→Elon Musk, Copilot→Satya Nadella, Llama→Mark Zuckerberg.
The model the guide's prompts run on counts even when the headline only
says "AI prompts". What stays banned: a famous AI face as decoration on a
story that names no company AND no tool (the original Altman
content-vendor post-mortem).

**Cover text prop exception** (Aug 12, from the same references): covers
render on gpt-image which writes short text cleanly — ONE prop may carry
ONE bold 1-3 word text element when that text IS the punchline ("RIP
CLAUDE" plaque, "DISCOUNTED" stamp), quoted exactly in the brief. Never a
sentence, never on inner slides (Seedream garbles); QA rejects garble.

**Frame law** (owner Aug 14: "the best accounts create the picture on the
upper half and the picture is enough — they don't cut it in the middle"):
every generated image displays in a roughly SQUARE window at the TOP of the
slide, bottom fifth feathered into black. Generate square (Seedream 2048sq,
gpt-image 1:1) and compose complete FOR that window: waist-up or tighter,
faces and props in the upper two-thirds, nothing essential in the bottom
quarter or clipped by the sides, never full-body or tall vertical scenes.
Judge enforcement: image_score CROP-SURVIVAL GATE rejects compositions that
stop reading when the bottom quarter is hidden. Renderers anchor photos
center-top so residual crop always comes off the bottom, never the face.

**Composite staging** (reference-folder audit Aug 14, ~/Desktop/ig/technology
ig — measured on every cover: Elon chest-up + giant Tesla logo disc + memo
icon; MacBook floating whole over huge "PRO" letters; Sam Altman waist-up
holding the keyboard, glowing OpenAI logo behind): the winning covers are
BUILT composites, not single photos. ONE complete subject (whole device,
whole prop, person waist-up) arranged with 1-2 supporting elements (brand
mark, one story icon) on a DARK backdrop that fades toward the bottom edge.
Nothing is ever amputated by a frame edge — a complete object on dark reads
designed; a cropped photo reads broken. Inner-slide corollary: when a slide
shows a real screenshot/UI, the reference treatment is the COMPLETE artifact
as a floating card on dark, never an edge-to-edge crop (not wired yet — we
generate photos, no real-screenshot lane).

## 7. THE COVER ARCHETYPES — the 30-cover forensic audit (Sep 4-5 2026, owner order)

The Sep 4 "brutal collage" was built from ONE reference cover (Bernie). The
owner then dropped THIRTY covers from the reference page (3 grid screenshots
in ~/Desktop/"optimal 1", tiles archived mentally here) and ordered the real
principle extracted: **the page has no single image formula — it picks the
picture by asking "what would PROVE this headline in half a second", then
builds that proof as a saturated photoreal composite.** The picture is always
the story's PROOF or its CONSEQUENCE staged, never decoration.

### The story→picture map, cover by cover

| Story | Picture | Why that picture |
|---|---|---|
| Nvidia DLSS 5 launches with NBA 2K27 | same game frame twice, chips "DLSS 5 Off/On" + arrows | before/after IS the product's whole claim |
| Tesla Cybercab launches, undercuts Uber | real product photo, doors up, real street | the object itself is the shock; add nothing |
| OpenAI builds AI "kill switch" | plain close-up of a worried Altman, dark grade | the story is fear at the top; the face carries it |
| China puts scientists on billboards | real subway photo + round flag inset + arrow | "this is really happening" needs raw evidence |
| DLSS 5 leaked, modders using it | game face vs game face, "DLSS 4.5"/"DLSS 5" labels | comparison — labels argue, eye spot-the-differences |
| iPhone 18 Pro color lineup | exec cutout between two GIANT phones | person for trust + the products as the news |
| GTA VI limited controllers | the game's own character holding the real controllers | product presented by its own famous world |
| Dyson $499 AI toothbrush | products + circular zoom bubbles on each feature | a weird gadget sells on its features, zoomed |
| OpenAI GPT-6 Astra | real Altman seated + one galaxy inset bubble | launch with nothing to show → face + one symbol |
| Pixel vs iPhone vs Galaxy | three phones, flaming "VS" between | the VS poster — a fight, not a spec sheet |
| Polymarket 20x leverage | DiCaprio Wolf of Wall Street + trading-UI bubble | culture cast: the domain's one iconic movie scene |
| Quantum breaks Bitcoin in 9 min | giant cracking Bitcoin in flames + digital clock 09:00 | no face, no product → violent metaphor + the number as a physical prop |
| Patagonia founder gave it away | Chouinard cutout + logo badge + young-him climbing photo | a life story = a biographical multi-photo collage |
| NYC bans AI in schools | official at podium + red circle over "AI" + classroom inset | power + the banned thing + the affected, one frame |
| New Apple CEO John Ternus | cutout + orbit of every Apple product + ghost logo | "meet the man who now owns ALL of this" |
| Gmail hidden powers (guide) | Pichai + giant Gmail M + real UI + frustrated woman | vendor cast + the story's character + evidence |
| AirPods hidden features (guide) | Tim Cook holding the case + chrome Apple mark | vendor cast holding the exact product |
| Cook's last day as CEO | press photo of him wiping his eye — nothing else | when the story IS a feeling, props dilute it |
| GTA VI vs GTA V | split of both games' art + both logos | comparison |
| Sony: you don't own digital games | dark PS5 still-life, disc + controller | the objects in question, staged like evidence |
| ChatGPT plans your trip (guide) | Altman relaxed on a beach + giant glowing ChatGPT logo | vendor CEO living the READER's scenario |
| First-person Waldo game | raw game screenshot | the content itself is the hook — show it |
| Flappy Bird creator story | Dong Nguyen cutout + name chip + his game world | builder + his creation + LABEL name chip |
| Higgsfield recreates any video | "ORIGINAL" vs output, arrow between | before/after with labels |
| F-22 vanishes in vapor cloud | the actual caught photo + photographer inset + arrow | the story is the photo; inset credits the moment |
| GTA 6 made $450M pre-launch | game characters + flying money + "$5 MILLION in pre-orders" data chip | world + the number pinned as a chip |
| iPhone worst-day features | Cook holding the phone out + chrome Apple mark | vendor cast, product to camera |
| Things worth millions (listicle) | 4-photo grid (sneakers, watch, car, stamp) | list post = grid of the actual things |
| Daily recaps ×2 | multi-story photo grid / one movie still | recap = collage of the day, or pure attention bait |

### The seven archetypes (operative, coded into art_direct + genimg Sep 5)

Chosen by STORY TYPE — wrong archetype = concept failure:
- **A. POLICY/BAN collage** — famous actor + the ban made physical (red
  prohibition circle over the banned thing, bars/gavel) + optional inset of
  the affected. (~3 of 30 — the Bernie format is ONE lane, not the law.)
- **B. VENDOR CAST / BUILDER** — the person + giant glossy dimensional brand
  mark + the real product oversized. THE DOMINANT PERSON FORMAT (~7 of 30).
- **C. HUMAN MOMENT** — one emotional real press photo, zero props, brand
  mark ghosted at most.
- **D. PRODUCT HERO** — the product giant in its real world; no person.
- **E. LABELED COMPARISON / VS** — digital content compares as a FULL-BLEED
  split (the imagery fills the frame edge-to-edge, thin dividing line, no
  monitors/desk/room); physical products as the objects themselves huge,
  flaming VS between. Mandatory 1-3-word boxed label chips either way; the
  difference staged VIOLENT, never polite.
- **F. EVIDENCE + INSET** — the real documentary photo + ONE circular bubble
  (white ring, white hand-drawn arrow) with the secondary proof.
- **G. SYMBOLIC DRAMA** — faceless hero object mid-violence; the headline's
  number may appear as a physical prop (clock, odometer, price tag).

### Craft constants (every archetype, frozen in genimg scaffolds)

- ONE dominant subject; 2-3 props max, oversized to thumbnail-read.
- Real photographs as raw material — people and products are cutouts of real
  photos, never memory-drawn; AI composes and grades.
- Razor cutout edges + light rim; upper corners clear of the head.
- Brutal grade: very high saturation, high contrast, two-color palette.
- In-image text: ONLY quoted label chips (1-3 words, boxed, max 3) and real
  logo marks. Garbled or invented words = dead cover.
- Bottom of frame stays simple — the renderer's scrim owns the headline zone.

### Hook constants read off the same 30

- Name/brand in the first words on ~90% (name-first law confirmed at scale).
- A number on almost every cover: $499, 44%, $450M, 600,000, 20 years, 9 min.
- The small white substrip (our kicker) rides on ~90% of covers carrying the
  next-best fact — treat it as default-on for news.
- Formulas seen: "X JUST launched/built/revealed", "HERE'S THE NEW", "MEET X,
  THE...", "A GUY/WOMAN USED X FOR N YEARS THINKING...", "THIS BILLIONAIRE/
  PROGRAMMER...", second-person "YOUR IPHONE HAS...".

## 8. THE RECEIPT LAW — inner slides & CTA, the 18-slide forensic audit (Sep 5 2026, owner order)

Owner order Sep 5: "the second slide and the rest are very important and also
need to look good these are the highest converters." Audited every single
inner slide of three full reference swipe-throughs from the "optimal 1"
folder (Valve news post, 24-hours recap post, Gmail edu post) — 18 slides,
each logged as story → picture → why it was chosen.

### The one law

**Every inner slide's picture is that slide's OWN claim staged as its most
literal proof artifact.** Not the post's topic. Not a mood. The specific
sentence on THIS slide, receipted. A picture that decorates instead of
proves is a fail. Five receipt types, in preference order:

- **R1. SOURCE FOOTAGE** — a video still / screenshot of the actual moment,
  framed on a rounded card over the dark stage. Used when footage of the
  claim exists (Valve slide 2: the exact video frame that answers the
  cover's question). Screenshots live INSIDE the post as evidence, never as
  the cover.
- **R2. PRESS MOMENT** — a real photograph of THIS slide's actor mid-moment,
  full-bleed with feathered edges. EMOTIONAL REGISTER MATCHED: the recap
  post ran a black-and-white portrait on its death slide and grinning color
  shots on win slides. The photo's mood = the claim's mood, always.
- **R3. REACTION RECEIPT** — the real source post typeset as a clean X card
  on the dark backdrop. It is proof AND the comedy beat at once (Valve ran
  two). ANTI-FABRICATION: only pipeline-injected real data (handle, text,
  views, date from radar_x) — the model never writes tweet content. This is
  the ONE exception to the never-quote rule.
- **R4. DATA MADE PHYSICAL** — no person available → the story's real object
  + its chart fused into one physical scene, palette drawn from the object
  (recap post: gold bars under golden candlestick columns glowing on a dark
  wall). Never a floating graph, never a screenshot of a chart.
- **R5. SKILL RECEIPT (edu)** — the EXACT feature mid-use on a real device
  in a real evening workspace, one slide = one skill = one scene, scenes
  varied across the post. GARBLE GUARD: exactly one crisp quoted 1-3-word
  screen element (a toast reading "Undo"), everything else on the screen
  soft-focus/bokeh — our generators die on long UI text (5 of 6 historic
  fails were garble). Exception: full copy-paste prompt slides, where the
  prompt text itself is the payload.

### Edu inner-slide anatomy (Gmail post, 4 skill slides)

- Numbered headlines ("3/ UNDO SENT EMAILS") — a progress ratchet.
- Body in sentence case with the operative path bolded, arrow-notation steps
  ("-> Settings -> General").
- Every slide carries a skill-receipt image; none are text-only.

### CTA anatomy (both reference CTAs)

- The story's person, warm expression, story object held toward camera,
  ghosted brand mark behind, page-identity line ("WE SHARE USEFUL TECH
  FEATURES MOST PEOPLE NEVER FIND"). Our Aug 1 CTA closer already matches
  the VISUAL. The identity-line TEXT conflicts with the owner's Aug 18
  save-close law — flagged to owner Sep 5, not silently changed.

### Where it lives in code

- write.py: SLIDE_SCHEMA layout enum ["card","break","tweet"] (fixed the
  latent bug where "break" was impossible under structured output), reaction
  receipt prompt block + main() radar-data injection, emotional-register
  bullet in IMAGE ASSIGNMENT, DATA MADE PHYSICAL in art_direct STAKES, six
  qa() gates taught the tweet layout.
- render.py: .tweetcard CSS + tweet branch in slide_html (X-style card,
  avatar initial, formatted views, art_bg backdrop).
- edu.py: THE SKILL RECEIPT law replaces "1-2 most visual slides"; gen cap
  3 → 5 (owner-ordered quality push, ~+$1.3/mo worst case, reported).
