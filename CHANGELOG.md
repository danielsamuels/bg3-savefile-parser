# Changelog

All notable changes to this project will be documented here.

## Unreleased

### Added
- **Object-type filter**: Items with `type "Object"` in game stat files (books,
  containers, quest items) are now classified as carried regardless of the
  equipped-flag bit. Fixes false positives for `FOR_DangerousBook` and
  `UNI_CONT_DEVIL_PuzzleBox_A`.
- **Slot-conflict resolution** (`resolve_slot_conflicts`): After classification,
  items grouped into the same equipment slot are compared. Flags-signalled items
  take priority over ECS-only items; ties broken by per-instance component
  membership count. Ring slot has capacity 2; all others capacity 1. Fixes
  false positives for `ARM_HalfPlate_Body`, `WPN_Greatclub_1`,
  `ARM_Boots_Leather`, `MAG_Lesser_Infernal_Plate_Armor`, `DEN_HellridersPride`,
  and `WPN_Torch` (Wyll + Karlach).
- **Per-instance entity map** (`build_instance_entity_map`): Uses the parallel
  Creators/Items arrays in the ItemFactory node to map `(position, stats)` to
  the specific ECS entity GUID for each physical item instance. Prevents
  membership-count contamination across multiple instances of the same item type.
- CI via GitHub Actions (`.github/workflows/ci.yml`): runs ruff, ty, and pytest
  on every push and pull request.
- Unit tests for `split_equipped_carried` (object-type filter),
  `resolve_slot_conflicts`, and `build_instance_entity_map`.
- `pyproject.toml`: project metadata (description, license, authors, URLs);
  replaced `mypy` with `ty` for type checking; added `[tool.ty]` config.
- **Numeric save lookup**: `uv run bg3_save_reader.py 286` resolves to the
  most recent save whose name ends in `_286`; full save names also work.
- **`--inspect NAME`**: prints classification signals (eq-bit, membership
  count, active status) and the full LSMF component list for any party item
  whose internal stats name contains NAME — the diagnostic workflow used to
  crack each misclassification so far, now built in.
- **WieldedComponent gate for ECS promotion**: items in
  `game.inventory.v0.WieldedComponent` (a stale previously-in-a-weapon-slot
  marker) are no longer ECS-promoted to equipped on membership count alone.
  Fixes `ARM_Shield`/`ARM_Cloak` false positives in QuickSave_257.
- **2-handed offhand blocking**: when a 2-handed weapon is Flags-equipped in
  the melee main-hand slot, offhand candidates are demoted (can't hold a
  shield alongside a greatsword/halberd).
- **Richer Flags slot-conflict tiebreaking**, in priority order: active
  on-equip STATUS (fixes Phalar Aluve shown as carried in saves 267/268),
  physical-attachment components — `WieldedComponent` or
  `GravityDisabledComponent` (fixes Halberd of Vigilance and Knife of the
  Undermountain King in save 286), `OwnedAsLootComponent` (fixes
  `DEN_HellridersPride` in save 246), then per-instance membership count.

### Fixed
- Honour-mode stat file patches that use `using "SameName"` (self-referential
  `using` fields) are now ignored, preventing infinite loops in slot resolution.

## 2025-06 (initial public state)

- Binary LSPK/LSF parser for BG3 save files (`.lsv`)
- Character report: race, class, level, XP, location
- Equipped item detection via STATUS effects and the `0x04000000` Flags bit,
  with ECS component-membership fallback for items with no LSF signal
- Spell/ability list extracted from the LSMF ECS blob
- Quest and story state from Osiris frame 9 (opt-in via `--quests`)
- Display-name resolution from installed game data with cache
- Thumbnail extraction (`--thumbnail`)
- PEP 723 inline-script metadata for `uv run` zero-setup usage
