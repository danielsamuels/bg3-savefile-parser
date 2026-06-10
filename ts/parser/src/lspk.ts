/** LSPK package container: save frames, SaveInfo.json. Mirrors bg3parser/lspk.py. */
import { decompress as zstdDecompress } from 'fzstd';

import { lz4BlockDecompress } from './lz4.js';

const LSPK_FILE_ENTRY = 272; // bytes per file-list entry in LSPK v18

export interface LspkEntry {
  offset: number;
  part: number;
  flags: number;
  sizeOnDisk: number;
  uncompressed: number;
}

/** Decompress one save frame (frames are plain zstd). */
export function decompFrame(raw: Uint8Array): Uint8Array {
  return zstdDecompress(raw);
}

/** Parse the LSPK v18 file list: name -> entry. */
export function lspkFilelist(data: Uint8Array): Map<string, LspkEntry> {
  const dv = new DataView(data.buffer, data.byteOffset, data.byteLength);
  const magic = String.fromCharCode(...data.subarray(0, 4));
  if (magic !== 'LSPK') throw new Error(`not an LSPK package (${magic})`);
  // 64-bit offset read as two u32s — real offsets fit in a JS number
  const flistOff = dv.getUint32(8, true) + dv.getUint32(12, true) * 2 ** 32;
  const numFiles = dv.getUint32(flistOff, true);
  const compSize = dv.getUint32(flistOff + 4, true);
  const comp = data.subarray(flistOff + 8, flistOff + 8 + compSize);
  const raw = lz4BlockDecompress(comp, numFiles * LSPK_FILE_ENTRY);
  const rdv = new DataView(raw.buffer, raw.byteOffset, raw.byteLength);
  const out = new Map<string, LspkEntry>();
  for (let i = 0; i < numFiles; i++) {
    const b = i * LSPK_FILE_ENTRY;
    let end = b;
    while (end < b + 256 && raw[end] !== 0) end++;
    const name = new TextDecoder('latin1').decode(raw.subarray(b, end));
    const offLo = rdv.getUint32(b + 256, true);
    const offHi = rdv.getUint16(b + 260, true);
    out.set(name, {
      offset: offLo + offHi * 2 ** 32,
      part: rdv.getUint8(b + 262),
      flags: rdv.getUint8(b + 263),
      sizeOnDisk: rdv.getUint32(b + 264, true),
      uncompressed: rdv.getUint32(b + 268, true),
    });
  }
  return out;
}

/** Read a .lsv save and return its named frames (still compressed). */
export function extractFrames(data: Uint8Array): Map<string, Uint8Array> {
  const flist = [...lspkFilelist(data).entries()].sort((a, b) => a[1].offset - b[1].offset);
  const out = new Map<string, Uint8Array>();
  for (const [name, e] of flist) {
    const frame = data.subarray(e.offset, e.offset + e.sizeOnDisk);
    // The thumbnail's filename embeds the save name and varies per save.
    out.set(name.toLowerCase().endsWith('.webp') ? 'thumbnail' : name, frame);
  }
  return out;
}

/** Decompress and parse SaveInfo.json. */
export function parseInfoJson(frames: Map<string, Uint8Array>): Record<string, unknown> {
  const raw = frames.get('SaveInfo.json');
  if (!raw) throw new Error('SaveInfo.json missing from package');
  return JSON.parse(new TextDecoder().decode(decompFrame(raw)));
}
