import { describe, expect, it } from 'vitest';
import { renderTextReport } from '../src/textReport.ts';

// Minimal SaveReport stub: only the fields the header reads.
const stub = {
  source: 'QuickSave_1.lsv',
  names_resolved: false,
  save_info: {
    save_name: 'My Save',
    save_id: 286,
    saved_at: '2026-06-22 10:00:00 UTC',
    level: 'WLD_Main_A',
    game_version: '?',
    difficulty: '',
    leader: 'Tav',
    mods: [],
  },
  characters: [
    {
      name: 'Tav (player)',
      at_camp: false,
      classes: [],
      equipped: [],
      carried: [],
      undetermined: [],
      spells: null,
      resources: [],
      feats: [],
    },
    {
      name: 'Shadowheart',
      at_camp: true,
      classes: [],
      equipped: [],
      carried: [],
      undetermined: [],
      spells: null,
      resources: [],
      feats: [],
    },
  ],
  camp_chest: null,
  quests: null,
  story: null,
} as unknown as Parameters<typeof renderTextReport>[0];

describe('renderTextReport header', () => {
  it('prints the Save and Party summary lines after the banner', () => {
    const text = renderTextReport(stub);
    expect(text).toContain(
      'Save: My Save (#286)   Region: WLD_Main_A   Saved: 2026-06-22 10:00:00 UTC',
    );
    expect(text).toContain('Party: Tav (player)'); // active party only, camp excluded
    expect(text).not.toContain('Shadowheart,'); // camp companion not in the Party line
  });
});
