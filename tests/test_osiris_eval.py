"""Tests for the argument-aware Osiris evaluator (bg3parser.osiris_eval).

Forward-chaining over the parsed rules with real variable binding, so a cause
propagates to an effect only when the arguments actually thread through (the
spike's name-matching connected 83% of quest outcomes to any event; binding is
what prunes that).
"""

from bg3parser.osiris_eval import Engine, Fact
from bg3parser.osiris_rules import parse_rules

# A synthetic program shaped like the real Nightsong -> rescue chain:
# an event fires a proc, the proc kills a tracked prisoner, and a rule with a
# variable join closes the quest that tracks THAT prisoner.
PROGRAM = """KBSECTION
IF
Event("free_ns")
THEN
PROC_Purge();

PROC
PROC_Purge()
THEN
DB_PrisonerDead("tief");

IF
DB_PrisonerDead(_g)
AND
DB_Tracked(_g, _quest)
THEN
QuestUpdate(_quest, "Failed");

IF
DB_PrisonerDead("someone_else")
THEN
QuestUpdate("UNRELATED", "Failed");
EXITSECTION
"""


class TestEngine:
    def test_cause_propagates_through_proc_and_variable_join(self):
        rules = parse_rules(PROGRAM)
        engine = Engine(rules)
        facts = engine.derive({Fact('Event', ('free_ns',)), Fact('DB_Tracked', ('tief', 'HAV'))})
        # the quest that tracks the dead prisoner closes
        assert Fact('QuestUpdate', ('HAV', 'Failed')) in facts

    def test_constant_mismatch_does_not_fire(self):
        # the UNRELATED quest keys off a different prisoner constant, so even
        # though DB_PrisonerDead fires, the mismatch must block it.
        rules = parse_rules(PROGRAM)
        engine = Engine(rules)
        facts = engine.derive({Fact('Event', ('free_ns',)), Fact('DB_Tracked', ('tief', 'HAV'))})
        assert Fact('QuestUpdate', ('UNRELATED', 'Failed')) not in facts

    def test_no_cause_no_effect(self):
        # without the triggering event, the chain never starts
        rules = parse_rules(PROGRAM)
        engine = Engine(rules)
        facts = engine.derive({Fact('DB_Tracked', ('tief', 'HAV'))})
        assert not any(f.pred == 'QuestUpdate' for f in facts)
