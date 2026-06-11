import type {
  CharacterReport,
  ItemRef,
  QuestRef,
  QuestsReport,
  SaveInfo,
  SaveReport,
  SpellRef,
} from '@bg3save/parser/src/model.ts';
import type { StoryState } from '@bg3save/parser/src/osiris.ts';

import './styles.css';
import { type EffectsTable, effectLines } from './effects.ts';
import {
  allSaves,
  clearSaves,
  deleteSave,
  GOLD_STATS,
  groupHistory,
  REPORT_VERSION,
  recordSave,
  renderHistoryHtml,
} from './history.ts';
import {
  buildItemIndex,
  type ItemPlace,
  MIN_QUERY,
  renderSearchResults,
  renderSearchSection,
  searchItems,
} from './search.ts';
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

// Item tooltip text; reports render fine without it, so failures are silent.
let effectsTable: EffectsTable = {};
const effectsReady: Promise<void> = fetch('/effects.json')
  .then((r) => r.json())
  .then((data) => {
    effectsTable = data as EffectsTable;
  })
  .catch(() => {});

const effectsFor = (stats: string): string[] => effectLines(effectsTable, stats);

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
  (document.activeElement as HTMLElement | null)?.blur?.();
  document.body.classList.add('busy');
  reportEl.innerHTML = '';
  Promise.all([file.arrayBuffer(), gamedataReady, effectsReady]).then(([buffer]) => {
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

const itemName = (name: string, stats: string): string => {
  const lines = effectsFor(stats);
  return lines.length
    ? `<span class="has-fx" title="${esc(lines.join('\n'))}">${esc(name)}</span>`
    : esc(name);
};

const itemLabel = (it: ItemRef): string => {
  const count = it.count > 1 ? ` <span class="count">×${it.count}</span>` : '';
  return `${itemName(it.name ?? it.stats, it.stats)}${count}`;
};

const CARRIED_GROUPS: [string, string][] = [
  ['weapon', 'Weapons & magic items'],
  ['armour', 'Armour & accessories'],
  ['consumable', 'Potions & consumables'],
  ['book', 'Books & scrolls'],
  ['misc', 'Everything else'],
];

/** Items grouped by coarse category, stacks collapsed to one ×N line. */
function itemGroups(items: ItemRef[]): string {
  return CARRIED_GROUPS.map(([key, label]) => {
    const counts = new Map<string, number>();
    const statsOf = new Map<string, string>();
    // Gold is money, not luggage; the fold summary already totals it.
    for (const it of items.filter((i) => i.category === key && !GOLD_STATS.has(i.stats))) {
      const name = it.name ?? it.stats;
      counts.set(name, (counts.get(name) ?? 0) + it.count);
      if (!statsOf.has(name)) statsOf.set(name, it.stats);
    }
    if (!counts.size) return '';
    const lines = [...counts.entries()]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(
        ([n, ct]) =>
          `<li>${itemName(n, statsOf.get(n) ?? '')}${ct > 1 ? ` <span class="count">×${ct}</span>` : ''}</li>`,
      )
      .join('');
    return `<h5 class="group-head">${esc(label)}</h5><ul class="items">${lines}</ul>`;
  }).join('');
}

const SKIP_RESOURCES = new Set(['Action', 'Bonus Action', 'Reaction', 'Movement Speed']);

/** "2026-06-11 15:07:39 UTC" -> the user's local time; original on parse failure. */
function localTime(savedAt: string): string {
  const m = savedAt.match(/^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2}) UTC$/);
  if (!m) return savedAt;
  const d = new Date(`${m[1]}T${m[2]}Z`);
  return Number.isNaN(d.getTime())
    ? savedAt
    : d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

function renderSaveHead(si: SaveInfo, sourceName: string, thumbUrl: string | null): string {
  const metaRow = (label: string, value: string): string =>
    value ? `<div><dt>${label}</dt><dd>${value}</dd></div>` : '';
  const mods = si.mods.length
    ? `<details class="save-mods"><summary>${si.mods.length} mod${si.mods.length > 1 ? 's' : ''} installed${
        si.has_unofficial_mods
          ? ' <span class="unofficial">(flagged modded by the game)</span>'
          : ''
      }</summary><ul>${si.mods.map((m) => `<li>${esc(m)}</li>`).join('')}</ul></details>`
    : '';
  const thumb = thumbUrl
    ? `<img class="save-thumb" src="${esc(thumbUrl)}" alt="Load-screen thumbnail of this save" />`
    : '';
  return `<header class="save-head${thumb ? ' has-thumb' : ''}" style="--i:0">
    <div class="save-head-text">
      <h2>${esc(si.save_name !== '?' ? si.save_name : sourceName)}</h2>
      <dl class="save-meta">
        ${metaRow('Leader', esc(si.leader))}
        ${metaRow('Save', si.save_id === null ? '' : `#${si.save_id}`)}
        ${metaRow('Region', si.level === '?' ? '' : labelled(si.level, REGION_LABELS))}
        ${metaRow('Difficulty', friendlyDifficulty(si.difficulty))}
        ${metaRow('Supplies', si.camp_supplies ? String(si.camp_supplies) : '')}
        ${metaRow('Recipes', si.recipes?.length ? `${si.recipes.length} known` : '')}
        ${metaRow('Saved', si.saved_at === '?' ? '' : esc(localTime(si.saved_at)))}
        ${metaRow('Game version', si.game_version === '?' ? '' : esc(si.game_version))}
      </dl>
      ${mods}
    </div>
    ${thumb}
  </header>`;
}

function renderSpells(spells: SpellRef[]): string {
  const labels = (cat: string): string[] =>
    [...new Set(spells.filter((s) => s.category === cat).map((s) => s.name ?? s.id))].sort();
  const shown = labels('spell');
  const sub = labels('sub-spell');
  const basic = labels('basic-action');
  if (!shown.length && !sub.length && !basic.length) return '';

  // A display name is prepared when any of its refs (upcast variants share
  // a name) is prepared; null preparation data hides the markers entirely.
  const preparedNames = new Set(
    spells.filter((s) => s.prepared && s.category === 'spell').map((s) => s.name ?? s.id),
  );
  const hasPrepData = spells.some((s) => s.prepared !== null);
  const preparedShown = shown.filter((n) => preparedNames.has(n));

  const foldNote = [
    hasPrepData && preparedShown.length ? `${preparedShown.length} prepared` : '',
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
      <ul class="items">${shown
        .map(
          (n) =>
            `<li${preparedNames.has(n) ? ' class="prep" title="prepared"' : ''}>${esc(n)}</li>`,
        )
        .join('')}</ul>
      ${subList('Sub-spells (upcasts & variants)', sub)}
      ${subList('Basic actions', basic)}
    </div>
  </details>`;
}

/** Object URLs for the save-embedded character portraits, by created name. */
let portraitUrls = new Map<string, string>();
let guardianUrl: string | null = null;

function setPortraits(
  portraits: { name: string; buf: ArrayBuffer }[],
  guardian: ArrayBuffer | null,
): void {
  for (const url of portraitUrls.values()) URL.revokeObjectURL(url);
  if (guardianUrl) URL.revokeObjectURL(guardianUrl);
  portraitUrls = new Map();
  for (const pt of portraits) {
    if (!pt.name) continue;
    portraitUrls.set(
      pt.name.toLowerCase(),
      URL.createObjectURL(new Blob([pt.buf], { type: 'image/webp' })),
    );
  }
  guardianUrl = guardian ? URL.createObjectURL(new Blob([guardian], { type: 'image/webp' })) : null;
}

function portraitFor(charName: string): string | null {
  const base = charName.replace(/ \((player|hireling)\)$/, '').toLowerCase();
  return portraitUrls.get(base) ?? null;
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
  const loc =
    c.location && !c.at_camp ? ` · <span title="subregion">${esc(c.location)}</span>` : '';
  const hp = c.hp ? ` · ${c.hp.current}/${c.hp.max} HP${c.hp.temp ? ` (+${c.hp.temp})` : ''}` : '';
  const conc = c.concentration
    ? ` · <span class="conc">concentrating on ${esc(c.concentration.name ?? c.concentration.id)}</span>`
    : '';
  const meta = `${labelled(c.race, RACE_LABELS)} · ${esc(classes)} · Level ${esc(String(c.level))}${xp}${hp}${loc}${conc}`;
  const stats = c.abilities
    ? `<p class="char-stats">${(['str', 'dex', 'con', 'int', 'wis', 'cha'] as const)
        .map((k) => `<span><b>${k.toUpperCase()}</b> ${c.abilities![k]}</span>`)
        .join('')}</p>`
    : '';

  const resourceGroups = new Map<string, NonNullable<CharacterReport['resources']>>();
  for (const r of c.resources ?? []) {
    if (!r.name || SKIP_RESOURCES.has(r.name) || r.name.includes('_') || r.max <= 0) continue;
    if (!resourceGroups.has(r.name)) resourceGroups.set(r.name, []);
    resourceGroups.get(r.name)!.push(r);
  }
  const resources = resourceGroups.size
    ? `<p class="char-stats char-resources">${[...resourceGroups]
        .map(([name, rs]) => {
          rs.sort((a, b) => a.level - b.level);
          const bits = rs
            .map(
              (r) =>
                `${r.level ? `L${r.level} ` : ''}<span class="${r.current < r.max ? 'spent' : ''}">${r.current}/${r.max}</span>`,
            )
            .join(' · ');
          return `<span><b>${esc(name)}</b> ${bits}</span>`;
        })
        .join('')}</p>`
    : '';

  const feats = c.feats?.length
    ? `<p class="char-stats char-feats"><span><b>Feats</b> ${c.feats
        .map((f) => {
          const counts = new Map<string, number>();
          for (const a of f.picks) counts.set(a, (counts.get(a) ?? 0) + 1);
          const picks = [...counts].map(([a, n]) => `+${n} ${a}`).join(', ');
          return esc(`${f.name ?? f.guid} (L${f.level}${picks ? `: ${picks}` : ''})`);
        })
        .join(' · ')}</span></p>`
    : '';

  const tag = isPlayer ? 'player' : c.at_camp ? 'at camp' : '';
  const portraitUrl = portraitFor(c.name);
  const portrait = portraitUrl
    ? `<img class="char-portrait" src="${esc(portraitUrl)}" alt="" width="72" height="72" loading="lazy">`
    : '';
  const head = `<div class="char-head${portrait ? ' has-portrait' : ''}">${portrait}<div>
    <h3 class="char-name">${esc(displayName)}${tag ? `<span class="who">${tag}</span>` : ''}</h3>
    <p class="char-meta">${meta}</p></div></div>${stats}${resources}${feats}`;

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

  // Gold stacks are money, not luggage: "14 items · 2,102 gold", not "2,116 items".
  const carriedGold = c.carried
    .filter((i) => GOLD_STATS.has(i.stats))
    .reduce((n, i) => n + i.count, 0);
  const carriedItems = c.carried
    .filter((i) => !GOLD_STATS.has(i.stats))
    .reduce((n, i) => n + i.count, 0);
  const carriedGroups = itemGroups(c.carried);
  const goldNote = carriedGold
    ? `<span class="fold-note">${carriedGold.toLocaleString('en-GB')} gold</span>`
    : '';
  const carried =
    carriedItems || carriedGold
      ? `<details class="fold"><summary>Carried <span class="count">${carriedItems}</span>${goldNote}</summary><div>${carriedGroups}</div></details>`
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

/** Fallback when no journal titles resolved at all: drop the short all-caps
 *  prefixes from the id and split camel case. */
function questLabel(id: string): string {
  const pretty = id
    .split('_')
    .filter((s) => !(s.length <= 6 && s === s.toUpperCase()))
    .map(camelSplit)
    .join(' ');
  return pretty || id;
}

/** The in-game journal hides quests with no title (engine bookkeeping like
 *  ORI_Avatar_*); mirror that. Named sub-quests of hidden parents are
 *  promoted to top level, and duplicate titles collapse to one entry. */
interface QuestView {
  tree: Map<string, Set<string>>;
  objectives: Map<string, string>;
}

function questTree(quests: QuestRef[]): QuestView {
  const anyNamed = quests.some((q) => q.name !== null);
  const titleOf = (q: QuestRef): string | null => q.name ?? (anyNamed ? null : questLabel(q.id));
  const named = new Map<string, string>();
  const objectives = new Map<string, string>();
  for (const q of quests) {
    const t = titleOf(q);
    if (t !== null) {
      named.set(q.id, t);
      if (q.objective && !objectives.has(t)) objectives.set(t, q.objective);
    }
  }
  const tree = new Map<string, Set<string>>();
  for (const q of quests) {
    const title = named.get(q.id);
    if (title === undefined) continue;
    const [parentId] = q.id.split('_SUB_') as [string, string?];
    const parentTitle = q.id !== parentId ? named.get(parentId) : undefined;
    if (parentTitle !== undefined && parentTitle !== title) {
      tree.set(parentTitle, (tree.get(parentTitle) ?? new Set()).add(title));
    } else if (!tree.has(title)) {
      tree.set(title, new Set());
    }
  }
  // A title shown as a sub-quest somewhere shouldn't also float at top level.
  const subTitles = new Set([...tree.values()].flatMap((s) => [...s]));
  for (const [title, subs] of tree) {
    if (!subs.size && subTitles.has(title)) tree.delete(title);
  }
  return { tree, objectives };
}

function questList(view: QuestView): string {
  const { tree, objectives } = view;
  const obj = (title: string): string => {
    const text = objectives.get(title);
    return text ? `<div class="quest-obj">${esc(text)}</div>` : '';
  };
  const rows = [...tree.entries()]
    .map(
      ([p, subs]) =>
        `<li>${esc(p)}${obj(p)}${
          subs.size
            ? `<ul>${[...subs].map((s) => `<li>${esc(s)}${obj(s)}</li>`).join('')}</ul>`
            : ''
        }</li>`,
    )
    .join('');
  return `<ul class="items quests">${rows}</ul>`;
}

function renderCampChest(items: ItemRef[], index: number): string {
  if (!items.length) return '';
  const gold = items.filter((i) => GOLD_STATS.has(i.stats)).reduce((n, i) => n + i.count, 0);
  const total = items.filter((i) => !GOLD_STATS.has(i.stats)).reduce((n, i) => n + i.count, 0);
  const goldNote = gold
    ? `<span class="fold-note">${gold.toLocaleString('en-GB')} gold</span>`
    : '';
  return `<section class="char" style="--i:${index}">
    <h3 class="char-name">Camp Chest</h3>
    <details class="fold">
      <summary>Stored <span class="count">${total}</span>${goldNote}</summary>
      <div>${itemGroups(items)}</div>
    </details>
  </section>`;
}

function renderQuests(q: QuestsReport, index: number): string {
  if (q.failed) return '';
  const active = questTree(q.active);
  const closed = questTree(q.closed);
  if (!active.tree.size && !closed.tree.size) return '';
  return `<section class="char" style="--i:${index}">
    <h3 class="char-name">Quest Log</h3>
    <details class="fold" open>
      <summary>In progress <span class="count">${active.tree.size}</span></summary>
      <div>${questList(active)}</div>
    </details>
    <details class="fold">
      <summary>Completed or closed <span class="count">${closed.tree.size}</span><span class="fold-note">the save does not distinguish completed from failed</span></summary>
      <div>${questList(closed)}</div>
    </details>
  </section>`;
}

function renderCampaign(story: StoryState, index: number): string {
  const approval = story.approval.length
    ? `<div class="approval">
        <h4 class="sect-head">Companion approval</h4>
        <ul class="approval-list">${story.approval
          .map((a) => {
            const pct = Math.max(0, Math.min(100, a.rating));
            const dating = story.dating.includes(a.name) ? 'dating' : '';
            return `<li><span class="ap-name">${esc(a.name)}</span><span class="ap-bar"><span style="width:${pct}%"></span></span><span class="ap-val">${a.rating}</span><span class="ap-dating">${dating}</span></li>`;
          })
          .join('')}</ul>
      </div>`
    : '';
  const tadpoles = story.tadpoles.length
    ? story.tadpoles.map((t) => `${esc(t.name)} ×${t.count}`).join(', ')
    : '';
  const counter = (label: string, value: string): string =>
    value ? `<div><dt>${label}</dt><dd>${value}</dd></div>` : '';
  const guardian = guardianUrl
    ? `<figure class="guardian"><img src="${esc(guardianUrl)}" alt="The Dream Guardian" width="84" height="84"><figcaption>Dream Guardian</figcaption></figure>`
    : '';
  return `<section class="char campaign" style="--i:${index}">
    <h3 class="char-name">Campaign</h3>
    <div class="campaign-grid">
      ${guardian}
      ${approval}
      <dl class="save-meta campaign-counters">
        ${counter('Long rests', String(story.long_rests))}
        ${counter('Waypoints', String(story.waypoints.length))}
        ${counter('Traders met', String(story.traders_met))}
        ${counter('Tadpoles', tadpoles)}
      </dl>
    </div>
  </section>`;
}

let thumbUrl: string | null = null;

/* ---- Item search --------------------------------------------------------- */

// The query survives re-parses (watch mode: quicksave, then glance at the
// same search), so it lives outside the rendered report.
let itemIndex: ItemPlace[] = [];
let itemQuery = '';

function updateSearchResults(): void {
  const summaryEl = reportEl.querySelector('.search-summary') as HTMLElement | null;
  const listEl = reportEl.querySelector('.search-results') as HTMLElement | null;
  if (!summaryEl || !listEl) return;
  if (itemQuery.trim().length < MIN_QUERY) {
    summaryEl.textContent = '';
    listEl.innerHTML = '';
    return;
  }
  const view = renderSearchResults(searchItems(itemIndex, itemQuery), itemQuery, effectsFor);
  summaryEl.textContent = view.summary;
  listEl.innerHTML = view.listHtml;
}

reportEl.addEventListener('input', (e) => {
  const input = e.target as HTMLInputElement;
  if (input.id !== 'item-search-input') return;
  itemQuery = input.value;
  updateSearchResults();
});

function showReport(r: SaveReport, statusText: string, thumbnail?: ArrayBuffer | null): void {
  setStatus(statusText);

  if (thumbUrl) URL.revokeObjectURL(thumbUrl);
  thumbUrl = thumbnail ? URL.createObjectURL(new Blob([thumbnail], { type: 'image/webp' })) : null;

  const namesNote = r.names_resolved
    ? ''
    : '<p class="names-note">Display names unavailable; items and spells are shown by their internal names.</p>';

  itemIndex = buildItemIndex(r, SLOT_LABELS, GOLD_STATS);
  reportEl.innerHTML =
    renderSaveHead(r.save_info, r.source, thumbUrl) +
    namesNote +
    renderSearchSection(itemQuery, 1) +
    r.characters.map((c, i) => renderCharacter(c, i + 2)).join('') +
    (r.camp_chest ? renderCampChest(r.camp_chest, r.characters.length + 2) : '') +
    (r.quests ? renderQuests(r.quests, r.characters.length + 3) : '') +
    (r.story ? renderCampaign(r.story, r.characters.length + 4) : '');
  updateSearchResults();

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
        setPortraits(rec.portraits ?? [], rec.guardian ?? null);
        showReport(
          rec.report,
          `Loaded ${rec.saveName} from history (saved ${rec.savedAt}).`,
          rec.thumbnail,
        );
        if ((rec.version ?? 0) < REPORT_VERSION) {
          reportEl.insertAdjacentHTML(
            'afterbegin',
            `<p class="stale-note">This entry was parsed by an older version of the site.
             Drop the save file again to see everything the parser can read now.</p>`,
          );
        }
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
    | {
        kind: 'report';
        report: SaveReport;
        ms: number;
        thumbnail: ArrayBuffer | null;
        portraits?: { name: string; buf: ArrayBuffer }[];
        guardian?: ArrayBuffer | null;
      }
    | { kind: 'error'; message: string };
  document.body.classList.remove('busy');
  if (msg.kind === 'error') {
    const detail = msg.message.replace(/^Error:\s*/, '').replace(/\s*\([^)]*\)\s*$/, '');
    setStatus(`Couldn't read that file (${detail}). Is it a BG3 .lsv save?`, true);
    return;
  }
  const r = msg.report;
  const time = msg.ms < 1000 ? `${msg.ms} ms` : `${(msg.ms / 1000).toFixed(1)} s`;
  setPortraits(msg.portraits ?? [], msg.guardian ?? null);
  showReport(r, `Parsed ${r.source} in ${time}. Nothing left your machine.`, msg.thumbnail);
  currentCampaign = r.save_info.leader;
  recordSave(r, msg.thumbnail, msg.portraits ?? [], msg.guardian ?? null)
    .then(refreshHistory)
    .catch((err) => console.error('History store failed:', err));
};
