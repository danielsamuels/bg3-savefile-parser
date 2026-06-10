import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

import { extractFrames, parseInfoJson } from '../src/lspk.js';

const FIXTURES = join(__dirname, '..', '..', '..', 'tests', 'fixtures');

function load(name: string): Uint8Array {
  return new Uint8Array(readFileSync(join(FIXTURES, name)));
}

describe('LSPK container (parity with bg3parser.lspk)', () => {
  it('extracts the expected frames from quicksave_maia.lsv', () => {
    const frames = extractFrames(load('quicksave_maia.lsv'));
    for (const key of ['Globals.lsf', 'meta.lsf', 'SaveInfo.json', 'StorySave.bin', 'thumbnail']) {
      expect(frames.has(key), key).toBe(true);
    }
    expect([...frames.keys()].filter((k) => k.startsWith('LevelCache/')).length).toBeGreaterThan(0);
  });

  it('parses the party out of SaveInfo.json', () => {
    const frames = extractFrames(load('quicksave_maia.lsv'));
    const info = parseInfoJson(frames) as {
      'Active Party': { Characters: { Origin: string; Level: string | number }[] };
    };
    const party = info['Active Party'].Characters;
    const origins = new Set(party.map((c) => c.Origin));
    for (const o of ['Wyll', 'Karlach', 'Shadowheart']) expect(origins.has(o), o).toBe(true);
    for (const c of party) expect(Number(c.Level)).toBeGreaterThan(0);
  });

  it('handles the tutorial autosave too', () => {
    const frames = extractFrames(load('autosave_shadowheart_tutorial.lsv'));
    const info = parseInfoJson(frames) as { 'Active Party': { Characters: unknown[] } };
    expect(info['Active Party'].Characters.length).toBeGreaterThan(0);
  });
});
