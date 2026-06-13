"""Tests for the quest cause-and-effect analyser (bg3parser.quest_analysis)."""

import pytest

from bg3parser import gamedata
from bg3parser.discovery import find_save_by_token
from bg3parser.lspk import extract_frames
from bg3parser.osiris import read_story
from bg3parser.osiris_eval import Fact, facts_from_databases
from bg3parser.quest_analysis import QuestAnalyser, named_consequences, quest_outcomes


class TestQuestOutcomes:
    def test_extracts_quest_and_step_and_dedupes_player_prefix(self):
        delta = {
            Fact('QuestUpdate', ('MOO_GnomeRescue', 'WulbrenPermaDefeated')),
            # the same outcome written with a leading character arg collapses
            Fact('QuestUpdate', ('S_Player_X', 'MOO_GnomeRescue', 'WulbrenPermaDefeated')),
            Fact('QuestClose', ('SOME_Quest',)),
            Fact('DB_Unrelated', ('x',)),
        }
        out = quest_outcomes(delta)
        assert ('MOO_GnomeRescue', 'WulbrenPermaDefeated') in out
        assert ('SOME_Quest', 'closed') in out
        assert len(out) == 2


class TestNamedConsequences:
    class FakeNames:
        def quest_name_for(self, q):
            return {'MOO_GnomeRescue': 'Rescue Wulbren'}.get(q)

    class FakeStep:
        def __init__(self, ud):
            self.unlock_disable = ud

    def test_filters_to_active_and_marks_terminal(self):
        outcomes = {('MOO_GnomeRescue', 'WulbrenDead'), ('NOT_ACTIVE', 'x')}
        step_index = {('MOO_GnomeRescue', 'WulbrenDead'): self.FakeStep(2)}
        res = named_consequences(outcomes, {'MOO_GnomeRescue'}, self.FakeNames(), step_index)
        assert len(res) == 1
        assert res[0]['title'] == 'Rescue Wulbren'
        assert res[0]['terminal'] is True


GAME_DIR = gamedata.find_game_data_dir()
SAVE_363 = find_save_by_token('363') if GAME_DIR else None


@pytest.mark.skipif(not (GAME_DIR and SAVE_363), reason='needs game install + save 363')
class TestAnalyserOnRealSave:
    def test_prison_purge_fails_the_gnome_rescue(self):
        analyser = QuestAnalyser.load()
        ver, ntf, goals = read_story(extract_frames(SAVE_363))
        baseline = facts_from_databases(ntf)
        out = analyser.consequences(baseline, {Fact('PROC_MOO_Assault_PurgePrison', ())})
        quests = {q for q, _ in out}
        # the assault purge kills the tracked gnome prisoners -> rescue fails
        assert 'MOO_GnomeRescue' in quests
