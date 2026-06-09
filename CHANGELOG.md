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
