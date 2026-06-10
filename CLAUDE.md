# Design Context

The web frontend (`ts/site/`, live at https://bg3.danielfinch.co.uk) has its
strategic design context in [PRODUCT.md](PRODUCT.md) at the repo root. Read it
before any UI work.

- **Register**: product — the report is the point; design serves the task.
- **Personality**: arcane, trustworthy, precise — Identify-spell energy, not
  game-UI cosplay.
- **Principles**: the report is the product; trust is visible (local-only
  parsing, verifiably); precision is the flavor; Faerûn in the accents, not
  the architecture; fast in, fast out.
- **Accessibility**: WCAG AA contrast + full keyboard operability as the
  floor; `prefers-reduced-motion` respected.

No DESIGN.md yet — generate one with `/impeccable document` after the next
design pass settles the visual system.
