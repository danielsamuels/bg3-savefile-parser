/** Local save history: parsed reports stored in IndexedDB, grouped by
 *  campaign, with gold / XP progression charts. Nothing leaves the browser. */
import type { SaveReport } from '@bg3save/parser/src/model.ts';

const GOLD_STATS = new Set(['OBJ_GoldCoin', 'OBJ_GoldPile']);

export interface HistoryRecord {
  id: string;
  gameId: string;
  saveName: string;
  savedAt: string;
  leader: string;
  region: string;
  gold: number;
  partyLevel: number;
  leaderXp: number | null;
  report: SaveReport;
}

let dbPromise: Promise<IDBDatabase> | null = null;

function openDb(): Promise<IDBDatabase> {
  dbPromise ??= new Promise((resolve, reject) => {
    const req = indexedDB.open('bg3save', 1);
    req.onupgradeneeded = () => {
      req.result.createObjectStore('saves', { keyPath: 'id' });
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
  return dbPromise;
}

function tx<T>(mode: IDBTransactionMode, run: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  return openDb().then(
    (db) =>
      new Promise<T>((resolve, reject) => {
        const t = db.transaction('saves', mode);
        const req = run(t.objectStore('saves'));
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => reject(req.error);
      }),
  );
}

export function toRecord(report: SaveReport): HistoryRecord {
  const si = report.save_info;
  let gold = 0;
  let partyLevel = 0;
  let leaderXp: number | null = null;
  for (const c of report.characters) {
    for (const it of c.carried) if (GOLD_STATS.has(it.stats)) gold += it.count;
    const lvl = Number(c.level);
    if (Number.isFinite(lvl) && lvl > partyLevel) partyLevel = lvl;
    if (c.name === `${si.leader} (player)`) leaderXp = c.xp;
  }
  return {
    id: `${si.game_id}|${si.save_id ?? si.save_name}|${si.saved_at}`,
    gameId: si.game_id,
    saveName: si.save_name,
    savedAt: si.saved_at,
    leader: si.leader,
    region: si.level,
    gold,
    partyLevel,
    leaderXp,
    report,
  };
}

export const recordSave = (report: SaveReport): Promise<unknown> =>
  tx('readwrite', (s) => s.put(toRecord(report)));

export const allSaves = (): Promise<HistoryRecord[]> =>
  tx<HistoryRecord[]>('readonly', (s) => s.getAll() as IDBRequest<HistoryRecord[]>);

export const deleteSave = (id: string): Promise<unknown> =>
  tx('readwrite', (s) => s.delete(id));

export const clearSaves = (): Promise<unknown> => tx('readwrite', (s) => s.clear());

/* ---- Rendering ---------------------------------------------------------- */

// Coerces: a malformed stored record must degrade, not kill the whole view.
const esc = (s: unknown): string =>
  String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]!);

/** Minimal sparkline: a gold polyline with end-value labels. */
function sparkline(label: string, points: { x: string; y: number }[]): string {
  if (points.length < 2) return '';
  const w = 220;
  const h = 48;
  const pad = 4;
  const ys = points.map((p) => p.y);
  const lo = Math.min(...ys);
  const hi = Math.max(...ys);
  const span = hi - lo || 1;
  const px = (i: number) => pad + (i * (w - 2 * pad)) / (points.length - 1);
  const py = (y: number) => h - pad - ((y - lo) * (h - 2 * pad)) / span;
  const line = points.map((p, i) => `${px(i).toFixed(1)},${py(p.y).toFixed(1)}`).join(' ');
  const dots = points
    .map(
      (p, i) =>
        `<circle cx="${px(i).toFixed(1)}" cy="${py(p.y).toFixed(1)}" r="2.5"><title>${esc(p.x)}: ${p.y.toLocaleString('en-GB')}</title></circle>`,
    )
    .join('');
  const last = points[points.length - 1]!.y;
  return `<figure class="spark">
    <figcaption>${esc(label)} <span class="count">${last.toLocaleString('en-GB')}</span></figcaption>
    <svg viewBox="0 0 ${w} ${h}" role="img" aria-label="${esc(label)} over ${points.length} saves, latest ${last.toLocaleString('en-GB')}">
      <polyline points="${line}" />${dots}
    </svg>
  </figure>`;
}

export interface HistoryView {
  records: HistoryRecord[];
  campaign: string;
  campaigns: { id: string; label: string }[];
}

// GameID is regenerated on every save, so the leader name is the only stable
// campaign grouping the save offers (two campaigns sharing a leader merge).
export function groupHistory(records: HistoryRecord[], preferredCampaign?: string): HistoryView | null {
  if (!records.length) return null;
  const byCampaign = new Map<string, HistoryRecord[]>();
  for (const r of records) {
    const key = r.leader || '?';
    byCampaign.set(key, [...(byCampaign.get(key) ?? []), r]);
  }
  for (const list of byCampaign.values()) list.sort((a, b) => (a.savedAt < b.savedAt ? -1 : 1));
  const campaigns = [...byCampaign.entries()]
    .map(([id, list]) => ({
      id,
      label: `${list[0]!.leader} (${list.length} save${list.length > 1 ? 's' : ''})`,
      latest: list[list.length - 1]!.savedAt,
    }))
    .sort((a, b) => (a.latest > b.latest ? -1 : 1));
  const campaign =
    preferredCampaign && byCampaign.has(preferredCampaign) ? preferredCampaign : campaigns[0]!.id;
  return { records: byCampaign.get(campaign)!, campaign, campaigns };
}

export function renderHistoryHtml(view: HistoryView): string {
  const { records, campaign, campaigns } = view;
  const select =
    campaigns.length > 1
      ? `<label class="hist-campaign">Campaign
           <select id="hist-campaign">${campaigns
             .map((c) => `<option value="${esc(c.id)}"${c.id === campaign ? ' selected' : ''}>${esc(c.label)}</option>`)
             .join('')}</select></label>`
      : '';
  const charts =
    records.length > 1
      ? `<div class="hist-charts">
           ${sparkline('Party gold', records.map((r) => ({ x: `${r.saveName} (${r.savedAt})`, y: r.gold })))}
           ${sparkline(
             'Leader XP',
             records.filter((r) => r.leaderXp !== null).map((r) => ({ x: `${r.saveName} (${r.savedAt})`, y: r.leaderXp! })),
           )}
         </div>`
      : '';
  const rows = [...records]
    .reverse()
    .map(
      (r) => `<li>
        <button class="hist-open" data-id="${esc(r.id)}">
          <span class="hist-name">${esc(r.saveName)}</span>
          <span class="hist-meta">${esc(r.savedAt.replace(' UTC', ''))} · Lvl ${r.partyLevel} · ${r.gold.toLocaleString('en-GB')} gold</span>
        </button>
        <button class="hist-del" data-id="${esc(r.id)}" aria-label="Remove ${esc(r.saveName)} from history">×</button>
      </li>`,
    )
    .join('');
  return `<details class="fold" open>
    <summary>Campaign history <span class="count">${records.length}</span><span class="fold-note">stored in this browser only</span></summary>
    <div>
      ${select}
      ${charts}
      <ul class="hist-list">${rows}</ul>
      <button class="hist-clear" id="hist-clear">Clear history</button>
    </div>
  </details>`;
}
