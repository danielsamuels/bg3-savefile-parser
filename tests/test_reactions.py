"""Reaction abilities (the in-game Reactions panel) — decode, attribution, and
gamefile-sourced naming.

The matcher binds an interrupt row to a character by feat/resource signature,
not by a fragile entity index (game.interrupt.v0.PreferencesComponent owners do
not line up with the spell-book entity space). These tests pin that behaviour:
the live row wins over origin-pool stand-ins, item procs are dropped, ambiguous
matches attach nothing, and names come from the game files.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import bg3parser as parser  # noqa: E402
from bg3parser import gamedata  # noqa: E402
from bg3parser.model import match_reactions  # noqa: E402

FIXTURE_DIR = Path(__file__).parent / 'fixtures'
GAMEDATA_JSON = PROJECT_ROOT / 'data' / 'gamedata.json'


def stub_dn() -> gamedata.DisplayNames:
    return gamedata.DisplayNames(
        {},
        {},
        interrupt_names={
            'Interrupt_Riposte': 'Riposte',
            'Interrupt_AttackOfOpportunity': 'Opportunity Attack',
            'Interrupt_PolearmMaster': 'Polearm Master: Opportunity Attack',
        },
    )


def char(name, feats=(), resources=()):
    """A minimal stand-in carrying just the fields match_reactions reads."""
    return SimpleNamespace(
        name=name,
        feats=[{'name': f} for f in feats],
        resources=[{'name': r} for r in resources],
        reactions=None,
    )


def test_live_row_wins_over_standin_and_drops_item_procs():
    maia = char(
        'Maia', feats=['Polearm Master', 'Great Weapon Master'], resources=['Interrupt_Indomitable']
    )
    prefs = {
        5: [
            'Interrupt_AttackOfOpportunity',
            'Interrupt_Riposte',
            'Interrupt_MAG_ParalyzingCritical',  # item proc — dropped
            'Interrupt_PolearmMaster',  # the feat anchor
        ],
        9: ['Interrupt_Riposte', 'Interrupt_AttackOfOpportunity'],  # origin-pool stand-in
    }
    match_reactions([maia], prefs, stub_dn())
    # Polearm Master anchors row 5 (the stand-in scores 0); names from game files.
    assert maia.reactions == [
        'Opportunity Attack',
        'Riposte',
        'Polearm Master: Opportunity Attack',
    ]


def test_no_signature_attaches_nothing():
    # Without game data, feat names are None: an empty signature must not guess.
    karlach = SimpleNamespace(name='Karlach', feats=[{'name': None}], resources=[], reactions=None)
    prefs = {5: ['Interrupt_Riposte', 'Interrupt_AttackOfOpportunity']}
    match_reactions([karlach], prefs, stub_dn())
    assert karlach.reactions is None


def test_tie_attaches_nothing():
    fighter = char('Fighter', feats=['Sentinel'])
    prefs = {1: ['Interrupt_Sentinel'], 2: ['Interrupt_Sentinel']}  # two rows tie
    match_reactions([fighter], prefs, stub_dn())
    assert fighter.reactions is None


def test_one_row_never_claimed_by_two_characters():
    a = char('A', feats=['Polearm Master'])
    b = char('B', feats=['Polearm Master'])
    prefs = {5: ['Interrupt_PolearmMaster', 'Interrupt_Riposte']}
    match_reactions([a, b], prefs, stub_dn())
    claimed = [c for c in (a, b) if c.reactions]
    assert len(claimed) == 1  # the first claims it; the other gets nothing


def test_quicksave_419_maia_reactions_from_gamefiles(monkeypatch):
    """End to end on a bundled save: the Battle Master's Riposte is surfaced,
    with the in-game name pulled from the game files (not a regex guess)."""
    if not GAMEDATA_JSON.exists():
        import pytest

        pytest.skip('committed gamedata.json absent')
    monkeypatch.setenv('BG3_GAMEDATA_JSON', str(GAMEDATA_JSON))
    report = parser.gather_report(str(FIXTURE_DIR / 'quicksave_419.lsv'))
    maia = next(c for c in report.characters if c.name.startswith('Maia'))
    assert maia.reactions, 'Maia should have a matched reaction row'
    assert 'Riposte' in maia.reactions
    # The game calls it "Opportunity Attack", which a regex over the ID would miss.
    assert 'Opportunity Attack' in maia.reactions
