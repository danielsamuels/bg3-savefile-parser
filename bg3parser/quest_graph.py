"""Quest dependency graph: the game's DB_QuestDef_* quest interaction tables.

Built on demand from the local game install (the Osiris goal scripts that ship
as readable source under Story/RawFiles/Goals/*.txt), so an agent can answer
"which quests should I prioritise" with grounded facts. See
docs/superpowers/specs/2026-06-13-quest-dependency-graph-design.md.
"""

import re
from dataclasses import dataclass


@dataclass
class QuestDefStmt:
    """One parsed DB_QuestDef_* statement: its kind suffix and cleaned args."""

    kind: str
    args: list[str]


@dataclass
class Edge:
    """A normalised quest interaction: a trigger that drives a quest to a step.

    Structural fields are filled by normalize_edge; the label/title/objective
    text and the terminal flag are enriched at build time from the loca map and
    the quest prototypes.
    """

    kind: str  # raw DB_QuestDef_* suffix
    trigger_kind: str  # point_of_no_return | flag | companion_left | region_enter
    # | region_leave | npc_death | npc_defeated | book_read | quest_chain | conditional
    trigger_ref: str  # raw trigger token (flag/tag name, region id, S_<entity> token)
    quest_id: str  # the quest this edge drives (the target)
    target_step: str
    source_quest: str | None = None  # quest_chain only: the upstream quest
    source_step: str | None = None
    # enriched at build time:
    trigger_label: str | None = None
    quest_title: str | None = None
    target_objective_text: str | None = None
    terminal: bool | None = None


# Trigger-first kinds carry args [trigger, quest, step, ...]; every other kind
# carries [quest, step, trigger, ...]. ChainedState and ConditionalState are
# handled specially.
STATE_KINDS = {'State', 'State_ConditionalFlag', 'State_CompanionLeft'}

# Quest-first kinds: args [quest, step, trigger, ...]. Value is the trigger_kind.
QUEST_FIRST_KINDS = {
    'LevelLoaded': 'region_enter',
    'LevelUnloading': 'region_leave',
    'SawDeadState': 'npc_death',
    'DefeatedState': 'npc_defeated',
    'PermaDefeatedState': 'npc_defeated',
    'SawDefeatedState': 'npc_defeated',
    'SawPermaDefeatedState': 'npc_defeated',
    'BookReadState': 'book_read',
}


def normalize_edge(stmt: QuestDefStmt) -> Edge | None:
    """Turn a parsed DB_QuestDef_* statement into a structural Edge."""
    a = stmt.args
    if stmt.kind in STATE_KINDS:
        trigger, quest, step = a[0], a[1], a[2]
        if stmt.kind == 'State_CompanionLeft':
            trigger_kind = 'companion_left'
        elif 'PointOfNoReturn' in trigger:
            trigger_kind = 'point_of_no_return'
        else:
            trigger_kind = 'flag'
        return Edge(stmt.kind, trigger_kind, trigger, quest, step)
    if stmt.kind in QUEST_FIRST_KINDS:
        trigger = a[2] if len(a) > 2 else ''
        return Edge(stmt.kind, QUEST_FIRST_KINDS[stmt.kind], trigger, a[0], a[1])
    if stmt.kind == 'ChainedState':
        return Edge(
            stmt.kind,
            'quest_chain',
            f'{a[0]}/{a[1]}',
            quest_id=a[2],
            target_step=a[3],
            source_quest=a[0],
            source_step=a[1],
        )
    if stmt.kind == 'ConditionalState':
        return Edge(stmt.kind, 'conditional', ' '.join(a[2:]), a[0], a[1])
    return None


# A DB_QuestDef_* statement ends in `);`. Argument casts like (FLAG), (ITEM),
# (CHARACTER) carry their own parens but no commas, so anchoring on the trailing
# `);` (DOTALL, for multi-line statements) avoids truncating at a cast.
STATEMENT_RE = re.compile(r'DB_QuestDef_(\w+)\((.*?)\);', re.DOTALL)
CAST_RE = re.compile(r'^\([A-Z]+\)')
LINE_COMMENT_RE = re.compile(r'//[^\n]*')


def clean_arg(arg: str) -> str:
    """Strip whitespace, a leading type cast, and surrounding quotes."""
    arg = CAST_RE.sub('', arg.strip())
    if len(arg) >= 2 and arg[0] == '"' and arg[-1] == '"':
        arg = arg[1:-1]
    return arg


def parse_questdef_statements(text: str) -> list[QuestDefStmt]:
    """Parse all DB_QuestDef_* statements out of Osiris goal-script text."""
    text = LINE_COMMENT_RE.sub('', text)
    out = []
    for kind, raw_args in STATEMENT_RE.findall(text):
        args = [clean_arg(a) for a in raw_args.split(',')]
        out.append(QuestDefStmt(kind=kind, args=args))
    return out
