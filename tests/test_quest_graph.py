"""Tests for the quest dependency graph (bg3parser.quest_graph).

The edge parser is a pure function over Osiris goal-script text, so it runs in
CI with no game install. Graph-build tests that touch the paks are gated on a
local install, mirroring the gamedata tests.
"""

from bg3parser.quest_graph import (
    QuestDefStmt,
    normalize_edge,
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

    def test_unknown_kind_returns_none(self):
        assert normalize_edge(QuestDefStmt('SomethingElse', ['a', 'b'])) is None
