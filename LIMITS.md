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

### Equipped vs carried is heuristic
"Equipped" = items that grant a `STATUS` effect **or** carry the `0x04000000`
`Flags` bit (filtered to equipment-type stats names). Neither signal is complete:

- **False negatives:** a worn item that grants no passive *and* lacks the flag
  bit is listed as carried (observed: Wyll's Evasive Shoes and Pearl of Power).
- **False positives:** a *spare* weapon/armour the character carries but isn't
  wearing can be marked equipped (observed: Hellrider's Pride on Shadowheart).
  Worn-vs-spare is only distinguishable via the ECS equipment component.

### Exact equipment slot
Which slot an item occupies (MainHand / OffHand / Ring1 / Ring2 / Amulet /
Helmet / Boots / Gloves / Cloak / Armour / Ranged) lives in the ECS blob and
is not recovered.

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
GUIDs), resolved through separate handle↔GUID tables. Recovering exact equipment
slots and the worn-vs-spare distinction requires reimplementing the full ECS
component reader (bg3se-scale). Decoding it in Python is the remaining frontier;
contributions welcome.
