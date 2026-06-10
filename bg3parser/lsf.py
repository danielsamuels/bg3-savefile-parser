"""LSF / LSOF binary resource format: nodes, attributes, value decoding."""

import struct
from typing import Any, TypedDict, cast

import lz4.block
import lz4.frame
import zstandard as zstd


class Node(TypedDict):
    name: str
    parent: int
    children: list[int]
    attrs: dict[str, Any]


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
