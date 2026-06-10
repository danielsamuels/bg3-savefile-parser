import type {
  CharacterReport,
  ItemRef,
  SaveInfo,
  SaveReport,
  SpellRef,
} from '@bg3save/parser/src/model.ts';

import './styles.css';
import {
  allSaves,
  clearSaves,
  deleteSave,
  groupHistory,
  recordSave,
  renderHistoryHtml,
} from './history.ts';
import { renderTextReport } from './textReport.ts';
import { isWatching, startWatching, stopWatching, watchSupported } from './watch.ts';

if ('serviceWorker' in navigator && !import.meta.env.DEV) {
  window.addEventListener('load', () => {
    void navigator.serviceWorker.register('/sw.js');
  });
}

const worker = new Worker(new URL('./worker.ts', import.meta.url), { type: 'module' });
const statusEl = document.querySelector('#status') as HTMLElement;
const reportEl = document.querySelector('#report') as HTMLElement;
const drop = document.querySelector('#drop') as HTMLElement;
const dropLabel = drop.querySelector('.drop-label') as HTMLElement;
const fileInput = drop.querySelector('input') as HTMLInputElement;

// Parsing waits for the name table so a fast drop still gets display names.
const gamedataReady: Promise<void> = fetch('/gamedata.json')
  .then((r) => r.json())
  .then((data) => worker.postMessage({ kind: 'gamedata', data }))
  .catch(() => {
    setStatus('Name data failed to load; internal names will be shown.', true);
  });

function setStatus(text: string, isError = false): void {
  statusEl.textContent = text;
  statusEl.classList.toggle('error', isError);
}

function parse(file: File): void {
  if (!file.name.toLowerCase().endsWith('.lsv')) {
    setStatus(`That doesn't look like a BG3 save: expected a .lsv file, got “${file.name}”.`, true);
    return;
  }
  setStatus(`Reading ${file.name}…`);
  reportEl.innerHTML = '';
  Promise.all([file.arrayBuffer(), gamedataReady]).then(([buffer]) => {
    worker.postMessage({ kind: 'parse', name: file.name, buffer }, [buffer]);
  });
}

/* Drag a file anywhere on the page; the drop zone lights up and takes it. */
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
  if (file) parse(file);
});
fileInput.addEventListener('change', () => {
  if (fileInput.files?.[0]) parse(fileInput.files[0]);
});

const esc = (s: string): string =>
  s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]!);

/* ---- Friendly labels (raw value always kept in the title attribute) ---- */

// 'BattleMaster' → 'Battle Master'
const camelSplit = (s: string): string => s.replace(/([a-z])([A-Z])/g, '$1 $2');

const RACE_LABELS: Record<string, string> = {
  Human: 'Human',
  Githyanki: 'Githyanki',
  HalfOrc: 'Half-Orc',
  Elf_HighElf: 'High Elf',
  Elf_WoodElf: 'Wood Elf',
  Drow_LolthSworn: 'Lolth-Sworn Drow',
  Drow_Seldarine: 'Seldarine Drow',
  HalfElf_High: 'High Half-Elf',
  HalfElf_Wood: 'Wood Half-Elf',
  HalfElf_Drow: 'Drow Half-Elf',
  Halfling_Lightfoot: 'Lightfoot Halfling',
  Halfling_Strongheart: 'Strongheart Halfling',
  Dwarf_Gold: 'Gold Dwarf',
  Dwarf_Shield: 'Shield Dwarf',
  Dwarf_Duergar: 'Duergar',
  Gnome_Rock: 'Rock Gnome',
  Gnome_Forest: 'Forest Gnome',
  Gnome_Deep: 'Deep Gnome',
  Tiefling_Asmodeus: 'Asmodeus Tiefling',
  Tiefling_Mephistopheles: 'Mephistopheles Tiefling',
  Tiefling_Zariel: 'Zariel Tiefling',
};

const SLOT_LABELS: Record<string, string> = {
  Helmet: 'Headwear',
  Breast: 'Armour',
  'Melee Main Weapon': 'Main Hand',
  'Melee Offhand Weapon': 'Off Hand',
  'Ranged Main Weapon': 'Ranged Main',
  'Ranged Offhand Weapon': 'Ranged Off',
  MusicalInstrument: 'Instrument',
  VanityBody: 'Camp Clothes',
  VanityBoots: 'Camp Shoes',
};

const DIFFICULTY_LABELS: Record<string, string> = {
  DifficultyEasy: 'Explorer',
  DifficultyMedium: 'Balanced',
  DifficultyHard: 'Tactician',
  DifficultyHonour: 'Honour Mode',
};

const REGION_LABELS: Record<string, string> = {
  TUT_Avernus_C: 'The Nautiloid',
  WLD_Main_A: 'The Wilderness (Act 1)',
  CRE_Main_A: 'Rosymorn Monastery & Crèche (Act 1)',
  SCL_Main_A: 'Shadow-Cursed Lands (Act 2)',
  BGO_Main_A: 'Wyrm’s Crossing & Rivington (Act 3)',
  CTY_Main_A: 'Baldur’s Gate (Act 3)',
};

const EQUIPMENT_NOTES: Record<string, string> = {
  'no-character-node':
    'No inventory found for this character. Usually a summon, or a companion waiting on another level.',
  'no-items': 'No items attributed; the character may be off the current level.',
};

const SPELLS_NOTES: Record<string, string> = {
  'ambiguous-build':
    'Spell book ambiguous: another party member has an identical class build, and the save does not name spell-book owners.',
  'not-found': 'No spell book found in this save.',
};

const labelled = (raw: string, table: Record<string, string>): string => {
  const friendly = table[raw];
  return friendly && friendly !== raw
    ? `<span title="${esc(raw)}">${esc(friendly)}</span>`
    : esc(raw);
};

const friendlyDifficulty = (joined: string): string =>
  joined
    .split(', ')
    .filter((t) => t !== 'RulesetLarian')
    .map((t) => labelled(t, DIFFICULTY_LABELS))
    .join(', ');

/* ---- Rendering --------------------------------------------------------- */

const itemLabel = (it: ItemRef): string => {
  const name = esc(it.name ?? it.stats);
  const count = it.count > 1 ? ` <span class="count">×${it.count}</span>` : '';
  return `${name}${count}`;
};

const CARRIED_GROUPS: [string, string][] = [
  ['weapon', 'Weapons & magic items'],
  ['armour', 'Armour & accessories'],
  ['consumable', 'Potions & consumables'],
  ['book', 'Books & scrolls'],
  ['misc', 'Everything else'],
];

function renderSaveHead(si: SaveInfo, sourceName: string): string {
  const metaRow = (label: string, value: string): string =>
    value ? `<div><dt>${label}</dt><dd>${value}</dd></div>` : '';
  const mods = si.mods.length
    ? `<details class="save-mods"><summary>${si.mods.length} mod${si.mods.length > 1 ? 's' : ''} installed${
        si.has_unofficial_mods
          ? ' <span class="unofficial">(flagged modded by the game)</span>'
          : ''
      }</summary><ul>${si.mods.map((m) => `<li>${esc(m)}</li>`).join('')}</ul></details>`
    : '';
  return `<header class="save-head" style="--i:0">
    <h2>${esc(si.save_name !== '?' ? si.save_name : sourceName)}</h2>
    <dl class="save-meta">
      ${metaRow('Leader', esc(si.leader))}
      ${metaRow('Region', si.level === '?' ? '' : labelled(si.level, REGION_LABELS))}
      ${metaRow('Difficulty', friendlyDifficulty(si.difficulty))}
      ${metaRow('Saved', si.saved_at === '?' ? '' : esc(si.saved_at))}
      ${metaRow('Game version', si.game_version === '?' ? '' : esc(si.game_version))}
    </dl>
    ${mods}
  </header>`;
}

function renderSpells(spells: SpellRef[]): string {
  const labels = (cat: string): string[] =>
    [...new Set(spells.filter((s) => s.category === cat).map((s) => s.name ?? s.id))].sort();
  const shown = labels('spell');
  const sub = labels('sub-spell');
  const basic = labels('basic-action');
  if (!shown.length && !sub.length && !basic.length) return '';

  const foldNote = [
    sub.length ? `+${sub.length} sub-spells` : '',
    basic.length ? `+${basic.length} basic actions` : '',
  ]
    .filter(Boolean)
    .join(' · ');

  const subList = (title: string, list: string[]): string =>
    list.length
      ? `<details class="sub"><summary>${title} <span class="count">${list.length}</span></summary>
         <ul class="items">${list.map((n) => `<li>${esc(n)}</li>`).join('')}</ul></details>`
      : '';

  return `<details class="fold">
    <summary>Spells &amp; abilities <span class="count">${shown.length}</span>${
      foldNote ? `<span class="fold-note">${foldNote}</span>` : ''
    }</summary>
    <div>
      <ul class="items">${shown.map((n) => `<li>${esc(n)}</li>`).join('')}</ul>
      ${subList('Sub-spells (upcasts & variants)', sub)}
      ${subList('Basic actions', basic)}
    </div>
  </details>`;
}

function renderCharacter(c: CharacterReport, index: number): string {
  const isPlayer = c.name.endsWith(' (player)');
  const displayName = isPlayer ? c.name.slice(0, -' (player)'.length) : c.name;
  const classes = (c.classes as { Main?: string; Sub?: string }[])
    .map((cl) => {
      const main = camelSplit(cl.Main ?? '');
      return cl.Sub ? `${main} / ${camelSplit(cl.Sub)}` : main;
    })
    .join('; ');
  const xp = c.xp !== null ? ` · ${c.xp.toLocaleString('en-GB')} XP` : '';
  const loc = c.location ? ` · <span class="loc" title="subregion">${esc(c.location)}</span>` : '';
  const meta = `${labelled(c.race, RACE_LABELS)} · ${esc(classes)} · Level ${esc(String(c.level))}${xp}${loc}`;

  const head = `<h3 class="char-name">${esc(displayName)}${isPlayer ? '<span class="who">player</span>' : ''}</h3>
    <p class="char-meta">${meta}</p>`;

  if (c.equipment_note && !c.equipped.length && !c.carried.length && !c.undetermined.length) {
    return `<section class="char" style="--i:${index}">${head}
      <p class="char-note">${esc(EQUIPMENT_NOTES[c.equipment_note] ?? c.equipment_note)}</p>
    </section>`;
  }

  const equipped = [...c.equipped].sort((a, b) => {
    const ka = a.slot_rank.concat([0, 0]);
    const kb = b.slot_rank.concat([0, 0]);
    return (
      ka[0]! - kb[0]! || ka[1]! - kb[1]! || (a.name ?? a.stats).localeCompare(b.name ?? b.stats)
    );
  });
  const equippedList = equipped.length
    ? `<h4 class="sect-head">Equipped <span class="count">${equipped.length}</span></h4>
       <ul class="equip">${equipped
         .map(
           (it) =>
             `<li><span class="slot"${it.slot ? ` title="${esc(it.slot)}"` : ''}>${
               it.slot ? esc(SLOT_LABELS[it.slot] ?? it.slot) : '—'
             }</span><span class="item">${itemLabel(it)}</span></li>`,
         )
         .join('')}</ul>`
    : '';

  const undetermined = c.undetermined.length
    ? `<h4 class="sect-head">Worn or carried (undetermined) <span class="count">${c.undetermined.length}</span></h4>
       <ul class="items">${c.undetermined.map((it) => `<li>${itemLabel(it)}</li>`).join('')}</ul>
       <p class="undet-note">The save's equipment signals conflict for these items; they are on the character either way.</p>`
    : '';

  const carriedTotal = c.carried.reduce((n, i) => n + i.count, 0);
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
    return `<h5 class="group-head">${esc(label)}</h5><ul class="items">${lines}</ul>`;
  }).join('');
  const carried = carriedTotal
    ? `<details class="fold"><summary>Carried <span class="count">${carriedTotal}</span></summary><div>${carriedGroups}</div></details>`
    : '';

  const spells = c.spells ? renderSpells(c.spells) : '';
  const spellsNote =
    !spells && c.spells_note
      ? `<p class="char-note">${esc(SPELLS_NOTES[c.spells_note] ?? c.spells_note)}</p>`
      : '';

  return `<section class="char" style="--i:${index}">${head}
    ${equippedList}${undetermined}${carried}${spells}${spellsNote}
  </section>`;
}

function showReport(r: SaveReport, statusText: string): void {
  setStatus(statusText);

  const namesNote = r.names_resolved
    ? ''
    : '<p class="names-note">Display names unavailable; items and spells are shown by their internal names.</p>';

  reportEl.innerHTML =
    renderSaveHead(r.save_info, r.source) +
    namesNote +
    r.characters.map((c, i) => renderCharacter(c, i + 1)).join('');

  document.body.classList.add('has-report');
  dropLabel.innerHTML =
    '<strong>Drop another save</strong> <span class="drop-or">or click to browse</span>';

  const dl = document.querySelector('#download') as HTMLAnchorElement;
  if (dl.href) URL.revokeObjectURL(dl.href);
  dl.href = URL.createObjectURL(new Blob([renderTextReport(r)], { type: 'text/plain' }));
  dl.download = `${r.save_info.save_name !== '?' ? r.save_info.save_name : r.source.replace(/\.lsv$/i, '')}.txt`;
  dl.hidden = false;
}

/* ---- Local history ------------------------------------------------------ */

const historyEl = document.querySelector('#history') as HTMLElement;
let currentCampaign: string | undefined;

async function refreshHistory(): Promise<void> {
  try {
    const view = groupHistory(await allSaves(), currentCampaign);
    historyEl.innerHTML = view ? renderHistoryHtml(view) : '';
  } catch (err) {
    console.error('History render failed:', err);
    historyEl.innerHTML = '';
  }
}

historyEl.addEventListener('click', (e) => {
  const btn = (e.target as HTMLElement).closest('button');
  if (!btn) return;
  if (btn.id === 'hist-clear') {
    void clearSaves().then(refreshHistory);
  } else if (btn.classList.contains('hist-del')) {
    void deleteSave(btn.dataset.id!).then(refreshHistory);
  } else if (btn.classList.contains('hist-open')) {
    void allSaves().then((records) => {
      const rec = records.find((r) => r.id === btn.dataset.id);
      if (rec) {
        showReport(rec.report, `Loaded ${rec.saveName} from history (saved ${rec.savedAt}).`);
        window.scrollTo({ top: 0 });
      }
    });
  }
});

historyEl.addEventListener('change', (e) => {
  const sel = e.target as HTMLSelectElement;
  if (sel.id === 'hist-campaign') {
    currentCampaign = sel.value;
    void refreshHistory();
  }
});

void refreshHistory();

/* ---- Live save watching (Chromium only) --------------------------------- */

const watchBtn = document.querySelector('#watch') as HTMLButtonElement;
if (watchSupported()) {
  watchBtn.hidden = false;
  watchBtn.addEventListener('click', () => {
    if (isWatching()) {
      stopWatching();
      watchBtn.textContent = 'Watch the save folder for quicksaves';
      watchBtn.classList.remove('watching');
      setStatus('Stopped watching.');
      return;
    }
    void startWatching({
      onSave: parse,
      onStatus: (text) => setStatus(text),
    }).then((started) => {
      if (started) {
        watchBtn.textContent = 'Watching for quicksaves (click to stop)';
        watchBtn.classList.add('watching');
      }
    });
  });
}

worker.onmessage = (ev: MessageEvent) => {
  const msg = ev.data as
    | { kind: 'report'; report: SaveReport; ms: number }
    | { kind: 'error'; message: string };
  if (msg.kind === 'error') {
    const detail = msg.message.replace(/^Error:\s*/, '').replace(/\s*\([^)]*\)\s*$/, '');
    setStatus(`Couldn't read that file (${detail}). Is it a BG3 .lsv save?`, true);
    return;
  }
  const r = msg.report;
  const time = msg.ms < 1000 ? `${msg.ms} ms` : `${(msg.ms / 1000).toFixed(1)} s`;
  showReport(r, `Parsed ${r.source} in ${time}. Nothing left your machine.`);
  currentCampaign = r.save_info.leader;
  recordSave(r)
    .then(refreshHistory)
    .catch((err) => console.error('History store failed:', err));
};
