"""Executable backlog of known feature-coverage gaps (see COVERAGE.md).

Every test here asserts the DESIRED state of a feature the report should expose
and is marked xfail(strict=True). While the gap is open the test xfails; the day
someone implements it the test xpasses, which under strict=True is a hard
failure that says "remove this marker, you closed the gap." The backlog cannot
silently rot, and nothing here ever blocks CI for an unimplemented feature.

Two kinds of gap:
  - missing/unsurfaced: a player-facing attribute we do not put in the report.
  - unlabeled: a value we can read but have no name for (a gamedata gap).

When you close one: implement it, delete the xfail marker, keep the assertion.
"""

import json
from argparse import Namespace

import pytest

import bg3parser as parser
from bg3parser import gamedata, render, report_views
from tests.test_parser import FIXTURE_DIR

# QuickSave_419: mid/late campaign, tadpoled party, full resource set, gear.
SAVE = str(FIXTURE_DIR / 'quicksave_419.lsv')


@pytest.fixture(scope='module')
def report():
    return parser.gather_report(SAVE)


@pytest.fixture(scope='module')
def avatar(report):
    return next(c for c in report.characters if not c.at_camp)


@pytest.fixture(scope='module')
def view(avatar):
    return report_views.character_view(avatar, gamedata.DisplayNames.load(), 'summary', 'all')


# --- Character sheet: attributes a player reads that we do not extract ---


@pytest.mark.xfail(strict=True, reason='AC not extracted (COVERAGE.md)')
def test_armour_class(avatar):
    assert getattr(avatar, 'armour_class', None) is not None


@pytest.mark.xfail(strict=True, reason='resistances/immunities not extracted')
def test_resistances(avatar):
    assert getattr(avatar, 'resistances', None)


@pytest.mark.xfail(strict=True, reason='active statuses/conditions not extracted')
def test_active_statuses(avatar):
    # Concentration is surfaced; the broader buff/debuff status row is not.
    assert getattr(avatar, 'statuses', None) is not None


@pytest.mark.xfail(strict=True, reason='skill/save proficiencies not extracted')
def test_proficiencies(avatar):
    profs = getattr(avatar, 'proficiencies', None)
    assert profs and 'skills' in profs


@pytest.mark.xfail(strict=True, reason='exhaustion level not extracted')
def test_exhaustion(avatar):
    assert getattr(avatar, 'exhaustion', None) is not None


@pytest.mark.xfail(strict=True, reason='background + background goals not extracted')
def test_background(avatar):
    assert getattr(avatar, 'background', None)


@pytest.mark.xfail(strict=True, reason='passive class/racial features not extracted (feats only)')
def test_passive_features(view):
    assert view.get('passives')


@pytest.mark.xfail(strict=True, reason='encumbrance / carry weight not extracted')
def test_encumbrance(avatar):
    assert getattr(avatar, 'weight', None) is not None


@pytest.mark.xfail(strict=True, reason='inspiration points not surfaced as a field')
def test_inspiration(report):
    assert report.save_info.get('inspiration') is not None


# --- Resources: collected but not surfaced / not labelled ---


@pytest.mark.xfail(strict=True, reason='standalone resource collection not walked (only per-char)')
def test_standalone_party_resources_surfaced(report):
    # a9c98304 = 4 and a24ca5e2 = 2 are real resources in the save, surfaced nowhere.
    surfaced = report.save_info.get('party_resources')
    assert surfaced and any(r.get('guid', '').startswith('a9c98304') for r in surfaced)


@pytest.mark.xfail(strict=True, reason='gamedata action-resource name table is incomplete')
def test_present_resource_has_name():
    dn = gamedata.DisplayNames.load()
    if not dn.available:
        pytest.skip('no game data available')
    # 78236f5a is present in saves with value 1 but has no name in gamedata.
    name = dn.resource_name_for('78236f5a-94d5-4f8b-bb54-16f5508723e6')
    assert name


# --- Story / world: decoded or collected, not surfaced ---


@pytest.mark.xfail(strict=True, reason='faction reputation decoded (FORMAT) but not surfaced')
def test_faction_reputation_surfaced():
    report = parser.gather_report(SAVE, opts=Namespace(quests=True))
    assert report.story and report.story.get('faction_reputation')


@pytest.mark.xfail(strict=True, reason='global flags collected raw, not interpreted into decisions')
def test_global_flags_interpreted():
    report = parser.gather_report(SAVE, opts=Namespace(quests=True))
    decisions = (report.story or {}).get('decisions')
    assert decisions  # human-readable key story choices, not raw GLO_* flags


# --- Inventory ---


@pytest.mark.xfail(strict=True, reason='item charges / per-rest uses remaining not surfaced')
def test_item_charges(avatar):
    charged = [it for it in avatar.equipped if getattr(it, 'charges', None) is not None]
    assert charged


# --- Sanity: the report we DO produce stays parseable JSON (not xfail) ---


def test_report_json_is_valid(report):
    json.loads(render.render_json(report))
