"""MCP server: the parser as assistant tools.

Lets an MCP client (Claude Code, Claude Desktop, ...) ask questions like
"is there better gear in my bags?" or "what should I do next?" by parsing
a save on demand and handing the model a report sized to the question
(see report_views). Parsed saves are cached in-process, so follow-up
calls about the same save return instantly.

Run with the `mcp` extra installed:

    uv run --extra mcp bg3save-mcp
"""

import datetime
import os
from argparse import Namespace

from mcp.server.fastmcp import FastMCP

from .discovery import candidate_profile_dirs, find_latest_save, find_save_by_token, glob_saves
from .effects import Effects
from .gamedata import DisplayNames, find_game_data_dir
from .lspk import extract_frames, lspk_extract
from .model import SaveReport, gather_report
from .osiris import read_story
from .osiris_eval import Fact, facts_from_databases
from .quest_analysis import QuestAnalyser, named_consequences
from .quest_graph import (
    QUEST_PROTOTYPES_PATH,
    QuestGraph,
    build_quest_graph,
    build_quest_outlook,
    parse_quest_steps,
)
from .report_views import (
    DETAIL_LEVELS,
    ITEM_FILTERS,
    QUEST_FILTERS,
    SECTIONS,
    save_view,
    validate_choice,
)

server = FastMCP(
    'bg3save',
    instructions=(
        "Read-only tools over local Baldur's Gate 3 save files. parse_save "
        'returns a report: save metadata, party characters (abilities, HP, '
        'worn gear keyed by slot with empty slots as null, carried items, '
        'prepared spells), camp companions, the camp chest, and active '
        'quests with current objectives. The defaults fit one tool result; '
        'narrow with sections/items or deepen with detail="full" and '
        'quests="all". Items carry rarity (absent = common); per-character '
        'and chest gold is summed into a gold field. For gear advice, pass '
        'effects=true to annotate items with their tooltip text, or look up '
        'a specific item with item_info. quest_outlook flags which active '
        'quests an upcoming action (a point of no return, region change, or '
        'NPC death) would close, for "what should I prioritise" questions. '
        "quest_consequences goes deeper: it evaluates the game's actual Osiris "
        'rules against a save to derive emergent cause-and-effect that the '
        'explicit quest edges miss.'
    ),
)

display_names: DisplayNames | None = None
effects_table: Effects | None = None
quest_graph: QuestGraph | None = None


def shared_display_names() -> DisplayNames:
    """The DisplayNames table, loaded once per server process."""
    global display_names
    if display_names is None:
        display_names = DisplayNames.load()
    return display_names


def shared_quest_graph() -> QuestGraph | None:
    """The quest interaction graph, built once per server process.

    Needs a local game install (the graph is read from the paks); returns None
    when no install is found.
    """
    global quest_graph
    if quest_graph is None:
        data_dir = find_game_data_dir()
        if not data_dir:
            return None
        quest_graph = build_quest_graph(data_dir, shared_display_names())
    return quest_graph


quest_analyser: QuestAnalyser | None = None
quest_step_index: dict | None = None


def shared_quest_analyser() -> QuestAnalyser | None:
    """The Osiris rule engine analyser, built once per process (needs install)."""
    global quest_analyser
    if quest_analyser is None:
        data_dir = find_game_data_dir()
        if not data_dir:
            return None
        quest_analyser = QuestAnalyser.load(data_dir)
    return quest_analyser


def shared_quest_step_index() -> dict:
    """(quest_id, step) -> StepInfo from the quest prototypes, built once."""
    global quest_step_index
    if quest_step_index is None:
        data_dir = find_game_data_dir()
        if not data_dir:
            return {}
        data = lspk_extract(os.path.join(data_dir, 'Gustav.pak'), QUEST_PROTOTYPES_PATH)
        quest_step_index = parse_quest_steps(data.decode('utf-8', 'replace'))
    return quest_step_index


def resolve_save_path(save: str) -> str:
    """Resolve 'latest' / a save number / name / path to a save file path."""
    if save == 'latest':
        path = find_latest_save()
    elif os.path.isfile(save):
        path = save
    else:
        path = find_save_by_token(save)
    if path is None:
        raise FileNotFoundError(
            f'No save found for {save!r}. Use list_saves to see what exists, '
            'or set BG3_SAVE_DIR if the saves live somewhere unusual.'
        )
    return path


def shared_effects() -> Effects:
    """The item-effects table, loaded once per server process."""
    global effects_table
    if effects_table is None:
        effects_table = Effects.load()
    return effects_table


# Parsed-save cache: repeated parse_save calls against the same save (other
# sections, another detail level) skip the multi-second extraction. Keyed by
# path and fingerprinted on mtime+size so a fresh save under the same name
# (QuickSave overwrites) reparses. The view layer is pure, so one report
# serves every parameter combination; quests are the exception (gathering
# them is gated for cost), so a cached quest-less report is upgraded in
# place when a later call wants them.
parse_cache: dict[str, tuple[tuple[int, int], SaveReport]] = {}
PARSE_CACHE_MAX = 4


def cached_report(path: str, want_quests: bool) -> SaveReport:
    fingerprint = (os.stat(path).st_mtime_ns, os.path.getsize(path))
    hit = parse_cache.get(path)
    if hit is not None and hit[0] == fingerprint:
        report = hit[1]
        if not want_quests or report.quests is not None:
            parse_cache.pop(path)  # reinsert: keep recently used entries alive
            parse_cache[path] = (fingerprint, report)
            return report
    report = gather_report(path, opts=Namespace(quests=want_quests))
    parse_cache.pop(path, None)
    parse_cache[path] = (fingerprint, report)
    while len(parse_cache) > PARSE_CACHE_MAX:
        del parse_cache[next(iter(parse_cache))]
    return report


@server.tool()
def list_saves(limit: int = 20) -> list[dict]:
    """List local BG3 saves, newest first, with name, path, and modified time."""
    env = os.environ.get('BG3_SAVE_DIR')
    roots = [env] if env else candidate_profile_dirs()
    patterns = (
        '*/Savegames/Story/*/*.lsv',
        'Savegames/Story/*/*.lsv',
        'Story/*/*.lsv',
        '*/*.lsv',
        '*.lsv',
    )
    found = sorted(glob_saves(roots, patterns), key=os.path.getmtime, reverse=True)
    return [
        {
            'name': os.path.splitext(os.path.basename(p))[0],
            'path': p,
            'modified': datetime.datetime.fromtimestamp(
                os.path.getmtime(p), tz=datetime.UTC
            ).strftime('%Y-%m-%d %H:%M:%S UTC'),
        }
        for p in found[: max(1, limit)]
    ]


@server.tool()
def parse_save(
    save: str = 'latest',
    sections: list[str] | None = None,
    detail: str = 'summary',
    items: str = 'all',
    quests: str | bool = 'active',
    effects: bool = False,
) -> dict:
    """Parse a BG3 save and return a report as JSON.

    `save` is 'latest' (most recently modified save), a save number ('286'),
    a save name ('QuickSave_286'), or an absolute .lsv path.

    `sections` picks what to report (default: all of meta, party, camp,
    camp_chest, quests).

    `detail` shapes characters: 'summary' (default) gives race/class/level,
    XP, ability scores, HP, feats, worn gear keyed by slot (null = empty
    slot, so an open ring slot is visible), carried items, gold, and
    prepared spell names (mod macros and performances filtered out);
    'full' adds the complete spell book with prepared flags, action
    resources, and internal IDs — rarely needed for gear or build advice.

    `items` filters carried and camp-chest items: 'magic' (equippable with
    above-common rarity), 'equipment' (anything equippable), or 'all'
    (default; includes consumables and junk).

    `quests` is 'active' (default), 'all' (adds closed quest names), or
    'none'. Quest parsing costs ~2s; 'none' skips it.

    `effects=True` annotates items with their in-game tooltip text (passive
    names and descriptions, damage, AC, boost strings) — use it for gear
    advice instead of recalling item lore. Pairs well with items='magic'.
    """
    section_list = tuple(sections) if sections else SECTIONS
    for s in section_list:
        validate_choice(s, SECTIONS, 'sections')
    validate_choice(detail, DETAIL_LEVELS, 'detail')
    validate_choice(items, ITEM_FILTERS, 'items')
    if isinstance(quests, bool):  # the pre-filter API
        quests = 'active' if quests else 'none'
    validate_choice(quests, QUEST_FILTERS, 'quests')

    path = resolve_save_path(save)
    gather_quests = 'quests' in section_list and quests != 'none'
    report = cached_report(path, gather_quests)
    fx = shared_effects() if effects else None
    return save_view(report, shared_display_names(), section_list, detail, items, quests, fx)


@server.tool()
def item_info(names: str | list[str], limit_per_name: int = 8) -> dict[str, list[dict]]:
    """Look up items by display name and return their in-game effect text.

    `names` is one case-insensitive substring or a LIST of them — pass every
    item you are evaluating in a single call ('["hellrider", "spellsparkler",
    "caustic band"]') rather than calling once per item. Each query maps to
    its matches: slot, rarity, and tooltip lines (passives, damage, AC,
    boosts in plain English), straight from the installed game's data — the
    answer to "what does this item do", with no save parsing involved.
    Several entries can share one display name (each variant is returned).
    For a whole save's gear at once, parse_save(effects=true, items='magic')
    is usually the better shape.
    """
    dn = shared_display_names()
    fx = shared_effects()
    if not fx.available:
        raise RuntimeError(
            'No effects table: needs an installed game (BG3_DATA_DIR) or BG3_EFFECTS_JSON.'
        )
    queries = [names] if isinstance(names, str) else list(names)
    out: dict[str, list[dict]] = {q: [] for q in queries}
    for stats in fx.table:
        display = dn.name_for(stats) or stats
        hay = f'{display.lower()} {stats.lower()}'
        for q in queries:
            matches = out[q]
            if len(matches) >= max(1, limit_per_name) or q.strip().lower() not in hay:
                continue
            entry: dict = {'name': display, 'stats': stats, 'effects': fx.lines(stats)}
            slot = dn.stats_to_slot.get(stats)
            if slot:
                entry['slot'] = slot
            rarity = dn.rarity_for(stats)
            if rarity:
                entry['rarity'] = rarity
            matches.append(entry)
    return out


@server.tool()
def quest_outlook(save: str = 'latest') -> dict:
    """Which active quests will be closed by an upcoming action, and by what.

    Answers "are there quests I should prioritise?" with the game's own quest
    interaction graph (read from the installed game data, not model recall):
    for each active quest in the save, the triggers that will *close* it if you
    act before finishing it. Triggers are point-of-no-return story advances,
    entering or leaving a region, an NPC dying or being defeated, a companion
    leaving, or another quest progressing.

    Returns `active_quests` (only those with a closing trigger; each has its
    title, current objective, and `terminating_triggers` with a `trigger_kind`,
    a human `trigger` label, and optional `result_text`), a rolled-up
    `point_of_no_return_groups` (each point of no return and the quests it would
    close), and `active_total`. An empty `active_quests` means nothing in the
    log is at risk from a known trigger.

    `save` is 'latest', a save number ('286'), a name, or an absolute path.
    Needs a local game install to read the quest graph.
    """
    path = resolve_save_path(save)
    graph = shared_quest_graph()
    if graph is None:
        raise RuntimeError(
            'quest_outlook needs an installed game (set BG3_DATA_DIR if it is '
            'somewhere unusual) to read the quest interaction graph.'
        )
    report = cached_report(path, want_quests=True)
    if report.quests is None or report.quests.get('failed'):
        return {
            'active_quests': [],
            'point_of_no_return_groups': [],
            'active_total': 0,
            'note': 'no quest state could be read from this save',
        }
    return build_quest_outlook(report.quests, graph)


@server.tool()
def quest_consequences(action: str, save: str = 'latest') -> dict:
    """Determine which of your active quests an action would change or close.

    Unlike quest_outlook (which reads the designers' explicit DB_QuestDef edges),
    this *evaluates the game's actual Osiris rules* against your save: it seeds
    the rule engine with this save's live story state, injects the action, and
    forward-chains to see which quests it drives to a new step. That catches
    emergent consequences the explicit edges miss -- e.g. the Moonrise prison
    purge killing the tracked prisoners and failing the rescue quests.

    `action` is an Osiris action predicate: a proc or event, e.g.
    'PROC_MOO_Assault_PurgePrison'. Results are derived from the game files and
    this save, not model recall. Each affected quest gives its title, the step
    it moves to, and whether that step is terminal (closes the quest).

    `save` is 'latest', a save number, a name, or a path. Needs a game install.
    Slower than the other tools (it loads and evaluates the whole rule base).
    """
    analyser = shared_quest_analyser()
    if analyser is None:
        raise RuntimeError(
            'quest_consequences needs an installed game (set BG3_DATA_DIR if '
            'it is somewhere unusual) to read the Osiris rules.'
        )
    path = resolve_save_path(save)
    res = read_story(extract_frames(path))
    if res is None:
        return {'action': action, 'affected_quests': [], 'note': 'no story state in this save'}
    _ver, name_to_facts, _goals = res
    baseline = facts_from_databases(name_to_facts)
    report = cached_report(path, want_quests=True)
    active = None
    if report.quests and not report.quests.get('failed'):
        active = {q['id'] for q in report.quests.get('active', [])}
    outcomes = analyser.consequences(baseline, {Fact(action, ())})
    affected = named_consequences(
        outcomes, active, shared_display_names(), shared_quest_step_index()
    )
    return {'action': action, 'affected_quests': affected}


def main() -> None:
    server.run()


if __name__ == '__main__':
    main()
