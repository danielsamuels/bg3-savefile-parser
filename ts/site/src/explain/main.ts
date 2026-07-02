/** /anatomy — the byte-level save explainer. Streams and annotations come
 *  from the worker (SaveAnatomy); this file is presentation and navigation. */
import type { Region, StreamMeta, WindowRegion } from '@bg3save/parser/src/annotate.ts';

import '../styles.css';
import './anatomy.css';
import { takeSave } from './handoff.ts';
import { CHUNK, type HexChunk, HexView } from './hexview.ts';

const worker = new Worker(new URL('./worker.ts', import.meta.url), { type: 'module' });

const statusEl = document.querySelector('#status') as HTMLElement;
const explorerEl = document.querySelector('#explorer') as HTMLElement;
const crumbsEl = document.querySelector('#crumbs') as HTMLElement;
const noteEl = document.querySelector('#stream-note') as HTMLElement;
const coverageEl = document.querySelector('#coverage') as HTMLElement;
const hexEl = document.querySelector('#hex') as HTMLElement;
const blocksEl = document.querySelector('#blocks') as HTMLElement;
const outlineEl = document.querySelector('#outline') as HTMLElement;
const childrenEl = document.querySelector('#children') as HTMLElement;
const childrenSect = document.querySelector('#children-sect') as HTMLElement;
const detailEl = document.querySelector('#detail') as HTMLElement;
const drop = document.querySelector('#drop') as HTMLElement;
const fileInput = drop.querySelector('input') as HTMLInputElement;
const sampleBtn = document.querySelector('#sample') as HTMLButtonElement;
const viewBytesBtn = document.querySelector('#view-bytes') as HTMLButtonElement;
const viewBlocksBtn = document.querySelector('#view-blocks') as HTMLButtonElement;

const esc = (s: string): string =>
  s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]!);

const fmtInt = (n: number): string => n.toLocaleString('en-GB');

function fmtBytes(n: number): string {
  if (n >= 1048576) return `${(n / 1048576).toFixed(1)} MB`;
  if (n >= 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${n} B`;
}

function setStatus(text: string, isError = false): void {
  statusEl.textContent = text;
  statusEl.classList.toggle('error', isError);
}

/* ---- Worker plumbing ----------------------------------------------------- */

interface WindowReply {
  kind: 'window';
  id: string;
  start: number;
  req: number;
  buffer: ArrayBuffer;
  regions: WindowRegion[];
}
type WorkerReply =
  | { kind: 'opened'; meta: StreamMeta }
  | { kind: 'stream'; meta: StreamMeta }
  | WindowReply
  | { kind: 'error'; message: string; req?: number };

let reqSeq = 0;
const pendingWindows = new Map<
  number,
  { resolve: (c: HexChunk) => void; reject: (e: Error) => void }
>();
let onMeta: ((meta: StreamMeta) => void) | null = null;

worker.onmessage = (ev: MessageEvent) => {
  const msg = ev.data as WorkerReply;
  if (msg.kind === 'opened' || msg.kind === 'stream') {
    onMeta?.(msg.meta);
    return;
  }
  if (msg.kind === 'window') {
    const p = pendingWindows.get(msg.req);
    pendingWindows.delete(msg.req);
    p?.resolve({ bytes: new Uint8Array(msg.buffer), regions: msg.regions });
    return;
  }
  if (msg.req !== undefined) {
    const p = pendingWindows.get(msg.req);
    pendingWindows.delete(msg.req);
    p?.reject(new Error(msg.message));
    return;
  }
  document.body.classList.remove('busy');
  setStatus(`Couldn't read that (${msg.message.replace(/^Error:\s*/, '')})`, true);
};

function fetchChunk(id: string, start: number, end: number): Promise<HexChunk> {
  return new Promise((resolve, reject) => {
    const req = ++reqSeq;
    pendingWindows.set(req, { resolve, reject });
    worker.postMessage({ kind: 'window', id, start, end, req });
  });
}

/* ---- State --------------------------------------------------------------- */

let saveName = '';
let opened = false;
let currentMeta: StreamMeta | null = null;
let hex: HexView | null = null;
let view: 'bytes' | 'blocks' = window.matchMedia('(max-width: 800px)').matches ? 'blocks' : 'bytes';

const HUE_CLASSES = 8;
const hueClass = (r: { group?: number; kind?: string; gap?: boolean }): string =>
  r.kind === 'gap' || r.gap ? 'gx' : `g${(r.group ?? 0) % HUE_CLASSES}`;

/* ---- Stream titles for breadcrumbs --------------------------------------- */

function crumbsFor(id: string): { id: string; label: string }[] {
  const file = { id: 'file', label: saveName || 'save' };
  if (id === 'file') return [file];
  if (id === 'filelist') return [file, { id, label: 'file list' }];
  if (id.startsWith('frame/')) return [file, { id, label: id.slice('frame/'.length) }];
  if (id.startsWith('lsmf/')) {
    const name = id.slice('lsmf/'.length);
    return [file, { id: `frame/${name}`, label: name }, { id, label: 'NewAge blob' }];
  }
  if (id.startsWith('lsf/')) {
    const rest = id.slice('lsf/'.length);
    const cut = rest.lastIndexOf('/');
    const name = rest.slice(0, cut);
    const sec = rest.slice(cut + 1);
    const secLabel = sec === 'attrs' ? 'attributes' : sec;
    return [file, { id: `frame/${name}`, label: name }, { id, label: secLabel }];
  }
  return [file, { id, label: id }];
}

/* ---- Rendering ------------------------------------------------------------ */

function renderDetail(r: WindowRegion | Region | null): void {
  if (!r) {
    detailEl.innerHTML =
      '<p class="detail-hint">Click a byte, or pick a region from the structure list. Arrow keys walk the bytes.</p>';
    return;
  }
  const len = r.end - r.start;
  const range = `0x${r.start.toString(16)} – 0x${(r.end - 1).toString(16)}`;
  const streamBtn = r.stream
    ? `<p><button type="button" class="linklike" data-stream="${esc(r.stream)}">Open this as a stream →</button></p>`
    : '';
  const gap = 'kind' in r && r.kind === 'gap';
  detailEl.innerHTML = `
    <p class="detail-label"><span class="swatch ${hueClass(r as Region)}"></span>${esc(r.label)}</p>
    <p class="detail-range">${range} · ${fmtInt(len)} byte${len === 1 ? '' : 's'}${gap || ('gap' in r && r.gap) ? ' · unaccounted' : ''}</p>
    ${r.detail ? `<p class="detail-text">${esc(r.detail)}</p>` : ''}
    ${streamBtn}`;
}

function renderCrumbs(id: string): void {
  crumbsEl.innerHTML = crumbsFor(id)
    .map((c, i, all) =>
      i === all.length - 1
        ? `<span aria-current="page">${esc(c.label)}</span>`
        : `<button type="button" data-stream="${esc(c.id)}">${esc(c.label)}</button><span class="crumb-sep">›</span>`,
    )
    .join('');
}

function regionItem(r: Region, size: number): string {
  const share = size ? (r.end - r.start) / size : 0;
  const pct = (100 * share).toFixed(share < 0.001 ? 3 : 1);
  const head = `<span class="swatch ${hueClass(r)}"></span><span class="ol-label">${esc(r.label)}</span>
    <span class="ol-size">${fmtBytes(r.end - r.start)} · ${pct}%</span>`;
  const btn = `<button type="button" class="ol-item${r.kind === 'gap' ? ' is-gap' : ''}" data-start="${r.start}" data-end="${r.end}" data-label="${esc(r.label)}">${head}</button>`;
  if (!r.kids?.length) return `<li>${btn}</li>`;
  return `<li><details><summary>${head}</summary>
    <div class="ol-kid-head">${btn}</div>
    <ol class="outline">${r.kids.map((k) => regionItem(k, size)).join('')}</ol>
  </details></li>`;
}

function renderOutline(meta: StreamMeta): void {
  outlineEl.innerHTML = meta.regions.map((r) => regionItem(r, meta.size)).join('');
}

function renderChildren(meta: StreamMeta): void {
  childrenSect.hidden = !meta.children.length;
  childrenEl.innerHTML = meta.children
    .map(
      (c) => `<li><button type="button" class="child-item" data-stream="${esc(c.id)}">
        <span class="child-title">${esc(c.title)}</span>
        ${c.size ? `<span class="child-size">${fmtBytes(c.size)}</span>` : ''}
        <span class="child-note">${esc(c.note)}</span>
      </button></li>`,
    )
    .join('');
}

function blockItem(r: Region, size: number): string {
  const share = size ? (r.end - r.start) / size : 0;
  const pct = (100 * share).toFixed(share < 0.001 ? 3 : 1);
  const kids = r.kids?.length
    ? `<div class="blk-kids">${r.kids.map((k) => blockItem(k, size)).join('')}</div>`
    : '';
  return `<details class="blk ${hueClass(r)}">
    <summary>
      <span class="blk-label">${esc(r.label)}</span>
      <span class="blk-size">${fmtBytes(r.end - r.start)} · ${pct}%</span>
      <span class="blk-bar" style="--w:${Math.max(1.5, 100 * share)}%"></span>
    </summary>
    <div class="blk-body">
      <p class="detail-range">0x${r.start.toString(16)} – 0x${(r.end - 1).toString(16)}${r.kind === 'gap' ? ' · unaccounted' : ''}</p>
      ${r.detail ? `<p>${esc(r.detail)}</p>` : ''}
      <p class="blk-actions">
        <button type="button" class="linklike" data-start="${r.start}" data-end="${r.end}">View these bytes</button>
        ${r.stream ? `<button type="button" class="linklike" data-stream="${esc(r.stream)}">Open as a stream →</button>` : ''}
      </p>
      ${kids}
    </div>
  </details>`;
}

function renderBlocks(meta: StreamMeta): void {
  blocksEl.innerHTML = meta.regions.map((r) => blockItem(r, meta.size)).join('');
}

function applyView(): void {
  viewBytesBtn.setAttribute('aria-pressed', String(view === 'bytes'));
  viewBlocksBtn.setAttribute('aria-pressed', String(view === 'blocks'));
  hexEl.parentElement?.classList.toggle('view-blocks', view === 'blocks');
  hexEl.hidden = view !== 'bytes';
  blocksEl.hidden = view !== 'blocks';
}

function showStream(meta: StreamMeta): void {
  currentMeta = meta;
  explorerEl.hidden = false;
  renderCrumbs(meta.id);
  noteEl.textContent = meta.note;
  const pct = meta.size ? (100 * meta.covered) / meta.size : 100;
  coverageEl.innerHTML = `<span class="cov-bar" role="img" aria-label="Coverage ${pct.toFixed(1)}%"><span style="width:${pct.toFixed(2)}%"></span></span>
    <span class="cov-text">${pct >= 99.95 && meta.covered !== meta.size ? '>99.9' : pct.toFixed(pct === 100 ? 0 : 1)}% of ${fmtBytes(meta.size)} annotated</span>`;
  renderOutline(meta);
  renderChildren(meta);
  renderBlocks(meta);
  renderDetail(null);
  hex?.destroy();
  hex = new HexView(hexEl, {
    size: meta.size,
    fetchChunk: (start, end) => fetchChunk(meta.id, start, end),
    onSelect: (r) => renderDetail(r),
  });
  applyView();
  document.body.classList.remove('busy');
}

function openStream(id: string, push = true): void {
  if (!opened) return;
  document.body.classList.add('busy');
  setStatus('');
  onMeta = (meta) => {
    if (meta.id !== id) return;
    showStream(meta);
    if (push) history.pushState({ stream: id }, '', `#s=${encodeURIComponent(id)}`);
  };
  worker.postMessage({ kind: 'stream', id });
}

/* ---- Opening a save ------------------------------------------------------- */

function openSave(name: string, buffer: ArrayBuffer): void {
  saveName = name;
  setStatus(`Reading ${name}…`);
  document.body.classList.add('busy');
  onMeta = (meta) => {
    opened = true;
    setStatus(`${name}: ${fmtBytes(meta.size)}, parsed locally. Nothing left your machine.`);
    showStream(meta);
    history.replaceState({ stream: 'file' }, '', '#s=file');
  };
  worker.postMessage({ kind: 'open', buffer }, [buffer]);
}

function openFile(file: File): void {
  if (!file.name.toLowerCase().endsWith('.lsv')) {
    setStatus(`That doesn't look like a BG3 save: expected a .lsv file, got “${file.name}”.`, true);
    return;
  }
  file
    .arrayBuffer()
    .then((buffer) => openSave(file.name, buffer))
    .catch(() => setStatus('Could not read that file.', true));
}

window.addEventListener('dragover', (e) => {
  e.preventDefault();
  drop.classList.add('over');
});
window.addEventListener('dragleave', (e) => {
  if (e.relatedTarget === null) drop.classList.remove('over');
});
window.addEventListener('drop', (e) => {
  e.preventDefault();
  drop.classList.remove('over');
  const file = e.dataTransfer?.files[0];
  if (file) openFile(file);
});
fileInput.addEventListener('change', () => {
  if (fileInput.files?.[0]) openFile(fileInput.files[0]);
});

sampleBtn.addEventListener('click', () => {
  sampleBtn.disabled = true;
  setStatus('Fetching the sample save…');
  fetch('/sample.lsv')
    .then((r) => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.arrayBuffer();
    })
    .then((buf) => openSave('sample: tutorial autosave', buf))
    .catch(() => setStatus('Could not fetch the sample save. Check your connection.', true))
    .finally(() => {
      sampleBtn.disabled = false;
    });
});

/* ---- Delegated clicks: crumbs, outline, children, blocks, detail ---------- */

document.addEventListener('click', (e) => {
  const el = (e.target as HTMLElement).closest('button') as HTMLButtonElement | null;
  if (!el) return;
  if (el.dataset.stream) {
    openStream(el.dataset.stream);
    return;
  }
  if (el.dataset.start !== undefined) {
    const start = Number(el.dataset.start);
    const end = Number(el.dataset.end);
    view = 'bytes';
    applyView();
    hex?.jump(start, { start, end });
    renderDetail({ start, end, label: el.dataset.label ?? '', group: 0 } as WindowRegion);
    // fetch the real region annotation for the detail card once the chunk lands
    fetchChunk(currentMeta!.id, start, Math.min(start + CHUNK, currentMeta!.size)).then((c) => {
      const r = c.regions.find((x) => x.start <= start && x.end > start);
      if (r) renderDetail(r);
    });
  }
});

viewBytesBtn.addEventListener('click', () => {
  view = 'bytes';
  applyView();
});
viewBlocksBtn.addEventListener('click', () => {
  view = 'blocks';
  applyView();
});

window.addEventListener('popstate', () => {
  const m = location.hash.match(/^#s=(.+)$/);
  if (m && opened) openStream(decodeURIComponent(m[1]!), false);
});

/* ---- Handoff from the report page ----------------------------------------- */

if (location.hash === '#last') {
  history.replaceState(null, '', location.pathname);
  takeSave().then((rec) => {
    if (rec) openSave(rec.name, rec.bytes);
    else setStatus('No handed-over save found — drop a .lsv here, or load the sample.');
  });
}
