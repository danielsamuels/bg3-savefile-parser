import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

import { DisplayNames, type GamedataJson } from '../src/gamedata.js';
import { gatherReport } from '../src/model.js';

const ROOT = join(__dirname, '..', '..', '..');
const gamedata = new DisplayNames(
  JSON.parse(readFileSync(join(ROOT, 'data', 'gamedata.json'), 'utf-8')) as GamedataJson,
);

const fixtures = readdirSync(join(ROOT, 'tests', 'parity'))
  .filter((f) => f.endsWith('.expected.json'))
  .map((f) => f.replace('.expected.json', ''));

describe('full report parity with bg3save --json', () => {
  it.each(fixtures)('%s', (stem) => {
    const expected = JSON.parse(
      readFileSync(join(ROOT, 'tests', 'parity', `${stem}.expected.json`), 'utf-8'),
    );
    const save = new Uint8Array(readFileSync(join(ROOT, 'tests', 'fixtures', `${stem}.lsv`)));
    const actual = gatherReport(save, gamedata, `${stem}.lsv`);
    expect(JSON.parse(JSON.stringify(actual))).toEqual(expected);
  });
});
