/** LSF / LSOF binary resource format. Mirrors bg3parser/lsf.py. */
import { lz4BlockDecompress, lz4FrameDecompress } from './lz4.js';

export type AttrValue = string | number | boolean | [number, number, number] | Uint8Array;

export interface LsofNode {
  name: string;
  parent: number;
  children: number[];
  attrs: Record<string, AttrValue>;
}

export function decompSection(
  raw: Uint8Array,
  disk: number,
  unc: number,
  flags: number,
  chunked: boolean,
): Uint8Array {
  if (disk === 0 && unc === 0) return new Uint8Array(0);
  if (disk === 0) return raw.subarray(0, unc);
  const m = flags & 0x0f;
  if (m === 0) return raw.subarray(0, disk);
  if (m === 2) {
    return chunked
      ? lz4FrameDecompress(raw.subarray(0, disk), unc)
      : lz4BlockDecompress(raw.subarray(0, disk), unc);
  }
  throw new Error(`unknown compression mode ${m}`);
}

export function parseStringTable(data: Uint8Array): string[][] {
  const dv = new DataView(data.buffer, data.byteOffset, data.byteLength);
  const dec = new TextDecoder();
  const names: string[][] = [];
  let pos = 4;
  const n = dv.getUint32(0, true);
  for (let i = 0; i < n; i++) {
    const chain: string[] = [];
    names.push(chain);
    const ns = dv.getUint16(pos, true);
    pos += 2;
    for (let j = 0; j < ns; j++) {
      const slen = dv.getUint16(pos, true);
      pos += 2;
      chain.push(dec.decode(data.subarray(pos, pos + slen)));
      pos += slen;
    }
  }
  return names;
}

function lkp(names: string[][], nh: number): string {
  const chain = names[nh >>> 16];
  const s = chain?.[nh & 0xffff];
  return s ?? `?${nh.toString(16).padStart(8, '0')}`;
}

const HEX: string[] = Array.from({ length: 256 }, (_, i) => i.toString(16).padStart(2, '0'));

/** Canonical UUID string for a 16-byte fully little-endian BG3 GUID. */
export function guidLeStr(x: Uint8Array, off = 0): string {
  const h = (i: number) => HEX[x[off + i]!]!;
  return (
    `${h(3)}${h(2)}${h(1)}${h(0)}-${h(5)}${h(4)}-${h(7)}${h(6)}-` +
    `${h(9)}${h(8)}-${h(11)}${h(10)}${h(13)}${h(12)}${h(15)}${h(14)}`
  );
}

// LSF attribute type IDs that hold strings:
// String/WString/LSString/LSWString/Path/FixedString
const STRING_TIDS = new Set([20, 21, 22, 23, 29, 30]);

const utf8 = new TextDecoder();

function decodeStr(data: Uint8Array, off: number, len: number): string {
  let end = off + len;
  while (end > off && data[end - 1] === 0) end--;
  return utf8.decode(data.subarray(off, end));
}

function readVal(
  val: Uint8Array,
  dv: DataView,
  off: number,
  tid: number,
  length: number,
): AttrValue | null {
  if (STRING_TIDS.has(tid)) return decodeStr(val, off, length - 1);
  switch (tid) {
    case 2:
      return dv.getUint16(off, true);
    case 3:
      return dv.getInt16(off, true);
    case 4:
      return dv.getInt32(off, true);
    case 5:
      return dv.getUint32(off, true);
    case 6:
      return dv.getFloat32(off, true);
    case 24:
      return Number(dv.getBigUint64(off, true));
    case 26:
    case 32:
      return Number(dv.getBigInt64(off, true));
    case 28: {
      // TranslatedString: 2-byte version + 4-byte string length prefix
      const hlen = dv.getInt32(off + 2, true);
      return decodeStr(val, off + 6, hlen - 1);
    }
    case 31:
      return guidLeStr(val, off);
    case 1:
      return val[off]!;
    case 19:
      return val[off] !== 0;
    case 12:
      return [dv.getFloat32(off, true), dv.getFloat32(off + 4, true), dv.getFloat32(off + 8, true)];
    case 25: // ScratchBuffer (opaque byte blob, e.g. LSMF ECS data)
      return val.subarray(off, off + length);
    default:
      return null;
  }
}

/** Parse an LSOF v7 binary into a flat list of nodes (name, parent, children, attrs). */
export function parseLsof(data: Uint8Array): LsofNode[] {
  const dv = new DataView(data.buffer, data.byteOffset, data.byteLength);
  if (String.fromCharCode(...data.subarray(0, 4)) !== 'LSOF') throw new Error('bad LSOF magic');
  const ver = dv.getUint32(4, true);

  const u = (i: number) => dv.getUint32(16 + i * 4, true);
  const [strUnc, strDisk, , , nodUnc, nodDisk, attUnc, attDisk, valUnc, valDisk] = [
    u(0),
    u(1),
    u(2),
    u(3),
    u(4),
    u(5),
    u(6),
    u(7),
    u(8),
    u(9),
  ] as const;

  const cflags = dv.getUint8(56);
  const mfmt = dv.getUint32(60, true);
  const chunked = ver >= 2;
  // V3 (16-byte) node entries are used ONLY when MetadataFormat == 1.
  const hasKeys = mfmt === 1;

  // A section with sizeOnDisk == 0 is stored uncompressed.
  const strN = strDisk || strUnc;
  const nodN = nodDisk || nodUnc;
  const attN = attDisk || attUnc;
  const valN = valDisk || valUnc;

  let pos = 64;
  const strData = decompSection(data.subarray(pos, pos + strN), strDisk, strUnc, cflags, false);
  pos += strN;
  const nodData = decompSection(data.subarray(pos, pos + nodN), nodDisk, nodUnc, cflags, chunked);
  pos += nodN;
  const attData = decompSection(data.subarray(pos, pos + attN), attDisk, attUnc, cflags, chunked);
  pos += attN;
  const valData = decompSection(data.subarray(pos, pos + valN), valDisk, valUnc, cflags, chunked);

  const names = parseStringTable(strData);
  const nodeSize = hasKeys ? 16 : 12;
  const numNodes = Math.floor(nodData.length / nodeSize);
  const ndv = new DataView(nodData.buffer, nodData.byteOffset, nodData.byteLength);

  const nodes: LsofNode[] = new Array(numNodes);
  for (let i = 0; i < numNodes; i++) {
    const b = i * nodeSize;
    nodes[i] = {
      name: lkp(names, ndv.getUint32(b, true)),
      parent: ndv.getInt32(b + 8, true),
      children: [],
      attrs: {},
    };
  }
  for (let i = 0; i < numNodes; i++) {
    const p = nodes[i]!.parent;
    if (p >= 0 && p < numNodes) nodes[p]!.children.push(i);
  }

  // Attribute entries: name-handle (u32), type-and-length (u32), node (i32).
  const adv = new DataView(attData.buffer, attData.byteOffset, attData.byteLength);
  const vdv = new DataView(valData.buffer, valData.byteOffset, valData.byteLength);
  const nameCache = new Map<number, string>();
  const numAttrs = Math.floor(attData.length / 12);
  let dataOff = 0;
  for (let i = 0; i < numAttrs; i++) {
    const b = i * 12;
    const tl = adv.getUint32(b + 4, true);
    const tid = tl & 0x3f;
    const length = tl >>> 6;
    const ni = adv.getInt32(b + 8, true);
    const val = readVal(valData, vdv, dataOff, tid, length);
    if (val !== null && ni < numNodes) {
      const nh = adv.getUint32(b, true);
      let aname = nameCache.get(nh);
      if (aname === undefined) {
        aname = lkp(names, nh);
        nameCache.set(nh, aname);
      }
      nodes[ni]!.attrs[aname] = val;
    }
    dataOff += length;
  }
  return nodes;
}
