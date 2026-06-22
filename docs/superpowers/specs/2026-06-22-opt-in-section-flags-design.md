# Opt-in section flags for the CLI

Date: 2026-06-22
Status: design approved, pending spec review

## Problem

The `bg3save` CLI renders a fixed default report: party identity, equipped
gear, and spells, with a one-off `--no-spells` flag to subtract spells and a
handful of additive flags (`--save-info`, `--quests`, `--carried`,
`--all-items`, `--vendors`, `--limits`) for everything else. The default set is
not composable: you cannot ask for "characters and their equipped gear but not
spells" without the awkward `--no-spells` subtraction, and there is no way to
drop the identity block while keeping gear, or to control the active party and
camp independently.

This makes every grouping opt-in. The report becomes something you compose from
flags rather than a fixed shape you subtract from.

## Behavior change

- Every grouping is off by default.
- A bare `bg3save 286` prints a short confirmation header instead of a full
  report.
- `--no-spells` is retired (no longer meaningful once spells are opt-in).

This changes the default output of the CLI. The website is unaffected in what
it displays (see Parity).

## The bare-command header

Always printed, on every invocation, from data available cheaply (the package
header plus the active-party parse that already runs):

- save name / number, slot, region, save date
- active party members, named
- when no group flag is given: a one-line pointer to the available flags

When at least one group flag is given, the header still prints but the
"available flags" hint is dropped. The exact metadata fields are whatever is
cheaply available without triggering the `--save-info` gather path; at minimum
the save name/number and the active party names. In-game clock time is included
only if already parsed; otherwise the save's real-world date stands in.

## The flags

All group flags default to off (`action='store_true'`).

Top-level (existing flags, unchanged semantics):

- `--save-info` — save metadata block
- `--quests` — quest / story state (gather-gated, adds ~1-2s)
- `--vendors` — merchant for-sale stock (gather-gated)
- `--all-items` — full level item pool (gather-gated)
- `--limits` — known limitations note

Active party (per-character), new:

- `--characters` — identity core: race, class/subclass, level, XP, location,
  abilities, HP, resources, feats, reactions, concentration
- `--equipment` — worn gear
- `--spells` — spell book
- `--carried` — carried / personal inventory

Camp, symmetric to the active party, new:

- `--camp-characters` — camp companion identity core
- `--camp-equipment` — camp companion worn gear
- `--camp-spells` — camp companion spell books
- `--camp-carried` — camp companion carried inventory
- `--camp-chest` — camp chest contents

Shortcuts:

- `--party` — expands to `--characters --equipment --spells` (the active party,
  matching the old default report; no camp, no quests, no vendors)
- `--all` — turns on every group flag, including the gather-gated ones
  (`--quests`, `--vendors`, `--all-items`) and all camp flags. Literally
  everything; slower because of the gather-gated sections.

## Framing rule

The character name is the frame for any per-character content. The identity
lines (race/class/level/...) belong to `--characters`; gear, spells, and
carried are independent of it.

- `--equipment` alone renders each active party member's name followed by their
  worn gear, with no identity lines.
- The `PARTY CHARACTERS` section header renders only if at least one of
  `--characters`, `--equipment`, `--spells`, `--carried` is active.
- The `CAMP COMPANIONS` section header renders only if at least one of
  `--camp-characters`, `--camp-equipment`, `--camp-spells`, `--camp-carried` is
  active.
- The `CAMP CHEST` section renders only with `--camp-chest`.

A per-character group with no identity flag still shows the name as a header so
the gear/spells have an owner.

## Gating: gather vs render

Two distinct gates, already partly present in the code:

- Gather-gated (real parse cost): `--quests` (Osiris), `--vendors`,
  `--all-items`. The flag triggers both the gather in `gather_report` and the
  display. Unchanged from today.
- Render-gated (cheap, gathered regardless): the per-character party data
  (identity, equipment, spells, carried), camp companions, and the camp chest
  are all already gathered during the normal party/camp parse. These groups are
  selected purely at render time in `render_text`.

`--all` sets the gather-gated opts as well, so the expensive sections are
actually parsed when it is used. `--party` sets only render-gated flags and
adds no parse cost.

## Affected code

- `bg3parser/cli.py` — argparse definitions: add the new flags, the `--party`
  and `--all` shortcuts, expand the shortcuts after parsing, remove
  `--no-spells`, rewrite the epilog/help text.
- `bg3parser/render.py` — `render_text`: build the `opts_dict` from the new
  flags; pass per-group booleans through to the template. Compute the
  bare-command header and the "no flags" hint.
- `bg3parser/templates/report.txt.j2` and `character.txt.j2` — gate each
  section/sub-section on its group flag; render the always-on header; render
  the section headers only when their group is active; replace the `no_spells`
  inversion with a positive `spells` check.
- `bg3parser/model.py` — `gather_report`: ensure `--all` triggers the
  gather-gated paths. The gather gates for quests/vendors/all-items stay as is.
- Tests — update CLI/render tests that assume the old default; add coverage for
  the new flag combinations and the bare-command header.

## Parity with the website

`render_text` is mirrored in the TypeScript site so the site's text download is
byte-identical to the CLI. The website shows a full report and exposes no flags.

To keep the download unchanged, the TS renderer passes a fixed group set
equivalent to the report the site shows today (party identity + equipment +
spells + camp companions + camp chest + quests + save metadata — confirm the
exact set against the current site output during implementation). Any CLI-vs-TS
byte-identity parity test is updated to compare against that fixed invocation
rather than the bare default. The site's displayed output does not change.

## Out of scope

- No `--camp` shortcut (camp groups are requested individually); add later if
  wanted.
- No change to `--json` (it already emits everything gathered, with no
  display-side folding).
- No change to `--inspect`, `--thumbnail`, `--verbose`, `--all-spells`.
