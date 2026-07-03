import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { beforeAll, describe, expect, it } from 'vitest';

import { type Region, SaveAnatomy, type StreamMeta } from '../src/annotate.js';

const FIXTURES = join(__dirname, '..', '..', '..', 'tests', 'fixtures');

function load(name: string): Uint8Array {
  return new Uint8Array(readFileSync(join(FIXTURES, name)));
}

/** Regions at one level must be sorted, non-overlapping, and inside [0, size). */
function checkInvariants(regions: Region[], size: number): void {
  let pos = 0;
  for (const r of regions) {
    expect(r.start, r.label).toBeGreaterThanOrEqual(pos);
    expect(r.end, r.label).toBeGreaterThan(r.start);
    expect(r.end, r.label).toBeLessThanOrEqual(size);
    if (r.kids) {
      for (const k of r.kids) {
        expect(k.start).toBeGreaterThanOrEqual(r.start);
        expect(k.end).toBeLessThanOrEqual(r.end);
      }
    }
    pos = r.end;
  }
}

function coverage(m: StreamMeta): number {
  return m.size ? m.covered / m.size : 1;
}

describe('SaveAnatomy (quicksave_maia.lsv)', () => {
  let anatomy: SaveAnatomy;
  beforeAll(() => {
    anatomy = new SaveAnatomy(load('quicksave_maia.lsv'));
  });

  it('annotates the container with full coverage and gap-free top level', () => {
    const m = anatomy.meta('file');
    checkInvariants(m.regions, m.size);
    // header + frames + file list account for essentially the whole file
    expect(coverage(m)).toBeGreaterThan(0.99);
    const titles = m.children.map((c) => c.id);
    for (const want of [
      'filelist',
      'frame/Globals.lsf',
      'frame/meta.lsf',
      'frame/SaveInfo.json',
      'frame/StorySave.bin',
      'frame/thumbnail',
    ]) {
      expect(titles).toContain(want);
    }
  });

  it('decodes the file list with one labelled entry per package file', () => {
    const m = anatomy.meta('filelist');
    checkInvariants(m.regions, m.size);
    expect(coverage(m)).toBe(1);
    const w = anatomy.window('filelist', 0, 272 * 3);
    expect(w.regions.length).toBe(3);
    expect(w.regions[0]!.label.length).toBeGreaterThan(0);
    expect(w.bytes.length).toBe(272 * 3);
  });

  it('annotates an LSOF frame header and its four sections', () => {
    const m = anatomy.meta('frame/Globals.lsf');
    checkInvariants(m.regions, m.size);
    expect(coverage(m)).toBeGreaterThan(0.999);
    const labels = m.regions.map((r) => r.label);
    expect(labels).toContain('LSOF header');
    for (const sec of ['strings section', 'nodes section', 'attributes section', 'values section'])
      expect(labels).toContain(sec);
    // Globals carries the ECS blob
    expect(m.children.map((c) => c.id)).toContain('lsmf/Globals.lsf');
  });

  it('windows the LSOF header into labelled fields', () => {
    const w = anatomy.window('frame/Globals.lsf', 0, 64);
    const labels = w.regions.map((r) => r.label);
    expect(labels[0]).toBe('magic “LSOF”');
    expect(labels.some((l) => l.startsWith('MetadataFormat'))).toBe(true);
  });

  it('annotates the node table with resolved names', () => {
    const m = anatomy.meta('lsf/Globals.lsf/nodes');
    checkInvariants(m.regions, m.size);
    expect(coverage(m)).toBe(1);
    const w = anatomy.window('lsf/Globals.lsf/nodes', 0, 12 * 5);
    expect(w.regions.length).toBe(5);
    for (const r of w.regions) {
      expect(r.label).toMatch(/^#\d/);
      expect(r.label).not.toContain('?');
    }
  });

  it('annotates attribute values with node.attr labels and decoded previews', () => {
    const m = anatomy.meta('lsf/Globals.lsf/values');
    checkInvariants(m.regions, m.size);
    expect(coverage(m)).toBeGreaterThan(0.999);
    const w = anatomy.window('lsf/Globals.lsf/values', 0, 4096);
    expect(w.regions.length).toBeGreaterThan(10);
    expect(w.regions.every((r) => r.label.includes('.'))).toBe(true);
    expect(m.children.map((c) => c.id)).toContain('lsmf/Globals.lsf');
  });

  it('annotates the string table', () => {
    const m = anatomy.meta('lsf/Globals.lsf/strings');
    checkInvariants(m.regions, m.size);
    expect(coverage(m)).toBe(1);
    const w = anatomy.window('lsf/Globals.lsf/strings', 4, 512);
    expect(w.regions.length).toBeGreaterThan(0);
    expect(w.regions[0]!.label).toContain('chain');
  });

  it('annotates the LSMF blob: header, columns, ownerlists, directory', () => {
    const m = anatomy.meta('lsmf/Globals.lsf');
    checkInvariants(m.regions, m.size);
    const labels = m.regions.map((r) => r.label);
    expect(labels[0]).toBe('LSMF header');
    expect(labels).toContain('ownerlist record table');
    expect(labels).toContain('component-type directory');
    expect(labels).toContain('core.v0.EntityId');
    const dir = m.regions.find((r) => r.label === 'component-type directory')!;
    expect(dir.kids!.map((k) => k.label)).toContain('component names text');
    // windowing the descriptor table yields per-component entries
    const desc = dir.kids!.find((k) => k.label.startsWith('component descriptor table'))!;
    const dw = anatomy.window('lsmf/Globals.lsf', desc.start, desc.start + 96);
    expect(dw.regions.map((r) => r.label).join(' ')).toContain('core.v0');
    // most of the blob is structurally accounted for
    expect(coverage(m)).toBeGreaterThan(0.5);
    // the header window names the magic and directory fields
    const w = anatomy.window('lsmf/Globals.lsf', 0, 48);
    expect(w.regions.some((r) => r.label.startsWith('dir_off'))).toBe(true);
  });

  it('annotates the Osiris story save end-to-end', () => {
    const m = anatomy.meta('frame/StorySave.bin');
    checkInvariants(m.regions, m.size);
    expect(coverage(m)).toBe(1);
    const names = m.regions.map((r) => r.label);
    for (const want of ['Types', 'Nodes', 'Databases', 'Goals'])
      expect(
        names.some((n) => n.startsWith(want)),
        want,
      ).toBe(true);
    expect(m.note).toContain('consumed all');
  });

  it('annotates SaveInfo.json by top-level key', () => {
    const m = anatomy.meta('frame/SaveInfo.json');
    checkInvariants(m.regions, m.size);
    expect(m.regions.some((r) => r.label === '“Active Party”')).toBe(true);
  });

  it('annotates the thumbnail RIFF chunks', () => {
    const m = anatomy.meta('frame/thumbnail');
    checkInvariants(m.regions, m.size);
    expect(m.regions[0]!.label).toBe('RIFF header');
    expect(m.regions.some((r) => r.label.startsWith('chunk'))).toBe(true);
    expect(coverage(m)).toBe(1);
  });

  it('clamps windows to stream bounds', () => {
    const m = anatomy.meta('frame/SaveInfo.json');
    const w = anatomy.window('frame/SaveInfo.json', m.size - 8, m.size + 100);
    expect(w.bytes.length).toBe(8);
    for (const r of w.regions) expect(r.start).toBeLessThan(m.size);
  });
});

describe('SaveAnatomy (autosave_shadowheart_tutorial.lsv)', () => {
  it('holds container invariants and coverage on a second save', () => {
    const anatomy = new SaveAnatomy(load('autosave_shadowheart_tutorial.lsv'));
    const m = anatomy.meta('file');
    checkInvariants(m.regions, m.size);
    expect(coverage(m)).toBeGreaterThan(0.99);
    for (const child of m.children) {
      const cm = anatomy.meta(child.id);
      checkInvariants(cm.regions, cm.size);
    }
  });
});
