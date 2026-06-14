"""Osiris story-engine state (frame 9): quests, goals, story flags."""

import struct

from .lsf import decomp_frame
from .party import PARTY_ORIGINS

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


def osi_read_node_entry_item(rdr: OsiReader) -> dict:
    """A NodeEntryItem: a Rete trigger edge (target node, entry point, source goal).

    `node_ref` is the downstream node fired when this node produces a row;
    `entry_point` selects which input of that node (left/right for joins);
    `goal_ref` is the goal that owns the edge (0 = none).
    """
    return {'node_ref': rdr.ref_u32(), 'entry_point': rdr.u32(), 'goal_ref': rdr.ref_u32()}


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


def osi_read_node_base(rdr: OsiReader) -> tuple:
    """The fields every node shares: db_ref (u32), name, and num_params.

    `num_params` is present in the stream only when `name` is non-empty.
    """
    db_ref = rdr.u32()
    name = rdr.string()
    num_params = rdr.u8() if name else 0
    return db_ref, name, num_params


def osi_read_rel_node_tail(rdr: OsiReader) -> dict:
    """RelNode body: a single-parent join used by RelOp and Rule nodes.

    Layout: ParentRef, AdapterRef, RelDatabaseNodeRef, RelJoin (NEI),
    RelDatabaseIndirection (u8). The adapter reshapes the parent's output
    tuple into this node's input columns.
    """
    return {
        'parent_ref': rdr.ref_u32(),
        'adapter_ref': rdr.ref_u32(),
        'rel_db_node_ref': rdr.ref_u32(),
        'rel_join': osi_read_node_entry_item(rdr),
        'rel_indirection': rdr.u8(),
    }


def osi_read_join_node_tail(rdr: OsiReader) -> dict:
    """JoinNode body: the two-input join used by And and NotAnd nodes.

    Layout: Left/RightParentRef, Left/RightAdapterRef, then per side a
    DatabaseNodeRef + join NEI + indirection byte. Each adapter reshapes its
    parent's output into the join's column space.
    """
    return {
        'left_parent_ref': rdr.ref_u32(),
        'right_parent_ref': rdr.ref_u32(),
        'left_adapter_ref': rdr.ref_u32(),
        'right_adapter_ref': rdr.ref_u32(),
        'left_db_node_ref': rdr.ref_u32(),
        'left_db_join': osi_read_node_entry_item(rdr),
        'left_indirection': rdr.u8(),
        'right_db_node_ref': rdr.ref_u32(),
        'right_db_join': osi_read_node_entry_item(rdr),
        'right_indirection': rdr.u8(),
    }


def osi_read_nodes(rdr: OsiReader) -> dict:
    """Read the Nodes section: the full compiled Rete network.

    Returns `{node_id: node}` where each node is a dict carrying its type,
    `db_ref`, `name`, `num_params`, and the per-type body (ReferencedBy edges
    for data nodes; parent/adapter refs and join wiring for tree nodes; the
    comparison for RelOp; calls/variables for Rule). The `(db_ref, name)`
    pairs with both non-zero are the database-name records used to label the
    Databases section.
    """
    n = rdr.u32()
    nodes: dict = {}
    for _ in range(n):
        nt = rdr.u8()
        node_id = rdr.u32()
        db_ref, name, num_params = osi_read_node_base(rdr)
        node: dict = {
            'id': node_id,
            'type': nt,
            'db_ref': db_ref,
            'name': name,
            'num_params': num_params,
        }

        if nt in (OSI_NODE_DATABASE, OSI_NODE_PROC):
            # DataNode: the list of rule edges that read from this database/proc.
            rc = rdr.u32()
            node['referenced_by'] = [osi_read_node_entry_item(rdr) for _ in range(rc)]
        elif nt in (OSI_NODE_DIV_QUERY, OSI_NODE_INT_QUERY, OSI_NODE_USER_QUERY):
            pass  # Query nodes carry only the base fields.
        elif nt in (OSI_NODE_AND, OSI_NODE_NOT_AND):
            node['next_node'] = osi_read_node_entry_item(rdr)
            node.update(osi_read_join_node_tail(rdr))
        elif nt == OSI_NODE_REL_OP:
            node['next_node'] = osi_read_node_entry_item(rdr)
            node.update(osi_read_rel_node_tail(rdr))
            node['left_value_index'] = rdr.i8()
            node['right_value_index'] = rdr.i8()
            node['left_value'] = osi_read_value(rdr)
            node['right_value'] = osi_read_value(rdr)
            node['rel_op'] = rdr.i32()  # RelOpType: 0=<,1=<=,2=>,3=>=,4===,5=!=
        elif nt == OSI_NODE_RULE:
            node['next_node'] = osi_read_node_entry_item(rdr)
            node.update(osi_read_rel_node_tail(rdr))
            cc = rdr.u32()
            node['calls'] = [osi_read_call(rdr) for _ in range(cc)]
            vc = rdr.u8()
            variables = []
            for _ in range(vc):
                if rdr.ver < OSI_VER_VALUE_FLAGS:
                    rdr.u8()  # legacy per-variable type tag (must be 1)
                variables.append(osi_read_variable(rdr))
            node['variables'] = variables
            node['line'] = rdr.u32()
            if rdr.ver >= OSI_VER_ADD_QUERY:
                node['is_query'] = rdr.bool()
        else:
            raise ValueError(f'Unknown Osiris node type {nt} at pos {rdr.pos}')
        nodes[node_id] = node
    return nodes


def osi_node_db_names(nodes: dict) -> dict:
    """The `{db_ref: name}` label map: nodes with both a name and a database."""
    return {nd['db_ref']: nd['name'] for nd in nodes.values() if nd['name'] and nd['db_ref']}


def osi_read_adapters(rdr: OsiReader) -> dict:
    """Read the Adapters section: column reshapers between Rete nodes.

    An adapter rewrites an input tuple into an output tuple. Each record is
    `(index, constants, logical_indices, logical_to_physical)`:

      * `constants` — a Tuple of constant output columns (logical index → value).
      * `logical_indices` — one sbyte per output physical column. A value >= 0
        copies that logical column from the input tuple; -1 emits a constant
        (from `constants`) or a null when no constant is mapped.
      * `logical_to_physical` — `{logical_index: physical_index}` naming the
        output tuple's columns so downstream nodes can address them.

    Returns `{adapter_index: adapter}`.
    """
    n = rdr.u32()
    adapters: dict = {}
    for _ in range(n):
        index = rdr.u32()
        constants = osi_read_tuple(rdr)
        lc = rdr.u8()
        logical_indices = [rdr.i8() for _ in range(lc)]
        mc = rdr.u8()
        logical_to_physical = {}
        for _ in range(mc):
            key = rdr.u8()
            logical_to_physical[key] = rdr.u8()
        adapters[index] = {
            'index': index,
            'constants': constants,
            'logical_indices': logical_indices,
            'logical_to_physical': logical_to_physical,
        }
    return adapters


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


def extract_story(name_to_facts: dict) -> dict:
    """Distil campaign/social state from the story databases.

    Osiris CHARACTER values are strings ending in a 36-char GUID
    (`S_Player_ShadowHeart_3ed74f06-…`); the suffix maps onto PARTY_ORIGINS.
    Labels are unreliable (Minthara is `S_GOB_DrowCommander_…`), so matching
    is always by GUID. The player avatar is identified via DB_Avatars (in an
    origin run the avatar is itself an `S_Player_X` string) and reported as
    'Player'.
    """

    def rows(nm: str) -> list[list]:
        return [[c.get('value') for c in r] for r in name_to_facts.get(nm, [])]

    avatar_rows = rows('DB_Avatars')
    avatar = avatar_rows[0][0] if avatar_rows and avatar_rows[0] else None

    def char_name(s) -> str | None:
        if not isinstance(s, str) or len(s) < 36:
            return None
        if avatar is not None and s == avatar:
            return 'Player'
        return PARTY_ORIGINS.get(s[-36:])

    # Companion approval toward the player (observed range 0..100; only
    # characters with at least one approval event have rows).
    approval = sorted(
        (
            {'name': nm, 'rating': r[2]}
            for r in rows('DB_ApprovalRating')
            if len(r) == 3
            and avatar is not None
            and r[1] == avatar
            and (nm := char_name(r[0])) not in (None, 'Player')
        ),
        key=lambda a: (-a['rating'], a['name']),
    )

    # Romance: companions whose "is dating the avatar" flag is set.
    flags = set(get_db_strings(name_to_facts, 'DB_GlobalFlag'))
    dating = sorted(
        nm
        for r in rows('DB_CompanionIsDating')
        if len(r) == 2 and r[1] in flags and (nm := char_name(r[0])) not in (None, 'Player')
    )

    counters = {r[0]: r[1] for r in rows('DB_GlobalCounter') if len(r) == 2}

    tadpoles = sorted(
        (
            {'name': nm, 'count': r[1]}
            for r in rows('DB_GLO_Tadpoled_Count')
            if len(r) == 2 and (nm := char_name(r[0])) is not None
        ),
        key=lambda t: (-t['count'], t['name']),
    )

    waypoints = sorted({r[0] for r in rows('DB_WaypointUnlocked') if len(r) == 2 and r[0]})

    return {
        'approval': approval,
        'dating': dating,
        'long_rests': counters.get('Camp_Rest_Count', 0),
        'tadpoles': tadpoles,
        'waypoints': waypoints,
        'traders_met': len(rows('DB_TradeTreasureGeneratedEver')),
    }


def get_db_strings(name_to_facts: dict, db_name: str) -> list[str]:
    """All non-None string values from a single-column database."""
    return [
        str(row[0]['value'])
        for row in name_to_facts.get(db_name, [])
        if row and row[0].get('is_valid') and row[0].get('value') is not None
    ]


def read_story(frames: dict[str, bytes]):
    """Parse frame 9 into (version, name_to_facts, goals), or None on failure.

    `name_to_facts` is the full live story database: `{db_name: [row, ...]}`
    where each row is a list of `{is_valid, value}` columns. This is the
    Osiris fact base the rule engine needs as its baseline. The parse must read
    all sections in order (Types → Enums → DivObjects → Functions → Nodes →
    Adapters → Databases → Goals → GlobalActions); ~1-2 s on a typical save.
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
        nodes = osi_read_nodes(rdr)
        db_names = osi_node_db_names(nodes)
        osi_read_adapters(rdr)
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

        return ver, name_to_facts, goals

    except Exception:
        return None


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
    """
    res = read_story(frames)
    if res is None:
        return None
    ver, name_to_facts, goals = res
    try:
        accepted = set(get_db_strings(name_to_facts, 'DB_QuestIsAccepted'))
        closed = set(get_db_strings(name_to_facts, 'DB_QuestIsClosed'))
        active = sorted(accepted - closed)
        closed_l = sorted(closed)

        goals_done = sorted(g['name'] for g in goals.values() if g['flags'] == 0x07 and g['name'])

        global_flags = get_db_strings(name_to_facts, 'DB_GlobalFlag')

        return {
            'version': ver,
            'quests_active': active,
            'quests_closed': closed_l,
            'goals_finalized': goals_done,
            'global_flags': global_flags[:50],
            'global_flags_total': len(global_flags),
            'story': extract_story(name_to_facts),
        }
    except Exception:
        return None
