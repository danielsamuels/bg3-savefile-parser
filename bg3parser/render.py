"""Views over the report model: plain text and JSON."""

import dataclasses
import json

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


def render_text(report: SaveReport, opts=None) -> str:
    """Render the model as the classic plain-text report."""
    def opt(name: str) -> bool:
        return bool(getattr(opts, name.replace('-', '_'), False)) if opts is not None else False

    verbose = opt('verbose')
    lines: list[str] = []
    w = lines.append

    w('BG3 Save File Report')
    w(f'Source: {report.source}')
    w('=' * 72)

    if report.save_info is not None:
        si = report.save_info
        w('')
        w(f'Save Name  : {si["save_name"]}')
        w(f'Save #     : {si["save_id"]}')
        w(f'Saved At   : {si["saved_at"]}')
        w(f'Game Ver   : {si["game_version"]}')
        w(f'Level      : {si["level"]}')
        w(f'Difficulty : {si["difficulty"]}')
        w(f'Leader     : {si["leader"]}')
        if si['mods']:
            flag = '  (flagged unofficial by game)' if si['has_unofficial_mods'] else ''
            w(f'Mods       : {len(si["mods"])} user mod(s){flag}')
            for mod_name in si['mods']:
                w(f'             {mod_name}')
        else:
            w('Mods       : none')
        item_name_source = (
            'resolved from game data'
            if report.names_resolved
            else 'internal only (game data not found; set BG3_DATA_DIR)'
        )
        w(f'Item names : {item_name_source}')

    if report.quests is not None:
        w('')
        w('━' * 72)
        w('QUEST & STORY STATE  (Osiris / StorySave.bin)')
        w('━' * 72)
        q = report.quests
        if q['failed']:
            w('\n  (Osiris parse failed or frame not present)\n')
        else:
            w(f'\n  Osiris version: {q["version"] >> 8}.{q["version"] & 0xFF}')
            w(f'\n  Quests in progress ({len(q["active"])}):')
            for name in q['active']:
                w(f'    {name}')
            w(f'\n  Quests closed / resolved ({len(q["closed"])}):')
            w('  (closed covers completed and failed; no separate failed-quest DB)')
            for name in q['closed']:
                w(f'    {name}')
            w(f'\n  Finalized goals — flags=0x07 ({len(q["goals_finalized"])}):')
            w('  (orchestration goals finalize when the act/phase is *entered*, not finished;')
            w('   the presence of "Act2" here means Act 2 was started, not completed)')
            for name in q['goals_finalized']:
                w(f'    {name}')
            w(f'\n  Story flags — DB_GlobalFlag '
              f'(first {len(q["global_flags"])} of {q["global_flags_total"]} shown):')
            for name in q['global_flags']:
                w(f'    {name}')
            w('')

    w('')
    w('━' * 72)
    w('PARTY CHARACTERS')
    w('━' * 72)
    for char in report.characters:
        render_character(char, w, verbose=verbose,
                         all_spells=opt('all-spells'), carried=opt('carried'),
                         inspect_pattern=report.inspect_pattern)

    if report.level_items is not None:
        li = report.level_items
        w('')
        w('━' * 72)
        w('ALL ITEMS ON CURRENT LEVEL  (per-character gear listed above)')
        w('Note: items carried by party members are attributed to each character')
        w('above, by shared world position. The list below is the full level pool')
        w('(world loot, containers, vendor stock) for reference.')
        w('━' * 72)
        w(f'\n  {li["total"]} items total  ({li["unique"]} unique types)\n')
        for e in li['entries']:
            qty = f'x{e.count}' if e.count > 1 else '   '
            label = (f'{e.name} ({e.stats})' if verbose else e.name) if e.name else e.stats
            w(f'  {qty:4s} {label:60s} {e.category}')

    if opt('limits'):
        w('')
        w('━' * 72)
        w('LIMITS')
        w('━' * 72)
        w(LIMITS_NOTE)

    return '\n'.join(lines)


def render_character(char: CharacterReport, w, *, verbose: bool,
                     all_spells: bool, carried: bool,
                     inspect_pattern: str = '') -> None:
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
        folded = {'sub-spell': [], 'basic-action': []}
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
        return

    w(f'    Equipped ({len(char.equipped)}):')
    for item in sorted(char.equipped,
                       key=lambda i: (i.slot_rank, fmt_item(i, verbose))):
        suffix = f'  [{item.slot}]' if item.slot else ''
        w(f'      – {fmt_item(item, verbose)}{suffix}')
    if char.undetermined:
        w(f'    Worn or carried — undetermined ({len(char.undetermined)}):')
        for item in char.undetermined:
            w(f'      – {fmt_item(item, verbose)}')
    if carried:
        w(f'    Carried / personal inventory ({len(char.carried)}):')
        for item in char.carried:
            w(f'      – {fmt_item(item, verbose)}')


def render_json(report: SaveReport, indent: int = 2) -> str:
    """Render the model as JSON (everything gathered, no view-side folding)."""
    return json.dumps(dataclasses.asdict(report), indent=indent, ensure_ascii=False)
