"""Stable telemetry exports derived from the structured report model."""

from __future__ import annotations

import datetime
import json
from collections import Counter
from typing import Any

from .model import SLOT_DISPLAY_ORDER, CharacterReport, ItemRef, SaveReport


def telemetry_v1(report: SaveReport) -> dict[str, Any]:
    """Map a ``SaveReport`` to the stable Telemetry Schema v1 boundary."""

    save_info = report.save_info or {}
    active = [char for char in report.characters if not char.at_camp]
    camp = [char for char in report.characters if char.at_camp]

    document: dict[str, Any] = {
        'schema_version': 1,
        'save': _save(save_info),
        'campaign': _campaign(save_info),
        'party': [_character(char) for char in active],
        'camp': [_character(char) for char in sorted(camp, key=lambda char: char.name)],
        'relationships': _relationships(report.story),
        'quests': _quests(report.quests),
        'tactical': {
            'location': _tactical_location(active, save_info),
            'in_combat': None,
            'round': None,
            'active_actor': None,
            'initiative': [],
            'enemies': [],
            'threats': [],
            'objectives': [],
        },
    }
    return document


def render_telemetry_v1(report: SaveReport) -> str:
    """Serialize Telemetry Schema v1 deterministically for files and Git."""

    return json.dumps(telemetry_v1(report), indent=2, ensure_ascii=False) + '\n'


def _known(value: Any) -> Any | None:
    return None if value in (None, '', '?') else value


def _saved_at(value: Any) -> str | None:
    value = _known(value)
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.datetime.strptime(value, '%Y-%m-%d %H:%M:%S UTC')
    except ValueError:
        return value if value.endswith('Z') else None
    return parsed.replace(tzinfo=datetime.UTC).isoformat().replace('+00:00', 'Z')


def _save(info: dict) -> dict[str, Any]:
    return {
        'name': _known(info.get('save_name')),
        'saved_at': _saved_at(info.get('saved_at')),
        'region': _known(info.get('level')),
        'difficulty': _known(info.get('difficulty')),
        'leader': _known(info.get('leader')),
        'game_version': _known(info.get('game_version')),
        'mods': sorted({name for name in info.get('mods', []) if _known(name)}),
    }


def _campaign(info: dict) -> dict[str, Any]:
    campaign = {}
    for key in ('camp_supplies', 'short_rests', 'inspiration', 'tadpoles_available'):
        if info.get(key) is not None:
            campaign[key] = info[key]
    if info.get('recipes') is not None:
        campaign['recipes'] = sorted(info['recipes'])
    return campaign


def _character(char: CharacterReport) -> dict[str, Any]:
    result: dict[str, Any] = {
        'name': char.name,
        'classes': [
            {'name': cls.get('Main') or None, 'subclass': cls.get('Sub') or None}
            for cls in char.classes
        ],
    }
    if isinstance(char.level, int) and not isinstance(char.level, bool):
        result['level'] = char.level
    result.update(
        {
            key: value
            for key, value in (('race', char.race), ('xp', char.xp), ('location', char.location))
            if _known(value) is not None
        }
    )
    if char.abilities is not None:
        result['abilities'] = dict(char.abilities)
    if char.hp is not None:
        result['hp'] = dict(char.hp)
    if char.concentration is not None:
        result['concentration'] = {
            'id': char.concentration.get('id'),
            'name': char.concentration.get('name'),
        }
    if char.resources is not None:
        result['resources'] = sorted(
            (
                {
                    'id': resource.get('guid'),
                    'name': resource.get('name'),
                    'level': resource.get('level') or None,
                    'current': resource.get('current'),
                    'max': resource.get('max'),
                    'replenish': resource.get('replenish'),
                }
                for resource in char.resources
            ),
            key=lambda resource: (
                resource['name'] or '',
                resource['level'] if resource['level'] is not None else -1,
                resource['id'] or '',
            ),
        )
    if char.spells is not None:
        result['spells'] = [
            {
                'id': spell.id,
                'name': spell.name,
                'category': spell.category,
                'prepared': spell.prepared,
                'source': spell.source,
                'level': spell.level,
            }
            for spell in sorted(char.spells, key=lambda spell: spell.id)
        ]
    if char.illithid_powers is not None:
        result['illithid_powers'] = sorted(set(char.illithid_powers))
    if char.reactions is not None:
        result['reactions'] = sorted(set(char.reactions))
    if char.feats is not None:
        result['feats'] = sorted(
            (
                {
                    'guid': feat.get('guid'),
                    'name': feat.get('name'),
                    'level': feat.get('level'),
                    'picks': feat.get('picks', []),
                }
                for feat in char.feats
            ),
            key=lambda feat: (feat['guid'] or '', feat['level'] or 0),
        )
    result['equipment'] = [_equipment(item) for item in sorted(char.equipped, key=_equipment_key)]
    result['inventory'] = _inventory(char.carried)
    return result


def _item_identity(item: ItemRef) -> dict[str, Any]:
    return {
        'id': item.template_guid,
        'stats': item.stats,
        'name': item.name,
    }


def _equipment(item: ItemRef) -> dict[str, Any]:
    return _item_identity(item) | {'slot': item.slot, 'count': item.count}


def _equipment_key(item: ItemRef) -> tuple:
    base_slot = (item.slot or '').removesuffix(' 2')
    return (
        SLOT_DISPLAY_ORDER.get(base_slot, len(SLOT_DISPLAY_ORDER)),
        item.slot or '',
        item.stats,
        item.template_guid,
    )


def _inventory(items: list[ItemRef]) -> list[dict[str, Any]]:
    counts: Counter[tuple[str, str, str | None, str]] = Counter()
    for item in items:
        counts[(item.template_guid, item.stats, item.name, item.category)] += item.count
    result = [
        {
            'id': item_id,
            'stats': stats,
            'name': name,
            'category': category,
            'count': count,
        }
        for (item_id, stats, name, category), count in counts.items()
    ]
    return sorted(
        result,
        key=lambda item: (
            item['category'],
            item['name'] or '',
            item['stats'],
            item['id'],
        ),
    )


def _relationships(story: dict | None) -> list[dict[str, Any]]:
    if not story:
        return []
    dating = set(story.get('dating', []))
    approval_by_name = {
        approval['name']: approval['rating'] for approval in story.get('approval', [])
    }
    return sorted(
        (
            {
                'name': name,
                'approval': approval_by_name.get(name),
                'dating': name in dating,
            }
            for name in approval_by_name.keys() | dating
        ),
        key=lambda relationship: relationship['name'],
    )


def _quests(quests: dict | None) -> dict[str, list[dict[str, Any]]]:
    if not quests or quests.get('failed'):
        return {}
    return {
        key: sorted(
            (
                {
                    'id': quest.get('id'),
                    'name': quest.get('name'),
                    'objective': quest.get('objective'),
                }
                for quest in quests.get(key, [])
            ),
            key=lambda quest: quest['id'] or '',
        )
        for key in ('active', 'closed')
    }


def _tactical_location(active: list[CharacterReport], info: dict) -> str | None:
    locations = sorted({_known(char.location) for char in active} - {None})
    if len(locations) == 1:
        return locations[0]
    return _known(info.get('level'))
