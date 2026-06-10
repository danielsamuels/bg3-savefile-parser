"""Osiris story-engine state (frame 9): quests, goals, story flags."""

import struct

from .lsf import decomp_frame

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
OSI_VER_SCRAMBLE = 0x0104


OSI_VER_ADD_QUERY = 0x0106


OSI_VER_TYPE_ALIASES = 0x0109


OSI_VER_ENUMS = 0x010D


OSI_VER_VALUE_FLAGS = 0x010E


# Osiris node-type IDs
OSI_NODE_DATABASE = 1


OSI_NODE_PROC = 2


OSI_NODE_DIV_QUERY = 3


OSI_NODE_AND = 4


OSI_NODE_NOT_AND = 5


OSI_NODE_REL_OP = 6


OSI_NODE_RULE = 7


OSI_NODE_INT_QUERY = 8


OSI_NODE_USER_QUERY = 9


class OsiReader:
    """Sequential binary reader for the Osiris save format."""

    def __init__(
        self, data: bytes, ver: int, short_type_ids: bool, type_aliases: dict | None = None
    ):
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
        rdr.i8()  # index (not needed for database queries)
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
        rdr.i8()  # var_index
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
        rdr.u32()  # node id
        db_ref = rdr.ref_u32()
        nm = rdr.string()
        if nm:
            rdr.u8()  # param count (present when name non-empty)
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
        rdr.u8()  # SubGoalCombination
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
        pos += 1  # consume null terminator
        major = data[pos]
        minor = data[pos + 1]
        pos += 4
        ver = (major << 8) | minor
        pos += 0x80  # version buffer
        pos += 4  # debug flags

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
        closed = set(get_single_col_strings('DB_QuestIsClosed'))
        active = sorted(accepted - closed)
        closed_l = sorted(closed)

        goals_done = sorted(g['name'] for g in goals.values() if g['flags'] == 0x07 and g['name'])

        global_flags = get_single_col_strings('DB_GlobalFlag')

        return {
            'version': ver,
            'quests_active': active,
            'quests_closed': closed_l,
            'goals_finalized': goals_done,
            'global_flags': global_flags[:50],
            'global_flags_total': len(global_flags),
        }

    except Exception:
        return None
