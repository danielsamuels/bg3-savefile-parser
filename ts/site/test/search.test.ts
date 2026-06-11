import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { DisplayNames, type GamedataJson } from '@bg3save/parser/src/gamedata.ts';
import { gatherReport } from '@bg3save/parser/src/model.ts';
import { describe, expect, it } from 'vitest';
import { buildItemIndex, renderSearchResults, searchItems } from '../src/search.ts';

const ROOT = join(__dirname, '..', '..', '..');
const gamedata = new DisplayNames(
  JSON.parse(readFileSync(join(ROOT, 'data', 'gamedata.json'), 'utf-8')) as GamedataJson,
);
const save = new Uint8Array(readFileSync(join(ROOT, 'tests', 'fixtures', 'quicksave_294.lsv')));
const report = gatherReport(save, gamedata, 'quicksave_294.lsv', { quests: false });

const GOLD_STATS = new Set(['OBJ_GoldCoin', 'OBJ_GoldPile']);
const SLOT_LABELS = { 'Melee Main Weapon': 'Main Hand' };
const index = buildItemIndex(report, SLOT_LABELS, GOLD_STATS);

describe('item search', () => {
  it('finds an item across owners with its location', () => {
    const matches = searchItems(index, 'phalar');
    expect(matches.length).toBeGreaterThan(0);
    expect(matches[0]!.name).toBe('Phalar Aluve');
    expect(matches[0]!.owner).toBe('Wyll');
  });

  it('labels equipped matches with their slot', () => {
    const equipped = searchItems(index, 'halberd of vigilance');
    expect(equipped).toHaveLength(1);
    expect(equipped[0]!.how).toBe('equipped · Main Hand');
    expect(equipped[0]!.owner).toBe('Maia');
  });

  it('never indexes gold', () => {
    expect(searchItems(index, 'gold pile')).toHaveLength(0);
  });

  it('treats short queries as empty and misses as no places', () => {
    expect(searchItems(index, 'p')).toHaveLength(0);
    const view = renderSearchResults(searchItems(index, 'xyzzy'), 'xyzzy');
    expect(view.summary).toContain('Nothing in this save');
    expect(view.listHtml).toBe('');
  });

  it('marks the matched run and escapes names', () => {
    const matches = searchItems(index, 'phalar');
    const view = renderSearchResults(matches, 'phalar');
    expect(view.listHtml).toContain('<mark>Phalar</mark>');
    expect(view.summary).toMatch(/^\d+ items? in \d+ places?\.$/);
  });

  it('prefers prefix matches in the ordering', () => {
    const matches = searchItems(index, 'torch');
    expect(matches[0]!.name.toLowerCase().startsWith('torch')).toBe(true);
  });
});
