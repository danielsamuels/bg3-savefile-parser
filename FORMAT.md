# Baldur's Gate 3 save / data file format

A reference for the binary formats this parser reads: the `.lsv` save package,
the LSPK packages it (and the game data) are stored in, the LSF resource format
inside them, the `LSMF` ECS blob that holds the live world state, and the
`.loca` localisation format.

**Provenance.** Everything here was verified by parsing real files (a Patch-8
BG3 save, `QuickSave_242`, game version 4.1.1.7209685) unless noted. Field
names and the parts not yet decoded are cross-checked against two upstream
projects, neither of which is required to run this parser:

- LSLib (Norbyte): the canonical C# reader for LSPK / LSF / `.loca`.
  Paths below like `LSLib/LS/Resources/LSF/LSFCommon.cs` refer to it.
- bg3se (Norbyte's Script Extender): C++ definitions of the ECS
  *components* as they exist in live game memory (`BG3Extender/GameDefinitions/`).
  bg3se does **not** read the on-disk save; it reads RAM. LSLib reads the save
  but treats the `LSMF` blob as opaque bytes. So no existing tool decodes the
  ECS blob from a save; see [§6](#6-the-lsmf-ecs-blob-newage).

All integers are little-endian.

---

## Contents

- [Layering at a glance](#layering-at-a-glance)
- [1. LSPK package format (version 18)](#1-lspk-package-format-version-18)
  - [Frame map of a `.lsv` save](#frame-map-of-a-lsv-save)
  - [Frame 6: `MetaData` node attributes (fully decoded, 2 KB LSOF)](#frame-6-metadata-node-attributes-fully-decoded-2-kb-lsof)
  - [§1a. Frame 2: `CRE_Main_A` level state](#1a-frame-2-cre_main_a-level-state)
  - [§1b. Frame 5: `WLD_Main_A` level state](#1b-frame-5-wld_main_a-level-state)
- [2. LSF (LSOF) resource format](#2-lsf-lsof-resource-format)
  - [Header](#header)
  - [MetadataFormat and the V2 vs V3 layout](#metadataformat-and-the-v2-vs-v3-layout)
  - [String hash table (strings section)](#string-hash-table-strings-section)
  - [Node entries (nodes section)](#node-entries-nodes-section)
  - [Attribute entries (attributes section)](#attribute-entries-attributes-section)
  - [Attribute value types](#attribute-value-types)
- [3. Characters, items, and per-character ownership](#3-characters-items-and-per-character-ownership)
- [4. Item flags (`Item.Flags`, observed bits)](#4-item-flags-itemflags-observed-bits)
- [5. Game-data root templates (display names)](#5-game-data-root-templates-display-names)
- [6. The `LSMF` ECS blob ("NewAge")](#6-the-lsmf-ecs-blob-newage)
  - [Header](#header-1)
  - [Component-type directory (✅ decoded)](#component-type-directory--decoded)
  - [Ownerlist region (✅ decoded)](#ownerlist-region--decoded)
  - [Cross-component references: absolute byte-pointers (✅ decoded)](#cross-component-references-absolute-byte-pointers--decoded)
  - [Heap arrays and the string pool (✅ decoded)](#heap-arrays-and-the-string-pool--decoded)
  - [Spell books (✅ decoded: exact per-character spell lists)](#spell-books--decoded-exact-per-character-spell-lists)
  - [Character classes, templates, and origins (✅ decoded)](#character-classes-templates-and-origins--decoded)
  - [Inventory containers (✅ decoded: ownership web)](#inventory-containers--decoded-ownership-web)
  - [The equipment cluster (✅ decoded: worn items form a row block)](#the-equipment-cluster--decoded-worn-items-form-a-row-block)
  - [Entity-GUID bridge: corrects an earlier "no link exists" claim (✅ found)](#entity-guid-bridge-corrects-an-earlier-no-link-exists-claim--found)
  - [`MemberData` / `MemberComponent`: diff experiment and EntityHandle wall](#memberdata--membercomponent-diff-experiment-and-entityhandle-wall)
  - [What the equipment data looks like (from bg3se, in live memory)](#what-the-equipment-data-looks-like-from-bg3se-in-live-memory)
  - [Transform array (partially mapped)](#transform-array-partially-mapped)
  - [What blocks a full decode](#what-blocks-a-full-decode)
  - [Ability scores and hit points: packed streams (✅ decoded 2026-06)](#ability-scores-and-hit-points-packed-streams--decoded-2026-06)
  - [Prepared spells (✅ decoded 2026-06)](#prepared-spells--decoded-2026-06)
  - [Camp supplies: a cached value (✅ decoded 2026-06)](#camp-supplies-a-cached-value--decoded-2026-06)
  - [Also in the blob](#also-in-the-blob)
- [7. Localisation (`.loca`)](#7-localisation-loca)
- [8. Status / open problems](#8-status--open-problems)
- [9. Osiris story state (frame 9)](#9-osiris-story-state-frame-9)
  - [File header (unscrambled, 193 bytes total)](#file-header-unscrambled-193-bytes-total)
  - [Section order and observed sizes (QuickSave_242)](#section-order-and-observed-sizes-quicksave_242)
  - [Value encoding (ver ≥ `OSI_VER_VALUE_FLAGS`)](#value-encoding-ver--osi_ver_value_flags)
  - [Node types and parse layout](#node-types-and-parse-layout)
  - [Key quest-state databases](#key-quest-state-databases)
  - [Current quest objectives (LSF Journal, not Osiris)](#current-quest-objectives-lsf-journal-not-osiris)
  - [Goal flags](#goal-flags)
- [References](#references)

---

## Layering at a glance

```
.lsv save file  ──►  LSPK package  ──►  N files ("frames"), each an LSF resource
                                              │
   .pak game data ──► LSPK package  ──►       ├─ frame 0  Globals  ── contains ─┐
                                              ├─ frame 3  level cache           │
                                              ├─ frame 6  MetaData (save time,  │
                                              │            mods, session UUIDs) │
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
| 0 | LSOF | 3.1 MB | ✅ | **Globals**: `Characters`, `Items`, item `Creators` (Entity→TemplateID), and the `NewAge` LSMF blob; ~30 root regions including `Story`, `Journal`, `Waypoints`, `GameControl` |
| 1 | LSOF | 153 KB | ❌ | **Secondary level LSF**: 14 root regions (`Characters`, `Items`, `ItemMover`, `Triggers`, `Projectiles`, `Constellations`, `ConstellationHelpers`, `VariableManagers`, `AnubisFramework`, `SavedStates`, `Splines`, `CacheTemplates`, `NewAge`, `ModuleSettings`); 32 Character nodes (NPC-only, no party origin GUIDs), 79 Item nodes (world loot, no Translate or Stats matching any party position). A background/secondary area level cache. Contains no party character data and no party-owned items; not useful for the report. |
| 2 | LSOF | 2.1 MB | ❌ | **`CRE_Main_A` level cache**: 123 Character nodes, 2,024 Item nodes (world entities for a secondary area); no party-owned items |
| 3 | LSOF | 10.8 MB | ✅ | **Level cache** (`SCL_Main_A`): `Characters`, `Items`, `Surfaces`, AI state, `CrimeHandler`; ~11.8 k live `Item` nodes with `Stats` and world transforms |
| 4 | LSOF | 24 KB | ❌ | **Compact snapshot**: 37 root regions (most unresolved names `?XXXXXXXX`; resolved: `Characters`, `Items`, `Projectiles`, `Constellations`, `AtmosphereOverrides`, `AITurnData`, `CrimeHandler`, `Level`, `ModuleSettings`); 1 Character node (empty attrs, no template GUID), 0 Item nodes. Likely a minimal respawn-point or transition-screen state. No party data, no items. |
| 5 | LSOF | 14.7 MB | ❌ | **`WLD_Main_A` level cache**: 669 Character nodes, 14,833 Item nodes (world entities for the main open area); no party-owned items |
| 6 | LSOF | 2 KB | ✅ | **`MetaData`**: save metadata: wall-clock save time (Unix epoch), save number, campaign/session UUIDs, party leader name, RNG seed, mod list (`ModuleShortDesc` nodes), difficulty code, active ruleset UUIDs, game version, camera state |
| 7 | RIFF | ~1.7 MB | ✅ | **Load-screen thumbnail**: RIFF/WebP (lossy VP8), 1280×720 px; extracted by `extract_thumbnail` with `--thumbnail PATH` |
| 8 | JSON | 2.5 KB | ✅ | **`Info.json`**: save name, game version, difficulty, current level, active party (class/level/XP) |
| 9 | Osiris | 47.7 MB | ❌ | **Osiris database**: scripting engine state (`Osiris save file, Version 1.8`): quest flags, story counters, dialogue state |

### Frame 6: `MetaData` node attributes (fully decoded, 2 KB LSOF)

Frame 6 decompresses to ~2 077 bytes and contains a single `MetaData` root with
one child `MetaData` node that carries all attributes, plus several child nodes
(`ModuleSettings/Mods`, `GameVersions`, `PartyMetaData`, `ClientDatas`,
`Rulesets`, `CustomRulesetValues`). The useful attributes on the inner
`MetaData` node:

| Attribute | Type | Observed value | Notes |
|-----------|------|---------------|-------|
| `SaveTime` | UInt (5) | `1780520898` | Wall-clock save time, Unix epoch seconds (verified: `datetime.utcfromtimestamp(1780520898)` → 2026-06-03 21:08:18 UTC) |
| `SaveGameID` | Int (4) | `242` | Save slot number; matches the filename |
| `SaveGameType` | Int (4) | `1` | Save type code; `1` observed for QuickSave; mapping unverified beyond one save |
| `GameID` | UUID (31) | `bd8ccd4d-…` | Persistent campaign identity |
| `GameSessionID` | UUID (31) | `ea7c1dd2-…` | Per-session identity (changes each play session) |
| `LeaderName` | String (20) | `"Maia"` | Party leader display name |
| `Seed` | UInt (5) | `176876464` | RNG seed for this save |
| `Modded` | Bool (19) | `true` | True when any non-base modules are listed in the mod table |
| `HasUnofficialMods` | Bool (19) | `false` | BG3's own "tainted" flag; observed False when only UI/cosmetic mods are installed alongside GustavX; exact triggering conditions unverified beyond one save |
| `Difficulty` | Int (4) | `2` | Difficulty code (2 observed with `DifficultyMedium` per `Info.json`; full enum unknown) |
| `Level` | FixedString (22) | `"SCL_Main_A"` | Current level; same as `Info.json "Current Level"` |
| `CurrentSubRegion` | FixedString (22) | `""` | Current sub-region (may be empty) |
| `TutorialFinished` | Bool (19) | `true` | |
| `Sanity` | Bool (19) | `true` | |
| `Crossplay` | Bool (19) | `false` | |
| `DisabledSingleSave` | Bool (19) | `false` | |
| `DishonorDifficultySelection` | UUID (31) | null UUID | Honour-mode tracking (null UUID = not in Honour mode) |
| `TimeStamp` | UInt (5) | `147905` | In-game time counter; units unverified |
| `OriginalPlatform` | Int (4) | `7` | Platform code; `7` observed for Steam; full enum unknown |

**Redundant with `Info.json`:** `Level`, `Difficulty` code, game version (under
`GameVersions/GameVersion.Object`).

**Child nodes of interest:**

- `ModuleSettings/Mods/ModuleShortDesc`: one entry per active mod (`Name`,
  `Folder`, `MD5`, `Version64`, `PublishHandle`, and a `UUID` field).
  **UUID byte-order warning:** the `UUID` field in `ModuleShortDesc` does not
  follow the standard UUID byte-layout used elsewhere in LSF (the last two
  groups of bytes are swapped compared to the canonical form embedded in the
  `Folder` string, e.g. `Folder = "ImpUI_26922ba9-6018-5252-075d-7ff2ba6ed879"`
  vs `UUID` attr reads as `26922ba9-6018-5252-5d07-f27f6eba79d8`).  Use the
  `Folder` string for canonical mod identity, not the parsed `UUID` attr.
  GustavX is always present (base game module); additional entries are
  user-installed mods.
- `GameVersions/GameVersion.Object`: `FixedString` game version, e.g.
  `"4.1.1.7209685"`.
- `Rulesets`: two `FixedString` ruleset UUIDs (one per `Rulesets` node);
  the second corresponds to `RulesetLarian` per `Info.json`.
- `PartyMetaData/CharacterMetaData`: per-character icon IDs and name
  handle refs (loca/runtime handles; not resolved by this parser).
- `ClientDatas/ClientData`: UI state (`Slot`, `HotbarLocked`,
  `GameCameraDistance`, `GameCameraRotation`).

### §1a. Frame 2: `CRE_Main_A` level state

47,201 nodes, 27 root regions (V2 12-byte layout; `keys_unc`/`keys_disk` != 0
but `MetadataFormat = 0`). Structure is identical to frame 3: the same 27
top-level root names (`Characters`, `Items`, `Surfaces`, `GridDefinition`,
`ShroudManager`, `NewAge`, `AIGridHelper`, `CrimeHandler`, etc.).

**Node counts:** 123 `Character` nodes, 2,024 `Item` nodes.

**`GridDefinition` → `AiGridDefinition` (navmesh):**

```
GridDefinition
  └─ AiGridDefinition
       ├─ Buffer   ScratchBuffer   577,366 bytes on disk
       │                           LZ4-block compressed; Size attr = 5,112,224
       │                           (decompress with lz4.block.decompress(buf, uncompressed_size=Size))
       │                           Decompressed content: proprietary navmesh format (not decoded)
       ├─ Size     UInt            5,112,224   (uncompressed byte count for Buffer)
       └─ SubgridDefinition  ×362  (Object tiles — one per navmesh sub-region)
            ├─ MapKey     UInt     (tile identity, u32)
            ├─ Width      Int      (grid cells, varies; e.g. 2–128)
            ├─ Height     Int      (grid cells)
            ├─ Position   Vec3     (world-space origin of this tile)
            └─ LoadedExternally  Bool
```

Grid bounds (from `ShroudData` header): X ∈ [−867, 3759], Z ∈ [−2088, 852].

**`ShroudManager` → `Shroud` (fog-of-war):**

```
ShroudData   ScratchBuffer   213,088 bytes
```

`ShroudData` layout (verified by byte inspection):

| Offset | Type | Field |
|-------:|------|-------|
| 0 | i32 | min_x = −867 |
| 4 | i32 | min_z = −2088 |
| 8 | i32 | max_x = 3759 |
| 12 | i32 | max_z = 852 |
| 16–31 | — | 16 zero bytes |
| 32… | — | opaque runtime-serialised visibility data (not structurally decoded) |

**`NewAge` LSMF blob:** 3,581,032 bytes (same ECS format as frame 0; see §6).

### §1b. Frame 5: `WLD_Main_A` level state

330,830 nodes, 27 root regions (V2 12-byte layout; same caveat as §1a).
Structure is identical to frames 2/3.

**Node counts:** 669 `Character` nodes, 14,833 `Item` nodes.

**`GridDefinition` → `AiGridDefinition` (navmesh):**

```
GridDefinition
  └─ AiGridDefinition
       ├─ Buffer   ScratchBuffer   3,231,503 bytes on disk
       │                           LZ4-block compressed; Size attr = 14,302,818
       ├─ Size     UInt            14,302,818
       └─ SubgridDefinition  ×1,273  (Object tiles)
            ├─ MapKey / Width / Height / Position / LoadedExternally  (same as §1a)
```

Grid bounds: X ∈ [−3150, 1081], Z ∈ [−1117, 1319].

**`ShroudManager` → `Shroud`:**

`ShroudData` is 161,361 bytes. Header (same layout as §1a):

| Field | Value |
|-------|-------|
| min_x | −3150 |
| min_z | −1117 |
| max_x | 1081 |
| max_z | 1319 |

**`NewAge` LSMF blob:** 24,720,344 bytes (same ECS format as frame 0 but
larger; `WLD_Main_A` is the main open-world level).

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
| 16 | u32 | strings: uncompressed size |
| 20 | u32 | strings: size on disk |
| 24 | u32 | **keys**: uncompressed size |
| 28 | u32 | **keys**: size on disk |
| 32 | u32 | nodes: uncompressed size |
| 36 | u32 | nodes: size on disk |
| 40 | u32 | attributes: uncompressed size |
| 44 | u32 | attributes: size on disk |
| 48 | u32 | values: uncompressed size |
| 52 | u32 | values: size on disk |
| 56 | u8 | compression flags (low nibble = method, high nibble = level) |
| 57 | u8 | unknown (0) |
| 58 | u16 | unknown |
| 60 | u32 | **MetadataFormat** (see below) |

The four data sections (**strings, nodes, attributes, values**) follow
immediately, in that order, starting at offset 64. A section's on-disk byte
count is `sizeOnDisk` when compressed, or the **uncompressed size when
`sizeOnDisk == 0`** (uncompressed sections, common in the game's
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
> layout; `2` is *not* extended. Keying the node width off `mfmt != 0` wrongly
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

**V2, 12 bytes:**

| Offset | Type | Field |
|-------:|------|-------|
| 0 | u32 | name handle (MSB16 = chain, LSB16 = offset in chain) |
| 4 | i32 | first attribute index (`-1` = none) |
| 8 | i32 | parent index (`-1` = root region) |

**V3, 16 bytes** (`KeysAndAdjacency` only):

| Offset | Type | Field |
|-------:|------|-------|
| 0 | u32 | name handle |
| 4 | i32 | parent index |
| 8 | i32 | next sibling index |
| 12 | i32 | first attribute index |

### Attribute entries (attributes section)

**V2, 12 bytes** (used by saves & `_merged.lsf`):

| Offset | Type | Field |
|-------:|------|-------|
| 0 | u32 | name handle |
| 4 | u32 | type-and-length: `type = v & 0x3F`, `length = v >> 6` |
| 8 | i32 | owning node index |

V2 attribute **values** are stored back-to-back in the values section in
attribute order; walk a running offset, advancing by each attribute's `length`.

**V3, 16 bytes** (`KeysAndAdjacency` only): name handle (u32), type-and-length
(u32), next-attribute index (i32), explicit value **offset** (u32). Attributes
are chained per node from the node's `first attribute index`.

### Attribute value types

Full type enum (`LSLib/LS/NodeAttribute.cs`); ✓ = decoded by this parser:

| ID | Type | ID | Type | ID | Type |
|---:|------|---:|------|---:|------|
| 0 | None | 13 | Vec4 | 25 | ScratchBuffer ✓ (opaque bytes: the LSMF blob) |
| 1 | Byte ✓ | 14 | Mat2 | 26 | Long/Int64 ✓ |
| 2 | Short ✓ | 15 | Mat3 | 27 | Int8 |
| 3 | UShort ✓ | 16 | Mat3x4 | 28 | TranslatedString ✓ (u16 version, i32 len, handle) |
| 4 | Int ✓ | 17 | Mat4x3 | 29 | WString ✓ |
| 5 | UInt ✓ | 18 | Mat4 | 30 | LSWString ✓ |
| 6 | Float ✓ | 19 | Bool ✓ | 31 | UUID ✓ (16 bytes, little-endian) |
| 7 | Double | 20 | String ✓ | 32 | Int64 ✓ |
| 8–10 | IVec2–4 | 21 | Path ✓ | 33 | TranslatedFSString |
| 11 | Vec2 | 22 | FixedString ✓ | | |
| 12 | **Vec3 ✓** (3 × float, used for `Translate`) | 23 | LSString ✓ | 24 | ULongLong ✓ |

String types (20–23, 29, 30) store `length` bytes including a trailing NUL.
`TranslatedString` (28) stores a localisation **handle** (e.g.
`h0f8bb066g...`) resolved via `.loca` ([§7](#7-localisation-loca)).

---

## 3. Characters, items, and per-character ownership

Within frame 0 / frame 3 LSF trees:

- Party characters are `Character` nodes whose `CurrentTemplate` GUID is one
  of the known origin template GUIDs (Maia/Wyll/Karlach/Shadowheart in the test
  save). Each has a `Translate` (Vec3 world position).
- Items are `Item` nodes with `Stats` (internal name, e.g.
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
in multiple `Item` nodes in frame 0, once per actual instance (equipped copy,
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
| `0x04000000` | worn-equipment signal: present on 32/34 worn items; **absent** on 2 worn items (Evasive Shoes, Pearl of Power Amulet) and **present** on at least 1 inventory item (`DEN_HellridersPride`) as a false positive |
| `0x00000100` / `0x00200000` | seen on bags/containers (AlchemyPouch, Keychain) |
| `0x00040000` | seen on some items with `PreviousLevel` set (items moved between areas) |
| high bits (`0x80000000_0000…`) | consumables, quest items, some unequipped spares; **never** seen on any of the 34 verified worn items; useful as a negative signal |

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
`ParentTemplateId` (inheritance; follow it when `DisplayName` is absent), and
`DisplayName` (a `TranslatedString` handle).

> In a live save, items use a **per-save local** `CurrentTemplate` GUID that is
> absent from the static templates (0 of ~11.6 k matched), so resolution is by
> **Stats name** in practice. ~9 % of stats names map to >1 display name; an
> ambiguous one resolves to the first/base variant.

---

## 6. The `LSMF` ECS blob ("NewAge")

The single biggest piece of live state. It is stored as one LSF attribute of
type **ScratchBuffer (25)** on the root `NewAge` node of frame 0: an opaque
~4 MB byte buffer that LSLib does **not** decode. It is a **columnar
Entity-Component-System dump**.

> **Extraction gotcha.** The LSMF blob lives inside the LSF **values section**,
> which is itself LZ4-compressed (§2). A raw scan of the decompressed `.lsv` frame
> for `4C 53 4D 46` (`LSMF`) magic bytes will find a **false positive** in the
> LSF strings section at approximately offset 1 730 992 (the ASCII text `LSMF`
> appears there as part of a node name). The actual blob is only reachable by
> fully parsing the LSF (decompressing the values section and reading the
> `NewAge → ScratchBuffer` attribute value), as `parse_lsof` does.

### Header

| Offset | Type | Field |
|-------:|------|-------|
| 0 | char[4] + 4 | magic `4C 53 4D 46 01 01 00 08` (`LSMF` + version-ish) |
| 8 | u64 | (unidentified; looks like a hash/build id) |
| 16 | **u64** | **dir_off**: raw directory pointer; `names_off` (actual directory start) = `dir_off + 48` |
| 24 | **u64** | **names_size**: byte length of the component-names blob |
| 32 | **u32** | **desc_table_rel**: descriptor-table offset, relative to `names_off` |
| 36 | **u16** | **entry_count**: number of component descriptors (355 in QuickSave_242) |
| 48… | | component column data, then the directory region |

### Component-type directory (✅ decoded)

`blob[16:24]` stores `dir_off`; the directory starts at `names_off = dir_off + 48`.
It lists **every component type present**: 355 entries in `QuickSave_242`. Names
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
~350 types, e.g. `core.v0.EntityId` (elem=16: one entity-instance GUID per
row), `game.inventory.v0.MemberData` (#125, elem=16, rows=1314,
data_off=0x166010), `game.inventory.v0.MemberComponent` (#126, elem=8,
rows=1314, data_off=0x16b230). The inventory cluster is contiguous in the
names blob: `CanBeWieldedComponent · ContainerSlotData · MemberData ·
MemberComponent · OwnerComponent · StackMemberComponent · WieldedComponent · …`

> Dump the full directory of any save with the bundled exploration harness:
> `uv run explore_lsmf.py <save-number-or-path>` prints every component's
> element size, row count, ownerlist length, and data offset; imported as a
> module it exposes row access, ownerlist lookup, offset→component resolution,
> and the item→entity bridge for further reverse engineering.

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
(0-based) is its column index into the component's data, *not* its
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
**direct absolute byte offset into the blob**: not a handle, not a GUID. A
`locate(offset)` helper (scan all `ComponentDesc` entries for
`data_offset <= off < data_offset + elem_size*row_count`) resolves any such
value to `(component_name, row_index, byte_in_row)`. Every
`MemberData.ptr_a` (below) resolves with `byte_in_row == 0` against
`core.v0.EntityId`: i.e. it points at the start of an entity's 16-byte GUID
record, the closest thing to a stable cross-reference the on-disk format has.

### Heap arrays and the string pool (✅ decoded)

Variable-length component fields (arrays, hash maps, strings) live in two
regions outside the fixed-size column data:

- An **auxiliary heap** after the column data (~`0x37e000–0x38b000` in the
  test saves) holding serialized arrays. A component row stores such an array
  as a `{u64 begin, u64 end}` byte range; `0xFFFFFFFFFFFFFFFF` marks an empty
  slot.
- A **string pool** of concatenated ASCII (no separators, no NULs between
  entries): spell IDs, template GUID strings, origin names. Entries are
  referenced as `{pointer, length}` pairs.

**Pointer base quirk:** pointers into the heap and string pool are stored as
`(absolute offset − 48)`, the same convention as the header's `dir_off`,
while pointers into component column data are plain absolute offsets (they
resolve against descriptor `data_offset` values with `byte_in_row == 0`).
Add 48 before dereferencing a heap/pool pointer.

### Spell books (✅ decoded: exact per-character spell lists)

The complete chain from a character to its spells:

```
game.spell.v3.SpellBookComponent   row = {u64 begin, u64 end}
        │ byte range into…
game.spell.v3.SpellData            72-byte rows; field 6 (offset 48) = u64 ptr to…
game.spell.v0.SpellId              24-byte rows = {ptr_meta|ptr_str, ptr_str|len, len|ptr_src}
        │ {string ptr (+48), length} into…
the concatenated spell-ID string pool   →  "Shout_ActionSurge", …
```

Each character's `SpellData` rows are contiguous, so books are `{begin, end}`
slices. `SpellId` records appear in (at least) three shapes across save
versions: `{meta_ptr, str_ptr, len}`, `{str_ptr, len|flags, src_ptr}`, and
`{meta_ptr, str_ptr, len|generation}`: so a robust reader tries both
`(pointer, length)` pairings and accepts the one yielding printable ASCII.
Other `SpellData` fields: `[1]`/`[3]` point at enum singletons
(`ECooldownType`, `EAbility`), `[4]`/`[5]` are a `{begin, end}` slice into
`game.spell.v2.CastRequirements`, `[7..8]` hold a 16-byte GUID.

The decoded books are **complete and current**: class abilities, racial and
illithid powers, item-granted spells (they appear when the item is equipped
and disappear when it is removed), and mod-added spells all show up.

### Character classes, templates, and origins (✅ decoded)

- `game.stats.v0.ClassesComponent` (elem=16): `{begin, end}` heap range of
  40-byte entries `{16B class GUID, 16B subclass GUID, u64 level}`: one entry
  per class in a multiclass build. The GUIDs are the static UUIDs from the
  game's `ClassDescriptions.lsx`, so a save-side entity can be matched to
  `Info.json`'s per-member `(Main, Sub, Level)` without heuristics.
- `game.templates.v0.TemplateComponent` (elem=24):
  `{u64 ptr, u32 len=36, u32 idx, u64 ptr2}`: the entity's template GUID
  stored as a 36-char ASCII string in the pool (pointer needs +48).
- `game.character_creation.v0.OriginComponent` (elem=16): the character's
  origin, stored either as a `{ptr, len}` pool string (`"Lae'zel"`) or as the
  inline 16-byte origin UUID from `Origins.lsx` (e.g.
  `efc9d114-0296-4a30-b701-365fc07d44fb` = Wyll).

**One character is many entities.** A party member exists as several distinct
ECS entities: the world/body entity (whose GUID the LSF `Creators` table maps
to the character's `CurrentTemplate`), a spell-state entity (owning
`SpellBookComponent` / `ClassesComponent` / `LearnedSpells`), a party-slot
entity (`game.party.v0.MemberComponent`), a player entity
(`game.v0.PlayerComponent`), and origin-pool stand-ins (small NPC-grade spell
books, one per recruitable companion). Some `core.v0.EntityId` rows for these
special entities hold handle-like values, not GUIDs. The reliable link from a
party member to its spell-state entity is **class matching**: the entity whose
`ClassesComponent` equals the member's class/subclass/level set, taking the
largest book among candidates (the origin-pool stand-ins are strictly
smaller).

### Inventory containers (✅ decoded: ownership web)

- `game.inventory.v0.OwnerComponent` (elem=24, on characters):
  `{begin, end, u64 primary}`: an Inventories array in the heap plus
  `primary` pointing at the `core.v0.EntityId` row of the character's
  **primary inventory** pseudo-entity. Confirmed: the party leader's primary
  inventory is the container holding their carried items.
- `game.inventory.v1.IsOwnedComponent` (elem=8, on inventory entities):
  pointer to the owner's `EntityId` row.
- `game.inventory.v1.ContainerComponent` (elem=32, on inventory entities
  and containers): two `{begin, end}` heap ranges (empty = `FF…FF`).
- `game.inventory.v0.ContainerSlotData` (elem=16, no ownerlist;
  referenced by pointer): `{u64 ptr → item EntityId row, u32 slot,
  u32 generation}`. `slot` is the position **within that container**
  (inventory-grid cell, *not* the `ItemSlot` enum); `generation` reads as a
  small epoch counter on old rows but as uninitialised garbage (string-pool
  fragments) on fresh ones; don't rely on it. An item that has moved between
  containers can retain **stale rows** alongside its current one, and a slot
  row is **reused in place** when one item replaces another in the same
  container slot (observed when swapping amulets between saves 292→294).
- `game.inventory.v0.MemberData.ptr_a` points at single-item shadow
  inventories whose `IsOwnedComponent` names *other characters*: historical
  ownership bookkeeping (loot source), not current location. Treat
  `MemberComponent`/`MemberData` as a "has been in an inventory" signal, not
  a live container assignment.

**Stack amounts** (✅ decoded): each `game.inventory.v0.NewStackComponent`
row points at a stack record: a `{begin, end}` heap range of member-item
`EntityId` pointers, followed at +16 by a `{begin, end}` range of
`game.inventory.v0.StackEntry` rows, whose 8-byte entries are
`{u32 id, u32 amount}` inline; the record's total is their sum. Verified
against in-game gold piles of 766 and 2017 and a 2-potion stack
(QuickSave_296/297). Items without a record are single. Note the records sit
in the `Stack` component's data region but are **not aligned to its 32-byte
rows**: row-aligned reads produce chimeras; always navigate from the
`NewStackComponent` pointer.

Containers are inventory **grid pages** (~13–16 slots for characters), and a
character's containers freely mix worn and carried items; container identity
alone does **not** mark equipment. The camp **Traveller's Chest** is simply
the largest container (256 slots); its contents are fully listable, with item
identity recovered through `ContainerSlotData → EntityId` and names through
the LSF instance map or, for items with no Creators entry in the current
level, `game.templates.v0.TemplateComponent`: whose pool string is a
*static* root-template GUID, so the GUID→DisplayName path works for it.

### The equipment cluster (✅ decoded: worn items form a row block)

Each character's worn items occupy a **near-contiguous block of
`ContainerSlotData` rows** (their slots in the character's own containers,
allocated together), while an item moved to a bag gets a fresh row far
outside the block and an item that *was* worn keeps its old, now out-of-block
row. Ground-truthed across QuickSave_286–294 for four party members
simultaneously: every genuinely worn item (including ECS-only-signal ones
like the Evasive Shoes) sits inside its character's block, every stale
equip-bit item (Phalar Aluve, Jorgoral's Greatsword, Hellrider's Pride)
sits outside it, with no exceptions.

The parser anchors the block on items whose worn status is already certain
from LSF signals (uncontested Flags-bit items), trims anchors further than
24 rows from the anchor median (stale outliers), widens the span by 8 rows,
and uses membership in that window as the dominant worn/carried signal
(`party.equipment_cluster`). Within the block, row order resolves what the
stat files cannot: Ring vs Ring 2 (QuickSave_291) and main- vs off-hand for
a dual-wield pair (QuickSave_292: Githyanki Shortsword row 954 = main hand,
Dagger row 957 = off hand); earlier row = first/upper slot in both cases.

Two refinements, both in-game verified:

- Virtual slots. An equipped instrument stays in the backpack grid; the
  MusicalInstrument slot is a UI view, so the item's row sits mid-backpack
  while genuinely worn (QuickSave_294/295). Such slots are exempt from
  cluster demotion. The **light-source slot** (a torch on the paper doll) is
  the same phenomenon taken further: it is a view of an inventory item with
  *no* equip bit and no save-side slot at all; dropping the inventory item
  clears the slot (QuickSave_296). The parser reports such torches as
  carried.
- Per-instance classification. Several copies of one item type on a
  character share `(Translate, stats)` *and* often one local template
  (QuickSave_296: four identical Shortswords: two dual-wielded, two in a
  bag). The Creators/Items parallel arrays still give one entity per copy,
  and each copy's own ContainerSlotData rows against the cluster classify it
  individually.

### Entity-GUID bridge: corrects an earlier "no link exists" claim (✅ found)

A prior pass concluded that LSF item/character GUIDs never appear in the LSMF
blob's entity tables, and used that to argue the worn/carried question was
structurally unrecoverable. **That conclusion compared the wrong GUID
namespace.** `CurrentTemplate` on an `Item`/`Character` LSF node is a
*template/content* GUID; `core.v0.EntityId` rows hold *entity-instance* GUIDs:
two disjoint spaces. The bridge between them is the existing
`build_entity_template_map(nodes, root_name)` helper (`entity_guid →
template_guid`); inverted and chained:

```
item.CurrentTemplate ──(invert map for 'Items')──► entity_guid ──(raw 16-byte search)──► core.v0.EntityId row
```

this resolves cleanly for every item tested (Wyll's 7 known-equipped items each
land 5–8 `EntityId` row instances; entities are re-listed multiple times,
seemingly once per save "epoch"/frame). **So entity identity for a known item
*is* recoverable from the blob.** What is *not* recoverable (next section) is
which inventory/slot that entity sits in.

### `MemberData` / `MemberComponent`: diff experiment and EntityHandle wall

**Controlled equip/unequip diff (saves 242 vs 243).** Comparing saves where
Wyll's Evasive Shoes were equipped (save 242, entity row 1597) vs in his bag
(save 243, entity row 1679) identified **35 components whose ownerlist included
entity 1597 but not entity 1679**: components present only when the item is
equipped. `game.inventory.v0.MemberComponent` is one of them. The parser uses
**aggregate membership count** across all ownerlist records (equipped items have
~35–41 memberships; backpack items ~3–6; threshold 15) as its
equipped/carried signal; `MemberComponent` is a cross-check, not the sole
indicator. `MemberComponent` has 1314 rows in save 242 because it covers all
equipped entities in the scene (party, NPCs, world), not just party items.

**`game.inventory.v0.MemberComponent`** (#126, elem=**8**, rows=1314). The bg3se
in-memory struct is:
```cpp
struct MemberComponent { EntityHandle Inventory; int16_t EquipmentSlot; };
```
but the on-disk element is only 8 bytes: an **absolute byte-pointer into
`MemberData`'s data region**. The `EquipmentSlot` field is absent from the
on-disk representation.

**`game.inventory.v0.MemberData`** (#125, elem=16, rows=1314):
`{ u64 ptr_a, u64 handle_b }`.

Prior analysis found that `ptr_a` resolves (via the byte-pointer scheme above)
to a `core.v0.EntityId` row-start; collapsed across duplicates, only **262
distinct GUIDs** appear. **None of the 1419 known item-entity GUIDs is among
those 262**: they are **inventory-container pseudo-entities** (one per
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
billions: positions in the **live game's global entity pool**, not the save's
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
(= `605, 605` as two u16, entity-index-like markers) with `FF`-filled
rotation/scale fields. These give a known-value entry point into entity framing.

### What blocks a full decode

The directory is now decoded (any component's `{elem_size, row_count,
data_offset}` is a lookup away; see above), and entity identity for a *known*
item is recoverable via the `CurrentTemplate → entity_guid → EntityId` bridge.
What remains genuinely blocked:

1. **`EntityHandle` decoding.** `MemberData.handle_b` is a well-formed
   `EntityHandle` (`uint64 = Index(32) | Salt(22)<<32 | Type(10)<<54`; Salt≈852,
   Type=0, confirmed from bg3se source and byte inspection). Its `Index` field
   is in the billions: a position in the live game's global entity pool, not the
   save's local table. There is **no handle → GUID / handle → row table anywhere
   in the on-disk LSF tree** (confirmed by exhaustive whole-tree search). Any
   information gated behind a live `EntityHandle` is unresolvable from the save
   file alone.
2. **Exact equipment slot** (Helmet / Boots / Amulet / …). The save stores no
   *explicit* `ItemSlot` value, established by a byte-level sweep: for 12
   simultaneously-equipped items whose slots were known, no byte position in
   any LSMF component owned by those items consistently equalled the expected
   `ItemSlot` enum value, and `EquipmentVisualComponent` serialises as a null
   pointer. The slot *type* is re-derived from item stats on load (the parser
   does the same: stat-file `Slot` via the `using` chain). What the save does
   preserve is **ordering**: each worn item has a `ContainerSlotData` entry
   with a stable per-container position, which is how assignments the stats
   cannot express (which of two rings sits in Ring vs Ring2, main- vs
   off-hand for dual-wielded weapons) survive a save/load round trip.
   **Ground-truth verified** for both cases: QuickSave_291 (two worn rings:
   the ring with the earlier `ContainerSlotData` **row** sits in the first
   (upper) UI ring slot) and QuickSave_292 (dual-wielded weapons: the
   earlier row is the main hand). The `position` field within the entry is
   the inventory-grid cell and does *not* track the UI order.
3. The blob contains no slot-name or full-component-name strings to anchor on
   beyond the directory.

> Approaches that **failed** and shouldn't be retried as-is: treating the
> per-component GUID arrays as ownership lists (they're ordered by entity handle
> = creation order); co-occurrence / run-segmentation / run-header scans of the
> column data; comparing `CurrentTemplate` GUIDs directly against `EntityId`
> rows (wrong namespace; use the inverted `build_entity_template_map` bridge
> instead); interpreting `MemberData.ptr_a` as a pointer into `ContainerSlotData`
> (confirmed not: ptr_a values ~78 K–98 K fall outside CSD's range
> [1 409 808, 1 430 288), verified against 17 equipped items); attempting to
> derive slot or item identity from the four-`u16` decomposition of `handle_b`
> (it is a live `EntityHandle` with no on-disk translation table; the 30 distinct
> `mid` values are the high-16-bits of the Index field, not slot numbers).
> The viable path for recovering exact slot numbers: observe a controlled
> equip-to-different-slot experiment and diff which byte in `MemberData` (or
> a related component) changes per slot, or use Script Extender
> (`Ext.Entity.Get(...)` in Lua) to read the live `EquipmentSlot` value directly.

### Ability scores and hit points: packed streams (✅ decoded 2026-06)

Two components break the row-grid rule documented above: their data sections
are *packed streams* whose records do not align with the `elem_size` row grid
implied by the descriptor, and whose ownerlists contain phantom entries (an
owner with no record). Reads must anchor on the stream header and realign
owners to records.

- `game.stats.v3.StatsComponent` (descriptor says elem=36): a 20-byte stream
  header, then one 36-byte record per non-phantom owner:

  | Offset | Type | Field |
  |-------:|------|-------|
  | 0 | i32[6] | effective ability scores STR, DEX, CON, INT, WIS, CHA (item effects such as Gloves of Dexterity are folded in) |
  | 24 | i32 | proficiency bonus |
  | 28 | u16 | small enum |
  | 30 | u16 | per-save handle |
  | 32 | i32 | zero |

- `game.stats.v0.HealthComponent` (descriptor says elem=32): a 16-byte stream
  header, then 32-byte records `{i32 current, i32 max, i32 temp,
  i32 temp_max, 16-byte GUID}`. Entities can appear in two epochs with the
  current state first, so the first occurrence per entity wins.

The owner-to-record realignment is a small dynamic program
(`solve_owner_shifts` in `lsmf.py`): walking owners in order, owner k maps to
record `k - shift(k)` where the shift is non-decreasing and grows by at most
1 per step (each phantom owner pushes later records back by one). A
per-component validator scores candidate assignments; ties prefer the higher
shift. Validators: for stats, `prof == 2 + (level - 1) // 4` against the
class level from `ClassesComponent`, plus range checks (abilities 1..40, the
zero field zero); for health, `max` must equal the class hit-die formula
(first-level die, then per-level die, plus CON modifier per level) computed
from `ClassesComponent` and the stats stream. Both validated 7/7 characters
against canonical statlines (including Minsc's WIS 6 and the tutorial
dragon's 27/10/25/16/13/21).

### Prepared spells (✅ decoded 2026-06)

`game.spell.v0.SpellBookPrepares` rows are 80 bytes: five `{begin, end}` u64
heap ranges. The fourth range is the PreparedSpells array of 24-byte
SpellMetaId records:

| Offset | Type | Field |
|-------:|------|-------|
| 0 | u64 | string pointer (+48 rule) into the spell-ID pool |
| 8 | u32 | string length |
| 12 | u32 | pad |
| 16 | u64 | detail pointer (+48) |

The detail record is `{u64 pointer into the game.spell.v0.ESourceType value
pool, 16-byte ProgressionSource GUID}`. Observed SpellSourceType values:
0/1/2 = class/subclass/race progression, 3 = item boost, 6 = base spell set,
7 = weapon attack.

The prepares ownerlist uses an *older entity numbering* than the
spell-book/classes ownerlists (entity rows shift as the world creates
entities; this component's list was not rewritten). Realignment: for each
prepares row whose spell names are a near-subset (≥85%) of exactly one spell
book, record the row delta; the majority delta across the save (minimum 3
votes and a 50% share) realigns every row. Assume the same stale-numbering
pattern is possible for any component whose ownerlist looks shifted.

### Camp supplies: a cached value (✅ decoded 2026-06)

`game.camp.v0.TotalSuppliesComponent` is a single u32 row holding the
camp-supply total shown next to the Long Rest button. It is a cache: the
engine zeroes it and only recomputes when the camp/rest system runs, so 0
means "not cached", not "no supplies". Treat 0 as absent. This is the
clearest proof that some blob components persist stale or invalidated data;
expect the same of other cached aggregates.

### Also in the blob

- Spell / ability IDs as a large pool of concatenated ASCII (e.g.
  `Projectile_EldritchBlast`, `Shout_SecondWind`). These are read exactly via
  the spell-book chain above.
- Earlier analysis suggested some unique items (Shifting Corpus Ring, Spidersilk
  Armour) had no LSF `Item` node; this was incorrect. Ground-truth verification
  shows both `MAG_FlamingFist_ScoutRing` (Shifting Corpus Ring) and
  `GOB_DrowCommander_Leather_Armor` (Wyll's chest piece, confirmed worn, probable
  Spidersilk Armour by context) have full frame-0 Item nodes with the equip bit
  set and are attributed correctly by the position-matching approach. The display
  name for `GOB_DrowCommander_Leather_Armor` is not in the root templates scanned,
  so it remains unresolved: the related template `GOB_DrowCommander_Armor_Leather`
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
| **Frame 6 MetaData** | ✅ `parse_metadata`: wall-clock save time, save number, campaign/session UUIDs, leader name, RNG seed, mod list |
| Per-character item ownership | ✅ (Translate matching; ECS container web decoded as cross-check) |
| Display names | ✅ (root templates + `.loca`; stats and spells resolve through `ParentTemplateId` / `using` inheritance chains) |
| **Spell lists** | ✅ exact per-character books (`SpellBookComponent → SpellData → SpellId → string pool`; characters matched by `ClassesComponent`) |
| **Worn-vs-carried** | ✅ union of `Flags` bit, STATUS signal, ECS membership count, and physical-attachment components (`WieldedComponent` / `GravityDisabledComponent`), with slot-conflict resolution |
| Exact equipment slot (Boots / Amulet / Cloak / …) | ✅ derived from item stats (`Slot` via `using` chain); no explicit `ItemSlot` field exists in the save (byte-sweep verified); Ring vs Ring2 recovered from `ContainerSlotData` row order (ground-truth verified) |
| LSMF component-type directory | ✅ decoded (≈350 entries: name → elem\_size / row\_count / data\_offset) |
| LSMF ownerlist region (equipped/carried signal) | ✅ decoded (membership count per entity; threshold 15) |
| LSMF heap arrays + string pool | ✅ decoded (`{begin,end}` ranges; pointers stored as absolute−48) |
| LSMF spell books / classes / templates / origins | ✅ decoded (see §6) |
| LSMF ability scores + hit points | ✅ decoded (packed streams with phantom-owner realignment; see §6) |
| LSMF prepared spells | ✅ decoded (`SpellBookPrepares`, stale-ownerlist realignment; see §6) |
| LSMF camp supplies | ✅ decoded (`TotalSuppliesComponent`, a cache; 0 = unknown) |
| Current quest objectives | ✅ decoded (LSF `Journal → QuestsProgress`, see §9) |
| LSMF inventory container web | ✅ decoded (`OwnerComponent`, `IsOwnedComponent`, `ContainerComponent`, `ContainerSlotData`) |
| LSMF `MemberComponent` / `MemberData` structure | ✅ traced (8-byte pointer + 16-byte {ptr\_a, EntityHandle}); historical-ownership bookkeeping, not live location |
| LSMF `EntityHandle` → GUID translation | ❌ no on-disk table; requires live game state |
| Osiris story (frame 9) | ✅ (`parse_osiris`): quest state, goal flags, story flags |

---

## 9. Osiris story state (frame 9)

Frame 9 is the Osiris scripting-engine save: ~47 MB flat binary (no offset
table). All sections must be read sequentially in fixed order. Verified against
`QuickSave_242`: parser consumed all 47,731,506 bytes with 0 remaining.

### File header (unscrambled, 193 bytes total)

| Field | Type | Notes |
|-------|------|-------|
| null byte | u8 | always `0x00` |
| version string | NUL-terminated | e.g. `"Story save game v1.15.0"` |
| major | u8 | `1` for Patch 8 |
| minor | u8 | `15` for Patch 8 (version word = `0x010f`) |
| bigendian | u8 | unused (`0`) |
| unused | u8 | |
| version buffer | 0x80 bytes | additional version data (ver ≥ 0x0102) |
| debug flags | u32 | (ver ≥ 0x0103) |

After the header, all strings are XOR-scrambled byte-by-byte with `0xAD`
(null-terminated). This applies to every `string()` read in the sections below.

Version-feature gates (version word thresholds):

| Constant | Value | Effect |
|----------|-------|--------|
| `OSI_VER_SCRAMBLE` | `0x0104` | enables 0xAD XOR string scrambling |
| `OSI_VER_ADD_QUERY` | `0x0106` | adds `is_query` bool at end of RuleNode |
| `OSI_VER_TYPE_ALIASES` | `0x0109` | adds type-alias byte per type entry |
| `OSI_VER_ENUMS` | `0x010d` | enables Enums section; type IDs are u16 (not u32) |
| `OSI_VER_VALUE_FLAGS` | `0x010e` | changes Value layout (index + flags byte first) |

### Section order and observed sizes (QuickSave_242)

| Section | Start offset | Notes |
|---------|-------------|-------|
| Types | 193 | `u32` count + `(name, idx_u8, alias_u8)` per entry |
| Enums | 780 | (ver ≥ `OSI_VER_ENUMS`) `u32` count + `(u16 id, u32 enum_count, (string, u64)…)` |
| DivObjects | 2799 | `u32` count + `(name, u8, u32, u32, u32, u32)` per entry |
| Functions | 2803 | `u32` count + complex signature per entry |
| Nodes | 1,562,961 | `u32` count + variable-length node records |
| Adapters | 20,335,037 | `u32` count + `(u32, Tuple, logical_map, physical_map)` |
| Databases | 27,143,800 | `u32` count + `(u32 idx, ParameterList, u32 fact_count, facts)` |
| Goals | 42,457,920 | `u32` count + goal records |
| GlobalActions | 47,731,502 | `u32` count + Call records |
| EOF | 47,731,506 | 0 bytes remaining |

### Value encoding (ver ≥ `OSI_VER_VALUE_FLAGS`)

Each Value starts with:
```
i8   index   (not semantically needed for database reading)
u8   flags   (bit 0x08 = IsValid; if not set, value is empty, no payload follows)
```
Then a discriminator byte:

| Byte | Meaning | Payload |
|------|---------|---------|
| `0x30` (`'0'`) | typed value | `type_id` + value per builtin type (see below) |
| `0x31` (`'1'`) | reference int | `type_id` (ignored) + `i32` |
| `0x65` (`'e'`) | enum label | `u16` enum type id + string |

Builtin type dispatch for `'0'` (type alias applied first):

| Alias | Builtin | Read |
|-------|---------|------|
| 0 | None | nothing |
| 1 | Integer | `i32` |
| 2 | Integer64 | `i64` |
| 3 | Real | `f32` |
| 4, 5 | String, GuidString | `u8` has_value + string if non-zero |
| other | (string-like) | same as 4/5 |

### Node types and parse layout

Nodes are consumed sequentially. Each starts with `u8 node_type, u32 node_id,
u32 db_ref, string name`. If `name` is non-empty, a `u8` param-count follows.
A `(db_ref, name)` pair with both non-zero is the database-name record.

| Type | ID | Extra payload |
|------|-----|---------------|
| DatabaseNode | 1 | `u32` referenced-by count + count × NodeEntryItem |
| ProcNode | 2 | same as DatabaseNode |
| DivQueryNode | 3 | nothing |
| AndNode | 4 | 1×NEI + 4×ref_u32 + ref_u32 + NEI + u8 + ref_u32 + NEI + u8 |
| NotAndNode | 5 | same as AndNode |
| RelOpNode | 6 | NEI + 2×ref_u32 + ref_u32 + NEI + u8 + i8 + i8 + Value + Value + i32 |
| RuleNode | 7 | NEI + 2×ref_u32 + ref_u32 + NEI + u8 + calls-list + vars-list + u32 + (bool if ver≥ADD_QUERY) |
| InternalQueryNode | 8 | nothing |
| UserQueryNode | 9 | nothing |

`NEI` = NodeEntryItem = `(ref_u32, u32, ref_u32)`.

### Key quest-state databases

| Database | Schema | Contents |
|----------|--------|---------|
| `DB_QuestIsAccepted` | `(quest_id: string)` | All quests ever accepted: superset of in-progress **and** closed quests |
| `DB_QuestIsClosed` | `(quest_id: string)` | All resolved quests (completed or failed; no separate failed-quest DB exists) |
| `DB_QuestIsOpened` | `(quest_id: string)` | Quests that appeared in the journal (a smaller tracking set) |
| `DB_GlobalFlag` | `(flag_guid: string)` | Story-state flags with GUID suffixes; 1034 facts in test save |

**Quest-state derivation:**
```
in_progress = DB_QuestIsAccepted − DB_QuestIsClosed
closed      = DB_QuestIsClosed
```
`DB_QuestIsAccepted` is **not** pruned when a quest closes, so the raw
accepted list contains both in-progress and resolved quests.

### Current quest objectives (LSF Journal, not Osiris)

The journal's "current step" for each quest does not live in Osiris at all.
It is stored directly in the Globals LSF (frame 0):
`Journal → Quests → … → QuestsProgress` nodes carry `MapKey` (the quest ID)
and `ObjectiveID`, gated by `QuestUnlocked && !QuestDisabled`. The objective
text comes from game data (`objective_prototypes.lsx`, paired with
`quest_prototypes.lsx` for quest titles); note that lsx attributes sort
alphabetically, so the `Description` handle precedes the `ObjectiveID` it
belongs to when walking attribute order.

### Goal flags

The `Flags` byte in each Goal record:

| Value | Meaning |
|-------|---------|
| `0x00` | active / default (652 goals in test save) |
| `0x02` | child goal (232 goals; per LSLib Goal.cs) |
| `0x07` | finalized (60 goals in test save) |

> **`0x07` does not mean "player finished this content."** In Osiris,
> orchestration goals (e.g. `Act2`, `Act2_CMB_StatusOnInit`,
> `BG3_CleanUpDBs_SavegamePatch`) call `GoalCompleted()` in their **init**
> block; they finalize immediately after spawning sub-goals. So `flags=0x07`
> means "this goal's lifetime has ended," which for act/system goals fires
> when the act is *entered*, not when the player finishes it. In `QuickSave_242`
> (mid-Act-2), `Act2` appears in the finalized set while Act-2 quests are still
> in `DB_QuestIsAccepted − DB_QuestIsClosed`. Treat this as "act/phase
> initiated" rather than "player completed."


---

## References

- LSLib: `LSLib/LS/Resources/LSF/LSFCommon.cs` (structs), `LSFReader.cs`
  (V2/V3 selection), `NodeAttribute.cs` (type enum), `LSPKReader` (package).
- LSLib Osiris: `LSLib/LS/Story/Story.cs` (section order), `Common.cs`
  (`OsiReader`, header, version constants), `Value.cs` (value encoding),
  `DataNode.cs`, `Rule.cs`, `RelOp.cs`, `Join.cs`, `Rel.cs`, `Adapter.cs`,
  `Database.cs`, `Goal.cs`, `Call.cs`, `Function.cs` (node/section layouts).
- bg3se: `BG3Extender/GameDefinitions/Components/Inventory.h`, `Stats.h`
  (component layouts), `Enumerations/Stats.inl` (`ItemSlot`).
