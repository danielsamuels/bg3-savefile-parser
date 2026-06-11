"""Compact, filtered views over a SaveReport for the MCP tools.

The full report model serialises to ~200k characters on a mid-campaign
save: too big for one tool result. These views keep the facts an assistant
asks for (builds, worn gear with empty slots made explicit, magic items in
bags, active quests) and drop the bulk (basic actions in spell books,
internal GUIDs, vendor-trash detail) unless explicitly requested.

Used by mcp_server; deliberately import-free of the mcp package so the
views are testable with the base install.
"""

import dataclasses

from .effects import Effects
from .gamedata import DisplayNames
from .model import CharacterReport, ItemRef, SaveReport

SECTIONS = ('meta', 'party', 'camp', 'camp_chest', 'quests')
DETAIL_LEVELS = ('summary', 'full')
ITEM_FILTERS = ('magic', 'equipment', 'all')
QUEST_FILTERS = ('active', 'all', 'none')

GOLD_STATS = frozenset(('OBJ_GoldCoin', 'OBJ_GoldPile'))

# Slots reported even when empty, in panel order. An empty slot is an
# actionable fact (a bare ring slot is a free upgrade), so absence is
# spelled out as null rather than left to inference.
CANONICAL_SLOTS = (
    'Helmet',
    'Cloak',
    'Breast',
    'Gloves',
    'Boots',
    'Amulet',
    'Ring',
    'Ring 2',
    'Melee Main Weapon',
    'Melee Offhand Weapon',
    'Ranged Main Weapon',
    'Ranged Offhand Weapon',
)


def validate_choice(value: str, allowed: tuple[str, ...], param: str) -> str:
    if value not in allowed:
        raise ValueError(f'{param} must be one of {", ".join(allowed)}; got {value!r}')
    return value


def keep_item(ref: ItemRef, dn: DisplayNames, items: str) -> bool:
    """Apply the items filter; without gamedata everything passes ('all')."""
    if items == 'all' or not dn.available:
        return True
    if ref.stats not in dn.stats_to_slot:
        return False  # not equippable
    return items == 'equipment' or dn.rarity_for(ref.stats) is not None


def item_view(ref: ItemRef, dn: DisplayNames, fx: Effects | None = None) -> dict:
    out: dict = {'name': ref.name or ref.stats}
    slot = dn.stats_to_slot.get(ref.stats)
    if slot:
        out['slot'] = slot
    else:
        out['category'] = ref.category
    rarity = dn.rarity_for(ref.stats)
    if rarity:
        out['rarity'] = rarity
    if ref.count > 1:
        out['count'] = ref.count
    if fx is not None and (lines := fx.lines(ref.stats)):
        out['effects'] = lines
    return out


def equipped_view(char: CharacterReport, dn: DisplayNames, fx: Effects | None = None) -> dict:
    """Worn gear keyed by slot, canonical slots always present (null = empty)."""
    slots: dict = dict.fromkeys(CANONICAL_SLOTS)
    extras: list[dict] = []
    for ref in sorted(char.equipped, key=lambda r: r.slot_rank):
        entry: dict = {'name': ref.name or ref.stats}
        rarity = dn.rarity_for(ref.stats)
        if rarity:
            entry['rarity'] = rarity
        if fx is not None and (lines := fx.lines(ref.stats)):
            entry['effects'] = lines
        slot = ref.slot or ''
        if slot in slots and slots[slot] is None:
            slots[slot] = entry
        else:
            entry['slot'] = slot or None
            extras.append(entry)

    # A two-handed weapon fills its offhand slot; show that instead of an
    # apparently free slot.
    for main_slot, off_slot in (
        ('Melee Main Weapon', 'Melee Offhand Weapon'),
        ('Ranged Main Weapon', 'Ranged Offhand Weapon'),
    ):
        main = next((r for r in char.equipped if r.slot == main_slot), None)
        if main is not None and main.stats in dn.two_handed_stats and slots[off_slot] is None:
            slots[off_slot] = f'(used by two-handed {main.name or main.stats})'

    if extras:
        slots['other'] = extras
    return slots


def prepared_spell_names(char: CharacterReport) -> list[str]:
    """Class spells the character can cast right now, by display name.

    Basic actions and sub-spells are dropped; when the book carries no
    preparation data (known casters always have it) the whole class-spell
    list stands in. Upcast duplicates collapse on the shared display name.
    """
    real = [s for s in char.spells or [] if s.category == 'spell']
    has_prep_data = any(s.prepared is not None for s in real)
    picked = [s for s in real if s.prepared] if has_prep_data else real
    names: list[str] = []
    seen: set[str] = set()
    for s in picked:
        n = s.name or s.id
        if n not in seen:
            seen.add(n)
            names.append(n)
    return names


def character_view(
    char: CharacterReport,
    dn: DisplayNames,
    detail: str,
    items: str,
    fx: Effects | None = None,
) -> dict:
    if detail == 'full':
        return dataclasses.asdict(char)
    out: dict = {
        'name': char.name,
        'race': char.race,
        'classes': char.classes,
        'level': char.level,
    }
    if char.location and char.location != 'camp':
        out['location'] = char.location
    if char.at_camp:
        out['at_camp'] = True
    if char.abilities:
        out['abilities'] = char.abilities
    if char.hp:
        out['hp'] = char.hp
    out['equipped'] = equipped_view(char, dn, fx)
    if char.equipment_note:
        out['equipment_note'] = char.equipment_note
    gold = sum(r.count for r in char.carried if r.stats in GOLD_STATS)
    if gold:
        out['gold'] = gold
    carried = [
        item_view(r, dn, fx)
        for r in char.carried
        if r.stats not in GOLD_STATS and keep_item(r, dn, items)
    ]
    if carried:
        out['carried'] = carried
    undetermined = [item_view(r, dn, fx) for r in char.undetermined if keep_item(r, dn, items)]
    if undetermined:
        out['undetermined'] = undetermined
    spells = prepared_spell_names(char)
    if spells:
        out['prepared_spells'] = spells
    elif char.spells_note:
        out['spells_note'] = char.spells_note
    if char.concentration:
        out['concentrating_on'] = char.concentration.get('name') or char.concentration.get('id')
    return out


def save_view(
    report: SaveReport,
    dn: DisplayNames,
    sections: tuple[str, ...],
    detail: str,
    items: str,
    quests: str,
    fx: Effects | None = None,
) -> dict:
    out: dict = {'source': report.source}
    if not report.names_resolved:
        out['names_resolved'] = False

    if 'meta' in sections and report.save_info:
        info = dict(report.save_info)
        if detail != 'full':
            recipes = info.pop('recipes', None)
            if recipes:
                info['recipes_known'] = len(recipes)
            info.pop('game_id', None)
        out['save_info'] = info

    if 'party' in sections:
        out['party'] = [
            character_view(c, dn, detail, items, fx) for c in report.characters if not c.at_camp
        ]
    if 'camp' in sections:
        out['camp_companions'] = [
            character_view(c, dn, detail, items, fx) for c in report.characters if c.at_camp
        ]

    if 'camp_chest' in sections and report.camp_chest is not None:
        out['camp_chest'] = {
            'gold': sum(r.count for r in report.camp_chest if r.stats in GOLD_STATS),
            'items': [
                item_view(r, dn, fx)
                for r in report.camp_chest
                if r.stats not in GOLD_STATS and keep_item(r, dn, items)
            ],
        }

    if 'quests' in sections and quests != 'none' and report.quests is not None:
        if report.quests.get('failed'):
            out['quests'] = {'failed': True}
        else:
            qv: dict = {'active': report.quests['active']}
            if quests == 'all':
                qv['closed'] = [{'id': q['id'], 'name': q['name']} for q in report.quests['closed']]
            out['quests'] = qv

    return out
