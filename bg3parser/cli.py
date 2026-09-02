"""Command-line entry point."""

import argparse
import os
import sys

from . import sections
from .discovery import find_latest_save, find_save_by_token
from .lspk import extract_frames, extract_thumbnail
from .model import gather_report
from .render import render_json, render_text
from .telemetry import render_telemetry_v1

# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description='Extract character info from a BG3 .lsv save file.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            'Every section is opt-in. With no group flag, a short header is\n'
            'printed (save summary and active party) plus this hint.\n'
            '\n'
            'Shortcuts:\n'
            '  --party   active party identity, gear, and spells (the classic report)\n'
            '  --all     every section, including the slower ones\n'
            '\n'
            'Active party: --characters --equipment --spells --carried\n'
            'Camp:         --camp-characters --camp-equipment --camp-spells\n'
            '              --camp-carried --camp-chest\n'
            'Top level:    --save-info --quests --vendors --all-items --limits\n'
        ),
    )
    ap.add_argument(
        'save', nargs='?', metavar='save.lsv', help='path to save file (auto-detected if omitted)'
    )
    ap.add_argument(
        'output', nargs='?', metavar='output.txt', help='write report to file (default: stdout)'
    )

    # Shortcuts.
    ap.add_argument('--party', action='store_true', help='= --characters --equipment --spells')
    ap.add_argument('--all', action='store_true', help='turn on every section (slower)')

    # Active party (per-character).
    ap.add_argument(
        '--characters', action='store_true', help='party identity (race, class, level, …)'
    )
    ap.add_argument('--equipment', action='store_true', help='party worn gear')
    ap.add_argument('--spells', action='store_true', help='party spell books')
    ap.add_argument('--carried', action='store_true', help='party carried inventory')

    # Camp.
    ap.add_argument('--camp-characters', action='store_true', help='camp companion identity')
    ap.add_argument('--camp-equipment', action='store_true', help='camp companion worn gear')
    ap.add_argument('--camp-spells', action='store_true', help='camp companion spell books')
    ap.add_argument('--camp-carried', action='store_true', help='camp companion carried inventory')
    ap.add_argument('--camp-chest', action='store_true', help='camp chest contents')

    # Top level.
    ap.add_argument('--save-info', action='store_true', help='save metadata (name, date, mods, …)')
    ap.add_argument(
        '--quests', action='store_true', help='quest and story state (Osiris; adds ~1-2 s)'
    )
    ap.add_argument(
        '--vendors',
        action='store_true',
        help="every merchant's for-sale stock (items generated and not yet bought)",
    )
    ap.add_argument('--all-items', action='store_true', help='full item list for the current level')
    ap.add_argument('--limits', action='store_true', help='known limitations note')

    # Modifiers (unchanged).
    ap.add_argument(
        '--verbose',
        '-v',
        action='store_true',
        help='show internal names in parentheses after display names',
    )
    ap.add_argument(
        '--thumbnail', '-t', metavar='PATH', help="write the save's thumbnail image to PATH"
    )
    ap.add_argument(
        '--inspect',
        metavar='NAME',
        help='show classification signals and ECS components for party items '
        'whose internal stats name contains NAME (case-insensitive)',
    )
    ap.add_argument(
        '--all-spells',
        action='store_true',
        help='within --spells, list sub-spells and basic actions instead of folding them away',
    )
    ap.add_argument(
        '--json',
        action='store_true',
        help='emit the report as JSON (machine-readable; includes everything gathered)',
    )
    ap.add_argument(
        '--telemetry-json',
        nargs='?',
        const='-',
        metavar='PATH',
        help='emit Telemetry Schema v1 JSON, or also write it to PATH while rendering the report',
    )
    return ap


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    ap = build_parser()
    opts = ap.parse_args()
    sections.expand_shortcuts(opts)

    save_path = opts.save
    if not save_path:
        save_path = find_latest_save()
        if not save_path:
            ap.error('no save given and none auto-detected; pass a .lsv path or set BG3_SAVE_DIR')
        print(f'No save specified; using most recent: {save_path}', file=sys.stderr)
    elif not os.path.exists(save_path):
        resolved = find_save_by_token(save_path)
        if not resolved:
            ap.error(f'no save found matching {save_path!r}')
        save_path = resolved
        print(f'Resolved {opts.save!r} → {save_path}', file=sys.stderr)

    frames = extract_frames(save_path)

    if opts.thumbnail:
        dims = extract_thumbnail(frames, opts.thumbnail)
        if dims:
            print(f'Thumbnail written to {opts.thumbnail} ({dims[0]}x{dims[1]})', file=sys.stderr)
        else:
            print(f'Thumbnail written to {opts.thumbnail} (dimensions unknown)', file=sys.stderr)

    print(f'Parsing {save_path} …', file=sys.stderr)
    model = gather_report(save_path, frames, opts)
    telemetry = render_telemetry_v1(model) if opts.telemetry_json is not None else None
    report = (
        telemetry
        if opts.telemetry_json == '-'
        else (render_json(model) if opts.json else render_text(model, opts))
    )

    if telemetry is not None and opts.telemetry_json != '-':
        with open(opts.telemetry_json, 'w', encoding='utf-8', newline='\n') as fh:
            fh.write(telemetry)
        print(f'Telemetry written to {opts.telemetry_json}', file=sys.stderr)

    if opts.output:
        with open(opts.output, 'w', encoding='utf-8') as fh:
            fh.write(report)
        print(f'Report written to {opts.output}', file=sys.stderr)
    else:
        print(report)
