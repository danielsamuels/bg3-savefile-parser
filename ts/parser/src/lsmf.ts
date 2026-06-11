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
export const HIT_DIE: Record<string, [number, number]> = {
  Barbarian: [12, 7],
  Fighter: [10, 6],
  Paladin: [10, 6],
  Ranger: [10, 6],
  Bard: [8, 5],
  Cleric: [8, 5],
  Druid: [8, 5],
  Monk: [8, 5],
  Rogue: [8, 5],
  Warlock: [8, 5],
  Sorcerer: [6, 4],
  Wizard: [6, 4],
};

/** Map owner index k -> data record index j for stream-serialized components.
 *
 *  Some LSMF components serialize their rows as one packed stream (with a
 *  small stream header), and the ownerlist can contain a few entries with no
 *  data record ("phantoms"). The data record for owner k is then
 *  j = k - (phantoms before k): a monotone, non-decreasing shift, found by a
 *  small dynamic program maximizing validated owners. Ties prefer the higher
 *  shift (phantoms cluster early in the ownerlist).
 */
export function solveOwnerShifts(
  ownerCount: number,
  validAt: (k: number, j: number) => boolean,
  maxShift = 3,
): Map<number, number> {
  const NEG = -(1 << 30);
  let dp = [0, ...Array.from({ length: maxShift }, () => NEG)];
  const choice: number[][] = [];
  for (let k = 0; k < ownerCount; k++) {
    const gains = Array.from({ length: maxShift + 1 }, (_, sh) => (validAt(k, k - sh) ? 1 : 0));
    const ndp = Array.from({ length: maxShift + 1 }, () => NEG);
    const pred = Array.from({ length: maxShift + 1 }, () => 0);
    let best = NEG;
    let bestS = 0;
    for (let sh = 0; sh <= maxShift; sh++) {
      if (dp[sh]! >= best) {
        best = dp[sh]!;
        bestS = sh;
      }
      if (best > NEG) {
        ndp[sh] = best + gains[sh]!;
        pred[sh] = bestS;
      }
    }
    dp = ndp;
    choice.push(pred);
  }
  let sh = 0;
  for (let x = 0; x <= maxShift; x++) if (dp[x]! >= dp[sh]!) sh = x;
  const out = new Map<number, number>();
  for (let k = ownerCount - 1; k >= 0; k--) {
    out.set(k, k - sh);
    sh = choice[k]![sh]!;
  }
  return out;
}

/** Effective ability scores: entity row -> [STR,DEX,CON,INT,WIS,CHA].
 *  Mirrors bg3parser/lsmf.py parse_lsmf_ability_scores (packed stream with a
 *  20-byte header; 36-byte records straddling the nominal row grid). */
export function parseLsmfAbilityScores(blob: Uint8Array): Map<number, number[]> {
  const idx = lsmfComponentIndex(blob);
  const st = idx.get('game.stats.v3.StatsComponent');
  if (st?.elemSize !== 36) return new Map();
  const { dv } = align(blob);
  const L = blob.length;
  const levels = new Map<number, number>();
  for (const [ent, cls] of parseLsmfClasses(blob)) {
    levels.set(
      ent,
      cls.reduce((a: number, [, , lvl]: [string, string, number]) => a + lvl, 0),
    );
  }

  const rec = (j: number): number[] | null => {
    const p = st.dataOffset + 20 + j * st.elemSize;
    if (j < 0 || p + 36 > L) return null;
    return Array.from({ length: 9 }, (_, i) => dv.getInt32(p + i * 4, true));
  };

  const validAt = (k: number, j: number): boolean => {
    const v = rec(j);
    if (v === null) return false;
    const prof = v[6]!;
    if (v[8] !== 0 || !v.slice(0, 6).every((x) => x >= 1 && x <= 40) || prof < 0 || prof > 10) {
      return false;
    }
    const lvl = levels.get(st.ownerRows[k]!);
    if (lvl && lvl >= 1 && lvl <= 20) return prof === 2 + Math.floor((lvl - 1) / 4);
    return true;
  };

  const mapping = solveOwnerShifts(st.rowCount, validAt);
  const out = new Map<number, number[]>();
  for (let k = 0; k < st.rowCount; k++) {
    const ent = st.ownerRows[k]!;
    const j = mapping.get(k)!;
    if (validAt(k, j) && !out.has(ent)) out.set(ent, rec(j)!.slice(0, 6));
  }
  return out;
}

/** Hit points: entity row -> [current, max, temp, temp_max].
 *  Mirrors bg3parser/lsmf.py parse_lsmf_health (16-byte stream header,
 *  32-byte records, phantom shift validated by the class/CON HP formula). */
export function parseLsmfHealth(
  blob: Uint8Array,
  abilities: Map<number, number[]>,
  classNames: Record<string, string>,
): Map<number, number[]> {
  const idx = lsmfComponentIndex(blob);
  const hl = idx.get('game.stats.v0.HealthComponent');
  if (hl?.elemSize !== 32) return new Map();
  const { dv } = align(blob);
  const L = blob.length;

  const expected = new Map<number, number>();
  for (const [ent, cls] of parseLsmfClasses(blob)) {
    const ab = abilities.get(ent);
    if (!ab) continue;
    const conmod = Math.floor((ab[2]! - 10) / 2);
    let total = 0;
    let lvls = 0;
    for (const [cguid, , lvl] of cls as [string, string, number][]) {
      const die = HIT_DIE[classNames[cguid] ?? ''];
      if (!die) {
        total = 0;
        break;
      }
      total += (lvls === 0 ? die[0] : die[1]) + (lvl - (lvls === 0 ? 1 : 0)) * die[1];
      lvls += lvl;
    }
    if (total && lvls) expected.set(ent, total + conmod * lvls);
  }

  const rec = (j: number): number[] | null => {
    const p = hl.dataOffset + 16 + j * hl.elemSize;
    if (j < 0 || p + 16 > L) return null;
    return Array.from({ length: 4 }, (_, i) => dv.getInt32(p + i * 4, true));
  };

  const plausible = (j: number): boolean => {
    const v = rec(j);
    if (v === null) return false;
    const [cur, mx, temp, tempMax] = v as [number, number, number, number];
    return (
      mx > 0 &&
      mx <= 4000 &&
      cur >= 0 &&
      cur <= mx &&
      temp >= 0 &&
      temp <= 200 &&
      tempMax >= 0 &&
      tempMax <= 200
    );
  };

  const validAt = (k: number, j: number): boolean => {
    if (!plausible(j)) return false;
    const exp = expected.get(hl.ownerRows[k]!);
    return exp !== undefined && rec(j)![1] === exp;
  };

  const mapping = solveOwnerShifts(hl.rowCount, validAt);
  const out = new Map<number, number[]>();
  for (let k = 0; k < hl.rowCount; k++) {
    const ent = hl.ownerRows[k]!;
    const j = mapping.get(k)!;
    if (plausible(j) && !out.has(ent)) out.set(ent, rec(j)!);
  }
  return out;
}

export interface ResourceAmount {
  guid: string;
  level: number;
  amount: number;
  max: number;
  replenish: number;
}

/**
 * Action resources per entity (spell slots, rage, ki, superiority dice...).
 * Rows are a {begin, end} heap range of 64-byte AmountEntry records; the
 * ownerlist values are unreliable, the true mapping is positional:
 * entity = (row - offset) % (rows - 1), offset derived by majority vote.
 */
export function parseLsmfActionResources(blob: Uint8Array): Map<number, ResourceAmount[]> {
  const idx = lsmfComponentIndex(blob);
  const comp = idx.get('game.action_resources.v1.Component');
  const out = new Map<number, ResourceAmount[]>();
  if (comp?.elemSize !== 16 || comp.rowCount < 2 || comp.ownerRows.length < comp.rowCount) {
    return out;
  }
  const { dv } = align(blob);
  const L = blob.length;
  const rows = comp.rowCount;

  const votes = new Map<number, number>();
  for (let k = 0; k < rows; k++) {
    const d = k - comp.ownerRows[k]!;
    if (d >= 0 && d <= 64) votes.set(d, (votes.get(d) ?? 0) + 1);
  }
  if (!votes.size) return out;
  let offset = 0;
  let best = -1;
  for (const [d, n] of votes) {
    if (n > best) {
      best = n;
      offset = d;
    }
  }

  const decodeRow = (k: number): ResourceAmount[] | null => {
    const p = comp.dataOffset + k * comp.elemSize;
    const b = u64(dv, p);
    const e = u64(dv, p + 8);
    const size = e - b;
    const q0 = b + LSMF_HEAP_BASE;
    if (!(size > 0 && size < 64 * 300 && size % 64 === 0 && q0 > 0 && q0 <= L - size)) return null;
    const recs: ResourceAmount[] = [];
    for (let i = 0; i < size / 64; i++) {
      const q = q0 + i * 64;
      const guid = guidLeStr(blob, q);
      const lvl = dv.getInt32(q + 16, true);
      const pad = dv.getInt32(q + 20, true);
      const amount = dv.getFloat64(q + 24, true);
      const max = dv.getFloat64(q + 32, true);
      const replenish = u64(dv, q + 40);
      if (pad !== 0 || lvl < 0 || lvl > 9 || amount < 0 || max < 0 || replenish > 0x7f) return null;
      recs.push({ guid, level: lvl, amount, max, replenish });
    }
    return recs.length ? recs : null;
  };

  const order: number[] = [];
  for (let k = offset; k < rows; k++) order.push(k);
  for (let k = 0; k < offset; k++) order.push(k);
  for (const k of order) {
    const ent = (((k - offset) % (rows - 1)) + (rows - 1)) % (rows - 1);
    if (out.has(ent)) continue;
    const recs = decodeRow(k);
    if (recs) out.set(ent, recs);
  }
  return out;
}

/**
 * Active concentration per entity: entity -> spell ID. Rows are
 * {u64 caster ptr, u64 spell-name ptr (all-FF when idle), u32 len, u32 extra}.
 */
export function parseLsmfConcentration(blob: Uint8Array): Map<number, string> {
  const idx = lsmfComponentIndex(blob);
  const comp = idx.get('game.concentration.v0.ConcentrationComponent');
  const out = new Map<number, string>();
  if (comp?.elemSize !== 24) return out;
  const { dv } = align(blob);
  const L = blob.length;
  for (let k = 0; k < comp.ownerRows.length; k++) {
    if (k >= comp.rowCount || comp.dataOffset + (k + 1) * comp.elemSize > L) break;
    const p = comp.dataOffset + k * comp.elemSize;
    const hi = dv.getBigUint64(p + 8, true);
    if (hi === 0xffffffffffffffffn) continue;
    const ptr = Number(hi);
    const ln = dv.getUint32(p + 16, true);
    const p0 = ptr + LSMF_HEAP_BASE;
    if (!(ln > 0 && ln <= 128 && p0 > 0 && p0 <= L - ln)) continue;
    let ok = true;
    let name = '';
    for (let i = 0; i < ln; i++) {
      const c = blob[p0 + i]!;
      if (c < 0x20 || c >= 0x7f) {
        ok = false;
        break;
      }
      name += String.fromCharCode(c);
    }
    const ent = comp.ownerRows[k]!;
    if (ok && name && !out.has(ent)) out.set(ent, name);
  }
  return out;
}

export interface Portrait {
  name: string;
  webp: Uint8Array;
}

/**
 * Custom character portraits embedded in the save (creation order) plus the
 * Dream Guardian's. CCCI data rows are {begin,end} ranges over WebP bytes
 * behind the 3-row metadata prefix; the prefix's middle row is the Guardian.
 * Names chain in creation order through the CC stats rows (row0+56, then
 * each row's +80). Ground-truth verified by eye across three saves.
 */
export function parseLsmfPortraits(blob: Uint8Array): {
  portraits: Portrait[];
  guardian: Uint8Array | null;
} {
  const idx = lsmfComponentIndex(blob);
  const icon = idx.get('game.icon.v0.CharacterCreationCustomIconComponent');
  if (icon?.elemSize !== 16) return { portraits: [], guardian: null };
  const { dv } = align(blob);
  const L = blob.length;

  const webpAt = (p: number): Uint8Array | null => {
    if (p + 16 > L) return null;
    const b = u64(dv, p);
    const e = u64(dv, p + 8);
    if (!(b > 0 && b < e && e + LSMF_HEAP_BASE <= L)) return null;
    const img = blob.slice(b + LSMF_HEAP_BASE, e + LSMF_HEAP_BASE);
    return img[0] === 0x52 && img[1] === 0x49 && img[2] === 0x46 && img[3] === 0x46 ? img : null;
  };

  const guardian = webpAt(icon.dataOffset + 16);
  const names = parseLsmfCcCreationNames(blob);
  const portraits: Portrait[] = [];
  const base = icon.dataOffset + 48;
  for (let k = 0; k < icon.rowCount; k++) {
    const img = webpAt(base + k * icon.elemSize);
    if (img) portraits.push({ name: names[k] ?? '', webp: img });
  }
  return { portraits, guardian };
}

/** Created characters' names in creation order (see parseLsmfPortraits). */
export function parseLsmfCcCreationNames(blob: Uint8Array): string[] {
  const idx = lsmfComponentIndex(blob);
  const comp = idx.get('game.character_creation.v1.CharacterCreationStatsComponent');
  if (comp?.elemSize !== 88) return [];
  const { dv } = align(blob);
  const L = blob.length;
  const base = comp.dataOffset + 48;
  const nameAt = (p: number): string => {
    if (p + 8 > L) return '';
    const p0 = u64(dv, p) + LSMF_HEAP_BASE;
    if (!(p0 > 0 && p0 < L - 1)) return '';
    let name = '';
    for (let i = p0; i < Math.min(p0 + 80, L); i++) {
      const c = blob[i]!;
      if (c === 0) return name;
      if (c < 0x20 || c >= 0x7f) return '';
      name += String.fromCharCode(c);
    }
    return '';
  };
  const out = [nameAt(base + 56)];
  for (let k = 0; k < comp.rowCount - 1; k++) out.push(nameAt(base + k * comp.elemSize + 80));
  return out;
}

/**
 * Character names from CharacterCreationStatsComponent rows (88B behind a
 * 48-byte prefix; name pointer at +80), in row order. Covers the player,
 * origin companions, and hirelings' custom names.
 */
export function parseLsmfCcNames(blob: Uint8Array): string[] {
  const idx = lsmfComponentIndex(blob);
  const comp = idx.get('game.character_creation.v1.CharacterCreationStatsComponent');
  if (comp?.elemSize !== 88) return [];
  const { dv } = align(blob);
  const L = blob.length;
  const base = comp.dataOffset + 48;
  const out: string[] = [];
  for (let k = 0; k < comp.rowCount; k++) {
    const p = base + k * comp.elemSize;
    if (p + comp.elemSize > L) break;
    const p0 = u64(dv, p + 80) + LSMF_HEAP_BASE;
    if (!(p0 > 0 && p0 < L - 1)) continue;
    let name = '';
    let ok = true;
    for (let i = p0; i < Math.min(p0 + 80, L); i++) {
      const c = blob[i]!;
      if (c === 0) break;
      if (c < 0x20 || c >= 0x7f) {
        ok = false;
        break;
      }
      name += String.fromCharCode(c);
    }
    if (ok && name) out.push(name);
  }
  return out;
}

const LEVELUP_NULL_GUID = '00000000-0000-0000-0000-000000000000';
const NULL_PTR = 0xffffffffffffffffn;

const ABILITY_ENUM = [
  'None',
  'Strength',
  'Dexterity',
  'Constitution',
  'Intelligence',
  'Wisdom',
  'Charisma',
];

export interface LevelUpRecord {
  levels: [string, string][];
  feats: { guid: string; level: number; picks: string[] }[];
}

/**
 * Level-up history per created character: classes taken and feats picked.
 * See lsmf.py parse_lsmf_feats for the layout; the first three rows are
 * metadata (type GUID, heap-range header, sentinel), so per-character data
 * starts 48 bytes after the descriptor's data_offset.
 */
export function parseLsmfFeats(blob: Uint8Array): LevelUpRecord[] {
  const idx = lsmfComponentIndex(blob);
  const comp = idx.get('game.character_creation.v3.LevelUpComponent');
  if (comp?.elemSize !== 16) return [];
  const { dv } = align(blob);
  const L = blob.length;

  const abilityPool = new Map<number, number>();
  const ea = idx.get('game.character_creation.v1.EAbility');
  if (ea) {
    for (let r = 0; r < ea.rowCount; r++) {
      const p = ea.dataOffset + 48 + r * ea.elemSize;
      if (p + 8 <= L) abilityPool.set(ea.dataOffset + r * ea.elemSize, u64(dv, p));
    }
  }

  const abilityPicks = (begin: number, end: number): string[] => {
    const picks: string[] = [];
    if (!(begin > 0 && begin < end && end <= L && (end - begin) % 8 === 0)) return picks;
    for (let i = 0; i < (end - begin) / 8; i++) {
      const ptr = u64(dv, begin + LSMF_HEAP_BASE + 8 * i);
      const val = abilityPool.get(ptr);
      if (val !== undefined && val >= 0 && val < ABILITY_ENUM.length) {
        picks.push(ABILITY_ENUM[val]!);
      }
    }
    return picks;
  };

  const featPicks = (selPtr: number): string[] => {
    const p = selPtr + LSMF_HEAP_BASE;
    if (!(p > 0 && p <= L - 112)) return [];
    const fb = dv.getBigUint64(p, true);
    const fe = u64(dv, p + 8);
    if (fb === NULL_PTR || Number(fb) >= fe) return [];
    const out: string[] = [];
    for (let i = 0; i < (fe - Number(fb)) / 8; i++) {
      const sel = u64(dv, Number(fb) + LSMF_HEAP_BASE + 8 * i);
      const sp = sel + LSMF_HEAP_BASE;
      if (!(sp > 0 && sp <= L - 40)) continue;
      const pb = u64(dv, sp + 24);
      const pe = u64(dv, sp + 32);
      out.push(...abilityPicks(pb, pe));
    }
    return out;
  };

  const out: LevelUpRecord[] = [];
  const dataBase = comp.dataOffset + 48;
  for (let j = 0; j < comp.rowCount; j++) {
    const row = dataBase + j * comp.elemSize;
    if (row + comp.elemSize > L) break;
    const bRaw = dv.getBigUint64(row, true);
    const e = u64(dv, row + 8);
    if (bRaw === NULL_PTR) continue;
    const b = Number(bRaw);
    if (b >= e || e - b > 8 * 64) continue;
    const levels: [string, string][] = [];
    const feats: { guid: string; level: number; picks: string[] }[] = [];
    for (let k = 0; k < (e - b) / 8; k++) {
      const ptr = u64(dv, b + LSMF_HEAP_BASE + 8 * k);
      const p = ptr + LSMF_HEAP_BASE;
      if (!(p > 0 && p <= L - 96)) continue;
      const cls = guidLeStr(blob, p);
      const sub = guidLeStr(blob, p + 16);
      const feat = guidLeStr(blob, p + 32);
      levels.push([cls, sub]);
      if (feat !== LEVELUP_NULL_GUID) {
        const selPtr = u64(dv, p + 72);
        feats.push({ guid: feat, level: levels.length, picks: featPicks(selPtr) });
      }
    }
    if (levels.length) out.push({ levels, feats });
  }
  return out;
}

/**
 * Map known characters to their stats-entity rows via the template link:
 * stats_entity = world_entity + 1, wrapping modulo the character-entity
 * count. `templates` maps lowercase template GUID -> caller's name.
 */
export function parseLsmfStatsEntities(
  blob: Uint8Array,
  templates: Map<string, string>,
): Map<string, number> {
  const idx = lsmfComponentIndex(blob);
  const tc = idx.get('game.templates.v0.TemplateComponent');
  const cc = idx.get('game.stats.v0.ClassesComponent');
  const out = new Map<string, number>();
  if (!tc || !cc || !cc.ownerRows.length) return out;
  const { dv } = align(blob);
  const n = cc.ownerRows.length;
  const L = blob.length;
  for (let k = 0; k < tc.ownerRows.length; k++) {
    if (k >= tc.rowCount || tc.dataOffset + (k + 1) * tc.elemSize > L) break;
    const p = tc.dataOffset + k * tc.elemSize;
    const ptr = Number(dv.getBigInt64(p, true));
    const ln = dv.getUint32(p + 8, true);
    const p0 = ptr + LSMF_HEAP_BASE;
    if (!(ln > 0 && ln <= 40 && p0 >= 0 && p0 <= L - ln)) continue;
    let guid = '';
    for (let i = 0; i < ln; i++) guid += String.fromCharCode(blob[p0 + i]!);
    const name = templates.get(guid.toLowerCase());
    if (name !== undefined && !out.has(name)) out.set(name, (tc.ownerRows[k]! + 1) % n);
  }
  return out;
}

/** The party's unlocked crafting recipes, as stat names (ALCH_*). */
export function parseLsmfRecipes(blob: Uint8Array): string[] {
  const idx = lsmfComponentIndex(blob);
  const rd = idx.get('game.party.v0.RecipeData');
  if (rd?.elemSize !== 24) return [];
  const { dv } = align(blob);
  const L = blob.length;
  const out = new Set<string>();
  for (let k = 0; k < rd.rowCount; k++) {
    const p = rd.dataOffset + k * rd.elemSize;
    if (p + 24 > L) break;
    const ptr = u64(dv, p);
    const ln = dv.getUint32(p + 8, true);
    const p0 = ptr + LSMF_HEAP_BASE;
    if (!(ln > 0 && ln <= 128 && p0 > 0 && p0 <= L - ln)) continue;
    let ok = true;
    let name = '';
    for (let i = 0; i < ln; i++) {
      const c = blob[p0 + i]!;
      if (c < 0x20 || c >= 0x7f) {
        ok = false;
        break;
      }
      name += String.fromCharCode(c);
    }
    if (ok && name) out.add(name);
  }
  return [...out].sort();
}

export function parseLsmfCampSupplies(blob: Uint8Array): number | null {
  const idx = lsmfComponentIndex(blob);
  const ts = idx.get('game.camp.v0.TotalSuppliesComponent');
  if (ts?.elemSize !== 4 || ts.rowCount !== 1) return null;
  const { bytes, dv } = align(blob);
  // The u32 sits after a 48-byte metadata prefix (ground-truth verified).
  if (ts.dataOffset + 52 > bytes.length) return null;
  return dv.getUint32(ts.dataOffset + 48, true);
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
 *  layout. StackEntry is {u16 member-index, u16 pad, u32 amount}: a member's
 *  amount is the sum of its entries, so per-member amounts are exact. */
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
    const members: (string | null)[] = [];
    for (let i = 0; i < n; i++) {
      const a = u64(dv, memLo + LSMF_HEAP_BASE + i * 8) + LSMF_HEAP_BASE;
      if (
        a >= eid.dataOffset &&
        a < eid.dataOffset + eid.rowCount * 16 &&
        (a - eid.dataOffset) % 16 === 0
      ) {
        members.push(guidLeStr(bytes, a));
      } else {
        members.push(null); // keep indices aligned
      }
    }
    const perMember = new Map<number, number>();
    for (let w = a0; w < a1; w += 8) {
      const i = dv.getUint16(w, true);
      if (i < members.length) {
        perMember.set(i, (perMember.get(i) ?? 0) + dv.getUint32(w + 4, true));
      }
    }
    for (const [i, amount] of perMember) {
      const guid = members[i];
      if (guid !== null && guid !== undefined && amount > 1) out.set(guid, amount);
    }
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
