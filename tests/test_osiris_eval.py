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

    def test_consequences_returns_only_the_caused_delta(self):
        # baseline context (the tracked prisoner) is matchable but not echoed;
        # only what the injected cause derives is returned.
        rules = parse_rules(PROGRAM)
        engine = Engine(rules)
        delta = engine.consequences(
            {Fact('Event', ('free_ns',))},
            {Fact('DB_Tracked', ('tief', 'HAV'))},
        )
        assert Fact('QuestUpdate', ('HAV', 'Failed')) in delta
        assert Fact('DB_Tracked', ('tief', 'HAV')) not in delta  # context not echoed

    def test_builtin_die_emits_died_event(self):
        # Die fires the Died event; here Died closes a quest, so the chain is
        # quest-relevant and survives pruning.
        prog = 'KBSECTION\nIF\nDied(_c)\nTHEN\nQuestUpdate("Q", "Dead");\nEXITSECTION\n'
        engine = Engine(parse_rules(prog))
        delta = engine.derive({Fact('Die', ('bob', 'DEATHTYPE.DoT', '1'))})
        assert Fact('QuestUpdate', ('Q', 'Dead')) in delta


class TestFactsFromDatabases:
    def test_converts_db_rows_to_ground_facts(self):
        from bg3parser.osiris_eval import facts_from_databases

        name_to_facts = {
            'DB_QuestIsClosed': [[{'is_valid': True, 'value': 'HAV_Save'}]],
            'DB_Tracked': [
                [{'is_valid': True, 'value': 'tief'}, {'is_valid': True, 'value': 1}],
            ],
        }
        facts = facts_from_databases(name_to_facts)
        assert Fact('DB_QuestIsClosed', ('HAV_Save',)) in facts
        assert Fact('DB_Tracked', ('tief', '1')) in facts  # ints stringified, arity kept
