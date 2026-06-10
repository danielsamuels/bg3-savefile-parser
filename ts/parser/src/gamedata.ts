/** Derived game-data maps (data/gamedata.json, built by the Python lab).
 *  Mirrors bg3parser/gamedata.py's DisplayNames. */

export interface GamedataJson {
  guid: Record<string, string>;
  stats: Record<string, string>;
  spells?: Record<string, string>;
  object_types?: string[];
  stats_slots?: Record<string, string>;
  two_handed?: string[];
  sub_spells?: string[];
  quest_names?: Record<string, string>;
  class_uuid_names?: Record<string, string>;
}

export class DisplayNames {
  readonly guid: Record<string, string>;
  readonly stats: Record<string, string>;
  readonly spells: Record<string, string>;
  readonly objectTypeStats: Set<string>;
  readonly statsToSlot: Record<string, string>;
  readonly twoHandedStats: Set<string>;
  readonly subSpells: Set<string>;
  readonly questNames: Record<string, string>;
  readonly classUuidNames: Record<string, string>;

  constructor(data?: GamedataJson) {
    this.guid = data?.guid ?? {};
    this.stats = data?.stats ?? {};
    this.spells = data?.spells ?? {};
    this.objectTypeStats = new Set(data?.object_types ?? []);
    this.statsToSlot = data?.stats_slots ?? {};
    this.twoHandedStats = new Set(data?.two_handed ?? []);
    this.subSpells = new Set(data?.sub_spells ?? []);
    this.questNames = data?.quest_names ?? {};
    this.classUuidNames = data?.class_uuid_names ?? {};
  }

  get available(): boolean {
    return Object.keys(this.guid).length > 0 || Object.keys(this.stats).length > 0;
  }

  /** Display name for an item, preferring the precise GUID; null if unresolved. */
  nameFor(stats: string, guid = ''): string | null {
    if (guid && guid in this.guid) return this.guid[guid]!;
    return this.stats[stats] ?? null;
  }

  spellNameFor(spellId: string): string | null {
    return this.spells[spellId] ?? null;
  }

  /** Journal title for a quest, or null if unresolved. */
  questNameFor(questId: string): string | null {
    return this.questNames[questId] ?? null;
  }
}
