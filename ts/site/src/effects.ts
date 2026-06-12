/** Item effect text (effects.json, built by the Python lab from the game's
 *  stat files). Keyed by stats name; mirrors bg3parser/effects.py. */

export interface EffectText {
  name: string;
  desc: string;
}

export interface EffectRecord {
  passives?: EffectText[];
  statuses?: EffectText[];
  /** Translated display lines; legacy artifacts held a raw functor string. */
  boosts?: string[];
  boosts_raw?: string;
  damage?: string;
  ac?: number | string;
}

export type EffectsTable = Record<string, EffectRecord>;

/** The record flattened to display lines ('Name: description.'). */
export function effectLines(table: EffectsTable, stats: string): string[] {
  const rec = table[stats];
  if (!rec) return [];
  const out: string[] = [];
  for (const eff of [...(rec.passives ?? []), ...(rec.statuses ?? [])]) {
    out.push(eff.name ? `${eff.name}: ${eff.desc}` : eff.desc);
  }
  if (rec.damage) out.push(`Damage: ${rec.damage}`);
  if (rec.ac !== undefined) out.push(`Armour Class: ${rec.ac}`);
  if (Array.isArray(rec.boosts)) out.push(...rec.boosts);
  return out;
}
