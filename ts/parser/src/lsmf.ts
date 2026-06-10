/** The LSMF ECS blob ("NewAge"): components, ownerlists, containers, stacks.
 *  Mirrors bg3parser/lsmf.py. */
import { guidLeStr } from './lsf.js';

// All absolute offsets in the blob are stored as (actual - 48).
export const LSMF_HEAP_BASE = 48;

export const OWNED_AS_LOOT_COMP = 'game.v0.OwnedAsLootComponent';
export const WIELDED_COMP = 'game.inventory.v0.WieldedComponent';
export const GRAVITY_DISABLED_COMP = 'game.gravity.v0.GravityDisabledComponent';

export interface CompDesc {
  name: string;
  elemSize: number;
  rowCount: number;
  dataOffset: number;
}

/** Ownerlist record: component index, packed-u32 start offset, entity count. */
export type OwnerRecord = [comp: number, start: number, entityCount: number];

export interface ScannedBlob {
  compDescs: CompDesc[];
  records: OwnerRecord[];
}

interface AlignedBlob {
  bytes: Uint8Array; // 4-aligned copy when needed
  dv: DataView;
  words: Uint32Array;
}

const alignCache = new WeakMap<Uint8Array, AlignedBlob>();
const scanCache = new WeakMap<Uint8Array, ScannedBlob | null>();

function align(blob: Uint8Array): AlignedBlob {
  let cached = alignCache.get(blob);
  if (!cached) {
    const bytes = blob.byteOffset % 4 === 0 ? blob : blob.slice();
    const dv = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    const words = new Uint32Array(bytes.buffer, bytes.byteOffset, Math.floor(bytes.byteLength / 4));
    cached = { bytes, dv, words };
    alignCache.set(blob, cached);
  }
  return cached;
}

const u64 = (dv: DataView, off: number) => Number(dv.getBigUint64(off, true));

/** Parse the LSMF header, component descriptors, and ownerlist table.
 *  Returns null on any parse failure. Cached per blob object — the ownerlist
 *  sweep walks the whole blob and dominates parse time. */
export function scanLsmfBlob(blob: Uint8Array): ScannedBlob | null {
  const cached = scanCache.get(blob);
  if (cached !== undefined) return cached;
  const result = scanLsmfBlobUncached(blob);
  scanCache.set(blob, result);
  return result;
}

function scanLsmfBlobUncached(blob: Uint8Array): ScannedBlob | null {
  try {
    const { bytes, dv, words } = align(blob);
    const L = bytes.length;
    const dirOff = u64(dv, 16);
    const namesSize = u64(dv, 24);
    const namesOff = dirOff + LSMF_HEAP_BASE;
    const descTableRel = dv.getUint32(32, true);
    const entryCount = dv.getUint16(36, true);
    if (!(namesOff > 0 && namesOff < L && entryCount > 0 && entryCount < 2000)) return null;
    const namesSec = bytes.subarray(namesOff, namesOff + namesSize);
    const descBase = namesOff + descTableRel;
    const dec = new TextDecoder();

    const compDescs: CompDesc[] = [];
    const rowsByComp = new Map<number, number>();
    for (let i = 0; i < entryCount; i++) {
      const base = descBase + i * 48;
      if (base + 48 > L) break;
      const nameOff = u64(dv, base);
      const nameLen = u64(dv, base + 8);
      const elemSize = dv.getUint32(base + 24, true);
      const rowCount = u64(dv, base + 32);
      const dataOffset = u64(dv, base + 40);
      rowsByComp.set(i, rowCount);
      const name =
        nameLen > 0 && nameLen < 200
          ? dec.decode(namesSec.subarray(nameOff, nameOff + nameLen))
          : '';
      compDescs.push({ name, elemSize, rowCount, dataOffset });
    }

    // Ownerlist region: 32-byte records {start, end, comp, entity_count} (u64s).
    const validRecord = (p: number): OwnerRecord | null => {
      const start = u64(dv, p);
      const end = u64(dv, p + 8);
      const comp = u64(dv, p + 16);
      const ec = u64(dv, p + 24);
      if (
        comp < entryCount &&
        ec > 0 &&
        rowsByComp.get(comp) === ec &&
        end > start &&
        end - start === ec * 4 &&
        end <= L &&
        start < L
      ) {
        return [comp, start, ec];
      }
      return null;
    };

    // u32 prefilter: a record at word i has comp/ec high dwords at i+5 / i+7.
    const validPos: number[] = [];
    const maxWord = Math.floor((L - 32) / 4);
    for (let i = 0; i <= maxWord; i++) {
      if (words[i + 5] === 0 && words[i + 7] === 0) {
        const comp = words[i + 4]!;
        const ec = words[i + 6]!;
        if (comp < entryCount && ec > 0 && rowsByComp.get(comp) === ec && validRecord(i * 4)) {
          validPos.push(i * 4);
        }
      }
    }

    // The real table is the densest chain of positions spaced by multiples of 32.
    let anchor = 0;
    let bestCount = 0;
    for (let vi = 0; vi < validPos.length; vi++) {
      let count = 1;
      let last = validPos[vi]!;
      for (let vj = vi + 1; vj < validPos.length; vj++) {
        const d = validPos[vj]! - last;
        if (d % 32 === 0 && d <= 32 * 40) {
          count++;
          last = validPos[vj]!;
        } else if (d > 32 * 40) break;
      }
      if (count > bestCount) {
        anchor = validPos[vi]!;
        bestCount = count;
      }
    }

    const records: OwnerRecord[] = [];
    if (bestCount > 0) {
      let p = anchor;
      let misses = 0;
      while (p + 32 <= L && misses < 4) {
        const rec = validRecord(p);
        if (rec !== null) {
          records.push(rec);
          misses = 0;
        } else {
          const compLo = dv.getUint32(p + 16, true);
          const compHi = dv.getUint32(p + 20, true);
          misses = compLo === 0xffffffff && compHi === 0xffffffff ? 0 : misses + 1;
        }
        p += 32;
      }
    }
    return { compDescs, records };
  } catch {
    return null;
  }
}

export interface ComponentInfo extends CompDesc {
  /** The component's ownerlist: the k-th data row belongs to ownerRows[k]. */
  ownerRows: Uint32Array;
}

/** Map component name -> descriptor + ownerlist (first descriptor per name wins). */
export function lsmfComponentIndex(blob: Uint8Array): Map<string, ComponentInfo> {
  const scanned = scanLsmfBlob(blob);
  const out = new Map<string, ComponentInfo>();
  if (!scanned) return out;
  const { bytes } = align(blob);
  const owners = new Map<number, Uint32Array>();
  for (const [comp, start, ec] of scanned.records) {
    const view = new Uint8Array(bytes.buffer, bytes.byteOffset + start, ec * 4).slice();
    owners.set(comp, new Uint32Array(view.buffer));
  }
  scanned.compDescs.forEach((desc, i) => {
    if (desc.name && !out.has(desc.name)) {
      out.set(desc.name, { ...desc, ownerRows: owners.get(i) ?? new Uint32Array(0) });
    }
  });
  return out;
}

export interface Membership {
  guidToRows: Map<string, number[]>;
  membershipCount: Map<number, number>;
}

/** Entity GUID table + per-entity ownerlist membership counts. */
export function parseLsmfMembership(blob: Uint8Array): Membership | null {
  const scanned = scanLsmfBlob(blob);
  if (!scanned) return null;
  const { bytes, dv } = align(blob);
  let eidOff = 0;
  let eidRows = 0;
  for (const d of scanned.compDescs) {
    if (d.name === 'core.v0.EntityId') {
      eidOff = d.dataOffset;
      eidRows = d.rowCount;
    }
  }
  if (!eidRows || eidOff + eidRows * 16 > bytes.length) return null;

  const guidToRows = new Map<string, number[]>();
  for (let i = 0; i < eidRows; i++) {
    const g = guidLeStr(bytes, eidOff + i * 16);
    const rows = guidToRows.get(g);
    if (rows) rows.push(i);
    else guidToRows.set(g, [i]);
  }
  const membershipCount = new Map<number, number>();
  for (const [, start, ec] of scanned.records) {
    for (let k = 0; k < ec; k++) {
      const row = dv.getUint32(start + k * 4, true);
      membershipCount.set(row, (membershipCount.get(row) ?? 0) + 1);
    }
  }
  return { guidToRows, membershipCount };
}

/** ECS row indices per named component (every named component when names omitted). */
export function parseLsmfComponentRows(
  blob: Uint8Array,
  compNames?: string[],
): Map<string, Set<number>> {
  const result = new Map<string, Set<number>>();
  for (const n of compNames ?? []) result.set(n, new Set());
  const scanned = scanLsmfBlob(blob);
  if (!scanned) return result;
  const { dv } = align(blob);
  const want = compNames ? new Set(compNames) : null;
  for (const [comp, start, ec] of scanned.records) {
    const name = scanned.compDescs[comp]?.name;
    if (!name || (want && !want.has(name))) continue;
    let rows = result.get(name);
    if (!rows) {
      rows = new Set();
      result.set(name, rows);
    }
    for (let k = 0; k < ec; k++) rows.add(dv.getUint32(start + k * 4, true));
  }
  return result;
}

/** Entity row -> every ContainerSlotData row referencing it (ascending). */
export function parseLsmfAllContainerPositions(blob: Uint8Array): Map<number, number[]> {
  const idx = lsmfComponentIndex(blob);
  const csd = idx.get('game.inventory.v0.ContainerSlotData');
  const eid = idx.get('core.v0.EntityId');
  const out = new Map<number, number[]>();
  if (!csd || !eid) return out;
  const { dv } = align(blob);
  for (let r = 0; r < csd.rowCount; r++) {
    const ptr = u64(dv, csd.dataOffset + r * csd.elemSize);
    const rel = ptr - eid.dataOffset;
    if (ptr && rel >= 0 && rel % 16 === 0 && rel / 16 < eid.rowCount) {
      const ent = rel / 16;
      const rows = out.get(ent);
      if (rows) rows.push(r);
      else out.set(ent, [r]);
    }
  }
  return out;
}

/** Entity row -> first ContainerSlotData row (ring/hand ordering). */
/** Extract prepared spells: entity row -> [spell ID, source type, source GUID][].
 *
 *  game.spell.v0.SpellBookPrepares rows are 80 bytes (five {begin, end} heap
 *  ranges); the fourth range is the PreparedSpells array of 24-byte
 *  SpellMetaId records {string pointer, length, pad, detail pointer}. The
 *  detail record holds a pointer into the game.spell.v0.ESourceType value
 *  pool (the SpellSourceType) followed by the ProgressionSource GUID.
 *
 *  The prepares ownerlist is written in an older entity numbering than the
 *  spell-book ownerlists, so rows are realigned by the dominant per-save
 *  delta between each prepares row and the unique spell book containing its
 *  spell names. Mirrors bg3parser/lsmf.py parse_lsmf_prepared_spells.
 */
/** The camp-supply total shown next to the Long Rest button, or null.
 *
 *  game.camp.v0.TotalSuppliesComponent holds one u32 — but it is a cache the
 *  engine zeroes and only recomputes when the camp/rest system runs, so 0
 *  means "not cached", not "no supplies"; callers should treat 0 as absent.
 */
export function parseLsmfCampSupplies(blob: Uint8Array): number | null {
  const idx = lsmfComponentIndex(blob);
  const ts = idx.get('game.camp.v0.TotalSuppliesComponent');
  if (!ts || ts.elemSize !== 4 || ts.rowCount !== 1) return null;
  const { bytes, dv } = align(blob);
  if (ts.dataOffset + 4 > bytes.length) return null;
  return dv.getUint32(ts.dataOffset, true);
}

export function parseLsmfPreparedSpells(blob: Uint8Array): Map<number, [string, number, string][]> {
  const idx = lsmfComponentIndex(blob);
  const sp = idx.get('game.spell.v0.SpellBookPrepares');
  const et = idx.get('game.spell.v0.ESourceType');
  if (!sp || !et || sp.elemSize !== 80) return new Map();
  const { bytes, dv } = align(blob);
  const L = bytes.length;

  const sourcePool = new Map<number, number>();
  for (let r = 0; r < et.rowCount; r++) {
    const off = et.dataOffset + r * et.elemSize;
    if (off + et.elemSize > L) break;
    sourcePool.set(off - LSMF_HEAP_BASE, u64(dv, off));
  }

  const heapStr = (ptr: number, ln: number): string | null => {
    const p0 = ptr + LSMF_HEAP_BASE;
    if (!(ln > 0 && ln <= 128 && p0 > 0 && p0 <= L - ln)) return null;
    for (let i = 0; i < ln; i++) {
      const ch = bytes[p0 + i]!;
      if (ch < 0x20 || ch >= 0x7f) return null;
    }
    return new TextDecoder().decode(bytes.subarray(p0, p0 + ln));
  };

  const raw = new Map<number, [string, number, string][]>();
  for (let k = 0; k < sp.rowCount; k++) {
    const ent = sp.ownerRows[k]!;
    const base = sp.dataOffset + k * sp.elemSize;
    const begin = u64(dv, base + 48);
    const end = u64(dv, base + 56);
    const size = end - begin;
    if (!(begin >= 0 && begin < end && end <= L && size % 24 === 0 && size <= 24 * 4096)) {
      continue;
    }
    const entries: [string, number, string][] = [];
    for (let p = begin + LSMF_HEAP_BASE; p < end + LSMF_HEAP_BASE; p += 24) {
      const sptr = u64(dv, p);
      const ln = dv.getUint32(p + 8, true);
      const detail = u64(dv, p + 16);
      const name = heapStr(sptr, ln);
      if (name === null) continue;
      let sourceType = -1;
      let sourceGuid = '';
      const d0 = detail + LSMF_HEAP_BASE;
      if (d0 > 0 && d0 <= L - 24) {
        const eptr = u64(dv, d0);
        const st = sourcePool.get(eptr);
        if (st !== undefined) {
          sourceType = st;
          sourceGuid = guidLeStr(bytes, d0 + 8);
        }
      }
      entries.push([name, sourceType, sourceGuid]);
    }
    if (entries.length && entries.length > (raw.get(ent)?.length ?? 0)) raw.set(ent, entries);
  }

  // Realign the stale prepares numbering against the spell-book numbering.
  const books = parseLsmfSpellbooks(blob);
  const bookSets = new Map<number, Set<string>>();
  for (const [e, v] of books) bookSets.set(e, new Set(v));
  const deltas = new Map<number, number>();
  for (const [ent, entries] of raw) {
    const names = new Set(entries.map(([n]) => n));
    if (names.size < 8) continue;
    const cands: number[] = [];
    for (const [be, bs] of bookSets) {
      let overlap = 0;
      for (const n of names) if (bs.has(n)) overlap++;
      if (overlap >= 0.85 * names.size) cands.push(be);
    }
    if (cands.length === 1) {
      const d = cands[0]! - ent;
      deltas.set(d, (deltas.get(d) ?? 0) + 1);
    }
  }
  if (!deltas.size) return new Map();
  let delta = 0;
  let votes = 0;
  let total = 0;
  for (const [d, v] of deltas) {
    total += v;
    if (v > votes) {
      votes = v;
      delta = d;
    }
  }
  if (votes < 3 || votes < 0.5 * total) delta = 0;
  const out = new Map<number, [string, number, string][]>();
  for (const [ent, entries] of raw) out.set(ent + delta, entries);
  return out;
}

export function parseLsmfContainerPositions(blob: Uint8Array): Map<number, number> {
  const out = new Map<number, number>();
  for (const [ent, rows] of parseLsmfAllContainerPositions(blob)) out.set(ent, rows[0]!);
  return out;
}

/** Item entity GUID -> stack amount; see the Python docstring for the record
 *  layout and why only single-member records carry a usable amount. */
export function parseLsmfStackAmounts(blob: Uint8Array): Map<string, number> {
  const out = new Map<string, number>();
  const idx = lsmfComponentIndex(blob);
  const ns = idx.get('game.inventory.v0.NewStackComponent');
  const se = idx.get('game.inventory.v0.StackEntry');
  const eid = idx.get('core.v0.EntityId');
  if (!ns || !se || !eid) return out;
  const { bytes, dv } = align(blob);
  const L = bytes.length;
  const seB0 = se.dataOffset;
  const seB1 = se.dataOffset + se.rowCount * se.elemSize;
  for (let k = 0; k < ns.rowCount; k++) {
    const ptr = u64(dv, ns.dataOffset + k * ns.elemSize) + LSMF_HEAP_BASE;
    if (!(ptr >= 32 && ptr <= L - 32)) continue;
    const memLo = u64(dv, ptr);
    const memHi = u64(dv, ptr + 8);
    const seLo = u64(dv, ptr + 16);
    const seHi = u64(dv, ptr + 24);
    const n = memHi > memLo ? (memHi - memLo) / 8 : 0;
    if (!(n > 0 && n <= 256) || (memHi - memLo) % 8 !== 0 || memLo + LSMF_HEAP_BASE + n * 8 > L) {
      continue;
    }
    const a0 = seLo + LSMF_HEAP_BASE;
    const a1 = seHi + LSMF_HEAP_BASE;
    if (!(seB0 <= a0 && a0 < a1 && a1 <= seB1) || (a1 - a0) % 8 !== 0) continue;
    let total = 0;
    for (let w = a0; w < a1; w += 8) total += dv.getUint32(w + 4, true);
    if (total <= 0) continue;
    const members: string[] = [];
    for (let i = 0; i < n; i++) {
      const a = u64(dv, memLo + LSMF_HEAP_BASE + i * 8) + LSMF_HEAP_BASE;
      if (
        a >= eid.dataOffset &&
        a < eid.dataOffset + eid.rowCount * 16 &&
        (a - eid.dataOffset) % 16 === 0
      ) {
        members.push(guidLeStr(bytes, a));
      }
    }
    if (members.length === 1) out.set(members[0]!, total);
  }
  return out;
}

/** Extract every spell book: entity row -> ordered list of spell IDs. */
export function parseLsmfSpellbooks(blob: Uint8Array): Map<number, string[]> {
  const out = new Map<number, string[]>();
  const idx = lsmfComponentIndex(blob);
  const sb = idx.get('game.spell.v3.SpellBookComponent');
  const sd = idx.get('game.spell.v3.SpellData');
  const si = idx.get('game.spell.v0.SpellId');
  if (!sb || !sd || !si) return out;
  if (sb.elemSize !== 16 || sd.elemSize < 56 || si.elemSize !== 24) return out;
  const { bytes, dv } = align(blob);
  const L = bytes.length;
  const sdLo = sd.dataOffset;
  const sdHi = sd.dataOffset + sd.rowCount * sd.elemSize;
  const siLo = si.dataOffset;
  const siHi = si.dataOffset + si.rowCount * si.elemSize;
  const dec = new TextDecoder();

  const spellIdName = (row: number): string | null => {
    // Observed record shapes: {meta_ptr, str_ptr, len-packed} and
    // {str_ptr, len-packed, source_ptr}; try both (pointer, length) pairings.
    // len-packed fields carry a generation counter in the high dword; read
    // the low dword directly (a u64->Number round trip can corrupt low bits).
    const base = si.dataOffset + row * si.elemSize;
    const a = u64(dv, base);
    const b = u64(dv, base + 8);
    const bLo = dv.getUint32(base + 8, true);
    const cLo = dv.getUint32(base + 16, true);
    for (const [ptr, ln] of [
      [b, cLo],
      [a, bLo],
    ] as const) {
      const p0 = ptr + LSMF_HEAP_BASE;
      if (!(ln > 0 && ln <= 128 && p0 > 0 && p0 <= L - ln)) continue;
      const s = bytes.subarray(p0, p0 + ln);
      let printable = true;
      for (const ch of s) {
        if (ch < 0x20 || ch >= 0x7f) {
          printable = false;
          break;
        }
      }
      if (printable) return dec.decode(s);
    }
    return null;
  };

  for (let k = 0; k < Math.min(sb.ownerRows.length, sb.rowCount); k++) {
    const ent = sb.ownerRows[k]!;
    const begin = u64(dv, sb.dataOffset + k * sb.elemSize);
    const end = u64(dv, sb.dataOffset + k * sb.elemSize + 8);
    if (!(sdLo <= begin && begin <= end && end <= sdHi)) continue;
    const names: string[] = [];
    const r0 = Math.floor((begin - sdLo) / sd.elemSize);
    const r1 = Math.floor((end - sdLo) / sd.elemSize);
    for (let r = r0; r < r1; r++) {
      const v = u64(dv, sd.dataOffset + r * sd.elemSize + 48);
      if (siLo <= v && v < siHi) {
        const nm = spellIdName(Math.floor((v - siLo) / si.elemSize));
        if (nm) names.push(nm);
      }
    }
    if (names.length && names.length > (out.get(ent)?.length ?? 0)) out.set(ent, names);
  }
  return out;
}

export type ClassEntry = [classGuid: string, subclassGuid: string, level: number];

/** Extract class progressions: entity row -> [(class, subclass, level), …]. */
export function parseLsmfClasses(blob: Uint8Array): Map<number, ClassEntry[]> {
  const out = new Map<number, ClassEntry[]>();
  const idx = lsmfComponentIndex(blob);
  const cc = idx.get('game.stats.v0.ClassesComponent');
  if (cc?.elemSize !== 16) return out;
  const { bytes, dv } = align(blob);
  const L = bytes.length;
  for (let k = 0; k < Math.min(cc.ownerRows.length, cc.rowCount); k++) {
    const ent = cc.ownerRows[k]!;
    const begin = u64(dv, cc.dataOffset + k * cc.elemSize);
    const end = u64(dv, cc.dataOffset + k * cc.elemSize + 8);
    const size = end - begin;
    if (!(size > 0 && size <= 40 * 16 && size % 40 === 0)) continue;
    const p0 = begin + LSMF_HEAP_BASE;
    if (p0 + size > L) continue;
    let entries: ClassEntry[] = [];
    for (let i = 0; i < size / 40; i++) {
      const base = p0 + i * 40;
      const lvl = u64(dv, base + 32);
      if (lvl > 30) {
        entries = [];
        break;
      }
      entries.push([guidLeStr(bytes, base), guidLeStr(bytes, base + 16), lvl]);
    }
    if (entries.length) out.set(ent, entries);
  }
  return out;
}
