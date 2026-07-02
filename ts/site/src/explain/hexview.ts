/** Virtualized hex viewer: offset | 16 bytes | ASCII, with region tinting.
 *  Bytes and their annotations are fetched per 4 KB chunk from the worker,
 *  so streams of tens of MB render without holding them on the main thread. */
import type { WindowRegion } from '@bg3save/parser/src/annotate.ts';

export const CHUNK = 4096;
const ROW = 16;
const OVERSCAN = 8;
/** Browsers cap element heights around 16–33 M px; stay safely below. */
const MAX_SPACER = 8_000_000;
const CACHE_MAX = 64;

export interface HexChunk {
  bytes: Uint8Array;
  regions: WindowRegion[]; // sorted by start
}

export interface HexViewOpts {
  size: number;
  fetchChunk: (start: number, end: number) => Promise<HexChunk>;
  /** A region was clicked or reached with the keyboard (null = cleared). */
  onSelect: (r: WindowRegion | null) => void;
}

const HEXD: string[] = Array.from({ length: 256 }, (_, i) => i.toString(16).padStart(2, '0'));

function regionAt(regions: WindowRegion[], off: number): WindowRegion | null {
  let lo = 0;
  let hi = regions.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    const r = regions[mid]!;
    if (r.end <= off) lo = mid + 1;
    else if (r.start > off) hi = mid - 1;
    else return r;
  }
  return null;
}

export class HexView {
  private root: HTMLElement;
  private opts: HexViewOpts;
  private spacer: HTMLElement;
  private rowsEl: HTMLElement;
  private rowH = 20;
  private chunks = new Map<number, HexChunk | 'loading'>();
  private lru: number[] = [];
  private totalRows: number;
  private spacerH: number;
  private selection: { start: number; end: number } | null = null;
  private cursor = 0;
  private raf = 0;
  private destroyed = false;

  constructor(root: HTMLElement, opts: HexViewOpts) {
    this.root = root;
    this.opts = opts;
    this.totalRows = Math.max(1, Math.ceil(opts.size / ROW));
    root.innerHTML =
      '<div class="hx-scroll"><div class="hx-spacer"></div><div class="hx-rows"></div></div>';
    this.spacer = root.querySelector('.hx-spacer') as HTMLElement;
    this.rowsEl = root.querySelector('.hx-rows') as HTMLElement;

    // Measure a probe row so virtual maths matches the real line height.
    this.rowsEl.innerHTML = `<div class="hxr">${this.rowHtml(0, null)}</div>`;
    const probe = this.rowsEl.firstElementChild as HTMLElement;
    this.rowH = Math.max(12, probe.getBoundingClientRect().height || 20);
    this.rowsEl.innerHTML = '';

    this.spacerH = Math.min(this.totalRows * this.rowH, MAX_SPACER);
    this.spacer.style.height = `${this.spacerH}px`;

    const scroller = root.querySelector('.hx-scroll') as HTMLElement;
    scroller.addEventListener('scroll', () => this.schedule());
    this.rowsEl.addEventListener('click', (e) => {
      const cell = (e.target as HTMLElement).closest('[data-o]') as HTMLElement | null;
      if (!cell) return;
      this.setCursor(Number(cell.dataset.o));
    });
    root.addEventListener('keydown', (e) => this.onKey(e));
    this.schedule();
  }

  destroy(): void {
    this.destroyed = true;
    if (this.raf) cancelAnimationFrame(this.raf);
    this.root.innerHTML = '';
  }

  /** Scroll the view so `off` is visible; optionally select its region span. */
  jump(off: number, span?: { start: number; end: number }): void {
    const scroller = this.root.querySelector('.hx-scroll') as HTMLElement;
    const row = Math.floor(off / ROW);
    const frac = this.totalRows <= 1 ? 0 : row / this.totalRows;
    scroller.scrollTop =
      this.spacerH === this.totalRows * this.rowH
        ? Math.max(0, (row - 2) * this.rowH)
        : Math.max(0, frac * (this.spacerH - scroller.clientHeight));
    this.cursor = off;
    if (span) this.selection = span;
    this.schedule();
  }

  private setCursor(off: number): void {
    this.cursor = Math.max(0, Math.min(off, this.opts.size - 1));
    const chunk = this.chunks.get(Math.floor(this.cursor / CHUNK));
    const r = chunk && chunk !== 'loading' ? regionAt(chunk.regions, this.cursor) : null;
    this.selection = r ? { start: r.start, end: r.end } : null;
    this.opts.onSelect(r);
    this.schedule();
  }

  private onKey(e: KeyboardEvent): void {
    const steps: Record<string, number> = {
      ArrowLeft: -1,
      ArrowRight: 1,
      ArrowUp: -ROW,
      ArrowDown: ROW,
      PageUp: -ROW * 24,
      PageDown: ROW * 24,
    };
    let next: number | null = null;
    if (e.key in steps) next = this.cursor + steps[e.key]!;
    else if (e.key === 'Home') next = 0;
    else if (e.key === 'End') next = this.opts.size - 1;
    else if (e.key === 'Escape') {
      this.selection = null;
      this.opts.onSelect(null);
      this.schedule();
      return;
    }
    if (next === null) return;
    e.preventDefault();
    this.setCursor(next);
    this.ensureVisible(this.cursor);
  }

  private ensureVisible(off: number): void {
    const scroller = this.root.querySelector('.hx-scroll') as HTMLElement;
    const view = scroller.clientHeight;
    const rowTop = this.rowTopPx(Math.floor(off / ROW), scroller);
    if (rowTop < scroller.scrollTop || rowTop + this.rowH > scroller.scrollTop + view) {
      this.jump(off);
    }
  }

  private rowTopPx(row: number, scroller: HTMLElement): number {
    if (this.spacerH === this.totalRows * this.rowH) return row * this.rowH;
    const denom = Math.max(1, this.totalRows - Math.floor(scroller.clientHeight / this.rowH));
    return (row / denom) * (this.spacerH - scroller.clientHeight);
  }

  private schedule(): void {
    if (this.raf || this.destroyed) return;
    this.raf = requestAnimationFrame(() => {
      this.raf = 0;
      this.render();
    });
  }

  private chunk(ci: number): HexChunk | null {
    const hit = this.chunks.get(ci);
    if (hit === 'loading') return null;
    if (hit) {
      const at = this.lru.indexOf(ci);
      if (at >= 0) this.lru.splice(at, 1);
      this.lru.push(ci);
      return hit;
    }
    this.chunks.set(ci, 'loading');
    const start = ci * CHUNK;
    this.opts
      .fetchChunk(start, Math.min(start + CHUNK, this.opts.size))
      .then((c) => {
        if (this.destroyed) return;
        this.chunks.set(ci, c);
        this.lru.push(ci);
        while (this.lru.length > CACHE_MAX) this.chunks.delete(this.lru.shift()!);
        this.schedule();
      })
      .catch(() => this.chunks.delete(ci));
    return null;
  }

  private rowHtml(off: number, chunk: HexChunk | null): string {
    const n = Math.min(ROW, this.opts.size - off);
    const offCol = off.toString(16).padStart(8, '0');
    if (!chunk) {
      return `<span class="hxo">${offCol}</span><span class="hxb hx-wait">…</span>`;
    }
    const base = off - Math.floor(off / CHUNK) * CHUNK;
    let bytes = '';
    let ascii = '';
    let r: WindowRegion | null = null;
    for (let i = 0; i < n; i++) {
      const o = off + i;
      if (!r || o >= r.end || o < r.start) r = regionAt(chunk.regions, o);
      const v = chunk.bytes[base + i]!;
      const cls = [
        'b',
        r && !r.gap ? `g${r.group % 8}` : 'gx',
        r?.band ? 'b1' : '',
        r && o === r.start ? 'rs' : '',
        this.selection && o >= this.selection.start && o < this.selection.end ? 'sel' : '',
        o === this.cursor ? 'cur' : '',
      ]
        .filter(Boolean)
        .join(' ');
      bytes += `<span class="${cls}" data-o="${o}">${HEXD[v]}</span>`;
      const ch = v >= 0x20 && v < 0x7f ? String.fromCharCode(v) : null;
      const acls =
        this.selection && o >= this.selection.start && o < this.selection.end ? ' class="sel"' : '';
      ascii += `<span${acls}>${ch === '<' ? '&lt;' : ch === '&' ? '&amp;' : (ch ?? '·')}</span>`;
    }
    return `<span class="hxo">${offCol}</span><span class="hxb">${bytes}</span><span class="hxa">${ascii}</span>`;
  }

  private render(): void {
    if (this.destroyed) return;
    const scroller = this.root.querySelector('.hx-scroll') as HTMLElement;
    const view = scroller.clientHeight || 400;
    const viewRows = Math.ceil(view / this.rowH);
    const maxTop = Math.max(1, this.spacerH - view);
    const frac = Math.min(1, scroller.scrollTop / maxTop);
    const exact = this.spacerH === this.totalRows * this.rowH;
    const rowFloat = exact
      ? scroller.scrollTop / this.rowH
      : frac * Math.max(0, this.totalRows - viewRows);
    const first = Math.max(0, Math.floor(rowFloat) - OVERSCAN);
    const last = Math.min(this.totalRows - 1, Math.floor(rowFloat) + viewRows + OVERSCAN);

    let html = '';
    for (let row = first; row <= last; row++) {
      const off = row * ROW;
      html += `<div class="hxr">${this.rowHtml(off, this.chunk(Math.floor(off / CHUNK)))}</div>`;
    }
    this.rowsEl.style.transform = `translateY(${scroller.scrollTop - (rowFloat - first) * this.rowH}px)`;
    this.rowsEl.innerHTML = html;
  }
}
