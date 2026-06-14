"""Quest dependency graph: the game's DB_QuestDef_* quest interaction tables.

Built on demand from the local game install (the Osiris goal scripts that ship
as readable source under Story/RawFiles/Goals/*.txt), so an agent can answer
"which quests should I prioritise" with grounded facts. See
docs/superpowers/specs/2026-06-13-quest-dependency-graph-design.md.
"""

import os
import re
from dataclasses import dataclass

from . import lsx
from .gamedata import DisplayNames
from .lspk import lspk_extract_many


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


@dataclass
class StepInfo:
    """A quest step's journal objective and its terminal marker.

    unlock_disable == 2 marks a quest-closing step (live progression steps are
    0, gated steps 1).
    """

    objective_id: str
    unlock_disable: int


@dataclass
class QuestGraph:
    """The full set of normalised, enriched quest interaction edges."""

    edges: list[Edge]

    def terminating_edges_for(self, quest_id: str) -> list[Edge]:
        """Edges that close (move to a terminal step) the given quest."""
        return [e for e in self.edges if e.quest_id == quest_id and e.terminal]

    def edges_for(self, quest_id: str) -> list[Edge]:
        """Every edge whose target or quest-chain source is this quest."""
        return [e for e in self.edges if e.quest_id == quest_id or e.source_quest == quest_id]


def parse_quest_steps(lsx_text: str) -> dict[tuple[str, str], StepInfo]:
    """Map (quest_id, step_id) -> StepInfo from quest_prototypes.lsx.

    Each QuestStep is read from inside its enclosing Quest node, so the step is
    attributed to the right quest regardless of how the document nests them.
    """
    out: dict[tuple[str, str], StepInfo] = {}
    root = lsx.parse(lsx_text)
    for quest in lsx.iter_nodes(root, 'Quest'):
        quest_id = lsx.attrs(quest).get('QuestID')
        if not quest_id:
            continue
        for step in lsx.iter_nodes(quest, 'QuestStep'):
            a = lsx.attrs(step)
            step_id = a.get('ID')
            if not step_id:
                continue
            out[(quest_id, step_id)] = StepInfo(
                objective_id=a.get('Objective') or '',
                unlock_disable=int(a.get('UnlockDisable') or 0),
            )
    return out


GUID_SUFFIX_RE = re.compile(
    r'_[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
)


def strip_guid(token: str) -> str:
    """Drop a trailing _<guid> from a name+guid token."""
    return GUID_SUFFIX_RE.sub('', token)


def entity_name(token: str) -> str:
    """Readable name from an S_<name>_<guid> entity token (e.g. 'HAG_Hag')."""
    name = strip_guid(token)
    return name[2:] if name.startswith('S_') else name


def trigger_label(edge: Edge) -> str:
    """A human description of what fires this edge, for the agent to phrase."""
    k = edge.trigger_kind
    if k in ('point_of_no_return', 'flag'):
        return strip_guid(edge.trigger_ref)
    if k == 'region_enter':
        return f'entering {edge.trigger_ref}'
    if k == 'region_leave':
        return f'leaving {edge.trigger_ref}'
    if k == 'npc_death':
        return f'{entity_name(edge.trigger_ref)} dies'
    if k == 'npc_defeated':
        return f'{entity_name(edge.trigger_ref)} is defeated'
    if k == 'book_read':
        return f'reading {entity_name(edge.trigger_ref)}'
    if k == 'companion_left':
        return f'companion leaves: {strip_guid(edge.trigger_ref)}'
    if k == 'quest_chain':
        return f'{edge.source_quest} progresses'
    return 'a story condition'


def enrich_edge(
    edge: Edge, step_index: dict[tuple[str, str], StepInfo], names: DisplayNames
) -> Edge:
    """Fill an edge's terminal flag, journal text, quest title, and trigger label."""
    info = step_index.get((edge.quest_id, edge.target_step))
    edge.terminal = bool(info and info.unlock_disable == 2)
    if info and info.objective_id:
        # COMPLETION objectives often resolve to empty text; treat that as absent.
        edge.target_objective_text = names.quest_objective_for(info.objective_id) or None
    edge.quest_title = names.quest_name_for(edge.quest_id)
    edge.trigger_label = trigger_label(edge)
    if edge.trigger_kind == 'quest_chain' and edge.source_quest:
        src_title = names.quest_name_for(edge.source_quest)
        if src_title:
            edge.trigger_label = f'{src_title} progresses'
    return edge


def normalize_edge(stmt: QuestDefStmt) -> Edge | None:
    """Turn a parsed DB_QuestDef_* statement into a structural Edge."""
    a = stmt.args
    if stmt.kind in STATE_KINDS:
        if len(a) < 3:
            return None
        trigger, quest, step = a[0], a[1], a[2]
        if stmt.kind == 'State_CompanionLeft':
            trigger_kind = 'companion_left'
        elif 'PointOfNoReturn' in trigger:
            trigger_kind = 'point_of_no_return'
        else:
            trigger_kind = 'flag'
        return Edge(stmt.kind, trigger_kind, trigger, quest, step)
    if stmt.kind in QUEST_FIRST_KINDS:
        if len(a) < 2:
            return None
        trigger = a[2] if len(a) > 2 else ''
        return Edge(stmt.kind, QUEST_FIRST_KINDS[stmt.kind], trigger, a[0], a[1])
    if stmt.kind == 'ChainedState':
        # 4-arg form is cross-quest (srcQ, srcStep, dstQ, dstStep); the 3-arg
        # form chains within one quest (quest, srcStep, dstStep).
        if len(a) == 4:
            src_q, src_s, dst_q, dst_s = a[0], a[1], a[2], a[3]
        elif len(a) == 3:
            src_q, src_s, dst_q, dst_s = a[0], a[1], a[0], a[2]
        else:
            return None
        return Edge(
            stmt.kind,
            'quest_chain',
            f'{src_q}/{src_s}',
            quest_id=dst_q,
            target_step=dst_s,
            source_quest=src_q,
            source_step=src_s,
        )
    if stmt.kind == 'ConditionalState':
        if len(a) < 2:
            return None
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


GOALS_PATH_RE = re.compile(r'Story/RawFiles/Goals/.*\.txt$', re.IGNORECASE)
QUEST_PROTOTYPES_PATH = 'Mods/GustavDev/Story/Journal/quest_prototypes.lsx'


def build_quest_graph(data_dir: str, names: DisplayNames | None = None) -> QuestGraph:
    """Build the quest interaction graph from the local install's Gustav.pak.

    Reads the Osiris goal scripts (the DB_QuestDef_* edges) and the quest
    prototypes (step -> objective / terminal marker) in a single pak open, then
    enriches each edge with resolved titles and journal text.
    """
    names = names or DisplayNames.load()
    pak = os.path.join(data_dir, 'Gustav.pak')

    def wanted(name: str) -> bool:
        return name == QUEST_PROTOTYPES_PATH or bool(GOALS_PATH_RE.search(name))

    files = lspk_extract_many(pak, wanted)

    step_index: dict[tuple[str, str], StepInfo] = {}
    proto = files.get(QUEST_PROTOTYPES_PATH)
    if proto:
        step_index = parse_quest_steps(proto.decode('utf-8', 'replace'))

    edges: list[Edge] = []
    seen: set[tuple] = set()
    for name, data in files.items():
        if not GOALS_PATH_RE.search(name):
            continue
        for stmt in parse_questdef_statements(data.decode('latin1', 'replace')):
            edge = normalize_edge(stmt)
            if edge is None:
                continue
            key = (
                edge.kind,
                edge.trigger_ref,
                edge.quest_id,
                edge.target_step,
                edge.source_quest,
                edge.source_step,
            )
            if key in seen:
                continue
            seen.add(key)
            edges.append(enrich_edge(edge, step_index, names))
    return QuestGraph(edges)


def build_quest_outlook(quests: dict, graph: QuestGraph) -> dict:
    """Join a save's active quests to the graph: what will close each, and why.

    `quests` is a SaveReport.quests dict (its 'active' list carries each quest's
    id, name, and current objective). Only quests with at least one terminating
    trigger are returned (those are the ones worth prioritising); point-of-no-
    return triggers are also rolled up into groups.
    """
    active = quests.get('active', []) if quests else []
    out_quests: list[dict] = []
    ponr: dict[str, list[str]] = {}
    for q in active:
        qid = q.get('id')
        title = q.get('name') or qid
        triggers: list[dict] = []
        seen: set[tuple] = set()
        for edge in graph.terminating_edges_for(qid):
            key = (edge.trigger_kind, edge.trigger_label)
            if key in seen:
                continue
            seen.add(key)
            trigger = {
                'trigger_kind': edge.trigger_kind,
                'trigger': edge.trigger_label,
                'result': 'closes',
            }
            if edge.target_objective_text:
                trigger['result_text'] = edge.target_objective_text
            triggers.append(trigger)
            if edge.trigger_kind == 'point_of_no_return':
                ponr.setdefault(edge.trigger_label or '', []).append(title)
        if triggers:
            out_quests.append(
                {
                    'id': qid,
                    'title': title,
                    'current_objective': q.get('objective'),
                    'terminating_triggers': triggers,
                }
            )
    groups = [
        {'trigger': trig, 'closes': sorted(set(titles))} for trig, titles in sorted(ponr.items())
    ]
    return {
        'active_quests': out_quests,
        'point_of_no_return_groups': groups,
        'active_total': len(active),
    }
