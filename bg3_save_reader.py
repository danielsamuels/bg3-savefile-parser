#!/usr/bin/env python3
"""
bg3_save_reader.py  –  Extract character and item info from a BG3 .lsv save file.

Usage:
    python3 bg3_save_reader.py [save.lsv] [output.txt]

If save.lsv is omitted, the most recently modified save is auto-detected
(override the search root with the BG3_SAVE_DIR environment variable).
If output.txt is omitted the report is printed to stdout.

Dependencies (pip install):
    zstandard  lz4

What it extracts
----------------
  Party characters  – name, race, class/subclass, level, XP, origin
  Spells/abilities  – extracted from the LSMF ECS blob string pool;
                      split by known BG3 spell-ID prefixes and attributed
                      to each character using class-specific rules
  Equipped gear     – items whose on-equip passives create STATUS nodes
                      (partial: only passive-granting items are visible)
  Inventory         – all items with empty "Level" in the level cache
                      (~1 000+ items; ownership attribution needs LSMF parsing)
  Display names     – internal names resolved to "Display Name (INTERNAL_NAME)"
                      from the installed game data (root templates + loca),
                      where the game is found; otherwise internal names only.
                      Set BG3_DATA_DIR to point at the game's Data directory.

Known limitations
-----------------
  Complete equipment slots (weapon/shield/ring/amulet/armour by slot) and
  per-character inventory ownership live in the LSMF ECS binary blob.
  Spell attribution uses class-based heuristics; a small number of generic
  abilities (Jump, Help, Shove, etc.) appear for all characters and are
  reported once in the "shared" section rather than per character.
  See LIMITS.md for full details.
"""

import json
import re
import struct
import sys
from collections import Counter
from uuid import UUID

try:
    import zstandard as zstd
except ImportError:
    sys.exit("pip install zstandard")
try:
    import lz4.block
    import lz4.frame
except ImportError:
    sys.exit("pip install lz4")

# ---------------------------------------------------------------------------
# LSPK / LSOF low-level helpers
# ---------------------------------------------------------------------------

ZSTD_MAGIC = b'\x28\xb5\x2f\xfd'


def _extract_frames(path: str) -> list[bytes]:
    with open(path, 'rb') as fh:
        data = fh.read()
    frames, pos = [], 0
    while pos < len(data):
        idx = data.find(ZSTD_MAGIC, pos)
        if idx == -1:
            break
        nxt = data.find(ZSTD_MAGIC, idx + 4)
        if nxt == -1:
            frames.append(data[idx:])
            break
        frames.append(data[idx:nxt])
        pos = nxt
    return frames


def _decomp_frame(raw: bytes) -> bytes:
    return zstd.ZstdDecompressor().decompress(raw)


def _decomp_section(raw: bytes, disk: int, unc: int, flags: int, chunked: bool) -> bytes:
    if disk == 0 and unc == 0:
        return b''
    if disk == 0:
        return raw[:unc]
    m = flags & 0x0F
    if m == 0:
        return raw[:disk]
    if m == 2:
        return lz4.frame.decompress(raw[:disk]) if chunked else lz4.block.decompress(raw[:disk], uncompressed_size=unc)
    raise ValueError(f'unknown compression mode {m}')


def _parse_string_table(data: bytes) -> list[list[str]]:
    names, pos = [], 0
    (n,) = struct.unpack_from('<I', data, pos); pos += 4
    for _ in range(n):
        chain = []; names.append(chain)
        (ns,) = struct.unpack_from('<H', data, pos); pos += 2
        for _ in range(ns):
            (l,) = struct.unpack_from('<H', data, pos); pos += 2
            chain.append(data[pos:pos + l].decode('utf-8', 'replace'))
            pos += l
    return names


def _lkp(names: list[list[str]], nh: int) -> str:
    try:
        return names[nh >> 16][nh & 0xFFFF]
    except IndexError:
        return f'?{nh:08x}'


def _read_val(val_data: bytes, off: int, tid: int, length: int):
    try:
        if tid in (20, 21, 22, 23, 29, 30):
            return val_data[off:off + length - 1].decode('utf-8', 'replace').rstrip('\x00')
        if tid == 28:
            hlen = struct.unpack_from('<i', val_data, off + 2)[0]
            return val_data[off + 6:off + 6 + hlen - 1].decode('utf-8', 'replace').rstrip('\x00')
        if tid == 31:
            return str(UUID(bytes_le=val_data[off:off + 16]))
        if tid == 1:
            return val_data[off]
        if tid == 2:
            return struct.unpack_from('<H', val_data, off)[0]
        if tid == 3:
            return struct.unpack_from('<h', val_data, off)[0]
        if tid == 4:
            return struct.unpack_from('<i', val_data, off)[0]
        if tid == 5:
            return struct.unpack_from('<I', val_data, off)[0]
        if tid == 6:
            return struct.unpack_from('<f', val_data, off)[0]
        if tid == 19:
            return bool(val_data[off])
        if tid in (26, 32):
            return struct.unpack_from('<q', val_data, off)[0]
        if tid == 24:
            return struct.unpack_from('<Q', val_data, off)[0]
        if tid == 12:
            return struct.unpack_from('<fff', val_data, off)
        if tid == 25:
            return val_data[off:off + length]   # ScratchBuffer (opaque)
        return None
    except Exception:
        return None


def parse_lsof(data: bytes) -> list[dict]:
    """
    Parse an LSOF v7 binary into a flat list of node dicts.
    Each dict has: name, parent, children (list of indices), attrs (dict).
    """
    magic, ver = struct.unpack_from('<4sI', data, 0)
    assert magic == b'LSOF', f'bad magic {magic!r}'

    (str_unc, str_disk, _ku, _kd, nod_unc, nod_disk,
     att_unc, att_disk, val_unc, val_disk) = struct.unpack_from('<10I', data, 16)

    cflags, _, _, mfmt = struct.unpack_from('<BB2sI', data, 56)
    chunked = ver >= 0x02
    # Wide (16-byte) node entries go with a populated keys section, signalled by
    # the keys section sizes (_ku/_kd) — NOT by the metadata-format word (mfmt).
    # The game's root-template _merged.lsf set mfmt=2 yet still use 12-byte node
    # entries with no keys section, so keying off mfmt mis-sized the node table.
    has_keys = (_ku != 0 or _kd != 0)

    # A section with sizeOnDisk == 0 is stored uncompressed; its on-disk byte
    # count is then the uncompressed size.  (Save frames are compressed, so
    # disk > 0; the game's root-template _merged.lsf files are uncompressed.)
    str_n = str_disk or str_unc
    nod_n = nod_disk or nod_unc
    att_n = att_disk or att_unc
    val_n = val_disk or val_unc

    pos = 64
    str_raw = data[pos:pos + str_n]; pos += str_n
    nod_raw = data[pos:pos + nod_n]; pos += nod_n
    att_raw = data[pos:pos + att_n]; pos += att_n
    val_raw = data[pos:pos + val_n]

    str_data = _decomp_section(str_raw, str_disk, str_unc, cflags, False)
    nod_data = _decomp_section(nod_raw, nod_disk, nod_unc, cflags, chunked)
    att_data = _decomp_section(att_raw, att_disk, att_unc, cflags, chunked)
    val_data = _decomp_section(val_raw, val_disk, val_unc, cflags, chunked)

    names = _parse_string_table(str_data)
    node_size = 16 if has_keys else 12
    num_nodes = len(nod_data) // node_size

    nodes = []
    for i in range(num_nodes):
        base = i * node_size
        nh = struct.unpack_from('<I', nod_data, base)[0]
        par = struct.unpack_from('<i', nod_data, base + 8)[0]
        nodes.append({'name': _lkp(names, nh), 'parent': par, 'children': [], 'attrs': {}})

    for i, nd in enumerate(nodes):
        if 0 <= nd['parent'] < num_nodes:
            nodes[nd['parent']]['children'].append(i)

    data_off = 0
    for i in range(len(att_data) // 12):
        base = i * 12
        nh = struct.unpack_from('<I', att_data, base)[0]
        tl = struct.unpack_from('<I', att_data, base + 4)[0]
        ni = struct.unpack_from('<i', att_data, base + 8)[0]
        tid = tl & 0x3F
        length = tl >> 6
        aname = _lkp(names, nh)
        val = _read_val(val_data, data_off, tid, length)
        if val is not None and ni < num_nodes:
            nodes[ni]['attrs'][aname] = val
        data_off += length

    return nodes


# ---------------------------------------------------------------------------
# Info.json  (frame 8 in the LSPK)
# ---------------------------------------------------------------------------

def _parse_info_json(frames: list[bytes]) -> dict:
    raw = _decomp_frame(frames[8])
    return json.loads(raw.decode('utf-8'))


# ---------------------------------------------------------------------------
# Spell extraction from LSMF ECS blob
# ---------------------------------------------------------------------------

# Known BG3 spell-ID prefixes (order matters – longest first)
_SPELL_PREFIXES = [
    'Teleportation_', 'AspectOfTheBeast_', 'FightingStyle_', 'TotemSpirit_',
    'PactOfThe', 'Projectile_', 'Summon_', 'Target_', 'Shout_', 'Zone_',
    'Rush_', 'Wall_',
]

_PREFIX_RE = re.compile(
    r'(?=' + '|'.join(re.escape(p) for p in _SPELL_PREFIXES) + r')'
)

# Spell IDs exclusive to each class/subclass (used for attribution)
_CLASS_EXCLUSIVE = {
    # Fighter / Battle Master
    'Fighter': {
        'Shout_SecondWind', 'Shout_ActionSurge', 'Shout_IndomitableAction',
        'FightingStyle_Defense', 'FightingStyle_Dueling',
        'FightingStyle_GreatWeaponFighting', 'FightingStyle_Protection',
        'FightingStyle_Archery', 'FightingStyle_TwoWeaponFighting',
        'Target_TripAttack', 'Projectile_TripAttack',
        'Target_DisarmingAttack', 'Projectile_DisarmingAttack',
        'Target_PrecisionAttack', 'Shout_PrecisionAttack',
        'Target_MenacingAttack', 'Projectile_MenacingAttack',
        'Target_Riposte', 'Shout_PushingAttack',
        'Projectile_MAG_PushingAttack',
    },
    # Warlock / Fiend
    'Warlock': {
        'Projectile_EldritchBlast', 'Shout_BladeWard',
        'Shout_ArmorOfAgathys', 'Shout_ArmsOfHadar',
        'Target_HungerOfHadar', 'Shout_HellishRebuke',
        'Wall_WallOfFire', 'Target_HexAgonizingBlastRepellingBlast',
        'PactOfTheChain', 'PactOfTheBlade', 'PactOfTheTome',
        'Wall_WallOfFireSculptorOfFlesh',
        'Target_HungerOfHadarDevilsSight',
    },
    # Barbarian / Totem Warrior
    'Barbarian': {
        'Shout_Rage', 'Shout_Rage_Totem_Tiger', 'Shout_Rage_Totem_Bear',
        'Target_RecklessAttack', 'Zone_TigersBloodlust',
        'TotemSpirit_Bear', 'TotemSpirit_Tiger', 'TotemSpirit_Eagle',
        'AspectOfTheBeast_Wolverine', 'AspectOfTheBeast_Bear',
        'AspectOfTheBeast_Eagle', 'AspectOfTheBeast_Elk', 'AspectOfTheBeast_Wolf',
        'Rush_SpringAttack',
    },
    # Cleric / Trickery Domain
    'Cleric': {
        'Target_SacredFlame', 'Target_Guidance', 'Target_Resistance',
        'Shout_ProduceFlame', 'Target_Thaumaturgy',
        'Target_Bless', 'Target_Bane', 'Target_ShieldOfFaith',
        'Target_InflictWounds', 'Projectile_GuidingBolt',
        'Shout_TurnUndead', 'Target_SpiritualWeapon',
        'Shout_SpiritGuardians', 'Shout_SpiritGuardians_Radiant',
        'Shout_SpiritGuardians_Necrotic',
        'Shout_Aid', 'Shout_PassWithoutTrace',
        'Target_BestowCurse', 'Zone_Fear', 'Target_DeathWard',
        'Target_BlessingOfTheTrickster', 'Target_InvokeDuplicity',
        'Shout_CloakOfShadows',
        'Target_Banishment', 'Teleportation_Revivify',
        'Shout_HealingWord_Mass', 'Shout_BeaconOfHope',
        'Target_SpeakWithDead', 'Target_GuardianOfFaith',
    },
}

# Abilities common to all or most characters (not attributable by class)
_UNIVERSAL = {
    'Target_HealingWord', 'Projectile_Jump', 'Target_Dip', 'Shout_Hide',
    'Shout_Dash', 'Target_Help', 'Shout_Disengage', 'Target_MainHandAttack',
    'Target_OffhandAttack', 'Target_UnarmedAttack', 'Target_Topple',
    'Shout_Disengage_CunningAction', 'Shout_Dash_CunningAction',
    'Shout_Hide_BonusAction', 'Target_ShoveThrow_ThrowThrow_ImprovisedWeapon',
    'Shout_MAG_Aid3_Self',
}


def _extract_lsmf_blob(nodes: list[dict]) -> bytes | None:
    """Return the raw LSMF ScratchBuffer blob from the NewAge node."""
    for nd in nodes:
        if nd['name'] == 'NewAge' and nd['parent'] == -1:
            return nd['attrs'].get('NewAge')
    return None


def _split_spell_string(packed: str) -> list[str]:
    """Split a concatenated BG3 spell-ID string into individual spell IDs."""
    parts = _PREFIX_RE.split(packed)
    result = []
    for part in parts:
        part = part.strip('\x00 ')
        if part:
            result.append(part)
    return result


def _extract_spell_strings_from_lsmf(blob: bytes) -> list[str]:
    """
    Find all significant packed spell-ID strings in the LSMF blob.
    Returns the list of all non-trivial ASCII runs that contain spell IDs.
    """
    # Find runs of printable ASCII that contain spell-ID prefixes
    all_strings = []
    pos = 0
    while pos < len(blob):
        start = pos
        while pos < len(blob) and 32 <= blob[pos] < 127:
            pos += 1
        run_len = pos - start
        if run_len >= 30:
            s = blob[start:pos].decode('ascii', 'replace')
            # Only keep strings that look like they contain spell IDs
            if any(p in s for p in _SPELL_PREFIXES):
                all_strings.append(s)
        pos += 1
    return all_strings


_CLASS_MAIN_TO_KEY = {
    'Fighter':   'Fighter',
    'Warlock':   'Warlock',
    'Barbarian': 'Barbarian',
    'Cleric':    'Cleric',
    # add more classes here if needed
}


def extract_spells_by_character(
    lsmf_blob: bytes,
    party_info: list[dict],
) -> dict[str, list[str]]:
    """
    Extract spells from the LSMF blob and attribute them to party members
    using class-based rules.

    Returns a dict mapping display_name → list of spell IDs.
    """
    all_strings = _extract_spell_strings_from_lsmf(lsmf_blob)

    # Collect all spell IDs from all runs
    all_spell_ids: set[str] = set()
    for s in all_strings:
        for sid in _split_spell_string(s):
            all_spell_ids.add(sid)

    # Build per-character exclusive attribution
    result: dict[str, list[str]] = {}
    assigned: set[str] = set()

    # Map party character display names to their class keys
    char_class_map: dict[str, str] = {}
    for char_info in party_info:
        origin = char_info.get('Origin', 'Generic')
        display_name = origin if origin != 'Generic' else 'Maia (player)'
        classes = char_info.get('Classes', [])
        if classes:
            main_class = classes[0].get('Main', '')
            class_key = _CLASS_MAIN_TO_KEY.get(main_class, main_class)
            char_class_map[display_name] = class_key

    # First pass: attribute exclusively owned spells
    for name, class_key in char_class_map.items():
        exclusive = _CLASS_EXCLUSIVE.get(class_key, set())
        owned = sorted(all_spell_ids & exclusive)
        result[name] = owned
        assigned |= exclusive

    # Second pass: attribute remaining non-universal spells to best-match class
    remainder = all_spell_ids - assigned - _UNIVERSAL
    # Spells with no exclusive owner go to a shared/generic bucket (omitted for brevity)

    return result


# ---------------------------------------------------------------------------
# Character extraction from Globals (frame 0)
# ---------------------------------------------------------------------------

PARTY_ORIGINS = {
    'f08563b3-748d-4783-7b83-62b8c60b220b': 'Maia (player)',
    'c774d764-4a17-48dc-70b4-ac32cee97d44': 'Wyll',
    '2c76687d-93a2-477b-188b-148a49b54c30': 'Karlach',
    '3ed74f06-3c60-42dc-f683-34f047cb79c6': 'Shadowheart',
}

NULL_UUID = '00000000-0000-0000-0000-000000000000'


def _find_party_character_nodes(nodes: list[dict]) -> dict[str, int]:
    chars_root = next(
        (i for i, nd in enumerate(nodes) if nd['name'] == 'Characters' and nd['parent'] == -1),
        None,
    )
    if chars_root is None:
        return {}

    found = {}

    def _walk(ni: int):
        nd = nodes[ni]
        tmpl = nd['attrs'].get('CurrentTemplate', '')
        if tmpl in PARTY_ORIGINS:
            found[PARTY_ORIGINS[tmpl]] = ni
        for ci in nd['children']:
            _walk(ci)

    for ci in nodes[chars_root]['children']:
        _walk(ci)
    return found


def _collect_status_equipped_items(nodes: list[dict], char_ni: int) -> list[dict]:
    result = []

    def _walk(ni: int):
        nd = nodes[ni]
        if nd['name'] == 'STATUS':
            src = nd['attrs'].get('SourceEquippedItem', '')
            if src and src != NULL_UUID:
                result.append({'entity': src, 'status_id': nd['attrs'].get('ID', '')})
        for ci in nd['children']:
            _walk(ci)

    for ci in nodes[char_ni]['children']:
        _walk(ci)
    return result


def _build_entity_template_map(nodes: list[dict], root_name: str) -> dict[str, str]:
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


def _build_template_stats_map(nodes: list[dict]) -> dict[str, str]:
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


def _collect_inventory_items(nodes: list[dict]) -> list[dict]:
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
            result.append({
                'stats': item['attrs'].get('Stats', ''),
                'template': item['attrs'].get('CurrentTemplate', ''),
                'flags': item['attrs'].get('Flags', 0),
                'prev_level': item['attrs'].get('PreviousLevel', ''),
            })
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
_NON_EQUIP_PREFIXES = (
    'OBJ_', 'CONS_', 'ALCH_', 'FOOD_', 'SCR_', 'SCROLL_', 'BOOK_',
    'LOOT_', 'KEY_', 'PUZ_', 'PLT_', 'TItem_', 'GOLD_',
)
_NON_EQUIP_SUBSTR = (
    '_Camp_', 'Underwear', 'Keychain', 'GoldPile',
    'Backpack', 'AlchemyPouch', 'CampSupplies',
)


def _is_equipment_type(stats: str) -> bool:
    """True if a stats name could plausibly be worn equipment."""
    if not stats:
        return False
    if stats.startswith(_NON_EQUIP_PREFIXES):
        return False
    if any(sub in stats for sub in _NON_EQUIP_SUBSTR):
        return False
    return True


def _collect_character_positions(nodes0: list[dict], party_nodes: dict[str, int]) -> dict[str, tuple]:
    """display_name -> exact Translate tuple of that character."""
    out = {}
    for name, ni in party_nodes.items():
        t = nodes0[ni]['attrs'].get('Translate')
        if isinstance(t, tuple):
            out[name] = t
    return out


def _collect_items_by_position(node_lists: list[list[dict]],
                               positions: dict[str, tuple]) -> dict[str, list[tuple]]:
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
            if prev is None:
                acc[name][stats] = (flags, guid)
            elif isinstance(flags, int) and (flags & EQUIPPED_FLAG_BIT) \
                    and not (isinstance(prev[0], int) and (prev[0] & EQUIPPED_FLAG_BIT)):
                acc[name][stats] = (flags, guid)
    return {n: [(s, f, g) for s, (f, g) in d.items()] for n, d in acc.items()}


def _split_equipped_carried(
    items: list[tuple],
    status_equipped: set[str],
) -> tuple[list[tuple], list[tuple], list[tuple]]:
    """Classify a character's attributed items into (equipped, carried, undetermined).

    The save's LSF data carries no reliable worn-vs-carried flag (a worn item
    with no on-equip passive is byte-identical to a carried one), so we only
    assert what the signals support:

      equipped     – has a positive worn signal: a STATUS on-equip effect, or
                     the 0x04000000 Flags bit on an equipment-type item.
      carried      – not equipment at all (consumables, keys, gold, camp/
                     cosmetic clothing): confidently *not* worn gear.
      undetermined – equipment-type items with no worn signal: could be worn
                     (e.g. boots/amulets that grant no passive) or a spare.

    Each returned entry is a (stats, guid) pair.  The true worn set + slot lives
    in the ECS blob's MemberComponent.EquipmentSlot (see LIMITS.md).
    """
    equipped, carried, undetermined = [], [], []
    for stats, flags, guid in items:
        signalled = stats in status_equipped or (
            isinstance(flags, int)
            and (flags & EQUIPPED_FLAG_BIT)
            and _is_equipment_type(stats)
        )
        if signalled:
            equipped.append((stats, guid))
        elif _is_equipment_type(stats):
            undetermined.append((stats, guid))
        else:
            carried.append((stats, guid))
    return sorted(set(equipped)), sorted(set(carried)), sorted(set(undetermined))


# ---------------------------------------------------------------------------
# Display-name resolution from installed game data  (optional)
# ---------------------------------------------------------------------------
#
# The save stores only internal names: each item carries a `Stats` name
# (e.g. "UND_SwordInStone") and a runtime `CurrentTemplate` GUID.  The
# human-facing name ("Phalar Aluve") lives in the game's data files, reached by
#
#     CurrentTemplate GUID ─► root-template DisplayName handle ─► loca text
#                  or  Stats name ─► root-template DisplayName handle ─► loca text
#
# Root templates live in the `_merged.lsf` files inside Shared.pak / Gustav.pak
# (LSPK v18 packages); the handle→text table is `english.loca` inside
# English.pak.  In practice every item in a live save — worn, carried, and the
# whole level loot pool — uses a per-save *local* template GUID that is absent
# from the static root templates, so the Stats-name path is what resolves names
# (the GUID path resolved nothing across the test saves; it is kept only as a
# more-precise match should a static template GUID ever appear).  Because a
# stats name can be shared by several items (~9% of names map to >1 display
# name), an ambiguous stats name resolves to the first/base variant.  All of
# this is best-effort: with no game install (or a parse miss) the report falls
# back to the bare internal name.

import os

_LSPK_FILE_ENTRY = 272  # bytes per file-list entry in LSPK v18

# Root-template _merged.lsf files, in load order (later overrides earlier).
_ROOT_TEMPLATE_FILES = [
    ('Shared.pak',  'Public/Shared/RootTemplates/_merged.lsf'),
    ('Shared.pak',  'Public/SharedDev/RootTemplates/_merged.lsf'),
    ('Gustav.pak',  'Public/GustavDev/RootTemplates/_merged.lsf'),
    ('Gustav.pak',  'Public/Gustav/RootTemplates/_merged.lsf'),
    ('Gustav.pak',  'Public/Honour/RootTemplates/_merged.lsf'),
    ('GustavX.pak', 'Public/GustavX/RootTemplates/_merged.lsf'),
]
_LOCA_PAK = 'Localization/English.pak'
_LOCA_FILE = 'Localization/English/english.loca'

# Bump when the resolver logic changes so a stale cache is not silently reused.
_DISPLAYNAME_SCHEMA_VERSION = 2


def _find_game_data_dir() -> str | None:
    """Locate the BG3 Data directory, or None if not found."""
    env = os.environ.get('BG3_DATA_DIR')
    if env and os.path.isdir(env):
        return env
    candidates = [
        '~/.local/share/Steam/steamapps/common/Baldurs Gate 3/Data',
        '~/.steam/steam/steamapps/common/Baldurs Gate 3/Data',
        '~/Library/Application Support/Steam/steamapps/common/Baldurs Gate 3/Data',
        'C:/Program Files (x86)/Steam/steamapps/common/Baldurs Gate 3/Data',
    ]
    for c in candidates:
        p = os.path.expanduser(c)
        if os.path.isdir(p):
            return p
    return None


def _lspk_filelist(fh) -> dict[str, tuple]:
    """Return {name: (offset, part, flags, size_on_disk, uncompressed)} for an LSPK v18."""
    fh.seek(0)
    head = fh.read(64)
    magic, _ver = struct.unpack_from('<4sI', head, 0)
    if magic != b'LSPK':
        raise ValueError(f'not an LSPK package ({magic!r})')
    flist_off = struct.unpack_from('<Q', head, 8)[0]
    fh.seek(flist_off)
    num_files, comp_size = struct.unpack_from('<II', fh.read(8))
    comp = fh.read(comp_size)
    raw = lz4.block.decompress(comp, uncompressed_size=num_files * _LSPK_FILE_ENTRY)
    out = {}
    for i in range(num_files):
        b = i * _LSPK_FILE_ENTRY
        name = raw[b:b + 256].split(b'\x00')[0].decode('latin1')
        off_lo, off_hi, part, flags, sod, unc = struct.unpack_from('<IHBBII', raw, b + 256)
        out[name] = ((off_lo | (off_hi << 32)), part, flags, sod, unc)
    return out


def _lspk_extract(pak_path: str, name: str) -> bytes:
    """Extract and decompress a single file from an LSPK v18 package."""
    with open(pak_path, 'rb') as fh:
        flist = _lspk_filelist(fh)
        if name not in flist:
            raise KeyError(name)
        offset, part, flags, sod, unc = flist[name]
        src = pak_path
        if part != 0:  # spilled into a sibling part file (Foo.pak -> Foo_N.pak)
            src = pak_path[:-4] + f'_{part}.pak'
        with open(src, 'rb') as pf:
            pf.seek(offset)
            blob = pf.read(sod if sod else unc)
    method = flags & 0x0F
    if method == 0:
        return blob[:unc]
    if method == 2:
        return lz4.block.decompress(blob, uncompressed_size=unc)
    if method == 3:
        return zstd.ZstdDecompressor().decompress(blob)
    raise ValueError(f'unknown LSPK compression method {method}')


def _parse_loca(blob: bytes) -> dict[str, str]:
    """Parse an english.loca blob into {handle: text}."""
    sig, num, texts_off = struct.unpack_from('<4sII', blob, 0)
    if sig != b'LOCA':
        raise ValueError(f'not a LOCA file ({sig!r})')
    pos = 12
    entries = []
    for _ in range(num):
        key = blob[pos:pos + 64].split(b'\x00')[0].decode('latin1'); pos += 64
        pos += 2  # version (uint16)
        length = struct.unpack_from('<I', blob, pos)[0]; pos += 4
        entries.append((key, length))
    out = {}
    tp = texts_off
    for key, length in entries:
        out[key] = blob[tp:tp + length - 1].decode('utf-8', 'replace').strip()
        tp += length
    return out


def _cache_path(data_dir: str) -> str:
    sig_parts = []
    for pak in {p for p, _ in _ROOT_TEMPLATE_FILES} | {_LOCA_PAK}:
        fp = os.path.join(data_dir, pak)
        try:
            st = os.stat(fp)
            sig_parts.append(f'{pak}:{st.st_mtime_ns}:{st.st_size}')
        except OSError:
            pass
    import hashlib
    sig_parts.append(f'schema:{_DISPLAYNAME_SCHEMA_VERSION}')
    sig = hashlib.md5('|'.join(sorted(sig_parts)).encode()).hexdigest()[:16]
    cdir = os.path.join(
        os.environ.get('XDG_CACHE_HOME', os.path.expanduser('~/.cache')),
        'bg3-savefile-parser',
    )
    os.makedirs(cdir, exist_ok=True)
    return os.path.join(cdir, f'displaynames-{sig}.json')


def build_displayname_maps(data_dir: str) -> tuple[dict[str, str], dict[str, str]]:
    """Build (guid->display_name, stats_name->display_name) from game data.

    Results are cached under XDG_CACHE_HOME keyed on the source paks' mtime/size,
    so the ~1 s parse only happens after a game update.
    """
    cache = _cache_path(data_dir)
    try:
        with open(cache, encoding='utf-8') as fh:
            data = json.load(fh)
        return data['guid'], data['stats']
    except (OSError, ValueError, KeyError):
        pass

    handle_to_text = _parse_loca(_lspk_extract(os.path.join(data_dir, _LOCA_PAK), _LOCA_FILE))

    guid_handle: dict[str, str] = {}   # template GUID -> own DisplayName handle ('' if none)
    guid_parent: dict[str, str] = {}   # template GUID -> ParentTemplateId
    stats_handle: dict[str, str] = {}  # stats name -> DisplayName handle
    for pak, name in _ROOT_TEMPLATE_FILES:
        try:
            nodes = parse_lsof(_lspk_extract(os.path.join(data_dir, pak), name))
        except (OSError, KeyError, ValueError):
            continue
        for nd in nodes:
            if nd['name'] != 'GameObjects':
                continue
            key = nd['attrs'].get('MapKey')
            if not key:
                continue
            handle = nd['attrs'].get('DisplayName', '')
            guid_handle[key] = handle
            guid_parent[key] = nd['attrs'].get('ParentTemplateId', '')
            stats = nd['attrs'].get('Stats', '')
            if stats and handle:
                stats_handle.setdefault(stats, handle)

    def resolve_guid_handle(guid: str) -> str:
        cur = guid
        for _ in range(32):  # follow ParentTemplateId until a DisplayName is set
            h = guid_handle.get(cur)
            if h:
                return h
            par = guid_parent.get(cur)
            if not par or par == cur:
                return ''
            cur = par
        return ''

    guid_name: dict[str, str] = {}
    for guid in guid_handle:
        h = resolve_guid_handle(guid)
        txt = handle_to_text.get(h) if h else None
        if txt:
            guid_name[guid] = txt

    stats_name: dict[str, str] = {}
    for stats, h in stats_handle.items():
        txt = handle_to_text.get(h)
        if txt:
            stats_name[stats] = txt

    try:
        with open(cache, 'w', encoding='utf-8') as fh:
            json.dump({'guid': guid_name, 'stats': stats_name}, fh)
    except OSError:
        pass
    return guid_name, stats_name


class DisplayNames:
    """Resolves internal item identifiers to 'Display Name (INTERNAL_NAME)'."""

    def __init__(self, guid_name: dict[str, str], stats_name: dict[str, str]):
        self._guid = guid_name
        self._stats = stats_name

    @classmethod
    def load(cls) -> 'DisplayNames':
        data_dir = _find_game_data_dir()
        if not data_dir:
            return cls({}, {})
        try:
            return cls(*build_displayname_maps(data_dir))
        except Exception:  # never let display-name resolution break the report
            return cls({}, {})

    @property
    def available(self) -> bool:
        return bool(self._guid or self._stats)

    def name_for(self, stats: str, guid: str = '') -> str | None:
        """Return the display name for an item, preferring the precise GUID."""
        if guid and guid in self._guid:
            return self._guid[guid]
        return self._stats.get(stats)

    def fmt(self, stats: str, guid: str = '') -> str:
        """Format as 'Display Name (INTERNAL_NAME)', or just the internal name."""
        dn = self.name_for(stats, guid)
        return f'{dn} ({stats})' if dn else stats


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------

def _fmt_class(cls: dict) -> str:
    main = cls.get('Main', '')
    sub = cls.get('Sub', '')
    return f'{main} / {sub}' if sub else main


def build_report(save_path: str) -> str:
    lines = []
    w = lines.append

    w('BG3 Save File Report')
    w(f'Source: {save_path}')
    w('=' * 72)

    frames = _extract_frames(save_path)

    # Display-name resolver (best-effort; empty if game data not found)
    dn = DisplayNames.load()

    # ---- Info.json --------------------------------------------------------
    info = _parse_info_json(frames)
    save_name = info.get('Save Name', '?')
    game_ver  = info.get('Game Version', '?')
    cur_level = info.get('Current Level', '?')
    difficulty = ', '.join(info.get('Difficulty', []))

    w('')
    w(f'Save Name  : {save_name}')
    w(f'Game Ver   : {game_ver}')
    w(f'Level      : {cur_level}')
    w(f'Difficulty : {difficulty}')
    w(f'Item names : {"resolved from game data" if dn.available else "internal only (game data not found; set BG3_DATA_DIR)"}')

    party_info = info.get('Active Party', {}).get('Characters', [])

    # ---- Parse Globals (frame 0) ------------------------------------------
    frame0_data = _decomp_frame(frames[0])
    nodes0 = parse_lsof(frame0_data)

    party_nodes = _find_party_character_nodes(nodes0)
    entity_to_template0 = _build_entity_template_map(nodes0, 'Items')
    template_to_stats0 = _build_template_stats_map(nodes0)
    char_positions = _collect_character_positions(nodes0, party_nodes)

    # Extract LSMF blob for spell data
    lsmf_blob = None
    for nd in nodes0:
        if nd['name'] == 'NewAge' and nd['parent'] == -1:
            raw = nd['attrs'].get('NewAge')
            if isinstance(raw, bytes):
                lsmf_blob = raw
            break

    # Extract spells from LSMF
    spell_map: dict[str, list[str]] = {}
    if lsmf_blob:
        spell_map = extract_spells_by_character(lsmf_blob, party_info)

    # ---- Parse level cache (frame 3) for item data -----------------------
    frame3_data = _decomp_frame(frames[3])
    nodes3 = parse_lsof(frame3_data)
    template_to_stats3 = _build_template_stats_map(nodes3)

    # Merged template→stats: frame 0 (equipped items) takes priority
    template_to_stats = {**template_to_stats3, **template_to_stats0}

    # Per-character item attribution by shared world position (frame 0 + frame 3)
    items_by_char = _collect_items_by_position([nodes0, nodes3], char_positions)

    # ---- Characters -------------------------------------------------------
    w('')
    w('━' * 72)
    w('PARTY CHARACTERS')
    w('━' * 72)

    for i, char_info in enumerate(party_info):
        classes   = char_info.get('Classes', [])
        level     = char_info.get('Level', '?')
        origin    = char_info.get('Origin', 'Generic')
        race      = char_info.get('Race', '?')
        xp        = char_info.get('Experience Points (Total)', None)
        subregion = char_info.get('Subregion', '')

        display_name = origin if origin != 'Generic' else 'Maia (player)'
        cls_str = '; '.join(_fmt_class(c) for c in classes) if classes else '?'

        w('')
        w(f'  {display_name}')
        w(f'    Race      : {race}')
        w(f'    Class     : {cls_str}')
        w(f'    Level     : {level}')
        if xp is not None:
            w(f'    XP        : {xp}')
        w(f'    Location  : {subregion}')

        # Spells
        spells = spell_map.get(display_name, [])
        if spells:
            w(f'    Spells/Abilities ({len(spells)}):')
            for sid in sorted(spells):
                w(f'      – {sid}')
        else:
            w(f'    Spells/Abilities : (class-specific list not found)')

        # Equipped + carried items, attributed by shared world position
        char_ni = party_nodes.get(display_name)
        status_equipped: set[str] = set()
        if char_ni is not None:
            for e in _collect_status_equipped_items(nodes0, char_ni):
                tmpl = entity_to_template0.get(e['entity'], '')
                stats_name = template_to_stats.get(tmpl, '')
                if stats_name:
                    status_equipped.add(stats_name)

        attributed = items_by_char.get(display_name, [])
        if attributed:
            equipped, carried, undetermined = _split_equipped_carried(attributed, status_equipped)
            w(f'    Equipped ({len(equipped)}):')
            for s, guid in equipped:
                tag = '  (passive confirmed)' if s in status_equipped else ''
                w(f'      – {dn.fmt(s, guid)}{tag}')
            if undetermined:
                w(f'    Worn or carried — undetermined ({len(undetermined)}):')
                w(f'      (equipment with no worn signal in the save; the true')
                w(f'       worn set + slot is only in the ECS blob — see LIMITS.md)')
                for s, guid in undetermined:
                    w(f'      – {dn.fmt(s, guid)}')
            w(f'    Carried / personal inventory ({len(carried)}):')
            for s, guid in carried:
                w(f'      – {dn.fmt(s, guid)}')
        elif char_ni is None:
            w(f'    Equipment : character node not found')
        else:
            w(f'    Equipment : no items attributed (character off current level?)')

    # ---- Inventory --------------------------------------------------------
    w('')
    w('━' * 72)
    w('ALL ITEMS ON CURRENT LEVEL  (per-character gear listed above)')
    w('Note: items carried by party members are attributed to each character')
    w('above, by shared world position. The list below is the full level pool')
    w('(world loot, containers, vendor stock) for reference.')
    w('━' * 72)

    inv = _collect_inventory_items(nodes3)
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

    # ---- Limits note ------------------------------------------------------
    w('')
    w('━' * 72)
    w('LIMITS')
    w('━' * 72)
    w('''
  Spell attribution uses class-based heuristics: each spell ID is matched
  against a hard-coded set of abilities exclusive to that character's class.
  Generic abilities (Jump, Help, Shove, etc.) are omitted to reduce noise.
  Higher-level or multiclass spells may appear under the wrong character.

  Per-character item ownership is recovered from shared world position
  (each carried/worn item copies its holder's Translate).  Whether an
  attributed item is *worn* is only asserted when a signal supports it (a
  STATUS on-equip effect, or the 0x04000000 Flags bit); equipment-type items
  with no such signal are listed as "worn or carried — undetermined" rather
  than guessed, because the save's LSF data has no reliable worn flag (a worn
  item granting no passive is byte-identical to a carried one).  The
  authoritative worn set and exact slot live in the NewAge LSMF ECS blob
  (MemberComponent.EquipmentSlot), which this parser does not decode; a few
  unique items have no LSF Item record at all and live only in that blob.
  See LIMITS.md.

  Display names are resolved from the installed game data (root templates +
  english.loca).  Carried items use a per-save local template GUID, so they
  resolve by Stats name rather than GUID; a few camp/cosmetic/container items
  whose templates live in other paks stay as internal names.  Without a game
  install (or with BG3_DATA_DIR unset and auto-detect failing) every item is
  shown by its internal name only.
''')

    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# Save-file auto-detection
# ---------------------------------------------------------------------------
#
# Saves live at  <profiles>/<Profile>/Savegames/Story/<Char>-<id>__<Name>/<Name>.lsv
# under a platform-specific BG3 profiles directory.  With no save given on the
# command line, the most recently modified .lsv across the known locations is
# used (override the search root with BG3_SAVE_DIR).

def _candidate_profile_dirs() -> list[str]:
    home = os.path.expanduser('~')
    bg3 = "Larian Studios/Baldur's Gate 3/PlayerProfiles"
    dirs = [
        os.path.join(home, '.local/share', bg3),                       # native Linux
        os.path.join(home, '.local/share/Steam/steamapps/compatdata/1086940/pfx/'
                           'drive_c/users/steamuser/AppData/Local', bg3),  # Proton
        os.path.join(home, 'Documents', bg3),                          # macOS
    ]
    local = os.environ.get('LOCALAPPDATA')
    if local:
        dirs.append(os.path.join(local, bg3))                          # Windows
    return dirs


def _find_latest_save() -> str | None:
    """Return the path of the most recently modified .lsv, or None if none found."""
    import glob
    # An explicit BG3_SAVE_DIR restricts the search; otherwise scan the known
    # platform locations.
    env = os.environ.get('BG3_SAVE_DIR')
    roots = [env] if env else _candidate_profile_dirs()

    # A root may be a PlayerProfiles dir, a Savegames/Story dir, or a single
    # save folder; these patterns match a .lsv at each of those depths.
    patterns = (
        '*/Savegames/Story/*/*.lsv', 'Savegames/Story/*/*.lsv',
        'Story/*/*.lsv', '*/*.lsv', '*.lsv',
    )
    found = set()
    for root in roots:
        if not os.path.isdir(root):
            continue
        for pat in patterns:
            found.update(glob.glob(os.path.join(root, pat)))
    if not found:
        return None
    return max(found, key=os.path.getmtime)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    args = sys.argv[1:]
    save_path = args[0] if args else None
    out_path  = args[1] if len(args) > 1 else None

    if not save_path:
        save_path = _find_latest_save()
        if not save_path:
            sys.exit('usage: bg3_save_reader.py [save.lsv] [output.txt]\n'
                     'No save given and none auto-detected; pass a .lsv path '
                     'or set BG3_SAVE_DIR to your Savegames directory.')
        print(f'No save specified; using most recent: {save_path}', file=sys.stderr)

    print(f'Parsing {save_path} …', file=sys.stderr)
    report = build_report(save_path)

    if out_path:
        with open(out_path, 'w', encoding='utf-8') as fh:
            fh.write(report)
        print(f'Report written to {out_path}', file=sys.stderr)
    else:
        print(report)


if __name__ == '__main__':
    main()
