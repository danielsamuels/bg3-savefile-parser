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


HIT_DIE = {
    'Barbarian': (12, 7),
    'Fighter': (10, 6),
    'Paladin': (10, 6),
    'Ranger': (10, 6),
    'Bard': (8, 5),
    'Cleric': (8, 5),
    'Druid': (8, 5),
    'Monk': (8, 5),
    'Rogue': (8, 5),
    'Warlock': (8, 5),
    'Sorcerer': (6, 4),
    'Wizard': (6, 4),
}


def solve_owner_shifts(owners, valid_at, max_shift: int = 3) -> dict[int, int]:
    """Map owner index k -> data record index j for stream-serialized components.

    Some LSMF components serialize their rows as one packed stream (with a
    small stream header), and the ownerlist can contain a few entries with no
    data record ("phantoms", e.g. destroyed entities). The data record for
    owner k is then j = k - (number of phantoms before k): a monotone,
    non-decreasing shift. valid_at(k, j) reports whether record j is
    consistent with owner k (e.g. proficiency bonus matches the class level);
    the shift step function maximizing validated owners is found by a small
    dynamic program over the shift value.
    """
    n = len(owners)
    NEG = -(1 << 30)
    dp = [0] + [NEG] * max_shift  # dp[s] = best score so far ending at shift s
    choice: list[list[int]] = []  # choice[k][s] = predecessor shift
    for k in range(n):
        gains = [1 if valid_at(k, k - sh) else 0 for sh in range(max_shift + 1)]
        ndp = [NEG] * (max_shift + 1)
        pred = [0] * (max_shift + 1)
        best, best_s = NEG, 0
        for sh in range(max_shift + 1):
            # ties prefer the higher shift: phantoms cluster early in the
            # ownerlist, so ambiguous stretches upgrade as soon as possible
            if dp[sh] >= best:
                best, best_s = dp[sh], sh
            if best > NEG:
                ndp[sh] = best + gains[sh]
                pred[sh] = best_s
        dp = ndp
        choice.append(pred)
    # backtrack the chosen shift per index (ties prefer the higher shift)
    sh = max(range(max_shift + 1), key=lambda x: (dp[x], x))
    shifts = [0] * n
    for k in range(n - 1, -1, -1):
        shifts[k] = sh
        sh = choice[k][sh]
    return {k: k - shifts[k] for k in range(n)}


def parse_lsmf_ability_scores(blob: bytes) -> dict[int, tuple]:
    """Extract effective ability scores: entity row -> (STR,DEX,CON,INT,WIS,CHA).

    game.stats.v3.StatsComponent data is a packed stream: a 20-byte header,
    then one 36-byte record per (non-phantom) owner:
      [0:24)  six i32 ability scores STR,DEX,CON,INT,WIS,CHA (effective:
              includes item effects such as Gloves of Dexterity)
      [24:28) i32 proficiency bonus
      [28:30) u16 small enum, [30:32) u16 per-save handle, [32:36) i32 zero
    Records do NOT align with the 36-byte row grid implied by the descriptor
    (they straddle row boundaries), and the ownerlist may hold a few entries
    with no record; both are handled by solve_owner_shifts with the
    proficiency-vs-class-level check as the validator.
    """
    idx = lsmf_component_index(blob)
    st = idx.get('game.stats.v3.StatsComponent')
    if not st or st[0] != 36:
        return {}
    elem, _rows, off, owners = st
    L = len(blob)
    levels = {ent: sum(lvl for _, _, lvl in cls) for ent, cls in parse_lsmf_classes(blob).items()}

    def rec(j: int):
        p = off + 20 + j * elem
        if not (j >= 0 and p + 36 <= L):
            return None
        return struct.unpack_from('<9i', blob, p)

    def valid_at(k: int, j: int) -> bool:
        v = rec(j)
        if v is None:
            return False
        ab, prof, zero = v[:6], v[6], v[8]
        if zero != 0 or not all(1 <= x <= 40 for x in ab) or not (0 <= prof <= 10):
            return False
        lvl = levels.get(owners[k])
        if lvl and 1 <= lvl <= 20:
            return prof == 2 + (lvl - 1) // 4
        return True

    mapping = solve_owner_shifts(owners, valid_at)
    out: dict[int, tuple] = {}
    for k, ent in enumerate(owners):
        j = mapping[k]
        if valid_at(k, j):
            out.setdefault(ent, rec(j)[:6])
    return out


def parse_lsmf_health(
    blob: bytes,
    abilities: dict[int, tuple] | None = None,
    class_names: dict[str, str] | None = None,
) -> dict[int, tuple]:
    """Extract hit points: entity row -> (current, max, temp, temp_max).

    game.stats.v0.HealthComponent data is a packed stream: a 16-byte header,
    then one 32-byte record per owner {i32 current, i32 max, i32 temp,
    i32 temp_max, 16-byte GUID}. The same phantom-owner shift as the stats
    stream applies (validated by the class/CON max-HP formula); entities can
    appear in two epochs, current state first, so the first occurrence wins.
    """
    idx = lsmf_component_index(blob)
    hl = idx.get('game.stats.v0.HealthComponent')
    if not hl or hl[0] != 32:
        return {}
    elem, _rows, off, owners = hl
    L = len(blob)
    if abilities is None:
        abilities = parse_lsmf_ability_scores(blob)
    class_names = class_names or {}

    expected: dict[int, int] = {}
    for ent, cls in parse_lsmf_classes(blob).items():
        ab = abilities.get(ent)
        if not ab:
            continue
        conmod = (ab[2] - 10) // 2
        total, lvls = 0, 0
        for cguid, _s, lvl in cls:
            die = HIT_DIE.get(class_names.get(cguid, ''))
            if not die:
                total = 0
                break
            total += (die[0] if lvls == 0 else die[1]) + (lvl - (1 if lvls == 0 else 0)) * die[1]
            lvls += lvl
        if total and lvls:
            expected[ent] = total + conmod * lvls

    def rec(j: int):
        p = off + 16 + j * elem
        if not (j >= 0 and p + 16 <= L):
            return None
        return struct.unpack_from('<4i', blob, p)

    def plausible(j: int) -> bool:
        v = rec(j)
        if v is None:
            return False
        cur, mx, temp, temp_max = v
        return 0 < mx <= 4000 and 0 <= cur <= mx and 0 <= temp <= 200 and 0 <= temp_max <= 200

    def valid_at(k: int, j: int) -> bool:
        if not plausible(j):
            return False
        exp = expected.get(owners[k])
        return exp is not None and rec(j)[1] == exp

    mapping = solve_owner_shifts(owners, valid_at)
    out: dict[int, tuple] = {}
    for k, ent in enumerate(owners):
        j = mapping[k]
        if plausible(j) and ent not in out:
            out[ent] = rec(j)
    return out


def parse_lsmf_action_resources(blob: bytes) -> dict[int, list[tuple]]:
    """Action resources per entity: spell slots, rage, ki, superiority dice...

    game.action_resources.v1.Component rows are a {begin, end} heap range of
    64-byte AmountEntry records: {16B resource GUID, i32 level, i32 pad,
    f64 amount, f64 max_amount, u64 replenish_type, 16B tail}.

    The ownerlist VALUES are unreliable (the first ~12 rows hold stale
    owners); the true mapping is positional: the row array is the entity
    array rotated by a fixed offset, so entity = (row - offset) % (rows - 1).
    The offset is derived per save as the majority of (row - owner) over the
    valid sequential section. Validated across the fixture corpus: Warlock
    pact slots, Cleric slots + Channel Divinity, Barbarian rage, Battle
    Master superiority dice, Rogue sneak-attack charge all land on the
    linked stats entities.

    Returns entity -> [(guid, level, amount, max, replenish), ...].
    """
    idx = lsmf_component_index(blob)
    comp = idx.get('game.action_resources.v1.Component')
    if not comp or comp[0] != 16:
        return {}
    elem, rows, off, owners = comp
    if rows < 2 or len(owners) < rows:
        return {}
    L = len(blob)

    votes: Counter = Counter(k - owners[k] for k in range(rows) if 0 <= k - owners[k] <= 64)
    if not votes:
        return {}
    offset = votes.most_common(1)[0][0]

    def decode_row(k: int) -> list[tuple] | None:
        b, e = struct.unpack_from('<QQ', blob, off + k * elem)
        size = e - b
        p = b + LSMF_HEAP_BASE
        if not (0 < size < 64 * 300 and size % 64 == 0 and 0 < p <= L - size):
            return None
        recs = []
        for i in range(size // 64):
            q = p + i * 64
            guid = guid_le_str(blob[q : q + 16])
            lvl, pad = struct.unpack_from('<ii', blob, q + 16)
            amt, mx = struct.unpack_from('<dd', blob, q + 24)
            (repl,) = struct.unpack_from('<Q', blob, q + 40)
            if pad != 0 or not (0 <= lvl <= 9) or amt < 0 or mx < 0 or repl > 0x7F:
                return None
            recs.append((guid, lvl, amt, mx, repl))
        return recs or None

    out: dict[int, list[tuple]] = {}
    # Sequential rows first so a stale duplicate in the rotated head loses.
    for k in list(range(offset, rows)) + list(range(offset)):
        ent = (k - offset) % (rows - 1)
        if ent in out:
            continue
        recs = decode_row(k)
        if recs:
            out[ent] = recs
    return out


def parse_lsmf_concentration(blob: bytes) -> dict[int, str]:
    """Active concentration per entity: entity -> spell ID.

    game.concentration.v0.ConcentrationComponent rows are 24 bytes:
    {u64 caster-related pointer, u64 spell-name pointer (all-FF when not
    concentrating), u32 length, u32 extra}. The ownerlist is direct.
    """
    idx = lsmf_component_index(blob)
    comp = idx.get('game.concentration.v0.ConcentrationComponent')
    if not comp or comp[0] != 24:
        return {}
    elem, rows, off, owners = comp
    L = len(blob)
    out: dict[int, str] = {}
    for k, ent in enumerate(owners):
        if k >= rows or off + (k + 1) * elem > L:
            break
        _skip, ptr, ln, _extra = struct.unpack_from('<QQII', blob, off + k * elem)
        if ptr == 0xFFFFFFFFFFFFFFFF:
            continue
        p0 = ptr + LSMF_HEAP_BASE
        if not (0 < ln <= 128 and 0 < p0 <= L - ln):
            continue
        raw = blob[p0 : p0 + ln]
        if raw and all(0x20 <= c < 0x7F for c in raw):
            out.setdefault(ent, raw.decode('ascii'))
    return out


def parse_lsmf_portraits(blob: bytes) -> tuple[list[tuple[str, bytes]], bytes | None]:
    """Custom character portraits embedded in the save, with the Dream Guardian.

    game.icon.v0.CharacterCreationCustomIconComponent rows (behind the usual
    3-row metadata prefix) are {begin, end} ranges over WebP image bytes, one
    per created character in creation order; the prefix's middle row is the
    range of the Dream Guardian's portrait. Names come from the CC stats
    rows, which chain the same creation order: the first created name sits at
    row0+56, then each row k's +80 pointer names creation slot k+1.

    Ground-truth verified by eye against three saves (16 portraits).
    Returns ([(name, webp bytes), ...], guardian webp bytes or None).
    """
    idx = lsmf_component_index(blob)
    icon = idx.get('game.icon.v0.CharacterCreationCustomIconComponent')
    if not icon or icon[0] != 16:
        return [], None
    elem, rows, off, _owners = icon
    L = len(blob)

    def webp_at(p: int) -> bytes | None:
        if p + 16 > L:
            return None
        b, e = struct.unpack_from('<QQ', blob, p)
        img = blob[b + LSMF_HEAP_BASE : e + LSMF_HEAP_BASE] if 0 < b < e <= L else b''
        return bytes(img) if img[:4] == b'RIFF' else None

    guardian = webp_at(off + 16)  # the prefix's middle row

    names = parse_lsmf_cc_creation_names(blob)
    out: list[tuple[str, bytes]] = []
    base = off + 48
    for k in range(rows):
        img = webp_at(base + k * elem)
        if img is None:
            continue
        name = names[k] if k < len(names) else ''
        out.append((name, img))
    return out, guardian


def parse_lsmf_cc_creation_names(blob: bytes) -> list[str]:
    """Created characters' names in creation order (see parse_lsmf_portraits)."""
    idx = lsmf_component_index(blob)
    comp = idx.get('game.character_creation.v1.CharacterCreationStatsComponent')
    if not comp or comp[0] != 88:
        return []
    elem, rows, off, _owners = comp
    L = len(blob)
    base = off + 48

    def name_at(p: int) -> str:
        if p + 8 > L:
            return ''
        (ptr,) = struct.unpack_from('<Q', blob, p)
        p0 = ptr + LSMF_HEAP_BASE
        if not (0 < p0 < L - 1):
            return ''
        end = blob.find(b'\x00', p0, p0 + 80)
        raw = blob[p0:end] if end > p0 else b''
        ok = raw and all(0x20 <= c < 0x7F for c in raw)
        return raw.decode('ascii') if ok else ''

    out = [name_at(base + 56)]
    out.extend(name_at(base + k * elem + 80) for k in range(rows - 1))
    return out


def parse_lsmf_cc_names(blob: bytes) -> list[str]:
    """Character names from CharacterCreationStatsComponent, in row order.

    Rows are 88 bytes behind a 48-byte metadata prefix; the u64 at row
    offset +80 points (stored form, +48 rule) at the character's
    NUL-terminated display name in the heap. Covers created characters:
    the player, origin companions, and hirelings (whose custom names live
    nowhere else that has been found).
    """
    idx = lsmf_component_index(blob)
    comp = idx.get('game.character_creation.v1.CharacterCreationStatsComponent')
    if not comp or comp[0] != 88:
        return []
    elem, rows, off, _owners = comp
    L = len(blob)
    base = off + 48
    out: list[str] = []
    for k in range(rows):
        p = base + k * elem
        if p + elem > L:
            break
        (ptr,) = struct.unpack_from('<Q', blob, p + 80)
        p0 = ptr + LSMF_HEAP_BASE
        if not (0 < p0 < L - 1):
            continue
        end = blob.find(b'\x00', p0, p0 + 80)
        raw = blob[p0:end] if end > p0 else b''
        if raw and all(0x20 <= c < 0x7F for c in raw):
            out.append(raw.decode('ascii'))
    return out


LEVELUP_NULL_GUID = '00000000-0000-0000-0000-000000000000'

ABILITY_ENUM = (
    'None',
    'Strength',
    'Dexterity',
    'Constitution',
    'Intelligence',
    'Wisdom',
    'Charisma',
)


def parse_lsmf_feats(blob: bytes) -> list[dict]:
    """Level-up history per created character: classes taken and feats picked.

    game.character_creation.v3.LevelUpComponent rows are a {begin, end} heap
    range of u64 pointers, one per level-up event, each pointing at a 96-byte
    LevelUpComponentData record: {16B class GUID, 16B subclass GUID, 16B feat
    GUID, 16B unknown GUID, u64 abilities ptr, u64 selectors ptr, u64 spell
    range begin, u64 end}. The selectors block is seven {begin, end} ranges
    (Feats, AbilityBonuses, Skills, SkillExpertise, Spells, Passives,
    Equipment) of pointers into the selector-record tables; the Feats range
    holds the ability picks made inside a feat (an ASI's +2/+1 choices).

    NOTE: the first three rows of this component's data are metadata (type
    GUID, heap-range header, all-FF sentinel), so per-character ranges start
    3 rows (48 bytes) after data_offset. The owning character-creation
    entities live in their own numbering; callers match records to
    characters by class build.
    Camp companions recruited by script (Halsin) have no record. The sibling
    game.progression.v3.LevelUpComponent has stale ownerlists; do not use it.

    Returns one dict per character: {'levels': [(class_guid, subclass_guid)],
    'feats': [{'guid', 'level', 'picks': [ability name, ...]}]}.
    """
    idx = lsmf_component_index(blob)
    comp = idx.get('game.character_creation.v3.LevelUpComponent')
    if not comp or comp[0] != 16:
        return []
    elem, rows, off, _owners = comp
    L = len(blob)

    # The EAbility enum-value pool, for resolving ability picks.
    ability_pool: dict[int, int] = {}
    ea = idx.get('game.character_creation.v1.EAbility')
    if ea:
        e_elem, e_rows, e_off, _ = ea
        for r in range(e_rows):
            p = e_off + 48 + r * e_elem
            if p + 8 <= L:
                ability_pool[e_off + r * e_elem] = struct.unpack_from('<Q', blob, p)[0]

    def ability_picks(begin: int, end: int) -> list[str]:
        picks = []
        if not (0 < begin < end <= L and (end - begin) % 8 == 0):
            return picks
        for i in range((end - begin) // 8):
            ptr = struct.unpack_from('<Q', blob, begin + LSMF_HEAP_BASE + 8 * i)[0]
            val = ability_pool.get(ptr)
            if val is not None and 0 <= val < len(ABILITY_ENUM):
                picks.append(ABILITY_ENUM[val])
        return picks

    def feat_picks(sel_ptr: int) -> list[str]:
        """Ability picks from the Feats selector range (range index 0)."""
        p = sel_ptr + LSMF_HEAP_BASE
        if not (0 < p <= L - 112):
            return []
        fb, fe = struct.unpack_from('<QQ', blob, p)
        if fb == 0xFFFFFFFFFFFFFFFF or fb >= fe:
            return []
        out: list[str] = []
        for i in range((fe - fb) // 8):
            sel = struct.unpack_from('<Q', blob, fb + LSMF_HEAP_BASE + 8 * i)[0]
            sp = sel + LSMF_HEAP_BASE
            if not (0 < sp <= L - 40):
                continue
            pb, pe = struct.unpack_from('<QQ', blob, sp + 24)
            out += ability_picks(pb, pe)
        return out

    out: list[dict] = []
    data_base = off + 48  # skip the three metadata rows (GUID, header, sentinel)
    for j in range(rows):
        row = data_base + j * elem
        if row + elem > L:
            break
        b, e = struct.unpack_from('<QQ', blob, row)
        if b == 0xFFFFFFFFFFFFFFFF or b >= e or e - b > 8 * 64:
            continue
        levels: list[tuple] = []
        feats: list[dict] = []
        for k in range((e - b) // 8):
            ptr = struct.unpack_from('<Q', blob, b + LSMF_HEAP_BASE + 8 * k)[0]
            p = ptr + LSMF_HEAP_BASE
            if not (0 < p <= L - 96):
                continue
            cls = guid_le_str(blob[p : p + 16])
            sub = guid_le_str(blob[p + 16 : p + 32])
            feat = guid_le_str(blob[p + 32 : p + 48])
            levels.append((cls, sub))
            if feat != LEVELUP_NULL_GUID:
                (sel_ptr,) = struct.unpack_from('<Q', blob, p + 72)
                feats.append({'guid': feat, 'level': len(levels), 'picks': feat_picks(sel_ptr)})
        if levels:
            out.append({'levels': levels, 'feats': feats})
    return out


def parse_lsmf_stats_entities(blob: bytes, templates: dict[str, str]) -> dict[str, int]:
    """Map known characters to their stats-entity rows via the template link.

    `templates` maps lowercase template GUID -> caller's name for it. A
    character occupies two consecutive entity slots: the world entity (which
    owns its game.templates.v0.TemplateComponent row, a pool string holding
    the template GUID) and the stats entity allocated immediately after it
    (which owns ClassesComponent, StatsComponent, HealthComponent, the spell
    book...). So stats_entity = world_entity + 1, wrapping modulo the
    character-entity count (the ClassesComponent ownerlist length).
    Validated on 8 fixture + 6 live saves with zero disagreements, including
    two saves that exercise the modular wrap.
    """
    idx = lsmf_component_index(blob)
    tc = idx.get('game.templates.v0.TemplateComponent')
    cc = idx.get('game.stats.v0.ClassesComponent')
    if not tc or not cc or not cc[3]:
        return {}
    elem, rows, off, owners = tc
    n = len(cc[3])
    L = len(blob)
    out: dict[str, int] = {}
    for k, ent in enumerate(owners):
        if k >= rows or off + (k + 1) * elem > L:
            break
        ptr, ln = struct.unpack_from('<qI', blob, off + k * elem)
        p0 = ptr + LSMF_HEAP_BASE
        if not (0 < ln <= 40 and 0 <= p0 <= L - ln):
            continue
        name = templates.get(blob[p0 : p0 + ln].decode('latin1').lower())
        if name is not None and name not in out:
            out[name] = (ent + 1) % n
    return out


def parse_lsmf_recipes(blob: bytes) -> list[str]:
    """The party's unlocked crafting recipes, as stat names (ALCH_*).

    game.party.v0.RecipeData rows are 24 bytes: {u64 string pointer (+48
    rule), u32 length, u32 junk, u8 unlocked-flag, pool tag}. A couple of
    rows per save are hash-map bookkeeping rather than entries (their
    pointers do not dereference to printable strings); they are skipped by
    the printable check. Validated growth: 2 recipes in the tutorial
    autosave (the game's starting pair), 43 mid-campaign.
    """
    idx = lsmf_component_index(blob)
    rd = idx.get('game.party.v0.RecipeData')
    if not rd or rd[0] != 24:
        return []
    elem, rows, off, _owners = rd
    L = len(blob)
    out = set()
    for k in range(rows):
        if off + (k + 1) * elem > L:
            break
        ptr, ln = struct.unpack_from('<QI', blob, off + k * elem)
        p0 = ptr + LSMF_HEAP_BASE
        if not (0 < ln <= 128 and 0 < p0 <= L - ln):
            continue
        raw = blob[p0 : p0 + ln]
        if raw and all(0x20 <= c < 0x7F for c in raw):
            out.add(raw.decode('ascii'))
    return sorted(out)


def parse_lsmf_camp_supplies(blob: bytes) -> int | None:
    """The camp-supply total shown next to the Long Rest button, or None.

    game.camp.v0.TotalSuppliesComponent holds one u32, preceded by a
    48-byte metadata prefix (the same prefix pattern as LevelUpComponent;
    the value sits at data_offset + 48). Ground-truth verified in-game
    (QuickSave_302 shows 220 in the rest UI and here) and plausible across
    the whole corpus. An earlier read at data_offset hit prefix bytes,
    which produced the now-retracted "zeroed cache" theory.
    """
    idx = lsmf_component_index(blob)
    ts = idx.get('game.camp.v0.TotalSuppliesComponent')
    if not ts:
        return None
    elem, rows, off, _owners = ts
    if elem != 4 or rows != 1 or off + 52 > len(blob):
        return None
    return struct.unpack_from('<I', blob, off + 48)[0]


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
    followed by a {begin, end} range of StackEntry rows. Each 8-byte entry
    is {u16 EntityIndex, u16 pad, u32 amount}: EntityIndex indexes the
    record's member array, so per-member amounts are exact — a member's
    amount is the sum of its entries (a member can have several:
    QuickSave_341's chest stack of 5 Revivify scrolls is members [1, 3, 1],
    the middle one carrying two entries). Verified against in-game gold
    piles of 766 and 2017 (QuickSave_297), per-copy grenade and soul-coin
    stacks (QuickSave_302), and the chest scroll stack (QuickSave_341).
    Members without an entry, and items without a record, are single
    (amount 1) and are not returned.
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
        member_guids: list[str | None] = []
        for w in struct.unpack_from(f'<{n}Q', blob, mem_lo + LSMF_HEAP_BASE):
            a = w + LSMF_HEAP_BASE
            if eid_off <= a < eid_off + eid_rows * 16 and (a - eid_off) % 16 == 0:
                member_guids.append(guid_le_str(blob[a : a + 16]))
            else:
                member_guids.append(None)  # keep indices aligned
        per_member: dict[int, int] = {}
        for w in struct.unpack_from(f'<{(a1 - a0) // 8}Q', blob, a0):
            i, amount = w & 0xFFFF, w >> 32
            if i < len(member_guids):
                per_member[i] = per_member.get(i, 0) + amount
        for i, amount in per_member.items():
            guid = member_guids[i]
            if guid is not None and amount > 1:
                out[guid] = amount
    return out
