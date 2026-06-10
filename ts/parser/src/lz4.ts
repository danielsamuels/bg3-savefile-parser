/** Raw LZ4 block decompression (no frame header). */

/** Decompress one raw block into dst starting at dstOff; returns bytes written. */
export function lz4BlockInto(src: Uint8Array, dst: Uint8Array, dstOff: number): number {
  let s = 0;
  let d = dstOff;
  while (s < src.length) {
    const token = src[s++]!;
    let litLen = token >> 4;
    if (litLen === 15) {
      let b;
      do {
        b = src[s++]!;
        litLen += b;
      } while (b === 255);
    }
    dst.set(src.subarray(s, s + litLen), d);
    s += litLen;
    d += litLen;
    if (s >= src.length) break; // last sequence ends with literals
    const offset = src[s]! | (src[s + 1]! << 8);
    s += 2;
    let matchLen = (token & 0x0f) + 4;
    if ((token & 0x0f) === 15) {
      let b;
      do {
        b = src[s++]!;
        matchLen += b;
      } while (b === 255);
    }
    let m = d - offset;
    // copy byte-by-byte: matches may overlap their own output
    for (let i = 0; i < matchLen; i++) dst[d++] = dst[m++]!;
  }
  return d - dstOff;
}

/** Decompress a raw LZ4 block to a known output size. */
export function lz4BlockDecompress(src: Uint8Array, dstSize: number): Uint8Array {
  const dst = new Uint8Array(dstSize);
  lz4BlockInto(src, dst, 0);
  return dst;
}

/** Decompress an LZ4 frame (magic 0x184D2204) to a known total output size.
 *  Checksums are skipped; both dependent and independent blocks work because
 *  matches read from the single shared output buffer. */
export function lz4FrameDecompress(src: Uint8Array, dstSize: number): Uint8Array {
  const dv = new DataView(src.buffer, src.byteOffset, src.byteLength);
  if (dv.getUint32(0, true) !== 0x184d2204) throw new Error('not an LZ4 frame');
  const flg = src[4]!;
  let pos = 6; // magic + FLG + BD
  if (flg & 0x08) pos += 8; // content size
  if (flg & 0x01) pos += 4; // dictionary id
  pos += 1; // header checksum
  const blockChecksum = (flg & 0x10) !== 0;
  const dst = new Uint8Array(dstSize);
  let d = 0;
  for (;;) {
    const size = dv.getUint32(pos, true);
    pos += 4;
    if (size === 0) break; // EndMark
    const uncompressed = (size & 0x80000000) !== 0;
    const len = size & 0x7fffffff;
    const block = src.subarray(pos, pos + len);
    pos += len;
    if (blockChecksum) pos += 4;
    if (uncompressed) {
      dst.set(block, d);
      d += len;
    } else {
      d += lz4BlockInto(block, dst, d);
    }
  }
  return dst;
}
