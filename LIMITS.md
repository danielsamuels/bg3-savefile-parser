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
items): all 34 worn items are attributed to the correct character; the
equipped/undetermined split catches 32/34 via the equip bit or STATUS signal,
with 2 worn items (Evasive Shoes and Pearl of Power Amulet) landing in the
"undetermined" bucket instead of "equipped".

## What is partial or missing

### Equipped vs carried is heuristic — and the save has no reliable worn flag
Items attributed to a character are split three ways:

- **Equipped** — a positive worn signal: the item grants a `STATUS` on-equip
  effect, **or** carries the `0x04000000` `Flags` bit (on an equipment-type
  stats name).
- **Carried** — not equipment at all (consumables, keys, gold, camp/cosmetic
  clothing): confidently *not* worn.
- **Worn or carried — undetermined** — equipment-type items with no worn
  signal. These are *not* guessed either way.

Validated against the QuickSave_242 ground truth (34 worn items across 4
characters):

- **Equip-bit recall: 32/34.** Two worn items lack the `0x04000000` bit:
  Evasive Shoes (`0x0000000c`) and Pearl of Power Amulet (`0x0000000c`),
  both on Wyll. Their `Flags` values are byte-identical to a carried Torch or
  Leather Boots.
- **One confirmed false positive.** `DEN_HellridersPride` (Hellrider's Pride)
  carries the equip bit but sits in Shadowheart's inventory, not in an
  equipment slot.
- **Negative signal.** Worn items **never** have the high flags bits
  (`Flags ≥ 0x80000000…`) set. Items with those bits are consumables, quest
  items, or unequipped spares. This is a useful filter but not sufficient on
  its own (some carried equipment-type items have only the baseline `0x0000000c`).
- The `STATUS.SourceEquippedItem` signal catches items that grant on-equip
  effects (passives, auras) and is complementary to the Flags bit — together
  they cover most of the worn set, but the 2 misses above (Evasive Shoes and
  Pearl of Power) are invisible to both.

So worn-vs-carried cannot be fully recovered from LSF data. The "undetermined"
bucket is honest about what remains ambiguous.

### Exact equipment slot
Which slot an item occupies (Helmet / Breast / Cloak / MeleeMainHand /
Boots / Gloves / Amulet / Ring / …) lives in the ECS blob, in
`eoc::inventory::MemberComponent.EquipmentSlot` (`int16`), and is not
recovered. The slot indices follow bg3se's `ItemSlot` enum
(Helmet=0, Breast=1, Cloak=2, …, Boots=9, Gloves=10, Amulet=11, …).

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

The worn set and exact slot live here, in
`eoc::inventory::MemberComponent` (`{ EntityHandle Inventory; int16 EquipmentSlot }`).
Decoding it would resolve every remaining limitation above.

**Why it's hard, and what the reference tools do and don't give us.** Two
upstream projects were consulted:

- **LSLib** (Norbyte) reads LSPK/LSF/LSV but treats this `ScratchBuffer` as an
  opaque `byte[]` — it has no LSMF/ECS decoder.
- **bg3se** (Norbyte's Script Extender) defines the component *layouts*
  (`MemberComponent`, `EquipableComponent`, the `ItemSlot` enum, etc.) but reads
  them from **live game memory**, not the on-disk save; the save's LSMF
  serialization is a separate, undocumented format.

So the component layouts are known, but the on-disk framing is not, and the
blob stores **no component-name or slot-name strings** to anchor a decode (the
type registry is hashed/indexed). Worse, component rows key on **EntityHandles**
with no handle→item/character table exposed, which is what earlier
co-occurrence / run-segmentation attempts foundered on.

One usable foothold exists: each party character's exact `Translate`
float-triple (the ownership key) **does** appear in the blob (5–8 hits each),
presumably via `MemberTransformComponent`, giving a known-value entry point to
walk entity framing from. A full Python decoder remains the open frontier.
