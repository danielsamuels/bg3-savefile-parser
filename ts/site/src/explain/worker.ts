/// <reference lib="webworker" />
import { SaveAnatomy } from '@bg3save/parser/src/annotate.ts';

let anatomy: SaveAnatomy | null = null;

export type WorkerRequest =
  | { kind: 'open'; buffer: ArrayBuffer }
  | { kind: 'stream'; id: string }
  | { kind: 'window'; id: string; start: number; end: number; req: number };

self.onmessage = (ev: MessageEvent) => {
  const msg = ev.data as WorkerRequest;
  try {
    if (msg.kind === 'open') {
      anatomy = new SaveAnatomy(new Uint8Array(msg.buffer));
      self.postMessage({ kind: 'opened', meta: anatomy.meta('file') });
      return;
    }
    if (!anatomy) throw new Error('no save open');
    if (msg.kind === 'stream') {
      self.postMessage({ kind: 'stream', meta: anatomy.meta(msg.id) });
      return;
    }
    const { bytes, regions } = anatomy.window(msg.id, msg.start, msg.end);
    const buffer = bytes.buffer as ArrayBuffer;
    self.postMessage(
      { kind: 'window', id: msg.id, start: msg.start, req: msg.req, buffer, regions },
      [buffer],
    );
  } catch (err) {
    const req = msg.kind === 'window' ? msg.req : undefined;
    self.postMessage({ kind: 'error', message: String(err), req });
  }
};
