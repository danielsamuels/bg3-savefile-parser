"""Views over the report model: plain text and JSON."""

import dataclasses
import json
from collections import Counter
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from .model import CharacterReport, ItemRef, SaveReport, SpellRef


def fmt_class(cls: dict) -> str:
    main = cls.get('Main', '')
    sub = cls.get('Sub', '')
    return f'{main} / {sub}' if sub else main


def fmt_item(item: ItemRef, verbose: bool) -> str:
    if item.name:
        return f'{item.name} ({item.stats})' if verbose else item.name
    return item.stats


def fmt_spell(spell: SpellRef, verbose: bool) -> str:
    if spell.name:
        return f'{spell.name} ({spell.id})' if verbose else spell.name
    return spell.id


SPELLS_NOTES = {
    'ambiguous-build': '(identical class build to another party member '
    '— spell books cannot be told apart)',
    'not-found': '(spell book not found)',
}
EQUIPMENT_NOTES = {
    'no-character-node': 'character node not found',
    'no-items': 'no items attributed (character off current level?)',
}

# Carried-inventory group headers, in display order.
CARRIED_GROUP_LABELS = (
    ('weapon', 'Weapons & magic items'),
    ('armour', 'Armour & accessories'),
    ('consumable', 'Potions & consumables'),
    ('book', 'Books & scrolls'),
    ('misc', 'Everything else'),
)


def prepare_char_data(char: CharacterReport, verbose: bool, all_spells: bool) -> dict:
    """Pre-process per-character spell and item data for the template.

    Handles set-based dedup, multi-key sorting, and spells-header suffix
    construction — the genuinely complex logic that belongs in Python.
    """
    data: dict = {}

    if char.spells is not None:
        folded: dict[str, list] = {'sub-spell': [], 'basic-action': []}
        shown_refs = []
        for sp in char.spells:
            if not all_spells and sp.category in folded:
                folded[sp.category].append(sp)
            else:
                shown_refs.append(sp)
        # Upcast variants share a display name; show each rendering once.
        shown = sorted({fmt_spell(sp, verbose) for sp in shown_refs})
        extras = [
            f'+{len(group)} {label}'
            for group, label in (
                (folded['sub-spell'], 'sub-spells'),
                (folded['basic-action'], 'basic actions'),
            )
            if group
        ]
        suffix = ('; ' + ', '.join(extras)) if extras else ''
        data['spells_shown'] = shown
        data['spells_header_suffix'] = suffix
    else:
        data['spells_shown'] = None
        data['spells_header_suffix'] = ''

    # Action resources: drop per-turn trivia, empty pools, and entries with
    # no localised name (internal interrupt charges and the like); group
    # spell-slot levels under one label.
    line_parts: list[str] = []
    skip_names = {'Action', 'Bonus Action', 'Reaction', 'Movement Speed'}
    if char.resources:
        groups: dict[str, list] = {}
        for r in char.resources:
            name = r['name']
            if not name or name in skip_names or '_' in name or r['max'] <= 0:
                continue
            groups.setdefault(name, []).append(r)
        for name, rs in groups.items():
            rs.sort(key=lambda r: r['level'])
            bits = ', '.join(
                (f'L{r["level"]} ' if r['level'] else '') + f'{r["current"]:g}/{r["max"]:g}'
                for r in rs
            )
            line_parts.append(f'{name} {bits}')
    data['resources_line'] = '; '.join(line_parts)

    # Feats: "Ability Improvement (L6: +2 Strength)"; picks counted per ability.
    feat_parts: list[str] = []
    for f in char.feats or ():
        label = f['name'] or f['guid']
        picks = Counter(f['picks'])
        picks_str = ', '.join(f'+{n} {a}' for a, n in picks.items())
        detail = f'L{f["level"]}' + (f': {picks_str}' if picks_str else '')
        feat_parts.append(f'{label} ({detail})')
    data['feats_line'] = '; '.join(feat_parts)

    # Pre-sort equipped items — sort key depends on verbose, so must be Python-side.
    data['equipped_sorted'] = sorted(
        char.equipped,
        key=lambda i: (i.slot_rank, fmt_item(i, verbose)),
    )

    # Carried inventory grouped by coarse category, empty groups omitted;
    # stacks and several copies of one item collapse to a single "… x766" line.
    groups: list[tuple[str, list[str]]] = []
    for key, label in CARRIED_GROUP_LABELS:
        counts: Counter = Counter()
        for i in char.carried:
            if i.category == key:
                counts[fmt_item(i, verbose)] += i.count
        lines = [f'{lbl} x{n}' if n > 1 else lbl for lbl, n in sorted(counts.items())]
        if lines:
            groups.append((label, lines))
    data['carried_groups'] = groups

    return data


def prepare_level_items(report: SaveReport, verbose: bool) -> list:
    """Pre-compute display strings for level-item entries."""
    if report.level_items is None:
        return []
    entries = []
    for e in report.level_items['entries']:
        qty = f'x{e.count}' if e.count > 1 else '   '
        label = (f'{e.name} ({e.stats})' if verbose else e.name) if e.name else e.stats
        entries.append(
            {
                'qty_str': f'{qty:<4s}',
                'label_str': f'{label:<60s}',
                'category': e.category,
            }
        )
    return entries


def make_jinja_env() -> Environment:
    """Create the Jinja2 environment with registered format filters."""
    env = Environment(
        loader=FileSystemLoader(Path(__file__).parent / 'templates'),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=False,
    )
    env.filters['fmt_class'] = fmt_class
    env.filters['fmt_item'] = fmt_item
    env.filters['fmt_spell'] = fmt_spell
    env.filters['pyfmt'] = repr
    return env


def render_text(report: SaveReport, opts=None) -> str:
    """Render the model as the classic plain-text report."""

    def opt(name: str) -> bool:
        return bool(getattr(opts, name.replace('-', '_'), False)) if opts is not None else False

    verbose = opt('verbose')
    all_spells = opt('all-spells')
    carried = opt('carried')

    chars_data = [
        prepare_char_data(char, verbose=verbose, all_spells=all_spells)
        for char in report.characters
    ]
    level_items_entries = prepare_level_items(report, verbose=verbose)

    # Camp chest contents, grouped like a carried inventory.
    camp_chest_groups: list[tuple[str, list[str]]] = []
    if report.camp_chest:
        for key, label in CARRIED_GROUP_LABELS:
            counts: Counter = Counter()
            for i in report.camp_chest:
                if i.category == key:
                    counts[fmt_item(i, verbose)] += i.count
            lines = [f'{lbl} x{n}' if n > 1 else lbl for lbl, n in sorted(counts.items())]
            if lines:
                camp_chest_groups.append((label, lines))

    opts_dict = {
        'verbose': verbose,
        'all_spells': all_spells,
        'carried': carried,
        'limits': opt('limits'),
        'save_info': opt('save-info'),
        'no_spells': opt('no-spells'),
    }

    # Pre-compute values that require Python operators not available in Jinja2.
    quests_version = ''
    if report.quests and not report.quests.get('failed'):
        v = report.quests['version']
        quests_version = f'{v >> 8}.{v & 0xFF}'

    tadpole_summary = ''
    approval_lines: list[str] = []
    if report.story:
        tadpole_summary = ', '.join(f'{t["name"]} x{t["count"]}' for t in report.story['tadpoles'])
        dating = set(report.story['dating'])
        approval_lines = [
            f'{a["name"]:<12}{a["rating"]:>4}' + ('   (dating)' if a['name'] in dating else '')
            for a in report.story['approval']
        ]

    env = make_jinja_env()
    template = env.get_template('report.txt.j2')

    output = template.render(
        report=report,
        opts=opts_dict,
        chars_data=chars_data,
        camp_chest_groups=camp_chest_groups,
        level_items_entries=level_items_entries,
        spells_notes=SPELLS_NOTES,
        equipment_notes=EQUIPMENT_NOTES,
        fmt_item=fmt_item,
        verbose=verbose,
        inspect_pattern=report.inspect_pattern,
        quests_version=quests_version,
        tadpole_summary=tadpole_summary,
        approval_lines=approval_lines,
    )
    return output


def render_json(report: SaveReport, indent: int = 2) -> str:
    """Render the model as JSON (everything gathered, no view-side folding)."""
    return json.dumps(dataclasses.asdict(report), indent=indent, ensure_ascii=False)
