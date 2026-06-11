/// <reference lib="webworker" />
import { DisplayNames, type GamedataJson } from '@bg3save/parser/src/gamedata.ts';
import { parseLsof } from '@bg3save/parser/src/lsf.ts';
import { parseLsmfPortraits } from '@bg3save/parser/src/lsmf.ts';
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

/** Embedded character portraits, keyed by created-character name. */
function portraitBytes(bytes: Uint8Array): {
  portraits: { name: string; buf: ArrayBuffer }[];
  guardian: ArrayBuffer | null;
} {
  try {
    const globals = extractFrames(bytes).get('Globals.lsf');
    if (!globals) return { portraits: [], guardian: null };
    const nodes = parseLsof(decompFrame(globals));
    const blobNode = nodes.find((nd) => nd.name === 'NewAge' && nd.parent === -1);
    const blob = blobNode?.attrs.NewAge;
    if (!(blob instanceof Uint8Array)) return { portraits: [], guardian: null };
    const { portraits, guardian } = parseLsmfPortraits(blob);
    return {
      portraits: portraits.map((pt) => ({
        name: pt.name,
        buf: pt.webp.buffer.slice(
          pt.webp.byteOffset,
          pt.webp.byteOffset + pt.webp.byteLength,
        ) as ArrayBuffer,
      })),
      guardian: guardian
        ? (guardian.buffer.slice(
            guardian.byteOffset,
            guardian.byteOffset + guardian.byteLength,
          ) as ArrayBuffer)
        : null,
    };
  } catch {
    return { portraits: [], guardian: null };
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
    const { portraits, guardian } = portraitBytes(bytes);
    const transfers = [
      ...(thumbnail ? [thumbnail] : []),
      ...portraits.map((pt) => pt.buf),
      ...(guardian ? [guardian] : []),
    ];
    self.postMessage(
      {
        kind: 'report',
        report,
        ms: Math.round(performance.now() - t0),
        thumbnail,
        portraits,
        guardian,
      },
      transfers,
    );
  } catch (err) {
    self.postMessage({ kind: 'error', message: String(err) });
  }
};
