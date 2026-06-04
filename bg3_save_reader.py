#!/usr/bin/env python3
"""
bg3_save_reader.py  –  Extract character and item info from a BG3 .lsv save file.

Usage:
    python3 bg3_save_reader.py <save.lsv> [output.txt]

If output.txt is omitted the report is printed to stdout.

Dependencies (pip install):
    zstandard  lz4

What it extracts
----------------
  Party characters     – name, race, class/subclass, level, XP, origin
  Equipped gear        – items whose passives are active as status effects
                         (partial; only items that apply a stat status count)
  Inventory            – all items with empty "Level" field in the level cache
                         (1 000+ items; not attributed to individual characters
                         because ownership lives in the ECS blob, see LIMITS.md)

Known limitations
-----------------
  Spell selections, complete equipment slots (ring/amulet/weapon/armour by slot),
  and per-character inventory ownership all live in the NewAge/LSMF ECS binary
  blob (attribute type ScratchBuffer).  lslib itself treats this as opaque bytes;
  parsing it is out of scope for this script.
"""

import json
import struct
import sys
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
        return None  # opaque / ignored
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
    has_keys = mfmt != 0

    pos = 64
    str_raw = data[pos:pos + str_disk]; pos += str_disk
    nod_raw = data[pos:pos + nod_disk]; pos += nod_disk
    att_raw = data[pos:pos + att_disk]; pos += att_disk
    val_raw = data[pos:pos + val_disk]

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
    """Frame 8 is Info.json; return its parsed content."""
    raw = _decomp_frame(frames[8])
    return json.loads(raw.decode('utf-8'))


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


def _find_nodes_by_name(nodes: list[dict], name: str, root: int | None = None) -> list[int]:
    result = []
    queue = [root] if root is not None else [i for i, n in enumerate(nodes) if n['parent'] == -1]
    while queue:
        ni = queue.pop()
        nd = nodes[ni]
        if nd['name'] == name:
            result.append(ni)
        queue.extend(nd['children'])
    return result


def _find_party_character_nodes(nodes: list[dict]) -> dict[str, int]:
    """Return {display_name: node_index} for each party member in frame 0."""
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
    """
    Walk the character's STATUS nodes and collect any SourceEquippedItem references.
    Returns list of {entity_uuid, status_id}.
    """
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
    """Build entity_uuid → template_uuid from a factory Creators region."""
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
    """
    Build template_uuid → stats_name from an Items factory region.

    Works for both frame 0 (Globals) and frame 3 (level cache).
    Frame 0 uses node name 'Item'; frame 3 uses 'Items' as the sub-container.
    """
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

    # Try the 'Items' sub-container (frame 3 layout)
    items_ni = next(
        (ci for ci in nodes[factory_ni]['children'] if nodes[ci]['name'] == 'Items'),
        None,
    )

    # Frame 0 uses 'Item' nodes directly under the factory children
    candidates: list[int] = []
    if items_ni is not None:
        candidates = nodes[items_ni]['children']
    else:
        # Gather all Item/GameObjects children across factory's children
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
    """
    Return all items with empty Level (not placed in the world).
    Each entry: {stats, template, flags, prev_level}.
    """
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
# Report formatting
# ---------------------------------------------------------------------------

def _fmt_class(cls: dict) -> str:
    main = cls.get('Main', '')
    sub = cls.get('Sub', '')
    return f'{main} / {sub}' if sub else main


def build_report(save_path: str) -> str:
    lines = []
    w = lines.append

    w(f'BG3 Save File Report')
    w(f'Source: {save_path}')
    w('=' * 72)

    frames = _extract_frames(save_path)

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

    # ---- Characters -------------------------------------------------------
    w('')
    w('━' * 72)
    w('PARTY CHARACTERS')
    w('━' * 72)

    party_info = info.get('Active Party', {}).get('Characters', [])

    # Parse Globals (frame 0) for status-based equipped items
    frame0_data = _decomp_frame(frames[0])
    nodes0 = parse_lsof(frame0_data)

    party_nodes = _find_party_character_nodes(nodes0)
    entity_to_template0 = _build_entity_template_map(nodes0, 'Items')

    # Build template→stats from Globals (frame 0) first; frame 3 fills the gaps
    template_to_stats0 = _build_template_stats_map(nodes0)

    # Parse level cache (frame 3) for item stats names and inventory list
    frame3_data = _decomp_frame(frames[3])
    nodes3 = parse_lsof(frame3_data)
    template_to_stats3 = _build_template_stats_map(nodes3)

    # Merged lookup: frame 0 takes priority (equipped items are there)
    template_to_stats = {**template_to_stats3, **template_to_stats0}

    for i, char_info in enumerate(party_info):
        classes   = char_info.get('Classes', [])
        level     = char_info.get('Level', '?')
        origin    = char_info.get('Origin', 'Generic')
        race      = char_info.get('Race', '?')
        xp        = char_info.get('Experience Points (Total)', None)
        subregion = char_info.get('Subregion', '')

        # Best display name: Origin field or "Maia (player)" for Generic
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

        # Spells: not available without LSMF ECS parsing
        w(f'    Spells    : [see LIMITS note below]')

        # Equipped items from status effects
        char_ni = party_nodes.get(display_name)
        if char_ni is not None:
            equipped = _collect_status_equipped_items(nodes0, char_ni)
            if equipped:
                w(f'    Equipped (passive-granting items only):')
                seen = set()
                for e in equipped:
                    tmpl = entity_to_template0.get(e['entity'], '')
                    stats_name = template_to_stats.get(tmpl, '')
                    item_label = stats_name if stats_name else (tmpl if tmpl else e['entity'])
                    key = (e['status_id'], item_label)
                    if key not in seen:
                        seen.add(key)
                        w(f'      – {item_label}  (status: {e["status_id"]})')
            else:
                w(f'    Equipped (passive-granting items only): none detected')
        else:
            w(f'    Equipped (passive-granting items only): character node not found')

    # ---- Inventory --------------------------------------------------------
    w('')
    w('━' * 72)
    w('PARTY INVENTORY  (items not placed in the world)')
    w('Note: item ownership (which character holds each item) requires')
    w('      parsing the ECS blob and is not available here.')
    w('━' * 72)

    inv = _collect_inventory_items(nodes3)
    # Sort and deduplicate by stats name
    from collections import Counter
    counts = Counter(item['stats'] for item in inv if item['stats'])
    w(f'\n  {len(inv)} items total  ({len(counts)} unique types)\n')

    for stats_name, count in sorted(counts.items()):
        marker = ''
        # Rough categorisation
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
        w(f'  {qty:4s} {stats_name:55s} {cat}')

    # ---- Limits note ------------------------------------------------------
    w('')
    w('━' * 72)
    w('LIMITS')
    w('━' * 72)
    w('''
  Spell selections, complete equipment slots (weapon/shield/ring/amulet/armour
  by slot), and per-character inventory ownership all live inside the NewAge
  ECS binary blob (LSMF format, attribute type ScratchBuffer in lslib).
  lslib itself treats this blob as opaque bytes; decoding it requires
  reimplementing the full ECS component reader from lslib/bg3se source.

  The "Equipped" section above only shows items whose on-equip passive creates
  a STATUS node on the character – a subset of all equipped gear.
''')

    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        sys.exit('usage: bg3_save_reader.py <save.lsv> [output.txt]')

    save_path = sys.argv[1]
    out_path  = sys.argv[2] if len(sys.argv) > 2 else None

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
