"""Single registry of known action-resource type GUIDs and how we handle each.

One table is the source of truth, replacing GUIDs scattered through other tests.
Each resource carries a status flag:

    handled         surfaced in the report (per-character pools, the tadpole pool)
    handled-unnamed surfaced, but gamedata has no display name for it
    gap             readable and named, but not surfaced yet

Three guards keep it honest:
  - test_no_unregistered_resource: any named resource present in a fixture but
    absent from RESOURCES fails. This is the anti-"silent miss" check: a new
    resource (new class build, game patch, or a collection we don't walk) cannot
    appear without someone giving it a status.
  - test_gap_resource_surfaced / test_unnamed_resource_named: xfail(strict) per
    gap/unnamed entry. Closing one flips it to XPASS, a hard failure that says
    "update this resource's status in RESOURCES".
  - test_registry_names_match_gamedata: the names we hardcode must match gamedata.

Add a resource here the moment the guard flags it; flip its status the moment a
gap or label is closed.
"""

import glob
import json
from pathlib import Path

import pytest

import bg3parser as parser
from bg3parser import gamedata, render
from tests.audit_resources import census_resources, lsmf_blob, per_character_guids
from tests.test_parser import FIXTURE_DIR

HANDLED = 'handled'
HANDLED_UNNAMED = 'handled-unnamed'
GAP = 'gap'

# guid (guid_le_str form) -> (gamedata name or None, status)
RESOURCES: dict[str, tuple[str | None, str]] = {
    # Per-character pools, surfaced via char.resources.
    '028304ef-e4b7-4dfb-a7ec-cd87865cdb16': ('Channel Divinity', HANDLED),
    '1531b6ec-4ba8-4b0d-8411-422d8f51855f': ('Sneak Attack Charge', HANDLED),
    '420c8df5-45c2-4253-93c2-7ec44e127930': ('Bonus Action', HANDLED),
    '45ff0f48-b210-4024-972f-b64a44dc6985': ('Reaction', HANDLED),
    '46886ba5-6505-4875-a747-ac14118e1e08': ('Sorcery Point(s)', HANDLED),
    '46bbeb43-9973-40fb-a11f-e386bc425a8e': ('Bardic Inspiration', HANDLED),
    '46d3d228-04e0-4a43-9a2e-78137e858c14': ('Ki Point(s)', HANDLED),
    '621126c6-a9f7-422c-9a0c-822503719ce4': ('Interrupt_LuckOfTheFarRealms_Charge', HANDLED),
    '6740f9f4-125d-4321-89e0-771fccd64622': ('Rage Charge', HANDLED),
    '68542019-178b-4f43-b9d3-51ab8e7b286b': ('Wild Shape Charge', HANDLED),
    '732e23a8-bb1d-4bec-a4df-1dd0e03b56c4': ('LegendaryResistanceCharge', HANDLED),
    '734cbcfb-8922-4b6d-8330-b2a7e4c14b6a': ('Action', HANDLED),
    '74737a08-7a77-457b-9740-ae363be2b80f': ('Arcane Recovery Charge', HANDLED),
    '8052b721-3a96-4baf-82c0-6dfa27da6c05': ('Interrupt_Indomitable', HANDLED),
    'b399bf6b-0294-4a92-b81c-7a711da2a315': ('Interrupt_HellishRebukeTiefling_Charge', HANDLED),
    'c0503ecf-c3cd-4719-9cfd-05460a1db95a': ('Channel Oath Charge', HANDLED),
    'c2d059f8-7369-4701-9a4c-f85c55d04db3': ('Lay on Hands Charge(s)', HANDLED),
    'd136c5d9-0ff0-43da-acce-a74a07f8d6bf': ('Spell Slot', HANDLED),
    'd6b2369d-84f0-4ca4-a3a7-62d2d192a185': ('Movement Speed', HANDLED),
    'e9127b70-22b7-42a1-b172-d02f828f260a': ('Warlock Spell Slot', HANDLED),
    'e92b57fe-78c0-4eb1-a92f-833aa2c20df2': ('Eyestalk Action', HANDLED),
    'f82e9e53-1391-4555-95b3-ad52c3b8e259': ('Superiority Die', HANDLED),
    # Per-character pools we surface but gamedata gives no name.
    '0d157939-3ede-45aa-a153-e8c2e47edb74': (None, HANDLED_UNNAMED),
    '78236f5a-94d5-4f8b-bb54-16f5508723e6': (None, HANDLED_UNNAMED),
    # Standalone collection (outside game.action_resources.v1.Component).
    '8b047f9c-ed68-4e00-87e0-c7eded6dcf09': ('Tadpole Power Point', HANDLED),
    'a9c98304-08e7-44b5-aaf9-da2ef5a50672': ('Inspiration Point', HANDLED),  # save_info.inspiration
    'a24ca5e2-01e1-48fd-a4c8-79b8817f0a18': (
        'Number of Short Rests',
        HANDLED,
    ),  # save_info.short_rests
}

FIXTURES = sorted(glob.glob(str(FIXTURE_DIR / '*.lsv')))
GAPS = [g for g, (_, s) in RESOURCES.items() if s == GAP]
UNNAMED = [g for g, (_, s) in RESOURCES.items() if s == HANDLED_UNNAMED]


def gamedata_names() -> dict[str, str]:
    data = json.loads((FIXTURE_DIR.parent.parent / 'data' / 'gamedata.json').read_text())
    return {k.lower(): v for k, v in data.get('action_resources', {}).items()}


@pytest.mark.parametrize('fixture', FIXTURES, ids=lambda p: Path(p).name)
def test_no_unregistered_resource(fixture):
    """Every named resource present in a save must have a registry entry."""
    blob = lsmf_blob(fixture)
    names = gamedata_names()
    present = set(per_character_guids(blob))
    present |= {g for g in census_resources(blob) if g.lower() in names}
    unknown = present - set(RESOURCES)
    assert not unknown, (
        f'{Path(fixture).name}: resources with no registry entry: {sorted(unknown)}. '
        'Add each to RESOURCES with a status (handled/handled-unnamed/gap)'
    )


@pytest.mark.parametrize('guid', GAPS)
@pytest.mark.xfail(strict=True, reason='standalone resource collection not walked/surfaced yet')
def test_gap_resource_surfaced(guid):
    """A gap resource should appear in the report once we surface it."""
    report = parser.gather_report(str(FIXTURE_DIR / 'quicksave_419.lsv'))
    assert guid in render.render_json(report)


@pytest.mark.parametrize('guid', UNNAMED)
@pytest.mark.xfail(strict=True, reason='gamedata has no display name for this resource')
def test_unnamed_resource_named(guid):
    dn = gamedata.DisplayNames.load()
    if not dn.available:
        pytest.skip('no game data available')
    assert dn.resource_name_for(guid)


def test_registry_names_match_gamedata():
    """Hardcoded names must match gamedata, so a rename can't drift unnoticed."""
    names = gamedata_names()
    for guid, (name, _status) in RESOURCES.items():
        if name is not None:
            assert names.get(guid.lower()) == name, (
                f'{guid}: registry {name!r} != gamedata {names.get(guid.lower())!r}'
            )
