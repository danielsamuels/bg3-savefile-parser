# Opt-in Section Flags Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every report grouping opt-in on the `bg3save` CLI, so a user composes exactly the sections they want (e.g. characters + equipped gear, no spells).

**Architecture:** A new `bg3parser/sections.py` holds the canonical group-flag registry and the `--party`/`--all` shortcut expansion, shared by the CLI and the renderer. `cli.py` gains one boolean flag per group plus the two shortcuts and calls the expander after parsing. `render.py` and the Jinja templates gate each section on its individual flag and print an always-on header (save summary + active party), with a hint block when no group is selected. The expensive gather-gated sections (`--quests`, `--vendors`, `--all-items`) are unchanged; the cheap per-character/camp data is gated purely at render time. `ts/site/src/textReport.ts` gains the same two header lines so the website download stays consistent.

**Tech Stack:** Python 3.14, argparse, Jinja2, pytest (golden-file fixtures); TypeScript (Bun/vitest) for the site mirror.

## Global Constraints

- No leading-underscore "private" names on functions or constants (dunder methods are fine).
- Prefer modules and logical structure over single-file designs.
- Prose files (README, help epilog): no em dashes (use colons/semicolons/parentheses); no bold-lead bullet lists; plain copulas; no inflated vocabulary.
- Human-facing names come from the gamedata layer; never synthesize a display name by string-transforming an internal id.
- Commit after every discrete change. End commit messages with the Co-Authored-By / Claude-Session trailer this repo uses.
- The Python header and the TS header must be byte-for-byte identical (see Task 6).
- Golden fixtures are regenerated with `BG3_UPDATE_GOLDEN=1 uv run pytest`; the TS-parity JSON oracle (`tests/generate_parity.py`) is untouched (the model does not change).

---

## File Structure

- `bg3parser/sections.py` (new) — group-flag registry + helpers. One responsibility: define the set of groups and the predicates over an argparse namespace.
- `bg3parser/cli.py` (modify) — argparse flags, shortcut expansion call, help text.
- `bg3parser/render.py` (modify) — `render_text`: build the per-group opts dict, compute header context and section-visibility predicates, pass them to the template.
- `bg3parser/templates/report.txt.j2` (modify) — header + hint; gate the section headers.
- `bg3parser/templates/character.txt.j2` (modify) — gate identity/spells/equipment/carried on per-section `show_*` flags.
- `ts/site/src/textReport.ts` (modify) — mirror the two header lines.
- `tests/test_sections.py` (new) — unit tests for the registry + expansion.
- `tests/test_parser.py` (modify) — fix tests assuming the old default; add flag-combination + header coverage; update `ALL_SECTION_OPTS`.
- `tests/fixtures/expected/*.txt` (regenerate) — `maia_default.txt`, `maia_all_sections.txt`, `shadowheart_default.txt`.
- `README.md` (modify) — CLI flag list and examples.

---

### Task 1: `sections.py` — group-flag registry and shortcut expansion

**Files:**
- Create: `bg3parser/sections.py`
- Test: `tests/test_sections.py`

**Interfaces:**
- Consumes: nothing (pure stdlib; operates on any object with attributes, e.g. an `argparse.Namespace`).
- Produces:
  - `PARTY_GROUPS: tuple[str, ...]` = `('characters', 'equipment', 'spells', 'carried')`
  - `CAMP_COMPANION_GROUPS: tuple[str, ...]` = `('camp_characters', 'camp_equipment', 'camp_spells', 'camp_carried')`
  - `CAMP_CHEST: str` = `'camp_chest'`
  - `TOPLEVEL_GROUPS: tuple[str, ...]` = `('save_info', 'quests', 'vendors', 'all_items', 'limits')`
  - `ALL_GROUPS: tuple[str, ...]` = `PARTY_GROUPS + CAMP_COMPANION_GROUPS + (CAMP_CHEST,) + TOPLEVEL_GROUPS`
  - `PARTY_SHORTCUT: tuple[str, ...]` = `('characters', 'equipment', 'spells')`
  - `expand_shortcuts(opts) -> None` — in place: `--all` sets every `ALL_GROUPS` attr True; `--party` sets every `PARTY_SHORTCUT` attr True.
  - `group_on(opts, name) -> bool` — `bool(getattr(opts, name, False))`
  - `any_party_group(opts) -> bool` — any of `PARTY_GROUPS` on.
  - `any_camp_companion_group(opts) -> bool` — any of `CAMP_COMPANION_GROUPS` on (excludes `camp_chest`).
  - `no_groups_selected(opts) -> bool` — none of `ALL_GROUPS` on.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_sections.py
from argparse import Namespace

from bg3parser import sections


def make(**flags):
    """A namespace with every group flag present, defaulting False."""
    ns = Namespace(all=False, party=False)
    for g in sections.ALL_GROUPS:
        setattr(ns, g, False)
    for k, v in flags.items():
        setattr(ns, k, v)
    return ns


def test_all_groups_partition():
    # camp_chest is its own group; not in the companion set.
    assert sections.CAMP_CHEST not in sections.CAMP_COMPANION_GROUPS
    assert sections.CAMP_CHEST in sections.ALL_GROUPS
    # No duplicates across the registry.
    assert len(sections.ALL_GROUPS) == len(set(sections.ALL_GROUPS))


def test_expand_all_sets_everything():
    ns = make(all=True)
    sections.expand_shortcuts(ns)
    assert all(getattr(ns, g) for g in sections.ALL_GROUPS)


def test_expand_party_sets_only_party_shortcut():
    ns = make(party=True)
    sections.expand_shortcuts(ns)
    assert getattr(ns, 'characters') and getattr(ns, 'equipment') and getattr(ns, 'spells')
    assert not getattr(ns, 'carried')
    assert not getattr(ns, 'quests')


def test_no_groups_selected_true_when_bare():
    assert sections.no_groups_selected(make()) is True


def test_no_groups_selected_false_with_one_flag():
    assert sections.no_groups_selected(make(equipment=True)) is False


def test_any_party_group():
    assert sections.any_party_group(make(equipment=True)) is True
    assert sections.any_party_group(make(camp_equipment=True)) is False


def test_any_camp_companion_group_excludes_chest():
    assert sections.any_camp_companion_group(make(camp_chest=True)) is False
    assert sections.any_camp_companion_group(make(camp_spells=True)) is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_sections.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'bg3parser.sections'`.

- [ ] **Step 3: Write the module**

```python
# bg3parser/sections.py
"""Canonical registry of report group flags, shared by the CLI and renderer.

Each grouping in the text report is opt-in via its own boolean flag on the
argparse namespace. This module is the single place that lists them and knows
how the --party and --all shortcuts expand, so cli.py and render.py never drift.
"""

# Per-character active-party groups (render-gated; data is always gathered).
PARTY_GROUPS = ('characters', 'equipment', 'spells', 'carried')

# Camp companion groups, symmetric to the active party. The camp chest is a
# container, not a per-character group, so it is tracked separately.
CAMP_COMPANION_GROUPS = ('camp_characters', 'camp_equipment', 'camp_spells', 'camp_carried')
CAMP_CHEST = 'camp_chest'

# Top-level groups. save_info/limits are render-gated; quests/vendors/all_items
# carry real gathering cost and are gather-gated in gather_report.
TOPLEVEL_GROUPS = ('save_info', 'quests', 'vendors', 'all_items', 'limits')

ALL_GROUPS = PARTY_GROUPS + CAMP_COMPANION_GROUPS + (CAMP_CHEST,) + TOPLEVEL_GROUPS

# --party reproduces the old default report: active party identity, gear, spells.
PARTY_SHORTCUT = ('characters', 'equipment', 'spells')


def group_on(opts, name: str) -> bool:
    return bool(getattr(opts, name, False))


def expand_shortcuts(opts) -> None:
    """Apply --all and --party to the namespace in place."""
    if getattr(opts, 'all', False):
        for g in ALL_GROUPS:
            setattr(opts, g, True)
    if getattr(opts, 'party', False):
        for g in PARTY_SHORTCUT:
            setattr(opts, g, True)


def any_party_group(opts) -> bool:
    return any(group_on(opts, g) for g in PARTY_GROUPS)


def any_camp_companion_group(opts) -> bool:
    return any(group_on(opts, g) for g in CAMP_COMPANION_GROUPS)


def no_groups_selected(opts) -> bool:
    return not any(group_on(opts, g) for g in ALL_GROUPS)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_sections.py -q`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add bg3parser/sections.py tests/test_sections.py
git commit -m "Add section-flag registry and shortcut expansion

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01EP5b6urrxPn8bV7iQUdn68"
```

---

### Task 2: CLI flags and shortcut wiring

**Files:**
- Modify: `bg3parser/cli.py`
- Test: `tests/test_cli_flags.py` (new)

**Interfaces:**
- Consumes: `sections.expand_shortcuts` from Task 1.
- Produces: an `argparse` parser exposing `--save-info`, `--quests`, `--vendors`, `--all-items`, `--limits`, `--characters`, `--equipment`, `--spells`, `--carried`, `--camp-characters`, `--camp-equipment`, `--camp-spells`, `--camp-carried`, `--camp-chest`, `--party`, `--all`. `--no-spells` is removed. To keep `main()` testable, factor the parser into `build_parser() -> argparse.ArgumentParser`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cli_flags.py
from bg3parser.cli import build_parser
from bg3parser import sections


def parse(argv):
    return build_parser().parse_args(argv)


def test_every_group_has_a_flag():
    p = build_parser()
    opts = p.parse_args(['save.lsv'])
    for g in sections.ALL_GROUPS:
        assert hasattr(opts, g), f'missing flag for group {g}'
        assert getattr(opts, g) is False


def test_party_shortcut_present():
    opts = parse(['save.lsv', '--party'])
    assert opts.party is True


def test_all_shortcut_present():
    opts = parse(['save.lsv', '--all'])
    assert opts.all is True


def test_camp_chest_flag_dest():
    opts = parse(['save.lsv', '--camp-chest'])
    assert opts.camp_chest is True


def test_no_spells_flag_removed():
    import pytest

    with pytest.raises(SystemExit):
        parse(['save.lsv', '--no-spells'])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_cli_flags.py -q`
Expected: FAIL with `ImportError: cannot import name 'build_parser'`.

- [ ] **Step 3: Refactor the parser into `build_parser()` and add the flags**

Extract everything from `ap = argparse.ArgumentParser(...)` through the last `ap.add_argument(...)` into `build_parser()`, returning `ap`. In `main()`, replace that block with `ap = build_parser()` then `opts = ap.parse_args()`. Remove the `--no-spells` argument. Add the new group flags and shortcuts. After `opts = ap.parse_args()`, add `sections.expand_shortcuts(opts)`. Rewrite the epilog. Concretely:

```python
import argparse
import os
import sys

from . import sections
from .discovery import find_latest_save, find_save_by_token
from .lspk import extract_frames, extract_thumbnail
from .model import gather_report
from .render import render_json, render_text


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description='Extract character info from a BG3 .lsv save file.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            'Every section is opt-in. With no group flag, a short header is\n'
            'printed (save summary and active party) plus this hint.\n'
            '\n'
            'Shortcuts:\n'
            '  --party   active party identity, gear, and spells (the classic report)\n'
            '  --all     every section, including the slower ones\n'
            '\n'
            'Active party: --characters --equipment --spells --carried\n'
            'Camp:         --camp-characters --camp-equipment --camp-spells\n'
            '              --camp-carried --camp-chest\n'
            'Top level:    --save-info --quests --vendors --all-items --limits\n'
        ),
    )
    ap.add_argument(
        'save', nargs='?', metavar='save.lsv', help='path to save file (auto-detected if omitted)'
    )
    ap.add_argument(
        'output', nargs='?', metavar='output.txt', help='write report to file (default: stdout)'
    )

    # Shortcuts.
    ap.add_argument('--party', action='store_true', help='= --characters --equipment --spells')
    ap.add_argument('--all', action='store_true', help='turn on every section (slower)')

    # Active party (per-character).
    ap.add_argument('--characters', action='store_true', help='party identity (race, class, level, …)')
    ap.add_argument('--equipment', action='store_true', help='party worn gear')
    ap.add_argument('--spells', action='store_true', help='party spell books')
    ap.add_argument('--carried', action='store_true', help='party carried inventory')

    # Camp.
    ap.add_argument('--camp-characters', action='store_true', help='camp companion identity')
    ap.add_argument('--camp-equipment', action='store_true', help='camp companion worn gear')
    ap.add_argument('--camp-spells', action='store_true', help='camp companion spell books')
    ap.add_argument('--camp-carried', action='store_true', help='camp companion carried inventory')
    ap.add_argument('--camp-chest', action='store_true', help='camp chest contents')

    # Top level.
    ap.add_argument('--save-info', action='store_true', help='save metadata (name, date, mods, …)')
    ap.add_argument('--quests', action='store_true', help='quest and story state (Osiris; adds ~1-2 s)')
    ap.add_argument(
        '--vendors',
        action='store_true',
        help="every merchant's for-sale stock (items generated and not yet bought)",
    )
    ap.add_argument('--all-items', action='store_true', help='full item list for the current level')
    ap.add_argument('--limits', action='store_true', help='known limitations note')

    # Modifiers (unchanged).
    ap.add_argument(
        '--verbose', '-v', action='store_true',
        help='show internal names in parentheses after display names',
    )
    ap.add_argument(
        '--thumbnail', '-t', metavar='PATH', help="write the save's thumbnail image to PATH"
    )
    ap.add_argument(
        '--inspect', metavar='NAME',
        help='show classification signals and ECS components for party items '
        'whose internal stats name contains NAME (case-insensitive)',
    )
    ap.add_argument(
        '--all-spells', action='store_true',
        help='within --spells, list sub-spells and basic actions instead of folding them away',
    )
    ap.add_argument(
        '--json', action='store_true',
        help='emit the report as JSON (machine-readable; includes everything gathered)',
    )
    return ap
```

In `main()`:

```python
def main():
    ap = build_parser()
    opts = ap.parse_args()
    sections.expand_shortcuts(opts)
    # ... rest unchanged (save_path resolution, frames, gather_report, render) ...
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_cli_flags.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add bg3parser/cli.py tests/test_cli_flags.py
git commit -m "Add opt-in section flags and --party/--all shortcuts to the CLI

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01EP5b6urrxPn8bV7iQUdn68"
```

---

### Task 3: Render-side gating, header, and hint

**Files:**
- Modify: `bg3parser/render.py:207-281` (`render_text`)
- Modify: `bg3parser/templates/report.txt.j2`
- Modify: `bg3parser/templates/character.txt.j2`
- Test: covered by Task 4 (existing-test updates) plus new substring tests added here.

**Interfaces:**
- Consumes: `sections.group_on/any_party_group/any_camp_companion_group/no_groups_selected` from Task 1; `report.save_info` (always populated by `gather_report`).
- Produces: text where each section renders only when its flag is on; an always-on header; a hint when no group is selected.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_parser.py`)

```python
def test_bare_report_is_header_and_hint():
    """No flags: header (save summary + party) and the no-sections hint, no body."""
    from argparse import Namespace

    from bg3parser import sections

    opts = Namespace(all=False, party=False, verbose=False, all_spells=False)
    for g in sections.ALL_GROUPS:
        setattr(opts, g, False)
    report = build_report(QUICKSAVE_MAIA, opts=opts)
    assert 'Party: ' in report
    assert 'No sections selected.' in report
    assert 'PARTY CHARACTERS' not in report  # body suppressed
    assert 'Equipped' not in report


def test_equipment_only_shows_gear_no_identity_no_spells():
    from argparse import Namespace

    from bg3parser import sections

    opts = Namespace(all=False, party=False, verbose=False, all_spells=False)
    for g in sections.ALL_GROUPS:
        setattr(opts, g, False)
    opts.equipment = True
    report = build_report(QUICKSAVE_MAIA, opts=opts)
    assert 'PARTY CHARACTERS' in report
    assert 'Maia (player)' in report          # name frames the gear
    assert 'Equipped' in report
    assert 'Spells/Abilities' not in report    # spells off
    assert 'No sections selected.' not in report  # a group is on
    assert '  Race      :' not in report        # identity off
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_parser.py -q -k "bare_report or equipment_only"`
Expected: FAIL (e.g. `'No sections selected.' not in report`, because the old default renders the full body).

- [ ] **Step 3: Rewrite `render_text`**

Replace the body of `render_text` (lines 207-281) with the version below. It drops the `no_spells` key, builds a full per-group opts dict, and computes the header/predicate context.

```python
def render_text(report: SaveReport, opts=None) -> str:
    """Render the model as the classic plain-text report."""
    from . import sections

    def opt(name: str) -> bool:
        return bool(getattr(opts, name.replace('-', '_'), False)) if opts is not None else False

    verbose = opt('verbose')
    all_spells = opt('all-spells')

    chars_data = [
        prepare_char_data(char, verbose=verbose, all_spells=all_spells)
        for char in report.characters
    ]
    level_items_entries = prepare_level_items(report, verbose=verbose)
    vendors_data = prepare_vendors(report, verbose=verbose)

    # Camp chest contents, grouped like a carried inventory.
    camp_chest_groups: list[tuple[str, list[str]]] = []
    if report.camp_chest:
        for key, label in CARRIED_GROUP_LABELS:
            counts: Counter = Counter()
            for i in report.camp_chest:
                if i.category == key:
                    counts[fmt_item(i, verbose)] += i.count
            lines = [f'{lbl} x{n}' if n > 1 else lbl for lbl, n in sorted(counts.items())]
            if lines:
                camp_chest_groups.append((label, lines))

    # Per-group visibility. With no opts (e.g. legacy callers passing None) the
    # report is treated as bare: header + hint only.
    opts_dict = {'verbose': verbose, 'all_spells': all_spells}
    for g in sections.ALL_GROUPS:
        opts_dict[g] = opt(g)

    active_party_names = ', '.join(c.name for c in report.characters if not c.at_camp)

    # Pre-compute values that require Python operators not available in Jinja2.
    quests_version = ''
    if report.quests and not report.quests.get('failed'):
        v = report.quests['version']
        quests_version = f'{v >> 8}.{v & 0xFF}'

    tadpole_summary = ''
    approval_lines: list[str] = []
    if report.story:
        tadpole_summary = ', '.join(f'{t["name"]} x{t["count"]}' for t in report.story['tadpoles'])
        dating = set(report.story['dating'])
        approval_lines = [
            f'{a["name"]:<12}{a["rating"]:>4}' + ('   (dating)' if a['name'] in dating else '')
            for a in report.story['approval']
        ]

    env = make_jinja_env()
    template = env.get_template('report.txt.j2')

    output = template.render(
        report=report,
        opts=opts_dict,
        any_party_group=sections.any_party_group(opts) if opts is not None else False,
        any_camp_companion_group=(
            sections.any_camp_companion_group(opts) if opts is not None else False
        ),
        no_groups=sections.no_groups_selected(opts) if opts is not None else True,
        active_party_names=active_party_names,
        chars_data=chars_data,
        camp_chest_groups=camp_chest_groups,
        level_items_entries=level_items_entries,
        vendors_data=vendors_data,
        vendor_min_stock=VENDOR_MIN_STOCK,
        spells_notes=SPELLS_NOTES,
        equipment_notes=EQUIPMENT_NOTES,
        fmt_item=fmt_item,
        verbose=verbose,
        inspect_pattern=report.inspect_pattern,
        quests_version=quests_version,
        tadpole_summary=tadpole_summary,
        approval_lines=approval_lines,
    )
    return output
```

Note: `sections.any_party_group(opts)` etc. read attributes off the raw namespace, so they need every group attr present. Real CLI namespaces have them (Task 2). Test namespaces set them (the helpers in the tests do). When `opts is None`, the predicates are hard-coded (bare).

- [ ] **Step 4: Rewrite `report.txt.j2`**

```jinja
BG3 Save File Report
Source: {{ report.source }}
========================================================================
Save: {{ report.save_info.save_name }} (#{{ report.save_info.save_id }})   Region: {{ report.save_info.level }}   Saved: {{ report.save_info.saved_at }}
Party: {{ active_party_names }}
{% if no_groups %}

No sections selected. Try --party (the classic report) or --all (everything),
or pick groups: --characters --equipment --spells --carried
                --camp-characters --camp-equipment --camp-spells --camp-carried
                --camp-chest --save-info --quests --vendors --all-items --limits
{% endif %}
{% if opts.save_info and report.save_info is not none %}
{% include 'save_info.txt.j2' %}
{% endif %}
{% if report.quests is not none %}
{% include 'quests.txt.j2' %}
{% endif %}
{% if any_party_group %}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PARTY CHARACTERS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{% for char in report.characters %}
{% set char_data = chars_data[loop.index0] %}
{% if not char.at_camp %}
{% set show_characters = opts.characters %}
{% set show_equipment = opts.equipment %}
{% set show_spells = opts.spells %}
{% set show_carried = opts.carried %}
{% include 'character.txt.j2' %}
{% endif %}
{% endfor %}
{% endif %}
{% if any_camp_companion_group and (report.characters | selectattr('at_camp') | list) %}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CAMP COMPANIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{% for char in report.characters %}
{% set char_data = chars_data[loop.index0] %}
{% if char.at_camp %}
{% set show_characters = opts.camp_characters %}
{% set show_equipment = opts.camp_equipment %}
{% set show_spells = opts.camp_spells %}
{% set show_carried = opts.camp_carried %}
{% include 'character.txt.j2' %}
{% endif %}
{% endfor %}
{% endif %}
{% if opts.camp_chest and report.camp_chest is not none %}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CAMP CHEST  ({{ report.camp_chest | length }} item types)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{% for label, lines in camp_chest_groups %}
  {{ label }}:
{% for line in lines %}
    – {{ line }}
{% endfor %}
{% endfor %}
{% endif %}
{% if opts.all_items and report.level_items is not none %}
{% include 'level_items.txt.j2' %}
{% endif %}
{% if opts.vendors and report.vendors is not none %}
{% include 'vendors.txt.j2' %}
{% endif %}
{% if opts.limits %}
{% include 'limits.txt.j2' %}
{% endif %}
```

Note: `level_items`/`vendors` were previously gated only on `report.* is not none`; since `gather_report` still gathers them only under `--all-items`/`--vendors`, adding the `opts.*` guard is belt-and-suspenders and keeps the gate visible alongside the others.

- [ ] **Step 5: Rewrite `character.txt.j2`** (identity/spells/equipment/carried each gated; name always shown)

```jinja
{{ char.name }}
{% if show_characters %}
  Race      : {{ char.race }}
  Class     : {{ char.classes | map('fmt_class') | join('; ') if char.classes else '?' }}
  Level     : {{ char.level }}
{% if char.xp is not none %}
  XP        : {{ char.xp }}
{% endif %}
{% if char.location %}
  Location  : {{ char.location }}
{% endif %}
{% if char.abilities %}
  Abilities : STR {{ char.abilities.str }}  DEX {{ char.abilities.dex }}  CON {{ char.abilities.con }}  INT {{ char.abilities.int }}  WIS {{ char.abilities.wis }}  CHA {{ char.abilities.cha }}
{% endif %}
{% if char.hp %}
  HP        : {{ char.hp.current }}/{{ char.hp.max }}{{ ' (+' ~ char.hp.temp ~ ' temp)' if char.hp.temp else '' }}
{% endif %}
{% if char_data.resources_line %}
  Resources : {{ char_data.resources_line }}
{% endif %}
{% if char_data.feats_line %}
  Feats     : {{ char_data.feats_line }}
{% endif %}
{% if char_data.reactions_line %}
  Reactions : {{ char_data.reactions_line }}
{% endif %}
{% if char.concentration %}
  Concentrating : {{ char.concentration.name or char.concentration.id }}
{% endif %}
{% endif %}
{% if show_spells and char.spells is not none %}
  Spells/Abilities ({{ char_data.spells_shown | length }}{{ char_data.spells_header_suffix }}):
{% for line in char_data.spells_shown %}
    – {{ line }}
{% endfor %}
{% elif show_spells %}
  Spells/Abilities : {{ spells_notes.get(char.spells_note or 'not-found') }}
{% endif %}
{% if char.inspect %}
  Inspect — items matching {{ inspect_pattern | pyfmt }}:
{% for entry in char.inspect %}
    – {{ entry.stats }}
      eq_bit={{ entry.eq_bit }} flags={{ entry.flags }} mc={{ entry.membership_count }} status={{ entry.has_status }}
      components ({{ entry.components | length }}):
{% for c in entry.components %}
        {{ c }}
{% endfor %}
{% endfor %}
{% endif %}
{% if show_equipment %}
{% if char.equipment_note %}
  Equipment : {{ equipment_notes[char.equipment_note] }}
{% else %}
  Equipped ({{ char.equipped | length }}):
{% for item in char_data.equipped_sorted %}
    – {{ item | fmt_item(verbose) }}{{ '  [' ~ item.slot ~ ']' if item.slot else '' }}
{% endfor %}
{% if char.undetermined %}
  Worn or carried — undetermined ({{ char.undetermined | length }}):
{% for item in char.undetermined %}
    – {{ item | fmt_item(verbose) }}
{% endfor %}
{% endif %}
{% endif %}
{% endif %}
{% if show_carried %}
  Carried / personal inventory ({{ char.carried | length }}):
{% for label, lines in char_data.carried_groups %}
    {{ label }}:
{% for line in lines %}
      – {{ line }}
{% endfor %}
{% endfor %}
{% endif %}
```

- [ ] **Step 6: Run the new tests to verify they pass**

Run: `uv run pytest tests/test_parser.py -q -k "bare_report or equipment_only"`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add bg3parser/render.py bg3parser/templates/report.txt.j2 bg3parser/templates/character.txt.j2 tests/test_parser.py
git commit -m "Gate every report section on its own flag; add header and hint

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01EP5b6urrxPn8bV7iQUdn68"
```

---

### Task 4: Update existing Python tests and regenerate goldens

**Files:**
- Modify: `tests/test_parser.py` (the tests that assumed the old default)
- Regenerate: `tests/fixtures/expected/maia_default.txt`, `maia_all_sections.txt`, `shadowheart_default.txt`

**Interfaces:**
- Consumes: the flags from Task 2, the rendering from Task 3.

These tests currently rely on party identity + gear + spells appearing with no flags. Under opt-in they must request the sections explicitly. A small helper keeps them readable.

- [ ] **Step 1: Add a flags helper and fix the broken tests**

Add near the top of `tests/test_parser.py` (after the imports):

```python
def section_opts(**flags):
    """An argparse-like namespace with every group flag present (default False)."""
    from bg3parser import sections

    ns = Namespace(all=False, party=False, verbose=False, all_spells=False)
    for g in sections.ALL_GROUPS:
        setattr(ns, g, False)
    for k, v in flags.items():
        setattr(ns, k, v)
    return ns
```

Apply these edits:

1. `test_no_spells` -> replace with `test_spells_opt_in`:

```python
def test_spells_opt_in():
    """Spells appear only with --spells; --equipment alone shows gear, not spells."""
    no_spells = build_report(QUICKSAVE_MAIA, opts=section_opts(characters=True, equipment=True))
    assert 'Spells/Abilities' not in no_spells
    assert 'Equipped' in no_spells
    with_spells = build_report(QUICKSAVE_MAIA, opts=section_opts(spells=True))
    assert 'Spells/Abilities' in with_spells
```

2. `test_quests` -> `opts=Namespace(quests=True)` becomes `opts=section_opts(quests=True)`.

3. `test_carried` -> `opts=section_opts(carried=True)`.

4. `test_save_info` -> `opts=section_opts(save_info=True)`.

5. `test_spells_folded_in_text` -> request spells:

```python
def test_spells_folded_in_text():
    report = build_report(QUICKSAVE_MAIA, opts=section_opts(spells=True))
    assert 'heuristic' not in report
    assert 'basic actions' in report
```

6. `test_all_spells_flag` -> spells + all_spells:

```python
def test_all_spells_flag():
    report = build_report(QUICKSAVE_MAIA, opts=section_opts(spells=True, all_spells=True))
    assert 'Spells/Abilities (' in report
    assert 'sub-spells' not in report
    assert 'basic actions' not in report
```

7. `test_smoke_text_output` -> render the classic report via the party shortcut:

```python
def test_smoke_text_output():
    # section_opts does not expand --party, so set the classic-report groups directly.
    report = build_report(
        QUICKSAVE_MAIA, opts=section_opts(characters=True, equipment=True, spells=True)
    )
    assert isinstance(report, str)
    assert len(report) > 1000
    for name in ['Maia (player)', 'Wyll', 'Karlach', 'Shadowheart']:
        assert name in report
```

8. `test_all_items_section` (`opts=Namespace(all_items=True)`) -> `opts=section_opts(all_items=True)`.

9. `test_limits` -> `opts=section_opts(limits=True)`.

10. The two `save_info=True` integration tests around lines 1192 and 1205 -> `section_opts(save_info=True)`.

11. `TestResolvedRender`: every `build_report(QUICKSAVE_MAIA, ...)` that needs character bodies must request them:
    - `test_slot_annotations_present`: `opts=section_opts(equipment=True, verbose=True)`
    - `test_friendly_names_replace_internal`: `opts=section_opts(equipment=True)`
    - `test_spell_folding_in_header`: `opts=section_opts(spells=True)`
    - `test_all_spells_disables_folding`: `opts=section_opts(spells=True, all_spells=True)`

12. `ALL_SECTION_OPTS` -> turn on every group via the registry so the "all sections" golden is genuinely everything:

```python
def all_section_opts():
    from bg3parser import sections

    ns = Namespace(all=False, party=False, verbose=False, all_spells=False)
    for g in sections.ALL_GROUPS:
        setattr(ns, g, True)
    return ns


ALL_SECTION_OPTS = all_section_opts()
```

13. `test_shadowheart_default` golden uses `Namespace(quests=True)` -> `section_opts(quests=True)`.

- [ ] **Step 2: Run the suite to see the golden mismatches (expected)**

Run: `uv run pytest tests/test_parser.py -q`
Expected: the three `TestTextOutputFormat` golden tests FAIL (output legitimately changed: header added, default body removed, all-sections expanded), plus any substring test edited in Step 1 that was not yet updated. Audit finding (verified during planning): only `tests/test_parser.py` renders text and asserts on it; every other test file asserts on the model object or on `render_json` output, both unaffected by display flags. If a later run surfaces a text-asserting test elsewhere, fix it the same way (add `section_opts(...)`); Task 5's full-suite run is the backstop.

- [ ] **Step 3: Regenerate the goldens**

Run: `BG3_UPDATE_GOLDEN=1 uv run pytest tests/test_parser.py -q -k TestTextOutputFormat`
Then inspect the diff:
Run: `git diff -- tests/fixtures/expected/`
Expected: `maia_default.txt` is now header + "No sections selected." hint only; `maia_all_sections.txt` gains camp/spells/equipment sections; `shadowheart_default.txt` is header + quests (no character bodies).

- [ ] **Step 4: Verify the full suite passes**

Run: `uv run pytest tests/test_parser.py -q`
Expected: PASS (all green).

- [ ] **Step 5: Commit**

```bash
git add tests/test_parser.py tests/fixtures/expected/
git commit -m "Update CLI/render tests and goldens for opt-in sections

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01EP5b6urrxPn8bV7iQUdn68"
```

---

### Task 5: Full Python verification

**Files:** none (verification only).

- [ ] **Step 1: Run the entire Python suite**

Run: `uv run pytest -q`
Expected: PASS. If `test_gather_report_model_and_json` or the live-parity tests touch the new flags, reconcile with `section_opts`.

- [ ] **Step 2: Smoke the CLI by hand**

Run: `uv run bg3save 286` -> header + hint, no body.
Run: `uv run bg3save 286 --characters --equipment` -> party names with identity + gear, no spells.
Run: `uv run bg3save 286 --party` -> classic report (identity + gear + spells).
Run: `uv run bg3save 286 --all > /dev/null && echo ok` -> everything, exits 0.
Expected: as described.

- [ ] **Step 3: Commit** (only if Step 1 required a fix; otherwise skip)

---

### Task 6: Mirror the header in the TS site renderer

**Files:**
- Modify: `ts/site/src/textReport.ts:219-233`
- Test: `ts/site/test/textReport.test.ts` (new) or extend `aiBriefing.test.ts`

**Interfaces:**
- Consumes: `report.save_info` (`si`) and `report.characters`, already in scope in `renderTextReport`.
- Produces: the two header lines, byte-identical to the Python header in Task 3.

- [ ] **Step 1: Write the failing test**

```typescript
// ts/site/test/textReport.test.ts
import { describe, expect, it } from 'vitest';
import { renderTextReport } from '../src/textReport.ts';

// Minimal SaveReport stub: only the fields the header reads.
const stub = {
  source: 'QuickSave_1.lsv',
  names_resolved: false,
  save_info: { save_name: 'My Save', save_id: 286, saved_at: '2026-06-22 10:00:00 UTC',
    level: 'WLD_Main_A', game_version: '?', difficulty: '', leader: 'Tav', mods: [] },
  characters: [
    { name: 'Tav (player)', at_camp: false, classes: [], equipped: [], carried: [],
      undetermined: [], spells: null, resources: [], feats: [] },
    { name: 'Shadowheart', at_camp: true, classes: [], equipped: [], carried: [],
      undetermined: [], spells: null, resources: [], feats: [] },
  ],
  camp_chest: null, quests: null, story: null,
} as unknown as Parameters<typeof renderTextReport>[0];

describe('renderTextReport header', () => {
  it('prints the Save and Party summary lines after the banner', () => {
    const text = renderTextReport(stub);
    expect(text).toContain('Save: My Save (#286)   Region: WLD_Main_A   Saved: 2026-06-22 10:00:00 UTC');
    expect(text).toContain('Party: Tav (player)'); // active party only, camp excluded
    expect(text).not.toContain('Shadowheart,'); // camp companion not in the Party line
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd ts && bun run vitest run site/test/textReport.test.ts`
Expected: FAIL (header lines absent).

- [ ] **Step 3: Insert the header lines**

In `renderTextReport`, change the opening `lines` array so the two header lines follow `BAR_EQ`, before the `Save Name :` block:

```typescript
export function renderTextReport(report: SaveReport): string {
  const si = report.save_info;
  const activeParty = report.characters
    .filter((c) => !c.at_camp)
    .map((c) => c.name)
    .join(', ');
  const lines: string[] = [
    'BG3 Save File Report',
    `Source: ${report.source}`,
    BAR_EQ,
    `Save: ${si.save_name} (#${si.save_id ?? '?'})   Region: ${si.level}   Saved: ${si.saved_at}`,
    `Party: ${activeParty}`,
    '',
    `Save Name  : ${si.save_name}`,
    // ... rest unchanged ...
```

Confirm the spacing (three spaces between `Region:`/`Saved:` segments and around them) matches the Python template in Task 3 exactly. There is no `(#?)` mismatch: Python prints `save_id` raw; TS uses `si.save_id ?? '?'`. The Python `save_info['save_id']` defaults to `'?'` when absent (see `gather_report`), so both render `?` for a missing id.

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd ts && bun run vitest run site/test/textReport.test.ts`
Expected: PASS.

- [ ] **Step 5: Run the TS suite and the parser typecheck**

Run: `cd ts && bun run vitest run && bunx tsc -p site/tsconfig.json --noEmit`
Expected: PASS (the `aiBriefing` length test still holds; the header only adds bytes).

- [ ] **Step 6: Commit**

```bash
git add ts/site/src/textReport.ts ts/site/test/textReport.test.ts
git commit -m "Mirror the save/party header line in the site text report

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01EP5b6urrxPn8bV7iQUdn68"
```

---

### Task 7: Update the README CLI section

**Files:**
- Modify: `README.md` (the "## The CLI (Python)" section)

**Interfaces:** none.

- [ ] **Step 1: Rewrite the CLI examples and flag list**

Replace the example block so it reflects opt-in sections. Follow the prose rules (no em dashes, no bold-lead bullets). For example:

````markdown
```sh
# Bare run prints a header (save summary and active party) plus a flag hint:
uv run bg3save 286

# The classic report (active party identity, gear, and spells):
uv run bg3save 286 --party

# Compose exactly what you want, for example characters and their gear only:
uv run bg3save 286 --characters --equipment

# Everything, including the slower quest/vendor parses:
uv run bg3save 286 --all

# Camp companions and the camp chest:
uv run bg3save 286 --camp-characters --camp-equipment --camp-chest

# Other sections: --save-info, --quests, --vendors, --all-items, --limits.
# Machine-readable output:
uv run bg3save 286 --json
```
````

- [ ] **Step 2: Verify prose with the avoid-ai-writing rules**

Re-read the edited section: confirm no em dashes, no `**Thing** —` bullets, plain copulas.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "Document opt-in section flags in the README

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01EP5b6urrxPn8bV7iQUdn68"
```

---

## Notes for the implementer

- `argparse` keeps the destination `all` for `--all` and `all_items` for `--all-items`; `getattr(opts, 'all')` is fine even though `all` shadows the builtin only as an attribute name.
- `expand_shortcuts` runs in `main()` only. Tests that bypass the CLI set the concrete group flags directly (that is what `section_opts` is for); they do not rely on shortcut expansion unless they call `sections.expand_shortcuts` themselves.
- The model (`gather_report`) does not change. The JSON output and the TS-parity JSON oracle are therefore unaffected; do not regenerate `tests/parity/`.
- `--all-spells` is a modifier on `--spells`: with `--all-spells` but no `--spells`, nothing expands because the spell section is not rendered. That is acceptable and matches the help text.
- Keep the `–` (en dash) bullet glyph in the templates as-is; it is the established report style and exempt from the prose em-dash rule (see the repo's avoid-ai-writing note).
