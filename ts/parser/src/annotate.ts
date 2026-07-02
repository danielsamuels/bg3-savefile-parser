/** Byte-level anatomy of a .lsv save, for the /anatomy explainer page.
 *
 *  A save is presented as a set of *streams* (the raw LSPK container, each
 *  decompressed frame, the decoded LSF sections inside a frame, the LSMF ECS
 *  blob) and each stream carries an outline of *regions* — what the parser
 *  understands every byte range to be — plus dense per-entry tables for the
 *  repetitive structures. Layout knowledge cited here is documented and
 *  verified in FORMAT.md.
 */
import { decompress as zstdDecompress } from 'fzstd';

import { type AttrValue, decompSection, guidLeStr, parseStringTable, readVal } from './lsf.js';
import { scanLsmfBlob } from './lsmf.js';
import { lz4BlockDecompress } from './lz4.js';
import { osirisAnatomy } from './osiris.js';

/* ---- Public shapes ------------------------------------------------------ */

export interface Region {
  start: number;
  end: number; // exclusive
  label: string;
  detail?: string;
  /** 'gap' marks bytes the parser has not structurally accounted for. */
  kind?: 'gap';
  /** Colour group index, assigned when the stream is built. */
  group?: number;
  /** Stream id this region links to (e.g. a frame region → its stream). */
  stream?: string;
  kids?: Region[];
}

export interface StreamRef {
  id: string;
  title: string;
  size: number;
  note: string;
}

export interface StreamMeta {
  id: string;
  title: string;
  note: string;
  size: number;
  /** Bytes covered by non-gap leaf regions (coverage = covered / size). */
  covered: number;
  parent: string | null;
  regions: Region[];
  children: StreamRef[];
}

export interface WindowRegion {
  start: number;
  end: number;
  label: string;
  detail?: string;
  group: number;
  /** Entry parity inside a dense table, for alternating shading. */
  band: number;
  gap?: boolean;
  stream?: string;
}

/** Per-entry annotation of a repetitive table inside one outline region. */
interface DenseTable {
  start: number;
  end: number;
  count: number;
  /** Uniform entry size; ignored when starts is given. */
  stride?: number;
  /** count+1 entry boundaries (absolute stream offsets), for variable entries. */
  starts?: Uint32Array;
  entry: (i: number) => { label: string; detail?: string };
}

export interface Leaf {
  start: number;
  end: number;
  label: string;
  detail?: string;
  group: number;
  gap: boolean;
  stream?: string;
  table?: DenseTable;
}

interface StreamData {
  meta: StreamMeta;
  bytes: Uint8Array;
  tables: Map<Region, DenseTable>;
  leaves: Leaf[];
}

/* ---- Formatting helpers ------------------------------------------------- */

const fmtInt = (n: number): string => n.toLocaleString('en-GB');

function fmtBytes(n: number): string {
  if (n >= 1048576) return `${(n / 1048576).toFixed(1)} MB`;
  if (n >= 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${n} B`;
}

const hex = (n: number, w = 0): string => `0x${n.toString(16).padStart(w, '0')}`;

const dvOf = (b: Uint8Array): DataView => new DataView(b.buffer, b.byteOffset, b.byteLength);

const latin1 = new TextDecoder('latin1');
const utf8 = new TextDecoder();

/** LSF attribute type names (LSLib NodeAttribute.cs; see FORMAT.md §2). */
const ATTR_TYPE_NAMES: Record<number, string> = {
  0: 'None',
  1: 'Byte',
  2: 'Short',
  3: 'UShort',
  4: 'Int',
  5: 'UInt',
  6: 'Float',
  7: 'Double',
  8: 'IVec2',
  9: 'IVec3',
  10: 'IVec4',
  11: 'Vec2',
  12: 'Vec3',
  13: 'Vec4',
  14: 'Mat2',
  15: 'Mat3',
  16: 'Mat3x4',
  17: 'Mat4x3',
  18: 'Mat4',
  19: 'Bool',
  20: 'String',
  21: 'Path',
  22: 'FixedString',
  23: 'LSString',
  24: 'ULongLong',
  25: 'ScratchBuffer',
  26: 'Long',
  27: 'Int8',
  28: 'TranslatedString',
  29: 'WString',
  30: 'LSWString',
  31: 'UUID',
  32: 'Int64',
  33: 'TranslatedFSString',
};

const FRAME_NOTES: Record<string, string> = {
  'Globals.lsf':
    'The live world state: Characters, Items, Story, Journal — and the NewAge ECS blob.',
  'meta.lsf': 'Save metadata: save time, campaign IDs, party leader, mod list, difficulty.',
  'SaveInfo.json': 'Plain-JSON summary: save name, game version, difficulty, active party.',
  'StorySave.bin': 'Osiris scripting-engine state: quest flags, story databases, goals.',
  thumbnail: 'The load-screen thumbnail: a 1280×720 lossy WebP.',
};

function frameNote(name: string): string {
  return (
    FRAME_NOTES[name] ??
    (name.startsWith('LevelCache/')
      ? 'Level cache: world entities for one area — characters, items, surfaces, navmesh, fog-of-war.'
      : 'Package member.')
  );
}

/** Sort regions, clamp overlaps, and fill holes with explicit gap regions. */
function fillGaps(regions: Region[], size: number, label: string, detail: string): Region[] {
  const sorted = regions.filter((r) => r.end > r.start).sort((a, b) => a.start - b.start);
  const out: Region[] = [];
  let pos = 0;
  for (const r of sorted) {
    if (r.start > pos) out.push({ start: pos, end: r.start, label, detail, kind: 'gap' });
    if (r.start < pos) {
      r.start = pos; // clamp a mis-scanned overlap rather than lie twice about a byte
      if (r.start >= r.end) continue;
    }
    out.push(r);
    pos = r.end;
  }
  if (pos < size) out.push({ start: pos, end: size, label, detail, kind: 'gap' });
  return out;
}

/** Assign colour groups and flatten the outline into sorted leaf spans. */
function flatten(regions: Region[], tables: Map<Region, DenseTable>): Leaf[] {
  const out: Leaf[] = [];
  const walk = (r: Region, group: number): void => {
    r.group = group;
    const table = tables.get(r);
    if (!r.kids?.length || table) {
      out.push({
        start: r.start,
        end: r.end,
        label: r.label,
        detail: r.detail,
        group,
        gap: r.kind === 'gap',
        stream: r.stream,
        table,
      });
      return;
    }
    let pos = r.start;
    for (const k of [...r.kids].sort((a, b) => a.start - b.start)) {
      if (k.start > pos)
        out.push({ start: pos, end: k.start, label: r.label, detail: r.detail, group, gap: false });
      walk(k, group);
      pos = Math.max(pos, k.end);
    }
    if (pos < r.end)
      out.push({ start: pos, end: r.end, label: r.label, detail: r.detail, group, gap: false });
  };
  for (let i = 0; i < regions.length; i++) walk(regions[i]!, i);
  return out.sort((a, b) => a.start - b.start);
}

function coveredBytes(leaves: Leaf[], size: number): number {
  let covered = 0;
  for (const l of leaves) {
    if (!l.gap) covered += Math.min(l.end, size) - Math.max(l.start, 0);
  }
  return Math.min(covered, size);
}

function escapePreview(s: string, cap = 90): string {
  // biome-ignore lint/suspicious/noControlCharactersInRegex: scrubbing control bytes from raw file text is the point
  const clean = s.replace(/[\x00-\x1f]/g, '·');
  return clean.length > cap ? `${clean.slice(0, cap)}…` : clean;
}

function previewValue(v: AttrValue | null, tid: number): string {
  if (v === null) return `not decoded by this parser (type ${ATTR_TYPE_NAMES[tid] ?? tid})`;
  if (v instanceof Uint8Array) return `${fmtBytes(v.length)} opaque blob`;
  if (Array.isArray(v)) return `(${v.map((x) => x.toFixed(3)).join(', ')})`;
  if (typeof v === 'string') return `“${escapePreview(v)}”`;
  return String(v);
}

/* ---- LSF frame parsing (header + section spans) -------------------------- */

interface LsofSectionSpan {
  disk: number; // bytes occupied in the frame
  sizeOnDisk: number;
  uncompressed: number;
  start: number;
}

interface LsofInfo {
  ver: number;
  cflags: number;
  mfmt: number;
  hasKeys: boolean;
  keysUnc: number;
  keysDisk: number;
  sections: Record<'strings' | 'nodes' | 'attrs' | 'values', LsofSectionSpan>;
  end: number; // offset after the values section
}

function lsofInfo(data: Uint8Array): LsofInfo {
  const dv = dvOf(data);
  if (latin1.decode(data.subarray(0, 4)) !== 'LSOF') throw new Error('bad LSOF magic');
  const ver = dv.getUint32(4, true);
  const u = (i: number) => dv.getUint32(16 + i * 4, true);
  const cflags = dv.getUint8(56);
  const mfmt = dv.getUint32(60, true);
  const mk = (unc: number, disk: number, start: number): LsofSectionSpan => ({
    disk: disk || unc,
    sizeOnDisk: disk,
    uncompressed: unc,
    start,
  });
  let pos = 64;
  const strings = mk(u(0), u(1), pos);
  pos += strings.disk;
  const nodes = mk(u(4), u(5), pos);
  pos += nodes.disk;
  const attrs = mk(u(6), u(7), pos);
  pos += attrs.disk;
  const values = mk(u(8), u(9), pos);
  pos += values.disk;
  return {
    ver,
    cflags,
    mfmt,
    hasKeys: mfmt === 1,
    keysUnc: u(2),
    keysDisk: u(3),
    sections: { strings, nodes, attrs, values },
    end: pos,
  };
}

/** Lazily-decoded LSF internals shared by a frame's section streams. */
class LsfParsed {
  info: LsofInfo;
  private frame: Uint8Array;
  private cache = new Map<string, Uint8Array>();
  private namesCache: string[][] | null = null;
  private startsCache: Uint32Array | null = null;

  constructor(frame: Uint8Array) {
    this.frame = frame;
    this.info = lsofInfo(frame);
  }

  section(sec: 'strings' | 'nodes' | 'attrs' | 'values'): Uint8Array {
    let b = this.cache.get(sec);
    if (!b) {
      const s = this.info.sections[sec];
      b = decompSection(
        this.frame.subarray(s.start, s.start + s.disk),
        s.sizeOnDisk,
        s.uncompressed,
        this.info.cflags,
        sec !== 'strings' && this.info.ver >= 2,
      );
      this.cache.set(sec, b);
    }
    return b;
  }

  names(): string[][] {
    if (!this.namesCache) this.namesCache = parseStringTable(this.section('strings'));
    return this.namesCache;
  }

  name(nh: number): string {
    const names = this.names();
    return names[nh >>> 16]?.[nh & 0xffff] ?? `?${nh.toString(16).padStart(8, '0')}`;
  }

  nodeSize(): number {
    return this.info.hasKeys ? 16 : 12;
  }

  nodeCount(): number {
    return Math.floor(this.section('nodes').length / this.nodeSize());
  }

  nodeName(i: number): string {
    const nd = this.section('nodes');
    if (i < 0 || i >= this.nodeCount()) return '?';
    return this.name(dvOf(nd).getUint32(i * this.nodeSize(), true));
  }

  attrCount(): number {
    return Math.floor(this.section('attrs').length / (this.info.hasKeys ? 16 : 12));
  }

  /** V2 value offsets: attribute values are packed back-to-back in order. */
  valueStarts(): Uint32Array {
    if (!this.startsCache) {
      const att = this.section('attrs');
      const adv = dvOf(att);
      const n = this.attrCount();
      const starts = new Uint32Array(n + 1);
      let off = 0;
      for (let i = 0; i < n; i++) {
        starts[i] = off;
        off += adv.getUint32(i * 12 + 4, true) >>> 6;
      }
      starts[n] = off;
      this.startsCache = starts;
    }
    return this.startsCache;
  }

  /** [values offset, length] of the root NewAge ScratchBuffer, or null. */
  newAgeSpan(): [number, number] | null {
    if (this.info.hasKeys) return null;
    const att = this.section('attrs');
    const adv = dvOf(att);
    const starts = this.valueStarts();
    for (let i = 0; i < this.attrCount(); i++) {
      const tl = adv.getUint32(i * 12 + 4, true);
      if ((tl & 0x3f) !== 25) continue;
      if (this.name(adv.getUint32(i * 12, true)) !== 'NewAge') continue;
      const ni = adv.getInt32(i * 12 + 8, true);
      if (this.nodeName(ni) === 'NewAge') return [starts[i]!, tl >>> 6];
    }
    return null;
  }

  hasNewAgeName(): boolean {
    return this.names().some((chain) => chain.includes('NewAge'));
  }
}

/* ---- JSON top-level tokenizer (byte offsets, ASCII-safe) ----------------- */

function jsonTopLevelRegions(data: Uint8Array): Region[] | null {
  const isWs = (b: number) => b === 0x20 || b === 0x09 || b === 0x0a || b === 0x0d;
  let i = 0;
  while (i < data.length && isWs(data[i]!)) i++;
  if (data[i] !== 0x7b /* { */) return null;
  const open = i;
  i++;
  const regions: Region[] = [
    {
      start: 0,
      end: open + 1,
      label: 'object start',
      detail: 'UTF-8 JSON text; the frame is stored as one zstd-compressed JSON document.',
    },
  ];
  const skipString = (): number | null => {
    if (data[i] !== 0x22) return null;
    const s = i;
    i++;
    while (i < data.length) {
      if (data[i] === 0x5c) i += 2;
      else if (data[i] === 0x22) {
        i++;
        return s;
      } else i++;
    }
    return null;
  };
  try {
    for (;;) {
      while (i < data.length && (isWs(data[i]!) || data[i] === 0x2c)) i++;
      if (i >= data.length) return null;
      if (data[i] === 0x7d /* } */) {
        regions.push({
          start: i,
          end: data.length,
          label: 'object end',
          detail: 'Closing brace and any trailing whitespace.',
        });
        return regions;
      }
      const keyStart = skipString();
      if (keyStart === null) return null;
      const key = utf8.decode(data.subarray(keyStart + 1, i - 1));
      while (i < data.length && isWs(data[i]!)) i++;
      if (data[i] !== 0x3a /* : */) return null;
      i++;
      while (i < data.length && isWs(data[i]!)) i++;
      const valStart = i;
      let depth = 0;
      for (;;) {
        if (i >= data.length) return null;
        const b = data[i]!;
        if (b === 0x22) {
          if (skipString() === null) return null;
          continue;
        }
        if (b === 0x7b || b === 0x5b) depth++;
        if (b === 0x7d || b === 0x5d) {
          if (depth === 0) break;
          depth--;
          if (depth === 0) {
            i++;
            break;
          }
          i++;
          continue;
        }
        if (depth === 0 && b === 0x2c) break;
        i++;
      }
      regions.push({
        start: keyStart,
        end: i,
        label: `“${key}”`,
        detail: `Value: ${escapePreview(utf8.decode(data.subarray(valStart, Math.min(i, valStart + 160))))}`,
      });
    }
  } catch {
    return null;
  }
}

/* ---- RIFF / WebP chunks --------------------------------------------------- */

const RIFF_NOTES: Record<string, string> = {
  'VP8 ': 'Lossy WebP bitstream (VP8): the 1280×720 load-screen image data.',
  VP8L: 'Lossless WebP bitstream.',
  VP8X: 'Extended-format header: canvas size and feature flags.',
  ICCP: 'ICC colour profile.',
  EXIF: 'EXIF metadata.',
  'XMP ': 'XMP metadata.',
  ANIM: 'Animation parameters.',
};

function riffRegions(data: Uint8Array): Region[] {
  const dv = dvOf(data);
  const riffSize = dv.getUint32(4, true);
  const regions: Region[] = [
    {
      start: 0,
      end: 12,
      label: 'RIFF header',
      detail: `“RIFF”, u32 payload size = ${fmtInt(riffSize)}, then the form type “WEBP”.`,
      kids: [
        { start: 0, end: 4, label: 'magic “RIFF”' },
        { start: 4, end: 8, label: `payload size = ${fmtInt(riffSize)}` },
        { start: 8, end: 12, label: 'form type “WEBP”' },
      ],
    },
  ];
  let pos = 12;
  while (pos + 8 <= data.length) {
    const fourcc = latin1.decode(data.subarray(pos, pos + 4));
    const size = dv.getUint32(pos + 4, true);
    const end = Math.min(pos + 8 + size + (size % 2), data.length);
    regions.push({
      start: pos,
      end,
      label: `chunk “${fourcc}”`,
      detail:
        `${fmtBytes(size)} of chunk data (padded to an even length). ${RIFF_NOTES[fourcc] ?? ''}`.trim(),
      kids: [
        { start: pos, end: pos + 4, label: `fourcc “${fourcc}”` },
        { start: pos + 4, end: pos + 8, label: `chunk size = ${fmtInt(size)}` },
        { start: pos + 8, end, label: `${fourcc} data` },
      ],
    });
    pos = end;
  }
  return regions;
}

/* ---- The anatomy engine --------------------------------------------------- */

const LSPK_FILE_ENTRY = 272;
/** Cached streams kept per save (beyond the container itself). */
const STREAM_CACHE_MAX = 8;

export class SaveAnatomy {
  private file: Uint8Array;
  private streams = new Map<string, StreamData>();
  private lru: string[] = [];
  private lsfCache = new Map<string, LsfParsed>();
  /** Package entries: [canonical frame name, stored path, entry fields]. */
  private entries: {
    name: string;
    path: string;
    offset: number;
    part: number;
    flags: number;
    sizeOnDisk: number;
    uncompressed: number;
  }[];
  private flistOff: number;
  private numFiles: number;
  private compSize: number;

  constructor(bytes: Uint8Array) {
    this.file = bytes;
    const dv = dvOf(bytes);
    if (latin1.decode(bytes.subarray(0, 4)) !== 'LSPK') {
      throw new Error('not an LSPK package: a .lsv save starts with the four bytes “LSPK”');
    }
    this.flistOff = dv.getUint32(8, true) + dv.getUint32(12, true) * 2 ** 32;
    this.numFiles = dv.getUint32(this.flistOff, true);
    this.compSize = dv.getUint32(this.flistOff + 4, true);
    const raw = lz4BlockDecompress(
      bytes.subarray(this.flistOff + 8, this.flistOff + 8 + this.compSize),
      this.numFiles * LSPK_FILE_ENTRY,
    );
    const rdv = dvOf(raw);
    this.entries = [];
    for (let i = 0; i < this.numFiles; i++) {
      const b = i * LSPK_FILE_ENTRY;
      let end = b;
      while (end < b + 256 && raw[end] !== 0) end++;
      const path = latin1.decode(raw.subarray(b, end));
      this.entries.push({
        name: path.toLowerCase().endsWith('.webp') ? 'thumbnail' : path,
        path,
        offset: rdv.getUint32(b + 256, true) + rdv.getUint16(b + 260, true) * 2 ** 32,
        part: rdv.getUint8(b + 262),
        flags: rdv.getUint8(b + 263),
        sizeOnDisk: rdv.getUint32(b + 264, true),
        uncompressed: rdv.getUint32(b + 268, true),
      });
    }
    this.entries.sort((a, b) => a.offset - b.offset);
  }

  meta(id: string): StreamMeta {
    return this.stream(id).meta;
  }

  window(id: string, start: number, end: number): { bytes: Uint8Array; regions: WindowRegion[] } {
    const s = this.stream(id);
    const from = Math.max(0, Math.min(start, s.meta.size));
    const to = Math.max(from, Math.min(end, s.meta.size));
    return { bytes: s.bytes.slice(from, to), regions: windowRegions(s.leaves, from, to) };
  }

  stream(id: string): StreamData {
    let s = this.streams.get(id);
    if (!s) {
      s = this.build(id);
      this.streams.set(id, s);
    }
    this.touch(id);
    return s;
  }

  private touch(id: string): void {
    const i = this.lru.indexOf(id);
    if (i >= 0) this.lru.splice(i, 1);
    this.lru.push(id);
    // The container stream is small (it shares this.file); never evict it.
    const evictable = this.lru.filter((k) => k !== 'file' && k !== 'filelist');
    while (evictable.length > STREAM_CACHE_MAX) {
      const victim = evictable.shift()!;
      this.streams.delete(victim);
      if (victim.startsWith('frame/')) this.lsfCache.delete(victim.slice('frame/'.length));
      this.lru.splice(this.lru.indexOf(victim), 1);
    }
  }

  private build(id: string): StreamData {
    if (id === 'file') return this.buildFile();
    if (id === 'filelist') return this.buildFilelist();
    if (id.startsWith('frame/')) return this.buildFrame(id.slice('frame/'.length));
    if (id.startsWith('lsmf/')) return this.buildLsmf(id.slice('lsmf/'.length));
    if (id.startsWith('lsf/')) {
      const rest = id.slice('lsf/'.length);
      const cut = rest.lastIndexOf('/');
      const sec = rest.slice(cut + 1);
      if (sec === 'strings' || sec === 'nodes' || sec === 'attrs' || sec === 'values') {
        return this.buildLsfSection(rest.slice(0, cut), sec);
      }
    }
    throw new Error(`unknown stream ${id}`);
  }

  private finish(
    id: string,
    title: string,
    note: string,
    parent: string | null,
    bytes: Uint8Array,
    regions: Region[],
    tables: Map<Region, DenseTable>,
    children: StreamRef[],
  ): StreamData {
    const leaves = flatten(regions, tables);
    return {
      meta: {
        id,
        title,
        note,
        size: bytes.length,
        covered: coveredBytes(leaves, bytes.length),
        parent,
        regions,
        children,
      },
      bytes,
      tables,
      leaves,
    };
  }

  private entry(name: string) {
    const e = this.entries.find((x) => x.name === name);
    if (!e) throw new Error(`no file “${name}” in this package`);
    return e;
  }

  private frameBytes(name: string): Uint8Array {
    const e = this.entry(name);
    return zstdDecompress(this.file.subarray(e.offset, e.offset + e.sizeOnDisk));
  }

  private lsf(name: string): LsfParsed {
    let p = this.lsfCache.get(name);
    if (!p) {
      p = new LsfParsed(this.stream(`frame/${name}`).bytes);
      this.lsfCache.set(name, p);
    }
    return p;
  }

  /* -- the raw .lsv container -- */

  private buildFile(): StreamData {
    const data = this.file;
    const dv = dvOf(data);
    const version = dv.getUint32(4, true);
    const md5 = [...data.subarray(22, 38)].map((b) => b.toString(16).padStart(2, '0')).join('');
    const numParts = dv.getUint16(38, true);
    const tables = new Map<Region, DenseTable>();

    const regions: Region[] = [
      {
        start: 0,
        end: 40,
        label: 'LSPK header',
        detail:
          'A .lsv save is an LSPK v18 package — the same container the game’s .pak data files use.',
        kids: [
          { start: 0, end: 4, label: 'magic “LSPK”' },
          {
            start: 4,
            end: 8,
            label: `package version = ${version}`,
            detail: 'u32; 18 for Patch-8 era saves.',
          },
          {
            start: 8,
            end: 16,
            label: `file-list offset = ${fmtInt(this.flistOff)}`,
            detail: 'u64 absolute offset. The file list sits after the data, near the end.',
          },
          {
            start: 16,
            end: 20,
            label: `file-list size = ${fmtInt(dv.getUint32(16, true))}`,
            detail: 'u32 compressed size of the file-list entry table.',
          },
          { start: 20, end: 21, label: `flags = ${hex(dv.getUint8(20))}` },
          { start: 21, end: 22, label: `priority = ${dv.getUint8(21)}` },
          { start: 22, end: 38, label: `MD5 = ${md5}` },
          {
            start: 38,
            end: 40,
            label: `parts = ${numParts}`,
            detail: 'u16; multi-part packages spill into Name_<part>.pak files. Saves use 1.',
          },
        ],
      },
    ];

    for (const e of this.entries) {
      regions.push({
        start: e.offset,
        end: e.offset + e.sizeOnDisk,
        label: e.name,
        stream: `frame/${e.name}`,
        detail:
          `Stored path “${e.path}”. One zstd frame: ${fmtBytes(e.sizeOnDisk)} on disk → ` +
          `${fmtBytes(e.uncompressed)} decompressed (entry flags ${hex(e.flags)}, part ${e.part}). ` +
          `${frameNote(e.name)}`,
      });
    }

    const flEnd = this.flistOff + 8 + this.compSize;
    regions.push({
      start: this.flistOff,
      end: flEnd,
      label: 'file list',
      stream: 'filelist',
      detail: `The package’s table of contents: ${this.numFiles} entries of 272 bytes each, LZ4-block compressed.`,
      kids: [
        { start: this.flistOff, end: this.flistOff + 4, label: `file count = ${this.numFiles}` },
        {
          start: this.flistOff + 4,
          end: this.flistOff + 8,
          label: `compressed size = ${fmtInt(this.compSize)}`,
        },
        {
          start: this.flistOff + 8,
          end: flEnd,
          label: 'LZ4-compressed entry table',
          detail: `Inflates to ${this.numFiles} × 272 bytes — decoded in the “file list” stream.`,
        },
      ],
    });

    const filled = fillGaps(
      regions,
      data.length,
      'unindexed bytes',
      'Bytes not covered by the LSPK header, any file entry, or the file list. Typically alignment padding between frames.',
    );

    const children: StreamRef[] = [
      {
        id: 'filelist',
        title: 'file list',
        size: this.numFiles * LSPK_FILE_ENTRY,
        note: 'The decompressed 272-byte-per-file entry table.',
      },
      ...this.entries.map((e) => ({
        id: `frame/${e.name}`,
        title: e.name,
        size: e.uncompressed,
        note: frameNote(e.name),
      })),
    ];

    return this.finish(
      'file',
      'the .lsv package',
      `LSPK v18 package: ${this.numFiles} files, ${fmtBytes(data.length)}. Every contained file is one zstd frame.`,
      null,
      data,
      filled,
      tables,
      children,
    );
  }

  /* -- the decompressed file-list entry table -- */

  private buildFilelist(): StreamData {
    const raw = lz4BlockDecompress(
      this.file.subarray(this.flistOff + 8, this.flistOff + 8 + this.compSize),
      this.numFiles * LSPK_FILE_ENTRY,
    );
    const rdv = dvOf(raw);
    const tables = new Map<Region, DenseTable>();
    const region: Region = {
      start: 0,
      end: raw.length,
      label: `file entries (${this.numFiles} × 272 B)`,
      detail:
        'Each entry: 256-byte NUL-padded path, u32 offset-low, u16 offset-high, u8 archive part, u8 flags (low nibble = compression method), u32 size on disk, u32 uncompressed size.',
    };
    tables.set(region, {
      start: 0,
      end: raw.length,
      count: this.numFiles,
      stride: LSPK_FILE_ENTRY,
      entry: (i) => {
        const b = i * LSPK_FILE_ENTRY;
        let end = b;
        while (end < b + 256 && raw[end] !== 0) end++;
        const path = latin1.decode(raw.subarray(b, end));
        const off = rdv.getUint32(b + 256, true) + rdv.getUint16(b + 260, true) * 2 ** 32;
        const disk = rdv.getUint32(b + 264, true);
        const unc = rdv.getUint32(b + 268, true);
        return {
          label: path,
          detail:
            `Entry ${i}: data at offset ${fmtInt(off)} (${hex(off)}); ${fmtBytes(disk)} on disk → ` +
            `${fmtBytes(unc)} uncompressed; part ${rdv.getUint8(b + 262)}; flags ${hex(rdv.getUint8(b + 263))}.`,
        };
      },
    });
    return this.finish(
      'filelist',
      'file list',
      `The package table of contents, LZ4-inflated: ${this.numFiles} entries.`,
      'file',
      raw,
      fillGaps([region], raw.length, 'padding', 'Trailing bytes after the last entry.'),
      tables,
      [],
    );
  }

  /* -- one decompressed frame -- */

  private buildFrame(name: string): StreamData {
    const e = this.entry(name);
    const bytes = this.frameBytes(name);
    const id = `frame/${name}`;
    const magic = latin1.decode(bytes.subarray(0, 4));
    const tables = new Map<Region, DenseTable>();

    if (magic === 'LSOF') {
      const p = new LsfParsed(bytes);
      this.lsfCache.set(name, p);
      return this.buildLsofFrame(id, name, bytes, p, tables);
    }

    if (magic === 'RIFF') {
      return this.finish(
        id,
        name,
        'RIFF/WebP image — the save’s load-screen thumbnail.',
        'file',
        bytes,
        fillGaps(riffRegions(bytes), bytes.length, 'trailing bytes', 'Bytes after the last chunk.'),
        tables,
        [],
      );
    }

    const osi = name === 'StorySave.bin' ? osirisAnatomy(bytes) : null;
    if (osi) return this.buildOsirisFrame(id, name, bytes, osi, tables);

    const json = jsonTopLevelRegions(bytes);
    if (json) {
      return this.finish(
        id,
        name,
        `UTF-8 JSON document, ${fmtBytes(bytes.length)}. ${frameNote(name)}`,
        'file',
        bytes,
        fillGaps(json, bytes.length, 'whitespace', 'Inter-token whitespace.'),
        tables,
        [],
      );
    }

    return this.finish(
      id,
      name,
      `Frame with unrecognised magic “${escapePreview(magic, 8)}” — ${fmtBytes(bytes.length)}.`,
      'file',
      bytes,
      [
        {
          start: 0,
          end: bytes.length,
          label: 'unrecognised frame',
          detail: `Decompressed from “${e.path}” but not a format this parser decodes.`,
          kind: 'gap',
        },
      ],
      tables,
      [],
    );
  }

  private buildLsofFrame(
    id: string,
    name: string,
    bytes: Uint8Array,
    p: LsfParsed,
    tables: Map<Region, DenseTable>,
  ): StreamData {
    const dv = dvOf(bytes);
    const info = p.info;
    const m = info.cflags & 0x0f;
    const method = m === 0 ? 'stored uncompressed' : m === 2 ? 'LZ4-compressed' : `method ${m}`;

    const sizeKids: Region[] = [];
    const names = ['strings', 'keys', 'nodes', 'attributes', 'values'];
    for (let i = 0; i < 10; i++) {
      const which = i % 2 === 0 ? 'uncompressed size' : 'size on disk';
      sizeKids.push({
        start: 16 + i * 4,
        end: 20 + i * 4,
        label: `${names[Math.floor(i / 2)]} ${which} = ${fmtInt(dv.getUint32(16 + i * 4, true))}`,
      });
    }
    const header: Region = {
      start: 0,
      end: 64,
      label: 'LSOF header',
      detail:
        'LSF binary resource header: magic, version, engine version, ten u32 section sizes, compression flags, and MetadataFormat.',
      kids: [
        { start: 0, end: 4, label: 'magic “LSOF”' },
        { start: 4, end: 8, label: `format version = ${info.ver}` },
        {
          start: 8,
          end: 16,
          label: `engine version = 0x${dv.getBigUint64(8, true).toString(16)}`,
          detail: 'i64, packed major.minor.revision.build.',
        },
        ...sizeKids,
        {
          start: 56,
          end: 57,
          label: `compression flags = ${hex(info.cflags)}`,
          detail: `Low nibble = method (${m}: ${method}), high nibble = level.`,
        },
        { start: 57, end: 60, label: 'reserved (0)' },
        {
          start: 60,
          end: 64,
          label: `MetadataFormat = ${info.mfmt}`,
          detail:
            info.mfmt === 1
              ? '1 = KeysAndAdjacency: the extended V3 16-byte node/attribute layout.'
              : `${info.mfmt} = the compact V2 12-byte node/attribute layout.`,
        },
      ],
    };

    const secRegion = (sec: 'strings' | 'nodes' | 'attrs' | 'values', title: string): Region => {
      const s = info.sections[sec];
      return {
        start: s.start,
        end: s.start + s.disk,
        label: `${title} section`,
        stream: `lsf/${name}/${sec}`,
        detail:
          s.sizeOnDisk === 0
            ? `${fmtBytes(s.disk)}, stored uncompressed.`
            : `${fmtBytes(s.sizeOnDisk)} on disk → ${fmtBytes(s.uncompressed)} decompressed (${method}).`,
      };
    };

    const regions = [
      header,
      secRegion('strings', 'strings'),
      secRegion('nodes', 'nodes'),
      secRegion('attrs', 'attributes'),
      secRegion('values', 'values'),
    ];

    const children: StreamRef[] = [
      {
        id: `lsf/${name}/strings`,
        title: `${name} › strings`,
        size: info.sections.strings.uncompressed || info.sections.strings.disk,
        note: 'The deduplicated name table: every node and attribute name.',
      },
      {
        id: `lsf/${name}/nodes`,
        title: `${name} › nodes`,
        size: info.sections.nodes.uncompressed || info.sections.nodes.disk,
        note: 'The node tree as a flat table of fixed-size entries.',
      },
      {
        id: `lsf/${name}/attrs`,
        title: `${name} › attributes`,
        size: info.sections.attrs.uncompressed || info.sections.attrs.disk,
        note: 'Typed attribute entries: name, type, length, owning node.',
      },
      {
        id: `lsf/${name}/values`,
        title: `${name} › values`,
        size: info.sections.values.uncompressed || info.sections.values.disk,
        note: 'Every attribute’s raw value bytes, packed back-to-back.',
      },
    ];
    let hasBlob = false;
    try {
      hasBlob = !info.hasKeys && p.hasNewAgeName();
    } catch {
      hasBlob = false;
    }
    if (hasBlob) {
      children.push({
        id: `lsmf/${name}`,
        title: `${name} › NewAge blob`,
        size: 0,
        note: 'The LSMF ECS world dump carried inside one ScratchBuffer attribute.',
      });
    }

    const keysNote =
      info.keysUnc || info.keysDisk
        ? ` The header declares a keys section (${fmtInt(info.keysUnc)} B uncompressed) but no key data is stored between the sections in save frames.`
        : '';
    return this.finish(
      id,
      name,
      `LSOF v${info.ver} resource: ${fmtInt(p.nodeCount())} nodes, ${fmtInt(p.attrCount())} attributes.${keysNote}`,
      'file',
      bytes,
      fillGaps(
        regions,
        bytes.length,
        'trailing bytes',
        'Bytes after the values section; not read by this parser.',
      ),
      tables,
      children,
    );
  }

  private buildOsirisFrame(
    id: string,
    name: string,
    bytes: Uint8Array,
    osi: NonNullable<ReturnType<typeof osirisAnatomy>>,
    tables: Map<Region, DenseTable>,
  ): StreamData {
    const verEnd = 1 + osi.versionString.length + 1;
    const header: Region = {
      start: 0,
      end: osi.headerEnd,
      label: 'Osiris header',
      detail: 'After this header every string in the file is XOR-scrambled byte-by-byte with 0xAD.',
      kids: [
        { start: 0, end: 1, label: 'null byte' },
        {
          start: 1,
          end: verEnd,
          label: `version string “${osi.versionString}”`,
          detail: 'NUL-terminated, stored unscrambled.',
        },
        {
          start: verEnd,
          end: verEnd + 4,
          label: `major.minor = ${osi.version >> 8}.${osi.version & 0xff}`,
          detail: 'u8 major, u8 minor, u8 big-endian flag (unused), u8 unused.',
        },
        { start: verEnd + 4, end: verEnd + 4 + 0x80, label: 'version buffer (0x80 bytes)' },
        { start: osi.headerEnd - 4, end: osi.headerEnd, label: 'debug flags (u32)' },
      ],
    };
    const notes: Record<string, string> = {
      Types: 'Named type table: (name, index, alias) per entry.',
      Enums: 'Enum definitions: labels and values per enum type.',
      DivObjects: 'DIV object table.',
      Functions: 'Function signatures for every call, query, proc and event.',
      Nodes:
        'The compiled Rete network: databases, procs, queries, rules, AND/NOT-AND joins. This is where database names live.',
      Adapters: 'Tuple adapters mapping rule variables onto database columns.',
      Databases:
        'The live story facts: every database’s rows — quest flags, counters, approval ratings, waypoints.',
      Goals: 'Goal records with init/exit calls; flags 0x07 marks a finalized goal.',
      GlobalActions: 'Deferred global calls.',
    };
    const regions: Region[] = [
      header,
      ...osi.sections.map((s) => ({
        start: s.start,
        end: s.end,
        label: `${s.name} (${fmtInt(s.count)})`,
        detail:
          `${notes[s.name] ?? ''} ${fmtInt(s.count)} entries, ${fmtBytes(s.end - s.start)}; read sequentially — the format has no offset table.`.trim(),
      })),
    ];
    const complete = osi.consumed === bytes.length;
    return this.finish(
      id,
      name,
      `Osiris story save, “${osi.versionString}”. ${
        complete
          ? `The parser consumed all ${fmtInt(bytes.length)} bytes — nothing unaccounted.`
          : `${fmtInt(bytes.length - osi.consumed)} bytes unread after the last section.`
      }`,
      'file',
      bytes,
      fillGaps(regions, bytes.length, 'unread bytes', 'Bytes after the last parsed section.'),
      tables,
      [],
    );
  }

  /* -- decoded LSF sections -- */

  private buildLsfSection(name: string, sec: 'strings' | 'nodes' | 'attrs' | 'values'): StreamData {
    const p = this.lsf(name);
    const bytes = p.section(sec);
    const id = `lsf/${name}/${sec}`;
    const parent = `frame/${name}`;
    const tables = new Map<Region, DenseTable>();
    const dv = dvOf(bytes);

    if (sec === 'strings') {
      const n = bytes.length >= 4 ? dv.getUint32(0, true) : 0;
      const starts = new Uint32Array(n + 1);
      let pos = 4;
      for (let i = 0; i < n; i++) {
        starts[i] = pos;
        const ns = dv.getUint16(pos, true);
        pos += 2;
        for (let j = 0; j < ns; j++) {
          pos += 2 + dv.getUint16(pos, true);
        }
      }
      starts[n] = pos;
      const chains: Region = {
        start: 4,
        end: pos,
        label: 'string hash chains',
        detail:
          'Per chain: u16 string count, then (u16 length, UTF-8 bytes) per string. A name handle packs chain index (high 16 bits) and position in the chain (low 16 bits).',
      };
      tables.set(chains, {
        start: 4,
        end: pos,
        count: n,
        starts,
        entry: (i) => {
          let q = starts[i]!;
          const ns = dv.getUint16(q, true);
          q += 2;
          const items: string[] = [];
          for (let j = 0; j < Math.min(ns, 24); j++) {
            const slen = dv.getUint16(q, true);
            q += 2;
            items.push(utf8.decode(bytes.subarray(q, q + slen)));
            q += slen;
          }
          const first = items[0] ?? '(empty)';
          return {
            label: ns > 1 ? `chain ${i}: “${first}” +${ns - 1} more` : `chain ${i}: “${first}”`,
            detail: `${ns} string${ns === 1 ? '' : 's'}: ${items.map((s) => `“${escapePreview(s, 40)}”`).join(', ')}${ns > 24 ? ', …' : ''}`,
          };
        },
      });
      return this.finish(
        id,
        `${name} › strings`,
        `Name table: ${fmtInt(n)} hash chains. Every node and attribute name in the frame, stored once.`,
        parent,
        bytes,
        fillGaps(
          [{ start: 0, end: 4, label: `chain count = ${fmtInt(n)}` }, chains],
          bytes.length,
          'trailing bytes',
          'Bytes after the last chain.',
        ),
        tables,
        [],
      );
    }

    if (sec === 'nodes') {
      const stride = p.nodeSize();
      const count = p.nodeCount();
      const region: Region = {
        start: 0,
        end: count * stride,
        label: `node table (${fmtInt(count)} × ${stride} B)`,
        detail: p.info.hasKeys
          ? 'V3 entry: u32 name handle, i32 parent, i32 next sibling, i32 first attribute.'
          : 'V2 entry: u32 name handle, i32 first attribute index, i32 parent index (−1 = root region).',
      };
      tables.set(region, {
        start: 0,
        end: count * stride,
        count,
        stride,
        entry: (i) => {
          const b = i * stride;
          const nh = dv.getUint32(b, true);
          const nodeName = p.name(nh);
          const par = dv.getInt32(b + (p.info.hasKeys ? 4 : 8), true);
          const fa = dv.getInt32(b + (p.info.hasKeys ? 12 : 4), true);
          return {
            label: `#${fmtInt(i)} ${nodeName}`,
            detail: `Name handle ${hex(nh, 8)} → “${nodeName}”; parent ${
              par === -1 ? 'none — a root region' : `#${fmtInt(par)} (${p.nodeName(par)})`
            }; first attribute ${fa === -1 ? 'none' : `#${fmtInt(fa)}`}.`,
          };
        },
      });
      return this.finish(
        id,
        `${name} › nodes`,
        `The frame’s node tree, flattened: ${fmtInt(count)} nodes of ${stride} bytes.`,
        parent,
        bytes,
        fillGaps([region], bytes.length, 'trailing bytes', 'Bytes after the last node entry.'),
        tables,
        [],
      );
    }

    const attrStride = p.info.hasKeys ? 16 : 12;
    const count = p.attrCount();
    const att = p.section('attrs');
    const adv = dvOf(att);
    const starts = p.info.hasKeys ? null : p.valueStarts();

    if (sec === 'attrs') {
      const region: Region = {
        start: 0,
        end: count * attrStride,
        label: `attribute table (${fmtInt(count)} × ${attrStride} B)`,
        detail: p.info.hasKeys
          ? 'V3 entry: u32 name handle, u32 type-and-length, i32 next attribute, u32 value offset.'
          : 'V2 entry: u32 name handle, u32 type-and-length (type = low 6 bits, length = the rest), i32 owning node. Values are packed in attribute order.',
      };
      tables.set(region, {
        start: 0,
        end: count * attrStride,
        count,
        stride: attrStride,
        entry: (i) => {
          const b = i * attrStride;
          const nh = adv.getUint32(b, true);
          const tl = adv.getUint32(b + 4, true);
          const tid = tl & 0x3f;
          const len = tl >>> 6;
          const attrName = p.name(nh);
          const owner = p.info.hasKeys ? null : adv.getInt32(b + 8, true);
          return {
            label: `#${fmtInt(i)} ${attrName}`,
            detail:
              `Type ${tid} (${ATTR_TYPE_NAMES[tid] ?? '?'}), ${fmtInt(len)} B` +
              (owner === null
                ? `; value at ${hex(adv.getUint32(b + 12, true))}.`
                : `; on node #${fmtInt(owner)} (${p.nodeName(owner)}); value at ${hex(starts![i]!)} in the values stream.`),
          };
        },
      });
      return this.finish(
        id,
        `${name} › attributes`,
        `${fmtInt(count)} typed attributes of ${attrStride} bytes each.`,
        parent,
        bytes,
        fillGaps([region], bytes.length, 'trailing bytes', 'Bytes after the last attribute.'),
        tables,
        [],
      );
    }

    // values
    const children: StreamRef[] = [];
    let newAge: [number, number] | null = null;
    try {
      newAge = p.newAgeSpan();
    } catch {
      newAge = null;
    }
    if (newAge) {
      children.push({
        id: `lsmf/${name}`,
        title: `${name} › NewAge blob`,
        size: newAge[1],
        note: 'The LSMF ECS world dump stored in this section as one ScratchBuffer value.',
      });
    }
    if (starts === null) {
      return this.finish(
        id,
        `${name} › values`,
        'Attribute values, addressed by explicit per-attribute offsets (V3 layout).',
        parent,
        bytes,
        [
          {
            start: 0,
            end: bytes.length,
            label: 'attribute values (offset-addressed)',
            detail:
              'V3 frames address values by explicit offset; per-value annotation is not derived for this layout.',
          },
        ],
        tables,
        children,
      );
    }
    const total = starts[count] ?? 0;
    const region: Region = {
      start: 0,
      end: total,
      label: 'attribute values, packed back-to-back',
      detail:
        'Each attribute’s raw bytes, in attribute-table order. The byte width of every entry comes from the attribute’s type-and-length field.',
    };
    tables.set(region, {
      start: 0,
      end: total,
      count,
      starts,
      entry: (i) => {
        const b = i * 12;
        const tl = adv.getUint32(b + 4, true);
        const tid = tl & 0x3f;
        const len = tl >>> 6;
        const attrName = p.name(adv.getUint32(b, true));
        const owner = adv.getInt32(b + 8, true);
        const v = readVal(bytes, dv, starts[i]!, tid, len);
        let preview = previewValue(v, tid);
        if (tid === 25 && attrName === 'NewAge') {
          preview += ' — the LSMF ECS world dump; open the NewAge blob stream to see inside';
        }
        return {
          label: `${p.nodeName(owner)}.${attrName}`,
          detail: `${ATTR_TYPE_NAMES[tid] ?? `type ${tid}`}, ${fmtInt(len)} B — ${preview}`,
        };
      },
    });
    return this.finish(
      id,
      `${name} › values`,
      `${fmtInt(count)} attribute values, ${fmtBytes(bytes.length)} of payload.`,
      parent,
      bytes,
      fillGaps([region], bytes.length, 'trailing bytes', 'Bytes after the last attribute value.'),
      tables,
      children,
    );
  }

  /* -- the LSMF ECS blob -- */

  private buildLsmf(name: string): StreamData {
    const p = this.lsf(name);
    const span = p.newAgeSpan();
    if (!span) throw new Error(`no NewAge ScratchBuffer in ${name}`);
    const blob = p.section('values').subarray(span[0], span[0] + span[1]);
    const id = `lsmf/${name}`;
    const parent = `frame/${name}`;
    const tables = new Map<Region, DenseTable>();
    const dv = dvOf(blob);
    const scan = scanLsmfBlob(blob);

    if (!scan) {
      return this.finish(
        id,
        `${name} › NewAge blob`,
        'LSMF ECS blob — the directory scan failed, so only the header is annotated.',
        parent,
        blob,
        [
          {
            start: 0,
            end: blob.length,
            label: 'LSMF blob (unscanned)',
            kind: 'gap',
            detail: 'The component-directory scan did not validate on this blob.',
          },
        ],
        tables,
        [],
      );
    }

    const dirOff = Number(dv.getBigUint64(16, true));
    const namesSize = Number(dv.getBigUint64(24, true));
    const namesOff = dirOff + 48;
    const descRel = dv.getUint32(32, true);
    const entryCount = dv.getUint16(36, true);
    const descBase = namesOff + descRel;

    const header: Region = {
      start: 0,
      end: 48,
      label: 'LSMF header',
      detail:
        'The ECS world dump. Every absolute pointer stored in the blob obeys the “+48” rule: stored value + 48 = real offset.',
      kids: [
        { start: 0, end: 8, label: 'magic “LSMF” + version bytes 01 01 00 08' },
        {
          start: 8,
          end: 16,
          label: 'per-save unique id',
          detail: 'u64, random per save; not a content hash.',
        },
        {
          start: 16,
          end: 24,
          label: `dir_off = ${fmtInt(dirOff)}`,
          detail: `u64 raw directory pointer; the names blob starts at dir_off + 48 = ${fmtInt(namesOff)}.`,
        },
        {
          start: 24,
          end: 32,
          label: `names_size = ${fmtInt(namesSize)}`,
          detail: 'u64 byte length of the component-type directory (names text + descriptors).',
        },
        {
          start: 32,
          end: 36,
          label: `desc_table_rel = ${fmtInt(descRel)}`,
          detail: 'u32 descriptor-table offset, relative to the names blob.',
        },
        { start: 36, end: 38, label: `entry_count = ${entryCount} component types` },
        { start: 38, end: 48, label: 'unidentified header bytes', kind: 'gap' },
      ],
    };

    const regions: Region[] = [header];
    const ownerOf = new Map<number, { start: number; ec: number }>();
    scan.records.forEach(([comp, start, ec]) => {
      ownerOf.set(comp, { start, ec });
    });

    // Component column data: one region per non-empty component.
    scan.compDescs.forEach((d, ci) => {
      const len = d.rowCount * d.elemSize;
      if (len <= 0 || d.dataOffset <= 0 || d.dataOffset + len > blob.length) return;
      const region: Region = {
        start: d.dataOffset,
        end: d.dataOffset + len,
        label: d.name || `component #${ci}`,
        detail: `Component #${ci} column data: ${fmtInt(d.rowCount)} rows × ${d.elemSize} B. Row k belongs to the entity at position k of this component’s ownerlist.`,
      };
      const owners = ownerOf.get(ci);
      const isEntityId = d.name === 'core.v0.EntityId' && d.elemSize === 16;
      tables.set(region, {
        start: d.dataOffset,
        end: d.dataOffset + len,
        count: d.rowCount,
        stride: d.elemSize,
        entry: (k) => {
          const owner =
            owners && owners.start + k * 4 + 4 <= blob.length
              ? dv.getUint32(owners.start + k * 4, true)
              : null;
          return {
            label: `row ${fmtInt(k)}`,
            detail:
              (owner === null
                ? 'No ownerlist for this component.'
                : `Entity row ${fmtInt(owner)}.`) +
              (isEntityId ? ` GUID ${guidLeStr(blob, d.dataOffset + k * 16)}.` : ''),
          };
        },
      });
      regions.push(region);
    });

    // Ownerlist entity-index arrays.
    scan.records.forEach(([comp, start, ec]) => {
      if (start + ec * 4 > blob.length) return;
      const compName = scan.compDescs[comp]?.name || `component #${comp}`;
      const region: Region = {
        start,
        end: start + ec * 4,
        label: `ownerlist · ${compName}`,
        detail: `${fmtInt(ec)} × u32 entity-row indices: position P in this array is column row P of ${compName}.`,
      };
      tables.set(region, {
        start,
        end: start + ec * 4,
        count: ec,
        stride: 4,
        entry: (k) => ({
          label: `→ entity row ${fmtInt(dv.getUint32(start + k * 4, true))}`,
        }),
      });
      regions.push(region);
    });

    // The 32-byte ownerlist record table.
    if (scan.recordOffsets.length) {
      const recStart = Math.min(...scan.recordOffsets);
      const recEnd = Math.max(...scan.recordOffsets) + 32;
      const region: Region = {
        start: recStart,
        end: recEnd,
        label: 'ownerlist record table',
        detail:
          '32-byte records: u64 start, u64 end (byte offsets of the entity-index array), u64 component index, u64 entity count. Slots of 0xFFFFFFFF… are free.',
      };
      tables.set(region, {
        start: recStart,
        end: recEnd,
        count: Math.floor((recEnd - recStart) / 32),
        stride: 32,
        entry: (k) => {
          const b = recStart + k * 32;
          const comp = Number(dv.getBigUint64(b + 16, true));
          const compName = comp < scan.compDescs.length ? scan.compDescs[comp]!.name : null;
          return compName
            ? {
                label: `record → ${compName}`,
                detail: `Array at ${hex(Number(dv.getBigUint64(b, true)))}–${hex(Number(dv.getBigUint64(b + 8, true)))}, ${fmtInt(Number(dv.getBigUint64(b + 24, true)))} entities.`,
              }
            : { label: 'free slot / filler' };
        },
      });
      regions.push(region);
    }

    // Component-type directory: the names text, then the descriptor table.
    // names_size spans both (names bytes = desc_table_rel; then entry_count × 48).
    if (namesOff + namesSize <= blob.length && descBase <= namesOff + namesSize) {
      const namesText: Region = {
        start: namesOff,
        end: Math.min(descBase, namesOff + namesSize),
        label: 'component names text',
        detail:
          'Component type names concatenated with no separators (e.g. “core.v0.Level” + “core.v0.EntityId” + …); descriptors carry (offset, length) pairs into this text.',
      };
      const descTable: Region = {
        start: descBase,
        end: Math.min(descBase + entryCount * 48, namesOff + namesSize),
        label: `component descriptor table (${entryCount} × 48 B)`,
        detail:
          'Per component: u64 name offset, u64 name length, u64 hash, u32 element size, u32 flags, u64 row count, u64 data offset.',
      };
      tables.set(descTable, {
        start: descTable.start,
        end: descTable.end,
        count: entryCount,
        stride: 48,
        entry: (k) => {
          const d = scan.compDescs[k];
          if (!d) return { label: `descriptor #${k}` };
          return {
            label: `#${k} ${d.name || '(unnamed)'}`,
            detail: `elem_size ${d.elemSize} B; rows ${fmtInt(d.rowCount)}; data at ${hex(d.dataOffset)}.`,
          };
        },
      });
      regions.push({
        start: namesOff,
        end: namesOff + namesSize,
        label: 'component-type directory',
        detail: `The index of all ${entryCount} component types: names text, then one 48-byte descriptor per type.`,
        kids: [namesText, descTable],
      });
    }

    const filled = fillGaps(
      regions,
      blob.length,
      'heap arrays & string pool',
      'Reached only through absolute byte-pointers stored inside component rows (the “+48” rule) — heap arrays, string data, and per-row variable payloads. Structurally understood but not row-addressable; see FORMAT.md §6.',
    );

    return this.finish(
      id,
      `${name} › NewAge blob`,
      `LSMF ECS world dump: ${entryCount} component types, ${fmtBytes(blob.length)}. A columnar Entity-Component-System snapshot.`,
      parent,
      blob,
      filled,
      tables,
      [],
    );
  }
}

/* ---- Window extraction ---------------------------------------------------- */

function lowerBound(leaves: Leaf[], off: number): number {
  let lo = 0;
  let hi = leaves.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (leaves[mid]!.end <= off) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/** Leaf regions (dense-table entries where available) intersecting [start, end). */
export function windowRegions(leaves: Leaf[], start: number, end: number): WindowRegion[] {
  const out: WindowRegion[] = [];
  for (let li = lowerBound(leaves, start); li < leaves.length; li++) {
    const leaf = leaves[li]!;
    if (leaf.start >= end) break;
    const t = leaf.table;
    if (!t || t.count === 0) {
      out.push({
        start: leaf.start,
        end: leaf.end,
        label: leaf.label,
        detail: leaf.detail,
        group: leaf.group,
        band: 0,
        gap: leaf.gap || undefined,
        stream: leaf.stream,
      });
      continue;
    }
    const from = Math.max(start, t.start);
    let i: number;
    if (t.starts) {
      let lo = 0;
      let hi = t.count - 1;
      while (lo < hi) {
        const mid = (lo + hi + 1) >> 1;
        if (t.starts[mid]! <= from) lo = mid;
        else hi = mid - 1;
      }
      i = lo;
    } else {
      i = Math.min(t.count - 1, Math.floor((from - t.start) / (t.stride ?? 1)));
    }
    for (; i < t.count; i++) {
      const es = t.starts ? t.starts[i]! : t.start + i * (t.stride ?? 1);
      const ee = t.starts ? t.starts[i + 1]! : es + (t.stride ?? 1);
      if (es >= end) break;
      if (ee <= start) continue;
      const e = t.entry(i);
      out.push({
        start: es,
        end: ee,
        label: e.label,
        detail: e.detail,
        group: leaf.group,
        band: i % 2,
      });
    }
  }
  return out;
}
