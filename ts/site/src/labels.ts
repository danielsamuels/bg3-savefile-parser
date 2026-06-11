/** Friendly labels for the game's internal identifiers, shared by the HTML
 *  report and the plain-text AI briefing. */

// 'BattleMaster' → 'Battle Master'
export const camelSplit = (s: string): string => s.replace(/([a-z])([A-Z])/g, '$1 $2');

export const RACE_LABELS: Record<string, string> = {
  Human: 'Human',
  Githyanki: 'Githyanki',
  HalfOrc: 'Half-Orc',
  Elf_HighElf: 'High Elf',
  Elf_WoodElf: 'Wood Elf',
  Drow_LolthSworn: 'Lolth-Sworn Drow',
  Drow_Seldarine: 'Seldarine Drow',
  HalfElf_High: 'High Half-Elf',
  HalfElf_Wood: 'Wood Half-Elf',
  HalfElf_Drow: 'Drow Half-Elf',
  Halfling_Lightfoot: 'Lightfoot Halfling',
  Halfling_Strongheart: 'Strongheart Halfling',
  Dwarf_Gold: 'Gold Dwarf',
  Dwarf_Shield: 'Shield Dwarf',
  Dwarf_Duergar: 'Duergar',
  Gnome_Rock: 'Rock Gnome',
  Gnome_Forest: 'Forest Gnome',
  Gnome_Deep: 'Deep Gnome',
  Tiefling_Asmodeus: 'Asmodeus Tiefling',
  Tiefling_Mephistopheles: 'Mephistopheles Tiefling',
  Tiefling_Zariel: 'Zariel Tiefling',
};

export const SLOT_LABELS: Record<string, string> = {
  Helmet: 'Headwear',
  Breast: 'Armour',
  'Melee Main Weapon': 'Main Hand',
  'Melee Offhand Weapon': 'Off Hand',
  'Ranged Main Weapon': 'Ranged Main',
  'Ranged Offhand Weapon': 'Ranged Off',
  MusicalInstrument: 'Instrument',
  VanityBody: 'Camp Clothes',
  VanityBoots: 'Camp Shoes',
};

export const DIFFICULTY_LABELS: Record<string, string> = {
  DifficultyEasy: 'Explorer',
  DifficultyMedium: 'Balanced',
  DifficultyHard: 'Tactician',
  DifficultyHonour: 'Honour Mode',
};

export const REGION_LABELS: Record<string, string> = {
  TUT_Avernus_C: 'The Nautiloid',
  WLD_Main_A: 'The Wilderness (Act 1)',
  CRE_Main_A: 'Rosymorn Monastery & Crèche (Act 1)',
  SCL_Main_A: 'Shadow-Cursed Lands (Act 2)',
  BGO_Main_A: 'Wyrm’s Crossing & Rivington (Act 3)',
  CTY_Main_A: 'Baldur’s Gate (Act 3)',
};
