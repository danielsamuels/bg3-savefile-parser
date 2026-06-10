/** Report model: gather everything the views need from a parsed save.
 *  Mirrors bg3parser/model.py; the output object matches `bg3save --json`
 *  field-for-field (the TS-parity contract). */
import type { DisplayNames } from './gamedata.js';
import type { LsofNode } from './lsf.js';
import { parseLsof } from './lsf.js';
import {
  GRAVITY_DISABLED_COMP,
  OWNED_AS_LOOT_COMP,
  parseLsmfAllContainerPositions,
  parseLsmfClasses,
  parseLsmfComponentRows,
  parseLsmfContainerPositions,
  parseLsmfMembership,
  parseLsmfSpellbooks,
  parseLsmfStackAmounts,
  WIELDED_COMP,
} from './lsmf.js';
import { decompFrame, extractFrames, parseInfoJson } from './lspk.js';
import { parseOsiris } from './osiris.js';
import {
  type AttributedItem,
  buildEntityTemplateMap,
  buildInstanceEntityLists,
  buildTemplateStatsMap,
  CAMP_RADIUS,
  campDistance,
  clusterAnchorRows,
  collectCharacterPositions,
  collectItemsByPosition,
  collectStatusEquippedItems,
  ecsResolveEquipped,
  equipmentCluster,
  findCampChest,
  findPartyCharacterNodes,
  type ItemPair,
  invertEntityTemplateMap,
  isEquipmentType,
  NULL_UUID,
  ORIGIN_INFO,
  resolveSlotConflicts,
  splitEquippedCarried,
} from './party.js';

export const COMMON_ACTION_SPELLS = new Set([
  'Shout_Dash',
  'Shout_Dash_NPC',
  'Shout_Disengage',
  'Shout_Hide',
  'Target_Shove',
  'Target_Help',
  'Target_Dip',
  'Throw_Throw',
  'Throw_ImprovisedWeapon',
  'Projectile_Jump',
  'Target_MainHandAttack',
  'Projectile_MainHandAttack',
  'Target_OffhandAttack',
  'Projectile_OffhandAttack',
  'Target_UnarmedAttack',
]);

export interface ItemRef {
  stats: string;
  template_guid: string;
  name: string | null;
  slot: string | null;
  slot_rank: number[];
  category: string;
  count: number;
}

export interface SpellRef {
  id: string;
  name: string | null;
  category: string;
}

export interface CharacterReport {
  name: string;
  race: string;
  classes: unknown[];
  level: unknown;
  xp: number | null;
  location: string;
  spells: SpellRef[] | null;
  spells_note: string | null;
  equipped: ItemRef[];
  undetermined: ItemRef[];
  carried: ItemRef[];
  equipment_note: string | null;
  inspect: null;
  at_camp: boolean;
}

export interface SaveInfo {
  save_name: string;
  save_id: number | null;
  saved_at: string;
  game_version: string;
  level: string;
  difficulty: string;
  leader: string;
  game_id: string;
  mods: string[];
  has_unofficial_mods: boolean;
}

export interface QuestRef {
  id: string;
  name: string | null;
}

/** Mirrors the Python quests dict: the failed shape carries only `failed`. */
export type QuestsReport =
  | { failed: true }
  | {
      failed: false;
      version: number;
      active: QuestRef[];
      closed: QuestRef[];
      goals_finalized: string[];
      global_flags: string[];
      global_flags_total: number;
    };

export interface GatherOpts {
  quests?: boolean;
}

export interface SaveReport {
  source: string;
  characters: CharacterReport[];
  save_info: SaveInfo;
  camp_chest: ItemRef[] | null;
  quests: QuestsReport | null;
  level_items: null;
  inspect_pattern: string;
  names_resolved: boolean;
}

// Base-game modules excluded from the user-mod list (mirrors lspk.py).
const BASE_MODULES = new Set([
  'GustavX',
  'Shared',
  'SharedDev',
  'Gustav',
  'Halflings',
  'Origins',
  'Honour',
  'DiceSet01',
  'DiceSet02',
  'DiceSet03',
  'DiceSet04',
  'DiceSet05',
  'DiceSet06',
  'DiceSet07',
]);

// Fallback when an item has no stat-file slot (or no game data present).
const ITEM_GROUP_BY_PREFIX: Record<string, string> = {
  WPN: 'weapon',
  MAG: 'weapon',
  ARM: 'armour',
  UNI: 'armour',
  ALCH: 'consumable',
  CONS: 'consumable',
  FOOD: 'consumable',
  BOOK: 'book',
  SCR: 'book',
};

export function itemCategory(stats: string, dn: DisplayNames): string {
  const slot = dn.statsToSlot[stats];
  if (slot) return slot.includes('Weapon') ? 'weapon' : 'armour';
  const parts = stats.split('_');
  if (parts[0] === 'OBJ' && parts.length > 1) {
    if (parts[1] === 'Potion' || parts[1] === 'Drink') return 'consumable';
    if (parts[1] === 'Scroll' || parts[1] === 'Book') return 'book';
  }
  return ITEM_GROUP_BY_PREFIX[parts[0]!] ?? 'misc';
}

// Display order for equipped items, mirroring the in-game panel.
export const SLOT_DISPLAY_ORDER = new Map<string, number>(
  [
    'Helmet',
    'Cloak',
    'Breast',
    'Gloves',
    'Boots',
    'Amulet',
    'Ring',
    'Melee Main Weapon',
    'Melee Offhand Weapon',
    'Ranged Main Weapon',
    'Ranged Offhand Weapon',
    'MusicalInstrument',
    'Underwear',
    'VanityBody',
    'VanityBoots',
  ].map((n, i) => [n, i]),
);

const pairKey = (p: ItemPair) => `${p[0]}\x00${p[1]}`;

function sortedUnion(...lists: ItemPair[][]): ItemPair[] {
  const seen = new Map<string, ItemPair>();
  for (const list of lists) for (const p of list) seen.set(pairKey(p), p);
  return [...seen.entries()].sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)).map(([, p]) => p);
}

interface InfoCharacter {
  Origin?: string;
  Race?: string;
  Classes?: { Main?: string; Sub?: string }[];
  Level?: unknown;
  'Experience Points (Total)'?: number;
  Subregion?: string;
}

/** Run the extraction pipeline and return the structured report model. */
export function gatherReport(
  data: Uint8Array,
  dn: DisplayNames,
  source = '',
  opts?: GatherOpts,
): SaveReport {
  const frames = extractFrames(data);
  const info = parseInfoJson(frames) as {
    'Active Party'?: { Characters?: InfoCharacter[] };
    'Save Name'?: string;
    'Game Version'?: string;
    'Current Level'?: string;
    Difficulty?: string[];
  };
  const partyInfo = info['Active Party']?.Characters ?? [];

  const metaNodes = parseLsof(decompFrame(frames.get('meta.lsf')!));
  const meta = metaNodes.find((n) => n.name === 'MetaData' && Object.keys(n.attrs).length > 0);
  const metaAttrs = meta?.attrs ?? {};
  const leaderName = (metaAttrs.LeaderName as string) ?? '';
  const playerDisplayName = leaderName ? `${leaderName} (player)` : 'Player';

  const userMods: string[] = [];
  for (const nd of metaNodes) {
    if (nd.name !== 'ModuleShortDesc') continue;
    const modName = (nd.attrs.Name as string) ?? '';
    const modFolder = (nd.attrs.Folder as string) ?? '';
    if ((modName || modFolder) && !BASE_MODULES.has(modName)) userMods.push(modName);
  }

  const saveTime = metaAttrs.SaveTime as number | undefined;
  let savedAt = '?';
  if (saveTime !== undefined && saveTime !== null) {
    const dt = new Date(saveTime * 1000);
    savedAt = Number.isFinite(dt.getTime())
      ? `${dt.toISOString().slice(0, 10)} ${dt.toISOString().slice(11, 19)} UTC`
      : String(saveTime);
  }
  const saveInfo: SaveInfo = {
    save_name: info['Save Name'] ?? '?',
    save_id: (metaAttrs.SaveGameID as number | undefined) ?? null,
    saved_at: savedAt,
    game_version: info['Game Version'] ?? '?',
    level: info['Current Level'] ?? '?',
    difficulty: (info.Difficulty ?? []).join(', '),
    leader: leaderName,
    game_id: (metaAttrs.GameID as string) ?? '',
    mods: userMods,
    has_unofficial_mods: Boolean(metaAttrs.HasUnofficialMods ?? false),
  };

  const nodes0 = parseLsof(decompFrame(frames.get('Globals.lsf')!));
  const partyNodes = findPartyCharacterNodes(nodes0, playerDisplayName);
  const entityToTemplate0 = buildEntityTemplateMap(nodes0, 'Items');
  const templateToStats0 = buildTemplateStatsMap(nodes0);
  const charPositions = collectCharacterPositions(nodes0, partyNodes);

  let lsmfBlob: Uint8Array | null = null;
  for (const nd of nodes0) {
    if (nd.name === 'NewAge' && nd.parent === -1) {
      const raw = nd.attrs.NewAge;
      if (raw instanceof Uint8Array) lsmfBlob = raw;
      break;
    }
  }

  const spellbooks = lsmfBlob ? parseLsmfSpellbooks(lsmfBlob) : new Map<number, string[]>();
  const entityClasses = lsmfBlob ? parseLsmfClasses(lsmfBlob) : new Map();
  const classNames = dn.classUuidNames;

  const buildKey = (ci: InfoCharacter): string | null => {
    const want = (ci.Classes ?? []).map((c) => `${c.Main ?? ''}\x00${c.Sub ?? ''}`).sort();
    if (!want.length || ci.Level === undefined || ci.Level === null) return null;
    return `${want.join('\x01')}|${ci.Level}`;
  };
  const partyBuilds = partyInfo.map(buildKey).filter((k): k is string => k !== null);
  const ambiguousBuilds = new Set(
    partyBuilds.filter((k, _i, a) => a.filter((x) => x === k).length > 1),
  );

  const exactSpellbook = (ci: InfoCharacter): string[] | null => {
    const key = buildKey(ci);
    if (key === null || ambiguousBuilds.has(key)) return null;
    const want = (ci.Classes ?? []).map((c) => `${c.Main ?? ''}\x00${c.Sub ?? ''}`).sort();
    const level = Number(ci.Level);
    const candidates: number[] = [];
    for (const [ent, classes] of entityClasses) {
      if (!spellbooks.has(ent)) continue;
      const got = classes
        .map(
          ([cg, sg]: [string, string, number]) =>
            `${classNames[cg] ?? ''}\x00${sg !== NULL_UUID ? (classNames[sg] ?? '') : ''}`,
        )
        .sort();
      const total = classes.reduce(
        (acc: number, [, , lvl]: [string, string, number]) => acc + lvl,
        0,
      );
      if (
        got.length === want.length &&
        got.every((g: string, i: number) => g === want[i]) &&
        total === level
      ) {
        candidates.push(ent);
      }
    }
    if (!candidates.length) return null;
    const best = candidates.reduce((a, b) =>
      (spellbooks.get(b)?.length ?? 0) > (spellbooks.get(a)?.length ?? 0) ? b : a,
    );
    return spellbooks.get(best)!;
  };

  const lsmfEcs = lsmfBlob ? parseLsmfMembership(lsmfBlob) : null;
  const compRows = lsmfBlob
    ? parseLsmfComponentRows(lsmfBlob, [OWNED_AS_LOOT_COMP, WIELDED_COMP, GRAVITY_DISABLED_COMP])
    : new Map<string, Set<number>>();
  const lsmfOwnedLoot = compRows.get(OWNED_AS_LOOT_COMP);
  const lsmfWielded = compRows.get(WIELDED_COMP);
  const lsmfGravityOff = compRows.get(GRAVITY_DISABLED_COMP);
  const lsmfCsdPos = lsmfBlob ? parseLsmfContainerPositions(lsmfBlob) : new Map<number, number>();
  const lsmfAllCsd = lsmfBlob
    ? parseLsmfAllContainerPositions(lsmfBlob)
    : new Map<number, number[]>();
  const lsmfStackAmounts = lsmfBlob ? parseLsmfStackAmounts(lsmfBlob) : new Map<string, number>();

  const templateToInstances = invertEntityTemplateMap(entityToTemplate0);
  const instanceEntityLists = buildInstanceEntityLists(nodes0);
  const instanceEntityMap = new Map<string, string>();
  for (const [key, ents] of instanceEntityLists) instanceEntityMap.set(key, ents[0]!);

  // Level caches
  const allLcNodeLists: LsofNode[][] = [];
  const templateToStats = new Map<string, string>();
  for (const [key, raw] of frames) {
    if (key.startsWith('LevelCache/') && raw.length) {
      const lcNodes = parseLsof(decompFrame(raw));
      allLcNodeLists.push(lcNodes);
      for (const [t, s] of buildTemplateStatsMap(lcNodes)) templateToStats.set(t, s);
    }
  }
  for (const [t, s] of templateToStats0) templateToStats.set(t, s); // frame 0 wins
  const itemsByChar = collectItemsByPosition([nodes0, ...allLcNodeLists], charPositions);

  /** Attribute and classify the items at a character's position. */
  function attachItems(char: CharacterReport, displayName: string): void {
    const charNi = partyNodes.get(displayName);
    const statusEquipped = new Set<string>();
    if (charNi !== undefined) {
      for (const e of collectStatusEquippedItems(nodes0, charNi)) {
        const tmpl = entityToTemplate0.get(e.entity) ?? '';
        const statsName = templateToStats.get(tmpl) ?? '';
        if (statsName) statusEquipped.add(statsName);
      }
    }

    const charPos = charPositions.get(displayName);
    const charStatsToEntity = new Map<string, string>();
    if (charPos !== undefined) {
      const prefix = `${charPos}|`;
      for (const [key, eg] of instanceEntityMap) {
        if (key.startsWith(prefix)) charStatsToEntity.set(key.slice(prefix.length), eg);
      }
    }

    const attributed: AttributedItem[] = itemsByChar.get(displayName) ?? [];
    if (!attributed.length) {
      char.equipment_note = charNi === undefined ? 'no-character-node' : 'no-items';
      return;
    }

    const split = splitEquippedCarried(
      attributed,
      statusEquipped,
      dn.objectTypeStats.size ? dn.objectTypeStats : undefined,
    );
    let flagsEquipped = split.equipped;
    let carried = split.carried;
    let undetermined = split.undetermined;

    let csdCluster: [number, number] | null = null;
    if (Object.keys(dn.statsToSlot).length && lsmfEcs && lsmfAllCsd.size) {
      csdCluster = equipmentCluster(
        clusterAnchorRows(
          flagsEquipped,
          dn.statsToSlot,
          charStatsToEntity,
          lsmfEcs.guidToRows,
          lsmfAllCsd,
        ),
      );
    }

    let ecsEq: ItemPair[] = [];
    if (undetermined.length && lsmfEcs) {
      const r = ecsResolveEquipped(
        undetermined,
        templateToInstances,
        lsmfEcs.guidToRows,
        lsmfEcs.membershipCount,
        {
          statsToEntity: charStatsToEntity,
          wieldedRows: lsmfWielded,
          csdCluster,
          allCsd: lsmfAllCsd.size ? lsmfAllCsd : undefined,
        },
      );
      ecsEq = r.equipped;
      undetermined = r.undetermined;
      carried = sortedUnion(carried, r.carried);
    }

    if (Object.keys(dn.statsToSlot).length && lsmfEcs) {
      const r = resolveSlotConflicts(
        flagsEquipped,
        ecsEq,
        dn.statsToSlot,
        charStatsToEntity,
        lsmfEcs.guidToRows,
        lsmfEcs.membershipCount,
        {
          ownedAsLootRows: lsmfOwnedLoot,
          twoHandedStats: dn.twoHandedStats.size ? dn.twoHandedStats : undefined,
          statusEquipped: statusEquipped.size ? statusEquipped : undefined,
          wieldedRows: lsmfWielded,
          gravityDisabledRows: lsmfGravityOff,
          csdCluster,
          allCsd: lsmfAllCsd.size ? lsmfAllCsd : undefined,
        },
      );
      flagsEquipped = r.keptFlags;
      ecsEq = r.keptEcs;
      carried = sortedUnion(carried, r.demoted);
    }

    let equipped = sortedUnion(flagsEquipped, ecsEq);

    // Per-instance reclassification of duplicate stats names.
    const instanceWornRows = new Map<string, number[]>();
    const overlayBagged = new Map<string, string[]>();
    if (csdCluster && charPos !== undefined && lsmfEcs) {
      const [lo, hi] = csdCluster;
      for (const statsName of [...new Set(attributed.map(([s]) => s))].sort()) {
        const ents = instanceEntityLists.get(`${charPos}|${statsName}`) ?? [];
        if (ents.length < 2 || !isEquipmentType(statsName)) continue;
        const wornRows: number[] = [];
        const baggedEnts: string[] = [];
        for (const eg of ents) {
          const rows: number[] = [];
          for (const er of lsmfEcs.guidToRows.get(eg) ?? []) {
            for (const r of lsmfAllCsd.get(er) ?? []) if (lo <= r && r <= hi) rows.push(r);
          }
          if (rows.length) wornRows.push(Math.min(...rows));
          else baggedEnts.push(eg);
        }
        const tmpl = attributed.find(([s]) => s === statsName)![2];
        equipped = equipped.filter(([s]) => s !== statsName);
        carried = carried.filter(([s]) => s !== statsName);
        undetermined = undetermined.filter(([s]) => s !== statsName);
        instanceWornRows.set(
          statsName,
          wornRows.sort((a, b) => a - b),
        );
        overlayBagged.set(statsName, baggedEnts);
        for (let i = 0; i < wornRows.length; i++) equipped.push([statsName, tmpl]);
        for (let i = 0; i < baggedEnts.length; i++) carried.push([statsName, tmpl]);
      }
    }

    const containerRank = (stats: string): number => {
      const eg = charStatsToEntity.get(stats) ?? '';
      const rows = lsmfEcs?.guidToRows.get(eg) ?? [];
      let best = 1 << 30;
      for (const r of rows) {
        const p = lsmfCsdPos.get(r);
        if (p !== undefined && p < best) best = p;
      }
      return best;
    };

    const ringSlotNo = new Map<string, number>();
    const rings = equipped.map(([s]) => s).filter((s) => dn.statsToSlot[s] === 'Ring');
    if (rings.length > 1) {
      [...rings]
        .sort((a, b) => containerRank(a) - containerRank(b))
        .forEach((s, i) => {
          ringSlotNo.set(s, i + 1);
        });
    }

    // Per-entry display rank; a duplicate group's k-th entry takes its k-th
    // worn instance's ContainerSlotData row.
    const dupeSeen = new Map<string, number>();
    const entryRows: [string, string, number][] = equipped.map(([s, guid]) => {
      const wr = instanceWornRows.get(s);
      if (wr) {
        const k = dupeSeen.get(s) ?? 0;
        dupeSeen.set(s, k + 1);
        return [s, guid, wr[k]!];
      }
      return [s, guid, containerRank(s)];
    });

    const offhandIdx = new Set<number>();
    const meleeIdx = entryRows
      .map((e, i) => [e, i] as const)
      .filter(([e]) => dn.statsToSlot[e[0]] === 'Melee Main Weapon')
      .map(([, i]) => i);
    if (meleeIdx.length === 2) {
      offhandIdx.add(
        entryRows[meleeIdx[0]!]![2] > entryRows[meleeIdx[1]!]![2] ? meleeIdx[0]! : meleeIdx[1]!,
      );
    }

    entryRows.forEach(([s, guid], i) => {
      let slot = dn.statsToSlot[s] ?? '';
      if (offhandIdx.has(i)) slot = 'Melee Offhand Weapon';
      const rank = [SLOT_DISPLAY_ORDER.get(slot) ?? 99, ringSlotNo.get(s) ?? 0];
      if (ringSlotNo.get(s) === 2) slot = 'Ring 2';
      char.equipped.push(itemRef(s, guid, { slot: slot || null, slot_rank: rank }));
    });
    char.undetermined = undetermined.map(([s, g]) => itemRef(s, g));

    // Stack amounts: a carried ItemRef's count is its instance's stack total.
    const baggedIters = new Map<string, string[]>();
    for (const [s, ents] of overlayBagged) baggedIters.set(s, [...ents]);
    const carriedCount = (s: string, g: string): number => {
      const queue = baggedIters.get(s);
      if (queue !== undefined) {
        const eg = queue.shift();
        return eg !== undefined ? (lsmfStackAmounts.get(eg) ?? 1) : 1;
      }
      const ents = charPos !== undefined ? (instanceEntityLists.get(`${charPos}|${s}`) ?? []) : [];
      if (ents.length === 1) return lsmfStackAmounts.get(ents[0]!) ?? 1;
      for (const eg of ents) {
        if (entityToTemplate0.get(eg) === g) return lsmfStackAmounts.get(eg) ?? 1;
      }
      return 1;
    };
    char.carried = carried.map(([s, g]) => itemRef(s, g, { count: carriedCount(s, g) }));
  }

  const itemRef = (
    stats: string,
    guid: string,
    extra?: Partial<Pick<ItemRef, 'slot' | 'slot_rank' | 'count'>>,
  ): ItemRef => ({
    stats,
    template_guid: guid,
    name: dn.nameFor(stats, guid),
    slot: extra?.slot ?? null,
    slot_rank: extra?.slot_rank ?? [],
    category: itemCategory(stats, dn),
    count: extra?.count ?? 1,
  });

  const report: SaveReport = {
    source,
    characters: [],
    save_info: saveInfo,
    camp_chest: null,
    quests: null,
    level_items: null,
    inspect_pattern: '',
    names_resolved: dn.available,
  };

  if (opts?.quests) {
    const osiris = parseOsiris(frames);
    const questRef = (qid: string): QuestRef => ({ id: qid, name: dn.questNameFor(qid) });
    report.quests =
      osiris === null
        ? { failed: true }
        : {
            failed: false,
            version: osiris.version,
            active: osiris.quests_active.map(questRef),
            closed: osiris.quests_closed.map(questRef),
            goals_finalized: osiris.goals_finalized,
            global_flags: osiris.global_flags,
            global_flags_total: osiris.global_flags_total,
          };
  }

  for (const charInfo of partyInfo) {
    const origin = charInfo.Origin ?? 'Generic';
    const displayName = origin !== 'Generic' ? origin : playerDisplayName;
    const char: CharacterReport = {
      name: displayName,
      race: charInfo.Race ?? '?',
      classes: charInfo.Classes ?? [],
      level: charInfo.Level ?? '?',
      xp: charInfo['Experience Points (Total)'] ?? null,
      location: charInfo.Subregion ?? '',
      spells: null,
      spells_note: null,
      equipped: [],
      undetermined: [],
      carried: [],
      equipment_note: null,
      inspect: null,
      at_camp: false,
    };
    report.characters.push(char);

    const book = exactSpellbook(charInfo);
    if (book !== null) {
      char.spells = [...new Set(book)].sort().map((sid) => ({
        id: sid,
        name: dn.spellNameFor(sid),
        category: COMMON_ACTION_SPELLS.has(sid)
          ? 'basic-action'
          : dn.subSpells.has(sid)
            ? 'sub-spell'
            : 'spell',
      }));
    } else if (buildKey(charInfo) !== null && ambiguousBuilds.has(buildKey(charInfo)!)) {
      char.spells_note = 'ambiguous-build';
    } else {
      char.spells_note = 'not-found';
    }

    attachItems(char, displayName);
  }

  // ---- Camp companions & camp chest ---------------------------------------
  // Mirrors the Python camp section: companions outside the active party are
  // recognised by proximity to the camp chest; class/level/spells come from
  // the ECS blob matched on the origin's fixed base class.
  const chestPos = findCampChest(nodes0);
  if (chestPos !== null && chestPos !== '0,0,0') {
    const activeNames = new Set(report.characters.map((c) => c.name));
    const campNames = [...charPositions.entries()]
      .filter(([name, pos]) => !activeNames.has(name) && campDistance(pos, chestPos) <= CAMP_RADIUS)
      .map(([name]) => name)
      .sort();
    const campBaseClasses = campNames.map((n) => ORIGIN_INFO[n]?.[1] ?? null);
    const activeBuildKeys = new Set(partyInfo.map(buildKey).filter((k): k is string => k !== null));

    const campSpellEntity = (baseClass: string): number | null => {
      const candidates: number[] = [];
      for (const [ent, classes] of entityClasses) {
        if (!spellbooks.has(ent)) continue;
        const names = classes.map(([cg]: [string, string, number]) => classNames[cg] ?? '');
        if (!names.includes(baseClass)) continue;
        const got = classes
          .map(
            ([cg, sg]: [string, string, number]) =>
              `${classNames[cg] ?? ''}\x00${sg !== NULL_UUID ? (classNames[sg] ?? '') : ''}`,
          )
          .sort();
        const total = classes.reduce(
          (acc: number, [, , lvl]: [string, string, number]) => acc + lvl,
          0,
        );
        if (activeBuildKeys.has(`${got.join('\x01')}|${total}`)) continue;
        candidates.push(ent);
      }
      if (!candidates.length) return null;
      return candidates.reduce((a, b) =>
        (spellbooks.get(b)?.length ?? 0) > (spellbooks.get(a)?.length ?? 0) ? b : a,
      );
    };

    for (const name of campNames) {
      const [race, baseClass] = ORIGIN_INFO[name] ?? ['?', null];
      const char: CharacterReport = {
        name,
        race,
        classes: [],
        level: '?',
        xp: null,
        location: 'camp',
        spells: null,
        spells_note: null,
        equipped: [],
        undetermined: [],
        carried: [],
        equipment_note: null,
        inspect: null,
        at_camp: true,
      };
      report.characters.push(char);

      const sameClass = campBaseClasses.filter((c) => c === baseClass).length;
      const ent = baseClass && sameClass === 1 ? campSpellEntity(baseClass) : null;
      if (ent !== null) {
        const classes = entityClasses.get(ent)!;
        char.classes = classes.map(([cg, sg]: [string, string, number]) =>
          sg !== NULL_UUID
            ? { Main: classNames[cg] ?? '?', Sub: classNames[sg] ?? '?' }
            : { Main: classNames[cg] ?? '?' },
        );
        char.level = classes.reduce(
          (acc: number, [, , lvl]: [string, string, number]) => acc + lvl,
          0,
        );
        char.spells = [...new Set(spellbooks.get(ent)!)].sort().map((sid) => ({
          id: sid,
          name: dn.spellNameFor(sid),
          category: COMMON_ACTION_SPELLS.has(sid)
            ? 'basic-action'
            : dn.subSpells.has(sid)
              ? 'sub-spell'
              : 'spell',
        }));
      } else if (baseClass && sameClass > 1) {
        char.spells_note = 'ambiguous-build';
      } else {
        char.spells_note = 'not-found';
      }

      attachItems(char, name);
    }

    // Chest contents: every item at the chest's exact position.
    const chestItems =
      collectItemsByPosition(
        [nodes0, ...allLcNodeLists],
        new Map([['__camp_chest__', chestPos]]),
      ).get('__camp_chest__') ?? [];

    const chestCount = (stats: string): number => {
      const ents = instanceEntityLists.get(`${chestPos}|${stats}`) ?? [];
      if (ents.length === 1) return lsmfStackAmounts.get(ents[0]!) ?? 1;
      let total = 0;
      for (const eg of ents) total += lsmfStackAmounts.get(eg) ?? 1;
      return total || 1;
    };

    report.camp_chest = [...chestItems]
      .sort((a, b) =>
        a[0] < b[0]
          ? -1
          : a[0] > b[0]
            ? 1
            : a[1] !== b[1]
              ? Number(a[1]) - Number(b[1])
              : a[2] < b[2]
                ? -1
                : 1,
      )
      .filter(([stats]) => stats)
      .map(([stats, , guid]) => itemRef(stats, guid, { count: chestCount(stats) }));
  }

  return report;
}
