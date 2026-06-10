#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "zstandard",
#     "lz4",
# ]
# ///
"""
bg3_save_reader.py  –  Extract character and item info from a BG3 .lsv save file.

Usage:
    uv run bg3_save_reader.py [save.lsv] [output.txt] [flags]
    # or, if dependencies are already installed:
    python3 bg3_save_reader.py [save.lsv] [output.txt] [flags]

Default output: party characters with race, class, level, spells/abilities,
and equipped gear.  Additional sections are opt-in:

    --save-info     save metadata (name, date, mods, …)
    --quests        quest and story state from the Osiris DB (adds ~1-2 s)
    --carried       each character's carried inventory
    --all-items     full item list for the current level
    --limits        known limitations note
    --verbose / -v  show internal names in parentheses after display names
    --thumbnail PATH / -t PATH
                    extract the load-screen thumbnail (1280×720 WebP) to PATH

If save.lsv is omitted, the most recently modified save is auto-detected
(override the search root with BG3_SAVE_DIR).  If output.txt is omitted the
report is printed to stdout.

Dependencies (zstandard, lz4) are declared in the inline script metadata above
(PEP 723), so `uv run` installs them automatically in an ephemeral environment.

Display names
-------------
  Internal item and spell names are resolved to "Display Name (INTERNAL_NAME)"
  using the installed game data (root templates + english.loca + spell stat
  files).  Set BG3_DATA_DIR to point at the game's Data directory; otherwise
  the game install is auto-detected at the usual Steam paths.  Without a game
  install every name is shown in its raw internal form.

Known limitations
-----------------
  Equipment slot is derived from item stats (the save stores no explicit
  ItemSlot field); Ring vs Ring 2 is recovered from container ordering.
  Spell books are read exactly from the save's ECS blob; if two party members
  share an identical class/subclass/level build, their books cannot be told
  apart and a class-based heuristic is used for those members.
  See LIMITS.md for full details.
"""

import argparse
import datetime
import glob
import hashlib
import io
import json
import os
import re
import struct
import sys
from collections import Counter
from functools import lru_cache
from typing import Any, TypedDict, cast

import lz4.block
import lz4.frame
import zstandard as zstd


class Node(TypedDict):
    name: str
    parent: int
    children: list[int]
    attrs: dict[str, Any]

# ---------------------------------------------------------------------------
# LSPK / LSOF low-level helpers
# ---------------------------------------------------------------------------

def extract_frames(path: str) -> dict[str, bytes]:
    """Read a .lsv save file and return its named frames.

    Keys for fixed-purpose entries:
      'Globals.lsf'    — world state (party, items, LSMF blob)
      'meta.lsf'       — save metadata (leader name, mods, timestamps)
      'thumbnail'      — load-screen WebP image (filename varies per save)
      'SaveInfo.json'  — save info JSON
      'StorySave.bin'  — Osiris story-state database
      'LevelCache/…'   — one key per level-cache file, using its LSPK name
    """
    with open(path, 'rb') as fh:
        data = fh.read()
    flist = lspk_filelist(io.BytesIO(data))
    sorted_entries = sorted(flist.items(), key=lambda kv: kv[1][0])
    raw_frames = [data[off:off + sod] for _, (off, _p, _f, sod, _u) in sorted_entries]
    names = [n for n, _ in sorted_entries]
    return normalize_named_frames(raw_frames, names)


def normalize_named_frames(raw_frames: list[bytes], names: list[str]) -> dict[str, bytes]:
    """Map named LSPK manifest entries to a dict keyed by LSPK name.

    The only normalisation applied is to the thumbnail entry, whose filename
    includes the save name and therefore varies per save (e.g. QuickSave_242.WebP).
    Everything else is stored under its actual LSPK name.
    """
    result: dict[str, bytes] = {}
    for name, frame in zip(names, raw_frames, strict=True):
        if name.lower().endswith('.webp'):
            result['thumbnail'] = frame
        else:
            result[name] = frame
    return result


def decomp_frame(raw: bytes) -> bytes:
    return zstd.ZstdDecompressor().decompress(raw)


def decomp_section(raw: bytes, disk: int, unc: int, flags: int, chunked: bool) -> bytes:
    if disk == 0 and unc == 0:
        return b''
    if disk == 0:
        return raw[:unc]
    m = flags & 0x0F
    if m == 0:
        return raw[:disk]
    if m == 2:
        if chunked:
            return lz4.frame.decompress(raw[:disk])
        return lz4.block.decompress(raw[:disk], uncompressed_size=unc)
    raise ValueError(f'unknown compression mode {m}')


def parse_string_table(data: bytes) -> list[list[str]]:
    names, pos = [], 0
    (n,) = struct.unpack_from('<I', data, pos)
    pos += 4
    for _ in range(n):
        chain = []
        names.append(chain)
        (ns,) = struct.unpack_from('<H', data, pos)
        pos += 2
        for _ in range(ns):
            (slen,) = struct.unpack_from('<H', data, pos)
            pos += 2
            chain.append(data[pos:pos + slen].decode('utf-8', 'replace'))
            pos += slen
    return names


def lkp(names: list[list[str]], nh: int) -> str:
    try:
        return names[nh >> 16][nh & 0xFFFF]
    except IndexError:
        return f'?{nh:08x}'


def guid_le_str(x: bytes) -> str:
    """Canonical UUID string for a 16-byte fully little-endian BG3 GUID.

    Equivalent to swapping the byte pairs at positions 8–15 and rendering
    via UUID(bytes_le=…), but ~3× faster (no UUID object construction).
    """
    h = x.hex()
    return (f'{h[6:8]}{h[4:6]}{h[2:4]}{h[0:2]}-{h[10:12]}{h[8:10]}-'
            f'{h[14:16]}{h[12:14]}-{h[18:20]}{h[16:18]}-'
            f'{h[22:24]}{h[20:22]}{h[26:28]}{h[24:26]}{h[30:32]}{h[28:30]}')


S_I = struct.Struct('<i')

# LSF attribute type IDs that hold strings:
# String/WString/LSString/LSWString/Path/FixedString
STRING_TIDS = frozenset((20, 21, 22, 23, 29, 30))

# Fixed-size scalar type IDs → precompiled Struct.
# 2/3: uint16/int16  4/5: int32/uint32  6: float  24: uint64
# 26/32: int64 (32 is an alias used in some versions)
SCALAR_STRUCTS = {
    2: struct.Struct('<H'), 3: struct.Struct('<h'),
    4: S_I, 5: struct.Struct('<I'),
    6: struct.Struct('<f'),
    24: struct.Struct('<Q'), 26: struct.Struct('<q'), 32: struct.Struct('<q'),
}
S_VEC3 = struct.Struct('<fff')


def read_val(val_data: bytes, off: int, tid: int, length: int):
    # LSF attribute type IDs as defined in the Larian LSLib source.
    try:
        if tid in STRING_TIDS:
            return val_data[off:off + length - 1].decode('utf-8', 'replace').rstrip('\x00')
        sc = SCALAR_STRUCTS.get(tid)
        if sc is not None:
            return sc.unpack_from(val_data, off)[0]
        if tid == 28:  # TranslatedString: 2-byte version + 4-byte string length prefix
            hlen = S_I.unpack_from(val_data, off + 2)[0]
            return val_data[off + 6:off + 6 + hlen - 1].decode('utf-8', 'replace').rstrip('\x00')
        if tid == 31:  # guid (16-byte fully little-endian UUID)
            return guid_le_str(val_data[off:off + 16])
        if tid == 1:   # uint8
            return val_data[off]
        if tid == 19:  # bool
            return bool(val_data[off])
        if tid == 12:  # vec3 (three packed floats: x, y, z world position)
            return S_VEC3.unpack_from(val_data, off)
        if tid == 25:  # ScratchBuffer (opaque byte blob, e.g. LSMF ECS data)
            return val_data[off:off + length]
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
    # V3 (16-byte) node entries are used ONLY when MetadataFormat == 1
    # (KeysAndAdjacency). Two known false signals to avoid:
    #   mfmt=2 (_merged.lsf): has no keys section — not V3.
    #   mfmt=0 with non-empty keys section (save frames 2/4/5): also not V3.
    # The keys-section sizes (_ku/_kd) are unreliable; mfmt==1 is the correct test.
    has_keys = (mfmt == 1)

    # A section with sizeOnDisk == 0 is stored uncompressed; its on-disk byte
    # count is then the uncompressed size.  (Save frames are compressed, so
    # disk > 0; the game's root-template _merged.lsf files are uncompressed.)
    str_n = str_disk or str_unc
    nod_n = nod_disk or nod_unc
    att_n = att_disk or att_unc
    val_n = val_disk or val_unc

    pos = 64
    str_raw = data[pos:pos + str_n]
    pos += str_n
    nod_raw = data[pos:pos + nod_n]
    pos += nod_n
    att_raw = data[pos:pos + att_n]
    pos += att_n
    val_raw = data[pos:pos + val_n]

    str_data = decomp_section(str_raw, str_disk, str_unc, cflags, False)
    nod_data = decomp_section(nod_raw, nod_disk, nod_unc, cflags, chunked)
    att_data = decomp_section(att_raw, att_disk, att_unc, cflags, chunked)
    val_data = decomp_section(val_raw, val_disk, val_unc, cflags, chunked)

    names = parse_string_table(str_data)
    node_size = 16 if has_keys else 12
    num_nodes = len(nod_data) // node_size

    # Node entries: name-handle (u32), first-attr (u32), parent (i32)
    # [, keys (u32) when V3].  Only the trailing whole entries are parsed.
    node_struct = struct.Struct('<I4xi4x' if has_keys else '<I4xi')
    nodes: list[Node] = [
        {'name': lkp(names, nh), 'parent': par, 'children': [], 'attrs': {}}
        for nh, par in node_struct.iter_unpack(nod_data[:num_nodes * node_size])
    ]

    for i, nd in enumerate(nodes):
        if 0 <= nd['parent'] < num_nodes:
            nodes[nd['parent']]['children'].append(i)

    # Attribute entries: name-handle (u32), type-and-length (u32), node (i32).
    # Attribute names repeat heavily, so the handle→name lookup is memoized.
    name_cache: dict[int, str] = {}
    data_off = 0
    for nh, tl, ni in struct.Struct('<IIi').iter_unpack(att_data[:len(att_data) // 12 * 12]):
        tid = tl & 0x3F
        length = tl >> 6
        val = read_val(val_data, data_off, tid, length)
        if val is not None and ni < num_nodes:
            aname = name_cache.get(nh)
            if aname is None:
                aname = name_cache[nh] = lkp(names, nh)
            nodes[ni]['attrs'][aname] = val
        data_off += length

    return cast(list[dict], nodes)


# ---------------------------------------------------------------------------
# SaveInfo.json
# ---------------------------------------------------------------------------

def parse_info_json(frames: dict[str, bytes]) -> dict:
    raw = decomp_frame(frames['SaveInfo.json'])
    return json.loads(raw.decode('utf-8'))


# ---------------------------------------------------------------------------
# MetaData  (meta.lsf in the LSPK)
# ---------------------------------------------------------------------------

def parse_metadata(frames: dict[str, bytes]) -> dict:
    """Parse meta.lsf (LSOF MetaData) and return a dict of useful fields.

    Returns:
        save_time           int  — wall-clock save time (Unix epoch seconds)
        save_game_id        int  — save slot number (e.g. 242)
        save_game_type      int  — save type code (1 = QuickSave, observed once)
        game_id             str  — campaign identity UUID
        game_session_id     str  — session identity UUID
        leader_name         str  — party leader's name
        seed                int  — RNG seed
        modded              bool — True when any non-base modules are present
        has_unofficial_mods bool — True when BG3 itself flags the save as
                                   unofficially modded (UI/cosmetic mods leave
                                   this False; gameplay-altering mods set it —
                                   one-sample observation, may not be universal)
        user_mods           list[dict]  — user-installed mods (base game
                                          modules like GustavX excluded);
                                          each entry has 'name' and 'folder'
        all_mods            list[dict]  — all ModuleShortDesc entries including
                                          base game modules
    """
    data = decomp_frame(frames['meta.lsf'])
    nodes = parse_lsof(data)

    # Node 0 is the bare 'MetaData' root (no attrs); node 1 is the child that
    # carries all attributes.  Find the child with the attrs rather than relying
    # on a hard-coded index.
    meta_attrs: dict = {}
    for nd in nodes:
        if nd['name'] == 'MetaData' and nd['attrs']:
            meta_attrs = nd['attrs']
            break

    # Mod list: each ModuleShortDesc child of the Mods node.
    # Note: the parsed UUID field in ModuleShortDesc has a different byte order
    # from entity GUIDs and cannot be used as a canonical mod identifier.
    # The Folder string (e.g. "ImpUI_26922ba9-6018-5252-075d-7ff2ba6ed879")
    # embeds the canonical mod UUID for user mods; use Name+Folder for identity.
    BASE_MODULES = {'GustavX', 'Shared', 'SharedDev', 'Gustav', 'Halflings',
                    'Origins', 'Honour', 'DiceSet01', 'DiceSet02', 'DiceSet03',
                    'DiceSet04', 'DiceSet05', 'DiceSet06', 'DiceSet07'}

    all_mods: list[dict] = []
    for nd in nodes:
        if nd['name'] == 'ModuleShortDesc':
            name = nd['attrs'].get('Name', '')
            folder = nd['attrs'].get('Folder', '')
            if name or folder:
                all_mods.append({'name': name, 'folder': folder})

    user_mods = [m for m in all_mods if m['name'] not in BASE_MODULES]

    return {
        'save_time':           meta_attrs.get('SaveTime'),
        'save_game_id':        meta_attrs.get('SaveGameID'),
        'save_game_type':      meta_attrs.get('SaveGameType'),
        'game_id':             meta_attrs.get('GameID', ''),
        'game_session_id':     meta_attrs.get('GameSessionID', ''),
        'leader_name':         meta_attrs.get('LeaderName', ''),
        'seed':                meta_attrs.get('Seed'),
        'modded':              bool(meta_attrs.get('Modded', False)),
        'has_unofficial_mods': bool(meta_attrs.get('HasUnofficialMods', False)),
        'user_mods':           user_mods,
        'all_mods':            all_mods,
    }


# Thumbnail extractor  (thumbnail / *.WebP in the LSPK)
# ---------------------------------------------------------------------------

def extract_thumbnail(frames: dict[str, bytes], output_path: str) -> tuple[int, int] | None:
    """Decompress the load-screen thumbnail and write it to output_path.

    The frame is a RIFF/WebP image.  Dimensions are parsed from the RIFF chunk
    structure without requiring Pillow or any image library.

    Supported sub-formats (covers all observed saves):
      VP8X (extended WebP) — canvas size at bytes 24-29 of the RIFF file.
      VP8L (lossless WebP) — packed width/height at bytes 21-24.
      VP8  (lossy WebP)    — width/height from the VP8 bitstream header.

    Returns (width, height) as a tuple, or None if the format is unrecognised.
    """
    data = decomp_frame(frames['thumbnail'])
    with open(output_path, 'wb') as fh:
        fh.write(data)

    # Verify it's a RIFF/WEBP container
    if len(data) < 20 or data[:4] != b'RIFF' or data[8:12] != b'WEBP':
        return None

    # Walk RIFF chunks to find the first VP8x / VP8L / VP8 chunk
    pos = 12
    while pos + 8 <= len(data):
        chunk_id = data[pos:pos + 4]
        chunk_sz = struct.unpack_from('<I', data, pos + 4)[0]
        if chunk_id == b'VP8X':
            # Extended WebP: 24-bit LE (width-1) at +12, (height-1) at +15
            if pos + 18 <= len(data):
                w = struct.unpack_from('<I', data[pos + 12:pos + 15] + b'\x00')[0] + 1
                h = struct.unpack_from('<I', data[pos + 15:pos + 18] + b'\x00')[0] + 1
                return (w, h)
        elif chunk_id == b'VP8L':
            # Lossless WebP: signature byte 0x2F, then packed 14+14-bit dims
            if pos + 13 <= len(data) and data[pos + 8] == 0x2F:
                v = struct.unpack_from('<I', data, pos + 9)[0]
                return ((v & 0x3FFF) + 1, ((v >> 14) & 0x3FFF) + 1)
        elif (chunk_id == b'VP8 ' and pos + 17 <= len(data)
                and data[pos + 11:pos + 14] == b'\x9d\x01\x2a'):
            # Lossy WebP: start code 9d 01 2a at byte 11 of chunk data
            w = struct.unpack_from('<H', data, pos + 14)[0] & 0x3FFF
            h = struct.unpack_from('<H', data, pos + 16)[0] & 0x3FFF
            return (w, h)
        pos += 8 + chunk_sz + (chunk_sz % 2)

    return None


# Osiris story-engine state  (frame 9)
# ---------------------------------------------------------------------------
#
# Frame 9 is a ~47 MB flat binary produced by the Osiris scripting engine
# (the BG3 story system).  It contains the full rule/goal/database state.
# The format is version 1.15 (0x010f).  All strings after the file header
# are XOR'd with 0xAD byte-by-byte (null-terminated).
#
# Useful story state lives in the Databases section: each named database is
# a collection of "facts" (rows of typed values) set by Osiris scripts.
# Key databases:
#   DB_QuestIsAccepted(quest_id) — quest has been started/accepted (a superset
#       of quests in progress *and* already-closed quests)
#   DB_QuestIsClosed(quest_id)   — quest is resolved (completed or failed;
#       no separate failed-quest DB exists in this file)
#   DB_GlobalFlag(flag_guid)     — global story-state flags (1034 in test save)
#
# Quest state derivation:
#   in progress = DB_QuestIsAccepted ∖ DB_QuestIsClosed
#   closed      = DB_QuestIsClosed
#
# Goals have a Flags byte; observed values:
#   0x00 = active/default
#   0x02 = child goal (per LSLib Goal.h)
#   0x07 = completed/done goal (60 goals in test save)
#
# Parse order is fixed — sections must be consumed sequentially:
#   Header → Types → Enums → DivObjects → Functions → Nodes →
#   Adapters → Databases → Goals → GlobalActions
#
# References:
#   LSLib/LS/Story/Story.cs, Goal.cs, Value.cs, DataNode.cs, Rule.cs, etc.
#   bg3se/BG3Extender/Osiris/OsirisExtender.h

# Osiris version constants (version word = (major<<8)|minor)
OSI_VER_SCRAMBLE    = 0x0104
OSI_VER_ADD_QUERY   = 0x0106
OSI_VER_TYPE_ALIASES = 0x0109
OSI_VER_ENUMS       = 0x010d
OSI_VER_VALUE_FLAGS = 0x010e

# Osiris node-type IDs
OSI_NODE_DATABASE  = 1
OSI_NODE_PROC      = 2
OSI_NODE_DIV_QUERY = 3
OSI_NODE_AND       = 4
OSI_NODE_NOT_AND   = 5
OSI_NODE_REL_OP    = 6
OSI_NODE_RULE      = 7
OSI_NODE_INT_QUERY = 8
OSI_NODE_USER_QUERY = 9


class OsiReader:
    """Sequential binary reader for the Osiris save format."""

    def __init__(self, data: bytes, ver: int, short_type_ids: bool,
                 type_aliases: dict | None = None):
        self.data = data
        self.pos = 0
        self.ver = ver
        self.short_type_ids = short_type_ids
        self.scramble = 0xAD if ver >= OSI_VER_SCRAMBLE else 0x00
        self.type_aliases = type_aliases or {}

    def remaining(self) -> int:
        return len(self.data) - self.pos

    def u8(self) -> int:
        v = self.data[self.pos]
        self.pos += 1
        return v

    def i8(self) -> int:
        v = struct.unpack_from('b', self.data, self.pos)[0]
        self.pos += 1
        return v

    def u16(self) -> int:
        v = struct.unpack_from('<H', self.data, self.pos)[0]
        self.pos += 2
        return v

    def u32(self) -> int:
        v = struct.unpack_from('<I', self.data, self.pos)[0]
        self.pos += 4
        return v

    def i32(self) -> int:
        v = struct.unpack_from('<i', self.data, self.pos)[0]
        self.pos += 4
        return v

    def i64(self) -> int:
        v = struct.unpack_from('<q', self.data, self.pos)[0]
        self.pos += 8
        return v

    def u64(self) -> int:
        v = struct.unpack_from('<Q', self.data, self.pos)[0]
        self.pos += 8
        return v

    def f32(self) -> float:
        v = struct.unpack_from('<f', self.data, self.pos)[0]
        self.pos += 4
        return v

    def bool(self) -> bool:
        v = self.u8()
        if v not in (0, 1):
            raise ValueError(f'Expected bool, got {v} at pos {self.pos - 1}')
        return v == 1

    def string(self) -> str:
        xor = self.scramble
        buf = bytearray()
        while self.pos < len(self.data):
            b = self.data[self.pos] ^ xor
            self.pos += 1
            if b == 0:
                break
            buf.append(b)
        return buf.decode('utf-8', errors='replace')

    def type_id(self) -> int:
        return self.u16() if self.short_type_ids else self.u32()

    def ref_u32(self) -> int:
        return self.u32()


def osi_read_value(rdr: OsiReader) -> dict:
    """Read a typed Value from the Osiris stream."""
    if rdr.ver >= OSI_VER_VALUE_FLAGS:
        rdr.i8()           # index (not needed for database queries)
        flags = rdr.u8()
        if not (flags & 0x08):  # IsValid bit
            return {'is_valid': False, 'value': None}
    d = rdr.u8()  # discriminator byte: ord('0'), ord('1'), or ord('e')
    if d == ord('1'):
        rdr.type_id()
        v = rdr.i32()
        return {'is_valid': True, 'value': v}
    elif d == ord('0'):
        t = rdr.type_id()
        wt = rdr.type_aliases.get(t, t)
        if wt == 0:
            return {'is_valid': True, 'value': None}
        elif wt == 1:
            return {'is_valid': True, 'value': rdr.i32()}
        elif wt == 2:
            return {'is_valid': True, 'value': rdr.i64()}
        elif wt == 3:
            return {'is_valid': True, 'value': rdr.f32()}
        elif wt in (4, 5):
            h = rdr.u8()
            return {'is_valid': True, 'value': rdr.string() if h else None}
        else:
            h = rdr.u8()
            return {'is_valid': True, 'value': rdr.string() if h else None}
    elif d == ord('e'):
        rdr.u16()  # enum type id
        lbl = rdr.string()
        return {'is_valid': True, 'value': lbl}
    else:
        raise ValueError(f'Unknown Osiris value discriminator 0x{d:02x} at pos {rdr.pos - 1}')


def osi_read_typed_value(rdr: OsiReader) -> dict:
    v = osi_read_value(rdr)
    if rdr.ver < OSI_VER_VALUE_FLAGS:
        rdr.bool()  # is_valid
        rdr.bool()  # out_param
        rdr.bool()  # is_a_type
    return v


def osi_read_variable(rdr: OsiReader) -> dict:
    v = osi_read_typed_value(rdr)
    if rdr.ver < OSI_VER_VALUE_FLAGS:
        rdr.i8()    # var_index
        rdr.bool()  # unused
        rdr.bool()  # adapted
    return v


def osi_read_tuple(rdr: OsiReader) -> list:
    count = rdr.u8()
    items = []
    for _ in range(count):
        if rdr.ver >= OSI_VER_VALUE_FLAGS:
            items.append(osi_read_value(rdr))
        else:
            rdr.u8()
            items.append(osi_read_value(rdr))
    return items


def osi_read_node_entry_item(rdr: OsiReader) -> tuple:
    return (rdr.ref_u32(), rdr.u32(), rdr.ref_u32())


def osi_read_call(rdr: OsiReader) -> dict:
    name = rdr.string()
    params = None
    negate = False
    if name:
        has = rdr.u8()
        if has:
            n = rdr.u8()
            params = []
            for _ in range(n):
                if rdr.ver < OSI_VER_VALUE_FLAGS:
                    rdr.u8()
                params.append(osi_read_variable(rdr))
        negate = rdr.bool()
    goal = rdr.i32()
    return {'name': name, 'params': params, 'negate': negate, 'goal_id': goal}


def osi_skip_types(rdr: OsiReader) -> None:
    n = rdr.u32()
    ta: dict = {}
    for _ in range(n):
        rdr.string()
        idx = rdr.u8()
        alias = rdr.u8() if rdr.ver >= OSI_VER_TYPE_ALIASES else 3
        if alias != 0:
            ta[idx] = alias
    rdr.type_aliases = ta


def osi_skip_enums(rdr: OsiReader) -> None:
    n = rdr.u32()
    for _ in range(n):
        rdr.u16()
        ec = rdr.u32()
        for _ in range(ec):
            rdr.string()
            rdr.u64()


def osi_skip_div_objects(rdr: OsiReader) -> None:
    n = rdr.u32()
    for _ in range(n):
        rdr.string()
        rdr.u8()
        rdr.u32()
        rdr.u32()
        rdr.u32()
        rdr.u32()


def osi_skip_functions(rdr: OsiReader) -> None:
    n = rdr.u32()
    for _ in range(n):
        rdr.u32()
        rdr.u32()
        rdr.u32()
        rdr.ref_u32()
        rdr.u8()
        rdr.u32()
        rdr.u32()
        rdr.u32()
        rdr.u32()
        rdr.string()
        ob = rdr.u32()
        for _ in range(ob):
            rdr.u8()
        c = rdr.u8()
        for _ in range(c):
            rdr.type_id()


def osi_read_param_list(rdr: OsiReader) -> list:
    c = rdr.u8()
    return [rdr.type_id() for _ in range(c)]


def osi_read_nodes(rdr: OsiReader) -> dict:
    """Read the Nodes section; returns {db_ref: name} for DatabaseNode/ProcNode entries."""
    n = rdr.u32()
    db_names: dict = {}
    for _ in range(n):
        nt = rdr.u8()
        rdr.u32()                              # node id
        db_ref = rdr.ref_u32()
        nm = rdr.string()
        if nm:
            rdr.u8()                           # param count (present when name non-empty)
        if nm and db_ref:
            db_names[db_ref] = nm
        if nt in (OSI_NODE_DATABASE, OSI_NODE_PROC):
            # DataNode extra: ReferencedBy list
            rc = rdr.u32()
            for _ in range(rc):
                osi_read_node_entry_item(rdr)
        elif nt in (OSI_NODE_DIV_QUERY, OSI_NODE_INT_QUERY, OSI_NODE_USER_QUERY):
            pass
        elif nt in (OSI_NODE_AND, OSI_NODE_NOT_AND):
            osi_read_node_entry_item(rdr)
            rdr.ref_u32()
            rdr.ref_u32()
            rdr.ref_u32()
            rdr.ref_u32()
            rdr.ref_u32()
            osi_read_node_entry_item(rdr)
            rdr.u8()
            rdr.ref_u32()
            osi_read_node_entry_item(rdr)
            rdr.u8()
        elif nt == OSI_NODE_REL_OP:
            osi_read_node_entry_item(rdr)
            rdr.ref_u32()
            rdr.ref_u32()
            rdr.ref_u32()
            osi_read_node_entry_item(rdr)
            rdr.u8()
            rdr.i8()
            rdr.i8()
            osi_read_value(rdr)
            osi_read_value(rdr)
            rdr.i32()
        elif nt == OSI_NODE_RULE:
            osi_read_node_entry_item(rdr)
            rdr.ref_u32()
            rdr.ref_u32()
            rdr.ref_u32()
            osi_read_node_entry_item(rdr)
            rdr.u8()
            cc = rdr.u32()
            for _ in range(cc):
                osi_read_call(rdr)
            vc = rdr.u8()
            for _ in range(vc):
                if rdr.ver < OSI_VER_VALUE_FLAGS:
                    rdr.u8()
                osi_read_variable(rdr)
            rdr.u32()
            if rdr.ver >= OSI_VER_ADD_QUERY:
                rdr.bool()
        else:
            raise ValueError(f'Unknown Osiris node type {nt} at pos {rdr.pos}')
    return db_names


def osi_skip_adapters(rdr: OsiReader) -> None:
    n = rdr.u32()
    for _ in range(n):
        rdr.u32()
        osi_read_tuple(rdr)
        lc = rdr.u8()
        for _ in range(lc):
            rdr.i8()
        mc = rdr.u8()
        for _ in range(mc):
            rdr.u8()
            rdr.u8()


def osi_read_databases(rdr: OsiReader) -> dict:
    """Read the Databases section; returns {db_index: {'facts': [[value, ...], ...]}}."""
    n = rdr.u32()
    dbs: dict = {}
    for _ in range(n):
        idx = rdr.u32()
        osi_read_param_list(rdr)
        fc = rdr.u32()
        facts = []
        for _ in range(fc):
            cc = rdr.u8()
            cols = [osi_read_value(rdr) for _ in range(cc)]
            facts.append(cols)
        dbs[idx] = facts
    return dbs


def osi_read_goals(rdr: OsiReader) -> dict:
    """Read the Goals section; returns {goal_idx: {'name': str, 'flags': int}}."""
    n = rdr.u32()
    goals: dict = {}
    for _ in range(n):
        idx = rdr.u32()
        nm = rdr.string()
        rdr.u8()                               # SubGoalCombination
        pg = rdr.u32()
        for _ in range(pg):
            rdr.ref_u32()
        sg = rdr.u32()
        for _ in range(sg):
            rdr.ref_u32()
        flags = rdr.u8()
        ic = rdr.u32()
        for _ in range(ic):
            osi_read_call(rdr)
        ec = rdr.u32()
        for _ in range(ec):
            osi_read_call(rdr)
        goals[idx] = {'name': nm, 'flags': flags}
    return goals


def parse_osiris(frames: dict[str, bytes]) -> dict | None:
    """Parse frame 9 (Osiris story state) and return useful quest/story data.

    Returns a dict with:
        version        – Osiris version word (int)
        quests_active  – quests in progress: DB_QuestIsAccepted ∖ DB_QuestIsClosed
        quests_closed  – resolved quests: DB_QuestIsClosed (completed or failed;
                         no separate failed-quest DB exists in the save)
        goals_done     – goal names with flags == 0x07 (completed goals)
        global_flags   – first 50 strings from DB_GlobalFlag (story-state flags)

    Returns None on any parse failure so the caller can degrade gracefully.
    The full parse must read all sections in order (Types → Enums → DivObjects →
    Functions → Nodes → Adapters → Databases → Goals → GlobalActions) before the
    Databases section is reachable; this costs ~1–2 s on a typical save.
    """
    try:
        if 'StorySave.bin' not in frames:
            return None
        data = decomp_frame(frames['StorySave.bin'])

        # --- Header ---
        # null byte, then unscrambled version string (NUL-terminated),
        # then major(u8), minor(u8), bigendian(u8?), unused(u8),
        # then (ver>=0x102) 0x80-byte buffer, then (ver>=0x103) u32 debug flags
        pos = 0
        if data[pos] != 0:
            return None
        pos += 1
        while data[pos] != 0:  # skip version string
            pos += 1
        pos += 1                # consume null terminator
        major = data[pos]
        minor = data[pos + 1]
        pos += 4
        ver = (major << 8) | minor
        pos += 0x80             # version buffer
        pos += 4                # debug flags

        rdr = OsiReader(data, ver, short_type_ids=(ver >= OSI_VER_ENUMS))
        rdr.pos = pos

        # --- Parse all sections in mandatory order ---
        osi_skip_types(rdr)
        if ver >= OSI_VER_ENUMS:
            osi_skip_enums(rdr)
        osi_skip_div_objects(rdr)
        osi_skip_functions(rdr)
        db_names = osi_read_nodes(rdr)
        osi_skip_adapters(rdr)
        databases = osi_read_databases(rdr)
        goals = osi_read_goals(rdr)
        # GlobalActions — consume so parse is complete
        n_ga = rdr.u32()
        for _ in range(n_ga):
            osi_read_call(rdr)

        # --- Build name → facts index ---
        name_to_facts: dict = {}
        for db_ref, nm in db_names.items():
            if db_ref in databases:
                name_to_facts[nm] = databases[db_ref]

        def get_single_col_strings(db_name: str) -> list[str]:
            """Return all non-None string values from a single-column database."""
            return [
                str(row[0]['value'])
                for row in name_to_facts.get(db_name, [])
                if row and row[0].get('is_valid') and row[0].get('value') is not None
            ]

        accepted = set(get_single_col_strings('DB_QuestIsAccepted'))
        closed   = set(get_single_col_strings('DB_QuestIsClosed'))
        active   = sorted(accepted - closed)
        closed_l = sorted(closed)

        goals_done = sorted(
            g['name'] for g in goals.values()
            if g['flags'] == 0x07 and g['name']
        )

        global_flags = get_single_col_strings('DB_GlobalFlag')

        return {
            'version':           ver,
            'quests_active':     active,
            'quests_closed':     closed_l,
            'goals_finalized':   goals_done,
            'global_flags':      global_flags[:50],
            'global_flags_total': len(global_flags),
        }

    except Exception:
        return None


# ---------------------------------------------------------------------------
# Spell extraction from LSMF ECS blob
# ---------------------------------------------------------------------------

# Known BG3 spell-ID prefixes (order matters – longest first)
SPELL_PREFIXES = [
    'Teleportation_', 'AspectOfTheBeast_', 'FightingStyle_', 'TotemSpirit_',
    'PactOfThe', 'Projectile_', 'Summon_', 'Target_', 'Shout_', 'Zone_',
    'Rush_', 'Wall_',
]

PREFIX_RE = re.compile(
    r'(?=' + '|'.join(re.escape(p) for p in SPELL_PREFIXES) + r')'
)

# Spell IDs exclusive to each class/subclass (used for attribution)
CLASS_EXCLUSIVE = {
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
UNIVERSAL = {
    'Target_HealingWord', 'Projectile_Jump', 'Target_Dip', 'Shout_Hide',
    'Shout_Dash', 'Target_Help', 'Shout_Disengage', 'Target_MainHandAttack',
    'Target_OffhandAttack', 'Target_UnarmedAttack', 'Target_Topple',
    'Shout_Disengage_CunningAction', 'Shout_Dash_CunningAction',
    'Shout_Hide_BonusAction', 'Target_ShoveThrow_ThrowThrow_ImprovisedWeapon',
    'Shout_MAG_Aid3_Self',
}


def extract_lsmf_blob(nodes: list[dict]) -> bytes | None:
    """Return the raw LSMF ScratchBuffer blob from the NewAge node."""
    for nd in nodes:
        if nd['name'] == 'NewAge' and nd['parent'] == -1:
            return nd['attrs'].get('NewAge')
    return None


def split_spell_string(packed: str) -> list[str]:
    """Split a concatenated BG3 spell-ID string into individual spell IDs."""
    parts = PREFIX_RE.split(packed)
    result = []
    for part in parts:
        part = part.strip('\x00 ')
        if part:
            result.append(part)
    return result


ASCII_RUN_RE = re.compile(rb'[ -~]{30,}')


def extract_spell_strings_from_lsmf(blob: bytes) -> list[str]:
    """
    Find all significant packed spell-ID strings in the LSMF blob.
    Returns the list of all non-trivial ASCII runs that contain spell IDs.
    """
    prefixes = tuple(p.encode() for p in SPELL_PREFIXES)
    return [
        m.group().decode('ascii')
        for m in ASCII_RUN_RE.finditer(blob)
        if any(p in m.group() for p in prefixes)
    ]


CLASS_MAIN_TO_KEY = {
    'Fighter':   'Fighter',
    'Warlock':   'Warlock',
    'Barbarian': 'Barbarian',
    'Cleric':    'Cleric',
    # add more classes here if needed
}


def extract_spells_by_character(
    lsmf_blob: bytes,
    party_info: list[dict],
    player_name: str = 'Player',
) -> dict[str, list[str]]:
    """
    Extract spells from the LSMF blob and attribute them to party members
    using class-based rules.

    Returns a dict mapping display_name → list of spell IDs.
    """
    all_strings = extract_spell_strings_from_lsmf(lsmf_blob)

    # Collect all spell IDs from all runs
    all_spell_ids: set[str] = set()
    for s in all_strings:
        for sid in split_spell_string(s):
            all_spell_ids.add(sid)

    # Build per-character exclusive attribution
    result: dict[str, list[str]] = {}
    assigned: set[str] = set()

    # Map party character display names to their class keys
    char_class_map: dict[str, str] = {}
    for char_info in party_info:
        origin = char_info.get('Origin', 'Generic')
        display_name = origin if origin != 'Generic' else player_name
        classes = char_info.get('Classes', [])
        if classes:
            main_class = classes[0].get('Main', '')
            class_key = CLASS_MAIN_TO_KEY.get(main_class, main_class)
            char_class_map[display_name] = class_key

    # First pass: attribute exclusively owned spells
    for name, class_key in char_class_map.items():
        exclusive = CLASS_EXCLUSIVE.get(class_key, set())
        owned = sorted(all_spell_ids & exclusive)
        result[name] = owned
        assigned |= exclusive

    # Second pass: non-universal spells with no exclusive owner go to a shared/
    # generic bucket (omitted for brevity; future work).

    return result


# ---------------------------------------------------------------------------
# Character extraction from Globals (frame 0)
# ---------------------------------------------------------------------------

PLAYER_CHAR_TEMPLATE = 'f08563b3-748d-4783-837b-b8620bc60b22'

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

# Class / subclass UUIDs from the game's ClassDescriptions.lsx (Shared.pak).
# These are static shipped constants; embedded so exact spell-book attribution
# works without a game install. Used to match LSMF ClassesComponent entries
# against the (Main, Sub) class names in the save's Info.json.
CLASS_UUID_NAMES = {
    'e6a0eb75-7a01-4f40-8563-24ba2615e99b': 'AbjurationSchool',
    'b36d247e-d39f-4ae9-9476-3ec315c55789': 'Ancients',
    'ede4778e-7602-440f-9075-b4bc8dc31cea': 'ArcaneTrickster',
    '733ddf8c-9ec4-4c5a-85e3-c70fd3df3c24': 'Archfey',
    'b53a8061-f31d-4985-adfe-d4d691a918d9': 'Assassin',
    'd8cadb42-0ff9-4049-afaf-e5d78d06a399': 'Barbarian',
    '92cd50b6-eb1b-4824-8adb-853e90c34c90': 'Bard',
    'e668c6f1-5149-4b10-ab7e-3637ed444066': 'BattleMaster',
    '6fd9547d-cc28-400e-bfa9-3a85baa70f24': 'BeastMaster',
    '32eee7d8-1b2f-4de5-b9ee-78fbd286c6ef': 'BerserkerPath',
    '0a01dc6b-ab1a-4c0e-8a5e-4787fe1f2caf': 'Champion',
    '7458da78-34b7-4150-a42f-37197ab04510': 'CircleOfTheLand',
    '3eab0689-e51b-4634-a690-0375d3cb2716': 'CircleOfTheMoon',
    '4b61af6c-4a44-436e-aa0a-0d11a2d6b8ee': 'CircleOfTheSpores',
    '114e7aee-d1d4-4371-8d90-8a2080592faf': 'Cleric',
    '7a3feb8d-dda7-46ec-9029-1f302f537432': 'ConjurationSchool',
    '1c761ad0-6f5f-409e-ac1d-ddf6f85c1fc4': 'Devotion',
    '7577b0e1-a517-4f82-8f72-05a227dc5e88': 'DivinationSchool',
    '36286b0a-26f9-4b4e-9311-fd1404301d20': 'DraconicBloodline',
    '457d0a6e-9da8-4f95-a225-18382f0e94b5': 'Druid',
    'b722614a-303f-411a-bb19-a1882ad1f4cc': 'EldritchKnight',
    '46d31950-6917-444e-ac87-706702825215': 'EnchantmentSchool',
    'c059dca1-c17d-4dce-8260-83ede5070eac': 'EvocationSchool',
    '8866db28-7dda-4fd6-93ed-20eca16314f0': 'Fiend',
    '721dfac3-92d4-41f5-b773-b7072a86232f': 'Fighter',
    '22894c32-54cf-49ea-b366-44bfcf01bb2a': 'FourElements',
    'd5f10e55-84e3-409b-aa64-2098c9550319': 'GloomStalker',
    'e1e4a21f-9405-46ec-81a0-ccc8d58d9736': 'GreatOldOne',
    '0aa1cff9-c45f-4d00-a95b-99a7aa96dd06': 'Hunter',
    '436c9e1a-3a39-48dd-b753-7cee1bd19c00': 'IllusionSchool',
    'ebe18794-b5e1-41c4-befa-4b9d6922b0ec': 'KnowledgeDomain',
    '4b5da2f5-b999-4623-8bff-a63df5560fb3': 'LifeDomain',
    'c54d7591-b305-4f22-b2a7-1bf5c4a3470a': 'LightDomain',
    'd21368ac-c776-465c-9dcf-6123dd52734f': 'LoreCollege',
    'c4598bdb-fc07-40dd-a62c-90cc138bd76f': 'Monk',
    '6dec76d0-df22-411c-8a78-3d6fb843ae50': 'NatureDomain',
    'fbb8347b-20e3-4846-ba91-0552cd12fc5f': 'NecromancySchool',
    '6fb3831e-45d8-4b30-9714-6fe73988921b': 'Oathbreaker',
    '2a5e3097-384c-4d29-8d6e-054fdfd26b80': 'OpenHand',
    'ff4d9497-023c-434a-bd14-82fc367e991c': 'Paladin',
    '36be18ba-23db-4dff-bfa6-ae105ce43144': 'Ranger',
    'e8b1eab0-ef11-40a2-8a0b-cee8d062bf2a': 'Rogue',
    'bf46d73f-d406-4cb8-9a1d-e6e758ca02c7': 'Shadow',
    '784001e2-c96d-4153-beb6-2adbef5abc92': 'Sorcerer',
    'd379fdae-b401-4731-8d50-277c73919ae3': 'StormSorcery',
    'c4bd5252-d68a-4330-9431-5e8ab24c5f29': 'SwordsCollege',
    '89bacf1b-8f15-4972-ada7-bf59c7c78441': 'TempestDomain',
    '32c7b8df-a6ec-4848-a9db-c0dce781beb9': 'Thief',
    '2e585948-d775-451d-b58b-15b75321d11e': 'TotemWarriorPath',
    'a12f2924-30b4-4185-9db9-2c5b383ff449': 'TransmutationSchool',
    'f013d01b-3310-43f7-81bf-a51130442b5e': 'TrickeryDomain',
    '2b46330d-0ada-4eb5-a131-3d250a41ca6a': 'ValorCollege',
    '3cc3d397-c47d-4966-87ae-88827f73f645': 'Vengeance',
    'b9ccf90e-b35b-4b73-b896-8ed2d32ae8c6': 'WarDomain',
    'b4225a4b-4bbe-4d97-9e3c-4719dbd1487c': 'Warlock',
    '14374d37-a70e-41a8-9dc5-85a23f8b5dd2': 'WildMagic',
    'd6bf00fc-3518-4d63-ba8b-03532c1abc4d': 'WildMagicPath',
    'a865965f-501b-46e9-9eaa-7748e8c04d09': 'Wizard',
}

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
        if tmpl == PLAYER_CHAR_TEMPLATE:
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
        (i for i, nd in enumerate(nodes) if nd['name'] == 'Items' and nd['parent'] == -1), None)
    if items_root is None:
        return {}
    factory_ni = nodes[items_root]['children'][0] if nodes[items_root]['children'] else None
    if factory_ni is None:
        return {}
    factory_children = nodes[factory_ni]['children']
    creators_ni = next((ci for ci in factory_children if nodes[ci]['name'] == 'Creators'), None)
    items_ni    = next((ci for ci in factory_children if nodes[ci]['name'] == 'Items'),    None)
    if creators_ni is None or items_ni is None:
        return {}
    result: dict[tuple, str] = {}
    # The format keeps Creators and Items parallel; tolerate a corrupt tail.
    for creator_ci, item_ci in zip(
        nodes[creators_ni]['children'], nodes[items_ni]['children'], strict=False,
    ):
        entity    = nodes[creator_ci]['attrs'].get('Entity', '')
        translate = nodes[item_ci]['attrs'].get('Translate')
        stats     = nodes[item_ci]['attrs'].get('Stats', '')
        if entity and translate and stats:
            result[(translate, stats)] = entity
    return result


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
NON_EQUIP_PREFIXES = (
    'OBJ_', 'CONS_', 'ALCH_', 'FOOD_', 'SCR_', 'SCROLL_', 'BOOK_',
    'LOOT_', 'KEY_', 'PUZ_', 'PLT_', 'TItem_', 'GOLD_',
)
NON_EQUIP_SUBSTR = (
    '_Camp_', 'Underwear', 'Keychain', 'GoldPile',
    'Backpack', 'AlchemyPouch', 'CampSupplies',
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


def collect_items_by_position(node_lists: list[list[dict]],
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
            if prev is None or (
                isinstance(flags, int) and (flags & EQUIPPED_FLAG_BIT)
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
            isinstance(flags, int)
            and (flags & EQUIPPED_FLAG_BIT)
            and is_equipment_type(stats)
        )
        if signalled:
            equipped.append((stats, guid))
        elif is_equipment_type(stats):
            undetermined.append((stats, guid))
        else:
            carried.append((stats, guid))
    return sorted(set(equipped)), sorted(set(carried)), sorted(set(undetermined))


# Items owned as inventory loot by a character. Direction relative to "worn"
# varies by save: a genuinely equipped item may be present (save 246 gloves)
# or absent (save 286 weapons), so this is only a weak tiebreaker.
OWNED_AS_LOOT_COMP = 'game.v0.OwnedAsLootComponent'
# Items that are (or were) in a weapon slot. For Flags-equipped items this
# supports genuineness; for ECS-promoted items it marks a stale leftover.
WIELDED_COMP = 'game.inventory.v0.WieldedComponent'
# Physics disabled because the item is attached to a character in the world
# (worn/held visual), absent on items sitting inside an inventory.
GRAVITY_DISABLED_COMP = 'game.gravity.v0.GravityDisabledComponent'


@lru_cache(maxsize=1)
def scan_lsmf_blob(blob: bytes) -> tuple | None:
    """Parse the LSMF header, component descriptors, and ownerlist table.

    Returns (comp_descs, records) where comp_descs[i] = (name, elem_size,
    row_count, data_offset) for component descriptor i, and records is a tuple
    of (comp_idx, start, entity_count) for every valid ownerlist record found.
    Returns None on any parse failure.

    The ownerlist scan walks the whole blob and dominates LSMF parse time, so
    the result is cached (size 1): membership counting, per-component row
    extraction, and --inspect all share one scan of the same blob.
    """
    # LSMF blob header (absolute offsets):
    #   blob[8:16]   = unknown (ignored)
    #   blob[16:24]  = dir_off    (raw directory pointer; actual names-blob start = dir_off + 48)
    #   blob[24:32]  = names_size (byte length of the component-names section)
    #   blob[32:36]  = desc_table_rel (descriptor-table offset, relative to names_off)
    #   blob[36:38]  = entry_count (number of component descriptors)
    #   names_off    = dir_off + 48  (start of the names blob / component-type directory)
    # Each 48-byte ComponentDesc at desc_base + i*48:
    #   [0:8]   name_offset (into names section)
    #   [8:16]  name_length
    #   [16:24] hash (not decoded)
    #   [24:28] elem_size
    #   [28:32] flags (not decoded)
    #   [32:40] row_count
    #   [40:48] data_offset (absolute byte offset of this component's column data)
    BLOB_HDR_BASE = 48  # all absolute offsets in the blob are stored as (actual - 48)
    try:
        L = len(blob)
        _, dir_off, names_size = struct.unpack_from('<QQQ', blob, 8)
        names_off = dir_off + BLOB_HDR_BASE
        desc_table_rel = struct.unpack_from('<I', blob, 32)[0]
        entry_count = struct.unpack_from('<H', blob, 36)[0]
        if not (0 < names_off < L and 0 < entry_count < 2000):
            return None
        names_sec = blob[names_off:names_off + names_size]
        desc_base = names_off + desc_table_rel

        comp_descs: list[tuple[str, int, int, int]] = []
        rows_by_comp: dict[int, int] = {}
        for i in range(entry_count):
            base = desc_base + i * 48
            if base + 48 > L:
                break
            name_off, name_len, _ = struct.unpack_from('<QQQ', blob, base)
            elem_size = struct.unpack_from('<I', blob, base + 24)[0]
            row_count, data_offset = struct.unpack_from('<QQ', blob, base + 32)
            rows_by_comp[i] = row_count
            name = ''
            if 0 < name_len < 200:
                name = names_sec[name_off:name_off + name_len].decode('utf-8', 'replace')
            comp_descs.append((name, elem_size, row_count, data_offset))

        # Ownerlist region: each 32-byte record is {start, end, comp_idx, entity_count}.
        # Records sit in a contiguous table; sentinel entries have comp=0xFFFF…FFFF
        # or start==end.
        unpack_rec = struct.Struct('<QQQQ').unpack_from

        def valid_record(p: int):
            start, end, comp, ec = unpack_rec(blob, p)
            if (comp < entry_count and ec > 0 and rows_by_comp.get(comp, -1) == ec
                    and end > start and (end - start) == ec * 4
                    and end <= L and start < L):
                return comp, start, ec
            return None

        # 4-byte scan to find candidate positions (captures all valid records plus
        # some false positives at non-32-aligned offsets).  Viewed as uint32
        # words, a record at word i has its comp/ec high dwords at i+5 / i+7;
        # entry_count < 2000, so both must be zero — that single-compare
        # prefilter rejects almost every offset before the full validation.
        valid_pos: list[int] = []
        words = memoryview(blob)[:L - L % 4].cast('I')
        rows_for = rows_by_comp.get
        for i in range((L - 32) // 4 + 1):
            if words[i + 5] == 0 and words[i + 7] == 0:
                comp = words[i + 4]
                ec = words[i + 6]
                if (comp < entry_count and ec > 0 and rows_for(comp, -1) == ec
                        and valid_record(i * 4) is not None):
                    valid_pos.append(i * 4)

        # Identify the real ownerlist table as the densest chain of valid positions
        # spaced by a multiple of 32 (non-32-aligned entries are false positives from
        # the scan above and are skipped; the real table is a tight 32-byte-stride array).
        anchor, best_count = 0, 0
        for vi in range(len(valid_pos)):
            count, last = 1, valid_pos[vi]
            for vj in range(vi + 1, len(valid_pos)):
                d = valid_pos[vj] - last
                if d % 32 == 0 and d <= 32 * 40:
                    count += 1
                    last = valid_pos[vj]
                elif d > 32 * 40:
                    break
            if count > best_count:
                anchor, best_count = valid_pos[vi], count

        # Walk the table from anchor in 32-byte steps, collecting every record.
        records: list[tuple[int, int, int]] = []
        if best_count > 0:
            p, misses = anchor, 0
            while p + 32 <= L and misses < 4:
                rec = valid_record(p)
                if rec is not None:
                    records.append(rec)
                    misses = 0
                else:
                    comp = unpack_rec(blob, p)[2]
                    misses = 0 if comp == 0xFFFFFFFFFFFFFFFF else misses + 1
                p += 32

        return tuple(comp_descs), tuple(records)

    except Exception:
        return None


def parse_lsmf_membership(
    blob: bytes,
) -> tuple[dict[str, list[int]], dict[int, int]] | None:
    """Extract per-entity component membership counts from the LSMF ECS blob.

    Returns (guid_to_rows, membership_count) where:
      guid_to_rows      — entity GUID string → list of EntityId row indices
      membership_count  — entity row index → number of component ownerlists it appears in

    Equipped items remain materialised in the ECS world (~35–41 memberships).
    Items moved to a backpack dematerialise (~3–6 memberships).
    Returns None on any parse failure.
    """
    scanned = scan_lsmf_blob(blob)
    if scanned is None:
        return None
    comp_descs, records = scanned

    eid_off = eid_rows = 0
    for name, _elem, row_count, data_offset in comp_descs:
        if name == 'core.v0.EntityId':
            eid_off, eid_rows = data_offset, row_count
    if not eid_rows or eid_off + eid_rows * 16 > len(blob):
        return None

    guid_to_rows: dict[str, list[int]] = {}
    for i in range(eid_rows):
        off = eid_off + i * 16
        g = guid_le_str(blob[off:off + 16])
        guid_to_rows.setdefault(g, []).append(i)

    membership_count: Counter[int] = Counter()
    try:
        for _comp, start, ec in records:
            membership_count.update(struct.unpack_from(f'<{ec}I', blob, start))
    except Exception:
        return None

    return guid_to_rows, membership_count


def parse_lsmf_component_rows(
    blob: bytes,
    comp_names: tuple[str, ...] | None = None,
) -> dict[str, frozenset[int]]:
    """Return ECS row indices for each named LSMF component.

    The result maps each requested component name to the frozenset of row
    indices belonging to it (an empty frozenset if the component is absent).
    With comp_names=None, every component with an ownerlist is extracted.
    Any parse failure yields empty frozensets for all requested names.
    """
    result: dict[str, set[int]] = {name: set() for name in comp_names or ()}
    scanned = scan_lsmf_blob(blob)
    if scanned is None:
        return {name: frozenset() for name in result}
    comp_descs, records = scanned

    try:
        for comp, start, ec in records:
            name = comp_descs[comp][0] if comp < len(comp_descs) else ''
            if not name or (comp_names is not None and name not in result):
                continue
            result.setdefault(name, set()).update(
                struct.unpack_from(f'<{ec}I', blob, start))
    except Exception:
        return {name: frozenset() for name in comp_names or ()}

    return {name: frozenset(rows) for name, rows in result.items()}


# Heap/string-pool pointers inside LSMF component rows are stored as
# (absolute blob offset - 48), the same convention as the header offsets.
LSMF_HEAP_BASE = 48


def lsmf_component_index(blob: bytes) -> dict[str, tuple]:
    """Map component name -> (elem_size, row_count, data_offset, owner_rows).

    owner_rows is the component's ownerlist as a tuple of entity-row indices,
    in data-row order (the k-th data row belongs to owner_rows[k]); empty for
    components without an ownerlist.
    """
    scanned = scan_lsmf_blob(blob)
    if scanned is None:
        return {}
    comp_descs, records = scanned
    owners: dict[int, tuple] = {}
    for comp, start, ec in records:
        try:
            owners[comp] = struct.unpack_from(f'<{ec}I', blob, start)
        except struct.error:
            continue
    out: dict[str, tuple] = {}
    for i, (name, elem, rows, off) in enumerate(comp_descs):
        if name and name not in out:
            out[name] = (elem, rows, off, owners.get(i, ()))
    return out


def parse_lsmf_spellbooks(blob: bytes) -> dict[int, list[str]]:
    """Extract every spell book: entity row -> ordered list of spell IDs.

    game.spell.v3.SpellBookComponent rows are {begin, end} byte ranges into
    game.spell.v3.SpellData (72-byte rows). SpellData field 6 points at a
    game.spell.v0.SpellId row, which carries (string pointer, length) into the
    blob's concatenated spell-ID pool. When an entity appears in multiple
    ownerlist epochs, the largest book wins.
    """
    idx = lsmf_component_index(blob)
    sb = idx.get('game.spell.v3.SpellBookComponent')
    sd = idx.get('game.spell.v3.SpellData')
    si = idx.get('game.spell.v0.SpellId')
    if not (sb and sd and si):
        return {}
    sb_elem, sb_rows, sb_off, sb_owners = sb
    sd_elem, sd_rows, sd_off, _ = sd
    si_elem, si_rows, si_off, _ = si
    if sb_elem != 16 or sd_elem < 56 or si_elem != 24:
        return {}
    L = len(blob)
    sd_lo, sd_hi = sd_off, sd_off + sd_rows * sd_elem
    si_lo, si_hi = si_off, si_off + si_rows * si_elem

    def spell_id_name(row: int) -> str | None:
        # Observed record shapes: {meta_ptr, str_ptr, len-packed} and
        # {str_ptr, len-packed, source_ptr}, where len-packed may carry a
        # generation counter in its high dword. Try both (pointer, length)
        # pairings and accept the first that yields printable ASCII.
        a, b, c = struct.unpack_from('<QQQ', blob, si_off + row * si_elem)
        for ptr, ln in ((b, c & 0xFFFFFFFF), (a, b & 0xFFFFFFFF)):
            p0 = ptr + LSMF_HEAP_BASE
            if not (0 < ln <= 128 and 0 < p0 <= L - ln):
                continue
            s = blob[p0:p0 + ln]
            if all(0x20 <= ch < 0x7F for ch in s):
                return s.decode('ascii')
        return None

    books: dict[int, list[str]] = {}
    for k, ent in enumerate(sb_owners):
        if k >= sb_rows:
            break
        begin, end = struct.unpack_from('<QQ', blob, sb_off + k * sb_elem)
        if not (sd_lo <= begin <= end <= sd_hi):
            continue
        names = []
        for r in range((begin - sd_lo) // sd_elem, (end - sd_lo) // sd_elem):
            v = struct.unpack_from('<Q', blob, sd_off + r * sd_elem + 48)[0]
            if si_lo <= v < si_hi:
                nm = spell_id_name((v - si_lo) // si_elem)
                if nm:
                    names.append(nm)
        if names and len(names) > len(books.get(ent, ())):
            books[ent] = names
    return books


def parse_lsmf_classes(blob: bytes) -> dict[int, tuple]:
    """Extract class progressions: entity row -> ((class, subclass, level), …).

    game.stats.v0.ClassesComponent rows are {begin, end} byte ranges into the
    auxiliary heap, holding 40-byte entries {class GUID, subclass GUID, u64
    level}. GUIDs are returned in canonical string form.
    """
    idx = lsmf_component_index(blob)
    cc = idx.get('game.stats.v0.ClassesComponent')
    if not cc:
        return {}
    elem, rows, off, owners = cc
    if elem != 16:
        return {}
    L = len(blob)
    out: dict[int, tuple] = {}
    for k, ent in enumerate(owners):
        if k >= rows:
            break
        begin, end = struct.unpack_from('<QQ', blob, off + k * elem)
        size = end - begin
        if not (0 < size <= 40 * 16 and size % 40 == 0):
            continue
        p0 = begin + LSMF_HEAP_BASE
        if p0 + size > L:
            continue
        entries = []
        for i in range(size // 40):
            base = p0 + i * 40
            cls = guid_le_str(blob[base:base + 16])
            sub = guid_le_str(blob[base + 16:base + 32])
            lvl = struct.unpack_from('<Q', blob, base + 32)[0]
            if lvl > 30:
                entries = []
                break
            entries.append((cls, sub, lvl))
        if entries:
            out[ent] = tuple(entries)
    return out


def parse_lsmf_container_positions(blob: bytes) -> dict[int, int]:
    """Map entity row -> its game.inventory.v0.ContainerSlotData row index.

    Each contained/worn item has one ContainerSlotData entry {ptr -> item
    EntityId row, u32 position, u32 generation}. The row order mirrors the
    in-game ordering of same-slot items: of two worn rings, the one with the
    earlier ContainerSlotData row sits in the first (upper) ring slot
    (ground-truth verified against QuickSave_291).
    """
    idx = lsmf_component_index(blob)
    csd = idx.get('game.inventory.v0.ContainerSlotData')
    eid = idx.get('core.v0.EntityId')
    if not (csd and eid):
        return {}
    csd_elem, csd_rows, csd_off, _ = csd
    _eid_elem, eid_rows, eid_off, _ = eid
    out: dict[int, int] = {}
    for r in range(csd_rows):
        ptr = struct.unpack_from('<Q', blob, csd_off + r * csd_elem)[0]
        rel = ptr - eid_off
        if ptr and rel >= 0 and rel % 16 == 0 and rel // 16 < eid_rows:
            out.setdefault(rel // 16, r)
    return out


def invert_entity_template_map(
    entity_to_template: dict[str, str],
) -> dict[str, list[str]]:
    """Reverse entity_guid→template_guid to template_guid→[entity_guids]."""
    result: dict[str, list[str]] = {}
    for entity_guid, tmpl_guid in entity_to_template.items():
        result.setdefault(tmpl_guid, []).append(entity_guid)
    return result


def ecs_resolve_equipped(
    undetermined: list[tuple],
    template_to_instances: dict[str, list[str]],
    guid_to_rows: dict[str, list[int]],
    membership_count: dict[int, int],
    *,
    threshold: int = 15,
    stats_to_entity: dict[str, str] | None = None,
    wielded_rows: frozenset[int] | None = None,
) -> tuple[list[tuple], list[tuple], list[tuple]]:
    """Classify undetermined items via ECS component membership counts.

    Equipped items (materialised in the ECS world) have ~35–41 component
    memberships; items moved to a backpack dematerialise to ~3–6.
    A threshold of 15 sits cleanly between the two groups.

    When stats_to_entity is provided, the per-instance entity GUID is used
    directly instead of looking up all level instances of the template, which
    prevents MC contamination from unrelated instances of the same item type.

    When wielded_rows is provided, items whose entity row is in
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
        in_wielded = wielded_rows is not None and any(r in wielded_rows for r in rows)
        if max_mc >= threshold and not in_wielded:
            now_equipped.append((stats, tmpl_guid))
        else:
            now_carried.append((stats, tmpl_guid))
    return now_equipped, now_carried, still_undetermined


SLOT_CAPACITY: dict[str, int] = {'Ring': 2}

# Report display order for equipped items, mirroring the in-game panel
# (armour top-to-bottom, then weapons, then instrument/vanity).
SLOT_DISPLAY_ORDER: dict[str, int] = {name: i for i, name in enumerate((
    'Helmet', 'Cloak', 'Breast', 'Gloves', 'Boots', 'Amulet', 'Ring',
    'Melee Main Weapon', 'Melee Offhand Weapon',
    'Ranged Main Weapon', 'Ranged Offhand Weapon',
    'MusicalInstrument', 'Underwear', 'VanityBody', 'VanityBoots',
))}


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
) -> tuple[list[tuple], list[tuple], list[tuple]]:
    """Resolve cases where more items are signalled for a slot than it can hold.

    Priority: Flags-signalled items beat ECS-only items for the same slot.
    When multiple Flags items compete for the same slot, tiebreaker priority is:
      1. active on-equip status (status_equipped) — truly wielded item
      2. WieldedComponent or GravityDisabledComponent — physically attached
         to the character (in a weapon slot / worn-visual physics override)
      3. OwnedAsLootComponent — direction is save-dependent, but when neither
         item has a physical-attachment signal the in-loot item is the worn one
      4. per-instance membership count (higher MC wins)
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

    slot_candidates: dict[str, list[tuple]] = {}
    no_slot_flags: list[tuple] = []
    no_slot_ecs:   list[tuple] = []

    for stats, guid in flags_equipped:
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
    kept_ecs:   list[tuple] = list(no_slot_ecs)
    demoted:    list[tuple] = []

    def flags_sort_key(sg: tuple) -> tuple:
        attached = in_rows(sg[0], wielded_rows) or in_rows(sg[0], gravity_disabled_rows)
        return (
            0 if (status_equipped and sg[0] in status_equipped) else 1,
            0 if attached else 1,
            0 if in_rows(sg[0], owned_as_loot_rows) else 1,
            -get_mc(sg[0]),
        )

    for slot, candidates in slot_candidates.items():
        capacity = SLOT_CAPACITY.get(slot, 1)
        if len(candidates) <= capacity:
            for stats, guid, signal in candidates:
                (kept_flags if signal == 'flags' else kept_ecs).append((stats, guid))
            continue
        flags_cands = [(s, g) for s, g, sig in candidates if sig == 'flags']
        ecs_cands   = [(s, g) for s, g, sig in candidates if sig == 'ecs']
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
            s in two_handed_stats for s, _ in kept_flags
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

LSPK_FILE_ENTRY = 272  # bytes per file-list entry in LSPK v18

# Root-template _merged.lsf files, in load order (later overrides earlier).
ROOT_TEMPLATE_FILES = [
    ('Shared.pak',  'Public/Shared/RootTemplates/_merged.lsf'),
    ('Shared.pak',  'Public/SharedDev/RootTemplates/_merged.lsf'),
    ('Gustav.pak',  'Public/GustavDev/RootTemplates/_merged.lsf'),
    ('Gustav.pak',  'Public/Gustav/RootTemplates/_merged.lsf'),
    ('Gustav.pak',  'Public/Honour/RootTemplates/_merged.lsf'),
    ('GustavX.pak', 'Public/GustavX/RootTemplates/_merged.lsf'),
]
LOCA_PAK = 'Localization/English.pak'
LOCA_FILE = 'Localization/English/english.loca'

STAT_ITEM_PAKS = ['Shared.pak', 'Gustav.pak', 'GustavX.pak']
STAT_ITEM_FILE_RE = re.compile(r'/Stats/Generated/Data/(?:Armor|Weapon|Object)\.txt$')

# Bump when the resolver logic changes so a stale cache is not silently reused.
DISPLAYNAME_SCHEMA_VERSION = 7


def find_game_data_dir() -> str | None:
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


def lspk_filelist(fh) -> dict[str, tuple]:
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
    raw = lz4.block.decompress(comp, uncompressed_size=num_files * LSPK_FILE_ENTRY)
    out = {}
    for i in range(num_files):
        b = i * LSPK_FILE_ENTRY
        name = raw[b:b + 256].split(b'\x00')[0].decode('latin1')
        off_lo, off_hi, part, flags, sod, unc = struct.unpack_from('<IHBBII', raw, b + 256)
        out[name] = ((off_lo | (off_hi << 32)), part, flags, sod, unc)
    return out


def lspk_extract(pak_path: str, name: str) -> bytes:
    """Extract and decompress a single file from an LSPK v18 package."""
    with open(pak_path, 'rb') as fh:
        flist = lspk_filelist(fh)
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


def parse_loca(blob: bytes) -> dict[str, str]:
    """Parse an english.loca blob into {handle: text}."""
    sig, num, texts_off = struct.unpack_from('<4sII', blob, 0)
    if sig != b'LOCA':
        raise ValueError(f'not a LOCA file ({sig!r})')
    pos = 12
    entries = []
    for _ in range(num):
        key = blob[pos:pos + 64].split(b'\x00')[0].decode('latin1')
        pos += 64
        pos += 2  # version (uint16)
        length = struct.unpack_from('<I', blob, pos)[0]
        pos += 4
        entries.append((key, length))
    out = {}
    tp = texts_off
    for key, length in entries:
        out[key] = blob[tp:tp + length - 1].decode('utf-8', 'replace').strip()
        tp += length
    return out


def cache_path(data_dir: str) -> str:
    sig_parts = []
    for pak in {p for p, _ in ROOT_TEMPLATE_FILES} | {LOCA_PAK}:
        fp = os.path.join(data_dir, pak)
        try:
            st = os.stat(fp)
            sig_parts.append(f'{pak}:{st.st_mtime_ns}:{st.st_size}')
        except OSError:
            pass
    sig_parts.append(f'schema:{DISPLAYNAME_SCHEMA_VERSION}')
    sig = hashlib.md5('|'.join(sorted(sig_parts)).encode()).hexdigest()[:16]
    cdir = os.path.join(
        os.environ.get('XDG_CACHE_HOME', os.path.expanduser('~/.cache')),
        'bg3-savefile-parser',
    )
    os.makedirs(cdir, exist_ok=True)
    return os.path.join(cdir, f'displaynames-{sig}.json')


def build_displayname_maps(
    data_dir: str,
) -> tuple[
    dict[str, str], dict[str, str], dict[str, str],
    frozenset[str], dict[str, str], frozenset[str],
]:
    """Build display-name and item-stat maps from installed game data.

    Returns (guid->name, stats->name, spell_id->name, object_type_stats, stats_to_slot,
    two_handed_stats).

    Results are cached under XDG_CACHE_HOME keyed on the source paks' mtime/size,
    so the ~1 s parse only happens after a game update.
    """
    cache = cache_path(data_dir)
    try:
        with open(cache, encoding='utf-8') as fh:
            data = json.load(fh)
        return (
            data['guid'],
            data['stats'],
            data.get('spells', {}),
            frozenset(data.get('object_types', [])),
            data.get('stats_slots', {}),
            frozenset(data.get('two_handed', [])),
        )
    except (OSError, ValueError, KeyError):
        pass

    handle_to_text = parse_loca(lspk_extract(os.path.join(data_dir, LOCA_PAK), LOCA_FILE))

    guid_handle: dict[str, str] = {}   # template GUID -> own DisplayName handle ('' if none)
    guid_parent: dict[str, str] = {}   # template GUID -> ParentTemplateId
    stats_guids: dict[str, list[str]] = {}  # stats name -> template GUIDs, in file order
    for pak, name in ROOT_TEMPLATE_FILES:
        try:
            nodes = parse_lsof(lspk_extract(os.path.join(data_dir, pak), name))
        except (OSError, KeyError, ValueError):
            continue
        for nd in nodes:
            if nd['name'] != 'GameObjects':
                continue
            key = nd['attrs'].get('MapKey')
            if not key:
                continue
            guid_handle[key] = nd['attrs'].get('DisplayName', '')
            guid_parent[key] = nd['attrs'].get('ParentTemplateId', '')
            stats = nd['attrs'].get('Stats', '')
            if stats:
                stats_guids.setdefault(stats, []).append(key)

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

    # Stats names resolve through the same ParentTemplateId chain: templates
    # like UNI_SCL_MoonlanternWithPixie carry no DisplayName of their own and
    # inherit it from their base template.
    stats_name: dict[str, str] = {}
    for stats, guids in stats_guids.items():
        for g in guids:
            h = resolve_guid_handle(g)
            txt = handle_to_text.get(h) if h else None
            if txt:
                stats_name[stats] = txt
                break

    # Spell stat files: Spell_*.txt from all item paks. Upcast variants and
    # item-granted spells inherit DisplayName through the `using` chain, so
    # entries without their own handle resolve via their parents.
    spell_raw: dict[str, dict] = {}
    for pak_name in STAT_ITEM_PAKS:
        pak_path = os.path.join(data_dir, pak_name)
        try:
            with open(pak_path, 'rb') as fh:
                flist = lspk_filelist(fh)
            spell_files = sorted(
                k for k in flist if re.search(r'/Stats/Generated/Data/Spell_.*\.txt$', k)
            )
        except (OSError, ValueError):
            continue
        for sf in spell_files:
            try:
                text = lspk_extract(pak_path, sf).decode('utf-8', errors='replace')
            except (OSError, KeyError, ValueError):
                continue
            for block_match in re.finditer(r'^new entry "([^"]+)"', text, re.MULTILINE):
                entry_name = block_match.group(1)
                start = block_match.end()
                next_block = re.search(r'^new entry', text[start:], re.MULTILINE)
                block_text = text[start : start + (next_block.start() if next_block else len(text))]
                dn_m = re.search(r'data "DisplayName" "([^";]+)', block_text)
                using_m = re.search(r'^using "([^"]+)"', block_text, re.MULTILINE)
                using = using_m.group(1) if using_m and using_m.group(1) != entry_name else None
                prev = spell_raw.get(entry_name)
                if prev is None:
                    spell_raw[entry_name] = {
                        'display': dn_m.group(1) if dn_m else None,
                        'using': using,
                    }
                else:
                    if prev['display'] is None and dn_m:
                        prev['display'] = dn_m.group(1)
                    if using:
                        prev['using'] = using

    spell_name: dict[str, str] = {}
    for entry_name in spell_raw:
        cur: str | None = entry_name
        seen: set[str] = set()
        while cur and cur not in seen:
            seen.add(cur)
            info = spell_raw.get(cur)
            if info is None:
                break
            if info['display']:
                txt = handle_to_text.get(info['display'])
                if txt:
                    spell_name[entry_name] = txt
                break
            cur = info['using']

    # Item stat files: Armor.txt / Weapon.txt / Object.txt from item paks.
    # Used to (a) identify Object-type items that cannot be equipped, and
    # (b) resolve the equipment slot for each item (following the `using` chain).
    stat_raw: dict[str, dict] = {}
    for pak_name in STAT_ITEM_PAKS:
        pak_path = os.path.join(data_dir, pak_name)
        try:
            with open(pak_path, 'rb') as fh:
                flist2 = lspk_filelist(fh)
            item_files = sorted(k for k in flist2 if STAT_ITEM_FILE_RE.search(k))
            for sf in item_files:
                text = lspk_extract(pak_path, sf).decode('utf-8', errors='replace')
                for bm in re.finditer(r'^new entry "([^"]+)"', text, re.MULTILINE):
                    name = bm.group(1)
                    start = bm.end()
                    nb = re.search(r'^new entry', text[start:], re.MULTILINE)
                    block = text[start: start + (nb.start() if nb else len(text))]
                    type_m  = re.search(r'^type "([^"]+)"',                  block, re.MULTILINE)
                    using_m = re.search(r'^using "([^"]+)"',                  block, re.MULTILINE)
                    slot_m  = re.search(r'^data "Slot" "([^"]+)"',            block, re.MULTILINE)
                    wp_m    = re.search(r'^data "Weapon Properties" "([^"]+)"', block, re.MULTILINE)
                    new_using = using_m.group(1) if using_m else None
                    prev = stat_raw.get(name)
                    if prev is None:
                        stat_raw[name] = {
                            'type':        type_m.group(1) if type_m else None,
                            'using':       new_using,
                            'slot':        slot_m.group(1) if slot_m else None,
                            'weapon_props': wp_m.group(1) if wp_m else None,
                        }
                    else:
                        # Honour-mode patches use `using "SameName"` for value-only
                        # overrides; skip self-referential `using` to avoid loops.
                        if new_using and new_using != name:
                            prev['using'] = new_using
                        if type_m:
                            prev['type'] = type_m.group(1)
                        if slot_m:
                            prev['slot'] = slot_m.group(1)
                        if wp_m:
                            prev['weapon_props'] = wp_m.group(1)
        except (OSError, KeyError, ValueError):
            pass

    object_type_stats_list = [n for n, d in stat_raw.items() if d.get('type') == 'Object']

    def resolve_slot(name: str, depth: int = 0) -> str | None:
        if depth > 24:
            return None
        entry = stat_raw.get(name)
        if not entry:
            return None
        if entry['slot']:
            return entry['slot']
        parent = entry.get('using')
        if parent and parent != name:
            return resolve_slot(parent, depth + 1)
        return None

    stats_to_slot: dict[str, str] = {}
    for name in stat_raw:
        s = resolve_slot(name)
        if s:
            stats_to_slot[name] = s

    def resolve_weapon_props(name: str, depth: int = 0) -> str | None:
        if depth > 24:
            return None
        entry = stat_raw.get(name)
        if not entry:
            return None
        if entry.get('weapon_props'):
            return entry['weapon_props']
        parent = entry.get('using')
        if parent and parent != name:
            return resolve_weapon_props(parent, depth + 1)
        return None

    two_handed_stats_list = [
        n for n in stat_raw
        if 'Twohanded' in (resolve_weapon_props(n) or '')
    ]

    try:
        with open(cache, 'w', encoding='utf-8') as fh:
            json.dump({
                'guid': guid_name,
                'stats': stats_name,
                'spells': spell_name,
                'object_types': object_type_stats_list,
                'stats_slots': stats_to_slot,
                'two_handed': two_handed_stats_list,
            }, fh)
    except OSError:
        pass
    return (
        guid_name, stats_name, spell_name,
        frozenset(object_type_stats_list), stats_to_slot,
        frozenset(two_handed_stats_list),
    )


class DisplayNames:
    """Resolves internal item/spell identifiers to 'Display Name (INTERNAL_NAME)'."""

    def __init__(
        self,
        guid_name:         dict[str, str],
        stats_name:        dict[str, str],
        spell_name:        dict[str, str]   | None = None,
        object_type_stats: frozenset[str]   | None = None,
        stats_to_slot:     dict[str, str]   | None = None,
        two_handed_stats:  frozenset[str]   | None = None,
    ):
        self._guid   = guid_name
        self._stats  = stats_name
        self._spells = spell_name or {}
        self.object_type_stats: frozenset[str] = object_type_stats or frozenset()
        self.stats_to_slot:     dict[str, str] = stats_to_slot     or {}
        self.two_handed_stats:  frozenset[str] = two_handed_stats  or frozenset()
        self.verbose = False  # set to True to append (INTERNAL_NAME) after display names

    @classmethod
    def load(cls) -> 'DisplayNames':
        data_dir = find_game_data_dir()
        if not data_dir:
            return cls({}, {}, {})
        try:
            return cls(*build_displayname_maps(data_dir))
        except Exception:  # never let display-name resolution break the report
            return cls({}, {}, {})

    @property
    def available(self) -> bool:
        return bool(self._guid or self._stats)

    def name_for(self, stats: str, guid: str = '') -> str | None:
        """Return the display name for an item, preferring the precise GUID."""
        if guid and guid in self._guid:
            return self._guid[guid]
        return self._stats.get(stats)

    def fmt(self, stats: str, guid: str = '') -> str:
        dn = self.name_for(stats, guid)
        if dn:
            return f'{dn} ({stats})' if self.verbose else dn
        return stats

    def fmt_spell(self, spell_id: str) -> str:
        dn = self._spells.get(spell_id)
        if dn:
            return f'{dn} ({spell_id})' if self.verbose else dn
        return spell_id


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
    # The heuristic string-pool attribution remains as a fallback.
    spell_map: dict[str, list[str]] = {}
    spellbooks: dict[int, list[str]] = {}
    entity_classes: dict[int, tuple] = {}
    if lsmf_blob:
        spell_map = extract_spells_by_character(lsmf_blob, party_info, player_display_name)
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
    # AND level apart; those members fall back to the heuristic.
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

        # Spells — exact book when the entity match succeeds, else heuristic
        book = exact_spellbook(char_info)
        if book is not None:
            distinct = set(book) - COMMON_ACTION_SPELLS
            # Upcast variants share a display name; show each rendering once.
            shown = sorted({dn.fmt_spell(sid) for sid in distinct})
            hidden = len(set(book)) - len(distinct)
            w(f'    Spells/Abilities ({len(shown)}; +{hidden} basic actions):')
            for line in shown:
                w(f'      – {line}')
        elif (spells := spell_map.get(display_name, [])):
            w(f'    Spells/Abilities ({len(spells)}, heuristic):')
            for sid in sorted(spells):
                w(f'      – {dn.fmt_spell(sid)}')
        else:
            w('    Spells/Abilities : (class-specific list not found)')

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
  identical build, their books cannot be told apart; those members fall back
  to a class-based heuristic (marked "heuristic" in the report).

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


# ---------------------------------------------------------------------------
# Save-file auto-detection
# ---------------------------------------------------------------------------
#
# Saves live at  <profiles>/<Profile>/Savegames/Story/<Char>-<id>__<Name>/<Name>.lsv
# under a platform-specific BG3 profiles directory.  With no save given on the
# command line, the most recently modified .lsv across the known locations is
# used (override the search root with BG3_SAVE_DIR).

def candidate_profile_dirs() -> list[str]:
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


def glob_saves(roots: list[str], patterns: tuple[str, ...]) -> set[str]:
    """Return every .lsv path matching any pattern under any existing root."""
    found: set[str] = set()
    for root in roots:
        if not os.path.isdir(root):
            continue
        for pat in patterns:
            found.update(glob.glob(os.path.join(root, pat)))
    return found


def find_latest_save() -> str | None:
    """Return the path of the most recently modified .lsv, or None if none found."""
    env = os.environ.get('BG3_SAVE_DIR')
    roots = [env] if env else candidate_profile_dirs()
    # A root may be a PlayerProfiles dir, a Savegames/Story dir, or a single
    # save folder; these patterns match a .lsv at each of those depths.
    patterns = (
        '*/Savegames/Story/*/*.lsv', 'Savegames/Story/*/*.lsv',
        'Story/*/*.lsv', '*/*.lsv', '*.lsv',
    )
    found = glob_saves(roots, patterns)
    if not found:
        return None
    return max(found, key=os.path.getmtime)


def find_save_by_token(token: str) -> str | None:
    """Find the most recently modified save whose name ends with _{token}.

    Accepts a bare number ("268") or a full save name ("QuickSave_268").
    Searches the same roots as find_latest_save().
    """
    env = os.environ.get('BG3_SAVE_DIR')
    roots = [env] if env else candidate_profile_dirs()
    patterns = (
        f'*/Savegames/Story/*_{token}/*_{token}.lsv',
        f'Savegames/Story/*_{token}/*_{token}.lsv',
        f'Story/*_{token}/*_{token}.lsv',
        f'*_{token}/*_{token}.lsv',
        f'*_{token}.lsv',
    )
    found = glob_saves(roots, patterns)
    if not found:
        return None
    return max(found, key=os.path.getmtime)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description='Extract character info from a BG3 .lsv save file.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            'By default only party characters are shown (race, class, level,\n'
            'spells/abilities, and equipped gear).  Use the flags below to\n'
            'include additional sections.'
        ),
    )
    ap.add_argument('save', nargs='?', metavar='save.lsv',
                    help='path to save file (auto-detected if omitted)')
    ap.add_argument('output', nargs='?', metavar='output.txt',
                    help='write report to file (default: stdout)')
    ap.add_argument('--save-info', action='store_true',
                    help='include save metadata (name, date, mods, …)')
    ap.add_argument('--quests', action='store_true',
                    help='include quest and story state (Osiris; adds ~1-2 s)')
    ap.add_argument('--carried', action='store_true',
                    help="include each character's carried inventory")
    ap.add_argument('--all-items', action='store_true',
                    help='include full item list for the current level')
    ap.add_argument('--limits', action='store_true',
                    help='include known limitations note')
    ap.add_argument('--verbose', '-v', action='store_true',
                    help='show internal names in parentheses after display names')
    ap.add_argument('--thumbnail', '-t', metavar='PATH',
                    help="write the save's thumbnail image to PATH")
    ap.add_argument('--inspect', metavar='NAME',
                    help='show classification signals and ECS components for party items '
                         'whose internal stats name contains NAME (case-insensitive)')
    opts = ap.parse_args()

    save_path = opts.save
    if not save_path:
        save_path = find_latest_save()
        if not save_path:
            ap.error('no save given and none auto-detected; '
                     'pass a .lsv path or set BG3_SAVE_DIR')
        print(f'No save specified; using most recent: {save_path}', file=sys.stderr)
    elif not os.path.exists(save_path):
        resolved = find_save_by_token(save_path)
        if not resolved:
            ap.error(f'no save found matching {save_path!r}')
        save_path = resolved
        print(f'Resolved {opts.save!r} → {save_path}', file=sys.stderr)

    frames = extract_frames(save_path)

    if opts.thumbnail:
        dims = extract_thumbnail(frames, opts.thumbnail)
        if dims:
            print(f'Thumbnail written to {opts.thumbnail} ({dims[0]}x{dims[1]})', file=sys.stderr)
        else:
            print(f'Thumbnail written to {opts.thumbnail} (dimensions unknown)', file=sys.stderr)

    print(f'Parsing {save_path} …', file=sys.stderr)
    report = build_report(save_path, frames, opts)

    if opts.output:
        with open(opts.output, 'w', encoding='utf-8') as fh:
            fh.write(report)
        print(f'Report written to {opts.output}', file=sys.stderr)
    else:
        print(report)


if __name__ == '__main__':
    main()
