"""The LSMF ECS blob ("NewAge"): components, spell books, containers."""

import struct
from collections import Counter

from .lsf import guid_le_str

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
        names_sec = blob[names_off : names_off + names_size]
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
                name = names_sec[name_off : name_off + name_len].decode('utf-8', 'replace')
            comp_descs.append((name, elem_size, row_count, data_offset))

        # Ownerlist region: each 32-byte record is {start, end, comp_idx, entity_count}.
        # Records sit in a contiguous table; sentinel entries have comp=0xFFFF…FFFF
        # or start==end.
        unpack_rec = struct.Struct('<QQQQ').unpack_from

        def valid_record(p: int):
            start, end, comp, ec = unpack_rec(blob, p)
            if (
                comp < entry_count
                and ec > 0
                and rows_by_comp.get(comp, -1) == ec
                and end > start
                and (end - start) == ec * 4
                and end <= L
                and start < L
            ):
                return comp, start, ec
            return None

        # 4-byte scan to find candidate positions (captures all valid records plus
        # some false positives at non-32-aligned offsets).  Viewed as uint32
        # words, a record at word i has its comp/ec high dwords at i+5 / i+7;
        # entry_count < 2000, so both must be zero — that single-compare
        # prefilter rejects almost every offset before the full validation.
        valid_pos: list[int] = []
        words = memoryview(blob)[: L - L % 4].cast('I')
        rows_for = rows_by_comp.get
        for i in range((L - 32) // 4 + 1):
            if words[i + 5] == 0 and words[i + 7] == 0:
                comp = words[i + 4]
                ec = words[i + 6]
                if (
                    comp < entry_count
                    and ec > 0
                    and rows_for(comp, -1) == ec
                    and valid_record(i * 4) is not None
                ):
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
        g = guid_le_str(blob[off : off + 16])
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
            result.setdefault(name, set()).update(struct.unpack_from(f'<{ec}I', blob, start))
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
            s = blob[p0 : p0 + ln]
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
            cls = guid_le_str(blob[base : base + 16])
            sub = guid_le_str(blob[base + 16 : base + 32])
            lvl = struct.unpack_from('<Q', blob, base + 32)[0]
            if lvl > 30:
                entries = []
                break
            entries.append((cls, sub, lvl))
        if entries:
            out[ent] = tuple(entries)
    return out


def parse_lsmf_prepared_spells(blob: bytes) -> dict[int, list[tuple[str, int, str]]]:
    """Extract prepared spells: entity row -> [(spell ID, source type, source GUID), ...].

    game.spell.v0.SpellBookPrepares rows are 80 bytes (five {begin, end} heap
    ranges); the fourth range is the PreparedSpells array of 24-byte
    SpellMetaId records {string pointer, length, pad, detail pointer}. The
    detail record holds a pointer into the game.spell.v0.ESourceType value
    pool (the SpellSourceType: 0/1/2 progression = class/subclass/race,
    3 = item boost, 6 = base spell set, 7 = weapon attack) followed by the
    ProgressionSource GUID.

    The prepares ownerlist is written in an older entity numbering than the
    spell-book/classes ownerlists (rows shift as entities are created), so
    rows are realigned by the dominant per-save delta between each prepares
    row and the unique spell book containing its spell names.
    """
    idx = lsmf_component_index(blob)
    sp = idx.get('game.spell.v0.SpellBookPrepares')
    et = idx.get('game.spell.v0.ESourceType')
    if not (sp and et):
        return {}
    elem, rows, off, owners = sp
    if elem != 80:
        return {}
    L = len(blob)

    e_elem, e_rows, e_off, _ = et
    source_pool = {
        e_off + r * e_elem - LSMF_HEAP_BASE: struct.unpack_from('<Q', blob, e_off + r * e_elem)[0]
        for r in range(e_rows)
        if e_off + (r + 1) * e_elem <= L
    }

    def heap_str(ptr: int, ln: int) -> str | None:
        p0 = ptr + LSMF_HEAP_BASE
        if not (0 < ln <= 128 and 0 < p0 <= L - ln):
            return None
        raw = blob[p0 : p0 + ln]
        return raw.decode('ascii') if all(0x20 <= ch < 0x7F for ch in raw) else None

    raw_map: dict[int, list[tuple[str, int, str]]] = {}
    for k, ent in enumerate(owners):
        if k >= rows:
            break
        begin, end = struct.unpack_from('<QQ', blob, off + k * elem + 48)
        size = end - begin
        if not (0 <= begin < end <= L and size % 24 == 0 and size <= 24 * 4096):
            continue
        entries = []
        for ptr in range(begin + LSMF_HEAP_BASE, end + LSMF_HEAP_BASE, 24):
            sptr, ln, _pad, detail = struct.unpack_from('<QIIQ', blob, ptr)
            name = heap_str(sptr, ln)
            if name is None:
                continue
            source_type, source_guid = -1, ''
            d0 = detail + LSMF_HEAP_BASE
            if 0 < d0 <= L - 24:
                eptr = struct.unpack_from('<Q', blob, d0)[0]
                if eptr in source_pool:
                    source_type = source_pool[eptr]
                    source_guid = guid_le_str(blob[d0 + 8 : d0 + 24])
            entries.append((name, source_type, source_guid))
        if entries and len(entries) > len(raw_map.get(ent, ())):
            raw_map[ent] = entries

    # Realign the stale prepares numbering against the spell-book numbering.
    books = parse_lsmf_spellbooks(blob)
    book_sets = {e: set(v) for e, v in books.items()}
    deltas: Counter = Counter()
    for ent, entries in raw_map.items():
        names = {n for n, _st, _g in entries}
        if len(names) < 8:
            continue
        cands = [be for be, bs in book_sets.items() if len(names & bs) >= 0.85 * len(names)]
        if len(cands) == 1:
            deltas[cands[0] - ent] += 1
    if not deltas:
        return {}
    delta, votes = deltas.most_common(1)[0]
    if votes < 3 or votes < 0.5 * sum(deltas.values()):
        delta = 0
    return {ent + delta: entries for ent, entries in raw_map.items()}


def parse_lsmf_container_positions(blob: bytes) -> dict[int, int]:
    """Map entity row -> its game.inventory.v0.ContainerSlotData row index.

    Each contained/worn item has one ContainerSlotData entry {ptr -> item
    EntityId row, u32 position, u32 generation}. The row order mirrors the
    in-game ordering of same-slot items: of two worn rings, the one with the
    earlier ContainerSlotData row sits in the first (upper) ring slot
    (ground-truth verified against QuickSave_291).
    """
    out: dict[int, int] = {}
    for ent, rows in parse_lsmf_all_container_positions(blob).items():
        out[ent] = rows[0]
    return out


def parse_lsmf_all_container_positions(blob: bytes) -> dict[int, tuple[int, ...]]:
    """Map entity row -> every ContainerSlotData row index referencing it.

    An item that has moved between containers can retain stale entries from
    earlier saves alongside its current one, so a single entity may appear in
    several rows. Row indices are returned in ascending order.
    """
    idx = lsmf_component_index(blob)
    csd = idx.get('game.inventory.v0.ContainerSlotData')
    eid = idx.get('core.v0.EntityId')
    if not (csd and eid):
        return {}
    csd_elem, csd_rows, csd_off, _ = csd
    _eid_elem, eid_rows, eid_off, _ = eid
    out: dict[int, list[int]] = {}
    for r in range(csd_rows):
        ptr = struct.unpack_from('<Q', blob, csd_off + r * csd_elem)[0]
        rel = ptr - eid_off
        if ptr and rel >= 0 and rel % 16 == 0 and rel // 16 < eid_rows:
            out.setdefault(rel // 16, []).append(r)
    return {ent: tuple(rows) for ent, rows in out.items()}


def parse_lsmf_stack_amounts(blob: bytes) -> dict[str, int]:
    """Map item entity GUID -> stack amount from the Stack component records.

    Each game.inventory.v0.NewStackComponent row points at a stack record:
    a {begin, end} heap range of member-item EntityId pointers at the target,
    followed by a {begin, end} range of StackEntry rows, whose 8-byte entries
    are {u32 id, u32 amount} inline — the record's amount is their sum.
    Verified against in-game gold piles of 766 and 2017 (QuickSave_297).
    Items without a record are single (amount 1) and are not returned.

    Only single-member records carry a usable amount (one entity holding a
    stack of N). Records grouping several member entities have no reliable
    per-member alignment with their entries (QuickSave_302: four grenades
    share one entry, three soul coins have four) — each member there is one
    physical copy, so they are skipped and default to 1.
    """
    idx = lsmf_component_index(blob)
    ns = idx.get('game.inventory.v0.NewStackComponent')
    se = idx.get('game.inventory.v0.StackEntry')
    eid = idx.get('core.v0.EntityId')
    if not (ns and se and eid):
        return {}
    ns_elem, ns_rows, ns_off, _ns_owners = ns
    se_elem, se_rows, se_off, _se_owners = se
    _eid_elem, eid_rows, eid_off, _eid_owners = eid
    se_b0, se_b1 = se_off, se_off + se_rows * se_elem
    L = len(blob)
    out: dict[str, int] = {}
    for k in range(ns_rows):
        ptr = struct.unpack_from('<Q', blob, ns_off + k * ns_elem)[0] + LSMF_HEAP_BASE
        if not (0 <= ptr <= L - 32):
            continue
        mem_lo, mem_hi, sl, sh = struct.unpack_from('<QQQQ', blob, ptr)
        n = (mem_hi - mem_lo) // 8 if mem_hi > mem_lo else 0
        if not (0 < n <= 256) or (mem_hi - mem_lo) % 8 or mem_lo + LSMF_HEAP_BASE + n * 8 > L:
            continue
        a0, a1 = sl + LSMF_HEAP_BASE, sh + LSMF_HEAP_BASE
        if not (se_b0 <= a0 < a1 <= se_b1) or (a1 - a0) % 8:
            continue
        total = sum(w >> 32 for w in struct.unpack_from(f'<{(a1 - a0) // 8}Q', blob, a0))
        if total <= 0:
            continue
        member_guids = []
        for w in struct.unpack_from(f'<{n}Q', blob, mem_lo + LSMF_HEAP_BASE):
            a = w + LSMF_HEAP_BASE
            if eid_off <= a < eid_off + eid_rows * 16 and (a - eid_off) % 16 == 0:
                member_guids.append(guid_le_str(blob[a : a + 16]))
        if len(member_guids) == 1:
            out[member_guids[0]] = total
    return out
