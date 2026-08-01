# Hebrew writing doctrine (@ainews.israel)

The Hebrew arm inherits EVERY rule of the English system (principles.md, the
owner rules, the QA gates). This file adds only what changes when the language
is Hebrew. Injected into the he.py localization prompt.

## Register: Israeli, not translated

- Write the way a smart Israeli 16-year-old actually talks. If a sentence
  sounds like it was translated from English, rewrite it. Test: would an
  Israeli say this out loud to a friend at the table?
- Simple everyday words. No archaic or literary Hebrew, no newspaper-Hebrew
  ("לדבריו", "כמו כן", "יצוין כי" are banned). No niqqud ever.
- Active and direct: "החברה פיטרה 300 עובדים", never "300 עובדים פוטרו על ידי החברה".
- Say what things DO, not what they are called. Zero tech jargon. If a term
  needs explaining, explain it in five words inline.

## What stays in English (LTR islands inside RTL text)

- Company, product, and person brand names: OpenAI, ChatGPT, Claude, SpaceX,
  Elon Musk (מותר גם "אילון מאסק" if the Hebrew form is the common one in
  Israeli media; use whichever an Israeli teen would type).
- "AI" stays "AI" (Israelis say and type AI; "בינה מלאכותית" is allowed once
  for flavor, never as the repeated term).
- ALL hashtags stay in English, copied from the English post unchanged.
- Numbers stay digits, money stays in the original currency ($10M stays $10M).
- The follow handle is @ainews.israel, always.

## Hard bans (same as English, plus the Hebrew ones)

- NO dashes of any kind: no em dash, no en dash, no " - ", and no Hebrew
  maqaf (־). Use a comma or a period. This is an owner hard rule.
- No gershayim-heavy acronym soup; prefer the plain word.
- Credits and sources keep their English names ("מקורות: The Verge").
- Never quotation-mark a whole sentence as a stylistic crutch.

## Translationese detector (the "machine built it" killers)

The tell of translated Hebrew is not wrong words, it is ENGLISH STRUCTURE
wearing Hebrew words. Scan every line for these and rewrite:

Calques (English idiom translated literally — always rewrite):
- "עושה שכל" (makes sense) → "הגיוני"
- "בסוף היום" (at the end of the day) → "בשורה התחתונה"
- "לקח החלטה" (took a decision) → "החליט"
- "עשה היסטוריה" (made history) → "שבר שיא" / state the record itself
- "משנה משחק" (game changer) → say WHAT changed, concretely
- "שם בחוץ" (out there) → "בעולם", or drop it
- "הולך לעשות" as future (going to do) → plain future: "יעשה"
- "אני מרגיש ש..." padding (I feel like) → just say the claim

Newspaper words a teen never says (swap to the spoken form):
- כאשר → כש..., על מנת → כדי, אשר → ש..., אולם → אבל
- כעת → עכשיו, בנוסף → וגם / חוץ מזה, מספר אנשים → כמה אנשים
- אנשים רבים → הרבה אנשים, ניתן ל... → אפשר, מהווה → זה
- לרכוש → לקנות, לבצע → the concrete verb (לבדוק, לשלוח...)

Structure smells (English syntax leaking through):
- Possessive chains: "המודל של החברה של..." → smichut or split the sentence.
- Passive with על ידי: "פותח על ידי OpenAI" → "OpenAI פיתחה".
- A Hebrew line whose word order maps 1:1 onto the English original — the
  hard test: if you can hear the English sentence underneath, rewrite from
  the story, not from the words.
- Chained relative clauses ("ה-X ש-Y ש-Z") → two short punches with a comma.

## Hooks in Hebrew (carry the English craft over)

- The information gap survives translation only if the TENSION survives:
  the cover plants a question, each slide answers it and plants the next.
  Localize the gap, not the words.
- Negativity and high arousal work in Hebrew exactly like English: fear,
  money, jobs, "זה כבר קורה", "בלי שביקשו רשות".
- The caption's first line carries the payoff (first ~125 chars show before
  "עוד"), with search words an Israeli would type.
- The reader is an Israeli scrolling at night: prices in dollars are fine,
  but when a story touches Israel (Israeli startup, Israeli lab, IDF tech,
  a global story with an Israeli angle) SAY IT and lead with it — local
  relevance is the strongest hook this page has that the English page lacks.

## Hook craft (covers + reel titles) — owner order Aug 1: "must improve significantly"

The kill test: read the line OUT LOUD. If a native Israeli would stumble, or
it sounds like English wearing Hebrew words, it is disqualified — no matter
how good the content is. Grammar errors (mismatched gender/number, singular
verb on a plural subject) are instant kills.

Write from the STORY, never from the English words. The English hook is
raw material for facts only; the Hebrew line is born in Hebrew.

Patterns that sound native (use these shapes):
- Front the punch with "מה ש...": "מה שלקח לך שנים ללמוד, הרובוט הזה עושה אחרי דקות"
- The moment-before: "שנייה לפני שכיסו אותו בבד, הרובוט עשה משהו מוזר"
- Second person, direct: "הצ'אטים הפרטיים שלך עם AI הגיעו לגוגל"
- Contrast in one breath: "עלה $20, נמכר ב-$317,000"
- The dry understatement Israelis love: state the insane fact flat, zero
  exclamation, let the fact scream.

Translationese failures (real ones we shipped — never again):
- "הרובוט הזה לומד תנועות שלקח לך שנים ללמוד, תוך דקות" — agreement broken
  (שלקחו), clause chain is English syntax. Native: "מה שלקח לך שנים ללמוד,
  הרובוט הזה למד תוך דקות"
- "עשה היסטוריה", "לקח החלטה", "הרשת השוותה" — English idioms in Hebrew
  words. Israelis say: "שבר שיא", "החליט", "כולם צחקו על".
- Chained relative clauses ("ה-X ש-Y ש-Z") — break into two short punches
  with a comma.

## RTL mechanics

- Text flows right-to-left; punctuation sits naturally (the renderer handles
  bidi, the writer just writes correct Hebrew).
- The accent markup (<em>) works exactly as in English: mark the minimum set
  of words that still communicates the claim standalone.
- Arrows in copy point LEFT (←) because that is where the next slide is.
