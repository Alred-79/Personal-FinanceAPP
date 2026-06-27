# Landing — Forecast → Instruments transition

The seam between the **Forecast** section and the **Instruments** filmstrip had a
dead band (a half-screen void above the pinned heading, plus `mt-28`). Two goals:
**close the gap** and **make the transition feel like moving through one engraved
document**, not scrolling over floating cards.

## Chosen direction — "The Plate Case" (SHIPPED)

A reframe after THREE seam-divider attempts were all rejected: the real problem
wasn't the gap, it was the Instruments reading as **six identical flat boxes**
(an AI-slop tell per the impeccable brand register: "cards are the lazy answer";
"identical card grids"). So instead of a divider, the fix is the cards + the space
they live in — a blend of three depth ideas:

1. **Heading IS the transition** — the title is struck/inked in with an intaglio
   `clip-path` reveal (left→right) while a guilloché **bloom** (`GuillocheBloom`,
   concentric rings + radials) forms behind it. The section ARRIVES as an
   engraving event, no divider graphic.
2. **Specimen case with depth (STATIC)** — each plate rests at its own `translateZ`
   (`PLATE_DEPTH` near/far wave, inside a static `.iv-stage3d` perspective) and
   casts a **real reflection** on the case floor (`-webkit-box-reflect`) + a
   contact shadow. Reads as engraved plates seated in a recessed case, not flat
   cards. `items-end` so reflections share a baseline. No tilt.

The **camera push was tried and removed** at the user's request ("I don't want to
play around with the camera"): the deck no longer has scroll-linked
`rotateX`/`z`/`scale` — only the horizontal `x` scrub + the static depth above.
Re-adding = `useTransform(scrollYProgress,[0,0.16],…)` on rotateX/z/scale into the
`.iv-deck` style.

Files: `sections/Instruments.tsx` (`EngravedHeading`, `GuillocheBloom`, FilmPlate
depth) + landing.css `.iv-stage3d` / `.iv-deck` / `.iv-plate3d` / `.iv-bloom`.
Reduced-motion: box-reflect removed; mobile/reduced get the plain Grid + Heading.
Ink law respected (gold/credit chrome only).

## Alternatives considered / tried (swap in if we want to change later)

1. **Engraved chapter seam** (tried, reverted) — a self-drawing guilloché rule +
   "CHAPTER · II" cartouche divider. Deliberate page-break beat; user disliked it.
2. **The number hands off** (tried, reverted) — Forecast green median line becomes
   a **rail** the plates mount on (`Handoff.tsx` + `.iv-rail`/`.iv-mount`).
3. **Ledger tape / film gate** (tried, reverted) — filmstrip as a perforated tape
   (`.iv-tape`) fed past a gold gate (`.iv-gate`). Too busy.
4. **Break the identical grid** (not built) — vary plate size/framing/tone, hero
   plate, engravings bleeding off edges. Could COMBINE with the Plate Case later.
5. **Aperture / vault reveal** (not built) — guilloché backdrop parts like an iris.

All but the chosen one were either rejected or deferred; the Plate Case attacks the
"flat boxes" complaint directly (depth + reflection + camera), not via a divider.
