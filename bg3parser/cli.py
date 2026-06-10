"""Command-line entry point."""

import argparse
import os
import sys

from .discovery import find_latest_save, find_save_by_token
from .lspk import extract_frames, extract_thumbnail
from .model import gather_report
from .render import render_json, render_text

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description='Extract character info from a BG3 .lsv save file.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            'By default only party characters are shown (race, class, level,\n'
            'spells/abilities, and equipped gear).  Use the flags below to\n'
            'include additional sections.'
        ),
    )
    ap.add_argument('save', nargs='?', metavar='save.lsv',
                    help='path to save file (auto-detected if omitted)')
    ap.add_argument('output', nargs='?', metavar='output.txt',
                    help='write report to file (default: stdout)')
    ap.add_argument('--save-info', action='store_true',
                    help='include save metadata (name, date, mods, …)')
    ap.add_argument('--quests', action='store_true',
                    help='include quest and story state (Osiris; adds ~1-2 s)')
    ap.add_argument('--carried', action='store_true',
                    help="include each character's carried inventory")
    ap.add_argument('--all-items', action='store_true',
                    help='include full item list for the current level')
    ap.add_argument('--limits', action='store_true',
                    help='include known limitations note')
    ap.add_argument('--verbose', '-v', action='store_true',
                    help='show internal names in parentheses after display names')
    ap.add_argument('--thumbnail', '-t', metavar='PATH',
                    help="write the save's thumbnail image to PATH")
    ap.add_argument('--inspect', metavar='NAME',
                    help='show classification signals and ECS components for party items '
                         'whose internal stats name contains NAME (case-insensitive)')
    ap.add_argument('--all-spells', action='store_true',
                    help='list sub-spells (container variants like each Disguise Self '
                         'appearance) and basic actions instead of folding them away')
    ap.add_argument('--json', action='store_true',
                    help='emit the report as JSON instead of text (machine-readable; '
                         'includes everything gathered, with no display folding)')
    opts = ap.parse_args()

    save_path = opts.save
    if not save_path:
        save_path = find_latest_save()
        if not save_path:
            ap.error('no save given and none auto-detected; '
                     'pass a .lsv path or set BG3_SAVE_DIR')
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
    report = render_json(model) if opts.json else render_text(model, opts)

    if opts.output:
        with open(opts.output, 'w', encoding='utf-8') as fh:
            fh.write(report)
        print(f'Report written to {opts.output}', file=sys.stderr)
    else:
        print(report)
