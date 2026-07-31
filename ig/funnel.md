# @yaffeai DM funnel (ManyChat) — built on $100M Offers

Goal: every engaged follower gets the welcome message; replies qualify them
(business owner -> booked meeting). Cross-posting: not for now.
Doctrine source: Obsidian vault "Marketing LLM" -> Library/$100M Offers (+ Playbook).

## The offer (Hormozi Grand Slam Offer — PROPOSED, the owner must approve before use)

The meeting itself is the free lead magnet, wrapped M-A-G-I-C style:

> **The Free AI Workload Audit** — a 15-minute call where we find the ONE task
> in your business that AI should take off your plate first, and what it would
> save you per month. You leave with the answer whether you hire us or not.

Value equation mapping:
- Dream outcome: a "digital employee" doing a real job in their business
- Likelihood: we show a concrete plan on the call, not a sales pitch
- Time delay: 15 minutes to the answer; first digital employee working in ~30 days
- Effort: zero — they book, we do the thinking. Done-for-you, never do-it-yourself

**DECIDE (owner — these are commitments to real customers, not copy):**
1. Guarantee (Hormozi service guarantee): "If your digital employee isn't doing
   the job within 30 days, we keep working free until it is." Ship it? (This is
   the single strongest lever for a business with no track record yet — Ch. 15.)
2. Honest scarcity: "I take on 3 new businesses a month" — true for a solo
   consultancy, but only say it if we'll enforce it. Ship it?
3. Booking tool: Calendly (or similar) link for the CTA — still unanswered.
   Without it, "book a meeting" = manual DM ping-pong.

Rules from the book (mandatory): never state price in DMs or posts (price lives
in the meeting) - no fake urgency/scarcity ever - pain first, then outcome with
a number, then how little effort - bonuses/value language over any discount talk.

## Platform reality (why "DM every new follower" needs a trigger)
Meta's official API has NO "new follower" event — no compliant tool (ManyChat,
Make, anything) can DM someone just because they followed. Tools that claim to
do it drive the app with a bot and get accounts banned. The compliant
equivalent: make every post's CTA drive a COMMENT or DM keyword, which IS an
official trigger, then the flow below fires. Same funnel, safe trigger.

**Keyword is now "AI"** (captions already ship "DM us 'AI'..." as of Jul 26).
Until ManyChat is live those DMs land in the owner's inbox — answer them manually
with Message 2's question, same script.

## Flow

**Trigger:** user DMs "AI" (or anything), comments "AI" on any post, or
replies to a story.

**Message 1 (welcome — pain first, the pain is the pitch):**
> Hey — glad you messaged 👋
>
> Most business owners we talk to are losing 10+ hours a week to work a
> computer should be doing: answering the same questions, chasing leads,
> writing the same emails.
>
> We build digital employees — AI that does that work for you, done-for-you,
> so you don't touch any tech.
>
> Quick question so I point you right 👇

**Message 2 (qualification quick-replies):**
- 🚀 I run a business
- 💡 I want to start one
- 🤖 I just want to learn AI

**Routing:**
- "I run a business" -> HOTTEST. Ask: "What's the one task that eats most of
  your week?" Then the offer: "That's usually the first thing we hand to a
  digital employee. Want a free 15-minute AI Workload Audit? We'll find what
  it would save you per month — you keep the answer either way." -> booking
  link (DECIDE #3).
- "I want to start one" -> nurture; share a builder story + follow-up.
- "I just want to learn AI" -> audience; keep them engaged, they follow + share.

## Post-side wiring
- LIVE (Jul 26): write.py + recap.py captions end the trend block with the
  business-owner DM line (keyword "AI"). Slide-side: the second-to-last slide
  of every daily_item is the VALUE slide (pain -> outcome number -> low effort).
- The follow-CTA slide stays a news-service CTA — reach and conversion CTAs
  are kept separate on purpose.

## Setup checklist (web UI, one-time, ~20 min)
1. manychat.com -> sign up free -> connect Instagram (needs the professional
   account; same one Make uses).
2. Automation -> New Flow -> trigger "User comments on your post" -> keyword
   AI -> all posts.
3. First step: public comment reply (short: "sent you a DM 👀") + the DM =
   Message 1.
4. Any reply -> Message 2 with the 3 quick replies.
5. Each quick reply -> tags the contact (business / starter / learner) and
   sends the routing message.
6. Also add trigger "User sends a DM" (any keyword) -> same Message 1, and
   "Story reply" -> same flow.
