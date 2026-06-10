"""LSPK package container: save frames, SaveInfo.json, meta.lsf, thumbnail."""

import io
import json
import struct

import lz4.block
import lz4.frame
import zstandard as zstd

from .lsf import decomp_frame, parse_lsof

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
