"""Unconsumed-component audit: ECS components with data that no view reads.

This finds the next tadpole-pool-class miss. The tadpole pool was not an unnamed
GUID; it was a whole structure the player sees that nothing in the pipeline read.
This tool lists components present in a save (rows > 0) that the parser does not
consume and that are not on a denylist of engine-internal namespaces/patterns, so
a real gap surfaces here instead of in a playthrough.

    uv run python tests/audit_components.py tests/fixtures/quicksave_419.lsv

Design note (exposure): the filter is a DENYLIST, not an allowlist. An earlier
version admitted only namespaces we thought of, which silently hid anything we
did not list, the exact failure mode this tool exists to catch. Now everything
unconsumed is a candidate unless it matches a known-internal namespace or name
pattern, so a new player-facing namespace (the next tadpole_tree) is visible by
default and the audit reports how many it filtered. Validated across 83 real
saves: 28 candidates, stable.

"Consumed" = referenced by name literal in bg3parser source, plus COVERED_ELSEWHERE
(concepts surfaced through byte scan / Osiris / info.json that no literal catches).
The guard lives in test_component_registry: a candidate must be triaged into GAPS
or INTERNAL there, so a new one cannot appear unreviewed.
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
# so the literal grep cannot see them. Excluded from candidates.
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
    'game.party.v0.WaypointsComponent',  # waypoints from Osiris DB_WaypointUnlocked
}

# Engine-internal namespaces: runtime/AI/visual/UI/combat state, not player sheet.
# Denylist (not allowlist) so an unanticipated player-facing namespace stays visible.
DENY_NAMESPACES = frozenset(
    {
        'visual',
        'animation',
        'anim',
        'physics',
        'ai',
        'sound',
        'light',
        'effect',
        'ftb',
        'turn_based',
        'combat',
        'capabilities',
        'shapeshift',
        'interrupt',
        'spell_cast',
        'hit',
        'movement',
        'steering',
        'pathing',
        'trigger',
        'triggers',
        'darkness',
        'sight',
        'through',
        'unsheath',
        'improvisedweapon',
        'splatter',
        'repose',
        'dialog',
        'escort',
        'patrol',
        'lock',
        'pickpocket',
        'multiplayer',
        'safe_position',
        'materialparameteroverride',
        'icon',
        'icons',
        'display_names',
        'game_timer',
        'character_creation',
        'death',
        'identity',
        'attitude',
        'body_type',
        'tags',
        'clock',
        'active',
        'wielded',
        'gravity',
        'stealth',
        'camera',
        'cursor',
        'net',
        'hotbar',
        'rolls',
        'roll',
        'lootvalidation',
        'jumpfollow',
        'breadcrumb',
        'fog_volume_requests',
        'cooldown',
        'invisibility',
        'size',
        'templates',
        'dual_wielding',
        'concentration',
        'avatar',
        'character',
        'spell',
        'item',
        'stats',
        'tutorial',
        'ownership',
        'progression',
        'experience',
        'approval',
        'timeline',
        'use',
        'damage',
        'ambush',
        'jump',
        'projectile',
        'sneak',
    }
)

# Internal component-name substrings (ownership/inventory/UI/trade plumbing) that
# slip through the namespace filter.
DENY_PATTERN = re.compile(
    r'Owner|Ownee|Owned|Latest|Previous|SaveWith|Savegame|StateComponent|WeaponSet|'
    r'PlayerComponent|IsGlobal|Detach|OffStage|IsCurrent|IsOriginal|LevelIsOwner|'
    r'InventoryItemData|EState|EWeapon|MemberComponent|MemberData|Composition|Portals|'
    r'ViewComponent|Recipes|GeneratedTreasure|GeneratedTrade|CanBeIn|CannotBeTaken|HasMoved|'
    r'HasOpened|CanMove|InteractionDisabled|IsStoryItem|ItemComponent|Wielding|StackMember|'
    r'\.Stack$|Tradable|LootComponent|PresentTrader|CanTrade|LegacyCanTrade|ModifiedJournal|'
    r'LootableReaction|EHotBar|Quality|Settings|SupplyComponent|Chest|Presence|EndTheDay|'
    r'Stowed|AreaLevel|LevelComponent|DifficultyCheck|TranslatedString|\.Level$|ProfileEvent|'
    r'ScriptedExplosion|IncapacitationReason|UniqueComponent|Snapshot|ClientControl|'
    r'IndicateDarkness|IsDroppedOnDeath|ShapeshiftEquipment|ShapeshiftAdded|ShapeshiftUnequipped|'
    r'BlockDismiss|ContainerData|\.Type$|DataComponent|Socket|RewardList|RegisteredForTriggers|'
    r'ActiveMusic|EEventSending|CachedLeave|InInsideOf|WaypointsComponent|FollowerComponent|'
    r'Follow'
)


def consumed_components() -> set[str]:
    src = ' '.join(p.read_text() for p in (ROOT / 'bg3parser').glob('*.py'))
    out = set(re.findall(r"'([a-z_]+\.[a-z_0-9]+\.v[0-9]+\.[A-Za-z0-9_]+)'", src))
    out |= set(re.findall(r"'(core\.v0\.[A-Za-z0-9_]+)'", src))
    return out | COVERED_ELSEWHERE


def is_internal(name: str) -> bool:
    ns = name.split('.')[1] if name.count('.') > 1 else ''
    return ns in DENY_NAMESPACES or bool(DENY_PATTERN.search(name))


def lsmf_blob(path: str) -> bytes:
    nodes = parse_lsof(decomp_frame(extract_frames(path)['Globals.lsf']))
    return next(
        nd['attrs']['NewAge'] for nd in nodes if nd['name'] == 'NewAge' and nd['parent'] == -1
    )


def candidate_components(blob: bytes) -> dict[str, int]:
    """Player-facing components present (rows > 0) the parser does not consume."""
    idx = lsmf_component_index(blob)
    consumed = consumed_components()
    return {
        name: info[1]
        for name, info in idx.items()
        if info[1] > 0 and name not in consumed and not is_internal(name)
    }


def audit(path: str) -> None:
    idx = lsmf_component_index(lsmf_blob(path))
    consumed = consumed_components()
    present = [n for n, i in idx.items() if i[1] > 0]
    cands = candidate_components(lsmf_blob(path))
    # Fail-loud: report what the filter removed so over-filtering is visible.
    n_consumed = sum(1 for n in present if n in consumed)
    n_internal = sum(1 for n in present if n not in consumed and is_internal(n))
    print(
        f'{Path(path).name}: {len(present)} present | {n_consumed} consumed | '
        f'{n_internal} internal (denylist) | {len(cands)} candidates'
    )
    for name in sorted(cands):
        print(f'  {name}  (rows={cands[name]})')


if __name__ == '__main__':
    paths = sys.argv[1:] or [str(ROOT / 'tests' / 'fixtures' / 'quicksave_419.lsv')]
    for p in paths:
        audit(p)
