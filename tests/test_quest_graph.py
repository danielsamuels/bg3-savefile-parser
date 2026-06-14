"""Tests for the quest dependency graph (bg3parser.quest_graph).

The edge parser is a pure function over Osiris goal-script text, so it runs in
CI with no game install. Graph-build tests that touch the paks are gated on a
local install, mirroring the gamedata tests.
"""

import pytest

from bg3parser import gamedata
from bg3parser.gamedata import DisplayNames
from bg3parser.quest_graph import (
    Edge,
    QuestDefStmt,
    QuestGraph,
    StepInfo,
    build_quest_graph,
    build_quest_outlook,
    enrich_edge,
    normalize_edge,
    parse_quest_steps,
    parse_questdef_statements,
)


class TestParseQuestdefStatements:
    def test_parses_state_edge_with_flag_cast(self):
        text = (
            'DB_QuestDef_State((FLAG)Act2_PointOfNoReturnReached_'
            'a3155f30-b8f3-4db5-ac21-d3036f4426e3, "GLO_Tadpole", '
            '"Apprentice_PointOfNoReturn");'
        )
        stmts = parse_questdef_statements(text)
        assert len(stmts) == 1
        assert stmts[0].kind == 'State'
        assert stmts[0].args == [
            'Act2_PointOfNoReturnReached_a3155f30-b8f3-4db5-ac21-d3036f4426e3',
            'GLO_Tadpole',
            'Apprentice_PointOfNoReturn',
        ]

    def test_ignores_commented_out_statements(self):
        text = (
            '//DB_QuestDef_State((FLAG)Foo_guid, "Q", "Step"); //on hold\n'
            'DB_QuestDef_State((FLAG)Bar_guid, "Q2", "Step2");'
        )
        stmts = parse_questdef_statements(text)
        assert len(stmts) == 1
        assert stmts[0].args[1] == 'Q2'

    def test_parses_multiline_statement_with_extra_args(self):
        text = (
            'DB_QuestDef_State_ConditionalFlag((FLAG)SCL_Drider_HasMet_2af6450a, '
            '"GLO_Moonrise", "MetDrider",\n'
            '\t0,(FLAG)HAV_Siege_State_NoProtection_2da0dbf1);'
        )
        stmts = parse_questdef_statements(text)
        assert len(stmts) == 1
        assert stmts[0].kind == 'State_ConditionalFlag'
        assert stmts[0].args == [
            'SCL_Drider_HasMet_2af6450a',
            'GLO_Moonrise',
            'MetDrider',
            '0',
            'HAV_Siege_State_NoProtection_2da0dbf1',
        ]

    def test_parses_chained_state_four_args(self):
        text = (
            'DB_QuestDef_ChainedState("GLO_Tadpole", "FoundHalsin", "DEN_Conflict", "FoundHalsin");'
        )
        stmts = parse_questdef_statements(text)
        assert stmts[0].kind == 'ChainedState'
        assert stmts[0].args == [
            'GLO_Tadpole',
            'FoundHalsin',
            'DEN_Conflict',
            'FoundHalsin',
        ]

    def test_keeps_npc_token_for_kill_edges(self):
        text = (
            'DB_QuestDef_SawDeadState("GLO_Tadpole", "HagDied", '
            'S_HAG_Hag_c457d064-83fb-4ec6-b74d-1f30dfafd12d);'
        )
        stmts = parse_questdef_statements(text)
        assert stmts[0].args[2] == 'S_HAG_Hag_c457d064-83fb-4ec6-b74d-1f30dfafd12d'


class TestNormalizeEdge:
    def test_point_of_no_return_state_edge(self):
        stmt = QuestDefStmt(
            'State',
            ['Act2_PointOfNoReturnReached_g', 'GLO_Tadpole', 'Apprentice_PointOfNoReturn'],
        )
        edge = normalize_edge(stmt)
        assert edge is not None
        assert edge.trigger_kind == 'point_of_no_return'
        assert edge.quest_id == 'GLO_Tadpole'
        assert edge.target_step == 'Apprentice_PointOfNoReturn'
        assert edge.trigger_ref == 'Act2_PointOfNoReturnReached_g'

    def test_plain_flag_state_edge(self):
        stmt = QuestDefStmt('State', ['SomeFlag_g', 'DEN_Conflict', 'MetGoblin'])
        edge = normalize_edge(stmt)
        assert edge is not None
        assert edge.trigger_kind == 'flag'
        assert edge.quest_id == 'DEN_Conflict'
        assert edge.target_step == 'MetGoblin'

    def test_region_enter_edge(self):
        stmt = QuestDefStmt('LevelLoaded', ['COL_FindZevlor', 'NeverFoundZevlor', 'BGO_Main_A'])
        edge = normalize_edge(stmt)
        assert edge is not None
        assert edge.trigger_kind == 'region_enter'
        assert edge.quest_id == 'COL_FindZevlor'
        assert edge.target_step == 'NeverFoundZevlor'
        assert edge.trigger_ref == 'BGO_Main_A'

    def test_region_leave_edge(self):
        stmt = QuestDefStmt('LevelUnloading', ['Q', 'Step', 'WLD_Main_A'])
        edge = normalize_edge(stmt)
        assert edge is not None
        assert edge.trigger_kind == 'region_leave'

    def test_npc_death_edge(self):
        stmt = QuestDefStmt('SawDeadState', ['GLO_Tadpole', 'HagDied', 'S_HAG_Hag_c457'])
        edge = normalize_edge(stmt)
        assert edge is not None
        assert edge.trigger_kind == 'npc_death'
        assert edge.quest_id == 'GLO_Tadpole'
        assert edge.target_step == 'HagDied'
        assert edge.trigger_ref == 'S_HAG_Hag_c457'

    def test_npc_defeated_edge(self):
        stmt = QuestDefStmt(
            'PermaDefeatedState', ['UND_MyconidCircle', 'DefeatedDuergar', 'S_UND_LoneDuergar_05c3']
        )
        edge = normalize_edge(stmt)
        assert edge is not None
        assert edge.trigger_kind == 'npc_defeated'

    def test_book_read_edge(self):
        stmt = QuestDefStmt(
            'BookReadState', ['GLO_Tadpole', 'ReadHalsinDiary', 'S_GLO_HalsinDiary_5e4a']
        )
        edge = normalize_edge(stmt)
        assert edge is not None
        assert edge.trigger_kind == 'book_read'
        assert edge.target_step == 'ReadHalsinDiary'

    def test_quest_chain_edge(self):
        stmt = QuestDefStmt(
            'ChainedState', ['GLO_Tadpole', 'FoundHalsin', 'DEN_Conflict', 'LearnedIt']
        )
        edge = normalize_edge(stmt)
        assert edge is not None
        assert edge.trigger_kind == 'quest_chain'
        assert edge.source_quest == 'GLO_Tadpole'
        assert edge.source_step == 'FoundHalsin'
        assert edge.quest_id == 'DEN_Conflict'
        assert edge.target_step == 'LearnedIt'

    def test_conditional_edge(self):
        stmt = QuestDefStmt(
            'ConditionalState',
            ['DEN_Conflict', 'LearnedHalsinMissing', 'RathGaveQuest', 'ZevGaveQuest', '1'],
        )
        edge = normalize_edge(stmt)
        assert edge is not None
        assert edge.trigger_kind == 'conditional'
        assert edge.quest_id == 'DEN_Conflict'
        assert edge.target_step == 'LearnedHalsinMissing'

    def test_quest_chain_within_same_quest_three_args(self):
        stmt = QuestDefStmt(
            'ChainedState', ['PLA_TollhouseHunters', 'AcceptedBoth', 'AcceptedAnders']
        )
        edge = normalize_edge(stmt)
        assert edge is not None
        assert edge.trigger_kind == 'quest_chain'
        assert edge.source_quest == 'PLA_TollhouseHunters'
        assert edge.source_step == 'AcceptedBoth'
        assert edge.quest_id == 'PLA_TollhouseHunters'
        assert edge.target_step == 'AcceptedAnders'

    def test_too_few_args_returns_none(self):
        assert normalize_edge(QuestDefStmt('State', ['only_two', 'x'])) is None
        assert normalize_edge(QuestDefStmt('ChainedState', ['q', 's'])) is None
        assert normalize_edge(QuestDefStmt('LevelLoaded', ['q'])) is None

    def test_unknown_kind_returns_none(self):
        assert normalize_edge(QuestDefStmt('SomethingElse', ['a', 'b'])) is None


QUEST_PROTOTYPE_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<save>
  <region id="quests">
    <node id="root">
      <children>
        <node id="Quest">
            <attribute id="QuestID" type="FixedString" value="HAG_HagSpawn"/>
            <attribute id="QuestTitle" type="TranslatedString" handle="h0001" version="4"/>
            <children>
                <node id="QuestStep">
                    <attribute id="ID" type="FixedString" value="HuntEthel"/>
                    <attribute id="Objective" type="FixedString" value="HAG_HagSpawn_HuntEthel"/>
                    <attribute id="UnlockDisable" type="uint8" value="0"/>
                </node>
                <node id="QuestStep">
                    <attribute id="ID" type="FixedString" value="ReachedNoReturn"/>
                    <attribute id="Objective" type="FixedString" value="HAG_HagSpawn_COMPLETION"/>
                    <attribute id="UnlockDisable" type="uint8" value="2"/>
                </node>
            </children>
        </node>
        <node id="Quest">
            <attribute id="QuestID" type="FixedString" value="CHA_Chapel"/>
            <children>
                <node id="QuestStep">
                    <attribute id="ID" type="FixedString" value="LeftRegion"/>
                    <attribute id="Objective" type="FixedString" value="CHA_Chapel_COMPLETION"/>
                    <attribute id="UnlockDisable" type="uint8" value="2"/>
                </node>
            </children>
        </node>
      </children>
    </node>
  </region>
</save>"""


class TestParseQuestSteps:
    def test_maps_quest_step_to_objective_and_unlock_disable(self):
        steps = parse_quest_steps(QUEST_PROTOTYPE_SAMPLE)
        info = steps[('HAG_HagSpawn', 'ReachedNoReturn')]
        assert info.objective_id == 'HAG_HagSpawn_COMPLETION'
        assert info.unlock_disable == 2

    def test_step_belongs_to_its_enclosing_quest(self):
        steps = parse_quest_steps(QUEST_PROTOTYPE_SAMPLE)
        # LeftRegion is CHA_Chapel's step, not HAG_HagSpawn's
        assert ('CHA_Chapel', 'LeftRegion') in steps
        assert ('HAG_HagSpawn', 'LeftRegion') not in steps
        assert steps[('HAG_HagSpawn', 'HuntEthel')].unlock_disable == 0


class TestEnrichEdge:
    def test_point_of_no_return_edge_resolves_title_text_and_terminal(self):
        edge = Edge(
            'State',
            'point_of_no_return',
            'Act2_PointOfNoReturnReached_a3155f30-b8f3-4db5-ac21-d3036f4426e3',
            'HAG_HagSpawn',
            'ReachedNoReturn',
        )
        steps = {('HAG_HagSpawn', 'ReachedNoReturn'): StepInfo('HAG_HagSpawn_COMPLETION', 2)}
        names = DisplayNames(
            {},
            {},
            quest_names={'HAG_HagSpawn': 'Save Mayrina'},
            quest_objectives={'HAG_HagSpawn_COMPLETION': 'You failed to save her.'},
        )
        enriched = enrich_edge(edge, steps, names)
        assert enriched.terminal is True
        assert enriched.quest_title == 'Save Mayrina'
        assert enriched.target_objective_text == 'You failed to save her.'
        assert enriched.trigger_label == 'Act2_PointOfNoReturnReached'

    def test_non_terminal_step_is_not_terminal(self):
        edge = Edge('LevelLoaded', 'region_enter', 'BGO_Main_A', 'Q', 'Arrived')
        steps = {('Q', 'Arrived'): StepInfo('Q_Arrived', 0)}
        enriched = enrich_edge(edge, steps, DisplayNames({}, {}))
        assert enriched.terminal is False

    def test_empty_objective_text_becomes_none(self):
        edge = Edge('State', 'flag', 'F', 'Q', 'Done')
        steps = {('Q', 'Done'): StepInfo('Q_COMPLETION', 2)}
        names = DisplayNames({}, {}, quest_objectives={'Q_COMPLETION': ''})
        enriched = enrich_edge(edge, steps, names)
        assert enriched.target_objective_text is None

    def test_npc_death_label(self):
        edge = Edge(
            'SawDeadState',
            'npc_death',
            'S_HAG_Hag_c457d064-83fb-4ec6-b74d-1f30dfafd12d',
            'GLO_Tadpole',
            'HagDied',
        )
        enriched = enrich_edge(edge, {}, DisplayNames({}, {}))
        assert enriched.trigger_label == 'HAG_Hag dies'

    def test_region_enter_label(self):
        edge = Edge('LevelLoaded', 'region_enter', 'BGO_Main_A', 'Q', 'Step')
        enriched = enrich_edge(edge, {}, DisplayNames({}, {}))
        assert enriched.trigger_label == 'entering BGO_Main_A'


def _edge(quest, kind='flag', terminal=True, source_quest=None):
    return Edge(
        'State',
        kind,
        'ref',
        quest,
        'Step',
        source_quest=source_quest,
        terminal=terminal,
    )


class TestQuestGraph:
    def test_terminating_edges_for_filters_by_quest_and_terminal(self):
        e1 = _edge('Q1', terminal=True)
        e2 = _edge('Q1', terminal=False)
        e3 = _edge('Q2', terminal=True)
        graph = QuestGraph([e1, e2, e3])
        assert graph.terminating_edges_for('Q1') == [e1]

    def test_edges_for_includes_quest_chain_source(self):
        e1 = _edge('Q2', kind='quest_chain', source_quest='Q1')
        graph = QuestGraph([e1])
        assert graph.edges_for('Q1') == [e1]
        assert graph.edges_for('Q2') == [e1]


GAME_DIR = gamedata.find_game_data_dir()


@pytest.mark.skipif(not GAME_DIR, reason='no game install to build the quest graph')
class TestBuildQuestGraph:
    def test_act2_point_of_no_return_closes_save_mayrina(self):
        names = gamedata.DisplayNames.load()
        graph = build_quest_graph(GAME_DIR or '', names)
        terminating = graph.terminating_edges_for('HAG_HagSpawn')
        ponr = [e for e in terminating if e.trigger_kind == 'point_of_no_return']
        assert ponr, 'expected a point-of-no-return terminal edge for HAG_HagSpawn'
        assert any(e.quest_title == 'Save Mayrina' for e in ponr)

    def test_edges_carry_resolved_titles(self):
        graph = build_quest_graph(GAME_DIR or '', gamedata.DisplayNames.load())
        titled = [e for e in graph.edges if e.quest_title]
        assert len(titled) > 100


class TestBuildQuestOutlook:
    def _graph(self):
        return QuestGraph(
            [
                Edge(
                    'State',
                    'point_of_no_return',
                    'Act2_PONR_g',
                    'HAG_HagSpawn',
                    'ReachedNoReturn',
                    terminal=True,
                    trigger_label='Act2_PONR',
                    quest_title='Save Mayrina',
                ),
                Edge(
                    'State',
                    'point_of_no_return',
                    'Act2_PONR_g',
                    'CHA_Chapel',
                    'LeftRegion',
                    terminal=True,
                    trigger_label='Act2_PONR',
                    quest_title='Explore the Ruins',
                ),
                Edge(
                    'LevelLoaded',
                    'region_enter',
                    'BGO',
                    'OTHER',
                    'Step',
                    terminal=False,
                    trigger_label='entering BGO',
                ),
            ]
        )

    def _quests(self):
        return {
            'active': [
                {'id': 'HAG_HagSpawn', 'name': 'Save Mayrina', 'objective': 'Defeat the hag'},
                {'id': 'CHA_Chapel', 'name': 'Explore the Ruins', 'objective': 'Look around'},
                {'id': 'OTHER', 'name': 'Other', 'objective': 'x'},
            ]
        }

    def test_lists_only_quests_with_terminating_triggers(self):
        out = build_quest_outlook(self._quests(), self._graph())
        titles = {q['title'] for q in out['active_quests']}
        assert titles == {'Save Mayrina', 'Explore the Ruins'}  # OTHER has no terminal edge

    def test_groups_point_of_no_return(self):
        out = build_quest_outlook(self._quests(), self._graph())
        groups = out['point_of_no_return_groups']
        assert len(groups) == 1
        assert groups[0]['trigger'] == 'Act2_PONR'
        assert set(groups[0]['closes']) == {'Save Mayrina', 'Explore the Ruins'}

    def test_quest_carries_objective_and_trigger_detail(self):
        out = build_quest_outlook(self._quests(), self._graph())
        mayrina = next(q for q in out['active_quests'] if q['title'] == 'Save Mayrina')
        assert mayrina['current_objective'] == 'Defeat the hag'
        trig = mayrina['terminating_triggers'][0]
        assert trig['result'] == 'closes'
        assert trig['trigger_kind'] == 'point_of_no_return'
        assert trig['trigger'] == 'Act2_PONR'
