/** AI-chat briefing: a condensed plain-text snapshot of the save, written to
 *  be pasted into an AI assistant chat so it can advise on quests, builds,
 *  and gear without seeing the save itself. Compared with the full text
 *  report it drops lore books, miscellaneous inventory, and per-line item
 *  lists in favour of compact one-line summaries. */
import type { CharacterReport, ItemRef, SaveReport } from '@bg3save/parser/src/model.ts';
import {
  camelSplit,
  DIFFICULTY_LABELS,
  RACE_LABELS,
  REGION_LABELS,
  SLOT_LABELS,
} from './labels.ts';
import {
  buildResourcesLine,
  EQUIPMENT_NOTES,
  equippedSorted,
  fmtClass,
  fmtFeat,
  fmtItem,
  foldSpells,
} from './textReport.ts';

// Scrolls share the 'book' category with lore books; pick them out by name so
// combat-ready consumables stay visible while the library stays out.
const isScroll = (it: ItemRef): boolean => /scroll/i.test(it.name ?? it.stats);

const consumables = (items: ItemRef[]): ItemRef[] =>
  items.filter((it) => it.category === 'consumable' || (it.category === 'book' && isScroll(it)));

// Position attribution puts bag contents in `carried` too, so this covers
// gear stowed in backpacks and pouches, not just loose inventory.
const gearItems = (items: ItemRef[]): ItemRef[] =>
  items.filter((it) => it.category === 'weapon' || it.category === 'armour');

/** Aggregate duplicates into "Name xN", sorted by name. */
function countedNames(items: ItemRef[]): string[] {
  const counts = new Map<string, number>();
  for (const it of items) counts.set(fmtItem(it), (counts.get(fmtItem(it)) ?? 0) + it.count);
  return [...counts.entries()]
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
    .map(([name, n]) => (n > 1 ? `${name} x${n}` : name));
}

function characterBlock(char: CharacterReport): string[] {
  const classes = (char.classes as { Main?: string; Sub?: string }[])
    .map((cl) => camelSplit(fmtClass(cl)))
    .join('; ');
  const race = RACE_LABELS[char.race] ?? char.race;
  const where = char.location ? ` — ${char.location}` : '';
  const out: string[] = [`### ${char.name} — ${race}, ${classes || '?'} ${char.level}${where}`];
  if (char.hp) {
    out.push(
      `- HP ${char.hp.current}/${char.hp.max}${char.hp.temp ? ` (+${char.hp.temp} temp)` : ''}`,
    );
  }
  if (char.abilities) {
    const a = char.abilities;
    out.push(
      `- Abilities: STR ${a.str}, DEX ${a.dex}, CON ${a.con}, INT ${a.int}, WIS ${a.wis}, CHA ${a.cha}`,
    );
  }
  const resources = buildResourcesLine(char.resources);
  if (resources) out.push(`- Resources: ${resources}`);
  if (char.feats?.length) out.push(`- Feats: ${char.feats.map(fmtFeat).join('; ')}`);
  if (char.concentration) {
    out.push(`- Concentrating on: ${char.concentration.name ?? char.concentration.id}`);
  }

  if (char.spells !== null) {
    const { shown, subSpells, basicActions } = foldSpells(char.spells);
    const extras = [
      subSpells ? `+${subSpells} sub-spells` : '',
      basicActions ? `+${basicActions} basic actions` : '',
    ].filter(Boolean);
    const suffix = extras.length ? `; ${extras.join(', ')} not listed` : '';
    out.push(`- Spells & abilities (${shown.length}${suffix}): ${shown.join(', ')}`);
  }

  if (char.equipment_note) {
    out.push(`- Equipment: ${EQUIPMENT_NOTES[char.equipment_note] ?? char.equipment_note}`);
    return out;
  }
  const equipped = equippedSorted(char.equipped).map((it) =>
    it.slot ? `${fmtItem(it)} [${SLOT_LABELS[it.slot] ?? it.slot}]` : fmtItem(it),
  );
  out.push(`- Equipped: ${equipped.join(', ') || 'nothing'}`);
  if (char.undetermined.length) {
    out.push(`- Worn or carried (undetermined): ${countedNames(char.undetermined).join(', ')}`);
  }
  const spare = countedNames(gearItems(char.carried));
  if (spare.length) out.push(`- Spare gear carried (incl. bags, unequipped): ${spare.join(', ')}`);
  const cons = countedNames(consumables(char.carried));
  if (cons.length) out.push(`- Consumables carried: ${cons.join(', ')}`);
  return out;
}

export function renderAiBriefing(report: SaveReport): string {
  const si = report.save_info;
  const lines: string[] = [
    "# Baldur's Gate 3 — campaign briefing",
    '',
    "A snapshot of my current Baldur's Gate 3 campaign, read directly from my",
    'save file. Treat it as ground truth for where things stand: it reflects',
    "the moment of the save, not a typical playthrough. I'll be asking for help",
    'with quests, character builds, and gear — base your advice on what is',
    'listed here, and avoid spoiling story content beyond the quests shown as',
    'in progress unless I ask.',
    '',
    '## Situation',
    `- Save: ${si.save_name}, saved ${si.saved_at} (game v${si.game_version})`,
    `- Region: ${REGION_LABELS[si.level] ?? si.level}`,
    `- Difficulty: ${
      si.difficulty
        .split(', ')
        .filter((t) => t !== 'RulesetLarian')
        .map((t) => DIFFICULTY_LABELS[t] ?? t)
        .join(', ') || si.difficulty
    }`,
    `- Party leader: ${si.leader}`,
  ];
  const party = report.characters.filter((c) => !c.at_camp);
  const campChars = report.characters.filter((c) => c.at_camp);
  lines.push(`- Active party: ${party.map((c) => c.name).join(', ')}`);
  if (campChars.length) lines.push(`- At camp: ${campChars.map((c) => c.name).join(', ')}`);
  if (si.camp_supplies != null) lines.push(`- Camp supplies: ${si.camp_supplies}`);
  if (si.mods.length) lines.push(`- Mods in use: ${si.mods.join(', ')}`);
  if (!report.names_resolved) {
    lines.push(
      '- Note: item and spell names below are internal identifiers (display names unavailable).',
    );
  }

  if (report.quests) {
    if (report.quests.failed) {
      lines.push('', '## Quests', '(quest state could not be read from this save)');
    } else {
      const q = report.quests;
      lines.push('', `## Quests in progress (${q.active.length})`);
      for (const n of q.active) {
        lines.push(
          `- ${n.name ?? n.id}${n.objective ? ` — current objective: ${n.objective}` : ''}`,
        );
      }
      lines.push(
        '',
        `## Quests closed (${q.closed.length}) — completed and failed are not distinguished`,
        q.closed.map((n) => n.name ?? n.id).join('; ') || '(none)',
      );
    }
  }

  if (report.story) {
    const s = report.story;
    lines.push('', '## Campaign state');
    lines.push(
      `- Long rests taken: ${s.long_rests}; waypoints unlocked: ${s.waypoints.length}; traders met: ${s.traders_met}`,
    );
    if (s.tadpoles.length) {
      lines.push(
        `- Tadpoles carried: ${s.tadpoles.map((t) => `${t.name} x${t.count}`).join(', ')}`,
      );
    }
    if (s.approval.length) {
      const dating = new Set(s.dating);
      const ratings = s.approval.map(
        (a) => `${a.name} ${a.rating}${dating.has(a.name) ? ' (dating)' : ''}`,
      );
      lines.push(`- Companion approval of the player: ${ratings.join(', ')}`);
    }
  }

  lines.push('', '## Active party');
  for (const char of party) {
    lines.push('');
    lines.push(...characterBlock(char));
  }
  if (campChars.length) {
    lines.push('', '## Companions at camp');
    for (const char of campChars) {
      lines.push('');
      lines.push(...characterBlock(char));
    }
  }

  if (report.camp_chest !== null) {
    lines.push('', '## Camp chest');
    const gear = countedNames(gearItems(report.camp_chest));
    if (gear.length) lines.push(`- Gear stored: ${gear.join(', ')}`);
    const cons = countedNames(consumables(report.camp_chest));
    if (cons.length) lines.push(`- Consumables: ${cons.join(', ')}`);
    const rest = report.camp_chest
      .filter((it) => (it.category === 'book' && !isScroll(it)) || it.category === 'misc')
      .reduce((n, it) => n + it.count, 0);
    if (rest) lines.push(`- Plus ${rest} books and miscellaneous items, not listed.`);
  }

  lines.push('');
  return lines.join('\n');
}
