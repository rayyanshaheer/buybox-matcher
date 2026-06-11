# Tryout Writeup — BuyBox Matcher

## What I built

A focused rebuild of the core disposition loop: take raw investor messages,
extract structured **buy boxes** with AI, then match a property deal against
every buyer and rank them with an **explainable 0-100 score**.

Two screens — Extract and Match. It demos in about 30 seconds.

## Why this, specifically

I researched the target product (Covent, and its earlier brand Dispo Genius).
The whole business is speed-to-buyer: take a property, find the buyers whose
criteria fit, reach out first. I picked the single most central slice of that —
**structured buyer criteria in, ranked explainable matches out** — instead of
cloning the full platform UI. A focused, working piece of the core says more
than a broad shallow copy.

## Key decisions

- **Server-side AI only.** Keys never reach the browser; the frontend talks
  only to my API.
- **Rule-based, explainable scoring first.** Every score ships with the reasons
  behind it. I avoided a black-box model because (a) there's no closed-deal
  training data on day one and (b) operators trust visible reasons.
- **Pure scoring core.** `score(property, buy_box) -> {score, reasons}` does no
  I/O, so it is trivially testable and easy to tune.
- **AI at the edges only.** AI handles fuzzy text (extraction, phrasing). The
  match decision itself stays deterministic and inspectable.
- **Synthetic but realistic data.** ~150 seeded buyers shaped like real buy
  boxes, so the demo behaves like production. The engine is data-source
  agnostic.

## What I cut (and why)

- Real SMS/email sending — generated, shown, not sent (Twilio/compliance is not
  the interesting part).
- Auth / multi-user — single-operator demo; auth adds no signal.
- Real investor data — synthetic seed; same engine works on real data.
- Full pipeline kanban — the interesting problem is matching, not stage UI.

## What I'd do next

1. **Learned scoring** from logged match → outcome data, with the rule-based
   scorer kept as an explainable fallback.
2. **Real outreach** via Twilio + email, with reply capture.
3. **Reply classification** to auto-prioritize follow-up.
4. **Buy box from full conversations**, not just a single message.

## Honest notes

- I did not claim to fix a gap in the real product — I can't verify their
  internals from outside. This is "a core piece, built well," not "something
  they're missing."
- All data here is synthetic.
- Scoring weights are hand-tuned, not yet validated against real conversion data.

## Links

- Live demo: <add URL>
- Repo: <add URL>
- Loom walkthrough: <add URL>
