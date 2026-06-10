# Product

## Register

product

## Users

Baldur's Gate 3 players — curious, not necessarily technical. They've just
finished a session (or are mid-playthrough) and want to see what their save
actually contains: who's in the party, what each character is wearing and
carrying, what spells they know. They arrive with a `.lsv` file and a healthy
wariness about uploading game files to random websites. The job: drop the
save, get a clean, readable, trustworthy report of the party — in seconds,
with the file never leaving their machine.

A secondary audience of modders and save-format tinkerers exists (the repo's
FORMAT.md crowd), but the site serves players first; deeper detail belongs in
progressive-disclosure layers, not the default view.

## Product Purpose

A fully client-side Baldur's Gate 3 save inspector at
https://bg3.danielfinch.co.uk. Drag-and-drop a `.lsv` save; a Web Worker
parses the binary formats (LSPK → LSF → LSMF ECS blob) in TypeScript and
renders per-character reports: race, class, level, XP, location, equipped
gear with slots, carried inventory, spells and abilities. Item and spell
names are resolved from a pre-built game-data file.

It exists because the alternative is either trusting an upload site with your
save or installing desktop tooling. Success looks like: a player gets a
correct, legible report of their party within seconds of dropping a file,
believes (correctly) that nothing was uploaded, and comes back after the next
session. The parsing accuracy is hard-won (validated against in-game ground
truth across many saves) — the interface must honor that precision rather
than hide it behind vagueness.

## Brand Personality

**Arcane, trustworthy, precise.** A scholar's instrument — the feel of
casting Identify on a magic item: mystical flavor, exact answers. The
Faerûn identity lives in the palette (warm gold on deep dark), the type, and
small confident touches; the data itself is presented with the rigor of a
well-kept ledger. Copy is calm and exact, never jokey, never breathless.
Privacy claims are stated plainly and verifiably ("check the network tab"),
not as marketing reassurance.

## Anti-references

- **Sketchy save-upload sites**: ad-laden "upload your save here" tools. We
  are the opposite — obviously local, no accounts, no tracking, verifiable.
- **Heavy skeuomorphic fantasy**: faux-leather textures, dragon filigree,
  parchment scroll-edges, game-UI cosplay. The fantasy is an accent, not a
  costume.
- **Generic SaaS template**: cream backgrounds, tracked-uppercase eyebrows,
  hero-metric cards, identical icon grids. This is a tool, not a landing
  funnel.

## Design Principles

1. **The report is the product.** Every design decision defers to legibility
   of the parsed data — hierarchy, scanability, and density tuned for
   "find my character's gear fast". Atmosphere never costs readability.
2. **Trust is visible.** Local-only parsing isn't a footnote; the interface
   demonstrates it (instant parse, no spinners pretending to upload, plain
   verifiable privacy copy).
3. **Precision is the flavor.** The parser's exactness is the brand. Show
   counts, slots, and classifications confidently; when something is
   genuinely undetermined, say so explicitly rather than papering over it.
4. **Faerûn in the accents, not the architecture.** Warm gold, dark depths,
   characterful type for headings — applied to a clean, standard tool
   layout with familiar affordances. No invented controls, no costume.
5. **Fast in, fast out.** One primary action (drop the file), instant
   feedback, report on screen in seconds. No onboarding, no steps, no modal
   in the way.

## Accessibility & Inclusion

- WCAG AA contrast as the working floor (gold-on-dark pairs verified ≥4.5:1
  for body text, ≥3:1 for large text).
- Full keyboard operability — the drop zone is also a focusable, labelled
  file input; disclosure sections (carried items, spells) keyboard-toggleable.
- `prefers-reduced-motion` respected for any transitions added.
- Report structure semantic (headings per character, lists for items) so
  screen readers can navigate by section.
