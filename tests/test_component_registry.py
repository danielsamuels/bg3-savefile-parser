"""Reviewed list of player-facing components the parser does not consume.

Each entry is a candidate surfaced by tests/audit_components.py: a component
present in saves (rows > 0), in a player-facing namespace, that no view reads.
This is the structural analogue of the resource registry, aimed at the tadpole
pool's actual failure mode (a whole structure the player sees that we never
read, not an unnamed GUID).

The guard fails if a save contains such a component NOT listed here, so a new
one (a game patch, a build that exercises a namespace our fixtures don't) gets
triaged instead of silently ignored. When a gap is closed by consuming the
component in the parser, it drops out of the audit's candidate set; delete it
from REVIEWED then.
"""

import glob
from pathlib import Path

import pytest

from tests.audit_components import candidate_components, lsmf_blob
from tests.test_parser import FIXTURE_DIR

# Genuine player-facing gaps worth surfacing (tracked in COVERAGE.md).
GAPS = {
    'game.god.v0.GodComponent',  # deity
    'game.god.v0.TagComponent',
    'game.character_creation.v0.GodComponent',
    'game.character_creation.v0.BackgroundComponent',  # background (Soldier, Criminal, ...)
    'game.background.v0.BackgroundGoals',  # background-goal progress
    'game.background.v0.GoalRecord',
    'game.background.v0.GoalsComponent',
    'game.calendar.v0.DaysPassedComponent',  # days passed / in-game date
    'game.calendar.v0.StartingDateComponent',
    'game.summons.v0.ContainerComponent',  # active summons
    'game.summons.v0.SummonWithStackId',
    'game.summons.v1.Lifetime',
    'game.summons.v1.LifetimeComponent',
    'game.summons.v1.EExtendedLifetime',
    'game.summons.v2.IsSummonComponent',
    'game.recruit.v0.RecruitedByComponent',  # hirelings / who recruited whom
    'game.recruit.v0.RecruiterComponent',
    'game.relation.v0.FactionComponent',  # faction reputation / relations
    'game.relation.v0.RelationFactions',
    'game.relation.v1.FactionRelation',
    'game.status.v0.IncapacitatedComponent',  # incapacitation (part of statuses)
    'game.passives.v1.UsageCountComponent',  # passive charges / use counts
    'game.passives.v0.ToggledPassivesComponent',  # toggled passives (e.g. Great Weapon Master)
}

# Reviewed and judged internal / not player-sheet (kept so the guard stays quiet).
INTERNAL = {
    'game.attitude.v0.AttitudeEntry',  # NPC AI attitudes, not the approval the player reads
    'game.attitude.v0.AttitudesToPlayersComponent',
    'game.attitude.v0.EIdentityState',
    'game.character_creation.v2.PassiveSelector',  # character-creation scratch
    'game.experience.v0.AvailableLevelComponent',  # "can level up" flag
    'game.experience.v0.ExperienceGaveOutComponent',  # bookkeeping
    'game.inventory.v0.CharacterHasGeneratedTradeTreasureComponent',
    'game.passives.v0.PersistentDataComponent',  # opaque {f32,f32} accumulators (FORMAT)
    'game.passives.v0.ScriptPassivesComponent',
    'game.relation.v0.ERelation',
    'game.relation.v2.RelationComponent',
    'game.status.v0.EIncapacitationReason',
    'game.status.v0.IndicateDarknessComponent',
    'game.status.v0.UniqueComponent',
    'game.trade.v0.CanTradeComponent',  # merchant-capability flags, not vendor stock
    'game.trade.v0.CanTradeSetComponent',
    'game.trade.v0.LegacyCanTradeProcessedComponent',
    'game.trade.v0.PresentTraderComponent',
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
