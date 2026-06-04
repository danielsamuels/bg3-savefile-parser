# What this parser can and cannot read

## What works

| Data | Source in save |
|------|----------------|
| Character name, race, class/subclass, level, XP | `Info.json` (frame 8 of the LSPK) |
| Passive-granting equipped items | `STATUS.SourceEquippedItem` in character nodes (frame 0) |
| Full party inventory list (internal names) | `Item` nodes with empty `Level` in level cache frames |

## What is missing

### Spell selections
Spell book data lives in the `NewAge` attribute (LSF attribute type 25 = `ScratchBuffer`).
This is an opaque LSMF-format ECS blob. lslib itself does not decode it; divine would
emit the same bytes base64-encoded. Parsing it would require reimplementing lslib's
full ECS component reader (thousands of lines + game-derived struct layouts from bg3se).

### Complete equipment slots
Only items that apply a `STATUS` node with `SourceEquippedItem` show up. Items that
are equipped but grant no passive (plain weapons, mundane armour, most trinkets) are
invisible to this parser. Full slot info (MainHand, OffHand, Armour, Boots, Gloves,
Helmet, Ring1, Ring2, Amulet, Cloak) is stored in the ECS blob alongside spell data.

### Per-character inventory ownership
The 1 100+ inventory items in the level-cache frame have no owner attribute in the
LSF node tree. Ownership is tracked inside the ECS blob. The parser lists all
unowned items as a single pool.

## The ECS blob (NewAge / LSMF)

The `NewAge` node in each level frame contains a single ScratchBuffer attribute
holding a multi-megabyte binary blob starting with the magic bytes `LSMF`.
This is a columnar component store: each component type (Character, Spells,
Equipment, Inventory, …) occupies a section, with entity indices into a UUID table.

BG3 Script Extender (bg3se) and lslib both read this format but the source is
complex. Contributions to decode it in Python are welcome.
