"""Resource census: enumerate every action resource in a save and flag the ones
we cannot name or do not walk.

This generalises the tadpole-pool miss. parse_lsmf_action_resources walks only
the per-character game.action_resources.v1.Component; the tadpole pool (and at
least three sibling resources) live in a separate collection it never reached,
so "we decoded the action-resource type" was true while whole resources went
unsurfaced. This tool counts resources at the instance level instead:

    uv run python tests/audit_resources.py tests/fixtures/quicksave_419.lsv

For each save it reports total resource GUIDs, how many are named by gamedata,
how many are unnamed, and how many sit outside the per-character component.
Run it after any resource-related change, or against a fresh save, to catch a
new collection or resource type before it silently goes missing from the report.
"""

import json
import math
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from bg3parser.lsf import decomp_frame, guid_le_str, parse_lsof  # noqa: E402
from bg3parser.lsmf import LSMF_HEAP_BASE, lsmf_component_index  # noqa: E402
from bg3parser.lspk import extract_frames  # noqa: E402


def lsmf_blob(path: str) -> bytes:
    nodes = parse_lsof(decomp_frame(extract_frames(path)['Globals.lsf']))
    return next(
        nd['attrs']['NewAge'] for nd in nodes if nd['name'] == 'NewAge' and nd['parent'] == -1
    )


def is_real_guid(g: bytes) -> bool:
    """Reject float-fragment / mostly-zero byte runs that look like AmountEntries."""
    return g[:4] != b'\0\0\0\0' and len(set(g)) >= 8 and g.count(0) <= 4


def census_resources(blob: bytes) -> dict[str, set[tuple[int, int]]]:
    """Map resource GUID -> {(amount, max), ...} for every AmountEntry in the blob.

    An AmountEntry is {16B GUID, i32 level 0..9, i32 pad==0, f64 amount, f64 max}
    with integer non-negative amounts; the GUID must look real (is_real_guid).
    """
    out: dict[str, set[tuple[int, int]]] = {}
    for i in range(0, len(blob) - 40, 8):
        level, pad = struct.unpack_from('<ii', blob, i + 16)
        if pad != 0 or not (0 <= level <= 9):
            continue
        amount, max_amount = struct.unpack_from('<dd', blob, i + 24)
        if not (math.isfinite(amount) and math.isfinite(max_amount)):
            continue
        if not (amount == int(amount) and max_amount == int(max_amount)):
            continue
        if not (0 <= amount <= max_amount <= 99 and max_amount >= 1):
            continue
        g = blob[i : i + 16]
        if not is_real_guid(g):
            continue
        out.setdefault(guid_le_str(g), set()).add((int(amount), int(max_amount)))
    return out


def per_character_guids(blob: bytes) -> set[str]:
    """GUIDs reachable via the per-character component (what the report walks)."""
    idx = lsmf_component_index(blob)
    comp = idx.get('game.action_resources.v1.Component')
    out: set[str] = set()
    if not comp:
        return out
    elem, rows, off, _ = comp
    L = len(blob)
    for k in range(rows):
        b, e = struct.unpack_from('<QQ', blob, off + k * elem)
        p, size = b + LSMF_HEAP_BASE, e - b
        if 0 < size < 64 * 400 and size % 64 == 0 and 0 < p <= L - size:
            for j in range(size // 64):
                out.add(guid_le_str(blob[p + j * 64 : p + j * 64 + 16]))
    return out


def audit(path: str) -> None:
    gd = json.loads((ROOT / 'data' / 'gamedata.json').read_text())
    names = {k.lower(): v for k, v in gd.get('action_resources', {}).items()}
    blob = lsmf_blob(path)
    res = census_resources(blob)
    per_char = per_character_guids(blob)
    unnamed = sorted(g for g in res if g.lower() not in names)
    standalone = sorted(g for g in res if g not in per_char)
    print(
        f'{Path(path).name}: {len(res)} resources, {len(res) - len(unnamed)} named, '
        f'{len(unnamed)} unnamed, {len(standalone)} outside the per-character component'
    )
    for g in sorted(set(unnamed) | set(standalone)):
        tags = []
        if g not in per_char:
            tags.append('standalone')
        if g.lower() not in names:
            tags.append('UNNAMED')
        label = names.get(g.lower(), '?')
        print(f'  {g}  {sorted(res[g])}  [{",".join(tags)}]  {label}')


if __name__ == '__main__':
    paths = sys.argv[1:] or [str(ROOT / 'tests' / 'fixtures' / 'quicksave_419.lsv')]
    for p in paths:
        audit(p)
