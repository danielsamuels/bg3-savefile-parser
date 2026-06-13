"""Tests for the quest dependency graph (bg3parser.quest_graph).

The edge parser is a pure function over Osiris goal-script text, so it runs in
CI with no game install. Graph-build tests that touch the paks are gated on a
local install, mirroring the gamedata tests.
"""

from bg3parser.quest_graph import parse_questdef_statements


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
