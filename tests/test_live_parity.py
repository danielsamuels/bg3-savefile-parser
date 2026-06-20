"""Top-down validation against the game's own UI.

The check that would have caught the tadpole-pool miss: compare the report to
what a player reads on screen. Fill tests/ground_truth/<label>.json from the
in-game UI (see TEMPLATE.json), then run `pytest -k live_parity`.

For every value provided, if the report can produce it the harness asserts they
match (a regression guard on real saves); values the report cannot yet produce
are reported as pending so the file doubles as the target list for open gaps.

CI-safe: each ground-truth file names an absolute save_path, and the test skips
when that path is absent (CI machines have no save installs).
"""

import glob
import json
import os

import pytest

import bg3parser as parser
from tests.test_parser import FIXTURE_DIR

GT_DIR = FIXTURE_DIR.parent / 'ground_truth'
GT_FILES = [f for f in glob.glob(str(GT_DIR / '*.json')) if not f.endswith('TEMPLATE.json')]

UNSUPPORTED = object()


def party_value(report, key):
    si = report.save_info
    if key in ('camp_supplies', 'tadpoles_available'):
        return si.get(key)
    return UNSUPPORTED  # gold / inspiration / short_rests_remaining: not surfaced yet


def char_value(char, key):
    if key == 'hp_current':
        return (char.hp or {}).get('current')
    if key == 'hp_max':
        return (char.hp or {}).get('max')
    if key == 'resources':
        return {
            r['name']: {'current': r['current'], 'max': r['max']} for r in (char.resources or [])
        }
    return UNSUPPORTED  # armour_class / exhaustion / resistances / conditions: gaps


@pytest.mark.skipif(
    not GT_FILES, reason='no ground-truth files; see tests/ground_truth/TEMPLATE.json'
)
@pytest.mark.parametrize('gt_path', GT_FILES, ids=lambda p: os.path.basename(p))
def test_live_parity(gt_path):
    with open(gt_path, encoding='utf-8') as f:
        gt = json.load(f)
    save = gt.get('save_path', '')
    if not save or not os.path.exists(save):
        pytest.skip(f'save not present: {save}')

    report = parser.gather_report(save)
    by_name = {c.name: c for c in report.characters}
    checked, pending, mismatches = 0, [], []

    for key, expected in (gt.get('party') or {}).items():
        if expected is None:
            continue
        actual = party_value(report, key)
        if actual is UNSUPPORTED:
            pending.append(f'party.{key}')
        elif actual != expected:
            mismatches.append(f'party.{key}: report={actual} game={expected}')
        else:
            checked += 1

    for name, fields in (gt.get('characters') or {}).items():
        char = by_name.get(name)
        if char is None:
            pending.append(f'character {name!r} not found in report')
            continue
        for key, expected in fields.items():
            if expected in (None, [], {}):
                continue
            actual = char_value(char, key)
            if actual is UNSUPPORTED:
                pending.append(f'{name}.{key}')
            elif actual != expected:
                mismatches.append(f'{name}.{key}: report={actual} game={expected}')
            else:
                checked += 1

    if pending:
        print(
            f'\n[live_parity] {os.path.basename(gt_path)}: {checked} verified, '
            f'{len(pending)} pending (report cannot produce yet): {", ".join(pending)}'
        )
    assert not mismatches, 'report disagrees with the game UI:\n  ' + '\n  '.join(mismatches)
    assert checked, 'nothing verifiable was provided; fill in supported fields'
