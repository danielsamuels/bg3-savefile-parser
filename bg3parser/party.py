"""Party characters and per-character item classification."""


# ---------------------------------------------------------------------------
# Character extraction from Globals (frame 0)
# ---------------------------------------------------------------------------

PLAYER_CHAR_TEMPLATE = 'f08563b3-748d-4783-837b-b8620bc60b22'

# The Dark Urge origin's shipped template; a Durge avatar is the player too.
DARK_URGE_TEMPLATE = '1f69a29f-8284-4d1d-a0e6-fba9fb02ac56'

PLAYER_CHAR_TEMPLATES = frozenset((PLAYER_CHAR_TEMPLATE, DARK_URGE_TEMPLATE))

# Info.json Origin values that mean "this is the player avatar".
PLAYER_ORIGINS = frozenset(('Generic', 'DarkUrge'))


PARTY_ORIGINS = {
    'c7c13742-bacd-460a-8f65-f864fe41f255': 'Astarion',
    'ad9af97d-75da-406a-ae13-7071c563f604': 'Gale',
    '7628bc0e-52b8-42a7-856a-13a6fd413323': 'Halsin',
    '91b6b200-7d00-4d62-8dc9-99e8339dfa1a': 'Jaheira',
    '2c76687d-93a2-477b-8b18-8a14b549304c': 'Karlach',
    '58a69333-40bf-8358-1d17-fff240d7fb12': "Lae'zel",
    '25721313-0c15-4935-8176-9f134385451b': 'Minthara',
    '0de603c5-42e2-4811-9dad-f652de080eba': 'Minsc',
    '3ed74f06-3c60-42dc-83f6-f034cb47c679': 'Shadowheart',
    'c774d764-4a17-48dc-b470-32ace9ce447d': 'Wyll',
}


NULL_UUID = '00000000-0000-0000-0000-000000000000'


# The camp chest ("Traveller's Chest") root templates, one per act/variant —
# static shipped GUIDs, so the chest is findable without a game install.
CAMP_CHEST_TEMPLATES = frozenset(
    (
        '65ad4dbc-74b2-47b6-bad4-1a109cfc9639',
        '96eab9d1-74b1-42f7-b1ad-061a9fcea8c4',
        '9b293d36-29f0-460c-bc81-2bdd4610a478',
        'b1487efd-4ae8-4747-866d-717df74169cd',
        'b5de2260-8e6b-4c2f-91eb-6f3133682a2f',
        'f68b5862-887c-4adf-b9f8-bb29e4d73b0f',
    )
)

# Characters within this distance of the camp chest count as "at camp".
# Observed campsite spread is ~60 units; the nearest non-camp NPC cluster
# in the fixtures is >900 units away.
CAMP_RADIUS = 100.0

# Origin companions' fixed race and base class (not serialised in the save;
# these are static game facts, used for companions outside the active party).
ORIGIN_INFO = {
    'Astarion': ('Elf_HighElf', 'Rogue'),
    'Gale': ('Human', 'Wizard'),
    'Halsin': ('Elf_WoodElf', 'Druid'),
    'Jaheira': ('HalfElf_High', 'Druid'),
    'Karlach': ('Tiefling_Zariel', 'Barbarian'),
    "Lae'zel": ('Githyanki', 'Fighter'),
    'Minsc': ('Human', 'Ranger'),
    'Minthara': ('Drow_LolthSworn', 'Paladin'),
    'Shadowheart': ('HalfElf_High', 'Cleric'),
    'Wyll': ('Human', 'Warlock'),
}


def find_camp_chest(nodes: list[dict]) -> tuple | None:
    """Return the camp chest's exact Translate tuple, or None.

    The chest sits at (0,0,0) before the first camp is established; that
    position is returned as-is (callers treat it as 'no usable camp').
    """
    for nd in nodes:
        if nd['name'] == 'Item' and nd['attrs'].get('CurrentTemplate', '') in CAMP_CHEST_TEMPLATES:
            t = nd['attrs'].get('Translate')
            if isinstance(t, tuple):
                return t
    return None


def camp_distance(a: tuple, b: tuple) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b, strict=False)) ** 0.5


def parse_journal_objectives(nodes: list[dict]) -> dict[str, str]:
    """quest_id -> current ObjectiveID, from the Journal's QuestsProgress map.

    Covers unlocked, not-yet-disabled journal quests (the active set); the
    save stores the current objective directly, no inference needed.
    """
    ji = next(
        (i for i, nd in enumerate(nodes) if nd['name'] == 'Journal' and nd['parent'] == -1),
        None,
    )
    if ji is None:
        return {}
    out: dict[str, str] = {}

    def walk(i: int) -> None:
        nd = nodes[i]
        if nd['name'] == 'QuestsProgress':
            qid = nd['attrs'].get('MapKey', '')
            for mi in nd['children']:
                for qi in nodes[mi]['children']:
                    q = nodes[qi]
                    if (
                        q['name'] == 'Quest'
                        and q['attrs'].get('QuestUnlocked')
                        and not q['attrs'].get('QuestDisabled')
                    ):
                        obj = q['attrs'].get('ObjectiveID', '')
                        if qid and obj:
                            out[qid] = obj
            return
        for c in nd['children']:
            walk(c)

    for c in nodes[ji]['children']:
        if nodes[c]['name'] == 'Quests':
            walk(c)
    return out


def find_party_character_nodes(nodes: list[dict], player_name: str = 'Player') -> dict[str, int]:
    chars_root = next(
        (i for i, nd in enumerate(nodes) if nd['name'] == 'Characters' and nd['parent'] == -1),
        None,
    )
    if chars_root is None:
        return {}

    found = {}

    def walk(ni: int):
        nd = nodes[ni]
        tmpl = nd['attrs'].get('CurrentTemplate', '')
        if tmpl in PLAYER_CHAR_TEMPLATES:
            found[player_name] = ni
        elif tmpl in PARTY_ORIGINS:
            found[PARTY_ORIGINS[tmpl]] = ni
        for ci in nd['children']:
            walk(ci)

    for ci in nodes[chars_root]['children']:
        walk(ci)
    return found


def collect_status_equipped_items(nodes: list[dict], char_ni: int) -> list[dict]:
    result = []

    def walk(ni: int):
        nd = nodes[ni]
        if nd['name'] == 'STATUS':
            src = nd['attrs'].get('SourceEquippedItem', '')
            if src and src != NULL_UUID:
                result.append({'entity': src, 'status_id': nd['attrs'].get('ID', '')})
        for ci in nd['children']:
            walk(ci)

    for ci in nodes[char_ni]['children']:
        walk(ci)
    return result


def build_entity_template_map(nodes: list[dict], root_name: str) -> dict[str, str]:
    factory_root = next(
        (i for i, nd in enumerate(nodes) if nd['name'] == root_name and nd['parent'] == -1),
        None,
    )
    if factory_root is None:
        return {}

    result = {}
    for child_ni in nodes[factory_root]['children']:
        creators_ni = next(
            (ci for ci in nodes[child_ni]['children'] if nodes[ci]['name'] == 'Creators'),
            None,
        )
        if creators_ni is None:
            continue
        for ci in nodes[creators_ni]['children']:
            ch = nodes[ci]
            entity = ch['attrs'].get('Entity', '')
            template = ch['attrs'].get('TemplateID', '')
            if entity:
                result[entity] = template
    return result


def build_instance_entity_map(nodes: list[dict]) -> dict[tuple, str]:
    """Return {(translate, stats): entity_guid} from parallel Creators/Items arrays."""
    items_root = next(
        (i for i, nd in enumerate(nodes) if nd['name'] == 'Items' and nd['parent'] == -1), None
    )
    if items_root is None:
        return {}
    factory_ni = nodes[items_root]['children'][0] if nodes[items_root]['children'] else None
    if factory_ni is None:
        return {}
    factory_children = nodes[factory_ni]['children']
    creators_ni = next((ci for ci in factory_children if nodes[ci]['name'] == 'Creators'), None)
    items_ni = next((ci for ci in factory_children if nodes[ci]['name'] == 'Items'), None)
    if creators_ni is None or items_ni is None:
        return {}
    return {key: ents[0] for key, ents in build_instance_entity_lists(nodes).items()}


def build_instance_entity_lists(nodes: list[dict]) -> dict[tuple, tuple[str, ...]]:
    """Return {(translate, stats): (entity_guid, …)} from parallel Creators/Items arrays.

    Several physical copies of the same item type on the same character share
    the (translate, stats) key but are distinct entities; the list keeps one
    GUID per copy, in array order.
    """
    items_root = next(
        (i for i, nd in enumerate(nodes) if nd['name'] == 'Items' and nd['parent'] == -1), None
    )
    if items_root is None:
        return {}
    factory_ni = nodes[items_root]['children'][0] if nodes[items_root]['children'] else None
    if factory_ni is None:
        return {}
    factory_children = nodes[factory_ni]['children']
    creators_ni = next((ci for ci in factory_children if nodes[ci]['name'] == 'Creators'), None)
    items_ni = next((ci for ci in factory_children if nodes[ci]['name'] == 'Items'), None)
    if creators_ni is None or items_ni is None:
        return {}
    result: dict[tuple, list[str]] = {}
    # The format keeps Creators and Items parallel; tolerate a corrupt tail.
    for creator_ci, item_ci in zip(
        nodes[creators_ni]['children'],
        nodes[items_ni]['children'],
        strict=False,
    ):
        entity = nodes[creator_ci]['attrs'].get('Entity', '')
        translate = nodes[item_ci]['attrs'].get('Translate')
        stats = nodes[item_ci]['attrs'].get('Stats', '')
        if entity and translate and stats:
            result.setdefault((translate, stats), []).append(entity)
    return {key: tuple(ents) for key, ents in result.items()}


def build_template_stats_map(nodes: list[dict]) -> dict[str, str]:
    items_root = next(
        (i for i, nd in enumerate(nodes) if nd['name'] == 'Items' and nd['parent'] == -1),
        None,
    )
    if items_root is None:
        return {}

    result = {}
    factory_ni = nodes[items_root]['children'][0] if nodes[items_root]['children'] else None
    if factory_ni is None:
        return result

    items_ni = next(
        (ci for ci in nodes[factory_ni]['children'] if nodes[ci]['name'] == 'Items'),
        None,
    )

    candidates: list[int] = []
    if items_ni is not None:
        candidates = nodes[items_ni]['children']
    else:
        for child_ni in nodes[factory_ni]['children']:
            for ci in nodes[child_ni]['children']:
                if nodes[ci]['name'] in ('Item', 'GameObjects'):
                    candidates.append(ci)

    for ci in candidates:
        item = nodes[ci]
        tmpl = item['attrs'].get('CurrentTemplate', '')
        stats = item['attrs'].get('Stats', '')
        if tmpl and stats:
            result[tmpl] = stats
    return result


def collect_inventory_items(nodes: list[dict]) -> list[dict]:
    items_root = next(
        (i for i, nd in enumerate(nodes) if nd['name'] == 'Items' and nd['parent'] == -1),
        None,
    )
    if items_root is None:
        return []

    factory_ni = nodes[items_root]['children'][0] if nodes[items_root]['children'] else None
    if factory_ni is None:
        return []

    items_ni = next(
        (ci for ci in nodes[factory_ni]['children'] if nodes[ci]['name'] == 'Items'),
        None,
    )
    if items_ni is None:
        return []

    result = []
    for ci in nodes[items_ni]['children']:
        item = nodes[ci]
        level = item['attrs'].get('Level', 'X')
        if level == '':
            result.append(
                {
                    'stats': item['attrs'].get('Stats', ''),
                    'template': item['attrs'].get('CurrentTemplate', ''),
                    'flags': item['attrs'].get('Flags', 0),
                    'prev_level': item['attrs'].get('PreviousLevel', ''),
                }
            )
    return result


# ---------------------------------------------------------------------------
# Per-character item attribution (position-based ownership)
# ---------------------------------------------------------------------------
#
# A carried/equipped item's `Translate` (world transform) is copied from the
# character carrying it, so every item on a party member shares that member's
# exact float coordinates.  Matching item Translate against character Translate
# attributes each item to its owner — without decoding the ECS blob.
#
# Whether an attributed item is *worn* vs merely *carried* is then decided by a
# union of two signals (neither complete on its own):
#   1. STATUS.SourceEquippedItem  — catches items that grant a passive/effect
#                                    (spell slots, auras) but is silent for
#                                    plain gear and for chars with few statuses.
#   2. Flags bit 0x04000000       — set on most worn equipment, but missing on
#                                    some worn items and present on a few held
#                                    consumables (filtered out by item type).
# Residual: a carried *spare* weapon/armour the character isn't wearing can
# still be flagged equipped; the worn-vs-spare distinction lives in the ECS
# equipment component (see LIMITS.md).

EQUIPPED_FLAG_BIT = 0x04000000


# Item stats-name prefixes / substrings that are never worn equipment.
NON_EQUIP_PREFIXES = (
    'OBJ_',
    'CONS_',
    'ALCH_',
    'FOOD_',
    'SCR_',
    'SCROLL_',
    'BOOK_',
    'LOOT_',
    'KEY_',
    'PUZ_',
    'PLT_',
    'TItem_',
    'GOLD_',
)


NON_EQUIP_SUBSTR = (
    '_Camp_',
    'Underwear',
    'Keychain',
    'GoldPile',
    'Backpack',
    'AlchemyPouch',
    'CampSupplies',
)


def is_equipment_type(stats: str) -> bool:
    """True if a stats name could plausibly be worn equipment."""
    if not stats:
        return False
    if stats.startswith(NON_EQUIP_PREFIXES):
        return False
    return not any(sub in stats for sub in NON_EQUIP_SUBSTR)


def collect_character_positions(
    nodes0: list[dict], party_nodes: dict[str, int]
) -> dict[str, tuple]:
    """display_name -> exact Translate tuple of that character."""
    out = {}
    for name, ni in party_nodes.items():
        t = nodes0[ni]['attrs'].get('Translate')
        if isinstance(t, tuple):
            out[name] = t
    return out


def collect_items_by_position(
    node_lists: list[list[dict]], positions: dict[str, tuple]
) -> dict[str, list[tuple]]:
    """Group Item records by which character's exact Translate they share.

    Returns {display_name: [(stats, flags), ...]} deduped per character.
    node_lists may contain several parsed frames (frame 0 + frame 3); records
    are merged so an item present in either frame is attributed.
    """
    pos2name = {t: n for n, t in positions.items()}
    # name -> {stats: (flags, guid)}; if an item appears more than once, keep the
    # record whose Flags carry the equipped bit so a clear-flagged duplicate
    # can't hide it.  The CurrentTemplate GUID is retained for display-name
    # resolution.
    acc: dict[str, dict[str, tuple]] = {n: {} for n in positions}
    for nodes in node_lists:
        for nd in nodes:
            if nd['name'] != 'Item':
                continue
            t = nd['attrs'].get('Translate')
            name = pos2name.get(t)
            if name is None:
                continue
            stats = nd['attrs'].get('Stats', '')
            if not stats:
                continue
            flags = nd['attrs'].get('Flags', 0)
            guid = nd['attrs'].get('CurrentTemplate', '')
            prev = acc[name].get(stats)
            if prev is None or (
                isinstance(flags, int)
                and (flags & EQUIPPED_FLAG_BIT)
                and not (isinstance(prev[0], int) and (prev[0] & EQUIPPED_FLAG_BIT))
            ):
                acc[name][stats] = (flags, guid)
    return {n: [(s, f, g) for s, (f, g) in d.items()] for n, d in acc.items()}


def split_equipped_carried(
    items: list[tuple],
    status_equipped: set[str],
    object_type_stats: frozenset[str] | None = None,
) -> tuple[list[tuple], list[tuple], list[tuple]]:
    """Classify attributed items into (equipped, carried, undetermined) using LSF signals.

      equipped     – STATUS on-equip effect, or 0x04000000 Flags bit on an
                     equipment-type item.
      carried      – not equipment at all (consumables, keys, gold, camp/
                     cosmetic clothing), or Object-type items (books, containers,
                     quest items) that cannot be equipped.
      undetermined – equipment-type items with no LSF worn signal; a second
                     pass via ecs_resolve_equipped resolves these using ECS
                     component membership counts.

    Each returned entry is a (stats, guid) pair.
    """
    equipped, carried, undetermined = [], [], []
    for stats, flags, guid in items:
        if object_type_stats and stats in object_type_stats:
            carried.append((stats, guid))
            continue
        signalled = stats in status_equipped or (
            isinstance(flags, int) and (flags & EQUIPPED_FLAG_BIT) and is_equipment_type(stats)
        )
        if signalled:
            equipped.append((stats, guid))
        elif is_equipment_type(stats):
            undetermined.append((stats, guid))
        else:
            carried.append((stats, guid))
    return sorted(set(equipped)), sorted(set(carried)), sorted(set(undetermined))


def invert_entity_template_map(
    entity_to_template: dict[str, str],
) -> dict[str, list[str]]:
    """Reverse entity_guid→template_guid to template_guid→[entity_guids]."""
    result: dict[str, list[str]] = {}
    for entity_guid, tmpl_guid in entity_to_template.items():
        result.setdefault(tmpl_guid, []).append(entity_guid)
    return result


def equipment_cluster(
    anchor_rows: list[int], *, margin: int = 8, trim: int = 24
) -> tuple[int, int] | None:
    """Estimate the ContainerSlotData row range holding a character's worn items.

    A character's worn items occupy a near-contiguous block of
    ContainerSlotData rows (their slots in the character's own containers),
    while an item moved to a bag gets a fresh row far outside that block —
    ground-truthed across QuickSave_286–294 for four party members. Anchors
    are the rows of items whose worn status is already near-certain from LSF
    signals. An anchor further than `trim` rows from the anchor median is a
    stale outlier (an unequipped item keeps its Flags bit and its old row)
    and is dropped; the surviving span widened by `margin` is the cluster.

    Returns None with fewer than two surviving anchors — not enough evidence
    to reclassify anything.
    """
    if len(anchor_rows) < 2:
        return None
    med = sorted(anchor_rows)[len(anchor_rows) // 2]
    kept = [r for r in anchor_rows if abs(r - med) <= trim]
    if len(kept) < 2:
        return None
    return (min(kept) - margin, max(kept) + margin)


# Slots whose items stay in the backpack grid while equipped — the slot is
# virtual, so the item's ContainerSlotData row says nothing about worn status
# (Maia's lute sat mid-backpack while genuinely equipped, QuickSave_294).
CLUSTER_EXEMPT_SLOTS = frozenset(('MusicalInstrument',))


def cluster_anchor_rows(
    flags_equipped: list[tuple],
    stats_to_slot: dict[str, str],
    stats_to_entity: dict[str, str],
    guid_to_rows: dict[str, list[int]],
    all_csd: dict[int, tuple[int, ...]],
) -> list[int]:
    """ContainerSlotData rows of items anchoring the equipment cluster.

    An anchor is an LSF-signalled equipment item that is its slot's sole
    claimant (two for rings), so its worn status needs no tiebreaking. Items
    with several ContainerSlotData entries contribute the entry nearest the
    median of the unambiguous (single-entry) anchors.
    """
    slot_counts: dict[str, int] = {}
    for stats, _guid in flags_equipped:
        slot = stats_to_slot.get(stats)
        if slot:
            slot_counts[slot] = slot_counts.get(slot, 0) + 1

    row_sets: list[tuple[int, ...]] = []
    for stats, _guid in flags_equipped:
        slot = stats_to_slot.get(stats)
        if (
            not slot
            or slot in CLUSTER_EXEMPT_SLOTS
            or slot_counts[slot] > SLOT_CAPACITY.get(slot, 1)
        ):
            continue
        eg = stats_to_entity.get(stats, '')
        rows = sorted({r for er in guid_to_rows.get(eg, []) for r in all_csd.get(er, ())})
        if rows:
            row_sets.append(tuple(rows))
    if not row_sets:
        return []
    singles = sorted(rs[0] for rs in row_sets if len(rs) == 1)
    med = singles[len(singles) // 2] if singles else row_sets[0][0]
    return [min(rs, key=lambda r: abs(r - med)) for rs in row_sets]


def csd_cluster_membership(
    stats: str,
    cluster: tuple[int, int],
    stats_to_entity: dict[str, str],
    guid_to_rows: dict[str, list[int]],
    all_csd: dict[int, tuple[int, ...]],
) -> bool | None:
    """Whether an item has a ContainerSlotData entry inside the cluster.

    Returns None when the item has no ContainerSlotData entries at all
    (no location evidence either way).
    """
    eg = stats_to_entity.get(stats, '')
    rows = [r for er in guid_to_rows.get(eg, []) for r in all_csd.get(er, ())]
    if not rows:
        return None
    lo, hi = cluster
    return any(lo <= r <= hi for r in rows)


def ecs_resolve_equipped(
    undetermined: list[tuple],
    template_to_instances: dict[str, list[str]],
    guid_to_rows: dict[str, list[int]],
    membership_count: dict[int, int],
    *,
    threshold: int = 15,
    stats_to_entity: dict[str, str] | None = None,
    wielded_rows: frozenset[int] | None = None,
    csd_cluster: tuple[int, int] | None = None,
    all_csd: dict[int, tuple[int, ...]] | None = None,
) -> tuple[list[tuple], list[tuple], list[tuple]]:
    """Classify undetermined items via ECS component membership counts.

    Equipped items (materialised in the ECS world) have ~35–41 component
    memberships; items moved to a backpack dematerialise to ~3–6.
    A threshold of 15 sits cleanly between the two groups — but it cannot
    separate worn items from items lying loose in the main inventory, which
    stay materialised too.

    When stats_to_entity is provided, the per-instance entity GUID is used
    directly instead of looking up all level instances of the template, which
    prevents MC contamination from unrelated instances of the same item type.

    When csd_cluster (with all_csd) is available, an item's own
    ContainerSlotData row decides: inside the character's equipment cluster →
    equipped, outside → carried (see equipment_cluster). This also overrides
    the WieldedComponent gate below, whose stale marker otherwise blocks
    genuinely worn items (Evasive Shoes, QuickSave_294).

    Without a cluster, items whose entity row is in
    game.inventory.v0.WieldedComponent are classified as carried rather than
    equipped: the WieldedComponent retains a stale marker for items that were
    previously in a weapon/equipment slot but have since been moved to the main
    inventory, so high MC alone is not sufficient for promotion.

    Items whose template GUID has no ECS entity at all are left undetermined
    rather than silently classified as carried.

    Returns (now_equipped, now_carried, still_undetermined).
    """
    now_equipped: list[tuple] = []
    now_carried: list[tuple] = []
    still_undetermined: list[tuple] = []
    for stats, tmpl_guid in undetermined:
        if stats_to_entity and stats in stats_to_entity:
            entity_guid = stats_to_entity[stats]
            rows = guid_to_rows.get(entity_guid, [])
        else:
            rows = [
                row
                for ig in template_to_instances.get(tmpl_guid, [])
                for row in guid_to_rows.get(ig, [])
            ]
        if not rows:
            still_undetermined.append((stats, tmpl_guid))
            continue
        max_mc = max(membership_count.get(row, 0) for row in rows)
        in_cluster: bool | None = None
        if csd_cluster is not None and all_csd is not None:
            csd_rows = [r for er in rows for r in all_csd.get(er, ())]
            if csd_rows:
                lo, hi = csd_cluster
                in_cluster = any(lo <= r <= hi for r in csd_rows)
        if in_cluster is not None:
            worn = in_cluster and max_mc >= threshold
        else:
            in_wielded = wielded_rows is not None and any(r in wielded_rows for r in rows)
            worn = max_mc >= threshold and not in_wielded
        if worn:
            now_equipped.append((stats, tmpl_guid))
        else:
            now_carried.append((stats, tmpl_guid))
    return now_equipped, now_carried, still_undetermined


SLOT_CAPACITY: dict[str, int] = {'Ring': 2}


# Report display order for equipped items, mirroring the in-game panel
# (armour top-to-bottom, then weapons, then instrument/vanity).
SLOT_DISPLAY_ORDER: dict[str, int] = {
    name: i
    for i, name in enumerate(
        (
            'Helmet',
            'Cloak',
            'Breast',
            'Gloves',
            'Boots',
            'Amulet',
            'Ring',
            'Melee Main Weapon',
            'Melee Offhand Weapon',
            'Ranged Main Weapon',
            'Ranged Offhand Weapon',
            'MusicalInstrument',
            'Underwear',
            'VanityBody',
            'VanityBoots',
        )
    )
}


def resolve_slot_conflicts(
    flags_equipped: list[tuple],
    ecs_equipped: list[tuple],
    stats_to_slot: dict[str, str],
    stats_to_entity: dict[str, str],
    guid_to_rows: dict[str, list[int]],
    membership_count: dict[int, int],
    owned_as_loot_rows: frozenset[int] | None = None,
    two_handed_stats: frozenset[str] | None = None,
    status_equipped: frozenset[str] | None = None,
    wielded_rows: frozenset[int] | None = None,
    gravity_disabled_rows: frozenset[int] | None = None,
    csd_cluster: tuple[int, int] | None = None,
    all_csd: dict[int, tuple[int, ...]] | None = None,
) -> tuple[list[tuple], list[tuple], list[tuple]]:
    """Resolve cases where more items are signalled for a slot than it can hold.

    When the character's equipment cluster is known (csd_cluster + all_csd,
    see equipment_cluster), an item's own ContainerSlotData row is decisive:
    a Flags-signalled item located outside the cluster has a stale equip bit
    and is demoted outright (unless an active on-equip status proves it worn),
    and two one-handed Flags items both inside the cluster are a dual-wield
    pair — "Melee Main Weapon" holds them both.

    Beyond that, Flags-signalled items beat ECS-only items for the same slot.
    When multiple Flags items compete for the same slot, tiebreaker priority is:
      1. active on-equip status (status_equipped) — truly wielded item
      2. a ContainerSlotData entry inside the equipment cluster
      3. WieldedComponent or GravityDisabledComponent — physically attached
         to the character (in a weapon slot / worn-visual physics override)
      4. OwnedAsLootComponent — direction is save-dependent, but when neither
         item has a physical-attachment signal the in-loot item is the worn one
      5. per-instance membership count (higher MC wins)
    Ring slot has capacity 2; all others capacity 1.

    If a 2-handed weapon is flags-equipped in "Melee Main Weapon", all
    ECS-only items in "Melee Offhand Weapon" are demoted (can't dual-wield).

    Returns (kept_flags_equipped, kept_ecs_equipped, demoted_to_carried).
    """

    def get_mc(stats: str) -> int:
        eg = stats_to_entity.get(stats, '')
        if not eg:
            return 0
        return max((membership_count.get(r, 0) for r in guid_to_rows.get(eg, [])), default=0)

    def in_rows(stats: str, rows: frozenset[int] | None) -> bool:
        if not rows:
            return False
        eg = stats_to_entity.get(stats, '')
        if not eg:
            return False
        return any(r in rows for r in guid_to_rows.get(eg, []))

    def in_cluster(stats: str) -> bool | None:
        if csd_cluster is None or all_csd is None:
            return None
        return csd_cluster_membership(stats, csd_cluster, stats_to_entity, guid_to_rows, all_csd)

    slot_candidates: dict[str, list[tuple]] = {}
    no_slot_flags: list[tuple] = []
    no_slot_ecs: list[tuple] = []
    demoted: list[tuple] = []

    for stats, guid in flags_equipped:
        # A Flags item whose ContainerSlotData entry lies outside the
        # character's equipment cluster sits in a bag: the equip bit is stale.
        # Virtual slots are exempt — their items stay in the grid while worn.
        if (
            in_cluster(stats) is False
            and stats_to_slot.get(stats) not in CLUSTER_EXEMPT_SLOTS
            and not (status_equipped and stats in status_equipped)
        ):
            demoted.append((stats, guid))
            continue
        slot = stats_to_slot.get(stats)
        if slot:
            slot_candidates.setdefault(slot, []).append((stats, guid, 'flags'))
        else:
            no_slot_flags.append((stats, guid))
    for stats, guid in ecs_equipped:
        slot = stats_to_slot.get(stats)
        if slot:
            slot_candidates.setdefault(slot, []).append((stats, guid, 'ecs'))
        else:
            no_slot_ecs.append((stats, guid))

    kept_flags: list[tuple] = list(no_slot_flags)
    kept_ecs: list[tuple] = list(no_slot_ecs)

    def flags_sort_key(sg: tuple) -> tuple:
        attached = in_rows(sg[0], wielded_rows) or in_rows(sg[0], gravity_disabled_rows)
        return (
            0 if (status_equipped and sg[0] in status_equipped) else 1,
            0 if in_cluster(sg[0]) else 1,
            0 if attached else 1,
            0 if in_rows(sg[0], owned_as_loot_rows) else 1,
            -get_mc(sg[0]),
        )

    for slot, candidates in slot_candidates.items():
        capacity = SLOT_CAPACITY.get(slot, 1)
        if slot == 'Melee Main Weapon':
            # Two one-handed Flags items both inside the equipment cluster can
            # only be a dual-wield pair: main and off hand.
            pair = [
                s
                for s, _g, sig in candidates
                if sig == 'flags'
                and in_cluster(s)
                and not (two_handed_stats and s in two_handed_stats)
            ]
            if len(pair) == 2:
                capacity = 2
        if len(candidates) <= capacity:
            for stats, guid, signal in candidates:
                (kept_flags if signal == 'flags' else kept_ecs).append((stats, guid))
            continue
        flags_cands = [(s, g) for s, g, sig in candidates if sig == 'flags']
        ecs_cands = [(s, g) for s, g, sig in candidates if sig == 'ecs']
        if flags_cands and ecs_cands:
            winners = sorted(flags_cands, key=flags_sort_key)[:capacity]
            kept_flags.extend(winners)
            demoted.extend(sg for sg in flags_cands if sg not in winners)
            demoted.extend(ecs_cands)
        elif flags_cands:
            winners = sorted(flags_cands, key=flags_sort_key)[:capacity]
            kept_flags.extend(winners)
            demoted.extend(sg for sg in flags_cands if sg not in winners)
        else:
            winners = sorted(ecs_cands, key=lambda sg: -get_mc(sg[0]))[:capacity]
            kept_ecs.extend(winners)
            demoted.extend(sg for sg in ecs_cands if sg not in winners)

    # 2-handed weapon in Melee Main Weapon blocks the offhand slot entirely.
    if two_handed_stats:
        main_has_twohanded = any(
            s in two_handed_stats
            for s, _ in kept_flags
            if stats_to_slot.get(s) == 'Melee Main Weapon'
        )
        if main_has_twohanded:
            still_kept: list[tuple] = []
            for s, g in kept_ecs:
                if stats_to_slot.get(s) == 'Melee Offhand Weapon':
                    demoted.append((s, g))
                else:
                    still_kept.append((s, g))
            kept_ecs = still_kept

    return kept_flags, kept_ecs, demoted
