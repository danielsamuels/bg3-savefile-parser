import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';
import { parseLsof } from '../src/lsf.js';
import {
  lsmfComponentIndex,
  parseLsmfAllContainerPositions,
  parseLsmfMembership,
  parseLsmfStackAmounts,
} from '../src/lsmf.js';
import { decompFrame, extractFrames } from '../src/lspk.js';

const FIXTURES = join(__dirname, '..', '..', '..', 'tests', 'fixtures');

function lsmfBlob(save: string): Uint8Array {
  const frames = extractFrames(new Uint8Array(readFileSync(join(FIXTURES, save))));
  const nodes = parseLsof(decompFrame(frames.get('Globals.lsf')!));
  const newAge = nodes.find((n) => n.name === 'NewAge' && n.parent === -1)!;
  return newAge.attrs.NewAge as Uint8Array;
}

describe('LSMF scanner (parity with bg3parser.lsmf)', () => {
  const blob = lsmfBlob('quicksave_296.lsv');

  it('finds the component directory and ownerlists', () => {
    const idx = lsmfComponentIndex(blob);
    expect(idx.size).toBeGreaterThan(300);
    const eid = idx.get('core.v0.EntityId')!;
    expect(eid.elemSize).toBe(16);
    expect(eid.rowCount).toBeGreaterThan(10_000);
    const csd = idx.get('game.inventory.v0.ContainerSlotData')!;
    expect(csd.elemSize).toBe(16);
    const member = idx.get('game.inventory.v0.MemberComponent')!;
    expect(member.ownerRows.length).toBe(member.rowCount);
  });

  it('computes membership counts in the documented ranges', () => {
    const m = parseLsmfMembership(blob)!;
    expect(m.guidToRows.size).toBeGreaterThan(1000);
    const counts = [...m.membershipCount.values()];
    expect(Math.max(...counts)).toBeGreaterThan(30); // materialised entities
  });

  it('maps ContainerSlotData rows per entity', () => {
    const all = parseLsmfAllContainerPositions(blob);
    expect(all.size).toBeGreaterThan(500);
    for (const rows of all.values()) {
      for (let i = 1; i < rows.length; i++) expect(rows[i]!).toBeGreaterThan(rows[i - 1]!);
    }
  });

  it('decodes stack amounts: in-game-verified gold piles (QuickSave_296)', () => {
    const amounts = parseLsmfStackAmounts(blob);
    const values = [...amounts.values()];
    expect(values).toContain(766); // Maia's gold
    expect(values).toContain(2017); // Wyll's gold
    for (const v of values) expect(v).toBeGreaterThan(0);
  });
});
