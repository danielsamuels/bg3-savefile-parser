# What this parser can and cannot read

> For the binary file formats themselves (LSPK, LSF, the `LSMF` ECS blob,
> `.loca`), see **[FORMAT.md](FORMAT.md)**.

## What works

| Data | Source in save |
|------|----------------|
| Character name, race, class/subclass, level, XP | `Info.json` (frame 8 of the LSPK) |
| **Per-character item ownership (equipped + carried)** | **`Item.Translate` matched to the character's `Translate`** (frames 0 + 3) |
| Equipped vs carried split (best-effort) | union of `STATUS.SourceEquippedItem` + the equipped `Flags` bit `0x04000000` |
| Full level item pool (internal names) | `Item` nodes in frame 0 + level-cache frame |
| **Human-readable item names** | **resolved from the installed game data** (root-template `_merged.lsf` → `DisplayName` handle → `english.loca`) |

### How display names work

Each item in the save carries only an internal `Stats` name
(`UND_SwordInStone`) and a runtime `CurrentTemplate` GUID. The display name
("Phalar Aluve") lives in the game's data files, reached by:

```
CurrentTemplate GUID ─► root-template DisplayName handle ─► english.loca text
        or  Stats name ─► root-template DisplayName handle ─► english.loca text
```

Root templates are the `_merged.lsf` files inside `Shared.pak` / `Gustav.pak`
(LSPK v18 packages); the handle→text table is `english.loca` inside
`English.pak`. The parser reads these directly (no `divine`/lslib needed) and
caches the resulting `{GUID,Stats} → name` maps under `XDG_CACHE_HOME`, keyed on
the source paks' mtime/size, so the ~1 s parse only re-runs after a game update.

The game install is auto-detected in the usual Steam locations, or pointed to
explicitly with the `BG3_DATA_DIR` environment variable. With no install found,
items fall back to their internal names.

**Resolution is by Stats name, not GUID.** Every item in a live save — worn,
carried, and the whole level loot pool — uses a per-save *local* `CurrentTemplate`
GUID absent from the static root templates (the GUID path resolved 0 of ~11 600
item GUIDs across the test saves), so names come from the Stats name. The GUID
path is kept only as a more-precise match should a static template GUID appear.

**Shared stats names.** ~9% of stats names (267 / 2901) map to more than one
display name; for those an item resolves to the first/base variant rather than
its exact variant. A handful of camp/cosmetic/container items whose templates
live in other paks remain internal-only.

Resolution was validated against a known four-character party loadout: every
piece of gear present resolved to the installed game's current name, including
mappings that were previously only guessed (`UNI_MassHealRing` → "The Whispering
Promise", `ARM_Ring_I_Silver_A` → "Onyx Ring", `GOB_DrowCommander_Amulet` →
"Amulet of Misty Step"). Two items resolve to names that differ from older
wiki/colloquial labels but match the current game data
(`MAG_Duergar_Sword_KingsKnife` → "King's Knife",
`MAG_Lesser_Infernal_Plate_Armor` → "Hellgloom Armour" — the ground truth for
this save uses the older label "Flawed Helldusk Armour"). One item in the party
loadout (`GOB_DrowCommander_Leather_Armor`, Wyll's chest) has no matching entry
in the root templates and shows as an unresolved internal name; see "One item
with an unresolved display name" below.

### How per-character ownership works

A carried or worn item's `Translate` (world transform) is copied from the
character holding it, so every item on a party member shares that member's
exact floating-point coordinates. Matching item `Translate` against character
`Translate` attributes each item to its owner **without decoding the ECS blob**.
The position-attribution itself is exact (an item is on a character or it
isn't). Validated against the QuickSave_242 ground truth (4 characters, 34 worn
items): all 34 worn items are attributed to the correct character with no
misclassifications.

## What is partial or missing

### How equipped vs carried is determined
Items attributed to a character are split two ways:

- **Equipped** — the item grants a `STATUS` on-equip effect, **or** carries the
  `0x04000000` `Flags` bit (on an equipment-type stats name), **or** its ECS
  entity appears in ≥ 15 component ownerlists (equipped items are materialised
  in the ECS world with ~35–41 memberships; backpack items dematerialise to
  ~3–6).
- **Carried** — not equipment at all (consumables, keys, gold, camp/cosmetic
  clothing), or an equipment-type item whose ECS entity has low membership
  (< 15 ownerlists).

The membership count is the authoritative signal for items the LSF signals miss.
A controlled diff of saves 242 (Evasive Shoes equipped on Wyll) and 243 (shoes
moved to his bag) found 35 components whose ownerlist contained the equipped
entity and not the in-bag entity; `game.inventory.v0.MemberComponent` is one of
them. The parser uses the total count across all components (threshold 15), not
a specific component check.

Validated against the QuickSave_242 ground truth (34 worn items across 4
characters): all 34 are classified as equipped. The ECS signal resolves items
invisible to the LSF signals alone (Evasive Shoes and Pearl of Power Amulet on
Wyll, both with `Flags=0x0000000c`, confirmed by controlled equip/unequip
experiments across saves 242/248/249 and 242/243).

**One confirmed false positive** in the LSF signals: `DEN_HellridersPride`
(Hellrider's Pride) carries the equip bit but sits in Shadowheart's inventory,
not in an equipment slot. The ECS signal would separately classify it by actual
slot status — this is not yet cross-validated.

### Exact equipment slot
Which slot an item occupies (Helmet / Boots / Amulet / Ring / …) is not
recovered. The bg3se C++ struct has `eoc::inventory::MemberComponent.EquipmentSlot`
(`int16`), but the on-disk `MemberComponent` is serialised as only 8 bytes (a
pointer into `MemberData`) — the slot field is absent from the on-disk form.
`MemberData`'s second field is a live `EntityHandle` with no on-disk translation
table, also blocking any handle-based reconstruction. The slot indices follow
bg3se's `ItemSlot` enum: Helmet=0, Breast=1, Cloak=2, Boots=9, Gloves=10,
Amulet=11, Ring=7/12. For most item types there is a 1:1 relationship between
the item and its slot, so the practical impact is limited.

### One item with an unresolved display name
`GOB_DrowCommander_Leather_Armor` (Wyll's chest piece, confirmed worn) has a
full frame-0 Item node and the equip bit, but its stats name is not present in
the root-template files scanned, so it shows without a display name. Context
suggests it is Spidersilk Armour: the GOB_DrowCommander item family maps to
Minthara's gear set, and the related template `GOB_DrowCommander_Armor_Leather`
uses stats `ARM_StuddedLeather_Body_Drow` → "Spidersilk Armour". A previous note
claimed Shifting Corpus Ring and Spidersilk Armour had no LSF Item records — this
was incorrect. Both `MAG_FlamingFist_ScoutRing` (Shifting Corpus Ring) and
`GOB_DrowCommander_Leather_Armor` have frame-0 Item nodes and are attributed
correctly.

### Spell selections
Spell book data lives in the `NewAge` attribute (LSF attribute type 25 =
`ScratchBuffer`), an opaque LSMF-format ECS blob. Spell attribution here uses
class-based heuristics on the LSMF string pool; multiclass/high-level spells may
be attributed to the wrong character.

## The ECS blob (NewAge / LSMF)

The `NewAge` node in each level frame contains a single ScratchBuffer attribute
holding a multi-megabyte binary blob starting with the magic bytes `LSMF`.
It is a columnar ECS component store: component sections are arrays ordered by
entity handle, with entity cross-references stored as handles (not the 16-byte
GUIDs), resolved through separate handle↔GUID tables.

### What is decoded

The parser reads the following from the ECS blob:

- **Component descriptor table**: 355 component types, each with name, element
  size, row count, and data offset (see FORMAT.md §6).
- **Ownerlist region**: each component that has one stores a 32-byte
  `{start, end, comp, entity_count}` record (all `uint64`); `start`..`end` is a
  packed `uint32[]` of entity-row indices. Scanning all ownerlists and counting
  per-entity memberships gives the equipped/carried signal: equipped items have
  ~35–41 memberships; items dematerialised into a backpack have ~3–6. A
  controlled diff (saves 242/243) confirmed `game.inventory.v0.MemberComponent`
  is one of 35 components present only for equipped entities.
- **Entity GUID bridge**: `core.v0.EntityId` stores 16-byte GUIDs at a known
  offset, indexed by entity row. Reversed `e2t_items` (from LSF Creators nodes)
  maps template GUID → instance GUID, linking the LSF item tree to the ECS rows.
  Spell strings are also read directly from the blob's printable-ASCII runs.

### What is not decoded

- **Exact equipment slot** (Helmet / Boots / Amulet / Ring / …): the on-disk
  `MemberComponent` element is 8 bytes (a pointer into `MemberData`); the
  `EquipmentSlot` field from the C++ struct is absent. `MemberData`'s second
  field is a live `EntityHandle` (Salt≈852, no on-disk translation table). The
  slot number is not recovered.
- **Per-character inventory ownership** via ECS: same blocker. The
  `Translate`-matching heuristic (see above) is used instead.

## Development

Install dev dependencies and run all checks with:

```sh
# Lint
uvx ruff check bg3_save_reader.py

# Format check (reports would-be changes without applying them)
uvx ruff format --check bg3_save_reader.py

# Tests (requires QuickSave_242.lsv; save-dependent tests skip when absent)
uv run --extra dev pytest

# Type check
uv run --extra dev mypy bg3_save_reader.py
```

The save file path defaults to the standard Steam/Proton location; override it
with the `BG3_SAVE_FILE` environment variable:

```sh
BG3_SAVE_FILE=/path/to/QuickSave_242.lsv uv run --extra dev pytest
```
