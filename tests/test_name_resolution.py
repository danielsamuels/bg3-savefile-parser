"""Regression guard on base-game name resolution.

If a gamedata rebuild silently stops resolving a chunk of real spells, quests, or
items, the report quietly degrades to raw identifiers. This asserts that every
base-game name in each fixture still resolves. Mod content is excluded on purpose
(its scope is unbounded and we do not ship names for it): spells/items flagged by
MOD_MARKERS and HIDDEN_ internal quests are filtered out.

Across the fixtures, base-game spells and quests resolve completely; the only
unresolved real item is FOR_SchoolOgres_Horn (a game object gamedata has no name
for), which is allow-listed so a *new* gap is what fails.
"""

import glob
import json
import re
from argparse import Namespace
from pathlib import Path

import pytest

import bg3parser as parser
from bg3parser.render import render_json
from tests.test_parser import FIXTURE_DIR

# Substrings that mark mod-added content; excluded from the guard.
MOD_MARKERS = re.compile(r'_Mods_|Macro_', re.IGNORECASE)
# Real base-game objects gamedata has no display name for yet (allow-listed).
KNOWN_UNRESOLVED_ITEMS = {'FOR_SchoolOgres_Horn'}

FIXTURES = sorted(glob.glob(str(FIXTURE_DIR / '*.lsv')))


def unresolved(report: dict) -> tuple[set[str], set[str], set[str]]:
    """Base-game identifiers whose name did not resolve: (spells, quests, items)."""
    spells, quests, items = set(), set(), set()
    for c in report.get('characters', []):
        for s in c.get('spells') or []:
            sid = s.get('id') or ''
            if s.get('name') is None and not MOD_MARKERS.search(sid):
                spells.add(sid)
        for it in (c.get('equipped') or []) + (c.get('carried') or []):
            if it.get('name') is None:
                stats = it.get('stats') or ''
                if not MOD_MARKERS.search(stats):
                    items.add(stats or it.get('template_guid'))
    for it in report.get('camp_chest') or []:
        if it.get('name') is None:
            stats = it.get('stats') or ''
            if not MOD_MARKERS.search(stats):
                items.add(stats or it.get('template_guid'))
    q = report.get('quests') or {}
    for n in q.get('active') or []:
        qid = n.get('id') or ''
        if n.get('name') is None and not qid.startswith('HIDDEN_'):
            quests.add(qid)
    return spells, quests, items


@pytest.mark.parametrize('fixture', FIXTURES, ids=lambda p: Path(p).name)
def test_base_game_names_resolve(fixture):
    save = parser.gather_report(fixture, opts=Namespace(quests=True))
    report = json.loads(render_json(save))
    spells, quests, items = unresolved(report)
    new_items = items - KNOWN_UNRESOLVED_ITEMS
    assert not spells, f'unresolved base-game spells: {sorted(spells)}'
    assert not quests, f'unresolved base-game quests: {sorted(quests)}'
    assert not new_items, (
        f'unresolved base-game items (add to gamedata or allow-list): {sorted(new_items)}'
    )
