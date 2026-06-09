"""
Tests for bg3_save_reader.py.

Two save files are bundled in tests/fixtures/:
  quicksave_maia.lsv                — full party, mid-campaign (primary fixture)
  autosave_shadowheart_tutorial.lsv — solo Shadowheart, tutorial / Nautiloid

Run with:
    uv run pytest
"""

import re
import sys
from argparse import Namespace
from pathlib import Path
from unittest import mock

# ---------------------------------------------------------------------------
# Make the project root importable regardless of working directory
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import bg3_save_reader as parser  # noqa: E402

# ---------------------------------------------------------------------------
# Save-file fixture paths
# ---------------------------------------------------------------------------

FIXTURE_DIR = Path(__file__).parent / 'fixtures'
QUICKSAVE_MAIA = str(FIXTURE_DIR / 'quicksave_maia.lsv')
SHADOWHEART_TUTORIAL = str(FIXTURE_DIR / 'autosave_shadowheart_tutorial.lsv')


# ---------------------------------------------------------------------------
# Helper: parse the text report into per-character equipped stats names
# ---------------------------------------------------------------------------

def extract_equipped_from_report(report: str) -> dict[str, set[str]]:
    """
    Parse the text report and return {character_name: {stats_name, ...}}
    for items listed under "Equipped (N):" for each character.

    Stats names are extracted from the "(STATS_NAME)" parenthetical that
    build_report() appends when game data is available, or from the bare
    internal name when it isn't.  Either way the stats name is recovered.
    """
    result: dict[str, set[str]] = {}
    current_char: str | None = None
    in_equipped = False

    for line in report.splitlines():
        # Detect character header lines (two leading spaces, no dash)
        char_match = re.match(r'^  (\S.*\S|\S+)\s*$', line)
        if char_match and not line.startswith('    ') and '─' not in line and '━' not in line:
            current_char = char_match.group(1).strip()
            in_equipped = False
            continue

        # Detect "Equipped (N):" section start
        if re.match(r'\s+Equipped \(\d+\):', line):
            in_equipped = True
            if current_char and current_char not in result:
                result[current_char] = set()
            continue

        # Any other section header ends the Equipped block
        if re.match(r'\s+(Carried|Worn or carried|Spells|Race|Class|Level|XP|Location|Equipment)\b',
                    line):
            in_equipped = False
            continue

        # Collect items in the Equipped block
        if in_equipped and current_char:
            item_match = re.match(r'\s+–\s+(.+)', line)
            if item_match:
                item_text = item_match.group(1).strip()
                # Try to extract the (STATS_NAME) parenthetical
                paren_match = re.search(r'\(([^)]+)\)\s*$', item_text)
                if paren_match:
                    stats = paren_match.group(1).strip()
                else:
                    # No display name was resolved — the whole token is the stats name
                    stats = item_text.strip()
                result[current_char].add(stats)

    return result


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------


def test_smoke_build_report():
    """build_report() must complete without error and produce a plausible report."""
    report = parser.build_report(QUICKSAVE_MAIA, opts=Namespace(verbose=True))
    assert isinstance(report, str)
    assert len(report) > 1000

    # At least 4 party character names must appear
    char_names = ['Maia (player)', 'Wyll', 'Karlach', 'Shadowheart']
    for name in char_names:
        assert name in report, f'Expected character {name!r} in report'

    # Count total equipped items across all characters
    equipped = extract_equipped_from_report(report)
    total_equipped = sum(len(items) for items in equipped.values())
    assert total_equipped >= 30, (
        f'Expected at least 30 total equipped items, got {total_equipped}'
    )


# ---------------------------------------------------------------------------
# Ground-truth test
# ---------------------------------------------------------------------------
#
# The expected sets below are the parser's validated output for QuickSave_242,
# cross-checked against tests/fixtures/quicksave-242-equipped-items.txt.
#
# Remaining deviation from the human-authored ground-truth file:
#
#   Maia:
#     ARM_Instrument_Lute    — not in the ground-truth file; false positive from
#                              the Flags bit.  Instrument items have their own
#                              slot (MusicalInstrument) with no conflict, so
#                              slot-conflict resolution cannot eliminate it.
#
#   Karlach:
#     UNI_Karlach_Gloves     — not in the ground-truth file; possible false
#                              positive, but there is no competing Gloves item to
#                              demote it via slot-conflict resolution.
#
# Previously documented false positives that are now fixed by the slot-conflict
# resolver and Object-type filter:
#   Maia:   ARM_HalfPlate_Body, FOR_DangerousBook, UNI_CONT_DEVIL_PuzzleBox_A,
#           WPN_Greatclub_1
#   Wyll:   ARM_Boots_Leather, MAG_Lesser_Infernal_Plate_Armor, WPN_Torch
#   Karlach: WPN_Torch
#   Shadowheart: DEN_HellridersPride

# Items eliminated by the object-type filter and slot-conflict resolver, both of
# which require game data.  When game data is unavailable (e.g. CI), these appear
# as false positives in each character's equipped set.
GAME_DATA_FILTERED: dict[str, set[str]] = {
    'Maia (player)': {
        'ARM_HalfPlate_Body',
        'FOR_DangerousBook',
        'UNI_CONT_DEVIL_PuzzleBox_A',
        'WPN_Greatclub_1',
    },
    'Wyll': {
        'ARM_Boots_Leather',
        'MAG_Lesser_Infernal_Plate_Armor',
        'WPN_Torch',
    },
    'Karlach': {
        'WPN_Torch',
    },
    'Shadowheart': {
        'DEN_HellridersPride',
    },
}

EXPECTED_EQUIPPED: dict[str, set[str]] = {
    'Maia (player)': {
        'ARM_Instrument_Lute',
        'FOR_NightWalkers',
        'MAG_FlamingFist_ScoutRing',
        'MAG_Harpers_HarpersAmulet',
        'MAG_MeleeDebuff_AttackDebuff1_OnDamage_Helmet',
        'MAG_MeleeDebuff_AttackDebuff2_OnDamage_SplintMail',
        'MAG_StrongString_Longbow',
        'MAG_ZOC_AdvantageOnMeleeAttackWhileSurounded_Gloves',
        'UND_SwordInStone',
    },
    'Wyll': {
        'GOB_DrowCommander_Leather_Armor',
        'MAG_BG_OfTheBanshee_Bow',
        'MAG_Duergar_Sword_KingsKnife',
        'MAG_Evasive_Shoes',
        'MAG_PHB_CloakOfProtection_Cloak',
        'MAG_PHB_ofPower_Pearl_Amulet',
        'MAG_Safeguard_Shield',
        'MAG_Thunder_Reverberation_Gloves',
        'UND_ShadowOfMenzoberranzan',
    },
    'Karlach': {
        'ARM_BootsOfSpeed',
        'GOB_DrowCommander_Amulet',
        'MAG_Acid_AcidDamageOnWeaponAttack_Ring',
        'MAG_BG_Harold_HeavyCrossbow',
        'MAG_BarbMonk_Offensive_Cloth',
        'MAG_Colossal_Greatsword',
        'MAG_Gish_ArcaneSynergy_Circlet',
        'MAG_Harpers_RingOfProjection',
        'UNI_Karlach_Gloves',
    },
    'Shadowheart': {
        'ARM_CircletOfBlasting',
        'ARM_Ring_I_Silver_A',
        'CRE_BloodOfLathander',
        'MAG_BG_OfDevotion_Shield',
        'MAG_BG_OfDexterity_Gloves',
        'MAG_Healer_HPRestoration_Amulet',
        'MAG_Hunting_Shortbow',
        'MAG_Paladin_MomentumOnConcentration_Boots',
        'MAG_Radiant_RadiatingOrb_Armor',
        'UNI_MassHealRing',
    },
}



def test_equipped_items_ground_truth():
    """
    Equipped item sets for QuickSave_242 must exactly match the validated
    baseline.  Any addition or removal in any character's equipped set causes
    this test to fail.

    When game data is unavailable (CI, no BG3 install) the object-type filter
    and slot-conflict resolver are inactive, so GAME_DATA_FILTERED items appear
    as false positives.  The expected set is widened accordingly so the test
    remains exact-equality in both regimes.
    """
    report = parser.build_report(QUICKSAVE_MAIA, opts=Namespace(verbose=True))
    actual = extract_equipped_from_report(report)
    game_data_available = parser.DisplayNames.load().available

    for char, expected_set in EXPECTED_EQUIPPED.items():
        expected = set(expected_set)
        if not game_data_available:
            expected |= GAME_DATA_FILTERED.get(char, set())
        actual_set = actual.get(char, set())
        added = actual_set - expected
        removed = expected - actual_set
        assert not added and not removed, (
            f'{char}: equipped set changed.\n'
            f'  Added   (unexpected): {sorted(added)}\n'
            f'  Removed (missing):    {sorted(removed)}'
        )


# ---------------------------------------------------------------------------
# Unit tests for pure functions (no save file required)
# ---------------------------------------------------------------------------

class TestSplitSpellString:
    """Tests for split_spell_string()."""

    def test_single_prefix(self):
        result = parser.split_spell_string('Shout_SecondWind')
        assert result == ['Shout_SecondWind']

    def test_two_prefixes_concatenated(self):
        result = parser.split_spell_string('Shout_SecondWindShout_ActionSurge')
        assert result == ['Shout_SecondWind', 'Shout_ActionSurge']

    def test_three_different_prefixes(self):
        result = parser.split_spell_string(
            'Projectile_EldritchBlastTarget_HexAgonizingBlastRepellingBlastShout_BladeWard'
        )
        assert result == [
            'Projectile_EldritchBlast',
            'Target_HexAgonizingBlastRepellingBlast',
            'Shout_BladeWard',
        ]

    def test_empty_string(self):
        assert parser.split_spell_string('') == []

    def test_null_bytes_stripped(self):
        result = parser.split_spell_string('\x00Shout_Rage\x00')
        assert result == ['Shout_Rage']

    def test_no_known_prefix(self):
        # split_spell_string splits on prefix *boundaries* but does not filter;
        # a string with no known prefix passes through as-is.
        assert parser.split_spell_string('SomeRandomText') == ['SomeRandomText']

    def test_teleportation_prefix(self):
        result = parser.split_spell_string('Teleportation_Revivify')
        assert result == ['Teleportation_Revivify']

    def test_pact_prefix(self):
        result = parser.split_spell_string('PactOfTheBlade')
        assert result == ['PactOfTheBlade']


class TestFmtClass:
    """Tests for fmt_class()."""

    def test_main_only(self):
        assert parser.fmt_class({'Main': 'Fighter'}) == 'Fighter'

    def test_main_and_sub(self):
        assert parser.fmt_class({'Main': 'Cleric', 'Sub': 'TrickeryDomain'}) == (
            'Cleric / TrickeryDomain'
        )

    def test_empty_sub_omitted(self):
        assert parser.fmt_class({'Main': 'Barbarian', 'Sub': ''}) == 'Barbarian'

    def test_missing_keys_graceful(self):
        assert parser.fmt_class({}) == ''

    def test_sub_without_main(self):
        # Edge case: Sub set but Main empty — separator still used
        assert parser.fmt_class({'Main': '', 'Sub': 'SomeSub'}) == ' / SomeSub'


class TestIsEquipmentType:
    """Tests for is_equipment_type()."""

    def test_weapon_is_equipment(self):
        assert parser.is_equipment_type('WPN_Longsword') is True

    def test_armor_is_equipment(self):
        assert parser.is_equipment_type('ARM_HalfPlate_Body') is True

    def test_magic_item_is_equipment(self):
        assert parser.is_equipment_type('MAG_Evasive_Shoes') is True

    def test_consumable_not_equipment(self):
        assert parser.is_equipment_type('CONS_Mushrooms_Bonecap') is False

    def test_obj_not_equipment(self):
        assert parser.is_equipment_type('OBJ_Keychain') is False

    def test_gold_not_equipment(self):
        assert parser.is_equipment_type('GOLD_Pile') is False

    def test_scroll_not_equipment(self):
        assert parser.is_equipment_type('SCR_SomeScroll') is False

    def test_scroll_long_form_not_equipment(self):
        assert parser.is_equipment_type('SCROLL_Fireball') is False

    def test_empty_string_not_equipment(self):
        assert parser.is_equipment_type('') is False

    def test_underwear_not_equipment(self):
        assert parser.is_equipment_type('ARM_Underwear_Elves') is False

    def test_camp_body_not_equipment(self):
        assert parser.is_equipment_type('ARM_Camp_Body') is False

    def test_backpack_not_equipment(self):
        assert parser.is_equipment_type('OBJ_Bag_AlchemyPouch_Backpack') is False

    def test_loot_prefix_not_equipment(self):
        assert parser.is_equipment_type('LOOT_Gem') is False

    def test_key_prefix_not_equipment(self):
        assert parser.is_equipment_type('KEY_IronKey') is False


# ---------------------------------------------------------------------------
# Unit tests for split_equipped_carried (object_type_stats filter)
# ---------------------------------------------------------------------------

class TestSplitEquippedCarried:
    """Tests for split_equipped_carried()."""

    EQUIPPED_FLAG = 0x04000000

    def test_status_equipped_wins(self):
        items = [('WPN_Sword', 0, 'g1')]
        equipped, carried, undetermined = parser.split_equipped_carried(
            items, status_equipped={'WPN_Sword'},
        )
        assert equipped == [('WPN_Sword', 'g1')]
        assert carried == []
        assert undetermined == []

    def test_flag_bit_equipped(self):
        items = [('WPN_Sword', self.EQUIPPED_FLAG, 'g1')]
        equipped, carried, undetermined = parser.split_equipped_carried(
            items, status_equipped=set(),
        )
        assert equipped == [('WPN_Sword', 'g1')]

    def test_non_equipment_always_carried(self):
        items = [('CONS_Potion', self.EQUIPPED_FLAG, 'g1')]
        equipped, carried, undetermined = parser.split_equipped_carried(
            items, status_equipped=set(),
        )
        assert carried == [('CONS_Potion', 'g1')]
        assert equipped == []

    def test_object_type_overrides_flag(self):
        # A FOR_DangerousBook-like item: has the Flags bit but is type Object.
        items = [('FOR_DangerousBook', self.EQUIPPED_FLAG, 'g1')]
        equipped, carried, undetermined = parser.split_equipped_carried(
            items, status_equipped=set(),
            object_type_stats=frozenset({'FOR_DangerousBook'}),
        )
        assert carried == [('FOR_DangerousBook', 'g1')]
        assert equipped == []

    def test_object_type_overrides_status(self):
        items = [('UNI_CONT_PuzzleBox', 0, 'g1')]
        equipped, carried, undetermined = parser.split_equipped_carried(
            items, status_equipped={'UNI_CONT_PuzzleBox'},
            object_type_stats=frozenset({'UNI_CONT_PuzzleBox'}),
        )
        assert carried == [('UNI_CONT_PuzzleBox', 'g1')]
        assert equipped == []

    def test_equipment_without_signal_is_undetermined(self):
        items = [('ARM_Boots', 0, 'g1')]
        equipped, carried, undetermined = parser.split_equipped_carried(
            items, status_equipped=set(),
        )
        assert undetermined == [('ARM_Boots', 'g1')]
        assert equipped == []
        assert carried == []


# ---------------------------------------------------------------------------
# Unit tests for resolve_slot_conflicts
# ---------------------------------------------------------------------------

class TestResolveSlotConflicts:
    """Tests for resolve_slot_conflicts()."""

    def test_no_conflict_passes_through(self):
        flags_eq = [('WPN_Sword', 'g1')]
        ecs_eq = [('ARM_Boots', 'g2')]
        stats_to_slot = {'WPN_Sword': 'Melee Main Weapon', 'ARM_Boots': 'Boots'}
        kept_flags, kept_ecs, demoted = parser.resolve_slot_conflicts(
            flags_eq, ecs_eq, stats_to_slot, {}, {}, {},
        )
        assert set(kept_flags) == {('WPN_Sword', 'g1')}
        assert set(kept_ecs) == {('ARM_Boots', 'g2')}
        assert demoted == []

    def test_flags_beats_ecs_for_same_slot(self):
        # Flags item and ECS item both claim the Chest slot — flags wins.
        flags_eq = [('ARM_Splint', 'g1')]
        ecs_eq = [('ARM_HalfPlate', 'g2')]
        stats_to_slot = {'ARM_Splint': 'Chest', 'ARM_HalfPlate': 'Chest'}
        kept_flags, kept_ecs, demoted = parser.resolve_slot_conflicts(
            flags_eq, ecs_eq, stats_to_slot, {}, {}, {},
        )
        assert ('ARM_Splint', 'g1') in kept_flags
        assert ('ARM_HalfPlate', 'g2') in demoted
        assert ('ARM_HalfPlate', 'g2') not in kept_ecs

    def test_ring_slot_allows_two(self):
        flags_eq = [('MAG_Ring1', 'g1'), ('MAG_Ring2', 'g2')]
        ecs_eq: list = []
        stats_to_slot = {'MAG_Ring1': 'Ring', 'MAG_Ring2': 'Ring'}
        kept_flags, kept_ecs, demoted = parser.resolve_slot_conflicts(
            flags_eq, ecs_eq, stats_to_slot, {}, {}, {},
        )
        assert len(kept_flags) == 2
        assert demoted == []

    def test_ring_slot_demotes_third(self):
        flags_eq = [('MAG_Ring1', 'g1'), ('MAG_Ring2', 'g2'), ('MAG_Ring3', 'g3')]
        ecs_eq: list = []
        stats_to_slot = {'MAG_Ring1': 'Ring', 'MAG_Ring2': 'Ring', 'MAG_Ring3': 'Ring'}
        # All same signal; MC tiebreaker needed.  Provide MC so we can predict winner.
        guid_to_rows = {'g1': [1], 'g2': [2], 'g3': [3]}
        membership_count = {1: 40, 2: 38, 3: 36}
        stats_to_entity = {'MAG_Ring1': 'g1', 'MAG_Ring2': 'g2', 'MAG_Ring3': 'g3'}
        kept_flags, kept_ecs, demoted = parser.resolve_slot_conflicts(
            flags_eq, ecs_eq, stats_to_slot, stats_to_entity, guid_to_rows, membership_count,
        )
        assert len(kept_flags) == 2
        assert len(demoted) == 1
        # Highest MC (g1=40, g2=38) should be kept; g3=36 demoted.
        assert ('MAG_Ring3', 'g3') in demoted

    def test_no_slot_info_passes_through(self):
        # Items with no slot data are not touched by conflict resolution.
        flags_eq = [('UNK_Item', 'g1')]
        ecs_eq = [('UNK_Item2', 'g2')]
        kept_flags, kept_ecs, demoted = parser.resolve_slot_conflicts(
            flags_eq, ecs_eq, {}, {}, {}, {},
        )
        assert ('UNK_Item', 'g1') in kept_flags
        assert ('UNK_Item2', 'g2') in kept_ecs
        assert demoted == []


# ---------------------------------------------------------------------------
# Unit tests for build_instance_entity_map
# ---------------------------------------------------------------------------

class TestBuildInstanceEntityMap:
    """Tests for build_instance_entity_map()."""

    def _make_nodes(self, items_data: list[dict]) -> list[dict]:
        """Build a minimal node tree for Items/Factory/Creators+Items."""
        nodes: list[dict] = []

        # node 0: Items root (parent=-1)
        nodes.append({'name': 'Items', 'parent': -1, 'children': [1], 'attrs': {}})
        # node 1: Factory
        nodes.append({'name': 'Factory', 'parent': 0, 'children': [2, 3], 'attrs': {}})
        # node 2: Creators
        creator_indices = list(range(4, 4 + len(items_data)))
        nodes.append({'name': 'Creators', 'parent': 1, 'children': creator_indices, 'attrs': {}})
        # node 3: Items (parallel list)
        item_indices = list(range(4 + len(items_data), 4 + 2 * len(items_data)))
        nodes.append({'name': 'Items', 'parent': 1, 'children': item_indices, 'attrs': {}})

        for d in items_data:
            nodes.append({'name': 'Creator', 'parent': 2, 'children': [], 'attrs': {
                'Entity': d['entity'],
                'TemplateID': d.get('template', ''),
            }})
        for d in items_data:
            nodes.append({'name': 'Item', 'parent': 3, 'children': [], 'attrs': {
                'Translate': d['translate'],
                'Stats': d['stats'],
            }})

        # Fix parent indices in creator/item nodes
        for i, d in enumerate(items_data):
            nodes[4 + i]['parent'] = 2
            nodes[4 + len(items_data) + i]['parent'] = 3

        return nodes

    def test_basic_mapping(self):
        nodes = self._make_nodes([
            {'entity': 'ent-1', 'translate': (1.0, 2.0, 3.0), 'stats': 'WPN_Sword'},
            {'entity': 'ent-2', 'translate': (4.0, 5.0, 6.0), 'stats': 'ARM_Boots'},
        ])
        result = parser.build_instance_entity_map(nodes)
        assert result[((1.0, 2.0, 3.0), 'WPN_Sword')] == 'ent-1'
        assert result[((4.0, 5.0, 6.0), 'ARM_Boots')] == 'ent-2'

    def test_empty_when_no_items_root(self):
        nodes = [{'name': 'Other', 'parent': -1, 'children': [], 'attrs': {}}]
        assert parser.build_instance_entity_map(nodes) == {}

    def test_skips_missing_fields(self):
        # An item with no Stats field should not appear in the result.
        nodes = self._make_nodes([
            {'entity': 'ent-1', 'translate': (1.0, 2.0, 3.0), 'stats': ''},
        ])
        result = parser.build_instance_entity_map(nodes)
        assert result == {}


# ---------------------------------------------------------------------------
# Integration tests using bundled fixture save files
# ---------------------------------------------------------------------------


def test_save_info():
    """--save-info section must appear and contain recognisable fields."""
    report = parser.build_report(QUICKSAVE_MAIA, opts=Namespace(save_info=True))
    assert 'Save Name' in report
    assert 'Game Ver' in report
    assert 'Leader' in report



def test_quests():
    """--quests must parse the Osiris story state and emit a quests section."""
    report = parser.build_report(QUICKSAVE_MAIA, opts=Namespace(quests=True))
    assert 'QUEST & STORY STATE' in report
    # The Osiris version line proves the parser reached the binary format.
    assert 'Osiris version:' in report
    # A mid-campaign save should have at least a handful of in-progress quests.
    assert 'Quests in progress' in report



def test_thumbnail(tmp_path):
    """extract_thumbnail must write a valid WebP file and return dimensions."""
    frames = parser.extract_frames(QUICKSAVE_MAIA)
    out = tmp_path / 'thumb.webp'
    dims = parser.extract_thumbnail(frames, str(out))
    assert out.exists()
    assert out.stat().st_size > 0
    # All observed saves use VP8X extended WebP.
    assert out.read_bytes()[:4] == b'RIFF'
    assert dims is not None
    w, h = dims
    assert w > 0 and h > 0



def test_carried():
    """--carried must emit a Carried / personal inventory section."""
    report = parser.build_report(QUICKSAVE_MAIA, opts=Namespace(carried=True))
    assert 'Carried / personal inventory' in report



def test_all_items():
    """--all-items must emit the full level inventory section."""
    report = parser.build_report(QUICKSAVE_MAIA, opts=Namespace(all_items=True))
    assert 'ALL ITEMS ON CURRENT LEVEL' in report
    assert 'items total' in report



def test_limits():
    """--limits must emit the known-limitations note."""
    report = parser.build_report(QUICKSAVE_MAIA, opts=Namespace(limits=True))
    assert 'LIMITS' in report
    assert 'Spell attribution' in report



def test_main_stdout(capsys):
    """main() with a save path must print the report to stdout."""
    with mock.patch('sys.argv', ['bg3_save_reader', QUICKSAVE_MAIA]):
        parser.main()
    captured = capsys.readouterr()
    assert 'BG3 Save File Report' in captured.out
    assert len(captured.out) > 1000



def test_main_output_file(tmp_path):
    """main() with an output path must write the report to the file."""
    out = tmp_path / 'report.txt'
    with mock.patch('sys.argv', ['bg3_save_reader', QUICKSAVE_MAIA, str(out)]):
        parser.main()
    assert out.exists()
    content = out.read_text(encoding='utf-8')
    assert 'BG3 Save File Report' in content


# ---------------------------------------------------------------------------
# Integration tests for the Shadowheart tutorial save (fewer LevelCache files)
# ---------------------------------------------------------------------------


def test_shadowheart_tutorial_frames():
    """Shadowheart AutoSave_2 must have the expected LSPK structure."""
    frames = parser.extract_frames(SHADOWHEART_TUTORIAL)
    assert 'Globals.lsf' in frames
    assert 'meta.lsf' in frames
    assert 'thumbnail' in frames
    assert 'SaveInfo.json' in frames
    assert 'StorySave.bin' in frames
    lc_keys = [k for k in frames if k.startswith('LevelCache/')]
    assert len(lc_keys) == 2
    assert 'LevelCache/TUT_Avernus_C.lsf' in frames



def test_shadowheart_tutorial_report():
    """build_report() on the tutorial save must complete and mention Shadowheart."""
    report = parser.build_report(SHADOWHEART_TUTORIAL)
    assert isinstance(report, str)
    assert len(report) > 500
    assert 'Shadowheart' in report



def test_shadowheart_quests():
    """Osiris parsing must work on the tutorial save's StorySave.bin."""
    report = parser.build_report(SHADOWHEART_TUTORIAL, opts=Namespace(quests=True))
    assert 'QUEST & STORY STATE' in report
    assert 'Osiris version:' in report
