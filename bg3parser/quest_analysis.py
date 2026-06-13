"""Quest cause-and-effect analyser.

Ties the pieces together: load the game's Osiris rules (Shared + Gustav goal
scripts), seed the argument-aware engine with a save's live story facts, inject
a candidate player action, and read off which quests it would change. Unlike the
declarative DB_QuestDef graph (which only sees edges the designers wrote
explicitly), this evaluates the actual rules, so it catches emergent imperative
consequences (e.g. freeing the Nightsong -> the assault purges the prison ->
the tracked prisoners die -> the rescue quests fail).

Needs a local game install (the rules are read from the paks).
"""

import os
import re
from dataclasses import dataclass

from .gamedata import find_game_data_dir
from .lspk import lspk_extract_many
from .osiris_eval import Engine
from .osiris_rules import parse_rules

GOAL_PAKS = ('Shared.pak', 'Gustav.pak', 'GustavX.pak')
GOALS_PATH_RE = re.compile(r'Story/RawFiles/Goals/.*\.txt$', re.IGNORECASE)


def load_rules(data_dir: str) -> list:
    """Parse every goal-script rule from the install's goal paks."""
    rules: list = []
    for pak in GOAL_PAKS:
        path = os.path.join(data_dir, pak)
        if not os.path.exists(path):
            continue
        files = lspk_extract_many(path, lambda n: bool(GOALS_PATH_RE.search(n)))
        for name, data in files.items():
            rules += parse_rules(data.decode('latin1', 'replace'), name)
    return rules


def quest_outcomes(delta) -> set:
    """Pull (quest_id, step) pairs out of derived QuestUpdate/QuestClose facts.

    QuestUpdate is written both as (quest, step) and (character, quest, step);
    either way the quest and step are the last two args. QuestClose(quest) marks
    a closed quest.
    """
    out = set()
    for f in delta:
        if f.pred == 'QuestUpdate' and len(f.args) >= 2:
            out.add((f.args[-2], f.args[-1]))
        elif f.pred == 'QuestClose' and f.args:
            out.add((f.args[0], 'closed'))
    return out


@dataclass
class QuestAnalyser:
    """Holds the parsed rule engine; answers cause-effect queries per save."""

    engine: Engine

    @classmethod
    def load(cls, data_dir: str | None = None) -> 'QuestAnalyser':
        data_dir = data_dir or find_game_data_dir()
        if not data_dir:
            raise RuntimeError('no game install found to load the quest rules')
        return cls(Engine(load_rules(data_dir)))

    def consequences(self, baseline_facts, cause_facts) -> set:
        """The (quest_id, step) outcomes an injected cause produces on a save.

        `baseline_facts` is the save's live story database (matchable context);
        `cause_facts` is the hypothetical player action. Returns the quest
        outcomes newly reachable because of the cause.
        """
        delta = self.engine.consequences(set(cause_facts), baseline_facts)
        return quest_outcomes(delta)


def named_consequences(outcomes, active_quests, names, step_index) -> list:
    """Shape raw (quest_id, step) outcomes into a save-scoped, readable report.

    Keeps only quests the player currently has open (`active_quests`), resolves
    each quest's title (`names.quest_name_for`), and marks whether the step is
    terminal (closes the quest) using the quest prototypes' UnlockDisable. Any
    of `active_quests` / `names` / `step_index` may be None to skip that step.
    """
    results = []
    for quest, step in sorted(outcomes):
        if active_quests is not None and quest not in active_quests:
            continue
        info = step_index.get((quest, step)) if step_index else None
        results.append(
            {
                'quest_id': quest,
                'title': (names.quest_name_for(quest) if names else None) or quest,
                'step': step,
                'terminal': bool(info and info.unlock_disable == 2),
            }
        )
    return results
