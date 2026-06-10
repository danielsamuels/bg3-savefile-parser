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
                # Strip the optional trailing "[Slot]" annotation, then take
                # the (STATS_NAME) parenthetical when a display name was
                # resolved; otherwise the whole token is the stats name.
                item_text = re.sub(r'\s*\[[^\]]+\]\s*$', '', item_text)
                paren_match = re.search(r'\(([^)]+)\)\s*$', item_text)
                stats = paren_match.group(1).strip() if paren_match else item_text.strip()
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
#   Karlach:
#     UNI_Karlach_Gloves     — not in the ground-truth file; possible false
#                              positive, but there is no competing Gloves item to
#                              demote it via slot-conflict resolution.
#
# Previously documented false positives that are now fixed by the slot-conflict
# resolver and Object-type filter:
#   Maia:   ARM_HalfPlate_Body, FOR_DangerousBook, UNI_CONT_DEVIL_PuzzleBox_A
#   Wyll:   MAG_Lesser_Infernal_Plate_Armor, WPN_Torch
#   Karlach: WPN_Torch
#   Shadowheart: DEN_HellridersPride
# (WPN_Greatclub_1 and ARM_Boots_Leather are no longer here: the
#  WieldedComponent ECS-promotion gate eliminates them without game data.)

# Items eliminated by the object-type filter and slot-conflict resolver, both of
# which require game data.  When game data is unavailable (e.g. CI), these appear
# as false positives in each character's equipped set.
GAME_DATA_FILTERED: dict[str, set[str]] = {
    'Maia (player)': {
        'ARM_HalfPlate_Body',
        'FOR_DangerousBook',
        'UNI_CONT_DEVIL_PuzzleBox_A',
    },
    'Wyll': {
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

    def test_owned_loot_tiebreaks_flags_conflict(self):
        # Two Flags items claim the same slot; the one in OwnedAsLootComponent wins
        # even when it has lower MC (the real save-246 / Hellrider's Pride scenario).
        flags_eq = [('DEN_HellridersPride', 'g_stale'), ('MAG_Thunder_Gloves', 'g_real')]
        ecs_eq: list = []
        stats_to_slot = {'DEN_HellridersPride': 'Gloves', 'MAG_Thunder_Gloves': 'Gloves'}
        stats_to_entity = {'DEN_HellridersPride': 'e_stale', 'MAG_Thunder_Gloves': 'e_real'}
        guid_to_rows = {'e_stale': [10], 'e_real': [20]}
        membership_count = {10: 37, 20: 35}  # stale has higher MC
        # Only e_real (row 20) is in OwnedAsLootComponent
        owned_as_loot_rows = frozenset([20])
        kept_flags, kept_ecs, demoted = parser.resolve_slot_conflicts(
            flags_eq, ecs_eq, stats_to_slot, stats_to_entity, guid_to_rows, membership_count,
            owned_as_loot_rows=owned_as_loot_rows,
        )
        assert ('MAG_Thunder_Gloves', 'g_real') in kept_flags
        assert ('DEN_HellridersPride', 'g_stale') in demoted

    def test_owned_loot_absent_falls_back_to_mc(self):
        # When owned_as_loot_rows is None, falls back to MC tiebreaker.
        flags_eq = [('ARM_Item1', 'g1'), ('ARM_Item2', 'g2')]
        ecs_eq: list = []
        stats_to_slot = {'ARM_Item1': 'Chest', 'ARM_Item2': 'Chest'}
        stats_to_entity = {'ARM_Item1': 'e1', 'ARM_Item2': 'e2'}
        guid_to_rows = {'e1': [1], 'e2': [2]}
        membership_count = {1: 38, 2: 42}  # e2 has higher MC
        kept_flags, kept_ecs, demoted = parser.resolve_slot_conflicts(
            flags_eq, ecs_eq, stats_to_slot, stats_to_entity, guid_to_rows, membership_count,
            owned_as_loot_rows=None,
        )
        assert ('ARM_Item2', 'g2') in kept_flags
        assert ('ARM_Item1', 'g1') in demoted

    def test_status_equipped_wins_over_higher_mc(self):
        # Phalar Aluve / moonlantern scenario: two flags items compete for Melee Main Weapon.
        # The one with an active status effect wins even when the other has higher MC.
        flags_eq = [('UND_SwordInStone', 'g_sword'), ('Quest_Lantern', 'g_lantern')]
        ecs_eq: list = []
        stats_to_slot = {
            'UND_SwordInStone': 'Melee Main Weapon',
            'Quest_Lantern': 'Melee Main Weapon',
        }
        stats_to_entity = {'UND_SwordInStone': 'e_sword', 'Quest_Lantern': 'e_lantern'}
        guid_to_rows = {'e_sword': [1], 'e_lantern': [2]}
        membership_count = {1: 40, 2: 41}  # lantern has higher MC but sword has status
        kept_flags, kept_ecs, demoted = parser.resolve_slot_conflicts(
            flags_eq, ecs_eq, stats_to_slot, stats_to_entity, guid_to_rows, membership_count,
            status_equipped=frozenset(['UND_SwordInStone']),
        )
        assert ('UND_SwordInStone', 'g_sword') in kept_flags
        assert ('Quest_Lantern', 'g_lantern') in demoted

    def test_status_equipped_none_falls_back_to_owned_loot(self):
        # Without status_equipped, the existing owned_loot/MC fallback applies.
        flags_eq = [('WPN_Sword', 'g1'), ('WPN_Axe', 'g2')]
        ecs_eq: list = []
        stats_to_slot = {'WPN_Sword': 'Melee Main Weapon', 'WPN_Axe': 'Melee Main Weapon'}
        stats_to_entity = {'WPN_Sword': 'e1', 'WPN_Axe': 'e2'}
        guid_to_rows = {'e1': [1], 'e2': [2]}
        membership_count = {1: 40, 2: 38}  # sword has higher MC
        kept_flags, kept_ecs, demoted = parser.resolve_slot_conflicts(
            flags_eq, ecs_eq, stats_to_slot, stats_to_entity, guid_to_rows, membership_count,
            status_equipped=None,
        )
        assert ('WPN_Sword', 'g1') in kept_flags
        assert ('WPN_Axe', 'g2') in demoted

    def test_status_equipped_wins_mixed_flags_and_ecs(self):
        # Real save 268 scenario: two flags items compete alongside several ECS items
        # for Melee Main Weapon.  The flags winner must still be chosen by status_equipped,
        # not by MC (the other flags item had a higher MC in the real save).
        flags_eq = [('UND_SwordInStone', 'g_sword'), ('Quest_Lantern', 'g_lantern')]
        ecs_eq = [('WPN_Torch', 'g_torch'), ('WPN_Pitchfork', 'g_pitch')]
        stats_to_slot = {
            'UND_SwordInStone': 'Melee Main Weapon',
            'Quest_Lantern': 'Melee Main Weapon',
            'WPN_Torch': 'Melee Main Weapon',
            'WPN_Pitchfork': 'Melee Main Weapon',
        }
        stats_to_entity = {
            'UND_SwordInStone': 'e_sword', 'Quest_Lantern': 'e_lantern',
            'WPN_Torch': 'e_torch', 'WPN_Pitchfork': 'e_pitch',
        }
        guid_to_rows = {'e_sword': [1], 'e_lantern': [2], 'e_torch': [3], 'e_pitch': [4]}
        membership_count = {1: 40, 2: 41, 3: 5, 4: 5}  # lantern has higher MC but sword has status
        kept_flags, kept_ecs, demoted = parser.resolve_slot_conflicts(
            flags_eq, ecs_eq, stats_to_slot, stats_to_entity, guid_to_rows, membership_count,
            status_equipped=frozenset(['UND_SwordInStone']),
        )
        assert ('UND_SwordInStone', 'g_sword') in kept_flags
        assert ('Quest_Lantern', 'g_lantern') in demoted
        assert ('WPN_Torch', 'g_torch') in demoted
        assert ('WPN_Pitchfork', 'g_pitch') in demoted

    def test_wielded_wins_over_owned_loot_and_mc(self):
        # Real save 286 (Wyll): Knife of the Undermountain King is genuinely
        # equipped (has WieldedComponent) while Phalar Aluve sits in the
        # inventory with higher MC and OwnedAsLootComponent membership.
        flags_eq = [('MAG_KingsKnife', 'g_knife'), ('UND_SwordInStone', 'g_sword')]
        ecs_eq: list = []
        stats_to_slot = {
            'MAG_KingsKnife': 'Melee Main Weapon',
            'UND_SwordInStone': 'Melee Main Weapon',
        }
        stats_to_entity = {'MAG_KingsKnife': 'e_knife', 'UND_SwordInStone': 'e_sword'}
        guid_to_rows = {'e_knife': [1], 'e_sword': [2]}
        membership_count = {1: 37, 2: 41}  # stale sword has higher MC
        kept_flags, kept_ecs, demoted = parser.resolve_slot_conflicts(
            flags_eq, ecs_eq, stats_to_slot, stats_to_entity, guid_to_rows, membership_count,
            owned_as_loot_rows=frozenset([2]),  # only the stale sword is in loot
            wielded_rows=frozenset([1]),
        )
        assert ('MAG_KingsKnife', 'g_knife') in kept_flags
        assert ('UND_SwordInStone', 'g_sword') in demoted

    def test_gravity_disabled_wins_over_owned_loot_and_mc(self):
        # Real save 286 (Maia): Halberd of Vigilance is genuinely equipped
        # (has GravityDisabledComponent) while the moonlantern sits in the
        # inventory with higher MC and OwnedAsLootComponent membership.
        flags_eq = [('MAG_Halberd', 'g_halberd'), ('Quest_Lantern', 'g_lantern')]
        ecs_eq: list = []
        stats_to_slot = {
            'MAG_Halberd': 'Melee Main Weapon',
            'Quest_Lantern': 'Melee Main Weapon',
        }
        stats_to_entity = {'MAG_Halberd': 'e_halberd', 'Quest_Lantern': 'e_lantern'}
        guid_to_rows = {'e_halberd': [1], 'e_lantern': [2]}
        membership_count = {1: 36, 2: 40}  # stale lantern has higher MC
        kept_flags, kept_ecs, demoted = parser.resolve_slot_conflicts(
            flags_eq, ecs_eq, stats_to_slot, stats_to_entity, guid_to_rows, membership_count,
            owned_as_loot_rows=frozenset([2]),  # only the stale lantern is in loot
            gravity_disabled_rows=frozenset([1]),
        )
        assert ('MAG_Halberd', 'g_halberd') in kept_flags
        assert ('Quest_Lantern', 'g_lantern') in demoted

    def test_status_equipped_wins_over_attachment_components(self):
        # status_equipped remains the strongest signal, above wielded/gravity.
        flags_eq = [('WPN_A', 'g_a'), ('WPN_B', 'g_b')]
        stats_to_slot = {'WPN_A': 'Melee Main Weapon', 'WPN_B': 'Melee Main Weapon'}
        stats_to_entity = {'WPN_A': 'e_a', 'WPN_B': 'e_b'}
        guid_to_rows = {'e_a': [1], 'e_b': [2]}
        membership_count = {1: 30, 2: 40}
        kept_flags, kept_ecs, demoted = parser.resolve_slot_conflicts(
            flags_eq, [], stats_to_slot, stats_to_entity, guid_to_rows, membership_count,
            status_equipped=frozenset(['WPN_A']),
            wielded_rows=frozenset([2]),  # B looks attached, but A has the status
        )
        assert ('WPN_A', 'g_a') in kept_flags
        assert ('WPN_B', 'g_b') in demoted

    def test_twohanded_weapon_demotes_ecs_offhand(self):
        # MAG_Colossal_Greatsword scenario: Karlach has a 2-handed flags weapon in
        # Melee Main Weapon; ECS-promoted shield in Melee Offhand Weapon is demoted.
        flags_eq = [('MAG_Greatsword', 'g_sword')]
        ecs_eq = [('MAG_Shield', 'g_shield')]
        stats_to_slot = {
            'MAG_Greatsword': 'Melee Main Weapon',
            'MAG_Shield': 'Melee Offhand Weapon',
        }
        two_handed_stats = frozenset(['MAG_Greatsword'])
        kept_flags, kept_ecs, demoted = parser.resolve_slot_conflicts(
            flags_eq, ecs_eq, stats_to_slot, {}, {}, {},
            two_handed_stats=two_handed_stats,
        )
        assert ('MAG_Greatsword', 'g_sword') in kept_flags
        assert ('MAG_Shield', 'g_shield') in demoted
        assert ('MAG_Shield', 'g_shield') not in kept_ecs

    def test_onehanded_weapon_preserves_offhand(self):
        # A one-handed weapon should not affect the offhand slot.
        flags_eq = [('WPN_Longsword', 'g_sword')]
        ecs_eq = [('ARM_Shield', 'g_shield')]
        stats_to_slot = {
            'WPN_Longsword': 'Melee Main Weapon',
            'ARM_Shield': 'Melee Offhand Weapon',
        }
        two_handed_stats = frozenset(['WPN_Greatsword'])  # longsword not in here
        kept_flags, kept_ecs, demoted = parser.resolve_slot_conflicts(
            flags_eq, ecs_eq, stats_to_slot, {}, {}, {},
            two_handed_stats=two_handed_stats,
        )
        assert ('WPN_Longsword', 'g_sword') in kept_flags
        assert ('ARM_Shield', 'g_shield') in kept_ecs
        assert demoted == []

    def test_twohanded_none_preserves_offhand(self):
        # With two_handed_stats=None, no 2-handed constraint is applied.
        flags_eq = [('WPN_Greatsword', 'g_sword')]
        ecs_eq = [('ARM_Shield', 'g_shield')]
        stats_to_slot = {
            'WPN_Greatsword': 'Melee Main Weapon',
            'ARM_Shield': 'Melee Offhand Weapon',
        }
        kept_flags, kept_ecs, demoted = parser.resolve_slot_conflicts(
            flags_eq, ecs_eq, stats_to_slot, {}, {}, {},
            two_handed_stats=None,
        )
        assert ('ARM_Shield', 'g_shield') in kept_ecs
        assert demoted == []


# ---------------------------------------------------------------------------
# Unit tests for build_instance_entity_map
# ---------------------------------------------------------------------------

class TestEcsResolveEquipped:
    """Tests for ecs_resolve_equipped(), focusing on the wielded_rows filter."""

    def test_wielded_rows_demotes_to_carried(self):
        # ARM_Shield scenario: item with high MC but present in WieldedComponent
        # should be classified as carried, not equipped.
        undetermined = [('ARM_Shield', 'tmpl-shield')]
        entity_guid = 'entity-shield'
        stats_to_entity = {'ARM_Shield': entity_guid}
        guid_to_rows = {entity_guid: [10, 20, 30]}
        membership_count = {10: 38, 20: 0, 30: 0}
        wielded_rows = frozenset([10])  # row 10 is in WieldedComponent

        eq, ca, undet = parser.ecs_resolve_equipped(
            undetermined, {}, guid_to_rows, membership_count,
            stats_to_entity=stats_to_entity,
            wielded_rows=wielded_rows,
        )
        assert eq == []
        assert ('ARM_Shield', 'tmpl-shield') in ca
        assert undet == []

    def test_not_wielded_promotes_to_equipped(self):
        # UNI_Karlach_Gloves scenario: item with high MC and NOT in WieldedComponent
        # should be classified as equipped.
        undetermined = [('UNI_Karlach_Gloves', 'tmpl-gloves')]
        entity_guid = 'entity-gloves'
        stats_to_entity = {'UNI_Karlach_Gloves': entity_guid}
        guid_to_rows = {entity_guid: [15, 40, 50]}
        membership_count = {15: 38, 40: 0, 50: 0}
        wielded_rows = frozenset([99])  # row 15 is NOT in WieldedComponent

        eq, ca, undet = parser.ecs_resolve_equipped(
            undetermined, {}, guid_to_rows, membership_count,
            stats_to_entity=stats_to_entity,
            wielded_rows=wielded_rows,
        )
        assert ('UNI_Karlach_Gloves', 'tmpl-gloves') in eq
        assert ca == []
        assert undet == []

    def test_no_wielded_rows_behaves_as_before(self):
        # Without wielded_rows parameter, high-MC item is promoted as before.
        undetermined = [('ARM_Shield', 'tmpl-shield')]
        entity_guid = 'entity-shield'
        stats_to_entity = {'ARM_Shield': entity_guid}
        guid_to_rows = {entity_guid: [10]}
        membership_count = {10: 38}

        eq, ca, undet = parser.ecs_resolve_equipped(
            undetermined, {}, guid_to_rows, membership_count,
            stats_to_entity=stats_to_entity,
        )
        assert ('ARM_Shield', 'tmpl-shield') in eq
        assert ca == []


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

        nodes.extend(
            {'name': 'Creator', 'parent': 2, 'children': [], 'attrs': {
                'Entity': d['entity'],
                'TemplateID': d.get('template', ''),
            }}
            for d in items_data
        )
        nodes.extend(
            {'name': 'Item', 'parent': 3, 'children': [], 'attrs': {
                'Translate': d['translate'],
                'Stats': d['stats'],
            }}
            for d in items_data
        )
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



def test_exact_spellbooks():
    """Every party member's spells must come from the exact LSMF spell book
    (no heuristic fallback), and known class abilities must be present."""
    report = parser.build_report(QUICKSAVE_MAIA, opts=Namespace(verbose=True))
    assert 'heuristic' not in report
    assert 'basic actions' in report
    # Wyll is a Fiend warlock: Eldritch Blast must be in his exact book.
    wyll = re.search(r'\n  Wyll\n(.*?)(?:\n  \S|\Z)', report, re.S).group(1)
    assert 'Projectile_EldritchBlast' in wyll
    # Karlach is a Totem barbarian.
    karlach = re.search(r'\n  Karlach\n(.*?)(?:\n  \S|\Z)', report, re.S).group(1)
    assert 'Shout_Rage' in karlach


def test_all_spells_flag():
    """--all-spells must list everything: no folded sub-spell/basic-action counts."""
    report = parser.build_report(QUICKSAVE_MAIA, opts=Namespace(all_spells=True))
    assert 'Spells/Abilities (' in report
    assert 'sub-spells' not in report
    assert 'basic actions' not in report


def test_parse_lsmf_spellbooks_direct():
    """parse_lsmf_spellbooks must return many non-trivial books from the blob."""
    frames = parser.extract_frames(QUICKSAVE_MAIA)
    nodes0 = parser.parse_lsof(parser.decomp_frame(frames['Globals.lsf']))
    blob = next(nd['attrs']['NewAge'] for nd in nodes0
                if nd['name'] == 'NewAge' and nd['parent'] == -1)
    books = parser.parse_lsmf_spellbooks(blob)
    assert len(books) > 100  # party + NPCs all carry spell books
    classes = parser.parse_lsmf_classes(blob)
    named = {parser.CLASS_UUID_NAMES.get(c) for cls in classes.values() for c, _s, _l in cls}
    assert {'Warlock', 'Barbarian', 'Cleric', 'Fighter'} <= named


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
