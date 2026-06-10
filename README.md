# bg3-savefile-parser

A dependency-light, pure-Python reader for **Baldur's Gate 3** `.lsv` save
files. It extracts, for a save:

- **Party characters** — race, class/subclass, level, XP, location
- **Per-character gear** — items attributed to each character by shared world
  position, split into *equipped* / *carried* / *worn-or-carried-undetermined*
- **Human-readable item names** — internal names resolved to
  `Display Name (INTERNAL_NAME)` from the installed game data, where available
- **Spells / abilities** — extracted from the ECS blob and attributed by class
- **Full level item pool** — every item in the current level cache

It reads the binary formats directly (LSPK packages, LSF resources, the `.loca`
localisation table) — no [LSLib](https://github.com/Norbyte/lslib)/`divine`
required.

## Usage

With [`uv`](https://docs.astral.sh/uv/) installed, run from a clone — the
project environment (just `zstandard` + `lz4`) is created automatically:

```sh
# Parse a specific save (writes to stdout, or to a file if given):
uv run bg3save /path/to/QuickSave_NNN.lsv [report.txt]

# Or give just the save number (finds the matching save automatically):
uv run bg3save 286

# Or omit the path to auto-detect and use the most recent save:
uv run bg3save

# Machine-readable output for building on top of the parser:
uv run bg3save 286 --json
```

Without `uv`: `pip install .` then `bg3save …`, or `python -m bg3parser …`.
The implementation lives in the `bg3parser` package, organised by format
layer (`lspk`, `lsf`, `lsmf`, `osiris`, `party`, `gamedata`, `model`,
`render`).

**Environment overrides**

| Variable | Purpose |
|----------|---------|
| `BG3_SAVE_DIR` | Restrict save auto-detection to this directory |
| `BG3_DATA_DIR` | Point at the game's `Data` directory for display-name resolution |

Display names are resolved from an installed copy of the game (auto-detected in
the usual Steam locations); without one, items are shown by their internal name.

## Documentation

- **[FORMAT.md](FORMAT.md)** — a reference for the binary file formats: LSPK
  packages, the LSF/LSOF resource format, the `LSMF` ECS blob, and `.loca`.
- **[LIMITS.md](LIMITS.md)** — what the parser can and cannot recover, and why
  (notably: exact equipment slot and worn-vs-spare live in the undecoded ECS
  blob).

## Status

Characters, ownership, display names, spell books, and the item pool are all
read exactly. Per-character spells come from the save's ECS blob
(`SpellBookComponent → SpellData → SpellId → string pool`), including
item-granted and mod-added spells. The worn-vs-carried distinction is resolved
by a layered set of signals (the `0x04000000` Flags bit, active on-equip
STATUS effects, and several `LSMF` ECS components), validated against in-game
ground truth across many saves, and every worn item is annotated with its
equipment slot (derived from item stats — the save does not serialise the
slot; the game re-derives it the same way). See the status table in
[FORMAT.md](FORMAT.md#8-status--open-problems).
