/** Plain-text report renderer: mirrors the Python text view
 *  (bg3parser/templates/*.txt.j2) with save-info and carried sections on. */
import type { CharacterReport, ItemRef, SaveReport, SpellRef } from '@bg3save/parser/src/model.ts';

const BAR_HEAVY = '━'.repeat(72);
const BAR_EQ = '='.repeat(72);

const SPELLS_NOTES: Record<string, string> = {
  'ambiguous-build':
    '(identical class build to another party member — spell books cannot be told apart)',
  'not-found': '(spell book not found)',
};

const EQUIPMENT_NOTES: Record<string, string> = {
  'no-character-node': 'character node not found',
  'no-items': 'no items attributed (character off current level?)',
};

const CARRIED_GROUP_LABELS: [string, string][] = [
  ['weapon', 'Weapons & magic items'],
  ['armour', 'Armour & accessories'],
  ['consumable', 'Potions & consumables'],
  ['book', 'Books & scrolls'],
  ['misc', 'Everything else'],
];

const fmtItem = (it: ItemRef): string => it.name ?? it.stats;
const fmtSpell = (sp: SpellRef): string => sp.name ?? sp.id;

const fmtClass = (cl: { Main?: string; Sub?: string }): string =>
  cl.Sub ? `${cl.Main ?? ''} / ${cl.Sub}` : (cl.Main ?? '');

// Python tuple ordering: (slot_rank, formatted name).
const equippedSorted = (items: ItemRef[]): ItemRef[] =>
  [...items].sort((a, b) => {
    const ra = a.slot_rank;
    const rb = b.slot_rank;
    for (let i = 0; i < Math.max(ra.length, rb.length); i++) {
      if (ra[i] === undefined) return -1;
      if (rb[i] === undefined) return 1;
      if (ra[i] !== rb[i]) return ra[i]! - rb[i]!;
    }
    return fmtItem(a) < fmtItem(b) ? -1 : fmtItem(a) > fmtItem(b) ? 1 : 0;
  });

function characterLines(char: CharacterReport): string[] {
  const out: string[] = [char.name];
  const classes = (char.classes as { Main?: string; Sub?: string }[]).map(fmtClass).join('; ');
  out.push(`  Race      : ${char.race}`);
  out.push(`  Class     : ${classes || '?'}`);
  out.push(`  Level     : ${char.level}`);
  if (char.xp !== null) out.push(`  XP        : ${char.xp}`);
  if (char.location) out.push(`  Location  : ${char.location}`);

  if (char.spells !== null) {
    const folded: Record<string, number> = { 'sub-spell': 0, 'basic-action': 0 };
    const shownSet = new Set<string>();
    for (const sp of char.spells) {
      if (sp.category in folded) folded[sp.category]!++;
      else shownSet.add(fmtSpell(sp));
    }
    const shown = [...shownSet].sort();
    const extras = [
      folded['sub-spell'] ? `+${folded['sub-spell']} sub-spells` : '',
      folded['basic-action'] ? `+${folded['basic-action']} basic actions` : '',
    ].filter(Boolean);
    const suffix = extras.length ? `; ${extras.join(', ')}` : '';
    out.push(`  Spells/Abilities (${shown.length}${suffix}):`);
    for (const line of shown) out.push(`    – ${line}`);
  } else {
    out.push(`  Spells/Abilities : ${SPELLS_NOTES[char.spells_note ?? 'not-found']}`);
  }

  if (char.equipment_note) {
    out.push(`  Equipment : ${EQUIPMENT_NOTES[char.equipment_note] ?? char.equipment_note}`);
    return out;
  }

  out.push(`  Equipped (${char.equipped.length}):`);
  for (const it of equippedSorted(char.equipped)) {
    out.push(`    – ${fmtItem(it)}${it.slot ? `  [${it.slot}]` : ''}`);
  }
  if (char.undetermined.length) {
    out.push(`  Worn or carried — undetermined (${char.undetermined.length}):`);
    for (const it of char.undetermined) out.push(`    – ${fmtItem(it)}`);
  }
  out.push(`  Carried / personal inventory (${char.carried.length}):`);
  for (const [key, label] of CARRIED_GROUP_LABELS) {
    const counts = new Map<string, number>();
    for (const it of char.carried) {
      if (it.category === key) counts.set(fmtItem(it), (counts.get(fmtItem(it)) ?? 0) + it.count);
    }
    if (!counts.size) continue;
    out.push(`    ${label}:`);
    for (const [name, n] of [...counts.entries()].sort(([a], [b]) =>
      a < b ? -1 : a > b ? 1 : 0,
    )) {
      out.push(`      – ${n > 1 ? `${name} x${n}` : name}`);
    }
  }
  return out;
}

export function renderTextReport(report: SaveReport): string {
  const si = report.save_info;
  const lines: string[] = [
    'BG3 Save File Report',
    `Source: ${report.source}`,
    BAR_EQ,
    '',
    `Save Name  : ${si.save_name}`,
    `Save #     : ${si.save_id ?? '?'}`,
    `Saved At   : ${si.saved_at}`,
    `Game Ver   : ${si.game_version}`,
    `Level      : ${si.level}`,
    `Difficulty : ${si.difficulty}`,
    `Leader     : ${si.leader}`,
  ];
  if (si.mods.length) {
    lines.push(
      `Mods       : ${si.mods.length} user mod(s)${si.has_unofficial_mods ? '  (flagged unofficial by game)' : ''}`,
    );
    for (const m of si.mods) lines.push(`             ${m}`);
  } else {
    lines.push('Mods       : none');
  }
  lines.push(
    `Item names : ${report.names_resolved ? 'resolved from game data' : 'internal only (name table not loaded)'}`,
  );
  lines.push(BAR_HEAVY, 'PARTY CHARACTERS', BAR_HEAVY);
  for (const char of report.characters) {
    lines.push('');
    lines.push(...characterLines(char));
  }
  lines.push('');
  return lines.join('\n');
}
