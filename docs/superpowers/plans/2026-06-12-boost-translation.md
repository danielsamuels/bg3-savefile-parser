# Boost Translation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Translate raw boost functor strings ("Resistance(Fire, Resistant)") into tooltip-style English ("Resistance to Fire damage") at gamedata build time, so the MCP report and the site show readable effect lines.

**Architecture:** A new pure-Python translator module (`bg3parser/boosts.py`) is called by `build_effects_map()` in `bg3parser/effects.py` while building `data/effects.json`. The artifact's `boosts` field becomes a list of translated lines, with the original functor string kept in `boosts_raw`. Consumers (Python `Effects.lines()`, TS `effectLines()`) just print the lines; no translation logic exists in TypeScript.

**Tech Stack:** Python 3 (uv, pytest, ruff), TypeScript (Bun workspace, vitest, biome). Spec: `docs/superpowers/specs/2026-06-12-boost-translation-design.md`.

**Conventions that apply to every commit here:**
- Pre-commit hooks run ruff and biome automatically; if a hook reformats, re-add and re-commit.
- Commit messages are plain sentences in the repo's existing style (look at `git log --oneline`), no `feat:` prefixes.
- Work directory is the repo root `/var/home/dan/Documents/GitHub/bg3-savefile-parser` unless a step says otherwise.

---

### Task 1: The translator module (`bg3parser/boosts.py`)

A pure function from a raw boost string to English display lines. No game-data access; spell and passive display names arrive as plain dicts.

**Files:**
- Create: `tests/test_boosts.py`
- Create: `bg3parser/boosts.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_boosts.py` with exactly:

```python
"""translate_boosts: functor strings to tooltip-style English."""

import pytest

from bg3parser.boosts import translate_boosts

CASES = [
    ('AC(1)', ['+1 Armour Class']),
    ('Ability(Charisma, 2, 22)', ['+2 Charisma (up to 22)']),
    ('Ability(Charisma, -1)', ['-1 Charisma']),
    ('Ability(Constitution, 2, 20, true)', ['+2 Constitution (up to 20)']),
    ('AbilityOverrideMinimum(Intelligence,19)', ['Raises Intelligence to 19 (unless higher)']),
    ('Advantage(Skill,Perception)', ['Advantage on Perception checks']),
    ('Advantage(SavingThrow, Constitution)', ['Advantage on Constitution saving throws']),
    ('Disadvantage(Skill,Stealth)', ['Disadvantage on Stealth checks']),
    ('Skill(Perception,2)', ['+2 to Perception checks']),
    ('RollBonus(SavingThrow, 1, Strength)', ['+1 to Strength saving throws']),
    ('RollBonus(SavingThrow, 1)', ['+1 to saving throws']),
    ('Resistance(Fire, Resistant)', ['Resistance to Fire damage']),
    ('Resistance(Bludgeoning, Vulnerable)', ['Vulnerable to Bludgeoning damage']),
    ('IgnoreResistance(Piercing,Resistant)', ['Ignores Piercing resistance']),
    ('WeaponEnchantment(2)', ['Weapon enchantment +2']),
    ('WeaponProperty(Magical)', ['Magical weapon']),
    ('WeaponDamage(1d10, Necrotic)', ['Extra 1d10 Necrotic damage']),
    ('CharacterWeaponDamage(1d6,Necrotic)', ['Extra 1d6 Necrotic damage']),
    ('Proficiency(Battleaxes)', ['Proficiency with Battleaxes']),
    ('ProficiencyBonus(SavingThrow,Wisdom)', ['Add proficiency bonus to Wisdom saving throws']),
    ('SpellSaveDC(1)', ['+1 Spell Save DC']),
    ('ActionResource(Movement,3,0)', ['+3m movement speed']),
    ('StatusImmunity(BURNING)', ['Immune to BURNING']),
    ('IgnoreFallDamage()', ['Immune to fall damage']),
    ('FallDamageMultiplier(0)', ['No fall damage']),
    ('CannotBeDisarmed()', ['Cannot be disarmed']),
    ('Invulnerable()', ['Invulnerable']),
    ('ItemReturnToOwner()', ['Returns to its owner when thrown']),
    # Bookkeeping the game never shows is suppressed outright.
    ('Tag(CAMPSUPPLIES)', []),
    ('HiddenDuringCinematic()', []),
    ('CriticalHit(AttackTarget,Failure,Never);CriticalHit(AttackTarget,Success,Never)', []),
    # Unknown functors and odd records fall back to their raw text.
    ('DamageReduction(All, Threshold, 1000)', ['DamageReduction(All, Threshold, 1000)']),
    ('CriticalHit(AttackRoll,Success,Always)', ['CriticalHit(AttackRoll,Success,Always)']),
    ('Advantage(AllAbilities)', ['Advantage(AllAbilities)']),
    ('NotAFunctor', ['NotAFunctor']),
]


@pytest.mark.parametrize(('raw', 'expected'), CASES)
def test_translate_boosts(raw, expected):
    assert translate_boosts(raw) == expected


def test_spell_names_and_multi_segment():
    lines = translate_boosts(
        'UnlockSpell(Shout_BootsOfSpeed);Resistance(Cold, Resistant);Tag(X)',
        spell_names={'Shout_BootsOfSpeed': 'Click Heels'},
    )
    assert lines == ['Grants spell: Click Heels', 'Resistance to Cold damage']


def test_unlock_spell_falls_back_to_stats_name():
    assert translate_boosts('UnlockSpell(Target_Mystery)') == ['Grants spell: Target_Mystery']


def test_known_conditions_become_parentheticals():
    known = translate_boosts(
        "IF(not HasPassive('MediumArmorMaster', context.Source)):Disadvantage(Skill,Stealth)",
        passive_names={'MediumArmorMaster': 'Medium Armour Master'},
    )
    assert known == ['Disadvantage on Stealth checks (unless you have Medium Armour Master)']
    positive = translate_boosts("IF(HasPassive('X', context.Source)):AC(1)")
    assert positive == ['+1 Armour Class (if you have X)']
    conc = translate_boosts('IF(IsConcentrating(context.Source)):WeaponDamage(1d4,Poison)')
    assert conc == ['Extra 1d4 Poison damage (while concentrating)']


def test_unknown_conditions_keep_their_raw_text():
    lines = translate_boosts(
        "IF (Tagged('ACT2_TWN_HOSPITAL_NURSE',context.Source)):UnlockSpell(Target_Surgery)"
    )
    assert lines == [
        "If Tagged('ACT2_TWN_HOSPITAL_NURSE',context.Source): Grants spell: Target_Surgery"
    ]


def test_empty_and_blank_input():
    assert translate_boosts('') == []
    assert translate_boosts(' ; ; ') == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_boosts.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'bg3parser.boosts'`.

- [ ] **Step 3: Write the translator**

Create `bg3parser/boosts.py` with exactly:

```python
"""Boost functors rendered as the English a tooltip would show.

The game's stat files describe item mechanics as functor strings
("AC(1);UnlockSpell(Shout_BootsOfSpeed)"). translate_boosts() turns one
into display lines ("+1 Armour Class", "Grants spell: Click Heels").
Bookkeeping the game never surfaces (Tag, HiddenDuringCinematic, the
can't-be-crit pair on world objects) is suppressed; functors and IF()
conditions outside the known vocabulary fall back to their raw text so
nothing disappears silently. Build-time only: effects.py calls this while
building effects.json, where spell and passive display names are at hand.
"""

import re

FUNCTOR_RE = re.compile(r'(\w+)\s*\((.*)\)$', re.DOTALL)

HAS_PASSIVE_RE = re.compile(r"(not\s+)?HasPassive\(\s*'([^']+)'\s*,\s*context\.Source\s*\)")

ROLL_TARGETS = {
    'SavingThrow': 'saving throws',
    'Attack': 'attack rolls',
    'MeleeWeaponAttack': 'melee attack rolls',
    'RangedWeaponAttack': 'ranged attack rolls',
    'SkillCheck': 'skill checks',
    'RawAbility': 'ability checks',
}

RESIST_STATES = {
    'Resistant': 'Resistance to {0} damage',
    'Vulnerable': 'Vulnerable to {0} damage',
    'Immune': 'Immunity to {0} damage',
}


def split_top(raw: str, sep: str = ';') -> list[str]:
    """Split on top-level separators (functor args nest in parentheses)."""
    parts, depth, cur = [], 0, ''
    for ch in raw:
        if ch == sep and depth == 0:
            parts.append(cur)
            cur = ''
            continue
        depth += ch == '('
        depth -= ch == ')'
        cur += ch
    if cur.strip():
        parts.append(cur)
    return parts


def peel_condition(seg: str) -> tuple[str | None, str]:
    """('cond', 'Functor(...)') from 'IF(cond):Functor(...)', else (None, seg)."""
    m = re.match(r'IF\s*\(', seg)
    if not m:
        return None, seg
    depth, i = 1, m.end()
    while i < len(seg) and depth:
        depth += seg[i] == '('
        depth -= seg[i] == ')'
        i += 1
    rest = seg[i:].lstrip()
    if depth or not rest.startswith(':'):
        return None, seg
    return seg[m.end() : i - 1].strip(), rest[1:].strip()


def translate_condition(cond: str, passive_names: dict[str, str]) -> str | None:
    """English for a known IF() condition, None outside the vocabulary."""
    m = HAS_PASSIVE_RE.fullmatch(cond)
    if m:
        name = passive_names.get(m.group(2), m.group(2))
        return ('unless you have ' if m.group(1) else 'if you have ') + name
    if re.fullmatch(r'IsConcentrating\(\s*context\.Source\s*\)', cond):
        return 'while concentrating'
    return None


def signed(n: str) -> str:
    return n if n.startswith(('-', '+')) else f'+{n}'


def suppressed(fn: str, args: list[str]) -> bool:
    """Boosts the game itself never shows on a tooltip."""
    if fn in ('Tag', 'HiddenDuringCinematic'):
        return True
    return fn == 'CriticalHit' and len(args) == 3 and args[0] == 'AttackTarget' and args[2] == 'Never'


def render_functor(fn: str, args: list[str], spell_names: dict[str, str]) -> str | None:
    """English for a known functor, None when outside the vocabulary."""
    try:
        if fn == 'AC':
            return f'{signed(args[0])} Armour Class'
        if fn == 'Ability':
            line = f'{signed(args[1])} {args[0]}'
            if len(args) > 2 and args[2]:
                line += f' (up to {args[2]})'
            return line
        if fn == 'AbilityOverrideMinimum':
            return f'Raises {args[0]} to {args[1]} (unless higher)'
        if fn in ('Advantage', 'Disadvantage'):
            if args[0] == 'Skill':
                return f'{fn} on {args[1]} checks'
            if args[0] == 'SavingThrow':
                what = f'{args[1]} saving throws' if len(args) > 1 else 'saving throws'
                return f'{fn} on {what}'
            return None
        if fn == 'Skill':
            return f'{signed(args[1])} to {args[0]} checks'
        if fn == 'RollBonus':
            what = ROLL_TARGETS.get(args[0], f'{args[0]} rolls')
            if args[0] == 'SavingThrow' and len(args) > 2:
                what = f'{args[2]} saving throws'
            return f'{signed(args[1])} to {what}'
        if fn == 'Resistance':
            tpl = RESIST_STATES.get(args[1])
            return tpl.format(args[0]) if tpl else None
        if fn == 'IgnoreResistance':
            return f'Ignores {args[0]} resistance'
        if fn == 'UnlockSpell':
            return f'Grants spell: {spell_names.get(args[0], args[0])}'
        if fn == 'WeaponEnchantment':
            return f'Weapon enchantment +{args[0]}'
        if fn == 'WeaponProperty':
            return 'Magical weapon' if args[0] == 'Magical' else None
        if fn in ('WeaponDamage', 'CharacterWeaponDamage'):
            dtype = f' {args[1]}' if len(args) > 1 else ''
            return f'Extra {args[0]}{dtype} damage'
        if fn == 'Proficiency':
            return f'Proficiency with {args[0]}'
        if fn == 'ProficiencyBonus':
            return f'Add proficiency bonus to {args[1]} saving throws' if args[0] == 'SavingThrow' else None
        if fn == 'SpellSaveDC':
            return f'{signed(args[0])} Spell Save DC'
        if fn == 'ActionResource':
            return f'{signed(args[1])}m movement speed' if args[0] == 'Movement' else None
        if fn == 'StatusImmunity':
            return f'Immune to {args[0]}'
        if fn == 'IgnoreFallDamage':
            return 'Immune to fall damage'
        if fn == 'FallDamageMultiplier':
            return 'No fall damage' if args[0] == '0' else None
        if fn == 'CannotBeDisarmed':
            return 'Cannot be disarmed'
        if fn == 'Invulnerable':
            return 'Invulnerable'
        if fn == 'ItemReturnToOwner':
            return 'Returns to its owner when thrown'
    except IndexError:
        return None
    return None


def translate_boosts(
    raw: str,
    spell_names: dict[str, str] | None = None,
    passive_names: dict[str, str] | None = None,
) -> list[str]:
    """The raw Boosts field as display lines; suppressed entries drop out."""
    spell_names = spell_names or {}
    passive_names = passive_names or {}
    out: list[str] = []
    for seg in split_top(raw):
        seg = seg.strip()
        if not seg:
            continue
        cond, body = peel_condition(seg)
        m = FUNCTOR_RE.fullmatch(body)
        if m:
            arg_text = m.group(2).strip()
            args = [a.strip() for a in split_top(arg_text, ',')] if arg_text else []
            if suppressed(m.group(1), args):
                continue
            line = render_functor(m.group(1), args, spell_names) or body
        else:
            line = body
        if cond is not None:
            known = translate_condition(cond, passive_names)
            line = f'{line} ({known})' if known else f'If {cond}: {line}'
        out.append(line)
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_boosts.py -q`
Expected: all pass (about 44 including parametrize cases).

- [ ] **Step 5: Lint and commit**

```bash
uvx ruff check bg3parser/boosts.py tests/test_boosts.py
git add bg3parser/boosts.py tests/test_boosts.py
git commit -m "Boost functor translator: stat-file syntax to tooltip English"
```

---

### Task 2: Wire translation into the effects build (`bg3parser/effects.py`)

`build_effects_map()` gains spell and passive display-name tables and stores translated `boosts` lines plus `boosts_raw`. `Effects.lines()` emits the lines directly. The generic semicolon splitter moves to boosts.py (one copy).

**Files:**
- Modify: `bg3parser/effects.py`

- [ ] **Step 1: Imports, schema bump, spell-file regex**

In `bg3parser/effects.py`:

Add after the existing `from .lspk import ...` import (line 33):

```python
from .boosts import split_top, translate_boosts
```

Change `EFFECTS_SCHEMA_VERSION = 1` to:

```python
EFFECTS_SCHEMA_VERSION = 2
```

Add below `PASSIVE_STATUS_FILE_RE` (line 38):

```python
SPELL_FILE_RE = re.compile(r'/Stats/Generated/Data/Spell_.*\.txt$')
```

- [ ] **Step 2: Replace split_params with the shared splitter**

Delete the whole `split_params` function (lines 94-107, including its docstring). In `localized_effect`, change:

```python
    params = split_params(fields.get('DescriptionParams', ''))
```

to:

```python
    params = split_top(fields.get('DescriptionParams', ''))
```

(`split_top` keeps empty middle parts exactly like `split_params` did, so positional `[1]`/`[2]` placeholder replacement is unchanged.)

Update the module docstring's boosts bullet (lines 10-11) to:

```python
- `Boosts` / `DefaultBoosts`: machine-readable functor strings ("AC(1)",
  "UnlockSpell(Target_MistyStep)"), translated to tooltip English by
  boosts.translate_boosts; the raw string is kept under `boosts_raw`.
```

- [ ] **Step 3: Collect spell stat entries in the pak loop**

In `build_effects_map`, after `effects_src: dict[str, dict[str, str]] = {}` add:

```python
    spells_src: dict[str, dict[str, str]] = {}
```

In the file loop, extend the target selection:

```python
            target = None
            if STAT_ITEM_FILE_RE.search(f):
                target = items
            elif PASSIVE_STATUS_FILE_RE.search(f):
                target = effects_src
            elif SPELL_FILE_RE.search(f):
                target = spells_src
            if target is None:
                continue
```

- [ ] **Step 4: Build display-name tables and translate**

Add a module-level helper after `chain_field`:

```python
def display_names(entries: dict[str, dict], handle_to_text: dict[str, str]) -> dict[str, str]:
    """{stats name: localized DisplayName}, following the `using` chain."""
    out: dict[str, str] = {}
    for name in entries:
        handle = (chain_field(entries, name, 'DisplayName') or '').split(';')[0]
        txt = handle_to_text.get(handle)
        if txt:
            out[name] = txt
    return out
```

In `build_effects_map`, after the pak loop and before `out: dict[str, dict] = {}`:

```python
    spell_names = display_names(spells_src, handle_to_text)
    passive_names = display_names(effects_src, handle_to_text)
```

Replace the boosts block:

```python
        boosts = ';'.join(
            b
            for b in (chain_field(items, name, 'Boosts'), chain_field(items, name, 'DefaultBoosts'))
            if b
        )
        if boosts:
            rec['boosts'] = boosts
```

with:

```python
        boosts = ';'.join(
            b
            for b in (chain_field(items, name, 'Boosts'), chain_field(items, name, 'DefaultBoosts'))
            if b
        )
        if boosts:
            rec['boosts_raw'] = boosts
            lines = translate_boosts(boosts, spell_names, passive_names)
            if lines:
                rec['boosts'] = lines
```

- [ ] **Step 5: Emit translated lines from Effects.lines()**

Replace in `Effects.lines`:

```python
        if 'boosts' in rec:
            out.append(f'Boosts: {rec["boosts"]}')
```

with:

```python
        boosts = rec.get('boosts')
        if isinstance(boosts, list):  # legacy artifacts held a raw string here
            out.extend(boosts)
```

Also update the docstring of `build_effects_map` (line 149) to:

```python
    """{stats name: {passives, statuses, boosts, boosts_raw, damage, ac}} from game data."""
```

- [ ] **Step 6: Run the Python suite (old artifact still loads cleanly)**

Run: `BG3_EFFECTS_JSON=data/effects.json uv run pytest tests/ -q`
Expected: all pass. (`Effects.lines` skips the legacy string `boosts`, so nothing asserts on raw boost text any more; `test_item_effects_table` checks passives and damage lines only.)

Also: `uvx ruff check bg3parser/ tests/ && uv run ty check bg3parser`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add bg3parser/effects.py
git commit -m "Effects build translates boosts; raw functors move to boosts_raw"
```

---

### Task 3: Regenerate the artifacts and pin the translations with tests

**Files:**
- Modify: `data/effects.json`, `ts/site/public/effects.json` (generated)
- Possibly modified as a no-op: `data/gamedata.json`, `ts/site/public/gamedata.json`
- Modify: `tests/test_parser.py` (extend `test_item_effects_table`, add sweep test)

- [ ] **Step 1: Regenerate from the local install**

Run: `uv run python tests/generate_gamedata.py`
Expected: four `wrote ...` lines. If it exits with `No BG3 install found`, stop and report; do not hand-edit the JSON.

- [ ] **Step 2: Eyeball the new records**

Run:

```bash
python3 - <<'EOF'
import json
d = json.load(open('data/effects.json'))
for k in ('UNI_RobeOfSummer', 'ARM_BootsOfSpeed', 'DEN_HellridersPride', 'ARM_ChainMail_Body'):
    print(k, '=>', {f: d[k][f] for f in d[k] if f in ('boosts', 'boosts_raw')})
EOF
```

Expected output (whitespace inside `boosts_raw` may differ):

```
UNI_RobeOfSummer => {'boosts': ['Resistance to Cold damage'], 'boosts_raw': 'Resistance(Cold, Resistant)'}
ARM_BootsOfSpeed => {'boosts': ['Grants spell: Click Heels'], 'boosts_raw': 'UnlockSpell(Shout_BootsOfSpeed)'}
DEN_HellridersPride => {'boosts': ['+1 to Strength saving throws'], 'boosts_raw': 'RollBonus(SavingThrow, 1, Strength)'}
ARM_ChainMail_Body => {'boosts': ['Disadvantage on Stealth checks'], 'boosts_raw': 'Disadvantage(Skill,Stealth)'}
```

If a record disagrees, debug the translator before continuing.

- [ ] **Step 3: Extend test_item_effects_table and add the sweep test**

In `tests/test_parser.py`, find `test_item_effects_table` (around line 1392) and append to its body:

```python
    # Boosts arrive translated; the raw functor string rides alongside.
    rec = fx.for_stats('UNI_RobeOfSummer')
    assert rec['boosts'] == ['Resistance to Cold damage']
    assert rec['boosts_raw'].replace(' ', '') == 'Resistance(Cold,Resistant)'
    assert 'Grants spell: Click Heels' in fx.lines('ARM_BootsOfSpeed')
```

Add a new test directly after it:

```python
def test_committed_boosts_have_no_untranslated_vocabulary():
    """Functors the translator claims to know must never fall back to raw."""
    from bg3parser.effects import Effects

    fx = Effects.load()
    if not fx.available:
        pytest.skip('no game install or BG3_EFFECTS_JSON')
    known = re.compile(
        r'^(?:AC|Ability|AbilityOverrideMinimum|Resistance|UnlockSpell|Skill'
        r'|RollBonus|WeaponEnchantment|Proficiency|SpellSaveDC|StatusImmunity)\('
    )
    for stats, rec in fx.table.items():
        for ln in rec.get('boosts', []):
            assert not known.match(ln), f'{stats}: untranslated boost {ln!r}'
```

(`re` and `pytest` are already imported at the top of test_parser.py.)

- [ ] **Step 4: Run the suite against the regenerated artifact**

Run: `BG3_EFFECTS_JSON=data/effects.json uv run pytest tests/ -q`
Expected: all pass. A failure in the sweep test means a real item uses a known functor with an arg shape the translator missed: extend `render_functor` (and `tests/test_boosts.py` with the new case), regenerate, rerun.

- [ ] **Step 5: Commit**

```bash
git add data/effects.json ts/site/public/effects.json data/gamedata.json ts/site/public/gamedata.json tests/test_parser.py
git commit -m "Regenerate effects.json with translated boost lines"
```

(If `git status` shows the gamedata.json pair unchanged, the add is a no-op; that's fine.)

---

### Task 4: TypeScript consumer (`ts/site/src/effects.ts`)

**Files:**
- Modify: `ts/site/src/effects.ts`
- Create: `ts/site/test/effects.test.ts`

- [ ] **Step 1: Write the failing test**

Create `ts/site/test/effects.test.ts` with exactly:

```typescript
import { describe, expect, it } from 'vitest';
import { type EffectsTable, effectLines } from '../src/effects.ts';

describe('effect lines', () => {
  it('renders translated boost lines after damage and AC', () => {
    const table: EffectsTable = {
      robe: {
        boosts: ['Resistance to Cold damage'],
        boosts_raw: 'Resistance(Cold, Resistant)',
        ac: 10,
      },
    };
    expect(effectLines(table, 'robe')).toEqual([
      'Armour Class: 10',
      'Resistance to Cold damage',
    ]);
  });

  it('skips legacy string boosts from stale artifacts', () => {
    const table = { old: { boosts: 'AC(1)' } } as unknown as EffectsTable;
    expect(effectLines(table, 'old')).toEqual([]);
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd ts/site && bun x vitest run test/effects.test.ts`
Expected: FAIL (boosts render as `Boosts: ...` string, and the type of `boosts` mismatches).

- [ ] **Step 3: Update the consumer**

In `ts/site/src/effects.ts`, change the `EffectRecord` interface:

```typescript
export interface EffectRecord {
  passives?: EffectText[];
  statuses?: EffectText[];
  /** Translated display lines; legacy artifacts held a raw functor string. */
  boosts?: string[];
  boosts_raw?: string;
  damage?: string;
  ac?: number | string;
}
```

and replace the boosts line in `effectLines`:

```typescript
  if (rec.boosts) out.push(`Boosts: ${rec.boosts}`);
```

with:

```typescript
  if (Array.isArray(rec.boosts)) out.push(...rec.boosts);
```

- [ ] **Step 4: Run the TS checks**

```bash
cd ts/site && bun x vitest run && bun run typecheck
cd ../.. && bunx biome ci ts
```

Expected: all tests pass (existing search.test.ts asserts only on `Damage:` and passive lines, which are unchanged), typecheck and biome clean.

- [ ] **Step 5: Commit**

```bash
git add ts/site/src/effects.ts ts/site/test/effects.test.ts
git commit -m "Site shows translated boost lines from the new effects schema"
```

---

### Task 5: Docs and push

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `bg3parser/mcp_server.py` (item_info docstring, around line 191)

- [ ] **Step 1: CHANGELOG entry**

Under `## Unreleased` / `### Changed` in `CHANGELOG.md`, add as the first bullet:

```markdown
- **Boosts in plain English**: item boost functors ("Resistance(Fire,
  Resistant)", "UnlockSpell(Target_MAG_HuntersMark_Grymskull)") are now
  translated at gamedata build time into the lines a tooltip would show
  ("Resistance to Fire damage", "Grants spell: Hunter's Mark"), with
  spell and passive names resolved from the game's localisation. The MCP
  report, item_info and the site all print the translated lines; the raw
  functor string stays in effects.json under `boosts_raw`. Internal
  bookkeeping (Tag, HiddenDuringCinematic, the can't-be-crit pair on
  world objects) no longer appears at all.
```

- [ ] **Step 2: MCP docstring touch-up**

In `bg3parser/mcp_server.py`, in the `item_info` docstring, change:

```
    its matches: slot, rarity, and tooltip lines (passives, damage, AC,
    boosts), straight from the installed game's data — the authoritative
```

to:

```
    its matches: slot, rarity, and tooltip lines (passives, damage, AC,
    boosts in plain English), straight from the installed game's data — the
```

(keep the rest of the sentence intact: the next line already continues `answer to ...`).

- [ ] **Step 3: Final full check**

```bash
BG3_EFFECTS_JSON=data/effects.json uv run pytest tests/ -q
uvx ruff check bg3parser/ explore_lsmf.py tests/
cd ts/site && bun x vitest run && bun run typecheck && cd ../..
```

Expected: everything green.

- [ ] **Step 4: Commit and push**

```bash
git add CHANGELOG.md bg3parser/mcp_server.py
git commit -m "Changelog and MCP docs for translated boosts"
git push
```

If the push fails with an SSH auth error, the 1Password agent is locked: leave the commits local and say so in the final report. Dan does not watch CI; do not wait for it.

---

## Self-review notes

- Spec coverage: translator module (Task 1), vocabulary + conditions + suppression (Task 1), spell/passive name tables + schema v2 + boosts_raw (Task 2), Effects.lines and old-artifact tolerance (Task 2), regeneration (Task 3), artifact sanity sweep (Task 3), TS type + Array.isArray guard (Task 4), out-of-scope items untouched.
- The `Boosts:` prefix disappears from both consumers; no other code greps for it (verified with repo-wide search).
- Type consistency: `translate_boosts(raw, spell_names, passive_names)` matches between boosts.py, effects.py and the tests; `boosts: string[]`/`boosts_raw: string` matches the Python record shape.
