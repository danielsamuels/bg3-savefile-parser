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

## The header

Printed on every invocation, immediately after the existing banner, from
`report.save_info` (always gathered) and the active-party list. Exact format,
which both the Python and TS renderers must produce identically:

```
BG3 Save File Report
Source: <path>
========================================================================
Save: <save_name> (#<save_id>)   Region: <level>   Saved: <saved_at>
Party: <name>, <name>, ...
```

`save_name`, `save_id`, `level` (the current region/act), and `saved_at` come
from `report.save_info`; the `Party:` names are the active (not-at-camp)
characters in model order. There is no in-game clock field, so `Saved:` is the
save's real-world timestamp.

When no group flag is given, a hint block follows the header:

```

No sections selected. Try --party (the classic report) or --all (everything),
or pick groups: --characters --equipment --spells --carried
                --camp-characters --camp-equipment --camp-spells --camp-carried
                --camp-chest --save-info --quests --vendors --all-items --limits
```

The hint is suppressed when any group flag is active. The website always
renders a full report, so it never emits the hint; the two header lines are the
shared, byte-identical part (see Parity).

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

- `bg3parser/sections.py` (new) — the canonical group-flag registry
  (`PARTY_GROUPS`, `CAMP_COMPANION_GROUPS`, `TOPLEVEL_GROUPS`, `ALL_GROUPS`,
  `PARTY_SHORTCUT`) plus `expand_shortcuts(opts)`, `any_party_group(opts)`,
  `any_camp_companion_group(opts)`, `no_groups_selected(opts)`. Shared by the
  CLI and the renderer so the flag list lives in exactly one place.
- `bg3parser/cli.py` — argparse definitions: add the new flags, the `--party`
  and `--all` shortcuts, call `expand_shortcuts` after parsing, remove
  `--no-spells`, rewrite the epilog/help text.
- `bg3parser/render.py` — `render_text`: build the `opts_dict` from the new
  flags; pass per-group booleans through to the template. Compute the
  bare-command header and the "no flags" hint.
- `bg3parser/templates/report.txt.j2` and `character.txt.j2` — gate each
  section/sub-section on its group flag; render the always-on header; render
  the section headers only when their group is active; replace the `no_spells`
  inversion with a positive `spells` check.
- `bg3parser/model.py` — no change. `--all` triggers the gather-gated paths
  because `expand_shortcuts` (in `cli.py`) sets `quests`/`vendors`/`all_items`
  to True before `gather_report` reads them; the existing gather gates stand.
- `ts/site/src/textReport.ts` — add the two header lines to `renderTextReport`
  (see Parity).
- Tests — update CLI/render tests that assume the old default; regenerate the
  golden fixtures; add coverage for the new flag combinations, the shortcuts,
  and the header/hint.

## Parity with the website

`render_text` is mirrored by `ts/site/src/textReport.ts`
(`renderTextReport(report)`), which takes no flags and always renders a full
report (save metadata, quests, party, camp companions, camp chest, carried).
There is no automated byte-identity test between the two; the mirror is
maintained by hand, and byte-identity holds for the matching full CLI
invocation, not the bare default (the TS side already always shows the full
`save_info` block, which the Python default does not).

The only TS change required is to add the two header lines (`Save: ...` /
`Party: ...`) immediately after the `BAR_EQ` separator, byte-for-byte identical
to the Python header, so the matching CLI invocation and the website download
stay consistent. The TS side never emits the no-sections hint (it always has
sections). No other TS change is needed; the model and JSON parity oracle are
untouched.

## Out of scope

- No `--camp` shortcut (camp groups are requested individually); add later if
  wanted.
- No change to `--json` (it already emits everything gathered, with no
  display-side folding).
- No change to `--inspect`, `--thumbnail`, `--verbose`, `--all-spells`.
