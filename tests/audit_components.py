"""Unconsumed-component audit: ECS components with data that no view reads.

This finds the next tadpole-pool-class miss. The tadpole pool was not an unnamed
GUID; it was a whole structure the player sees that nothing in the pipeline read.
This tool lists components present in a save (rows > 0) that the parser does not
consume and that look player-facing, so a real gap surfaces here instead of in a
playthrough.

    uv run python tests/audit_components.py tests/fixtures/quicksave_419.lsv

"Consumed" = referenced by name literal in bg3parser source, plus a manual set
of concepts surfaced through another path (byte scan, Osiris, or info.json) that
no name literal would catch. "Player-facing" is a namespace allowlist; internal
namespaces (visual, animation, AI, turn state, capabilities) are filtered out.

The matching guard test lives in test_component_registry: the candidate set must
stay within a reviewed baseline, so a new component (a patch, a build) cannot
appear without being triaged.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from bg3parser.lsf import decomp_frame, parse_lsof  # noqa: E402
from bg3parser.lsmf import lsmf_component_index  # noqa: E402
from bg3parser.lspk import extract_frames  # noqa: E402

# Concepts surfaced without a component name literal (byte scan / Osiris / info.json),
# so the literal-grep below cannot see them. Excluded from candidates.
COVERED_ELSEWHERE = {
    'game.tadpole_tree.v0.PowerContainerComponent',  # parse_lsmf_power_lists (byte scan)
    'game.tadpole_tree.v0.TadpoledComponent',
    'game.tadpole_tree.v0.HalfIllithidComponent',
    'game.tadpole_tree.v1.TreeStateComponent',
    'game.tadpole_tree.v1.ETadpoleTreeState',
    'game.approval.v0.Ratings',  # Osiris DB_ApprovalRating
    'game.race.v0.RaceComponent',  # race from info.json
    'game.tags.v0.RaceComponent',
    'game.experience.v0.ExperienceComponent',  # xp from info.json
    'game.progression.v3.LevelUpComponent',  # feats via character_creation LevelUp
}

# Player-facing namespaces worth reviewing; everything else is engine internals.
INTERESTING = (
    'status',
    'background',
    'god',
    'progression',
    'race',
    'passive',
    'summon',
    'trade',
    'recruit',
    'approval',
    'calendar',
    'experience',
    'tadpole',
    'boost',
    'resource',
    'hireling',
    'faction',
    'relation',
    'attitude',
    'reputation',
    'wallet',
    'currency',
    'disease',
    'deity',
)


def consumed_components() -> set[str]:
    src = ' '.join(p.read_text() for p in (ROOT / 'bg3parser').glob('*.py'))
    out = set(re.findall(r"'([a-z_]+\.[a-z_0-9]+\.v[0-9]+\.[A-Za-z0-9_]+)'", src))
    out |= set(re.findall(r"'(core\.v0\.[A-Za-z0-9_]+)'", src))
    return out | COVERED_ELSEWHERE


def lsmf_blob(path: str) -> bytes:
    nodes = parse_lsof(decomp_frame(extract_frames(path)['Globals.lsf']))
    return next(
        nd['attrs']['NewAge'] for nd in nodes if nd['name'] == 'NewAge' and nd['parent'] == -1
    )


def candidate_components(blob: bytes) -> dict[str, int]:
    """Player-facing components present (rows > 0) that the parser does not consume."""
    idx = lsmf_component_index(blob)
    consumed = consumed_components()
    out = {}
    for name, info in idx.items():
        rows = info[1]
        if rows <= 0 or name in consumed:
            continue
        if any(k in name.lower() for k in INTERESTING):
            out[name] = rows
    return out


def audit(path: str) -> None:
    cands = candidate_components(lsmf_blob(path))
    print(f'{Path(path).name}: {len(cands)} player-facing components present but not consumed')
    for name in sorted(cands):
        print(f'  {name}  (rows={cands[name]})')


if __name__ == '__main__':
    paths = sys.argv[1:] or [str(ROOT / 'tests' / 'fixtures' / 'quicksave_419.lsv')]
    for p in paths:
        audit(p)
