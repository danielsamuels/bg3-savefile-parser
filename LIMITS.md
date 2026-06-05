# What this parser can and cannot read

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
`MAG_Lesser_Infernal_Plate_Armor` → "Hellgloom Armour").

### How per-character ownership works

A carried or worn item's `Translate` (world transform) is copied from the
character holding it, so every item on a party member shares that member's
exact floating-point coordinates. Matching item `Translate` against character
`Translate` attributes each item to its owner **without decoding the ECS blob**.
The position-attribution itself is exact (an item is on a character or it
isn't). The *equipped-recall* against a known ground-truth loadout is high
(~31 of 35 worn items across a 4-member party) but several of those matches
rely on inferring a display name from an internal stats name (e.g.
`UND_SwordInStone` = Phalar Aluve, `MAG_StrongString_Longbow` = Titanstring);
a few of those inferences are uncertain, so treat the recall fraction as
approximate rather than a verified count.

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

Neither signal is reliable, and the LSF `Item` data has no field that
distinguishes worn from carried. Measured on the test save (Wyll), the
`Flags` value of his worn Evasive Shoes (`0x0000000c`) is **byte-identical**
to a carried Torch / Gold Pile / spare Leather Boots; three worn items
(Evasive Shoes, Pearl of Power, Hellgloom Armour) lack the `0x04000000` bit
entirely, while a *spare* (Drow Commander armour) carries it as a false
positive. So worn-vs-carried cannot be recovered from the data this parser
reads — only the heuristic "undetermined" bucket is honest about it.

### Exact equipment slot
Which slot an item occupies (Helmet / Breast / Cloak / MeleeMainHand /
Boots / Gloves / Amulet / Ring / …) lives in the ECS blob, in
`eoc::inventory::MemberComponent.EquipmentSlot` (`int16`), and is not
recovered. The slot indices follow bg3se's `ItemSlot` enum
(Helmet=0, Breast=1, Cloak=2, …, Boots=9, Gloves=10, Amulet=11, …).

### A few unique items have no `Item` record
Some uniques (e.g. Shifting Corpus Ring, Spidersilk Armour) have no `Item` node
in frame 0 or frame 3 at all — they exist only as entities inside the ECS blob,
so they cannot be named or attributed by this parser.

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

The worn set, exact slot, and the blob-only unique items all live here, in
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
