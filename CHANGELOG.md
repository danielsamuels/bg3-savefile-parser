# Changelog

All notable changes to this project will be documented here.

## Unreleased

### Added
- **Item search on the site**: a "Find an item" box in the report filters
  every item in the save by name (equipped with slot, carried,
  undetermined, camp chest) and says where each match lives ("Wyll ·
  carried", "Camp chest · stored"). The query survives watch-mode
  re-parses, so you can quicksave and glance at the same search.
- **Item rarity table**: `gamedata.json` now carries a `rarity` map (stats
  name to Uncommon/Rare/VeryRare/Legendary, resolved through the `using`
  chain; absent means common). `DisplayNames.rarity_for()` exposes it.
  `tests/generate_gamedata.py` regenerates the committed table and the site
  copy from a local game install.
- **Sized MCP reports** (`report_views.py`): `parse_save` now takes
  `sections` (meta/party/camp/camp_chest/quests), `detail`
  (summary/full), `items` (magic/equipment/all), and `quests`
  (active/all/none). The summary view keys worn gear by slot with empty
  slots explicit as null (two-handed weapons mark the offhand they cover),
  trims spell books to prepared class spells, folds gold stacks into one
  number, and annotates items with slot and rarity. Default output on a
  mid-campaign save dropped from ~214k to ~34k characters.
- **MCP parse cache**: the server keeps the last few parsed saves keyed on
  path and fingerprinted on mtime+size, so follow-up calls about the same
  save skip the multi-second parse; a quest-less cached report upgrades in
  place when quests are requested.

### Changed
- **Restructured into the `bg3parser` package** (modules by format layer:
  `lspk`, `lsf`, `lsmf`, `osiris`, `party`, `gamedata`, `discovery`,
  `model`, `render`, `cli`). The entry point is now `bg3save` (console
  script) or `python -m bg3parser`; `bg3_save_reader.py` is gone.
- **Model/view split**: `gather_report()` produces a structured
  `SaveReport` (dataclasses); `render_text()` and `render_json()` are views
  over it. `--json` emits the full machine-readable report. Text output is
  byte-identical to the pre-split format.

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

### Format decode (LSMF ECS blob)
- **Exact per-character spell books**: `game.spell.v3.SpellBookComponent`
  `{begin,end}` slices into `SpellData` (72-byte rows) whose field 6 points at
  `SpellId` `{pointer, length}` references into the blob's spell-ID string
  pool. Party members are matched by `game.stats.v0.ClassesComponent`
  (class/subclass/level, UUIDs from `ClassDescriptions.lsx`). Replaces the
  class-rule heuristic entirely (the heuristic and its hand-maintained
  CLASS_EXCLUSIVE table were subsequently removed; identical-build party
  members get an explanatory note instead).
- **Equipment slot per worn item** displayed in the report, derived from item
  stats. Established (byte-sweep over 12 known-slot items) that the save does
  not serialise `ItemSlot` at all — the engine re-derives it from stats.
- **Heap/string-pool conventions**: variable-length component fields are
  `{begin,end}` ranges; heap and pool pointers are stored as (absolute − 48).
- **Inventory container web decoded**: `OwnerComponent` (primary inventory),
  `IsOwnedComponent`, `ContainerComponent`, `ContainerSlotData`
  (slot-within-container + generation); `MemberData` identified as
  historical-ownership bookkeeping.
- **Display-name inheritance**: stats names resolve through `ParentTemplateId`
  chains and spell names through the stats `using` chain across all item paks
  — every item and all but mod-only spells in the test saves now resolve.
- **Sub-spell folding**: container variants (each Disguise Self appearance,
  every Chromatic Orb element, …) are detected via the stats
  `SpellContainerID` field and folded into their container spell by default,
  with a count in the header; `--all-spells` lists them (and basic actions).
- **Ring vs Ring 2** recovered from `ContainerSlotData` row order
  (ground-truth verified in-game) and shown in the report.

### Performance
Full-report time on a representative quicksave dropped from ~4.1s to ~1.9s
(the test suite from ~39s to ~26s):
- LSF node/attribute tables parse via precompiled `Struct.iter_unpack`;
  attribute-name lookups are memoized; GUIDs render by direct hex slicing
  instead of `uuid.UUID` construction; scalar values dispatch through a
  type-ID→Struct table.
- Spell strings are found with one C-speed regex over the ECS blob instead
  of a per-byte Python loop.
- The LSMF ownerlist scan runs once and is shared (`scan_lsmf_blob`,
  lru_cache) by membership counting, component-row extraction, and
  `--inspect`; its candidate scan prefilters offsets with a single
  uint32 compare via `memoryview.cast`.

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
