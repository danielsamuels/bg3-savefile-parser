"""Tests for the faithful Osiris rule parser (bg3parser.osiris_rules).

Pure parser over the goal-script KBSECTION rules, so it runs in CI with no game
install. Captures variables, casts, negation, comparisons, and actions, which
the argument-aware evaluator needs (the spike's name-only parser was too lossy).
"""

from bg3parser.osiris_rules import Const, Var, parse_rules


class TestParseRules:
    def test_parses_conditions_and_actions_with_vars_and_retract(self):
        text = """KBSECTION
IF
DB_DEBUG_AssaultLoaded(1)
AND
DB_DEBUG_ReadyNightsong(1)
THEN
NOT DB_DEBUG_ReadyNightsong(1);
PROC_NightsongPrison_FreeNightsong();
EXITSECTION
"""
        rules = parse_rules(text)
        assert len(rules) == 1
        r = rules[0]
        assert r.kind == 'IF'
        # trigger is the first condition
        assert r.trigger.pred == 'DB_DEBUG_AssaultLoaded'
        assert r.trigger.args == (Const('1', None),)
        assert len(r.conditions) == 2
        assert [c.atom.pred for c in r.conditions] == [
            'DB_DEBUG_AssaultLoaded',
            'DB_DEBUG_ReadyNightsong',
        ]
        assert all(not c.negated for c in r.conditions)
        # actions: a retraction then a proc call
        assert len(r.actions) == 2
        assert r.actions[0].retract is True
        assert r.actions[0].atom.pred == 'DB_DEBUG_ReadyNightsong'
        assert r.actions[1].retract is False
        assert r.actions[1].atom.pred == 'PROC_NightsongPrison_FreeNightsong'
        assert r.actions[1].atom.args == ()

    def test_parses_casts_variables_and_anonymous_wildcard(self):
        text = """KBSECTION
IF
DB_Positions((CHARACTER)_Char,(TRIGGER)_, "MOO_Bazaar")
THEN
PROC_SetFactions(_Char, "MOO_Bazaar");
EXITSECTION
"""
        r = parse_rules(text)[0]
        args = r.trigger.args
        assert args[0] == Var('_Char')  # cast stripped, variable kept
        assert args[1] == Var('_')  # anonymous wildcard
        assert args[2] == Const('MOO_Bazaar', None)  # string literal, quotes stripped

    def test_parses_negation_and_comparison_conditions(self):
        text = """KBSECTION
IF
TextEvent("clear")
AND
_Group != "RooftopEnemies"
AND
NOT DB_State_Current(_x, "MOO", "Assault")
THEN
Die(_Char);
EXITSECTION
"""
        r = parse_rules(text)[0]
        # the comparison condition
        comp = [c for c in r.conditions if c.comparison is not None]
        assert len(comp) == 1
        left, op, right = comp[0].comparison
        assert left == Var('_Group')
        assert op == '!='
        assert right == Const('RooftopEnemies', None)
        # the negated condition
        neg = [c for c in r.conditions if c.negated]
        assert len(neg) == 1
        assert neg[0].atom.pred == 'DB_State_Current'
