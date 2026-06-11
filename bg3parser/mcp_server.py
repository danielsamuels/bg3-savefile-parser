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
from .gamedata import DisplayNames
from .model import SaveReport, gather_report
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
        'and chest gold is summed into a gold field.'
    ),
)

display_names: DisplayNames | None = None


def shared_display_names() -> DisplayNames:
    """The DisplayNames table, loaded once per server process."""
    global display_names
    if display_names is None:
        display_names = DisplayNames.load()
    return display_names


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
) -> dict:
    """Parse a BG3 save and return a report as JSON.

    `save` is 'latest' (most recently modified save), a save number ('286'),
    a save name ('QuickSave_286'), or an absolute .lsv path.

    `sections` picks what to report (default: all of meta, party, camp,
    camp_chest, quests).

    `detail` shapes characters: 'summary' (default) gives race/class/level,
    ability scores, HP, worn gear keyed by slot (null = empty slot, so an
    open ring slot is visible), carried items, gold, and prepared spell
    names; 'full' adds the complete spell book with prepared flags, action
    resources, feats, XP, and internal IDs.

    `items` filters carried and camp-chest items: 'magic' (equippable with
    above-common rarity), 'equipment' (anything equippable), or 'all'
    (default; includes consumables and junk).

    `quests` is 'active' (default), 'all' (adds closed quest names), or
    'none'. Quest parsing costs ~2s; 'none' skips it.
    """
    section_list = tuple(sections) if sections else SECTIONS
    for s in section_list:
        validate_choice(s, SECTIONS, 'sections')
    validate_choice(detail, DETAIL_LEVELS, 'detail')
    validate_choice(items, ITEM_FILTERS, 'items')
    if isinstance(quests, bool):  # the pre-filter API
        quests = 'active' if quests else 'none'
    validate_choice(quests, QUEST_FILTERS, 'quests')

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
    gather_quests = 'quests' in section_list and quests != 'none'
    report = cached_report(path, gather_quests)
    return save_view(report, shared_display_names(), section_list, detail, items, quests)


def main() -> None:
    server.run()


if __name__ == '__main__':
    main()
