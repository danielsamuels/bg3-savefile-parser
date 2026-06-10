"""Report model: gather everything the views need from a parsed save.

gather_report() runs the full extraction pipeline and returns a SaveReport —
plain dataclasses with no formatting applied — which the views in render.py
turn into text or JSON.
"""

import datetime
from dataclasses import dataclass, field

from .gamedata import CLASS_UUID_NAMES, DisplayNames
from .lsf import decomp_frame, parse_lsof
from .lsmf import (
    GRAVITY_DISABLED_COMP,
    OWNED_AS_LOOT_COMP,
    WIELDED_COMP,
    parse_lsmf_all_container_positions,
    parse_lsmf_classes,
    parse_lsmf_component_rows,
    parse_lsmf_container_positions,
    parse_lsmf_membership,
    parse_lsmf_spellbooks,
)
from .lspk import extract_frames, parse_info_json, parse_metadata
from .osiris import parse_osiris
from .party import (
    EQUIPPED_FLAG_BIT,
    NULL_UUID,
    build_entity_template_map,
    build_instance_entity_lists,
    build_template_stats_map,
    cluster_anchor_rows,
    collect_character_positions,
    collect_inventory_items,
    collect_items_by_position,
    collect_status_equipped_items,
    ecs_resolve_equipped,
    equipment_cluster,
    find_party_character_nodes,
    invert_entity_template_map,
    is_equipment_type,
    resolve_slot_conflicts,
    split_equipped_carried,
)

# Basic actions present in every character's spell book; folded out of the
# default spell list by the text view.
COMMON_ACTION_SPELLS = frozenset(
    (
        'Shout_Dash',
        'Shout_Dash_NPC',
        'Shout_Disengage',
        'Shout_Hide',
        'Target_Shove',
        'Target_Help',
        'Target_Dip',
        'Throw_Throw',
        'Throw_ImprovisedWeapon',
        'Projectile_Jump',
        'Target_MainHandAttack',
        'Projectile_MainHandAttack',
        'Target_OffhandAttack',
        'Projectile_OffhandAttack',
        'Target_UnarmedAttack',
    )
)


@dataclass
class ItemRef:
    """One item: resolved display name (None if unresolved) + internal IDs."""

    stats: str
    template_guid: str
    name: str | None = None
    slot: str | None = None  # equipment slot incl. 'Ring 2'; equipped only
    slot_rank: tuple = ()  # view ordering: (panel position, ring number)
    category: str = 'misc'  # weapon | armour | consumable | book | misc


@dataclass
class SpellRef:
    id: str
    name: str | None = None
    category: str = 'spell'  # 'spell' | 'sub-spell' | 'basic-action'


@dataclass
class InspectEntry:
    stats: str
    eq_bit: bool
    flags: str
    membership_count: int
    has_status: bool
    components: list[str] = field(default_factory=list)


@dataclass
class CharacterReport:
    name: str
    race: str
    classes: list[dict]
    level: object
    xp: int | None
    location: str
    spells: list[SpellRef] | None = None
    spells_note: str | None = None  # 'ambiguous-build' | 'not-found'
    equipped: list[ItemRef] = field(default_factory=list)
    undetermined: list[ItemRef] = field(default_factory=list)
    carried: list[ItemRef] = field(default_factory=list)
    equipment_note: str | None = None  # 'no-character-node' | 'no-items'
    inspect: list[InspectEntry] | None = None


@dataclass
class LevelItemEntry:
    stats: str
    template_guid: str
    name: str | None
    count: int
    category: str


@dataclass
class SaveReport:
    source: str
    characters: list[CharacterReport] = field(default_factory=list)
    save_info: dict | None = None
    quests: dict | None = None
    level_items: dict | None = None
    inspect_pattern: str = ''
    names_resolved: bool = False


ITEM_CATEGORY_BY_PREFIX = {
    'WPN': '[weapon/magic]',
    'MAG': '[weapon/magic]',
    'ARM': '[armour/accessory]',
    'ALCH': '[alchemy]',
    'BOOK': '[book/scroll]',
    'SCR': '[book/scroll]',
    'FOOD': '[consumable]',
    'CONS': '[consumable]',
    'LOOT': '[misc/loot]',
    'MISC': '[misc/loot]',
    'OBJ': '[misc/loot]',
    'KEY': '[misc/loot]',
}

# Fallback when an item has no stat-file slot (or no game data is installed).
ITEM_GROUP_BY_PREFIX = {
    'WPN': 'weapon',
    'MAG': 'weapon',
    'ARM': 'armour',
    'UNI': 'armour',
    'ALCH': 'consumable',
    'CONS': 'consumable',
    'FOOD': 'consumable',
    'BOOK': 'book',
    'SCR': 'book',
}


def item_category(stats: str, dn: DisplayNames) -> str:
    """Coarse inventory grouping: weapon | armour | consumable | book | misc.

    Equipment is recognised by its stat-file slot (covers region-prefixed
    names like GOB_DrowCommander_Amulet); everything else falls back to the
    stats-name prefix.
    """
    slot = dn.stats_to_slot.get(stats)
    if slot:
        return 'weapon' if 'Weapon' in slot else 'armour'
    parts = stats.split('_')
    if parts[0] == 'OBJ' and len(parts) > 1:
        if parts[1] in ('Potion', 'Drink'):
            return 'consumable'
        if parts[1] in ('Scroll', 'Book'):
            return 'book'
    return ITEM_GROUP_BY_PREFIX.get(parts[0], 'misc')


# Display order for equipped items, mirroring the in-game panel.
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


def gather_report(save_path: str, frames: dict[str, bytes] | None = None, opts=None) -> SaveReport:
    """Run the extraction pipeline and return the structured report model.

    `opts` gates the sections with real gathering cost (--save-info, --quests,
    --all-items, --inspect); pure presentation flags (--verbose, --carried,
    --all-spells, --limits) are handled by the views.
    """

    def opt(name: str) -> bool:
        return bool(getattr(opts, name.replace('-', '_'), False)) if opts is not None else False

    if frames is None:
        frames = extract_frames(save_path)

    dn = DisplayNames.load()

    def item_ref(stats: str, guid: str, **kw) -> ItemRef:
        return ItemRef(
            stats=stats,
            template_guid=guid,
            name=dn.name_for(stats, guid),
            category=item_category(stats, dn),
            **kw,
        )

    report = SaveReport(source=save_path, names_resolved=dn.available)

    info = parse_info_json(frames)
    party_info = info.get('Active Party', {}).get('Characters', [])
    meta = parse_metadata(frames)
    leader_name = meta.get('leader_name') or ''
    player_display_name = f'{leader_name} (player)' if leader_name else 'Player'

    if opt('save-info'):
        save_time_str = '?'
        if meta.get('save_time') is not None:
            try:
                dt = datetime.datetime.fromtimestamp(meta['save_time'], tz=datetime.UTC)
                save_time_str = dt.strftime('%Y-%m-%d %H:%M:%S UTC')
            except (OSError, OverflowError, ValueError):
                save_time_str = str(meta['save_time'])
        report.save_info = {
            'save_name': info.get('Save Name', '?'),
            'save_id': meta.get('save_game_id', '?'),
            'saved_at': save_time_str,
            'game_version': info.get('Game Version', '?'),
            'level': info.get('Current Level', '?'),
            'difficulty': ', '.join(info.get('Difficulty', [])),
            'leader': meta.get('leader_name', '?'),
            'mods': [m.get('name', '?') for m in meta.get('user_mods', [])],
            'has_unofficial_mods': meta.get('has_unofficial_mods', False),
        }

    if opt('quests'):
        osiris = parse_osiris(frames)
        if osiris is None:
            report.quests = {'failed': True}
        else:
            report.quests = {
                'failed': False,
                'version': osiris['version'],
                'active': osiris['quests_active'],
                'closed': osiris['quests_closed'],
                'goals_finalized': osiris['goals_finalized'],
                'global_flags': osiris['global_flags'],
                'global_flags_total': osiris['global_flags_total'],
            }

    # ---- Globals.lsf ------------------------------------------------------
    nodes0 = parse_lsof(decomp_frame(frames['Globals.lsf']))
    party_nodes = find_party_character_nodes(nodes0, player_display_name)
    entity_to_template0 = build_entity_template_map(nodes0, 'Items')
    template_to_stats0 = build_template_stats_map(nodes0)
    char_positions = collect_character_positions(nodes0, party_nodes)

    lsmf_blob = None
    for nd in nodes0:
        if nd['name'] == 'NewAge' and nd['parent'] == -1:
            raw = nd['attrs'].get('NewAge')
            if isinstance(raw, bytes):
                lsmf_blob = raw
            break

    # Exact per-character spell books: each party member is matched to its
    # spell-book entity by (class, subclass, level); multiple entities can
    # match (origin-pool stand-ins exist per companion), so the largest book —
    # the live character — wins.
    spellbooks: dict[int, list[str]] = {}
    entity_classes: dict[int, tuple] = {}
    if lsmf_blob:
        spellbooks = parse_lsmf_spellbooks(lsmf_blob)
        entity_classes = parse_lsmf_classes(lsmf_blob)

    def build_key(char_info: dict) -> tuple | None:
        want = sorted((c.get('Main', ''), c.get('Sub', '')) for c in char_info.get('Classes', []))
        level = char_info.get('Level')
        if not want or level is None:
            return None
        return (tuple(want), level)

    # Class matching cannot tell two members with identical class, subclass,
    # AND level apart; those members get an explanatory note instead.
    party_builds = [k for ci in party_info if (k := build_key(ci)) is not None]
    ambiguous_builds = {k for k in party_builds if party_builds.count(k) > 1}

    def exact_spellbook(char_info: dict) -> list[str] | None:
        key = build_key(char_info)
        if key is None or key in ambiguous_builds:
            return None
        want, level = list(key[0]), key[1]
        candidates = []
        for ent, classes in entity_classes.items():
            if ent not in spellbooks:
                continue
            got = sorted(
                (
                    CLASS_UUID_NAMES.get(cg, ''),
                    CLASS_UUID_NAMES.get(sg, '') if sg != NULL_UUID else '',
                )
                for cg, sg, _lvl in classes
            )
            if got == want and sum(lvl for _, _, lvl in classes) == level:
                candidates.append(ent)
        if not candidates:
            return None
        return spellbooks[max(candidates, key=lambda e: len(spellbooks[e]))]

    lsmf_ecs = parse_lsmf_membership(lsmf_blob) if lsmf_blob else None
    comp_rows = (
        parse_lsmf_component_rows(
            lsmf_blob,
            (OWNED_AS_LOOT_COMP, WIELDED_COMP, GRAVITY_DISABLED_COMP),
        )
        if lsmf_blob
        else {}
    )
    lsmf_owned_loot = comp_rows.get(OWNED_AS_LOOT_COMP)
    lsmf_wielded = comp_rows.get(WIELDED_COMP)
    lsmf_gravity_off = comp_rows.get(GRAVITY_DISABLED_COMP)
    lsmf_csd_pos = parse_lsmf_container_positions(lsmf_blob) if lsmf_blob else {}
    lsmf_all_csd = parse_lsmf_all_container_positions(lsmf_blob) if lsmf_blob else {}

    inspect_pat = (getattr(opts, 'inspect', None) or '') if opts is not None else ''
    report.inspect_pattern = inspect_pat
    all_comp_rows: dict[str, frozenset[int]] = {}
    if inspect_pat and lsmf_blob:
        all_comp_rows = parse_lsmf_component_rows(lsmf_blob)

    template_to_instances = invert_entity_template_map(entity_to_template0)
    instance_entity_lists = build_instance_entity_lists(nodes0)
    instance_entity_map = {key: ents[0] for key, ents in instance_entity_lists.items()}

    # ---- Level caches -----------------------------------------------------
    all_lc_node_lists: list[list[dict]] = []
    template_to_stats_lc: dict[str, str] = {}
    for lc_key, lc_raw in frames.items():
        if lc_key.startswith('LevelCache/') and lc_raw:
            lc_nodes = parse_lsof(decomp_frame(lc_raw))
            all_lc_node_lists.append(lc_nodes)
            template_to_stats_lc.update(build_template_stats_map(lc_nodes))
    template_to_stats = {**template_to_stats_lc, **template_to_stats0}
    items_by_char = collect_items_by_position([nodes0] + all_lc_node_lists, char_positions)

    # ---- Characters -------------------------------------------------------
    for char_info in party_info:
        origin = char_info.get('Origin', 'Generic')
        display_name = origin if origin != 'Generic' else player_display_name
        char = CharacterReport(
            name=display_name,
            race=char_info.get('Race', '?'),
            classes=char_info.get('Classes', []),
            level=char_info.get('Level', '?'),
            xp=char_info.get('Experience Points (Total)', None),
            location=char_info.get('Subregion', ''),
        )
        report.characters.append(char)

        # Spells — exact book from the ECS blob
        book = exact_spellbook(char_info)
        if book is not None:
            char.spells = []
            for sid in sorted(set(book)):
                if sid in COMMON_ACTION_SPELLS:
                    cat = 'basic-action'
                elif sid in dn.sub_spells:
                    cat = 'sub-spell'
                else:
                    cat = 'spell'
                char.spells.append(SpellRef(id=sid, name=dn.spell_name_for(sid), category=cat))
        elif build_key(char_info) in ambiguous_builds:
            char.spells_note = 'ambiguous-build'
        else:
            char.spells_note = 'not-found'

        # Items attributed by shared world position
        char_ni = party_nodes.get(display_name)
        status_equipped: set[str] = set()
        if char_ni is not None:
            for e in collect_status_equipped_items(nodes0, char_ni):
                tmpl = entity_to_template0.get(e['entity'], '')
                stats_name = template_to_stats.get(tmpl, '')
                if stats_name:
                    status_equipped.add(stats_name)

        char_pos = char_positions.get(display_name)
        char_stats_to_entity: dict[str, str] = {}
        if char_pos is not None:
            for (trans, stats_key), eg in instance_entity_map.items():
                if trans == char_pos:
                    char_stats_to_entity[stats_key] = eg

        attributed = items_by_char.get(display_name, [])
        if inspect_pat and attributed:
            matches = [(s, f) for s, f, _g in attributed if inspect_pat.lower() in s.lower()]
            if matches:
                char.inspect = []
                guid_to_rows_i, membership_count_i = lsmf_ecs if lsmf_ecs else ({}, {})
                for s, f in matches:
                    eg = char_stats_to_entity.get(s, '')
                    rows = set(guid_to_rows_i.get(eg, []))
                    char.inspect.append(
                        InspectEntry(
                            stats=s,
                            eq_bit=bool(isinstance(f, int) and f & EQUIPPED_FLAG_BIT),
                            flags=hex(f) if isinstance(f, int) else repr(f),
                            membership_count=max(
                                (membership_count_i.get(r, 0) for r in rows), default=0
                            ),
                            has_status=s in status_equipped,
                            components=sorted(n for n, rs in all_comp_rows.items() if rows & rs),
                        )
                    )

        if not attributed:
            char.equipment_note = 'no-character-node' if char_ni is None else 'no-items'
            continue

        flags_equipped, carried, undetermined = split_equipped_carried(
            attributed,
            status_equipped,
            object_type_stats=dn.object_type_stats or None,
        )

        # The cluster of ContainerSlotData rows holding this character's worn
        # items, anchored on the uncontested LSF-signalled ones.
        csd_cluster = None
        if dn.stats_to_slot and lsmf_ecs is not None and lsmf_all_csd:
            csd_cluster = equipment_cluster(
                cluster_anchor_rows(
                    flags_equipped,
                    dn.stats_to_slot,
                    char_stats_to_entity,
                    lsmf_ecs[0],
                    lsmf_all_csd,
                )
            )

        ecs_eq: list[tuple] = []
        if undetermined and lsmf_ecs is not None:
            ecs_eq, ecs_ca, undetermined = ecs_resolve_equipped(
                undetermined,
                template_to_instances,
                *lsmf_ecs,
                stats_to_entity=char_stats_to_entity,
                wielded_rows=lsmf_wielded,
                csd_cluster=csd_cluster,
                all_csd=lsmf_all_csd or None,
            )
            carried = sorted(set(carried) | set(ecs_ca))

        if dn.stats_to_slot and lsmf_ecs is not None:
            guid_to_rows, membership_count = lsmf_ecs
            flags_equipped, ecs_eq, demoted = resolve_slot_conflicts(
                flags_equipped,
                ecs_eq,
                dn.stats_to_slot,
                char_stats_to_entity,
                guid_to_rows,
                membership_count,
                owned_as_loot_rows=lsmf_owned_loot,
                two_handed_stats=dn.two_handed_stats or None,
                status_equipped=frozenset(status_equipped) if status_equipped else None,
                wielded_rows=lsmf_wielded,
                gravity_disabled_rows=lsmf_gravity_off,
                csd_cluster=csd_cluster,
                all_csd=lsmf_all_csd or None,
            )
            carried = sorted(set(carried) | set(demoted))

        equipped = sorted(set(flags_equipped) | set(ecs_eq))

        # Several physical copies of one item type on a character share the
        # (translate, stats) key the pipeline runs on, collapsing them into one
        # entry (e.g. four identical shortswords: two dual-wielded, two in a
        # bag). Reclassify such groups per instance: each copy's own
        # ContainerSlotData rows decide, against the equipment cluster.
        instance_worn_rows: dict[str, list[int]] = {}
        if csd_cluster is not None and char_pos is not None and lsmf_ecs is not None:
            lo, hi = csd_cluster
            for stats_name in {s for s, _f, _g in attributed}:
                ents = instance_entity_lists.get((char_pos, stats_name), ())
                if len(ents) < 2 or not is_equipment_type(stats_name):
                    continue
                worn_rows = []
                for eg in ents:
                    rows = [
                        r
                        for er in lsmf_ecs[0].get(eg, [])
                        for r in lsmf_all_csd.get(er, ())
                        if lo <= r <= hi
                    ]
                    if rows:
                        worn_rows.append(min(rows))
                tmpl = next(g for s, _f, g in attributed if s == stats_name)
                equipped = [(s, g) for s, g in equipped if s != stats_name]
                carried = [(s, g) for s, g in carried if s != stats_name]
                undetermined = [(s, g) for s, g in undetermined if s != stats_name]
                instance_worn_rows[stats_name] = sorted(worn_rows)
                equipped.extend((stats_name, tmpl) for _ in worn_rows)
                carried.extend((stats_name, tmpl) for _ in range(len(ents) - len(worn_rows)))

        # Slot is derived from game stat files (the save does not serialise
        # ItemSlot). Of two worn rings, the earlier ContainerSlotData row is
        # the first (upper) ring slot — verified in-game (QuickSave_291).
        def container_rank(stats: str, s2e=char_stats_to_entity) -> int:
            eg = s2e.get(stats, '')
            rows = lsmf_ecs[0].get(eg, []) if lsmf_ecs else []
            return min((lsmf_csd_pos[r] for r in rows if r in lsmf_csd_pos), default=1 << 30)

        ring_slot_no: dict[str, int] = {}
        rings = [s for s, _g in equipped if dn.stats_to_slot.get(s) == 'Ring']
        if len(rings) > 1:
            for i, s in enumerate(sorted(rings, key=container_rank)):
                ring_slot_no[s] = i + 1

        # Per-entry display rank: a duplicate group's k-th equipped entry takes
        # its k-th worn instance's ContainerSlotData row.
        entry_rows: list[tuple[str, str, int]] = []
        dupe_seen: dict[str, int] = {}
        for s, guid in equipped:
            if s in instance_worn_rows:
                k = dupe_seen.get(s, 0)
                dupe_seen[s] = k + 1
                row = instance_worn_rows[s][k]
            else:
                row = container_rank(s)
            entry_rows.append((s, guid, row))

        # Two one-handed weapons in "Melee Main Weapon" are a dual-wield pair;
        # as with rings, the earlier ContainerSlotData row is the main hand.
        offhand_idx: set[int] = set()
        melee_idx = [
            i
            for i, (s, _g, _r) in enumerate(entry_rows)
            if dn.stats_to_slot.get(s) == 'Melee Main Weapon'
        ]
        if len(melee_idx) == 2:
            offhand_idx.add(max(melee_idx, key=lambda i: entry_rows[i][2]))

        for i, (s, guid, _row) in enumerate(entry_rows):
            slot = dn.stats_to_slot.get(s, '')
            if i in offhand_idx:
                slot = 'Melee Offhand Weapon'
            rank = (SLOT_DISPLAY_ORDER.get(slot, 99), ring_slot_no.get(s, 0))
            if ring_slot_no.get(s, 0) == 2:
                slot = 'Ring 2'
            char.equipped.append(item_ref(s, guid, slot=slot or None, slot_rank=rank))
        char.undetermined = [item_ref(s, g) for s, g in undetermined]
        char.carried = [item_ref(s, g) for s, g in carried]

    # ---- Full level item pool (--all-items) --------------------------------
    if opt('all-items'):
        inv = [item for lc_nodes in all_lc_node_lists for item in collect_inventory_items(lc_nodes)]
        counts: dict[str, int] = {}
        inv_guid: dict[str, str] = {}
        for item in inv:
            if item['stats']:
                counts[item['stats']] = counts.get(item['stats'], 0) + 1
                if item['template']:
                    inv_guid.setdefault(item['stats'], item['template'])
        entries = []
        for stats_name, count in sorted(counts.items()):
            guid = inv_guid.get(stats_name, '')
            entries.append(
                LevelItemEntry(
                    stats=stats_name,
                    template_guid=guid,
                    name=dn.name_for(stats_name, guid),
                    count=count,
                    category=ITEM_CATEGORY_BY_PREFIX.get(stats_name.split('_')[0], ''),
                )
            )
        report.level_items = {
            'total': len(inv),
            'unique': len(counts),
            'entries': entries,
        }

    return report
