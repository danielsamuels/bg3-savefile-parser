/// <reference lib="webworker" />
import { DisplayNames, type GamedataJson } from '@bg3save/parser/src/gamedata.ts';
import { gatherReport } from '@bg3save/parser/src/model.ts';

let gamedata: DisplayNames | null = null;

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
    const report = gatherReport(new Uint8Array(msg.buffer), gamedata ?? new DisplayNames(), msg.name);
    self.postMessage({ kind: 'report', report, ms: Math.round(performance.now() - t0) });
  } catch (err) {
    self.postMessage({ kind: 'error', message: String(err) });
  }
};
