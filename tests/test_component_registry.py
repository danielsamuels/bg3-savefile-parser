"""Reviewed list of player-facing components the parser does not consume.

Each entry is a candidate surfaced by tests/audit_components.py: a component
present in saves (rows > 0) that no view reads and that the denylist did not mark
internal. This is the structural analogue of the resource registry, aimed at the
tadpole pool's actual failure mode (a whole structure the player sees that we
never read, not an unnamed GUID).

The guard fails if a save contains such a component NOT listed here, so a new one
(a game patch, a build or act our fixtures do not exercise) gets triaged instead
of silently ignored. Because audit_components uses a denylist, a brand-new
player-facing namespace becomes a candidate by default rather than vanishing.

The lists below were triaged against all 83 of the developer's real saves, not
just the committed fixtures, so they hold outside the fixture sample. When a gap
is closed by consuming the component in the parser, it drops out of the audit's
candidate set; delete it from GAPS then.
"""

import glob
from argparse import Namespace
from pathlib import Path

import pytest

import bg3parser as parser
from tests.audit_components import candidate_components, lsmf_blob
from tests.test_parser import FIXTURE_DIR

# Genuine player-facing gaps worth surfacing (tracked in COVERAGE.md).
GAPS = {
    'game.god.v0.GodComponent',  # deity
    'game.god.v0.TagComponent',
    'game.background.v0.BackgroundGoals',  # background + background-goal progress
    'game.background.v0.GoalRecord',
    'game.background.v0.GoalsComponent',
    'game.calendar.v0.DaysPassedComponent',  # days passed / in-game date
    'game.calendar.v0.StartingDateComponent',
    'game.summons.v0.ContainerComponent',  # active summons (the summoner's list)
    'game.recruit.v0.RecruitedByComponent',  # hirelings / who recruited whom
    'game.recruit.v0.RecruiterComponent',
    'game.relation.v0.FactionComponent',  # faction reputation / relations
    'game.relation.v0.RelationFactions',
    'game.relation.v1.FactionRelation',
    'game.status.v0.IncapacitatedComponent',  # incapacitation (part of statuses)
    'game.passives.v1.UsageCountComponent',  # passive charges / use counts
    'game.passives.v0.ToggledPassivesComponent',  # toggled passives (Great Weapon Master, ...)
}

# Reviewed and judged internal / not player-sheet (kept so the guard stays quiet).
INTERNAL = {
    'game.camp.v0.TriggerComponent',  # camp trigger zones
    'game.passives.v0.ScriptPassivesComponent',  # script-managed passives, not the sheet
    'game.relation.v0.ERelation',  # relation enum
    'game.relation.v2.RelationComponent',  # relation flag/singleton
    'game.summons.v0.SummonWithStackId',  # summon-entity plumbing (the gap is ContainerComponent)
    'game.summons.v1.EExtendedLifetime',
    'game.summons.v1.Lifetime',
    'game.summons.v1.LifetimeComponent',
    'game.summons.v2.IsSummonComponent',
}

REVIEWED = GAPS | INTERNAL
FIXTURES = sorted(glob.glob(str(FIXTURE_DIR / '*.lsv')))


@pytest.mark.parametrize('fixture', FIXTURES, ids=lambda p: Path(p).name)
def test_no_unreviewed_component(fixture):
    """A player-facing unconsumed component must be triaged (in GAPS or INTERNAL)."""
    present = set(candidate_components(lsmf_blob(fixture)))
    new = present - REVIEWED
    assert not new, (
        f'{Path(fixture).name}: unreviewed player-facing components {sorted(new)}. '
        'Triage each: add to GAPS (worth surfacing, note in COVERAGE.md) or INTERNAL.'
    )


def test_gaps_are_live_candidates():
    """Every GAPS component must actually appear as a candidate in some fixture.
    If the denylist (or a new consumer) silently removed one, it would vanish from
    the audit with no failure; this catches that over-reach."""
    seen: set[str] = set()
    for fixture in FIXTURES:
        seen |= set(candidate_components(lsmf_blob(fixture)))
    missing = GAPS - seen
    assert not missing, (
        f'GAPS no longer surfaced by the audit (denied or consumed?): {sorted(missing)}. '
        'If consumed, remove from GAPS; if wrongly denied, fix audit_components.'
    )


def test_covered_elsewhere_still_surfaced():
    """audit_components.COVERED_ELSEWHERE marks components consumed via byte-scan /
    Osiris / info.json so they are not flagged as gaps. That classification goes
    stale silently if such a consumer is removed. Verify the concepts still reach
    the report, so a regression fails here instead of hiding a real gap."""
    report = parser.gather_report(
        str(FIXTURE_DIR / 'quicksave_419.lsv'), opts=Namespace(quests=True)
    )
    chars = report.characters
    # tadpole_tree -> illithid powers / pool
    assert (
        any(getattr(c, 'illithid_powers', None) for c in chars)
        or report.save_info.get('tadpoles_available') is not None
    )
    assert report.story and report.story.get('approval') is not None  # approval.v0.Ratings
    assert any(c.race for c in chars)  # race.v0.RaceComponent
    assert any(c.xp is not None for c in chars)  # experience.v0.ExperienceComponent
    assert 'waypoints' in report.story  # party.v0.WaypointsComponent (may be empty early)
    assert any(c.feats for c in chars)  # progression LevelUp (feats)
