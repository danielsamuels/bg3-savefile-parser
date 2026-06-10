"""Report assembly from a parsed save."""

import datetime
from collections import Counter

from .gamedata import CLASS_UUID_NAMES, DisplayNames
from .lsf import decomp_frame, parse_lsof
from .lsmf import (
    GRAVITY_DISABLED_COMP,
    OWNED_AS_LOOT_COMP,
    WIELDED_COMP,
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
    SLOT_DISPLAY_ORDER,
    build_entity_template_map,
    build_instance_entity_map,
    build_template_stats_map,
    collect_character_positions,
    collect_inventory_items,
    collect_items_by_position,
    collect_status_equipped_items,
    ecs_resolve_equipped,
    find_party_character_nodes,
    invert_entity_template_map,
    resolve_slot_conflicts,
    split_equipped_carried,
)

# Basic actions present in every character's spell book; filtered from the
# per-character spell report to keep it readable.
COMMON_ACTION_SPELLS = frozenset((
    'Shout_Dash', 'Shout_Dash_NPC', 'Shout_Disengage', 'Shout_Hide',
    'Target_Shove', 'Target_Help', 'Target_Dip', 'Throw_Throw',
    'Throw_ImprovisedWeapon', 'Projectile_Jump',
    'Target_MainHandAttack', 'Projectile_MainHandAttack',
    'Target_OffhandAttack', 'Projectile_OffhandAttack',
    'Target_UnarmedAttack',
))


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------

def fmt_class(cls: dict) -> str:
    main = cls.get('Main', '')
    sub = cls.get('Sub', '')
    return f'{main} / {sub}' if sub else main


def build_report(save_path: str, frames: dict[str, bytes] | None = None, opts=None) -> str:
    lines = []
    w = lines.append

    def opt(name: str) -> bool:
        return bool(getattr(opts, name.replace('-', '_'), False)) if opts is not None else False

    w('BG3 Save File Report')
    w(f'Source: {save_path}')
    w('=' * 72)

    if frames is None:
        frames = extract_frames(save_path)

    # Display-name resolver (best-effort; empty if game data not found)
    dn = DisplayNames.load()
    dn.verbose = opt('verbose')

    # ---- Info.json --------------------------------------------------------
    info = parse_info_json(frames)
    party_info = info.get('Active Party', {}).get('Characters', [])

    # ---- MetaData ------------------------------------------------------------
    meta = parse_metadata(frames)
    leader_name = meta.get('leader_name') or ''
    player_display_name = f'{leader_name} (player)' if leader_name else 'Player'

    if opt('save-info'):
        save_name = info.get('Save Name', '?')
        game_ver  = info.get('Game Version', '?')
        cur_level = info.get('Current Level', '?')
        difficulty = ', '.join(info.get('Difficulty', []))

        save_time_str = '?'
        if meta.get('save_time') is not None:
            try:
                dt = datetime.datetime.fromtimestamp(meta['save_time'], tz=datetime.UTC)
                save_time_str = dt.strftime('%Y-%m-%d %H:%M:%S UTC')
            except (OSError, OverflowError, ValueError):
                save_time_str = str(meta['save_time'])

        w('')
        w(f'Save Name  : {save_name}')
        w(f'Save #     : {meta.get("save_game_id", "?")}')
        w(f'Saved At   : {save_time_str}')
        w(f'Game Ver   : {game_ver}')
        w(f'Level      : {cur_level}')
        w(f'Difficulty : {difficulty}')
        w(f'Leader     : {meta.get("leader_name", "?")}')
        user_mods = meta.get('user_mods', [])
        has_unofficial = meta.get('has_unofficial_mods', False)
        if user_mods:
            flag = '  (flagged unofficial by game)' if has_unofficial else ''
            w(f'Mods       : {len(user_mods)} user mod(s){flag}')
            for mod_entry in user_mods:
                w(f'             {mod_entry.get("name", "?")}')
        else:
            w('Mods       : none')
        item_name_source = (
            'resolved from game data'
            if dn.available
            else 'internal only (game data not found; set BG3_DATA_DIR)'
        )
        w(f'Item names : {item_name_source}')

    # ---- Parse Osiris story state — only when --quests requested -----------
    osiris = parse_osiris(frames) if opt('quests') else None

    # ---- Parse Globals.lsf --------------------------------------------------
    frame0_data = decomp_frame(frames['Globals.lsf'])
    nodes0 = parse_lsof(frame0_data)

    party_nodes = find_party_character_nodes(nodes0, player_display_name)
    entity_to_template0 = build_entity_template_map(nodes0, 'Items')
    template_to_stats0 = build_template_stats_map(nodes0)
    char_positions = collect_character_positions(nodes0, party_nodes)

    # Extract LSMF blob for spell data
    lsmf_blob = None
    for nd in nodes0:
        if nd['name'] == 'NewAge' and nd['parent'] == -1:
            raw = nd['attrs'].get('NewAge')
            if isinstance(raw, bytes):
                lsmf_blob = raw
            break

    # Exact per-character spell books from the ECS blob: each party member is
    # matched to its spell-book entity by (class, subclass, level) from
    # Info.json; multiple entities can match (origin-pool stand-ins exist for
    # each companion), so the largest book — the live character — wins.
    spellbooks: dict[int, list[str]] = {}
    entity_classes: dict[int, tuple] = {}
    if lsmf_blob:
        spellbooks = parse_lsmf_spellbooks(lsmf_blob)
        entity_classes = parse_lsmf_classes(lsmf_blob)

    def build_key(char_info: dict) -> tuple | None:
        want = sorted(
            (c.get('Main', ''), c.get('Sub', '')) for c in char_info.get('Classes', [])
        )
        level = char_info.get('Level')
        if not want or level is None:
            return None
        return (tuple(want), level)

    # Class matching cannot tell two members with identical class, subclass,
    # AND level apart; those members get an explanatory note instead.
    party_builds = [k for ci in party_info if (k := build_key(ci)) is not None]
    ambiguous_builds = {k for k in party_builds if party_builds.count(k) > 1}

    def exact_spellbook(char_info: dict) -> list[str] | None:
        """The character's spell book, matched by class/subclass/level."""
        key = build_key(char_info)
        if key is None or key in ambiguous_builds:
            return None
        want, level = list(key[0]), key[1]
        candidates = []
        for ent, classes in entity_classes.items():
            if ent not in spellbooks:
                continue
            got = sorted(
                (CLASS_UUID_NAMES.get(cg, ''),
                 CLASS_UUID_NAMES.get(sg, '') if sg != NULL_UUID else '')
                for cg, sg, _lvl in classes
            )
            if got == want and sum(lvl for _, _, lvl in classes) == level:
                candidates.append(ent)
        if not candidates:
            return None
        best = max(candidates, key=lambda e: len(spellbooks[e]))
        return spellbooks[best]

    # Parse LSMF once; also build the reverse map used by ecs_resolve_equipped
    lsmf_ecs = parse_lsmf_membership(lsmf_blob) if lsmf_blob else None
    comp_rows = parse_lsmf_component_rows(
        lsmf_blob, (OWNED_AS_LOOT_COMP, WIELDED_COMP, GRAVITY_DISABLED_COMP),
    ) if lsmf_blob else {}
    lsmf_owned_loot = comp_rows.get(OWNED_AS_LOOT_COMP)
    lsmf_wielded = comp_rows.get(WIELDED_COMP)
    lsmf_gravity_off = comp_rows.get(GRAVITY_DISABLED_COMP)
    lsmf_csd_pos = parse_lsmf_container_positions(lsmf_blob) if lsmf_blob else {}

    # --inspect: map every LSMF component's rows so items can be looked up
    inspect_pat = (getattr(opts, 'inspect', None) or '') if opts is not None else ''
    all_comp_rows: dict[str, frozenset[int]] = {}
    if inspect_pat and lsmf_blob:
        all_comp_rows = parse_lsmf_component_rows(lsmf_blob)

    template_to_instances = invert_entity_template_map(entity_to_template0)
    instance_entity_map = build_instance_entity_map(nodes0)

    # ---- Parse all level-cache files for item data --------------------------
    all_lc_node_lists: list[list[dict]] = []
    template_to_stats_lc: dict[str, str] = {}
    for lc_key, lc_raw in frames.items():
        if lc_key.startswith('LevelCache/') and lc_raw:
            lc_nodes = parse_lsof(decomp_frame(lc_raw))
            all_lc_node_lists.append(lc_nodes)
            template_to_stats_lc.update(build_template_stats_map(lc_nodes))

    # Merged template→stats: Globals.lsf (equipped items) takes priority
    template_to_stats = {**template_to_stats_lc, **template_to_stats0}

    # Per-character item attribution across Globals.lsf + all level caches
    items_by_char = collect_items_by_position([nodes0] + all_lc_node_lists, char_positions)

    # ---- Quest & story state (Osiris) — only when --quests requested --------
    if opt('quests'):
        w('')
        w('━' * 72)
        w('QUEST & STORY STATE  (Osiris / StorySave.bin)')
        w('━' * 72)
        if osiris is None:
            w('\n  (Osiris parse failed or frame not present)\n')
        else:
            osi_ver = osiris['version']
            w(f'\n  Osiris version: {osi_ver >> 8}.{osi_ver & 0xFF}')

            active = osiris['quests_active']
            closed = osiris['quests_closed']
            goals_fin = osiris['goals_finalized']
            gflags = osiris['global_flags']
            gflags_total = osiris['global_flags_total']

            w(f'\n  Quests in progress ({len(active)}):')
            for q in active:
                w(f'    {q}')

            w(f'\n  Quests closed / resolved ({len(closed)}):')
            w('  (closed covers completed and failed; no separate failed-quest DB)')
            for q in closed:
                w(f'    {q}')

            w(f'\n  Finalized goals — flags=0x07 ({len(goals_fin)}):')
            w('  (orchestration goals finalize when the act/phase is *entered*, not finished;')
            w('   the presence of "Act2" here means Act 2 was started, not completed)')
            for g in goals_fin:
                w(f'    {g}')

            w(f'\n  Story flags — DB_GlobalFlag (first {len(gflags)} of {gflags_total} shown):')
            for f in gflags:
                w(f'    {f}')
            w('')

    # ---- Characters -------------------------------------------------------
    w('')
    w('━' * 72)
    w('PARTY CHARACTERS')
    w('━' * 72)

    for char_info in party_info:
        classes   = char_info.get('Classes', [])
        level     = char_info.get('Level', '?')
        origin    = char_info.get('Origin', 'Generic')
        race      = char_info.get('Race', '?')
        xp        = char_info.get('Experience Points (Total)', None)
        subregion = char_info.get('Subregion', '')

        display_name = origin if origin != 'Generic' else player_display_name
        cls_str = '; '.join(fmt_class(c) for c in classes) if classes else '?'

        w('')
        w(f'  {display_name}')
        w(f'    Race      : {race}')
        w(f'    Class     : {cls_str}')
        w(f'    Level     : {level}')
        if xp is not None:
            w(f'    XP        : {xp}')
        if subregion:
            w(f'    Location  : {subregion}')

        # Spells — exact book from the ECS blob
        book = exact_spellbook(char_info)
        if book is not None:
            distinct = set(book)
            basics = distinct & COMMON_ACTION_SPELLS
            # Container variants (each Disguise Self appearance, every Chromatic
            # Orb element, …) collapse into their container spell by default.
            subs = distinct & dn.sub_spells
            if opt('all-spells'):
                basics = subs = set()
            # Upcast variants share a display name; show each rendering once.
            shown = sorted({dn.fmt_spell(sid) for sid in distinct - basics - subs})
            extras = [f'+{len(s)} {label}' for s, label in
                      ((subs, 'sub-spells'), (basics, 'basic actions')) if s]
            suffix = ('; ' + ', '.join(extras)) if extras else ''
            w(f'    Spells/Abilities ({len(shown)}{suffix}):')
            for line in shown:
                w(f'      – {line}')
        elif build_key(char_info) in ambiguous_builds:
            w('    Spells/Abilities : (identical class build to another party member '
              '— spell books cannot be told apart)')
        else:
            w('    Spells/Abilities : (spell book not found)')

        # Equipped + carried items, attributed by shared world position
        char_ni = party_nodes.get(display_name)
        status_equipped: set[str] = set()
        if char_ni is not None:
            for e in collect_status_equipped_items(nodes0, char_ni):
                tmpl = entity_to_template0.get(e['entity'], '')
                stats_name = template_to_stats.get(tmpl, '')
                if stats_name:
                    status_equipped.add(stats_name)

        # Build per-character stats→entity map using parallel Creators/Items arrays
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
                guid_to_rows_i, membership_count_i = lsmf_ecs if lsmf_ecs else ({}, {})
                w(f'    Inspect — items matching {inspect_pat!r}:')
                for s, f in matches:
                    eg = char_stats_to_entity.get(s, '')
                    rows = set(guid_to_rows_i.get(eg, []))
                    mc = max((membership_count_i.get(r, 0) for r in rows), default=0)
                    eq_bit = bool(isinstance(f, int) and f & EQUIPPED_FLAG_BIT)
                    flags_hex = hex(f) if isinstance(f, int) else repr(f)
                    w(f'      – {s}')
                    w(f'        eq_bit={eq_bit} flags={flags_hex} mc={mc} '
                      f'status={s in status_equipped}')
                    comps = sorted(n for n, rs in all_comp_rows.items() if rows & rs)
                    w(f'        components ({len(comps)}):')
                    for c in comps:
                        w(f'          {c}')
        if attributed:
            flags_equipped, carried, undetermined = split_equipped_carried(
                attributed, status_equipped,
                object_type_stats=dn.object_type_stats or None,
            )
            ecs_eq: list[tuple] = []
            if undetermined and lsmf_ecs is not None:
                ecs_eq, ecs_ca, undetermined = ecs_resolve_equipped(
                    undetermined, template_to_instances, *lsmf_ecs,
                    stats_to_entity=char_stats_to_entity,
                    wielded_rows=lsmf_wielded,
                )
                carried = sorted(set(carried) | set(ecs_ca))

            if dn.stats_to_slot and lsmf_ecs is not None:
                guid_to_rows, membership_count = lsmf_ecs
                flags_equipped, ecs_eq, demoted = resolve_slot_conflicts(
                    flags_equipped, ecs_eq,
                    dn.stats_to_slot, char_stats_to_entity,
                    guid_to_rows, membership_count,
                    owned_as_loot_rows=lsmf_owned_loot,
                    two_handed_stats=dn.two_handed_stats or None,
                    status_equipped=frozenset(status_equipped) if status_equipped else None,
                    wielded_rows=lsmf_wielded,
                    gravity_disabled_rows=lsmf_gravity_off,
                )
                carried = sorted(set(carried) | set(demoted))

            equipped = sorted(set(flags_equipped) | set(ecs_eq))
            w(f'    Equipped ({len(equipped)}):')
            # Slot is derived from game stat files: the save itself does not
            # serialise ItemSlot (the game re-derives it from stats on load).
            # Of two worn rings, the earlier ContainerSlotData row is the
            # first (upper) ring slot — verified in-game (QuickSave_291).
            def container_rank(stats: str, s2e=char_stats_to_entity) -> int:
                eg = s2e.get(stats, '')
                rows = lsmf_ecs[0].get(eg, []) if lsmf_ecs else []
                return min((lsmf_csd_pos[r] for r in rows if r in lsmf_csd_pos),
                           default=1 << 30)
            ring_slot_no: dict[str, int] = {}
            rings = [s for s, _g in equipped if dn.stats_to_slot.get(s) == 'Ring']
            if len(rings) > 1:
                for i, s in enumerate(sorted(rings, key=container_rank)):
                    ring_slot_no[s] = i + 1

            def slot_order(sg: tuple, ranks=ring_slot_no) -> tuple:
                slot = dn.stats_to_slot.get(sg[0], '')
                return (SLOT_DISPLAY_ORDER.get(slot, 99),
                        ranks.get(sg[0], 0), dn.fmt(sg[0], sg[1]))
            for s, guid in sorted(equipped, key=slot_order):
                slot = dn.stats_to_slot.get(s, '')
                if ring_slot_no.get(s, 0) == 2:
                    slot = 'Ring 2'
                suffix = f'  [{slot}]' if slot else ''
                w(f'      – {dn.fmt(s, guid)}{suffix}')
            if undetermined:
                w(f'    Worn or carried — undetermined ({len(undetermined)}):')
                for s, guid in undetermined:
                    w(f'      – {dn.fmt(s, guid)}')
            if opt('carried'):
                w(f'    Carried / personal inventory ({len(carried)}):')
                for s, guid in carried:
                    w(f'      – {dn.fmt(s, guid)}')
        elif char_ni is None:
            w('    Equipment : character node not found')
        else:
            w('    Equipment : no items attributed (character off current level?)')

    # ---- Inventory — only when --all-items requested ----------------------
    if opt('all-items'):
        w('')
        w('━' * 72)
        w('ALL ITEMS ON CURRENT LEVEL  (per-character gear listed above)')
        w('Note: items carried by party members are attributed to each character')
        w('above, by shared world position. The list below is the full level pool')
        w('(world loot, containers, vendor stock) for reference.')
        w('━' * 72)

        inv = [item for lc_nodes in all_lc_node_lists
               for item in collect_inventory_items(lc_nodes)]
        counts = Counter(item['stats'] for item in inv if item['stats'])
        inv_guid: dict[str, str] = {}  # stats -> a representative CurrentTemplate GUID
        for item in inv:
            if item['stats'] and item['template']:
                inv_guid.setdefault(item['stats'], item['template'])
        w(f'\n  {len(inv)} items total  ({len(counts)} unique types)\n')

        for stats_name, count in sorted(counts.items()):
            prefix = stats_name.split('_')[0]
            if prefix in ('WPN', 'MAG'):
                cat = '[weapon/magic]'
            elif prefix == 'ARM':
                cat = '[armour/accessory]'
            elif prefix == 'ALCH':
                cat = '[alchemy]'
            elif prefix in ('BOOK', 'SCR'):
                cat = '[book/scroll]'
            elif prefix in ('FOOD', 'CONS'):
                cat = '[consumable]'
            elif prefix in ('LOOT', 'MISC', 'OBJ', 'KEY'):
                cat = '[misc/loot]'
            else:
                cat = ''
            qty = f'x{count}' if count > 1 else '   '
            label = dn.fmt(stats_name, inv_guid.get(stats_name, ''))
            w(f'  {qty:4s} {label:60s} {cat}')

    # ---- Limits note — only when --limits requested -----------------------
    if opt('limits'):
        w('')
        w('━' * 72)
        w('LIMITS')
        w('━' * 72)
        w('''
  Spell attribution reads each character's exact spell book from the save's
  ECS blob (SpellBookComponent -> SpellData -> SpellId -> string pool),
  matching party members by class/subclass/level.  If two members share an
  identical build, their books cannot be told apart and a note is shown
  instead.

  Per-character item ownership is recovered from shared world position
  (each carried/worn item copies its holder's Translate).  Whether an
  attributed item is *worn* is determined by layered signals: a STATUS
  on-equip effect; the 0x04000000 Flags bit; ECS component membership; and
  physical-attachment components, with per-slot conflict resolution.  The
  displayed [Slot] is derived from item stats — the save stores no explicit
  ItemSlot field (same-type assignment like Ring vs Ring2 persists via
  container ordering).  See LIMITS.md.

  Display names are resolved from the installed game data (root templates +
  english.loca, following ParentTemplateId/using inheritance).  Without a
  game install (or with BG3_DATA_DIR unset and auto-detect failing) items
  are shown by their internal names.
''')

    return '\n'.join(lines)
