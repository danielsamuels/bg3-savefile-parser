# What this parser can and cannot read

> For the binary file formats themselves (LSPK, LSF, the `LSMF` ECS blob,
> `.loca`), see **[FORMAT.md](FORMAT.md)**.

## What works

| Data | Source in save |
|------|----------------|
| Character name, race, class/subclass, level, XP | `Info.json` (frame 8 of the LSPK) |
| **Per-character item ownership (equipped + carried)** | **`Item.Translate` matched to the character's `Translate`** (frames 0 + 3) |
| Equipped vs carried split | layered signals: `STATUS.SourceEquippedItem`, the equipped `Flags` bit `0x04000000`, ECS membership count, and physical-attachment components, with per-slot conflict resolution |
| Equipment slot per worn item | derived from game stat files (`Slot` via the `using` chain); the save does not serialise `ItemSlot`; the engine re-derives it the same way |
| **Exact per-character spell books** | LSMF `SpellBookComponent → SpellData → SpellId → string pool`, matched to party members by `ClassesComponent` (class/subclass/level) |
| Full level item pool (internal names) | `Item` nodes in frame 0 + level-cache frame |
| **Human-readable item names** | **resolved from the installed game data** (root-template `_merged.lsf` → `DisplayName` handle → `english.loca`, following `ParentTemplateId` inheritance) |

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

**Resolution is by Stats name, not GUID.** Every item in a live save (worn,
carried, and the whole level loot pool) uses a per-save *local* `CurrentTemplate`
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
`MAG_Lesser_Infernal_Plate_Armor` → "Hellgloom Armour", the ground truth for
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

## How the harder classifications work

### How equipped vs carried is determined
Items attributed to a character are classified in layers:

1. **Object-type filter.** Stats names whose game stat entry has
   `type "Object"` (books, containers, quest items) can never be equipped and
   are classified as carried regardless of any other signal.
2. **LSF signals.** An item is equipped if it grants an active on-equip
   `STATUS` (`SourceEquippedItem`) or carries the `0x04000000` `Flags` bit on
   an equipment-type stats name. Items that are not equipment at all
   (consumables, keys, gold, camp/cosmetic clothing) are carried.
3. **The equipment cluster.** A character's worn items occupy a
   near-contiguous block of `ContainerSlotData` rows in the save's ECS blob,
   while items moved to a bag get a row far outside it (see FORMAT.md §6).
   The block is anchored on the uncontested signalled items from layer 2;
   membership in it then dominates the remaining layers: a Flags item located
   outside the cluster has a stale equip bit and is demoted (an item keeps
   its Flags bit after being unequipped), and an item inside the cluster is
   worn even when every other signal misses it.
4. **ECS membership.** Equipment-type items with no LSF signal are resolved by
   ECS component membership count: equipped items are materialised in the ECS
   world with ~35–41 ownerlist memberships, while items dematerialised into a
   backpack drop to ~3–6, so a threshold of 15 separates them cleanly. The
   count is taken per physical instance (the save's parallel Creators/Items
   arrays map each item to its specific entity), so other level instances of
   the same item type cannot contaminate it. The cluster from layer 3 gates
   the result where available (the membership count alone cannot separate
   worn items from items lying loose in the main inventory); without one,
   items present in `game.inventory.v0.WieldedComponent` are *not* promoted,
   as that component retains a stale marker on previously-slotted items.
5. **Slot-conflict resolution.** After all passes, equipped candidates are
   grouped by equipment slot (the stat files' `Slot` field via the `using`
   chain). A slot holds one item; rings hold two, and the melee slot holds
   a dual-wield pair (two one-handed Flags items inside the cluster). When
   more items claim a slot than it can hold, Flags-signalled items beat
   ECS-only items, and Flags-vs-Flags ties are broken in priority order:
   active on-equip status, then cluster membership, then physical attachment
   (`WieldedComponent` / `GravityDisabledComponent`), then
   `OwnedAsLootComponent` membership, then higher membership count. A
   two-handed weapon in the main-hand slot also demotes any ECS-only offhand
   claim. Losers are reclassified as carried.

The underlying signals were established by controlled equip/unequip
experiments: a diff of the same save with Evasive Shoes worn (242) vs bagged
(243) found 35 components whose ownerlists contained only the equipped entity
(`game.inventory.v0.MemberComponent` among them); saves 242/248/249 confirmed
the same for the Pearl of Power Amulet. The full cascade is validated against
ground-truth party loadouts across the test saves (QuickSave_242 through
QuickSave_294): every confirmed misclassification found along the way (
Hellrider's Pride with a stale equip bit, previously-wielded weapons retaining
high membership counts, game-stat Object items carrying the Flags bit, a
dual-wield pair losing to a stale greatsword (292), Phalar Aluve's stale bit
beating the genuinely-wielded King's Knife and the Evasive Shoes vanishing
behind a stale `WieldedComponent` marker (294)) now classifies correctly,
and no known misclassifications remain. QuickSave_292 and 294 are bundled as
test fixtures under their quicksave index.

### Exact equipment slot: derived from stats; order persists in the container
The save stores no **explicit** `ItemSlot` value. Evidence: a byte-level sweep
over every LSMF component owned by 12 simultaneously-worn items with known
slots found no byte position matching the `ItemSlot` enum, and
`EquipmentVisualComponent` serialises as a null pointer. The slot *type* is
re-derived from item stats on load; the parser does the same (the stat files'
`Slot` field, following the `using` inheritance chain), and every equipped
item in the report is annotated `[Slot]`.

Assignments the stats cannot express (which of two rings sits in Ring vs
Ring2, which of two dual-wielded weapons is in the main hand) survive
save/load via the **ordering** preserved in `ContainerSlotData`: the item
with the earlier row sits in the first slot. Ground-truth verified in-game
for rings (QuickSave_291) and dual-wielded weapons (QuickSave_292); the
report labels `[Ring]` / `[Ring 2]` and `[Melee Main Weapon]` /
`[Melee Offhand Weapon]` accordingly.

### Spell books: exact (decoded 2026-06)
Spell data lives in the `NewAge` LSMF ECS blob and is now decoded exactly:
`game.spell.v3.SpellBookComponent` rows are `{begin, end}` slices into
`game.spell.v3.SpellData`, whose rows point at `game.spell.v0.SpellId`
entries carrying `{pointer, length}` references into the blob's spell-ID
string pool (see FORMAT.md §6). Party members are matched to their spell-book
entity by class/subclass/level from `game.stats.v0.ClassesComponent`. The
resulting lists are complete and current: class abilities, racial and
illithid powers, item-granted spells, and mod-added spells all attribute to
the right character. Since 2026-06 attribution is exact for the player and
all origin companions via the template link (the stats entity is allocated
immediately after the character's world entity; see FORMAT.md §6), so even
identical builds resolve. Class-build matching remains only as the fallback
for custom hirelings, where identical builds still cannot be told apart.
(An earlier string-pool + class-rule heuristic was retired once the exact
chain proved reliable across saves.)

## Known limitations

- Shared stats names (~9% of stats names) resolve to the first/base
  display-name variant rather than the exact variant; see "How display names
  work" above.
- Identical hireling builds. The player and origin companions attribute
  exactly via the template link, but custom hirelings fall back to class
  matching; two hirelings with the same class, subclass, *and* level cannot
  be told apart, and the report says so explicitly instead of guessing.

## The ECS blob (NewAge / LSMF)

The `NewAge` node in each level frame contains a single ScratchBuffer attribute
holding a multi-megabyte binary blob starting with the magic bytes `LSMF`.
It is a columnar ECS component store: component sections are arrays ordered by
entity handle, with entity cross-references stored as handles (not the 16-byte
GUIDs), resolved through separate handle↔GUID tables.

### What is decoded

The parser reads the following from the ECS blob:

- Component descriptor table: 355 component types, each with name, element
  size, row count, and data offset (see FORMAT.md §6).
- Ownerlist region: each component that has one stores a 32-byte
  `{start, end, comp, entity_count}` record (all `uint64`); `start`..`end` is a
  packed `uint32[]` of entity-row indices. Scanning all ownerlists and counting
  per-entity memberships gives the equipped/carried signal: equipped items have
  ~35–41 memberships; items dematerialised into a backpack have ~3–6. A
  controlled diff (saves 242/243) confirmed `game.inventory.v0.MemberComponent`
  is one of 35 components present only for equipped entities.
- Entity GUID bridge: `core.v0.EntityId` stores 16-byte GUIDs at a known
  offset, indexed by entity row. Reversed `e2t_items` (from LSF Creators nodes)
  maps template GUID → instance GUID, linking the LSF item tree to the ECS rows.
  Spell strings are also read directly from the blob's printable-ASCII runs.

### Also decoded from the blob (see FORMAT.md §6 for structures)

- Spell books, classes, templates, origins: exact per-character spell
  lists; class/subclass/level per entity; template GUIDs as pool strings;
  origin UUIDs.
- The inventory container web: `OwnerComponent` (primary inventory per
  character), `IsOwnedComponent`, `ContainerComponent`, `ContainerSlotData`
  (slot-within-container + generation). Used as documentation and
  cross-checks; per-character ownership in the report still comes from the
  simpler and equally exact `Translate` matching.

### What is not decoded

- `ItemSlot` per worn item: not present in the save (byte-sweep verified);
  derived from item stats instead, exactly as the engine does on load.
- Live `EntityHandle` values (`MemberData.handle_b` and friends): indices
  into the running game's global entity pool with no on-disk translation
  table; anything gated exclusively behind one is unreachable from the save.
- The "new item" inventory indicator: not serialised at all. A controlled
  experiment (QuickSave_296–301: hover-clearing items, saving, reloading)
  showed every item reverts to "new" on load; the seen-state is session-only
  UI memory, so the whole inventory starts unseen each session and no
  corresponding state exists in the save to decode.

## Development

Run all checks with:

```sh
# Lint
uvx ruff check bg3parser/ explore_lsmf.py tests/

# Format
uvx ruff format bg3parser/ explore_lsmf.py tests/

# Type check
uv run ty check bg3parser

# Tests (fixture saves live in tests/fixtures/)
uv run pytest
```

Test saves are bundled under `tests/fixtures/`; tests that exercise an
installed game's data (display names, slots) adapt automatically when no
install is found (`BG3_DATA_DIR` unset and auto-detection failing).
