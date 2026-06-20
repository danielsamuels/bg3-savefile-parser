import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

import { DisplayNames, type GamedataJson } from '../src/gamedata.js';
import { gatherReport } from '../src/model.js';

const ROOT = join(__dirname, '..', '..', '..');

// The site ships a pre-parsed example report so a visitor with no save of
// their own can see a full party. It is the parser's own output for a real
// fixture, committed as JSON and loaded exactly like a stored history entry.
// This test keeps that committed file in lock-step with the parser: when an
// intentional change to the report shape lands, regenerate with
//   UPDATE_EXAMPLE=1 bun test ts/parser/test/example-report.test.ts
const FIXTURE = 'quicksave_419.lsv';
// The label the report is parsed-from; mirrored in the site's example button.
const SOURCE_NAME = 'example-save.lsv';
const EXAMPLE = join(ROOT, 'ts', 'site', 'public', 'example-report.json');

describe('site example report', () => {
  it('matches the parser output for the bundled fixture', () => {
    const gamedata = new DisplayNames(
      JSON.parse(readFileSync(join(ROOT, 'data', 'gamedata.json'), 'utf-8')) as GamedataJson,
    );
    const save = new Uint8Array(readFileSync(join(ROOT, 'tests', 'fixtures', FIXTURE)));
    const report = JSON.parse(
      JSON.stringify(gatherReport(save, gamedata, SOURCE_NAME, { quests: true })),
    );
    if (process.env.UPDATE_EXAMPLE) {
      writeFileSync(EXAMPLE, `${JSON.stringify(report)}\n`);
    }
    const committed = JSON.parse(readFileSync(EXAMPLE, 'utf-8'));
    expect(report).toEqual(committed);
  }, 30_000);
});
