/** Osiris story-engine state (StorySave.bin): quests, goals, story flags.
 *  Mirrors bg3parser/osiris.py — see that file for the format notes. */
import { decompFrame } from './lspk.js';
import { PARTY_ORIGINS } from './party.js';

const OSI_VER_SCRAMBLE = 0x0104;
const OSI_VER_ADD_QUERY = 0x0106;
const OSI_VER_TYPE_ALIASES = 0x0109;
const OSI_VER_ENUMS = 0x010d;
const OSI_VER_VALUE_FLAGS = 0x010e;

const OSI_NODE_DATABASE = 1;
const OSI_NODE_PROC = 2;
const OSI_NODE_DIV_QUERY = 3;
const OSI_NODE_AND = 4;
const OSI_NODE_NOT_AND = 5;
const OSI_NODE_REL_OP = 6;
const OSI_NODE_RULE = 7;
const OSI_NODE_INT_QUERY = 8;
const OSI_NODE_USER_QUERY = 9;

type OsiValue = string | number | bigint | null;

interface ReadValue {
  isValid: boolean;
  value: OsiValue;
}

class OsiReader {
  data: Uint8Array;
  dv: DataView;
  pos = 0;
  ver: number;
  shortTypeIds: boolean;
  scramble: number;
  typeAliases = new Map<number, number>();

  constructor(data: Uint8Array, ver: number, shortTypeIds: boolean) {
    this.data = data;
    this.dv = new DataView(data.buffer, data.byteOffset, data.byteLength);
    this.ver = ver;
    this.shortTypeIds = shortTypeIds;
    this.scramble = ver >= OSI_VER_SCRAMBLE ? 0xad : 0x00;
  }

  u8(): number {
    return this.data[this.pos++]!;
  }
  i8(): number {
    return this.dv.getInt8(this.pos++);
  }
  u16(): number {
    const v = this.dv.getUint16(this.pos, true);
    this.pos += 2;
    return v;
  }
  u32(): number {
    const v = this.dv.getUint32(this.pos, true);
    this.pos += 4;
    return v;
  }
  i32(): number {
    const v = this.dv.getInt32(this.pos, true);
    this.pos += 4;
    return v;
  }
  i64(): bigint {
    const v = this.dv.getBigInt64(this.pos, true);
    this.pos += 8;
    return v;
  }
  u64(): bigint {
    const v = this.dv.getBigUint64(this.pos, true);
    this.pos += 8;
    return v;
  }
  f32(): number {
    const v = this.dv.getFloat32(this.pos, true);
    this.pos += 4;
    return v;
  }
  bool(): boolean {
    const v = this.u8();
    if (v !== 0 && v !== 1) throw new Error(`Expected bool, got ${v} at pos ${this.pos - 1}`);
    return v === 1;
  }
  string(): string {
    const buf: number[] = [];
    while (this.pos < this.data.length) {
      const b = this.data[this.pos++]! ^ this.scramble;
      if (b === 0) break;
      buf.push(b);
    }
    return new TextDecoder().decode(new Uint8Array(buf));
  }
  typeId(): number {
    return this.shortTypeIds ? this.u16() : this.u32();
  }
  refU32(): number {
    return this.u32();
  }
}

function readValue(rdr: OsiReader): ReadValue {
  if (rdr.ver >= OSI_VER_VALUE_FLAGS) {
    rdr.i8(); // index (not needed for database queries)
    const flags = rdr.u8();
    if (!(flags & 0x08)) return { isValid: false, value: null }; // IsValid bit
  }
  const d = rdr.u8(); // discriminator byte: '0', '1', or 'e'
  if (d === 0x31 /* '1' */) {
    rdr.typeId();
    return { isValid: true, value: rdr.i32() };
  }
  if (d === 0x30 /* '0' */) {
    const t = rdr.typeId();
    const wt = rdr.typeAliases.get(t) ?? t;
    if (wt === 0) return { isValid: true, value: null };
    if (wt === 1) return { isValid: true, value: rdr.i32() };
    if (wt === 2) return { isValid: true, value: rdr.i64() };
    if (wt === 3) return { isValid: true, value: rdr.f32() };
    const h = rdr.u8();
    return { isValid: true, value: h ? rdr.string() : null };
  }
  if (d === 0x65 /* 'e' */) {
    rdr.u16(); // enum type id
    return { isValid: true, value: rdr.string() };
  }
  throw new Error(`Unknown Osiris value discriminator 0x${d.toString(16)} at pos ${rdr.pos - 1}`);
}

function readTypedValue(rdr: OsiReader): ReadValue {
  const v = readValue(rdr);
  if (rdr.ver < OSI_VER_VALUE_FLAGS) {
    rdr.bool(); // is_valid
    rdr.bool(); // out_param
    rdr.bool(); // is_a_type
  }
  return v;
}

function readVariable(rdr: OsiReader): ReadValue {
  const v = readTypedValue(rdr);
  if (rdr.ver < OSI_VER_VALUE_FLAGS) {
    rdr.i8(); // var_index
    rdr.bool(); // unused
    rdr.bool(); // adapted
  }
  return v;
}

function readTuple(rdr: OsiReader): void {
  const count = rdr.u8();
  for (let i = 0; i < count; i++) {
    if (rdr.ver < OSI_VER_VALUE_FLAGS) rdr.u8();
    readValue(rdr);
  }
}

function readNodeEntryItem(rdr: OsiReader): void {
  rdr.refU32();
  rdr.u32();
  rdr.refU32();
}

function readCall(rdr: OsiReader): void {
  const name = rdr.string();
  if (name) {
    const has = rdr.u8();
    if (has) {
      const n = rdr.u8();
      for (let i = 0; i < n; i++) {
        if (rdr.ver < OSI_VER_VALUE_FLAGS) rdr.u8();
        readVariable(rdr);
      }
    }
    rdr.bool(); // negate
  }
  rdr.i32(); // goal id
}

function skipTypes(rdr: OsiReader): void {
  const n = rdr.u32();
  const ta = new Map<number, number>();
  for (let i = 0; i < n; i++) {
    rdr.string();
    const idx = rdr.u8();
    const alias = rdr.ver >= OSI_VER_TYPE_ALIASES ? rdr.u8() : 3;
    if (alias !== 0) ta.set(idx, alias);
  }
  rdr.typeAliases = ta;
}

function skipEnums(rdr: OsiReader): void {
  const n = rdr.u32();
  for (let i = 0; i < n; i++) {
    rdr.u16();
    const ec = rdr.u32();
    for (let j = 0; j < ec; j++) {
      rdr.string();
      rdr.u64();
    }
  }
}

function skipDivObjects(rdr: OsiReader): void {
  const n = rdr.u32();
  for (let i = 0; i < n; i++) {
    rdr.string();
    rdr.u8();
    rdr.u32();
    rdr.u32();
    rdr.u32();
    rdr.u32();
  }
}

function skipFunctions(rdr: OsiReader): void {
  const n = rdr.u32();
  for (let i = 0; i < n; i++) {
    rdr.u32();
    rdr.u32();
    rdr.u32();
    rdr.refU32();
    rdr.u8();
    rdr.u32();
    rdr.u32();
    rdr.u32();
    rdr.u32();
    rdr.string();
    const ob = rdr.u32();
    for (let j = 0; j < ob; j++) rdr.u8();
    const c = rdr.u8();
    for (let j = 0; j < c; j++) rdr.typeId();
  }
}

function readParamList(rdr: OsiReader): void {
  const c = rdr.u8();
  for (let i = 0; i < c; i++) rdr.typeId();
}

/** Nodes section: {db_ref: name} for entries that name a database/proc ref. */
function readNodes(rdr: OsiReader): Map<number, string> {
  const n = rdr.u32();
  const dbNames = new Map<number, string>();
  for (let i = 0; i < n; i++) {
    const nt = rdr.u8();
    rdr.u32(); // node id
    const dbRef = rdr.refU32();
    const nm = rdr.string();
    if (nm) rdr.u8(); // param count (present when name non-empty)
    if (nm && dbRef) dbNames.set(dbRef, nm);
    if (nt === OSI_NODE_DATABASE || nt === OSI_NODE_PROC) {
      const rc = rdr.u32(); // DataNode extra: ReferencedBy list
      for (let j = 0; j < rc; j++) readNodeEntryItem(rdr);
    } else if (
      nt === OSI_NODE_DIV_QUERY ||
      nt === OSI_NODE_INT_QUERY ||
      nt === OSI_NODE_USER_QUERY
    ) {
      // no extra payload
    } else if (nt === OSI_NODE_AND || nt === OSI_NODE_NOT_AND) {
      readNodeEntryItem(rdr);
      rdr.refU32();
      rdr.refU32();
      rdr.refU32();
      rdr.refU32();
      rdr.refU32();
      readNodeEntryItem(rdr);
      rdr.u8();
      rdr.refU32();
      readNodeEntryItem(rdr);
      rdr.u8();
    } else if (nt === OSI_NODE_REL_OP) {
      readNodeEntryItem(rdr);
      rdr.refU32();
      rdr.refU32();
      rdr.refU32();
      readNodeEntryItem(rdr);
      rdr.u8();
      rdr.i8();
      rdr.i8();
      readValue(rdr);
      readValue(rdr);
      rdr.i32();
    } else if (nt === OSI_NODE_RULE) {
      readNodeEntryItem(rdr);
      rdr.refU32();
      rdr.refU32();
      rdr.refU32();
      readNodeEntryItem(rdr);
      rdr.u8();
      const cc = rdr.u32();
      for (let j = 0; j < cc; j++) readCall(rdr);
      const vc = rdr.u8();
      for (let j = 0; j < vc; j++) {
        if (rdr.ver < OSI_VER_VALUE_FLAGS) rdr.u8();
        readVariable(rdr);
      }
      rdr.u32();
      if (rdr.ver >= OSI_VER_ADD_QUERY) rdr.bool();
    } else {
      throw new Error(`Unknown Osiris node type ${nt} at pos ${rdr.pos}`);
    }
  }
  return dbNames;
}

function skipAdapters(rdr: OsiReader): void {
  const n = rdr.u32();
  for (let i = 0; i < n; i++) {
    rdr.u32();
    readTuple(rdr);
    const lc = rdr.u8();
    for (let j = 0; j < lc; j++) rdr.i8();
    const mc = rdr.u8();
    for (let j = 0; j < mc; j++) {
      rdr.u8();
      rdr.u8();
    }
  }
}

/** Databases section: {db_index: facts[][]} (each fact a row of values). */
function readDatabases(rdr: OsiReader): Map<number, ReadValue[][]> {
  const n = rdr.u32();
  const dbs = new Map<number, ReadValue[][]>();
  for (let i = 0; i < n; i++) {
    const idx = rdr.u32();
    readParamList(rdr);
    const fc = rdr.u32();
    const facts: ReadValue[][] = [];
    for (let j = 0; j < fc; j++) {
      const cc = rdr.u8();
      const cols: ReadValue[] = [];
      for (let k = 0; k < cc; k++) cols.push(readValue(rdr));
      facts.push(cols);
    }
    dbs.set(idx, facts);
  }
  return dbs;
}

/** Goals section: {goal_idx: {name, flags}}. */
function readGoals(rdr: OsiReader): Map<number, { name: string; flags: number }> {
  const n = rdr.u32();
  const goals = new Map<number, { name: string; flags: number }>();
  for (let i = 0; i < n; i++) {
    const idx = rdr.u32();
    const nm = rdr.string();
    rdr.u8(); // SubGoalCombination
    const pg = rdr.u32();
    for (let j = 0; j < pg; j++) rdr.refU32();
    const sg = rdr.u32();
    for (let j = 0; j < sg; j++) rdr.refU32();
    const flags = rdr.u8();
    const ic = rdr.u32();
    for (let j = 0; j < ic; j++) readCall(rdr);
    const ec = rdr.u32();
    for (let j = 0; j < ec; j++) readCall(rdr);
    goals.set(idx, { name: nm, flags });
  }
  return goals;
}

export interface StoryState {
  approval: { name: string; rating: number }[];
  dating: string[];
  long_rests: number;
  tadpoles: { name: string; count: number }[];
  waypoints: string[];
  traders_met: number;
}

export interface OsirisState {
  version: number;
  quests_active: string[];
  quests_closed: string[];
  goals_finalized: string[];
  global_flags: string[];
  global_flags_total: number;
  story: StoryState;
}

const byName = (a: string, b: string): number => (a < b ? -1 : a > b ? 1 : 0);

/** Distil campaign/social state from the story databases (see osiris.py). */
function extractStory(nameToFacts: Map<string, ReadValue[][]>): StoryState {
  const rows = (nm: string): unknown[][] =>
    (nameToFacts.get(nm) ?? []).map((r) => r.map((c) => c.value));

  const avatarRows = rows('DB_Avatars');
  const avatar = avatarRows.length && avatarRows[0]!.length ? avatarRows[0]![0] : null;

  const charName = (s: unknown): string | null => {
    if (typeof s !== 'string' || s.length < 36) return null;
    if (avatar !== null && s === avatar) return 'Player';
    return PARTY_ORIGINS[s.slice(-36)] ?? null;
  };

  const approval = rows('DB_ApprovalRating')
    .filter((r) => r.length === 3 && avatar !== null && r[1] === avatar)
    .map((r) => ({ name: charName(r[0]), rating: r[2] as number }))
    .filter((a): a is { name: string; rating: number } => a.name !== null && a.name !== 'Player')
    .sort((a, b) => b.rating - a.rating || byName(a.name, b.name));

  const flags = new Set(dbStrings(nameToFacts, 'DB_GlobalFlag'));
  const dating = rows('DB_CompanionIsDating')
    .filter((r) => r.length === 2 && typeof r[1] === 'string' && flags.has(r[1] as string))
    .map((r) => charName(r[0]))
    .filter((n): n is string => n !== null && n !== 'Player')
    .sort(byName);

  const counters = new Map(
    rows('DB_GlobalCounter')
      .filter((r) => r.length === 2)
      .map((r) => [r[0] as string, r[1] as number]),
  );

  const tadpoles = rows('DB_GLO_Tadpoled_Count')
    .filter((r) => r.length === 2)
    .map((r) => ({ name: charName(r[0]), count: r[1] as number }))
    .filter((t): t is { name: string; count: number } => t.name !== null)
    .sort((a, b) => b.count - a.count || byName(a.name, b.name));

  const waypoints = [
    ...new Set(
      rows('DB_WaypointUnlocked')
        .filter((r) => r.length === 2 && typeof r[0] === 'string' && r[0])
        .map((r) => r[0] as string),
    ),
  ].sort(byName);

  return {
    approval,
    dating,
    long_rests: counters.get('Camp_Rest_Count') ?? 0,
    tadpoles,
    waypoints,
    traders_met: rows('DB_TradeTreasureGeneratedEver').length,
  };
}

/** All non-null string values from a single-column database. */
function dbStrings(nameToFacts: Map<string, ReadValue[][]>, dbName: string): string[] {
  return (nameToFacts.get(dbName) ?? [])
    .filter((row) => row.length && row[0]!.isValid && row[0]!.value !== null)
    .map((row) => String(row[0]!.value));
}

/** Parse the Osiris story state; null on any failure (caller degrades). */
export function parseOsiris(frames: Map<string, Uint8Array>): OsirisState | null {
  try {
    const frame = frames.get('StorySave.bin');
    if (!frame) return null;
    const data = decompFrame(frame);

    // Header: NUL, version string (NUL-terminated), major/minor/bigendian/
    // unused bytes, 0x80-byte version buffer, u32 debug flags.
    let pos = 0;
    if (data[pos] !== 0) return null;
    pos += 1;
    while (data[pos] !== 0) pos += 1;
    pos += 1;
    const major = data[pos]!;
    const minor = data[pos + 1]!;
    pos += 4;
    const ver = (major << 8) | minor;
    pos += 0x80;
    pos += 4;

    const rdr = new OsiReader(data, ver, ver >= OSI_VER_ENUMS);
    rdr.pos = pos;

    skipTypes(rdr);
    if (ver >= OSI_VER_ENUMS) skipEnums(rdr);
    skipDivObjects(rdr);
    skipFunctions(rdr);
    const dbNames = readNodes(rdr);
    skipAdapters(rdr);
    const databases = readDatabases(rdr);
    const goals = readGoals(rdr);
    const nGa = rdr.u32(); // GlobalActions — consume so the parse is complete
    for (let i = 0; i < nGa; i++) readCall(rdr);

    const nameToFacts = new Map<string, ReadValue[][]>();
    for (const [dbRef, nm] of dbNames) {
      const facts = databases.get(dbRef);
      if (facts) nameToFacts.set(nm, facts);
    }

    const accepted = new Set(dbStrings(nameToFacts, 'DB_QuestIsAccepted'));
    const closed = new Set(dbStrings(nameToFacts, 'DB_QuestIsClosed'));
    const active = [...accepted].filter((q) => !closed.has(q)).sort();
    const closedL = [...closed].sort();

    const goalsDone = [...goals.values()]
      .filter((g) => g.flags === 0x07 && g.name)
      .map((g) => g.name)
      .sort();

    const globalFlags = dbStrings(nameToFacts, 'DB_GlobalFlag');

    return {
      version: ver,
      quests_active: active,
      quests_closed: closedL,
      goals_finalized: goalsDone,
      global_flags: globalFlags.slice(0, 50),
      global_flags_total: globalFlags.length,
      story: extractStory(nameToFacts),
    };
  } catch {
    return null;
  }
}
