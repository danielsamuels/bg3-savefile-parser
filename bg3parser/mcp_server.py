"""MCP server: the parser as assistant tools.

Lets an MCP client (Claude Code, Claude Desktop, ...) ask questions like
"is there better gear in my bags?" or "what should I do next?" by parsing
a save on demand and handing the model the full report.

Run with the `mcp` extra installed:

    uv run --extra mcp bg3save-mcp
"""

import dataclasses
import datetime
import os
from argparse import Namespace

from mcp.server.fastmcp import FastMCP

from .discovery import candidate_profile_dirs, find_latest_save, find_save_by_token, glob_saves
from .model import gather_report

server = FastMCP(
    'bg3save',
    instructions=(
        "Read-only tools over local Baldur's Gate 3 save files. parse_save "
        'returns the full report: save metadata, party characters (gear in '
        'slot order, carried inventory, exact spell books with prepared '
        'flags), camp companions, the camp chest, and the quest log with '
        'current objectives. Counts on carried items are stack totals; gold '
        'stacks are items with stats OBJ_GoldCoin/OBJ_GoldPile.'
    ),
)


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
def parse_save(save: str = 'latest', quests: bool = True) -> dict:
    """Parse a BG3 save and return the full report as JSON.

    `save` is 'latest' (most recently modified save), a save number ('286'),
    a save name ('QuickSave_286'), or an absolute .lsv path. Quest parsing
    adds the quest log with current objectives and costs ~2s; pass
    quests=False to skip it.
    """
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
    report = gather_report(path, opts=Namespace(quests=quests))
    return dataclasses.asdict(report)


def main() -> None:
    server.run()


if __name__ == '__main__':
    main()
