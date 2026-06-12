import { describe, expect, it } from 'vitest';
import { type EffectsTable, effectLines } from '../src/effects.ts';

describe('effect lines', () => {
  it('renders translated boost lines after damage and AC', () => {
    const table: EffectsTable = {
      robe: {
        boosts: ['Resistance to Cold damage'],
        boosts_raw: 'Resistance(Cold, Resistant)',
        damage: '1d8 Slashing',
        ac: 10,
      },
    };
    expect(effectLines(table, 'robe')).toEqual([
      'Damage: 1d8 Slashing',
      'Armour Class: 10',
      'Resistance to Cold damage',
    ]);
  });

  it('skips legacy string boosts from stale artifacts', () => {
    const table = { old: { boosts: 'AC(1)' } } as unknown as EffectsTable;
    expect(effectLines(table, 'old')).toEqual([]);
  });
});
