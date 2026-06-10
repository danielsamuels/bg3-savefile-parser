"""Views over the report model: plain text and JSON."""

import dataclasses
import json
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
        extras = [f'+{len(group)} {label}' for group, label in
                  ((folded['sub-spell'], 'sub-spells'),
                   (folded['basic-action'], 'basic actions')) if group]
        suffix = ('; ' + ', '.join(extras)) if extras else ''
        data['spells_shown'] = shown
        data['spells_header_suffix'] = suffix
    else:
        data['spells_shown'] = None
        data['spells_header_suffix'] = ''

    # Pre-sort equipped items — sort key depends on verbose, so must be Python-side.
    data['equipped_sorted'] = sorted(
        char.equipped,
        key=lambda i: (i.slot_rank, fmt_item(i, verbose)),
    )

    return data


def prepare_level_items(report: SaveReport, verbose: bool) -> list:
    """Pre-compute display strings for level-item entries."""
    if report.level_items is None:
        return []
    entries = []
    for e in report.level_items['entries']:
        qty = f'x{e.count}' if e.count > 1 else '   '
        label = (f'{e.name} ({e.stats})' if verbose else e.name) if e.name else e.stats
        entries.append({
            'qty_str': f'{qty:<4s}',
            'label_str': f'{label:<60s}',
            'category': e.category,
        })
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

    opts_dict = {
        'verbose': verbose,
        'all_spells': all_spells,
        'carried': carried,
        'limits': opt('limits'),
    }

    # Pre-compute values that require Python operators not available in Jinja2.
    quests_version = ''
    if report.quests and not report.quests.get('failed'):
        v = report.quests['version']
        quests_version = f'{v >> 8}.{v & 0xFF}'

    env = make_jinja_env()
    template = env.get_template('report.txt.j2')

    output = template.render(
        report=report,
        opts=opts_dict,
        chars_data=chars_data,
        level_items_entries=level_items_entries,
        spells_notes=SPELLS_NOTES,
        equipment_notes=EQUIPMENT_NOTES,
        fmt_item=fmt_item,
        verbose=verbose,
        inspect_pattern=report.inspect_pattern,
        quests_version=quests_version,
    )
    return output


def render_json(report: SaveReport, indent: int = 2) -> str:
    """Render the model as JSON (everything gathered, no view-side folding)."""
    return json.dumps(dataclasses.asdict(report), indent=indent, ensure_ascii=False)
