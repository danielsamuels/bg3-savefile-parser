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

## Install

```sh
pip install zstandard lz4
```

## Usage

```sh
# Parse a specific save (writes to stdout, or to a file if given):
python3 bg3_save_reader.py /path/to/QuickSave_NNN.lsv [report.txt]

# Or omit the path to auto-detect and use the most recent save:
python3 bg3_save_reader.py
```

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

Characters, ownership, display names, and the item pool are reliable. Spell
attribution is heuristic. The exact equipment slot and the worn-vs-carried
distinction require decoding the `LSMF` ECS blob, which is an open problem —
see the status table in [FORMAT.md](FORMAT.md#8-status--open-problems).
