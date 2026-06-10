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
        nameLen > 0 && nameLen < 200 ? dec.decode(namesSec.subarray(nameOff, nameOff + nameLen)) : '';
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
      if (a >= eid.dataOffset && a < eid.dataOffset + eid.rowCount * 16 && (a - eid.dataOffset) % 16 === 0) {
        members.push(guidLeStr(bytes, a));
      }
    }
    if (members.length === 1) out.set(members[0]!, total);
  }
  return out;
}
