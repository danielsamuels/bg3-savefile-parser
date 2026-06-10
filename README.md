# bg3-savefile-parser

Readers for **Baldur's Gate 3** `.lsv` save files, twice over: a TypeScript
parser powering a fully client-side website, and the pure-Python reference
implementation it was ported from. Both read the binary formats directly
(LSPK packages, LSF resources, the LSMF ECS blob, the Osiris story state, the
`.loca` localisation table), so no [LSLib](https://github.com/Norbyte/lslib)/
`divine` install is needed.

## The website

Drop a save on <https://bg3.danielfinch.co.uk> and read your campaign.
Parsing happens in a Web Worker in your browser; the file is never uploaded
(verifiably: check the network tab). It shows:

- The save: name, slot, region, difficulty, version, installed mods, and
  the load-screen thumbnail
- The party: race, class/subclass, level, XP; equipped gear in game-panel
  slot order; carried inventory grouped by category ("14 items · 2,102 gold")
- Camp: companions waiting at the campsite with their gear and spell
  books, plus the full contents of the camp chest
- Spell books: exact per-character spells from the ECS blob, with
  sub-spells and basic actions folded away like the in-game UI
- The quest log: in-progress and closed quests with their real journal
  titles, mirroring what the in-game journal shows
- Campaign history: parsed saves persist in your browser (IndexedDB
  only), with gold and XP progression charts across a playthrough
- Live mode (Chromium): point it at the save folder and every quicksave
  re-parses automatically
- A text download of the report, byte-identical to the CLI's output
- Installable as a PWA; works fully offline after the first visit

## The CLI (Python)

The Python package is the research lab where format discoveries land first,
and a complete CLI in its own right. With [`uv`](https://docs.astral.sh/uv/)
installed, run from a clone:

```sh
# Parse a specific save (writes to stdout, or to a file if given):
uv run bg3save /path/to/QuickSave_NNN.lsv [report.txt]

# Or give just the save number / omit it for the most recent save:
uv run bg3save 286
uv run bg3save

# Extra sections and switches:
uv run bg3save 286 --save-info --quests --carried --all-items --verbose

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
| `BG3_GAMEDATA_JSON` | Use a pre-built name table (e.g. the committed `data/gamedata.json`) instead of a game install |

Display names (items, spells, quests) are resolved from an installed copy of
the game (auto-detected in the usual Steam locations) or from the committed
name table; without either, internal names are shown.

## Architecture

```
bg3parser/      Python reference implementation + CLI (discoveries land here)
ts/parser/      @bg3save/parser: the TypeScript port (the product runtime)
ts/site/        the website (Vite, vanilla TS, Cloudflare Workers assets)
data/           gamedata.json: derived name/slot/quest tables (committed)
tests/          pytest suite, golden text fixtures, and the parity oracle
```

A parity contract holds the two implementations together: the
`tests/parity/*.expected.json` fixtures are generated from the Python model
(`uv run python tests/generate_parity.py`) and the TypeScript test suite
compares its output against them field-for-field across real saves. Any
classification change regenerates parity, and both suites must pass.
Pre-commit hooks (ruff, ty, Biome, tsc) and CI enforce this; CI also
deploys the site on green master builds.

## Documentation

- [FORMAT.md](FORMAT.md): a reference for the binary file formats. LSPK
  packages, the LSF/LSOF resource format, the `LSMF` ECS blob, the Osiris
  story save, and `.loca`.
- [LIMITS.md](LIMITS.md): what the parser can and cannot recover, and why.

## Status

Characters, ownership, display names, spell books, quests, camp companions,
and the item pool are all read from the save's own data. Per-character spells
come from the ECS blob (`SpellBookComponent → SpellData → SpellId → string
pool`), including item-granted and mod-added spells. The worn-vs-carried
distinction is resolved by a layered set of signals (the `0x04000000` Flags
bit, active on-equip STATUS effects, and several `LSMF` ECS components),
validated against in-game ground truth across many saves, and every worn item
is annotated with its equipment slot (derived from item stats, since the save
does not serialise the slot; the game re-derives it the same way). Camp companions
are recognised by proximity to the camp chest; their class, level, and spell
book come from ECS class matching on the origin's fixed base class. See the
status table in [FORMAT.md](FORMAT.md#8-status--open-problems).
