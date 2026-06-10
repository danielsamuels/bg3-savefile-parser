"""Regenerate the TS-parity oracle: canonical report JSON per fixture save.

Run after any classification or decoding change:

    uv run python tests/generate_parity.py

Uses the committed data/gamedata.json so the output is identical on any
machine (no game install required). The TypeScript parser's tests compare
their report model against these files field-for-field.
"""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
os.environ['BG3_GAMEDATA_JSON'] = str(ROOT / 'data' / 'gamedata.json')
sys.path.insert(0, str(ROOT))

import argparse  # noqa: E402
import dataclasses  # noqa: E402

from bg3parser.model import gather_report  # noqa: E402

# Quests are gathered so the TS Osiris port is parity-tested too.
OPTS = argparse.Namespace(quests=True)

FIXTURES = ROOT / 'tests' / 'fixtures'
PARITY = ROOT / 'tests' / 'parity'


def main() -> None:
    PARITY.mkdir(exist_ok=True)
    for save in sorted(FIXTURES.glob('*.lsv')):
        report = gather_report(str(save), opts=OPTS)
        data = dataclasses.asdict(report)
        data['source'] = save.name  # absolute paths differ per machine
        out = PARITY / f'{save.stem}.expected.json'
        out.write_text(
            json.dumps(data, indent=1, ensure_ascii=False, sort_keys=True) + '\n',
            encoding='utf-8',
        )
        print(f'{out.name}: {out.stat().st_size // 1024} KiB')


if __name__ == '__main__':
    main()
