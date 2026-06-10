/// <reference lib="webworker" />
import { DisplayNames, type GamedataJson } from '@bg3save/parser/src/gamedata.ts';
import { decompFrame, extractFrames } from '@bg3save/parser/src/lspk.ts';
import { gatherReport } from '@bg3save/parser/src/model.ts';

let gamedata: DisplayNames | null = null;

/** The save's load-screen WebP, decompressed; null when absent or unreadable. */
function thumbnailBytes(bytes: Uint8Array): ArrayBuffer | null {
  try {
    const frame = extractFrames(bytes).get('thumbnail');
    if (!frame?.length) return null;
    const d = decompFrame(frame);
    return d.buffer.slice(d.byteOffset, d.byteOffset + d.byteLength) as ArrayBuffer;
  } catch {
    return null;
  }
}

self.onmessage = (ev: MessageEvent) => {
  const msg = ev.data as
    | { kind: 'gamedata'; data: GamedataJson }
    | { kind: 'parse'; name: string; buffer: ArrayBuffer };
  if (msg.kind === 'gamedata') {
    gamedata = new DisplayNames(msg.data);
    return;
  }
  try {
    const t0 = performance.now();
    const bytes = new Uint8Array(msg.buffer);
    const report = gatherReport(bytes, gamedata ?? new DisplayNames(), msg.name, {
      quests: true,
    });
    const thumbnail = thumbnailBytes(bytes);
    self.postMessage(
      { kind: 'report', report, ms: Math.round(performance.now() - t0), thumbnail },
      thumbnail ? [thumbnail] : [],
    );
  } catch (err) {
    self.postMessage({ kind: 'error', message: String(err) });
  }
};
