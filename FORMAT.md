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
> (`_extract_frames`). The full LSPK reader above (`_lspk_filelist` /
> `_lspk_extract`) is used for the game `.pak`s.

### Frame map of a `.lsv` save

| Frame | Contents |
|------:|----------|
| 0 | **Globals** — `Characters`, `Items`, item `Creators` (Entity→TemplateID), and the `NewAge` LSMF blob |
| 3 | **`SCL_Main_A` level cache** — ~11.8 k live `Item` nodes with `Stats` names and world transforms |
| 8 | **`Info.json`** — plain JSON: save name, game version, active party (class/level/XP/location) |
| 9 | **Osiris** story state — binary, not parsed here |

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

> **Gotcha (this cost a real bug):** observed files use `MetadataFormat` `0`
> (saves) or `2` (the game's root-template `_merged.lsf`). Both are the **V2**
> layout — `2` is *not* extended. Keying the node width off `mfmt != 0` wrongly
> picks 16-byte nodes for the `_merged.lsf`, corrupting the node table. This
> parser instead detects the V2/V3 split via the presence of a **keys section**
> (`keys_unc/keys_disk != 0`), which coincides with `KeysAndAdjacency`. The
> strictly correct test is `MetadataFormat == 1`.

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

**Worn vs carried is *not* recoverable from LSF data.** The `Flags` field has no
reliable equipped bit: a worn item that grants no on-equip passive is
byte-identical to a carried one (e.g. worn Evasive Shoes `Flags=0x0000000c`
equals a carried Torch), three other worn items lack the `0x04000000` bit, and a
*spare* item can carry it as a false positive. The authoritative worn set + slot
live only in the ECS blob ([§6](#6-the-lsmf-ecs-blob-newage)). This parser
therefore reports three buckets: positively-signalled **Equipped**, definitely
non-equipment **Carried**, and **"worn or carried — undetermined"**.

---

## 4. Item flags (`Item.Flags`, observed bits)

Not authoritative for equipped state (see above), but observed:

| Bits (mask) | Meaning (inferred) |
|------------:|--------------------|
| `0x0000000c` | baseline, present on essentially every item |
| `0x04000000` | set on *most* worn equipment — but incomplete and with false positives |
| `0x00000100` / `0x00200000` | seen on bags/containers (AlchemyPouch, Keychain) |
| high bits (`0x80000000_0000…`) | seen on consumables / quest items |

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

### Header

| Offset | Type | Field |
|-------:|------|-------|
| 0 | char[4] + 4 | magic `4C 53 4D 46 01 01 00 08` (`LSMF` + version-ish) |
| 8 | u64 | (unidentified; looks like a hash/build id) |
| 16 | **u64** | **offset to the component-type directory** (≈30 KB before EOF) |
| 24 | u64 | (size/count, unidentified) |
| … | | component column data, then the directory |

### Component-type directory (✅ located)

`blob[16]` points to a directory listing **every component type present**,
grouped by namespace. Names are stored **without** the `eoc::` / `ls::` prefix
(so a search for the full bg3se name like `eoc::inventory::MemberComponent`
fails; the substring `MemberComponent` is present). The inventory cluster is
contiguous, e.g. in `QuickSave_242` around byte 4068640–4069200:

```
CanBeWieldedComponent · ContainerSlotData · MemberData · MemberComponent ·
OwnerComponent · StackMemberComponent · WieldedComponent · …
```

The directory's exact binary framing is **not yet decoded**: the names are not
simple `u16`-length-prefixed strings — they appear concatenated with
namespace/tag bytes (e.g. `swarm` + `MemberComponent` + `game…`).

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

1. The directory's name/column framing isn't cracked, so columns can't yet be
   mapped to component types programmatically.
2. Component rows cross-reference entities by **`EntityHandle`** (a packed
   index+salt), not by the 16-byte GUIDs used elsewhere. There is no decoded
   handle → GUID / handle → item table, so even after locating the
   `MemberComponent` column you can't yet say *which* item/character a row is.
3. The blob contains no slot-name or full-component-name strings to anchor on
   beyond the directory.

> Approaches that **failed** and shouldn't be retried as-is: treating the
> per-component GUID arrays as ownership lists (they're ordered by entity handle
> = creation order), and co-occurrence / run-segmentation / run-header scans of
> the column data. The viable path is to decode the directory framing, then the
> entity/handle tables, then read `MemberComponent` — a substantial effort.

### Also in the blob

- Spell / ability IDs as a large pool of NUL/concatenated ASCII (e.g.
  `Projectile_EldritchBlast`, `Shout_SecondWind`). This parser extracts these by
  known spell-ID prefixes and attributes them to characters by class heuristics
  (imperfect for multiclass/shared abilities).
- A few unique items (e.g. Shifting Corpus Ring, Spidersilk Armour) exist
  **only** as ECS entities here, with no LSF `Item` node, so they can't currently
  be named or attributed.

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
| **Worn-vs-carried, exact slot** | ❌ needs `MemberComponent.EquipmentSlot` from the LSMF blob |
| LSMF component-type directory | ✅ located; framing ❌ |
| LSMF entity/handle tables, component columns | ❌ open frontier |
| Osiris story (frame 9) | ❌ not parsed |

---

## References

- LSLib — `LSLib/LS/Resources/LSF/LSFCommon.cs` (structs), `LSFReader.cs`
  (V2/V3 selection), `NodeAttribute.cs` (type enum), `LSPKReader` (package).
- bg3se — `BG3Extender/GameDefinitions/Components/Inventory.h`, `Stats.h`
  (component layouts), `Enumerations/Stats.inl` (`ItemSlot`).
