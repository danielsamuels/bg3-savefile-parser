# Boost translation: human-readable item effect lines

Date: 2026-06-12
Status: approved

## Problem

Item effect records carry raw boost functor strings straight from the game's
stat files: `CriticalHit(AttackTarget,Success,Never);Resistance(Fire,
Resistant);UnlockSpell(Target_MAG_HuntersMark_Grymskull)`. They surface
verbatim as `Boosts: ...` lines in the MCP report, item_info, the site's
search results and item tooltips. Agents and humans both have to decode game
syntax.

## Decision summary

Translate at gamedata build time, in Python only. The committed
`data/effects.json` (and its `ts/site/public/` copy) stores ready-made
English lines; consumers just print them. Raw strings stay in the artifact
under a new field for machine consumers and debugging.

Decided with Dan:

- Non-player-facing boosts are suppressed entirely: `Tag(...)`,
  `HiddenDuringCinematic()`, and the `CriticalHit(AttackTarget, *, Never)`
  pair (the "can't be crit" bookkeeping on 1,477 generic world objects).
- `boosts` becomes a list of translated lines; `boosts_raw` keeps the
  original functor string whenever one existed.

## Components

### bg3parser/boosts.py (new, build-time only)

- Split the raw string on top-level semicolons (parenthesis-depth aware,
  same trick as `split_params` in effects.py).
- Peel an optional `IF(cond):` or `IF (cond):` prefix from each segment.
- Parse `Name(arg, arg, ...)` and render through a per-function vocabulary.
- Unknown functors and unknown conditions fall back to the raw segment
  text: nothing is silently dropped except the suppression list above.

Entry point: `translate_boosts(raw: str, spell_names, passive_names) ->
list[str]`.

### Vocabulary

Phrasing follows the game's own tooltip style. The observed corpus (27
functions across 2,376 records) and their renderings:

| Raw | Rendered |
| --- | --- |
| `Resistance(Fire, Resistant)` | Resistance to Fire damage |
| `Resistance(Bludgeoning, Vulnerable)` | Vulnerable to Bludgeoning damage |
| `UnlockSpell(Shout_BootsOfSpeed)` | Grants spell: Boots of Speed |
| `Ability(Charisma, 2, 22)` | +2 Charisma (up to 22) |
| `Ability(Charisma, -1)` | -1 Charisma |
| `AbilityOverrideMinimum(Strength, 20)` | Raises Strength to 20 (unless higher) |
| `RollBonus(SavingThrow, 1, Strength)` | +1 to Strength saving throws |
| `RollBonus(SavingThrow, 1)` | +1 to saving throws |
| `Skill(Perception, 2)` | +2 to Perception checks |
| `Advantage(Skill, Stealth)` | Advantage on Stealth checks |
| `Advantage(SavingThrow, Wisdom)` | Advantage on Wisdom saving throws |
| `Disadvantage(Skill, Stealth)` | Disadvantage on Stealth checks |
| `AC(1)` | +1 Armour Class |
| `WeaponEnchantment(1)` | Weapon enchantment +1 |
| `WeaponProperty(Magical)` | Magical weapon |
| `WeaponDamage(1d6, Necrotic)` | Extra 1d6 Necrotic damage |
| `CharacterWeaponDamage(1d6, Necrotic)` | Extra 1d6 Necrotic damage |
| `Proficiency(Battleaxes)` | Proficiency with Battleaxes |
| `ProficiencyBonus(SavingThrow, Wisdom)` | Add proficiency bonus to Wisdom saving throws |
| `SpellSaveDC(1)` | +1 Spell Save DC |
| `ActionResource(Movement, 3, 0)` | +3m movement speed |
| `StatusImmunity(X)` | Immune to X |
| `IgnoreResistance(Piercing, Resistant)` | Ignores Piercing resistance |
| `IgnoreFallDamage()` | Immune to fall damage |
| `FallDamageMultiplier(0)` | No fall damage |
| `CannotBeDisarmed()` | Cannot be disarmed |
| `Invulnerable()` | Invulnerable |
| `ItemReturnToOwner()` | Returns to its owner when thrown |
| `DamageReduction(...)` | raw fallback (single odd record) |
| `CriticalHit(...)` other than the suppressed Never pair | raw fallback |

Conditions, known set only; anything else renders as `If <raw>: <effect>`:

- `not HasPassive('X', context.Source)`: "unless you have X" (X resolved to
  the passive's display name via the already-loaded passives table)
- `HasPassive('X', context.Source)`: "if you have X"
- `IsConcentrating(context.Source)`: "while concentrating"

### effects.py changes

- `build_effects_map()` also parses `Spell_*.txt` stat files from the same
  paks into {spell stats name: localized DisplayName} for `UnlockSpell`.
- Record schema: `boosts` is now `list[str]` (omitted when every segment
  was suppressed), `boosts_raw` is the original string (present whenever
  the stat entry had one). `EFFECTS_SCHEMA_VERSION = 2` invalidates caches.
- `Effects.lines()` emits each translated line directly, dropping the
  `Boosts:` prefix; the lines read like tooltip text alongside passives.

### Consumers

- MCP server: inherits via `Effects.lines()`, no change.
- TS site (`ts/site/src/effects.ts`): `EffectRecord.boosts` becomes
  `string[]`; `effectLines()` pushes each line. No translation logic in TS,
  so no parity burden.

### Artifact regeneration

`uv run python tests/generate_gamedata.py` rebuilds `data/effects.json` and
the `ts/site/public/effects.json` copy from the local install.

## Error handling

- Translation failures never raise out of the build: a segment that cannot
  be parsed is emitted raw.
- `Effects.load()` already swallows all exceptions; unchanged.
- Old cached effects.json files are invalidated by the schema bump, and a
  consumer reading an old artifact (string `boosts`) must not crash: both
  `Effects.lines()` and the TS `effectLines()` skip a non-list `boosts`.

## Testing

- pytest unit tests for `translate_boosts`: one case per vocabulary row,
  the IF forms, multi-segment strings, suppression, raw fallback.
- Artifact sanity test: after regeneration, no translated line still
  contains `(` -heavy functor syntax except known fallbacks.
- TS: adjust the effects type and any fixture in site tests; typecheck and
  vitest must pass.

## Out of scope

- Runtime translation of boosts not present in the artifact.
- Rewording passive/status descriptions (already localized game text).
- The MCP verbosity follow-ups queued separately (summary-tier dedupe).
