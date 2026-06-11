---
name: BG3 Save Parser
description: A fully client-side Baldur's Gate 3 save inspector with a committed-dark, gold-led visual system
colors:
  lantern-gold: "oklch(0.80 0.10 85)"
  lantern-gold-bright: "oklch(0.86 0.105 88)"
  underdark: "oklch(0.17 0.012 80)"
  underdark-surface: "oklch(0.21 0.015 80)"
  hairline: "oklch(0.32 0.025 80)"
  parchment-ink: "oklch(0.91 0.025 85)"
  scribe-mute: "oklch(0.72 0.035 83)"
  ember-error: "oklch(0.74 0.13 28)"
typography:
  display:
    fontFamily: "EB Garamond, Georgia, Times New Roman, serif"
    fontSize: "2.125rem"
    fontWeight: 600
    lineHeight: 1.15
    letterSpacing: "0.01em"
  headline:
    fontFamily: "EB Garamond, Georgia, Times New Roman, serif"
    fontSize: "1.5rem"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "0.015em"
  title:
    fontFamily: "system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "0.9375rem"
    fontWeight: 600
    lineHeight: 1.3
  body:
    fontFamily: "system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.55
    letterSpacing: "0.01em"
  label:
    fontFamily: "system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
rounded:
  sm: "2px"
  md: "8px"
  lg: "10px"
spacing:
  xs: "0.25rem"
  sm: "0.5rem"
  md: "1rem"
  lg: "1.5rem"
  xl: "2.5rem"
  2xl: "4rem"
components:
  drop-zone:
    rounded: "{rounded.lg}"
    padding: "3.25rem 1.5rem"
    textColor: "{colors.parchment-ink}"
  drop-zone-compact:
    rounded: "{rounded.lg}"
    padding: "1rem 1.5rem"
  fold-summary:
    typography: "{typography.title}"
    textColor: "{colors.parchment-ink}"
  count-badge:
    textColor: "{colors.lantern-gold}"
  slot-label:
    typography: "{typography.label}"
    textColor: "{colors.scribe-mute}"
  names-note:
    rounded: "{rounded.md}"
    padding: "0.5rem 1rem"
    textColor: "{colors.scribe-mute}"
---

# Design System: BG3 Save Parser

## 1. Overview

**Creative North Star: "The Identify Spell"**

A scholar's instrument that reveals exact truths from a mysterious object. The player
hands over an arcane artifact (a binary `.lsv` save) and the interface returns precise,
trustworthy answers: who is in the party, what they wear, what they know. The mysticism
lives entirely in the atmosphere — a deep, warm dark and lantern gold — while the
answers themselves are set with the rigor of a well-kept ledger. Committed-dark is the
color strategy: the surface IS the atmosphere; gold is the revealing light.

The system explicitly rejects three things named in PRODUCT.md: the sketchy
save-upload-site look (ads, urgency, fake spinners), heavy skeuomorphic fantasy
(faux-leather, filigree, parchment scroll-edges), and the generic SaaS template (cream
backgrounds, tracked-uppercase eyebrows, hero-metric cards). Faerûn is carried in the
accents and the type, never in the architecture.

**Key Characteristics:**
- Committed dark: a warm near-black surface carries the whole page
- One metal: gold does headings, counts, focus, and interaction — nothing else does
- Two voices: a renaissance serif for names, a system sans for data
- Tactile and warm: controls respond with surface light and gold edges, not shadows
- Precision as flavor: exact counts, slot labels, and honest "undetermined" states

## 2. Colors

A single gold over layered warm darks; every text pair verified at 7:1 or better.

### Primary
- **Lantern Gold** (`oklch(0.80 0.10 85)`, ≈ #dbb970): the revealing light. Character
  names, the wordmark, counts, links, fold chevrons, and focus rings. 10.2:1 on
  Underdark.
- **Lantern Gold Bright** (`oklch(0.86 0.105 88)`, ≈ #eecd7e): hover state of gold
  elements only. Never appears at rest.

### Neutral
- **Underdark** (`oklch(0.17 0.012 80)`, ≈ #120f0a): the page background. Warm-hued
  near-black; the chroma leans toward gold, not generic warmth.
- **Underdark Surface** (`oklch(0.21 0.015 80)`, ≈ #1c1811): one tonal step up; hover
  fill for the drop zone and any raised panel.
- **Hairline** (`oklch(0.32 0.025 80)`, ≈ #3a3224): 1px rules and borders — section
  dividers, the drop zone dash, the names-note frame.
- **Parchment Ink** (`oklch(0.91 0.025 85)`, ≈ #e9e0cf): primary text. 14.6:1 on
  Underdark.
- **Scribe Mute** (`oklch(0.72 0.035 83)`, ≈ #afa38c): secondary text — meta lines,
  slot labels, group heads, hints. 7.7:1 on Underdark; never used below this lightness
  for text.

### Tertiary
- **Ember Error** (`oklch(0.74 0.13 28)`, ≈ #f2897c): error status lines only. 7.9:1 on
  Underdark.

### Named Rules
**The Lantern Rule.** Gold is the light source, not the paint. It marks what the reader
should find (names, counts, interactive edges) and never fills surfaces. If gold covers
more than roughly a tenth of the screen, the room is on fire — pull it back.

**The Warm-Dark Rule.** All neutrals share the gold hue (h≈80–85) at low chroma. Pure
gray and cool tints are prohibited; so is any cream/parchment body background — warmth
lives in the dark, not in a light surface.

## 3. Typography

**Display Font:** EB Garamond (self-hosted 40KB latin variable, weights 400–800; falls
back to Georgia)
**Body Font:** system-ui stack
**Mono (data codes):** ui-monospace, for raw internal identifiers only

**Character:** A renaissance serif speaks the proper nouns — save names, character
names, the wordmark — while a plain system sans carries every fact and label. The
pairing is the whole brand: arcane voice, precise hand.

### Hierarchy
- **Display** (600, 2.125rem, 1.15): the save name. One per page.
- **Headline** (600, 1.5rem, 1.2, Lantern Gold): character names.
- **Title** (600 sans, 0.9375rem): section heads ("Equipped", fold summaries) — weight
  and a gold count carry the hierarchy, never uppercase tracking.
- **Body** (400, 1rem, 1.55): all running text and item names; +0.01em letter-spacing
  to compensate light-on-dark.
- **Label** (400, 0.875rem, Scribe Mute): slot labels, hints, group heads, meta lines.

### Named Rules
**The Two Voices Rule.** The serif names things; the sans states facts. Neither borrows
the other's job — no serif body text, no sans character names.

**The No-Eyebrow Rule.** Tracked-uppercase section kickers are prohibited. Section
hierarchy is weight + gold count ("Equipped 9"), set in normal case.

## 4. Elevation

Flat, candlelit. Depth comes from tonal layering — Underdark → Underdark Surface →
Hairline — and never from drop shadows. There is no shadow vocabulary in the system;
hover states raise an element by lightening its fill (the drop zone gains Surface and a
gold border), not by lifting it off the page.

### Named Rules
**The Candlelit Rule.** Surfaces are flat at rest and brighten under attention. If a
box-shadow appears anywhere, it is a bug.

## 5. Components

Tactile and warm: controls sit quiet in the dark and answer touch with light — a gold
edge, a brighter surface, a turned chevron. Affordances are felt, not shouted.

### Drop Zone (signature component)
- **Shape:** softly rounded (10px), 1px dashed Hairline border
- **Default:** generous padding (3.25rem vertical), centered, hint path in Scribe Mute
- **Hover / Drag-over / Focus-within:** border turns Lantern Gold, fill rises to
  Underdark Surface (180ms ease-out); focus adds a 2px gold outline at 3px offset
- **Compact:** after the first parse it collapses to a quiet bar (1rem padding, hint
  hidden, label becomes "Drop another save")
- **Keyboard:** the file input stays focusable (clip-path hidden, never display:none)

### Disclosure Folds (carried, spells, mods)
- **Summary:** Title typography with a gold count and a muted fold-note
- **Marker:** custom 0.5em gold chevron, rotates 90° on open (180ms ease-out); native
  triangles are suppressed everywhere so the vocabulary is consistent
- **Content:** indented 1.1rem, items in an auto-fill grid (minmax 20rem)

### Equipped Grid
- **Rows:** two-column grid per item — fixed 7.5rem slot label (Scribe Mute, 0.875rem)
  beside the item name in Parchment Ink; auto-fills to two columns above ~50rem
- **Empty slot label:** an em dash placeholder glyph
- **Counts:** ×N in Lantern Gold

### Item Search
- **Placement:** part of the report, between the save header and the first character;
  appears only once a save is parsed
- **Control:** visible "Find an item" label (Scribe Mute) beside a type-to-filter
  search input — Surface fill, 1px Hairline border turning Lantern Gold on
  hover/focus, placeholder in Scribe Mute
- **Scope:** every item in the save — equipped (with slot), carried, undetermined,
  and the camp chest; gold stacks excluded
- **Results:** item name in Parchment Ink with the matched run in Lantern Gold (the
  Lantern Rule, literally), ×N count in gold, location in Scribe Mute
  ("Wyll · carried"); summary line is aria-live polite and states misses plainly
  ("Nothing in this save matches 'x'.")

### Character Sections
- **Separation:** 1px Hairline top rule + 2.5rem top margin — space and rules, not
  cards. Nested boxes are prohibited.
- **Entrance:** 8px rise + fade, 0.4s ease-out-quart, staggered 50ms per section;
  disabled entirely under prefers-reduced-motion

### Status Line
- **Role:** aria-live polite; Scribe Mute for progress, Ember Error for failures
- **Copy:** plain, verifiable statements ("Parsed X in 643 ms. Nothing left your
  machine.")

## 6. Do's and Don'ts

### Do:
- **Do** keep every text/background pair at 4.5:1 minimum; this system runs at 7:1+ —
  if a new pair lands below that, lighten the text toward Parchment Ink.
- **Do** put raw internal identifiers (`SCL_Main_A`, stats names) in the mono face with
  the friendly label leading and the raw value in a `title` attribute.
- **Do** use periods, semicolons, colons, and parentheses in UI copy — em dashes are
  reserved for the empty-slot placeholder glyph.
- **Do** state degraded states plainly ("Display names unavailable; internal names are
  shown") — honesty is the trust mechanic.

### Don't:
- **Don't** look like a sketchy save-upload site: no ads, no fake progress, no
  "uploading…" theater, no urgency copy (PRODUCT.md anti-reference, verbatim).
- **Don't** do heavy skeuomorphic fantasy: no faux-leather textures, dragon filigree,
  parchment scroll-edges, or game-UI cosplay (PRODUCT.md anti-reference).
- **Don't** drift into the generic SaaS template: no cream backgrounds,
  tracked-uppercase eyebrows, hero-metric cards, or identical icon grids (PRODUCT.md
  anti-reference).
- **Don't** use box-shadows (The Candlelit Rule) or side-stripe borders thicker than
  1px.
- **Don't** introduce a second accent color; semantic needs beyond gold and Ember Error
  must be argued for, not assumed.
- **Don't** use display:none on the file input or remove focus outlines; keyboard
  operability is non-negotiable.
