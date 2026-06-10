"""Views over the report model: plain text and JSON."""

import dataclasses
import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from .model import CharacterReport, ItemRef, LevelItemEntry, SaveReport, SpellRef


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


LIMITS_NOTE = '''
  Spell attribution reads each character's exact spell book from the save's
  ECS blob (SpellBookComponent -> SpellData -> SpellId -> string pool),
  matching party members by class/subclass/level.  If two members share an
  identical build, their books cannot be told apart and a note is shown
  instead.

  Per-character item ownership is recovered from shared world position
  (each carried/worn item copies its holder's Translate).  Whether an
  attributed item is *worn* is determined by layered signals: a STATUS
  on-equip effect; the 0x04000000 Flags bit; ECS component membership; and
  physical-attachment components, with per-slot conflict resolution.  The
  displayed [Slot] is derived from item stats — the save stores no explicit
  ItemSlot field (same-type assignment like Ring vs Ring2 persists via
  container ordering).  See LIMITS.md.

  Display names are resolved from the installed game data (root templates +
  english.loca, following ParentTemplateId/using inheritance).  Without a
  game install (or with BG3_DATA_DIR unset and auto-detect failing) items
  are shown by their internal names.
'''

SPELLS_NOTES = {
    'ambiguous-build': '(identical class build to another party member '
                       '— spell books cannot be told apart)',
    'not-found': '(spell book not found)',
}
EQUIPMENT_NOTES = {
    'no-character-node': 'character node not found',
    'no-items': 'no items attributed (character off current level?)',
}


def dedup_sorted_spells(spells: list[SpellRef], verbose: bool) -> list[str]:
    """Deduplicate spell display strings (upcast variants share a name) and sort."""
    return sorted({fmt_spell(sp, verbose) for sp in spells})


def sort_equipped(items: list[ItemRef], verbose: bool) -> list[ItemRef]:
    """Sort equipped items by (slot_rank, display_name) — compound key Jinja2 can't express."""
    return sorted(items, key=lambda i: (i.slot_rank, fmt_item(i, verbose)))


def fmt_level_item(entry: LevelItemEntry, verbose: bool) -> str:
    """Format a level item entry as the padded columns line."""
    qty = f'x{entry.count}' if entry.count > 1 else '   '
    if entry.name:
        label = f'{entry.name} ({entry.stats})' if verbose else entry.name
    else:
        label = entry.stats
    return f'{qty:4s} {label:60s} {entry.category}'


def render_char(char: CharacterReport, opts: dict) -> str:
    """Render one character block as a multi-line string for the template."""
    verbose = opts.get('verbose', False)
    all_spells = opts.get('all_spells', False)
    carried = opts.get('carried', False)
    inspect_pattern = opts.get('inspect_pattern', '')

    lines: list[str] = []
    w = lines.append

    cls_str = '; '.join(fmt_class(c) for c in char.classes) if char.classes else '?'
    w('')
    w(f'  {char.name}')
    w(f'    Race      : {char.race}')
    w(f'    Class     : {cls_str}')
    w(f'    Level     : {char.level}')
    if char.xp is not None:
        w(f'    XP        : {char.xp}')
    if char.location:
        w(f'    Location  : {char.location}')

    if char.spells is not None:
        folded: dict[str, list[SpellRef]] = {'sub-spell': [], 'basic-action': []}
        shown_refs: list[SpellRef] = []
        for sp in char.spells:
            if not all_spells and sp.category in folded:
                folded[sp.category].append(sp)
            else:
                shown_refs.append(sp)
        shown = dedup_sorted_spells(shown_refs, verbose)
        extras = [f'+{len(group)} {label}' for group, label in
                  ((folded['sub-spell'], 'sub-spells'),
                   (folded['basic-action'], 'basic actions')) if group]
        suffix = ('; ' + ', '.join(extras)) if extras else ''
        w(f'    Spells/Abilities ({len(shown)}{suffix}):')
        for line in shown:
            w(f'      – {line}')
    else:
        w(f'    Spells/Abilities : {SPELLS_NOTES.get(char.spells_note or "not-found")}')

    if char.inspect:
        w(f'    Inspect — items matching {inspect_pattern!r}:')
        for entry in char.inspect:
            w(f'      – {entry.stats}')
            w(f'        eq_bit={entry.eq_bit} flags={entry.flags} '
              f'mc={entry.membership_count} status={entry.has_status}')
            w(f'        components ({len(entry.components)}):')
            for c in entry.components:
                w(f'          {c}')

    if char.equipment_note:
        w(f'    Equipment : {EQUIPMENT_NOTES[char.equipment_note]}')
        return '\n'.join(lines)

    w(f'    Equipped ({len(char.equipped)}):')
    for item in sort_equipped(char.equipped, verbose):
        slot_suffix = f'  [{item.slot}]' if item.slot else ''
        w(f'      – {fmt_item(item, verbose)}{slot_suffix}')
    if char.undetermined:
        w(f'    Worn or carried — undetermined ({len(char.undetermined)}):')
        for item in char.undetermined:
            w(f'      – {fmt_item(item, verbose)}')
    if carried:
        w(f'    Carried / personal inventory ({len(char.carried)}):')
        for item in char.carried:
            w(f'      – {fmt_item(item, verbose)}')

    return '\n'.join(lines)


def build_opts_dict(opts) -> dict:
    """Convert opts namespace (or None) to a plain dict for template use."""
    def opt(name: str) -> bool:
        return bool(getattr(opts, name.replace('-', '_'), False)) if opts is not None else False

    inspect_pattern = (getattr(opts, 'inspect', None) or '') if opts is not None else ''
    return {
        'verbose': opt('verbose'),
        'all_spells': opt('all-spells'),
        'carried': opt('carried'),
        'limits': opt('limits'),
        'inspect_pattern': inspect_pattern,
    }


def build_jinja_env() -> Environment:
    """Build the Jinja2 environment with custom filters registered."""
    env = Environment(
        loader=FileSystemLoader(Path(__file__).parent / 'templates'),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters['fmt_class'] = fmt_class
    env.filters['fmt_item'] = fmt_item
    env.filters['fmt_spell'] = fmt_spell
    env.filters['dedup_sorted_spells'] = dedup_sorted_spells
    env.filters['sort_equipped'] = sort_equipped
    env.filters['fmt_level_item'] = fmt_level_item
    env.filters['render_char'] = render_char
    return env


def render_text(report: SaveReport, opts=None) -> str:
    """Render the model as the classic plain-text report."""
    env = build_jinja_env()
    template = env.get_template('report.txt.j2')
    opts_dict = build_opts_dict(opts)
    result = template.render(
        report=report,
        opts=opts_dict,
        limits_note=LIMITS_NOTE,
    )
    # The template always emits one trailing newline after the final {% endif %}.
    # Strip it unconditionally: LIMITS_NOTE itself ends with '\n', reproducing
    # the original behaviour where w(LIMITS_NOTE) followed by '\n'.join(lines)
    # yields exactly one trailing newline; the non-limits path has none.
    if result.endswith('\n'):
        result = result[:-1]
    return result


def render_json(report: SaveReport, indent: int = 2) -> str:
    """Render the model as JSON (everything gathered, no view-side folding)."""
    return json.dumps(dataclasses.asdict(report), indent=indent, ensure_ascii=False)
