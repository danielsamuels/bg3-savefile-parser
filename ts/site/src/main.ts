import type { CharacterReport, ItemRef, SaveReport } from '@bg3save/parser/src/model.ts';

const worker = new Worker(new URL('./worker.ts', import.meta.url), { type: 'module' });
const statusEl = document.querySelector('#status') as HTMLElement;
const reportEl = document.querySelector('#report') as HTMLElement;
const drop = document.querySelector('#drop') as HTMLElement;
const fileInput = drop.querySelector('input') as HTMLInputElement;

fetch('/gamedata.json')
  .then((r) => r.json())
  .then((data) => worker.postMessage({ kind: 'gamedata', data }))
  .catch(() => {
    statusEl.textContent = 'Name data failed to load — internal names will be shown.';
  });

function parse(file: File): void {
  statusEl.textContent = `Parsing ${file.name}…`;
  reportEl.innerHTML = '';
  file.arrayBuffer().then((buffer) => {
    worker.postMessage({ kind: 'parse', name: file.name, buffer }, [buffer]);
  });
}

drop.addEventListener('dragover', (e) => {
  e.preventDefault();
  drop.classList.add('over');
});
drop.addEventListener('dragleave', () => drop.classList.remove('over'));
drop.addEventListener('drop', (e) => {
  e.preventDefault();
  drop.classList.remove('over');
  const file = e.dataTransfer?.files[0];
  if (file) parse(file);
});
fileInput.addEventListener('change', () => {
  if (fileInput.files?.[0]) parse(fileInput.files[0]);
});

const esc = (s: string): string =>
  s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]!);

const itemLabel = (it: ItemRef): string => {
  const name = esc(it.name ?? it.stats);
  const slot = it.slot ? ` <span class="slot">[${esc(it.slot)}]</span>` : '';
  const count = it.count > 1 ? ` <span class="count">×${it.count}</span>` : '';
  return `${name}${count}${slot}`;
};

const CARRIED_GROUPS: [string, string][] = [
  ['weapon', 'Weapons & magic items'],
  ['armour', 'Armour & accessories'],
  ['consumable', 'Potions & consumables'],
  ['book', 'Books & scrolls'],
  ['misc', 'Everything else'],
];

function renderCharacter(c: CharacterReport): string {
  const classes = (c.classes as { Main?: string; Sub?: string }[])
    .map((cl) => (cl.Sub ? `${cl.Main} / ${cl.Sub}` : (cl.Main ?? '')))
    .join('; ');
  const equipped = [...c.equipped].sort((a, b) => {
    const ka = a.slot_rank.concat([0, 0]);
    const kb = b.slot_rank.concat([0, 0]);
    return ka[0]! - kb[0]! || ka[1]! - kb[1]! || (a.name ?? a.stats).localeCompare(b.name ?? b.stats);
  });
  const carriedGroups = CARRIED_GROUPS.map(([key, label]) => {
    const counts = new Map<string, number>();
    for (const it of c.carried.filter((i) => i.category === key)) {
      const name = it.name ?? it.stats;
      counts.set(name, (counts.get(name) ?? 0) + it.count);
    }
    if (!counts.size) return '';
    const lines = [...counts.entries()]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([n, ct]) => `<li>${esc(n)}${ct > 1 ? ` <span class="count">×${ct}</span>` : ''}</li>`)
      .join('');
    return `<h4 class="slot">${esc(label)}</h4><ul>${lines}</ul>`;
  }).join('');
  const spells =
    c.spells
      ?.filter((s) => s.category === 'spell')
      .map((s) => `<li>${esc(s.name ?? s.id)}</li>`)
      .join('') ?? '';
  return `<section class="char">
    <h2>${esc(c.name)}</h2>
    <div class="meta">${esc(c.race)} · ${esc(classes)} · Level ${esc(String(c.level))}${
      c.xp !== null ? ` · ${c.xp} XP` : ''
    }</div>
    <h3>Equipped (${equipped.length})</h3>
    <ul>${equipped.map((it) => `<li>${itemLabel(it)}</li>`).join('')}</ul>
    <details><summary>Carried (${c.carried.reduce((n, i) => n + i.count, 0)})</summary>${carriedGroups}</details>
    ${spells ? `<details><summary>Spells & abilities (${c.spells!.filter((s) => s.category === 'spell').length})</summary><ul>${spells}</ul></details>` : ''}
  </section>`;
}

worker.onmessage = (ev: MessageEvent) => {
  const msg = ev.data as
    | { kind: 'report'; report: SaveReport; ms: number }
    | { kind: 'error'; message: string };
  if (msg.kind === 'error') {
    statusEl.textContent = `Could not parse that file: ${msg.message}`;
    return;
  }
  statusEl.textContent = `Parsed ${msg.report.source} in ${msg.ms}ms.`;
  reportEl.innerHTML = msg.report.characters.map(renderCharacter).join('');
};
