/** Party characters and per-character item classification.
 *  Mirrors bg3parser/party.py. */
import type { LsofNode } from './lsf.js';

export const PLAYER_CHAR_TEMPLATE = 'f08563b3-748d-4783-837b-b8620bc60b22';

/** The Dark Urge origin's shipped template; a Durge avatar is the player too. */
export const DARK_URGE_TEMPLATE = '1f69a29f-8284-4d1d-a0e6-fba9fb02ac56';

export const PLAYER_CHAR_TEMPLATES = new Set([PLAYER_CHAR_TEMPLATE, DARK_URGE_TEMPLATE]);

/** Info.json Origin values that mean "this is the player avatar". */
export const PLAYER_ORIGINS = new Set(['Generic', 'DarkUrge']);

export const PARTY_ORIGINS: Record<string, string> = {
  'c7c13742-bacd-460a-8f65-f864fe41f255': 'Astarion',
  'ad9af97d-75da-406a-ae13-7071c563f604': 'Gale',
  '7628bc0e-52b8-42a7-856a-13a6fd413323': 'Halsin',
  '91b6b200-7d00-4d62-8dc9-99e8339dfa1a': 'Jaheira',
  '2c76687d-93a2-477b-8b18-8a14b549304c': 'Karlach',
  '58a69333-40bf-8358-1d17-fff240d7fb12': "Lae'zel",
  '25721313-0c15-4935-8176-9f134385451b': 'Minthara',
  '0de603c5-42e2-4811-9dad-f652de080eba': 'Minsc',
  '3ed74f06-3c60-42dc-83f6-f034cb47c679': 'Shadowheart',
  'c774d764-4a17-48dc-b470-32ace9ce447d': 'Wyll',
};

export const NULL_UUID = '00000000-0000-0000-0000-000000000000';

// The camp chest ("Traveller's Chest") root templates, one per act/variant.
export const CAMP_CHEST_TEMPLATES = new Set([
  '65ad4dbc-74b2-47b6-bad4-1a109cfc9639',
  '96eab9d1-74b1-42f7-b1ad-061a9fcea8c4',
  '9b293d36-29f0-460c-bc81-2bdd4610a478',
  'b1487efd-4ae8-4747-866d-717df74169cd',
  'b5de2260-8e6b-4c2f-91eb-6f3133682a2f',
  'f68b5862-887c-4adf-b9f8-bb29e4d73b0f',
]);

// Characters within this distance of the camp chest count as "at camp".
export const CAMP_RADIUS = 100.0;

// Origin companions' fixed race and base class (static game facts).
export const ORIGIN_INFO: Record<string, [string, string]> = {
  Astarion: ['Elf_HighElf', 'Rogue'],
  Gale: ['Human', 'Wizard'],
  Halsin: ['Elf_WoodElf', 'Druid'],
  Jaheira: ['HalfElf_High', 'Druid'],
  Karlach: ['Tiefling_Zariel', 'Barbarian'],
  "Lae'zel": ['Githyanki', 'Fighter'],
  Minsc: ['Human', 'Ranger'],
  Minthara: ['Drow_LolthSworn', 'Paladin'],
  Shadowheart: ['HalfElf_High', 'Cleric'],
  Wyll: ['Human', 'Warlock'],
};

/** The camp chest's exact position key, or null ('0,0,0' = no camp yet). */
export function findCampChest(nodes: LsofNode[]): string | null {
  for (const nd of nodes) {
    if (
      nd.name === 'Item' &&
      CAMP_CHEST_TEMPLATES.has((nd.attrs.CurrentTemplate as string) ?? '')
    ) {
      const k = posKey(nd.attrs.Translate);
      if (k !== null) return k;
    }
  }
  return null;
}

/** quest_id -> current ObjectiveID, from the Journal's QuestsProgress map. */
export function parseJournalObjectives(nodes: LsofNode[]): Map<string, string> {
  const out = new Map<string, string>();
  const ji = nodes.findIndex((nd) => nd.name === 'Journal' && nd.parent === -1);
  if (ji === -1) return out;
  const walk = (i: number): void => {
    const nd = nodes[i]!;
    if (nd.name === 'QuestsProgress') {
      const qid = (nd.attrs.MapKey as string) ?? '';
      for (const mi of nd.children) {
        for (const qi of nodes[mi]!.children) {
          const q = nodes[qi]!;
          if (q.name === 'Quest' && q.attrs.QuestUnlocked && !q.attrs.QuestDisabled) {
            const obj = (q.attrs.ObjectiveID as string) ?? '';
            if (qid && obj) out.set(qid, obj);
          }
        }
      }
      return;
    }
    for (const c of nd.children) walk(c);
  };
  for (const c of nodes[ji]!.children) {
    if (nodes[c]!.name === 'Quests') walk(c);
  }
  return out;
}

export function campDistance(a: string, b: string): number {
  const pa = a.split(',').map(Number);
  const pb = b.split(',').map(Number);
  let sum = 0;
  for (let i = 0; i < Math.min(pa.length, pb.length); i++) sum += (pa[i]! - pb[i]!) ** 2;
  return Math.sqrt(sum);
}
export const EQUIPPED_FLAG_BIT = 0x04000000;

/** Translate tuples are dict keys in Python; use a string key in TS. */
export type PosKey = string;

export function posKey(t: unknown): PosKey | null {
  return Array.isArray(t) && t.length === 3 ? t.join(',') : null;
}

export function findPartyCharacterNodes(
  nodes: LsofNode[],
  playerName = 'Player',
): Map<string, number> {
  const found = new Map<string, number>();
  const charsRoot = nodes.findIndex((nd) => nd.name === 'Characters' && nd.parent === -1);
  if (charsRoot < 0) return found;
  const walk = (ni: number): void => {
    const nd = nodes[ni]!;
    const tmpl = nd.attrs.CurrentTemplate as string | undefined;
    if (tmpl && PLAYER_CHAR_TEMPLATES.has(tmpl)) found.set(playerName, ni);
    else if (tmpl && tmpl in PARTY_ORIGINS) found.set(PARTY_ORIGINS[tmpl]!, ni);
    for (const ci of nd.children) walk(ci);
  };
  for (const ci of nodes[charsRoot]!.children) walk(ci);
  return found;
}

/** The character node whose Translate equals pos exactly, or null. */
export function findCharacterNodeAt(
  nodes: LsofNode[],
  pos: [number, number, number],
): number | null {
  const charsRoot = nodes.findIndex((nd) => nd.name === 'Characters' && nd.parent === -1);
  if (charsRoot < 0) return null;
  const found: number[] = [];
  const walk = (ni: number): void => {
    const t = nodes[ni]!.attrs.Translate;
    if (
      Array.isArray(t) &&
      t.length === 3 &&
      t[0] === pos[0] &&
      t[1] === pos[1] &&
      t[2] === pos[2]
    ) {
      found.push(ni);
    }
    for (const c of nodes[ni]!.children) walk(c);
  };
  for (const c of nodes[charsRoot]!.children) walk(c);
  return found.length === 1 ? found[0]! : null;
}

export function collectStatusEquippedItems(
  nodes: LsofNode[],
  charNi: number,
): { entity: string; statusId: string }[] {
  const result: { entity: string; statusId: string }[] = [];
  const walk = (ni: number): void => {
    const nd = nodes[ni]!;
    if (nd.name === 'STATUS') {
      const src = (nd.attrs.SourceEquippedItem as string) ?? '';
      if (src && src !== NULL_UUID) {
        result.push({ entity: src, statusId: (nd.attrs.ID as string) ?? '' });
      }
    }
    for (const ci of nd.children) walk(ci);
  };
  for (const ci of nodes[charNi]!.children) walk(ci);
  return result;
}

export function buildEntityTemplateMap(nodes: LsofNode[], rootName: string): Map<string, string> {
  const result = new Map<string, string>();
  const factoryRoot = nodes.findIndex((nd) => nd.name === rootName && nd.parent === -1);
  if (factoryRoot < 0) return result;
  for (const childNi of nodes[factoryRoot]!.children) {
    const creatorsNi = nodes[childNi]!.children.find((ci) => nodes[ci]!.name === 'Creators');
    if (creatorsNi === undefined) continue;
    for (const ci of nodes[creatorsNi]!.children) {
      const ch = nodes[ci]!;
      const entity = (ch.attrs.Entity as string) ?? '';
      if (entity) result.set(entity, (ch.attrs.TemplateID as string) ?? '');
    }
  }
  return result;
}

function itemsFactoryArrays(nodes: LsofNode[]): { creators: number[]; items: number[] } | null {
  const itemsRoot = nodes.findIndex((nd) => nd.name === 'Items' && nd.parent === -1);
  if (itemsRoot < 0) return null;
  const factoryNi = nodes[itemsRoot]!.children[0];
  if (factoryNi === undefined) return null;
  const fc = nodes[factoryNi]!.children;
  const creatorsNi = fc.find((ci) => nodes[ci]!.name === 'Creators');
  const itemsNi = fc.find((ci) => nodes[ci]!.name === 'Items');
  if (creatorsNi === undefined || itemsNi === undefined) return null;
  return { creators: nodes[creatorsNi]!.children, items: nodes[itemsNi]!.children };
}

/** {`${posKey}|${stats}`: [entity_guid, …]} from the parallel Creators/Items arrays. */
export function buildInstanceEntityLists(nodes: LsofNode[]): Map<string, string[]> {
  const result = new Map<string, string[]>();
  const arrays = itemsFactoryArrays(nodes);
  if (!arrays) return result;
  const n = Math.min(arrays.creators.length, arrays.items.length);
  for (let i = 0; i < n; i++) {
    const entity = (nodes[arrays.creators[i]!]!.attrs.Entity as string) ?? '';
    const item = nodes[arrays.items[i]!]!;
    const tk = posKey(item.attrs.Translate);
    const stats = (item.attrs.Stats as string) ?? '';
    if (entity && tk && stats) {
      const key = `${tk}|${stats}`;
      const list = result.get(key);
      if (list) list.push(entity);
      else result.set(key, [entity]);
    }
  }
  return result;
}

export function buildTemplateStatsMap(nodes: LsofNode[]): Map<string, string> {
  const result = new Map<string, string>();
  const itemsRoot = nodes.findIndex((nd) => nd.name === 'Items' && nd.parent === -1);
  if (itemsRoot < 0) return result;
  const factoryNi = nodes[itemsRoot]!.children[0];
  if (factoryNi === undefined) return result;
  const itemsNi = nodes[factoryNi]!.children.find((ci) => nodes[ci]!.name === 'Items');
  let candidates: number[] = [];
  if (itemsNi !== undefined) {
    candidates = nodes[itemsNi]!.children;
  } else {
    for (const childNi of nodes[factoryNi]!.children) {
      for (const ci of nodes[childNi]!.children) {
        const nm = nodes[ci]!.name;
        if (nm === 'Item' || nm === 'GameObjects') candidates.push(ci);
      }
    }
  }
  for (const ci of candidates) {
    const item = nodes[ci]!;
    const tmpl = (item.attrs.CurrentTemplate as string) ?? '';
    const stats = (item.attrs.Stats as string) ?? '';
    if (tmpl && stats && !result.has(tmpl)) result.set(tmpl, stats);
  }
  return result;
}

// Item stats-name prefixes / substrings that are never worn equipment.
const NON_EQUIP_PREFIXES = [
  'OBJ_',
  'CONS_',
  'ALCH_',
  'FOOD_',
  'SCR_',
  'SCROLL_',
  'BOOK_',
  'LOOT_',
  'KEY_',
  'PUZ_',
  'PLT_',
  'TItem_',
  'GOLD_',
];

const NON_EQUIP_SUBSTR = [
  '_Camp_',
  'Underwear',
  'Keychain',
  'GoldPile',
  'Backpack',
  'AlchemyPouch',
  'CampSupplies',
];

export function isEquipmentType(stats: string): boolean {
  if (!stats) return false;
  if (NON_EQUIP_PREFIXES.some((p) => stats.startsWith(p))) return false;
  return !NON_EQUIP_SUBSTR.some((s) => stats.includes(s));
}

export function collectCharacterPositions(
  nodes0: LsofNode[],
  partyNodes: Map<string, number>,
): Map<string, PosKey> {
  const out = new Map<string, PosKey>();
  for (const [name, ni] of partyNodes) {
    const tk = posKey(nodes0[ni]!.attrs.Translate);
    if (tk) out.set(name, tk);
  }
  return out;
}

export type AttributedItem = [stats: string, flags: number | unknown, guid: string];

/** Group Item records by which character's exact Translate they share. */
export function collectItemsByPosition(
  nodeLists: LsofNode[][],
  positions: Map<string, PosKey>,
): Map<string, AttributedItem[]> {
  const pos2name = new Map<PosKey, string>();
  for (const [n, t] of positions) pos2name.set(t, n);
  const acc = new Map<string, Map<string, [number | unknown, string]>>();
  for (const n of positions.keys()) acc.set(n, new Map());
  for (const nodes of nodeLists) {
    for (const nd of nodes) {
      if (nd.name !== 'Item') continue;
      const tk = posKey(nd.attrs.Translate);
      const name = tk ? pos2name.get(tk) : undefined;
      if (name === undefined) continue;
      const stats = (nd.attrs.Stats as string) ?? '';
      if (!stats) continue;
      const flags = nd.attrs.Flags ?? 0;
      const guid = (nd.attrs.CurrentTemplate as string) ?? '';
      const charAcc = acc.get(name)!;
      const prev = charAcc.get(stats);
      // Keep the record whose Flags carry the equipped bit so a clear-flagged
      // duplicate can't hide it.
      if (
        prev === undefined ||
        (typeof flags === 'number' &&
          (flags & EQUIPPED_FLAG_BIT) !== 0 &&
          !(typeof prev[0] === 'number' && (prev[0] & EQUIPPED_FLAG_BIT) !== 0))
      ) {
        charAcc.set(stats, [flags, guid]);
      }
    }
  }
  const out = new Map<string, AttributedItem[]>();
  for (const [n, d] of acc)
    out.set(
      n,
      [...d.entries()].map(([s, [f, g]]) => [s, f, g]),
    );
  return out;
}

export type ItemPair = [stats: string, guid: string];

/** Python-compatible sorted(set(...)) over (stats, guid) pairs. */
function sortedUniquePairs(pairs: ItemPair[]): ItemPair[] {
  const seen = new Map<string, ItemPair>();
  for (const p of pairs) seen.set(`${p[0]}\x00${p[1]}`, p);
  return [...seen.keys()].sort().map((k) => seen.get(k)!);
}

/** Classify attributed items into (equipped, carried, undetermined) using LSF signals. */
export function splitEquippedCarried(
  items: AttributedItem[],
  statusEquipped: Set<string>,
  objectTypeStats?: Set<string>,
): { equipped: ItemPair[]; carried: ItemPair[]; undetermined: ItemPair[] } {
  const equipped: ItemPair[] = [];
  const carried: ItemPair[] = [];
  const undetermined: ItemPair[] = [];
  for (const [stats, flags, guid] of items) {
    if (objectTypeStats?.has(stats)) {
      carried.push([stats, guid]);
      continue;
    }
    const signalled =
      statusEquipped.has(stats) ||
      (typeof flags === 'number' && (flags & EQUIPPED_FLAG_BIT) !== 0 && isEquipmentType(stats));
    if (signalled) equipped.push([stats, guid]);
    else if (isEquipmentType(stats)) undetermined.push([stats, guid]);
    else carried.push([stats, guid]);
  }
  return {
    equipped: sortedUniquePairs(equipped),
    carried: sortedUniquePairs(carried),
    undetermined: sortedUniquePairs(undetermined),
  };
}

export function invertEntityTemplateMap(e2t: Map<string, string>): Map<string, string[]> {
  const result = new Map<string, string[]>();
  for (const [eg, tg] of e2t) {
    const list = result.get(tg);
    if (list) list.push(eg);
    else result.set(tg, [eg]);
  }
  return result;
}

export function equipmentCluster(
  anchorRows: number[],
  margin = 8,
  trim = 24,
): [number, number] | null {
  if (anchorRows.length < 2) return null;
  const med = [...anchorRows].sort((a, b) => a - b)[anchorRows.length >> 1]!;
  const kept = anchorRows.filter((r) => Math.abs(r - med) <= trim);
  if (kept.length < 2) return null;
  return [Math.min(...kept) - margin, Math.max(...kept) + margin];
}

export const SLOT_CAPACITY: Record<string, number> = { Ring: 2 };

// Slots whose items stay in the backpack grid while equipped.
export const CLUSTER_EXEMPT_SLOTS = new Set(['MusicalInstrument']);

export function clusterAnchorRows(
  flagsEquipped: ItemPair[],
  statsToSlot: Record<string, string>,
  statsToEntity: Map<string, string>,
  guidToRows: Map<string, number[]>,
  allCsd: Map<number, number[]>,
): number[] {
  const slotCounts = new Map<string, number>();
  for (const [stats] of flagsEquipped) {
    const slot = statsToSlot[stats];
    if (slot) slotCounts.set(slot, (slotCounts.get(slot) ?? 0) + 1);
  }
  const rowSets: number[][] = [];
  for (const [stats] of flagsEquipped) {
    const slot = statsToSlot[stats];
    if (!slot || CLUSTER_EXEMPT_SLOTS.has(slot)) continue;
    if (slotCounts.get(slot)! > (SLOT_CAPACITY[slot] ?? 1)) continue;
    const eg = statsToEntity.get(stats) ?? '';
    const rows = new Set<number>();
    for (const er of guidToRows.get(eg) ?? []) for (const r of allCsd.get(er) ?? []) rows.add(r);
    if (rows.size) rowSets.push([...rows].sort((a, b) => a - b));
  }
  if (!rowSets.length) return [];
  const singles = rowSets
    .filter((rs) => rs.length === 1)
    .map((rs) => rs[0]!)
    .sort((a, b) => a - b);
  const med = singles.length ? singles[singles.length >> 1]! : rowSets[0]![0]!;
  return rowSets.map((rs) =>
    rs.reduce((best, r) => (Math.abs(r - med) < Math.abs(best - med) ? r : best)),
  );
}

export function csdClusterMembership(
  stats: string,
  cluster: [number, number],
  statsToEntity: Map<string, string>,
  guidToRows: Map<string, number[]>,
  allCsd: Map<number, number[]>,
): boolean | null {
  const eg = statsToEntity.get(stats) ?? '';
  const rows: number[] = [];
  for (const er of guidToRows.get(eg) ?? []) rows.push(...(allCsd.get(er) ?? []));
  if (!rows.length) return null;
  const [lo, hi] = cluster;
  return rows.some((r) => lo <= r && r <= hi);
}

export interface EcsResolveOptions {
  threshold?: number;
  statsToEntity?: Map<string, string>;
  wieldedRows?: Set<number>;
  csdCluster?: [number, number] | null;
  allCsd?: Map<number, number[]>;
}

/** Classify undetermined items via ECS component membership counts. */
export function ecsResolveEquipped(
  undetermined: ItemPair[],
  templateToInstances: Map<string, string[]>,
  guidToRows: Map<string, number[]>,
  membershipCount: Map<number, number>,
  opts: EcsResolveOptions = {},
): { equipped: ItemPair[]; carried: ItemPair[]; undetermined: ItemPair[] } {
  const threshold = opts.threshold ?? 15;
  const nowEquipped: ItemPair[] = [];
  const nowCarried: ItemPair[] = [];
  const still: ItemPair[] = [];
  for (const [stats, tmplGuid] of undetermined) {
    let rows: number[];
    const eg = opts.statsToEntity?.get(stats);
    if (eg !== undefined) {
      rows = guidToRows.get(eg) ?? [];
    } else {
      rows = [];
      for (const ig of templateToInstances.get(tmplGuid) ?? []) {
        rows.push(...(guidToRows.get(ig) ?? []));
      }
    }
    if (!rows.length) {
      still.push([stats, tmplGuid]);
      continue;
    }
    const maxMc = Math.max(...rows.map((r) => membershipCount.get(r) ?? 0));
    let inCluster: boolean | null = null;
    if (opts.csdCluster && opts.allCsd) {
      const csdRows: number[] = [];
      for (const er of rows) csdRows.push(...(opts.allCsd.get(er) ?? []));
      if (csdRows.length) {
        const [lo, hi] = opts.csdCluster;
        inCluster = csdRows.some((r) => lo <= r && r <= hi);
      }
    }
    let worn: boolean;
    if (inCluster !== null) {
      worn = inCluster && maxMc >= threshold;
    } else {
      const inWielded =
        opts.wieldedRows !== undefined && rows.some((r) => opts.wieldedRows!.has(r));
      worn = maxMc >= threshold && !inWielded;
    }
    (worn ? nowEquipped : nowCarried).push([stats, tmplGuid]);
  }
  return { equipped: nowEquipped, carried: nowCarried, undetermined: still };
}

export interface SlotConflictOptions {
  ownedAsLootRows?: Set<number>;
  twoHandedStats?: Set<string>;
  statusEquipped?: Set<string>;
  wieldedRows?: Set<number>;
  gravityDisabledRows?: Set<number>;
  csdCluster?: [number, number] | null;
  allCsd?: Map<number, number[]>;
}

/** Resolve cases where more items are signalled for a slot than it can hold. */
export function resolveSlotConflicts(
  flagsEquipped: ItemPair[],
  ecsEquipped: ItemPair[],
  statsToSlot: Record<string, string>,
  statsToEntity: Map<string, string>,
  guidToRows: Map<string, number[]>,
  membershipCount: Map<number, number>,
  opts: SlotConflictOptions = {},
): { keptFlags: ItemPair[]; keptEcs: ItemPair[]; demoted: ItemPair[] } {
  const getMc = (stats: string): number => {
    const eg = statsToEntity.get(stats);
    if (!eg) return 0;
    const rows = guidToRows.get(eg) ?? [];
    return rows.length ? Math.max(...rows.map((r) => membershipCount.get(r) ?? 0)) : 0;
  };
  const inRows = (stats: string, rows?: Set<number>): boolean => {
    if (!rows) return false;
    const eg = statsToEntity.get(stats);
    if (!eg) return false;
    return (guidToRows.get(eg) ?? []).some((r) => rows.has(r));
  };
  const inCluster = (stats: string): boolean | null => {
    if (!opts.csdCluster || !opts.allCsd) return null;
    return csdClusterMembership(stats, opts.csdCluster, statsToEntity, guidToRows, opts.allCsd);
  };

  const slotCandidates = new Map<string, [string, string, 'flags' | 'ecs'][]>();
  const noSlotFlags: ItemPair[] = [];
  const noSlotEcs: ItemPair[] = [];
  const demoted: ItemPair[] = [];

  for (const [stats, guid] of flagsEquipped) {
    // A Flags item located outside the cluster has a stale equip bit.
    // Virtual slots are exempt — their items stay in the grid while worn.
    if (
      inCluster(stats) === false &&
      !CLUSTER_EXEMPT_SLOTS.has(statsToSlot[stats] ?? '') &&
      !opts.statusEquipped?.has(stats)
    ) {
      demoted.push([stats, guid]);
      continue;
    }
    const slot = statsToSlot[stats];
    if (slot) {
      const list = slotCandidates.get(slot) ?? [];
      list.push([stats, guid, 'flags']);
      slotCandidates.set(slot, list);
    } else noSlotFlags.push([stats, guid]);
  }
  for (const [stats, guid] of ecsEquipped) {
    const slot = statsToSlot[stats];
    if (slot) {
      const list = slotCandidates.get(slot) ?? [];
      list.push([stats, guid, 'ecs']);
      slotCandidates.set(slot, list);
    } else noSlotEcs.push([stats, guid]);
  }

  const keptFlags: ItemPair[] = [...noSlotFlags];
  const keptEcs: ItemPair[] = [...noSlotEcs];

  const flagsSortKey = (stats: string): number[] => [
    opts.statusEquipped?.has(stats) ? 0 : 1,
    inCluster(stats) ? 0 : 1,
    inRows(stats, opts.wieldedRows) || inRows(stats, opts.gravityDisabledRows) ? 0 : 1,
    inRows(stats, opts.ownedAsLootRows) ? 0 : 1,
    -getMc(stats),
  ];
  const cmpKeys = (a: number[], b: number[]): number => {
    for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return a[i]! - b[i]!;
    return 0;
  };

  for (const [slot, candidates] of slotCandidates) {
    let capacity = SLOT_CAPACITY[slot] ?? 1;
    if (slot === 'Melee Main Weapon') {
      const pair = candidates.filter(
        ([s, , sig]) => sig === 'flags' && inCluster(s) && !opts.twoHandedStats?.has(s),
      );
      if (pair.length === 2) capacity = 2;
    }
    if (candidates.length <= capacity) {
      for (const [stats, guid, sig] of candidates) {
        (sig === 'flags' ? keptFlags : keptEcs).push([stats, guid]);
      }
      continue;
    }
    const flagsCands: ItemPair[] = candidates
      .filter(([, , s]) => s === 'flags')
      .map(([a, b]) => [a, b]);
    const ecsCands: ItemPair[] = candidates
      .filter(([, , s]) => s === 'ecs')
      .map(([a, b]) => [a, b]);
    if (flagsCands.length) {
      const sorted = [...flagsCands].sort((a, b) =>
        cmpKeys(flagsSortKey(a[0]), flagsSortKey(b[0])),
      );
      const winners = sorted.slice(0, capacity);
      keptFlags.push(...winners);
      demoted.push(...flagsCands.filter((sg) => !winners.includes(sg)));
      demoted.push(...(flagsCands.length && ecsCands.length ? ecsCands : []));
      if (!ecsCands.length) continue;
    } else {
      const sorted = [...ecsCands].sort((a, b) => getMc(b[0]) - getMc(a[0]));
      const winners = sorted.slice(0, capacity);
      keptEcs.push(...winners);
      demoted.push(...ecsCands.filter((sg) => !winners.includes(sg)));
    }
  }

  // 2-handed weapon in Melee Main Weapon blocks the offhand slot entirely.
  if (opts.twoHandedStats) {
    const mainHasTwoHanded = keptFlags.some(
      ([s]) => opts.twoHandedStats!.has(s) && statsToSlot[s] === 'Melee Main Weapon',
    );
    if (mainHasTwoHanded) {
      const stillKept: ItemPair[] = [];
      for (const sg of keptEcs) {
        if (statsToSlot[sg[0]] === 'Melee Offhand Weapon') demoted.push(sg);
        else stillKept.push(sg);
      }
      keptEcs.length = 0;
      keptEcs.push(...stillKept);
    }
  }

  return { keptFlags, keptEcs, demoted };
}
