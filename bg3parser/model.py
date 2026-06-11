"""Report model: gather everything the views need from a parsed save.

gather_report() runs the full extraction pipeline and returns a SaveReport —
plain dataclasses with no formatting applied — which the views in render.py
turn into text or JSON.
"""

import datetime
import re
from dataclasses import dataclass, field

from .gamedata import CLASS_UUID_NAMES, DisplayNames
from .lsf import decomp_frame, parse_lsof
from .lsmf import (
    GRAVITY_DISABLED_COMP,
    OWNED_AS_LOOT_COMP,
    WIELDED_COMP,
    parse_lsmf_ability_scores,
    parse_lsmf_action_resources,
    parse_lsmf_all_container_positions,
    parse_lsmf_camp_supplies,
    parse_lsmf_cc_names,
    parse_lsmf_classes,
    parse_lsmf_component_rows,
    parse_lsmf_concentration,
    parse_lsmf_container_positions,
    parse_lsmf_feats,
    parse_lsmf_health,
    parse_lsmf_membership,
    parse_lsmf_prepared_spells,
    parse_lsmf_recipes,
    parse_lsmf_spellbooks,
    parse_lsmf_stack_amounts,
    parse_lsmf_stats_entities,
)
from .lspk import extract_frames, parse_info_json, parse_metadata
from .osiris import parse_osiris
from .party import (
    CAMP_RADIUS,
    EQUIPPED_FLAG_BIT,
    NULL_UUID,
    ORIGIN_INFO,
    PARTY_ORIGINS,
    PLAYER_CHAR_TEMPLATES,
    PLAYER_ORIGINS,
    build_entity_template_map,
    build_instance_entity_lists,
    build_template_stats_map,
    camp_distance,
    cluster_anchor_rows,
    collect_character_positions,
    collect_inventory_items,
    collect_items_by_position,
    collect_status_equipped_items,
    ecs_resolve_equipped,
    equipment_cluster,
    find_camp_chest,
    find_character_node_at,
    find_party_character_nodes,
    invert_entity_template_map,
    is_equipment_type,
    parse_journal_objectives,
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
    count: int = 1  # stack amount (766 gold = one ItemRef, count 766)


@dataclass
class SpellRef:
    id: str
    name: str | None = None
    category: str = 'spell'  # 'spell' | 'sub-spell' | 'basic-action'
    prepared: bool | None = None  # None = no preparation data for the entity


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
    at_camp: bool = False  # companion waiting at the campsite
    abilities: dict | None = None  # {str,dex,con,int,wis,cha} — effective scores
    hp: dict | None = None  # {current,max,temp,temp_max}
    resources: list[dict] | None = None  # action resources (slots, rage, ki...)
    concentration: dict | None = None  # {id, name} of the concentration spell
    feats: list[dict] | None = None  # [{guid, name, level, picks}]


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
    camp_chest: list[ItemRef] | None = None
    quests: dict | None = None
    story: dict | None = None
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

    `opts` gates the sections with real gathering cost (--quests, --all-items,
    --inspect); pure presentation flags (--verbose, --carried, --all-spells,
    --limits, --save-info) are handled by the views. Save metadata is always
    gathered (meta.lsf is parsed regardless, for the leader name).
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
        'game_id': meta.get('game_id', ''),  # regenerated per save; not campaign-stable
        'mods': [m.get('name', '?') for m in meta.get('user_mods', [])],
        'has_unofficial_mods': meta.get('has_unofficial_mods', False),
    }

    # ---- Globals.lsf ------------------------------------------------------
    nodes0 = parse_lsof(decomp_frame(frames['Globals.lsf']))
    party_nodes = find_party_character_nodes(nodes0, player_display_name)
    entity_to_template0 = build_entity_template_map(nodes0, 'Items')
    template_to_stats0 = build_template_stats_map(nodes0)
    char_positions = collect_character_positions(nodes0, party_nodes)

    # Party members without a known template (hirelings) match their node by
    # the bit-exact position Info.json carries.
    for ci in info.get('Active Party', {}).get('Characters', []):
        origin_i = ci.get('Origin', 'Generic')
        dname = player_display_name if origin_i in PLAYER_ORIGINS else origin_i
        pos_i = ci.get('Position')
        if dname in char_positions or not isinstance(pos_i, list) or len(pos_i) != 3:
            continue
        ni = find_character_node_at(nodes0, tuple(pos_i))
        if ni is not None:
            party_nodes[dname] = ni
            char_positions[dname] = tuple(pos_i)

    # Quests need the journal (Globals) for current objectives, so this runs
    # after nodes0 is parsed.
    if opt('quests'):
        journal_objectives = parse_journal_objectives(nodes0)

        def quest_ref(qid: str) -> dict:
            obj_id = journal_objectives.get(qid, '')
            return {
                'id': qid,
                'name': dn.quest_name_for(qid),
                'objective': dn.quest_objective_for(obj_id) if obj_id else None,
            }

        osiris = parse_osiris(frames)
        if osiris is None:
            report.quests = {'failed': True}
        else:
            report.quests = {
                'failed': False,
                'version': osiris['version'],
                'active': [quest_ref(q) for q in osiris['quests_active']],
                'closed': [quest_ref(q) for q in osiris['quests_closed']],
                'goals_finalized': osiris['goals_finalized'],
                'global_flags': osiris['global_flags'],
                'global_flags_total': osiris['global_flags_total'],
            }
            report.story = osiris['story']

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
    prepared_spells: dict[int, list[tuple]] = {}
    ability_scores: dict[int, tuple] = {}
    health: dict[int, tuple] = {}
    stats_entities: dict[str, int] = {}
    action_resources: dict[int, list[tuple]] = {}
    concentration: dict[int, str] = {}
    levelup_records: list[dict] = []
    cc_names: list[str] = []
    if lsmf_blob:
        spellbooks = parse_lsmf_spellbooks(lsmf_blob)
        entity_classes = parse_lsmf_classes(lsmf_blob)
        prepared_spells = parse_lsmf_prepared_spells(lsmf_blob)
        supplies = parse_lsmf_camp_supplies(lsmf_blob)
        ability_scores = parse_lsmf_ability_scores(lsmf_blob)
        health = parse_lsmf_health(lsmf_blob, ability_scores, CLASS_UUID_NAMES)
        report.save_info['camp_supplies'] = supplies if supplies else None
        report.save_info['recipes'] = parse_lsmf_recipes(lsmf_blob)
        wanted = {g.lower(): n for g, n in PARTY_ORIGINS.items()}
        for t in PLAYER_CHAR_TEMPLATES:
            wanted[t.lower()] = '__player__'
        stats_entities = parse_lsmf_stats_entities(lsmf_blob, wanted)
        action_resources = parse_lsmf_action_resources(lsmf_blob)
        concentration = parse_lsmf_concentration(lsmf_blob)
        levelup_records = parse_lsmf_feats(lsmf_blob)
        cc_names = parse_lsmf_cc_names(lsmf_blob)

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

    def exact_spell_entity(char_info: dict) -> int | None:
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
        return max(candidates, key=lambda e: len(spellbooks[e]))

    def norm_name(s: str) -> str:
        return re.sub(r'[^a-z]', '', s.lower())

    # Hirelings' custom names exist only in the CC stats rows. With a single
    # hireling and a single unrecognised created-character name, the pairing
    # is unambiguous; several hirelings stay under their preset labels.
    hireling_names: dict[str, str] = {}
    hireling_origins = [
        ci.get('Origin', '')
        for ci in party_info
        if str(ci.get('Origin', '')).startswith('Hireling_')
    ]
    if len(hireling_origins) == 1 and cc_names:
        known_names = {norm_name(n) for n in PARTY_ORIGINS.values()}
        known_names.add(norm_name(leader_name or ''))
        extras = [n for n in cc_names if norm_name(n) not in known_names]
        if len(extras) == 1:
            hireling_names[hireling_origins[0]] = extras[0]

    stats_ent_by_norm = {norm_name(k): v for k, v in stats_entities.items() if k != '__player__'}

    def linked_entity(origin: str) -> int | None:
        """The character's stats entity via the exact template link.

        Returns None for characters without a known template (hirelings) or
        whose linked entity has no spell book yet (not fully recruited);
        callers fall back to build matching.
        """
        if origin in PLAYER_ORIGINS:
            ent = stats_entities.get('__player__')
        else:
            ent = stats_ent_by_norm.get(norm_name(origin))
        return ent if ent is not None and ent in spellbooks else None

    # Level-up records carry no entity link (their owners live in the
    # character-creation subsystem's numbering); match by class build, and
    # only when the build is unique among the records.
    def cc_build_key(rec: dict) -> tuple | None:
        per_class: dict[str, tuple[str, int]] = {}
        for cls_guid, sub_guid in rec['levels']:
            main = CLASS_UUID_NAMES.get(cls_guid, '')
            sub = CLASS_UUID_NAMES.get(sub_guid, '') if sub_guid != NULL_UUID else ''
            prev = per_class.get(main, ('', 0))
            per_class[main] = (sub or prev[0], prev[1] + 1)
        if not per_class:
            return None
        want = sorted((main, sub) for main, (sub, _n) in per_class.items())
        return (tuple(want), len(rec['levels']))

    feats_by_build: dict[tuple, list[dict] | None] = {}
    for rec in levelup_records:
        key = cc_build_key(rec)
        if key is None:
            continue
        # None marks a duplicate build: ambiguous, never attached.
        feats_by_build[key] = None if key in feats_by_build else rec['feats']

    def attach_feats(char: CharacterReport, key: tuple | None) -> None:
        feats = feats_by_build.get(key) if key is not None else None
        if feats:
            char.feats = [
                {
                    'guid': f['guid'],
                    'name': dn.feat_name_for(f['guid']),
                    'level': f['level'],
                    'picks': f['picks'],
                }
                for f in feats
            ]

    def attach_sheet(char: CharacterReport, ent: int) -> None:
        """Attach the character sheet read through the entity's ECS rows:
        ability scores, hit points, action resources, concentration."""
        ab = ability_scores.get(ent)
        if ab is not None:
            char.abilities = dict(zip(('str', 'dex', 'con', 'int', 'wis', 'cha'), ab, strict=False))
        h = health.get(ent)
        if h is not None:
            char.hp = {'current': h[0], 'max': h[1], 'temp': h[2], 'temp_max': h[3]}
        rs = action_resources.get(ent)
        if rs is not None:
            char.resources = [
                {
                    'guid': g,
                    'name': dn.resource_name_for(g),
                    'level': lvl,
                    'current': amt,
                    'max': mx,
                    'replenish': repl,
                }
                for g, lvl, amt, mx, repl in rs
            ]
        spell_id = concentration.get(ent)
        if spell_id is not None:
            char.concentration = {'id': spell_id, 'name': dn.spell_name_for(spell_id)}

    def spell_refs(ent: int) -> list[SpellRef]:
        """Build the SpellRef list for an entity's book, marking prepared spells.

        A book entry is prepared when its base prototype name (upcast _N
        suffix stripped) appears in the entity's PreparedSpells; entities
        without preparation data get prepared=None throughout.
        """
        prepared = prepared_spells.get(ent)
        prepared_bases = (
            {re.sub(r'_\d+$', '', name) for name, _st, _g in prepared}
            if prepared is not None
            else None
        )
        refs = []
        for sid in sorted(set(spellbooks[ent])):
            if sid in COMMON_ACTION_SPELLS:
                cat = 'basic-action'
            elif sid in dn.sub_spells:
                cat = 'sub-spell'
            else:
                cat = 'spell'
            is_prepared = (
                re.sub(r'_\d+$', '', sid) in prepared_bases if prepared_bases is not None else None
            )
            refs.append(
                SpellRef(id=sid, name=dn.spell_name_for(sid), category=cat, prepared=is_prepared)
            )
        return refs

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
    lsmf_stack_amounts = parse_lsmf_stack_amounts(lsmf_blob) if lsmf_blob else {}

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

    def attach_items(char: CharacterReport, display_name: str) -> None:
        """Attribute and classify the items at a character's position."""
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
            return

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
        overlay_bagged: dict[str, list[str]] = {}
        if csd_cluster is not None and char_pos is not None and lsmf_ecs is not None:
            lo, hi = csd_cluster
            for stats_name in sorted({s for s, _f, _g in attributed}):
                ents = instance_entity_lists.get((char_pos, stats_name), ())
                if len(ents) < 2 or not is_equipment_type(stats_name):
                    continue
                worn_rows = []
                bagged_ents = []
                for eg in ents:
                    rows = [
                        r
                        for er in lsmf_ecs[0].get(eg, [])
                        for r in lsmf_all_csd.get(er, ())
                        if lo <= r <= hi
                    ]
                    if rows:
                        worn_rows.append(min(rows))
                    else:
                        bagged_ents.append(eg)
                tmpl = next(g for s, _f, g in attributed if s == stats_name)
                equipped = [(s, g) for s, g in equipped if s != stats_name]
                carried = [(s, g) for s, g in carried if s != stats_name]
                undetermined = [(s, g) for s, g in undetermined if s != stats_name]
                instance_worn_rows[stats_name] = sorted(worn_rows)
                overlay_bagged[stats_name] = bagged_ents
                equipped.extend((stats_name, tmpl) for _ in worn_rows)
                carried.extend((stats_name, tmpl) for _ in bagged_ents)

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
        # Stack amounts: a carried ItemRef's count is its instance's stack
        # total (one gold pile of 766 = one ref, count 766).
        bagged_iters = {s: iter(ents) for s, ents in overlay_bagged.items()}

        def carried_count(s: str, g: str, _iters=bagged_iters, _pos=char_pos) -> int:
            it = _iters.get(s)
            if it is not None:
                eg = next(it, None)
                return lsmf_stack_amounts.get(eg, 1) if eg else 1
            ents = instance_entity_lists.get((_pos, s), ()) if _pos is not None else ()
            if len(ents) == 1:
                return lsmf_stack_amounts.get(ents[0], 1)
            for eg in ents:
                if entity_to_template0.get(eg) == g:
                    return lsmf_stack_amounts.get(eg, 1)
            return 1

        char.carried = [item_ref(s, g, count=carried_count(s, g)) for s, g in carried]

    # ---- Characters -------------------------------------------------------
    for char_info in party_info:
        origin = char_info.get('Origin', 'Generic')
        display_name = player_display_name if origin in PLAYER_ORIGINS else origin
        pos_key = display_name
        if origin.startswith('Hireling_'):
            custom = hireling_names.get(origin)
            if custom:
                display_name = f'{custom} (hireling)'
        char = CharacterReport(
            name=display_name,
            race=char_info.get('Race', '?'),
            classes=char_info.get('Classes', []),
            level=char_info.get('Level', '?'),
            xp=char_info.get('Experience Points (Total)', None),
            location=(lambda raw: dn.subregion_name_for(raw) or raw)(
                char_info.get('Subregion', '')
            ),
        )
        report.characters.append(char)

        # Spells — exact book from the ECS blob: the template link gives the
        # entity directly; build matching remains as the hireling fallback.
        ent = linked_entity(char_info.get('Origin', 'Generic'))
        if ent is None:
            ent = exact_spell_entity(char_info)
        if ent is not None:
            char.spells = spell_refs(ent)
            attach_sheet(char, ent)
        elif build_key(char_info) in ambiguous_builds:
            char.spells_note = 'ambiguous-build'
        else:
            char.spells_note = 'not-found'

        attach_feats(char, build_key(char_info))
        attach_items(char, pos_key)

    # ---- Camp companions & camp chest ---------------------------------------
    # Companions outside the active party are recognised by proximity to the
    # camp chest (the campsite anchor). Their class/level/spells come from the
    # ECS blob, matched on the origin's fixed base class; when two companions
    # at camp share a base class the books cannot be told apart.
    chest_pos = find_camp_chest(nodes0)
    if chest_pos is not None and chest_pos != (0.0, 0.0, 0.0):
        active_names = {c.name for c in report.characters}
        camp_names = [
            name
            for name, pos in sorted(char_positions.items())
            if name not in active_names and camp_distance(pos, chest_pos) <= CAMP_RADIUS
        ]
        camp_base_classes = [ORIGIN_INFO.get(n, ('?', None))[1] for n in camp_names]
        active_build_keys = {k for ci in party_info if (k := build_key(ci)) is not None}

        def camp_spell_entity(base_class: str) -> int | None:
            candidates = []
            for ent, classes in entity_classes.items():
                if ent not in spellbooks:
                    continue
                names = [CLASS_UUID_NAMES.get(cg, '') for cg, _sg, _lvl in classes]
                if base_class not in names:
                    continue
                got = sorted(
                    (
                        CLASS_UUID_NAMES.get(cg, ''),
                        CLASS_UUID_NAMES.get(sg, '') if sg != NULL_UUID else '',
                    )
                    for cg, sg, _lvl in classes
                )
                total = sum(lvl for _, _, lvl in classes)
                if (tuple(got), total) in active_build_keys:
                    continue  # that entity is an active party member's
                candidates.append(ent)
            if not candidates:
                return None
            return max(candidates, key=lambda e: len(spellbooks[e]))

        for name in camp_names:
            race, base_class = ORIGIN_INFO.get(name, ('?', None))
            char = CharacterReport(
                name=name,
                race=race,
                classes=[],
                level='?',
                xp=None,
                location='camp',
                at_camp=True,
            )
            report.characters.append(char)

            ent = linked_entity(name)
            if ent is None:
                ent = (
                    camp_spell_entity(base_class)
                    if base_class and camp_base_classes.count(base_class) == 1
                    else None
                )
            if ent is not None:
                char.classes = [
                    {'Main': CLASS_UUID_NAMES.get(cg, '?')}
                    | ({'Sub': CLASS_UUID_NAMES.get(sg, '?')} if sg != NULL_UUID else {})
                    for cg, sg, _lvl in entity_classes[ent]
                ]
                char.level = sum(lvl for _, _, lvl in entity_classes[ent])
                char.spells = spell_refs(ent)
                attach_sheet(char, ent)
                camp_key = (
                    tuple(sorted((c.get('Main', ''), c.get('Sub', '')) for c in char.classes)),
                    char.level,
                )
                attach_feats(char, camp_key)
            elif base_class and camp_base_classes.count(base_class) > 1:
                char.spells_note = 'ambiguous-build'
            else:
                char.spells_note = 'not-found'

            attach_items(char, name)

        # Chest contents: every item at the chest's exact position.
        chest_items = collect_items_by_position(
            [nodes0] + all_lc_node_lists, {'__camp_chest__': chest_pos}
        ).get('__camp_chest__', [])

        def chest_count(stats: str, guid: str) -> int:
            ents = instance_entity_lists.get((chest_pos, stats), ())
            if len(ents) == 1:
                return lsmf_stack_amounts.get(ents[0], 1)
            total = 0
            for eg in ents:
                total += lsmf_stack_amounts.get(eg, 1)
            return total or 1

        report.camp_chest = [
            item_ref(stats, guid, count=chest_count(stats, guid))
            for stats, _flags, guid in sorted(chest_items)
            if stats
        ]

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
