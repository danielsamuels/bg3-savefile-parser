# Baldur's Gate 3 save / data file format

A reference for the binary formats this parser reads: the `.lsv` save package,
the LSPK packages it (and the game data) are stored in, the LSF resource format
inside them, the `LSMF` ECS blob that holds the live world state, and the
`.loca` localisation format.

**Provenance.** Everything here was verified by parsing real files (a Patch-8
BG3 save, `QuickSave_242`, game version 4.1.1.7209685) unless noted. Field
names and the parts not yet decoded are cross-checked against two upstream
projects, neither of which is required to run this parser:

- **LSLib** (Norbyte) — the canonical C# reader for LSPK / LSF / `.loca`.
  Paths below like `LSLib/LS/Resources/LSF/LSFCommon.cs` refer to it.
- **bg3se** (Norbyte's Script Extender) — C++ definitions of the ECS
  *components* as they exist in live game memory (`BG3Extender/GameDefinitions/`).
  bg3se does **not** read the on-disk save; it reads RAM. LSLib reads the save
  but treats the `LSMF` blob as opaque bytes. So no existing tool decodes the
  ECS blob from a save — see [§6](#6-the-lsmf-ecs-blob-newage).

All integers are little-endian.

---

## Layering at a glance

```
.lsv save file  ──►  LSPK package  ──►  N files ("frames"), each an LSF resource
                                              │
   .pak game data ──► LSPK package  ──►       ├─ frame 0  Globals  ── contains ─┐
                                              ├─ frame 3  level cache           │
                                              ├─ frame 8  Info.json (plain JSON)│
                                              └─ frame 9  Osiris story (binary) │
                                                                                ▼
                              one LSF attribute of type ScratchBuffer (25) holds the
                              "NewAge" LSMF blob: a columnar ECS world dump (~4 MB)
```

A file is therefore decoded in three nested steps: **LSPK** (container) →
**LSF** (node/attribute tree) → for save state, the **LSMF** ECS blob carried
inside one LSF attribute.

---

## 1. LSPK package format (version 18)

Used by the game's `.pak` files and by `.lsv` saves. Header is at offset 0:

| Offset | Type | Field |
|-------:|------|-------|
| 0 | char[4] | magic `"LSPK"` |
| 4 | u32 | version (`18` for Patch 8) |
| 8 | u64 | file-list offset |
| 16 | u32 | file-list size (compressed) |
| 20 | u8 | flags |
| 21 | u8 | priority |
| 22 | u8[16] | MD5 |
| 38 | u16 | number of parts |

At the file-list offset:

| Type | Field |
|------|-------|
| u32 | number of files |
| u32 | compressed size of the entry table |
| …   | LZ4-block-compressed entry table (`numFiles × 272` bytes uncompressed) |

Each **272-byte** file entry:

| Offset | Type | Field |
|-------:|------|-------|
| 0 | char[256] | path (NUL-padded, `/`-separated) |
| 256 | u32 | offset low 32 bits |
| 260 | u16 | offset high 16 bits |
| 262 | u8 | archive part (file spills to `Name_<part>.pak` if non-zero) |
| 263 | u8 | flags (low nibble = compression) |
| 264 | u32 | size on disk (compressed) |
| 268 | u32 | uncompressed size |

`offset = offsetLow | (offsetHigh << 32)`. **Compression** (entry flags low
nibble): `0` = none, `1` = zlib, `2` = LZ4 (block, `uncompressed_size` known),
`3` = zstd. To extract a file: seek to `offset`, read `size_on_disk` (or
`uncompressed` if `size_on_disk == 0`) bytes, decompress per the method.

> **`.lsv` shortcut.** A save is an LSPK package whose contained files are each
> a stand-alone zstd frame. This parser locates them pragmatically by scanning
> for the zstd magic `28 b5 2f fd` rather than walking the file list
> (`extract_frames`). The full LSPK reader above (`lspk_filelist` /
> `lspk_extract`) is used for the game `.pak`s.

### Frame map of a `.lsv` save

10 frames (0–9) in `QuickSave_242`. ✅ = parsed by this tool; ❌ = not parsed.

| Frame | Magic | Decomp | Status | Contents |
|------:|-------|-------:|:------:|----------|
| 0 | LSOF | 3.1 MB | ✅ | **Globals** — `Characters`, `Items`, item `Creators` (Entity→TemplateID), and the `NewAge` LSMF blob; ~30 root regions including `Story`, `Journal`, `Waypoints`, `GameControl` |
| 1 | LSOF | 153 KB | ❌ | Secondary level LSF — probably a background/camp area's level state |
| 2 | LSOF | 2.1 MB | ❌ | Navigation mesh — `GridDefinition` root + 2,109 hashed navmesh tile roots; no item/character data |
| 3 | LSOF | 10.8 MB | ✅ | **Level cache** (`SCL_Main_A`) — `Characters`, `Items`, `Surfaces`, AI state, `CrimeHandler`; ~11.8 k live `Item` nodes with `Stats` and world transforms |
| 4 | LSOF | 24 KB | ❌ | Compact snapshot — `Characters`, `Items`, `Projectiles`, `Level`; likely a respawn-point or load-screen preview state |
| 5 | LSOF | 14.7 MB | ❌ | Fog-of-war / shroud — `GridDefinition` + 14,898 hashed tile visibility bitmap roots; no item/character data |
| 6 | LSOF | 2 KB | ❌ | Single `MetaData` root — supplemental save metadata |
| 7 | RIFF | ~1.7 MB | ❌ | **Load-screen thumbnail** — a RIFF-format image; not an LSF |
| 8 | JSON | 2.5 KB | ✅ | **`Info.json`** — save name, game version, difficulty, current level, active party (class/level/XP) |
| 9 | Osiris | 47.7 MB | ❌ | **Osiris database** — scripting engine state (`Osiris save file, Version 1.8`): quest flags, story counters, dialogue state |

---

## 2. LSF (LSOF) resource format

Each frame (and every `_merged.lsf`, `.lsf` in the paks) is an LSF resource: a
flat table of **nodes** forming a tree, each carrying typed **attributes**.

### Header

| Offset | Type | Field |
|-------:|------|-------|
| 0 | char[4] | magic `"LSOF"` |
| 4 | u32 | version (`7` = `VerExtendedNodes`+ for Patch 8) |
| 8 | i64 | engine version (packed major.minor.rev.build; `LSFHeaderV5`, present for BG3) |

Then the metadata block (`LSFMetadataV6`, 10 × u32 of section sizes) at offset 16:

| Offset | Type | Field |
|-------:|------|-------|
| 16 | u32 | strings — uncompressed size |
| 20 | u32 | strings — size on disk |
| 24 | u32 | **keys** — uncompressed size |
| 28 | u32 | **keys** — size on disk |
| 32 | u32 | nodes — uncompressed size |
| 36 | u32 | nodes — size on disk |
| 40 | u32 | attributes — uncompressed size |
| 44 | u32 | attributes — size on disk |
| 48 | u32 | values — uncompressed size |
| 52 | u32 | values — size on disk |
| 56 | u8 | compression flags (low nibble = method, high nibble = level) |
| 57 | u8 | unknown (0) |
| 58 | u16 | unknown |
| 60 | u32 | **MetadataFormat** (see below) |

The four data sections (**strings, nodes, attributes, values**) follow
immediately, in that order, starting at offset 64. A section's on-disk byte
count is `sizeOnDisk` when compressed, or the **uncompressed size when
`sizeOnDisk == 0`** (uncompressed sections — common in the game's
`_merged.lsf`). Compression per the flags byte: `0` none, `2` LZ4 (frame-mode
"chunked" when `version ≥ 2`, otherwise block-mode). A keys section exists only
in the extended layout below.

### MetadataFormat and the V2 vs V3 layout

`MetadataFormat` (`LSFCommon.cs::LSFMetadataFormat`): `0 = None`,
`1 = KeysAndAdjacency`, `2 = None2` (behaves identically to `None`).

The **long (V3) node & attribute layout** is used **only** when
`version ≥ VerExtendedNodes AND MetadataFormat == 1`. Otherwise the short (V2)
layout is used.

> **Gotcha (this cost two bugs):** observed files use `MetadataFormat` `0`
> (saves) or `2` (the game's root-template `_merged.lsf`). Both are the **V2**
> layout — `2` is *not* extended. Keying the node width off `mfmt != 0` wrongly
> picks 16-byte nodes for the `_merged.lsf`, corrupting the node table. An
> intermediate fix keyed off the keys-section sizes (`keys_unc/keys_disk != 0`),
> but save frames 2/4/5 have a non-empty keys section with `mfmt=0` (V2 layout),
> making that test also wrong. **The correct and final test is `MetadataFormat == 1`**,
> which this parser now uses.

### String hash table (strings section)

```
u32 numHashChains
repeat numHashChains:
    u16 numStringsInChain
    repeat: u16 length, then `length` bytes (UTF-8)
```

A name handle `nh` resolves as `names[nh >> 16][nh & 0xFFFF]`.

### Node entries (nodes section)

**V2 — 12 bytes:**

| Offset | Type | Field |
|-------:|------|-------|
| 0 | u32 | name handle (MSB16 = chain, LSB16 = offset in chain) |
| 4 | i32 | first attribute index (`-1` = none) |
| 8 | i32 | parent index (`-1` = root region) |

**V3 — 16 bytes** (`KeysAndAdjacency` only):

| Offset | Type | Field |
|-------:|------|-------|
| 0 | u32 | name handle |
| 4 | i32 | parent index |
| 8 | i32 | next sibling index |
| 12 | i32 | first attribute index |

### Attribute entries (attributes section)

**V2 — 12 bytes** (used by saves & `_merged.lsf`):

| Offset | Type | Field |
|-------:|------|-------|
| 0 | u32 | name handle |
| 4 | u32 | type-and-length: `type = v & 0x3F`, `length = v >> 6` |
| 8 | i32 | owning node index |

V2 attribute **values** are stored back-to-back in the values section in
attribute order; walk a running offset, advancing by each attribute's `length`.

**V3 — 16 bytes** (`KeysAndAdjacency` only): name handle (u32), type-and-length
(u32), next-attribute index (i32), explicit value **offset** (u32). Attributes
are chained per node from the node's `first attribute index`.

### Attribute value types

Full type enum (`LSLib/LS/NodeAttribute.cs`); ✓ = decoded by this parser:

| ID | Type | ID | Type | ID | Type |
|---:|------|---:|------|---:|------|
| 0 | None | 13 | Vec4 | 25 | ScratchBuffer ✓ (opaque bytes — the LSMF blob) |
| 1 | Byte ✓ | 14 | Mat2 | 26 | Long/Int64 ✓ |
| 2 | Short ✓ | 15 | Mat3 | 27 | Int8 |
| 3 | UShort ✓ | 16 | Mat3x4 | 28 | TranslatedString ✓ (u16 version, i32 len, handle) |
| 4 | Int ✓ | 17 | Mat4x3 | 29 | WString ✓ |
| 5 | UInt ✓ | 18 | Mat4 | 30 | LSWString ✓ |
| 6 | Float ✓ | 19 | Bool ✓ | 31 | UUID ✓ (16 bytes, little-endian) |
| 7 | Double | 20 | String ✓ | 32 | Int64 ✓ |
| 8–10 | IVec2–4 | 21 | Path ✓ | 33 | TranslatedFSString |
| 11 | Vec2 | 22 | FixedString ✓ | | |
| 12 | **Vec3 ✓** (3 × float — used for `Translate`) | 23 | LSString ✓ | 24 | ULongLong ✓ |

String types (20–23, 29, 30) store `length` bytes including a trailing NUL.
`TranslatedString` (28) stores a localisation **handle** (e.g.
`h0f8bb066g...`) resolved via `.loca` ([§7](#7-localisation-loca)).

---

## 3. Characters, items, and per-character ownership

Within frame 0 / frame 3 LSF trees:

- **Party characters** are `Character` nodes whose `CurrentTemplate` GUID is one
  of the known origin template GUIDs (Maia/Wyll/Karlach/Shadowheart in the test
  save). Each has a `Translate` (Vec3 world position).
- **Items** are `Item` nodes with `Stats` (internal name, e.g.
  `UND_SwordInStone`), `CurrentTemplate` (a per-save **runtime** GUID),
  `Translate`, `Flags`, `Level`, etc. There is **no slot or owner field**.
- Item `Creators` map `Entity` → `TemplateID`; templates map to `Stats`.

**Ownership by shared position.** A carried or worn item's `Translate` is copied
from the character holding it, so every item on a party member shares that
member's *exact* float coordinates. Matching item `Translate` against character
`Translate` attributes each item to its owner without touching the ECS blob.
This is exact for "which character is this on".

**Worn vs carried is *not* fully recoverable from LSF data.** Measured against a
known-correct loadout (QuickSave_242, 4 characters, 34 worn items), the
`0x04000000` Flags bit is present on **32 of 34 worn items** and absent on 2
(Evasive Shoes and Pearl of Power Amulet, both Wyll). One confirmed false
positive: `DEN_HellridersPride` carries the bit but sits in Shadowheart's
inventory. So the bit is a strong positive signal but neither necessary nor
sufficient. A *negative* signal also emerged: worn items **never** carry the high
flags bits (`Flags ≥ 0x80000000…`); those appear only on consumables, quest
items, and some unequipped spares. The authoritative worn set + slot live only in
the ECS blob ([§6](#6-the-lsmf-ecs-blob-newage)). This parser therefore reports
three buckets: positively-signalled **Equipped**, definitely non-equipment
**Carried**, and **"worn or carried — undetermined"**.

**Multiple Item nodes for the same stats name.** A single stats name can appear
in multiple `Item` nodes in frame 0 — once per actual instance (equipped copy,
spare, world spawn). For example, `ARM_Instrument_Lute` has three frame-0 nodes
in the test save: one with the equip bit (the equipped MusicalInstrument-slot
instance), one without (a spare), and one marked `UnsoldGenerated` (a vendor
copy). The dedup logic in this parser retains the node with the equip bit when
duplicates exist, so the equipped instance wins.

---

## 4. Item flags (`Item.Flags`, observed bits)

Not authoritative for equipped state (see §3 above), but measured against the
QuickSave_242 ground truth (34 worn items across 4 characters):

| Bits (mask) | Meaning (observed) |
|------------:|--------------------|
| `0x0000000c` | baseline, present on essentially every item |
| `0x04000000` | worn-equipment signal — present on 32/34 worn items; **absent** on 2 worn items (Evasive Shoes, Pearl of Power Amulet) and **present** on at least 1 inventory item (`DEN_HellridersPride`) as a false positive |
| `0x00000100` / `0x00200000` | seen on bags/containers (AlchemyPouch, Keychain) |
| `0x00040000` | seen on some items with `PreviousLevel` set (items moved between areas) |
| high bits (`0x80000000_0000…`) | consumables, quest items, some unequipped spares — **never** seen on any of the 34 verified worn items; useful as a negative signal |

---

## 5. Game-data root templates (display names)

The save stores only internal `Stats` names; the human-readable name lives in
the game `.pak`s and is resolved as:

```
item Stats name  ─►  root-template DisplayName handle  ─►  english.loca text
   (or CurrentTemplate GUID ─► root template, for static/world templates)
```

Root templates are the `_merged.lsf` files inside `Shared.pak` / `Gustav.pak` /
`GustavX.pak` (e.g. `Public/Shared/RootTemplates/_merged.lsf`). Each
`GameObjects` node has: `MapKey` (template GUID), `Name`, `Stats`,
`ParentTemplateId` (inheritance — follow it when `DisplayName` is absent), and
`DisplayName` (a `TranslatedString` handle).

> In a live save, items use a **per-save local** `CurrentTemplate` GUID that is
> absent from the static templates (0 of ~11.6 k matched), so resolution is by
> **Stats name** in practice. ~9 % of stats names map to >1 display name; an
> ambiguous one resolves to the first/base variant.

---

## 6. The `LSMF` ECS blob ("NewAge")

The single biggest piece of live state. It is stored as one LSF attribute of
type **ScratchBuffer (25)** on the root `NewAge` node of frame 0 — an opaque
~4 MB byte buffer that LSLib does **not** decode. It is a **columnar
Entity-Component-System dump**.

> **Extraction gotcha.** The LSMF blob lives inside the LSF **values section**,
> which is itself LZ4-compressed (§2). A raw scan of the decompressed `.lsv` frame
> for `4C 53 4D 46` (`LSMF`) magic bytes will find a **false positive** in the
> LSF strings section at approximately offset 1 730 992 (the ASCII text `LSMF`
> appears there as part of a node name). The actual blob is only reachable by
> fully parsing the LSF — decompressing the values section and reading the
> `NewAge → ScratchBuffer` attribute value — as `parse_lsof` does.

### Header

| Offset | Type | Field |
|-------:|------|-------|
| 0 | char[4] + 4 | magic `4C 53 4D 46 01 01 00 08` (`LSMF` + version-ish) |
| 8 | u64 | (unidentified; looks like a hash/build id) |
| 16 | **u64** | **dir_off** — raw directory pointer; `names_off` (actual directory start) = `dir_off + 48` |
| 24 | **u64** | **names_size** — byte length of the component-names blob |
| 32 | **u32** | **desc_table_rel** — descriptor-table offset, relative to `names_off` |
| 36 | **u16** | **entry_count** — number of component descriptors (355 in QuickSave_242) |
| 48… | | component column data, then the directory region |

### Component-type directory (✅ decoded)

`blob[16:24]` stores `dir_off`; the directory starts at `names_off = dir_off + 48`.
It lists **every component type present** — 355 entries in `QuickSave_242`. Names
are stored **without** the `eoc::` / `ls::` prefix (so a search for the full bg3se
name like `eoc::inventory::MemberComponent` fails; the substring `MemberComponent`
is present). The directory fields `desc_table_rel` (u32) and `entry_count` (u16)
live in the **blob header** at absolute offsets 32 and 36 (see §6 Header table),
not in the directory itself. Layout, offsets relative to `names_off`:

| Offset | Field |
|-------:|-------|
| `+0` | names blob: `names_size` bytes (from `blob[24:32]`) of component names concatenated **with no separators**, e.g. `"core.v0.Levelcore.v0.EntityIdgame.action_resources.v1.Component…"` |
| `+desc_table_rel` | ComponentDesc table: `entry_count` × 48-byte entries |

The descriptor table sits at `desc_base = names_off + desc_table_rel`, one
48-byte entry per component type:

```c
struct ComponentDesc {
    u64 name_offset;  // into the names blob
    u64 name_length;
    u64 hash;         // not decoded
    u32 elem_size;    // bytes per row
    u32 flags;        // not decoded
    u64 row_count;
    u64 data_offset;  // absolute byte offset of this component's column data
};
```

This is a complete `name → {elem_size, row_count, data_offset}` index for all
355 types, e.g. `core.v0.EntityId` (elem=16 — one entity-instance GUID per
row), `game.inventory.v0.MemberData` (#125, elem=16, rows=1314,
data_off=0x166010), `game.inventory.v0.MemberComponent` (#126, elem=8,
rows=1314, data_off=0x16b230). The inventory cluster is contiguous in the
names blob: `CanBeWieldedComponent · ContainerSlotData · MemberData ·
MemberComponent · OwnerComponent · StackMemberComponent · WieldedComponent · …`

### Ownerlist region (✅ decoded)

Between the component column data and the directory (`[48, names_off)`) there
is a contiguous table of **32-byte ownerlist records**, one per component that
has one:

```c
struct OwnerlistRecord {
    u64 start;         // absolute byte offset into blob: start of entity-row-index array
    u64 end;           // absolute byte offset: end of entity-row-index array
    u64 comp;          // index into the ComponentDesc table (0-based)
    u64 entity_count;  // (end - start) / 4
};
```

`start`..`end` is a packed array of `uint32` entity-row indices listing every
entity that owns this component (i.e., has a column-data row for it).

**Critical indexing rule.** An entity's **position `P`** in the ownerlist array
(0-based) is its column index into the component's data — *not* its
`core.v0.EntityId` row number. To read the component data for entity at
`EntityId` row `er`: scan the ownerlist for the position `P` where
`ownerlist[P] == er`, then read
`blob[data_offset + P * elem_size : data_offset + (P+1) * elem_size]`.

The ownerlist table is located by scanning the blob for the densest chain of
valid 32-byte-aligned records (valid = `comp < entry_count`,
`entity_count == rows_by_comp[comp]`, `end - start == entity_count * 4`). The
parser's `parse_lsmf_membership` scans all ownerlist records to build a
per-entity membership count; the count is the equipped/carried signal (see
LIMITS.md).

### Cross-component references: absolute byte-pointers (✅ decoded)

Where one component's row references another entity, the on-disk value is a
**direct absolute byte offset into the blob** — not a handle, not a GUID. A
`locate(offset)` helper (scan all `ComponentDesc` entries for
`data_offset <= off < data_offset + elem_size*row_count`) resolves any such
value to `(component_name, row_index, byte_in_row)`. Every
`MemberData.ptr_a` (below) resolves with `byte_in_row == 0` against
`core.v0.EntityId` — i.e. it points at the start of an entity's 16-byte GUID
record, the closest thing to a stable cross-reference the on-disk format has.

### Entity-GUID bridge — corrects an earlier "no link exists" claim (✅ found)

A prior pass concluded that LSF item/character GUIDs never appear in the LSMF
blob's entity tables — and used that to argue the worn/carried question was
structurally unrecoverable. **That conclusion compared the wrong GUID
namespace.** `CurrentTemplate` on an `Item`/`Character` LSF node is a
*template/content* GUID; `core.v0.EntityId` rows hold *entity-instance* GUIDs —
two disjoint spaces. The bridge between them is the existing
`build_entity_template_map(nodes, root_name)` helper (`entity_guid →
template_guid`); inverted and chained:

```
item.CurrentTemplate ──(invert map for 'Items')──► entity_guid ──(raw 16-byte search)──► core.v0.EntityId row
```

this resolves cleanly for every item tested (Wyll's 7 known-equipped items each
land 5–8 `EntityId` row instances — entities are re-listed multiple times,
seemingly once per save "epoch"/frame). **So entity identity for a known item
*is* recoverable from the blob.** What is *not* recoverable (next section) is
which inventory/slot that entity sits in.

### `MemberData` / `MemberComponent`: diff experiment and EntityHandle wall

**Controlled equip/unequip diff (saves 242 vs 243).** Comparing saves where
Wyll's Evasive Shoes were equipped (save 242, entity row 1597) vs in his bag
(save 243, entity row 1679) identified **35 components whose ownerlist included
entity 1597 but not entity 1679** — components present only when the item is
equipped. `game.inventory.v0.MemberComponent` is one of them. The parser uses
**aggregate membership count** across all ownerlist records (equipped items have
~35–41 memberships; backpack items ~3–6; threshold 15) as its
equipped/carried signal — `MemberComponent` is a cross-check, not the sole
indicator. `MemberComponent` has 1314 rows in save 242 because it covers all
equipped entities in the scene (party, NPCs, world), not just party items.

**`game.inventory.v0.MemberComponent`** (#126, elem=**8**, rows=1314). The bg3se
in-memory struct is:
```cpp
struct MemberComponent { EntityHandle Inventory; int16_t EquipmentSlot; };
```
but the on-disk element is only 8 bytes — an **absolute byte-pointer into
`MemberData`'s data region**. The `EquipmentSlot` field is absent from the
on-disk representation.

**`game.inventory.v0.MemberData`** (#125, elem=16, rows=1314):
`{ u64 ptr_a, u64 handle_b }`.

Prior analysis found that `ptr_a` resolves (via the byte-pointer scheme above)
to a `core.v0.EntityId` row-start; collapsed across duplicates, only **262
distinct GUIDs** appear. **None of the 1419 known item-entity GUIDs is among
those 262** — they are **inventory-container pseudo-entities** (one per
character/container/shop; 262 is a plausible count for a full save), consistent
with `MemberComponent` recording "item entity X belongs to inventory entity Y".
The `ptr_a` values (~78 K–98 K) were separately confirmed to **not** fall in
`game.inventory.v0.ContainerSlotData`'s data range [1 409 808, 1 430 288),
verified against all 17 tested equipped items.

`handle_b` is a packed `EntityHandle`. From bg3se source
(`CoreLib/Base/BaseTypes.h:126–189`, `TypedHandle<EntityHandleTag>`):
```
uint64  =  Index(32 bits)  |  Salt(22 bits) << 32  |  Type(10 bits) << 54
```
Read as four LE `u16`s `[low, mid, hi, top]`: `hi ≈ 0x0354`/`0x0355` is the
lower 16 bits of Salt (852/853); `top = 0` because Salt < 2¹⁶; `mid` (30
distinct values) is the upper 16 bits of the Index field; `low` spans the full
`u16` range. In the test save, bytes 12–15 of every `handle_b` read as
`54 03 00 00` (LE) → Salt = 852 = 0x354, Type = 0. `Index` values are in the
billions — positions in the **live game's global entity pool**, not the save's
local `core.v0.EntityId` table (~17 K rows). **No handle → GUID translation
table exists anywhere in the on-disk LSF tree** (confirmed by exhaustive
whole-tree search). `handle_b` is therefore unresolvable without live game state,
and with it the `EquipmentSlot` baked into the C++ form of `MemberComponent` is
also blocked.

### What the equipment data looks like (from bg3se, in live memory)

The components that answer "is it worn, in which slot" (`Components/Inventory.h`,
`Stats.h`):

```cpp
// "eoc::inventory::MemberComponent"
struct MemberComponent { EntityHandle Inventory; int16_t EquipmentSlot; };
// "eoc::EquipableComponent"
struct EquipableComponent { Guid EquipmentTypeID; ItemSlot Slot; };
// "eoc::inventory::WieldedComponent" { Guid }
```

> **On-disk vs in-memory.** The LSMF serialisation of `MemberComponent` is
> **8 bytes** (a byte-pointer into `MemberData`), not the 10-byte C++ struct.
> `EquipmentSlot` is absent from the on-disk form; it exists only in live
> game memory.

`EquipmentSlot` / `ItemSlot` enum (`Enumerations/Stats.inl`, `uint8`):

```
0 Helmet   1 Breast   2 Cloak   3 MeleeMainHand  4 MeleeOffHand
5 RangedMainHand  6 RangedOffHand  7 Ring  8 Underwear  9 Boots
10 Gloves  11 Amulet  12 Ring2  13 Wings  14 Horns  15 Overhead
16 MusicalInstrument  17 VanityBody  18 VanityBoots  19 MainHand  20 OffHand
```

### Transform array (partially mapped)

Character world `Translate` triples (`<fff`) appear in the blob 5–8× each
(presumably `MemberTransformComponent`), bracketed by a recurring `5D 02 5D 02`
(= `605, 605` as two u16 — entity-index-like markers) with `FF`-filled
rotation/scale fields. These give a known-value entry point into entity framing.

### What blocks a full decode

The directory is now decoded (any component's `{elem_size, row_count,
data_offset}` is a lookup away — see above), and entity identity for a *known*
item is recoverable via the `CurrentTemplate → entity_guid → EntityId` bridge.
What remains genuinely blocked:

1. **`EntityHandle` decoding.** `MemberData.handle_b` is a well-formed
   `EntityHandle` (`uint64 = Index(32) | Salt(22)<<32 | Type(10)<<54`; Salt≈852,
   Type=0 — confirmed from bg3se source and byte inspection). Its `Index` field
   is in the billions — a position in the live game's global entity pool, not the
   save's local table. There is **no handle → GUID / handle → row table anywhere
   in the on-disk LSF tree** (confirmed by exhaustive whole-tree search). Any
   information gated behind a live `EntityHandle` is unresolvable from the save
   file alone.
2. **Exact equipment slot** (Helmet / Boots / Amulet / …). The equipped/carried
   split is recoverable via membership count (see ownerlist region and LIMITS.md).
   What is not recovered is *which* slot an item occupies. The `EquipmentSlot`
   field from the C++ `MemberComponent` struct is absent from the 8-byte on-disk
   element, and the `EntityHandle` wall above blocks any handle-based
   reconstruction. For most equipment types there is a 1:1 relationship between
   item type and slot, so the practical impact is limited.
3. The blob contains no slot-name or full-component-name strings to anchor on
   beyond the directory.

> Approaches that **failed** and shouldn't be retried as-is: treating the
> per-component GUID arrays as ownership lists (they're ordered by entity handle
> = creation order); co-occurrence / run-segmentation / run-header scans of the
> column data; comparing `CurrentTemplate` GUIDs directly against `EntityId`
> rows (wrong namespace — use the inverted `build_entity_template_map` bridge
> instead); interpreting `MemberData.ptr_a` as a pointer into `ContainerSlotData`
> (confirmed not: ptr_a values ~78 K–98 K fall outside CSD's range
> [1 409 808, 1 430 288), verified against 17 equipped items); attempting to
> derive slot or item identity from the four-`u16` decomposition of `handle_b`
> (it is a live `EntityHandle` with no on-disk translation table; the 30 distinct
> `mid` values are the high-16-bits of the Index field, not slot numbers).
> The viable path for recovering exact slot numbers: observe a controlled
> equip-to-different-slot experiment and diff which byte in `MemberData` (or
> a related component) changes per slot — or use Script Extender
> (`Ext.Entity.Get(...)` in Lua) to read the live `EquipmentSlot` value directly.

### Also in the blob

- Spell / ability IDs as a large pool of NUL/concatenated ASCII (e.g.
  `Projectile_EldritchBlast`, `Shout_SecondWind`). This parser extracts these by
  known spell-ID prefixes and attributes them to characters by class heuristics
  (imperfect for multiclass/shared abilities).
- Earlier analysis suggested some unique items (Shifting Corpus Ring, Spidersilk
  Armour) had no LSF `Item` node — this was incorrect. Ground-truth verification
  shows both `MAG_FlamingFist_ScoutRing` (Shifting Corpus Ring) and
  `GOB_DrowCommander_Leather_Armor` (Wyll's chest piece, confirmed worn, probable
  Spidersilk Armour by context) have full frame-0 Item nodes with the equip bit
  set and are attributed correctly by the position-matching approach. The display
  name for `GOB_DrowCommander_Leather_Armor` is not in the root templates scanned,
  so it remains unresolved — the related template `GOB_DrowCommander_Armor_Leather`
  (Stats `ARM_StuddedLeather_Body_Drow`) resolves as "Spidersilk Armour" and
  likely shares an inheritance chain.

---

## 7. Localisation (`.loca`)

`english.loca` lives inside `Localization/English.pak` and maps handles → text.

| Offset | Type | Field |
|-------:|------|-------|
| 0 | char[4] | magic `"LOCA"` |
| 4 | u32 | number of entries |
| 8 | u32 | texts offset (where the string blob begins) |

Then `numEntries` entry headers:

```
char[64] key (NUL-terminated handle, e.g. "h0f8bb066g...")
u16      version
u32      length  (bytes of this entry's text, including trailing NUL)
```

The header block ends exactly at `textsOffset`; texts follow in entry order,
each `length` bytes (UTF-8, trailing NUL). A `TranslatedString` attribute's
handle indexes straight into this table.

---

## 8. Status / open problems

| Capability | Status |
|------------|--------|
| LSPK extract (pak + save frames) | ✅ |
| LSF parse (V2 layout, saves + `_merged.lsf`) | ✅ |
| V3 (`KeysAndAdjacency`) LSF layout | not exercised by these files; format documented above |
| Character / class / level / XP | ✅ (Info.json) |
| Per-character item ownership | ✅ (Translate matching) |
| Display names | ✅ (root templates + `.loca`) |
| Spell lists | ⚠️ heuristic (string pool + class rules) |
| **Worn-vs-carried** | ✅ 34/34 correct: union of `Flags` bit, STATUS signal, and ECS membership count ≥ 15 (`MemberComponent` ownerlist is one of the 35 equipped-only signals; controlled diff, saves 242/243) |
| Exact equipment slot (Boots / Amulet / Cloak / …) | ❌ `EntityHandle`-gated; absent from on-disk serialisation |
| LSMF component-type directory | ✅ decoded (355 entries: name → elem\_size / row\_count / data\_offset) |
| LSMF ownerlist region (equipped/carried signal) | ✅ decoded (membership count per entity; threshold 15) |
| LSMF `MemberComponent` / `MemberData` structure | ✅ traced (8-byte pointer + 16-byte {ptr\_a, EntityHandle}) |
| LSMF `EntityHandle` → GUID translation | ❌ no on-disk table; requires live game state |
| Osiris story (frame 9) | ❌ not parsed |

---

## References

- LSLib — `LSLib/LS/Resources/LSF/LSFCommon.cs` (structs), `LSFReader.cs`
  (V2/V3 selection), `NodeAttribute.cs` (type enum), `LSPKReader` (package).
- bg3se — `BG3Extender/GameDefinitions/Components/Inventory.h`, `Stats.h`
  (component layouts), `Enumerations/Stats.inl` (`ItemSlot`).
