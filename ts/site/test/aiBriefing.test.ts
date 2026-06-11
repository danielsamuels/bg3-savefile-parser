import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { DisplayNames, type GamedataJson } from '@bg3save/parser/src/gamedata.ts';
import { gatherReport } from '@bg3save/parser/src/model.ts';
import { describe, expect, it } from 'vitest';
import { renderAiBriefing } from '../src/aiBriefing.ts';
import { renderTextReport } from '../src/textReport.ts';

const ROOT = join(__dirname, '..', '..', '..');
const gamedata = new DisplayNames(
  JSON.parse(readFileSync(join(ROOT, 'data', 'gamedata.json'), 'utf-8')) as GamedataJson,
);
const save = new Uint8Array(readFileSync(join(ROOT, 'tests', 'fixtures', 'quicksave_294.lsv')));
const report = gatherReport(save, gamedata, 'quicksave_294.lsv', { quests: true });
const briefing = renderAiBriefing(report);

describe('AI briefing', () => {
  it('opens with context the assistant can act on', () => {
    expect(briefing).toMatch(/^# Baldur's Gate 3 — campaign briefing/);
    expect(briefing).toContain('ground truth');
    expect(briefing).toContain('## Situation');
  });

  it('covers quests with objectives', () => {
    expect(briefing).toContain('## Quests in progress');
    expect(briefing).toContain('## Quests closed');
    expect(briefing).toContain('current objective:');
  });

  it('describes each party member with build and gear', () => {
    for (const char of report.characters) {
      expect(briefing).toContain(`### ${char.name}`);
    }
    expect(briefing).toContain('- Equipped: ');
    expect(briefing).toContain('- Spells & abilities (');
    expect(briefing).toContain('- Abilities: STR ');
  });

  it('uses friendly labels, not internal identifiers', () => {
    expect(briefing).toContain('- Region: Shadow-Cursed Lands (Act 2)');
    expect(briefing).toContain('- Difficulty: Balanced');
    expect(briefing).toContain('High Elf');
    expect(briefing).toContain('[Main Hand]');
  });

  it('stays well under the full text report', () => {
    expect(briefing.length).toBeLessThan(renderTextReport(report).length * 0.8);
  });

  it('leaves lore books and misc inventory out of the camp chest', () => {
    expect(briefing).toContain('## Camp chest');
    expect(briefing).toMatch(/- Plus \d+ books and miscellaneous items, not listed\./);
  });
});
