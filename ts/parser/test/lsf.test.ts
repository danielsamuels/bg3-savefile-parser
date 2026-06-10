import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

import { decompFrame, extractFrames } from '../src/lspk.js';
import { parseLsof } from '../src/lsf.js';

const FIXTURES = join(__dirname, '..', '..', '..', 'tests', 'fixtures');

function frames(name: string) {
  return extractFrames(new Uint8Array(readFileSync(join(FIXTURES, name))));
}

describe('LSOF parser (parity with bg3parser.lsf)', () => {
  it('parses meta.lsf: leader name and save id', () => {
    const nodes = parseLsof(decompFrame(frames('quicksave_maia.lsv').get('meta.lsf')!));
    const meta = nodes.find((n) => n.name === 'MetaData' && Object.keys(n.attrs).length > 0);
    expect(meta?.attrs.LeaderName).toBe('Maia');
    expect(typeof meta?.attrs.SaveTime).toBe('number');
  });

  it('parses Globals.lsf: party characters, items, the LSMF blob', () => {
    const nodes = parseLsof(decompFrame(frames('quicksave_296.lsv').get('Globals.lsf')!));
    expect(nodes.length).toBeGreaterThan(100_000);

    // Karlach's character node, found by her origin CurrentTemplate
    const karlach = nodes.find(
      (n) => n.attrs.CurrentTemplate === '2c76687d-93a2-477b-8b18-8a14b549304c',
    );
    expect(karlach, 'Karlach character node').toBeDefined();
    expect(Array.isArray(karlach!.attrs.Translate)).toBe(true);

    // Item nodes with stats names and int Flags
    const items = nodes.filter((n) => n.name === 'Item' && typeof n.attrs.Stats === 'string');
    expect(items.length).toBeGreaterThan(1000);
    const sword = items.find((n) => n.attrs.Stats === 'WPN_Shortsword');
    expect(typeof sword?.attrs.Flags).toBe('number');

    // The LSMF ECS blob rides on the root NewAge node as a ScratchBuffer
    const newAge = nodes.find((n) => n.name === 'NewAge' && n.parent === -1);
    const blob = newAge?.attrs.NewAge as Uint8Array;
    expect(blob).toBeInstanceOf(Uint8Array);
    expect(blob.length).toBeGreaterThan(1_000_000);
    expect(String.fromCharCode(...blob.subarray(0, 4))).toBe('LSMF');
  });
});
