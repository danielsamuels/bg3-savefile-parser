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

# Naming

Human-facing names (items, spells, feats, reactions, quests, anything a player
reads) come from the game files via the gamedata layer (`bg3parser/gamedata.py`
-> `data/gamedata.json`, mirrored in TS). Never synthesize a display name from
an internal identifier by string transformation: the game calls
`Interrupt_AttackOfOpportunity` "Opportunity Attack" and `Interrupt_Overwhelm`
"Tenacity", which no regex over the ID would produce. If a name is missing, add
its source table to the gamedata build rather than guessing. (`re` itself is
fine and load-bearing: it is how we parse those game files.)
