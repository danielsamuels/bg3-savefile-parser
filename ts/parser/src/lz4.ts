/** Raw LZ4 block decompression (no frame header), to a known output size. */
export function lz4BlockDecompress(src: Uint8Array, dstSize: number): Uint8Array {
  const dst = new Uint8Array(dstSize);
  let s = 0;
  let d = 0;
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
    if (s >= src.length) break; // last block ends with literals
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
  return dst;
}
