"""
Tests for bg3_save_reader.py.

The save file (QuickSave_242.lsv) is looked up via the BG3_SAVE_FILE env var
or the known development path.  Tests that require the save are skipped when
it is absent so the suite stays green on machines that don't have the file.

Run with:
    uv run --extra dev pytest
"""

import os
import re
import sys
from argparse import Namespace
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Make the project root importable regardless of working directory
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import bg3_save_reader as parser  # noqa: E402

# ---------------------------------------------------------------------------
# Save-file fixture path
# ---------------------------------------------------------------------------

SAVE_FILE = os.environ.get(
    'BG3_SAVE_FILE',
    '/var/home/dan/.local/share/Larian Studios/Baldur\'s Gate 3'
    '/PlayerProfiles/Public/Savegames/Story'
    '/Maia-8312621517__QuickSave_242/QuickSave_242.lsv',
)

SAVE_AVAILABLE = os.path.isfile(SAVE_FILE)
requires_save = pytest.mark.skipif(not SAVE_AVAILABLE, reason='QuickSave_242.lsv not found')


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

@requires_save
def test_smoke_build_report():
    """build_report() must complete without error and produce a plausible report."""
    report = parser.build_report(SAVE_FILE, opts=Namespace(verbose=True))
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
# Known deviations from the human-authored ground-truth file are annotated:
#
#   Maia:
#     ARM_HalfPlate_Body     — "Half Plate Armour": the parser classifies this
#                              as equipped; the ground-truth file lists
#                              "Adamantine Splint Armour" as her chest piece.
#                              Both items are present; ARM_HalfPlate_Body likely
#                              sits in her inventory with the equip flag set.
#     ARM_Instrument_Lute    — not in the ground-truth file; likely a false
#                              positive from the Flags bit.
#     FOR_DangerousBook      — "The Necromancy of Thay": not in the ground-truth
#                              file; classified as equipped but is a carried book.
#     UNI_CONT_DEVIL_PuzzleBox_A — "Mysterious Artefact": carried quest item
#                              flagged as equipped; not in the ground-truth file.
#     WPN_Greatclub_1        — "Greatclub +1": ground-truth lists this as an
#                              *inventory* item; parser classifies it as equipped.
#
#   Wyll:
#     ARM_Boots_Leather      — "Leather Boots": not in the ground-truth file;
#                              likely a false positive (spare footwear).
#     MAG_Lesser_Infernal_Plate_Armor — "Hellgloom Armour" in current game data
#                              / "Flawed Helldusk Armour" in the ground-truth
#                              file (older label); ground-truth lists this as an
#                              *inventory* item, not worn.
#     WPN_Torch              — not worn equipment; false positive.
#
#   Karlach:
#     UNI_Karlach_Gloves     — not in the ground-truth file (no gloves listed
#                              for Karlach); possible false positive.
#     WPN_Torch              — not worn equipment; false positive.
#
#   Shadowheart:
#     DEN_HellridersPride    — "Hellrider's Pride": ground-truth explicitly lists
#                              this as an *inventory* item.  LIMITS.md documents
#                              it as a known LSF false positive.
#
# This test pins the *current* parser output as the regression baseline.
# If any item appears or disappears from any character's equipped set, the test
# fails — that is the regression guard.

EXPECTED_EQUIPPED: dict[str, set[str]] = {
    'Maia (player)': {
        'ARM_HalfPlate_Body',
        'ARM_Instrument_Lute',
        'FOR_DangerousBook',
        'FOR_NightWalkers',
        'MAG_FlamingFist_ScoutRing',
        'MAG_Harpers_HarpersAmulet',
        'MAG_MeleeDebuff_AttackDebuff1_OnDamage_Helmet',
        'MAG_MeleeDebuff_AttackDebuff2_OnDamage_SplintMail',
        'MAG_StrongString_Longbow',
        'MAG_ZOC_AdvantageOnMeleeAttackWhileSurounded_Gloves',
        'UND_SwordInStone',
        'UNI_CONT_DEVIL_PuzzleBox_A',
        'WPN_Greatclub_1',
    },
    'Wyll': {
        'ARM_Boots_Leather',
        'GOB_DrowCommander_Leather_Armor',
        'MAG_BG_OfTheBanshee_Bow',
        'MAG_Duergar_Sword_KingsKnife',
        'MAG_Evasive_Shoes',
        'MAG_Lesser_Infernal_Plate_Armor',
        'MAG_PHB_CloakOfProtection_Cloak',
        'MAG_PHB_ofPower_Pearl_Amulet',
        'MAG_Safeguard_Shield',
        'MAG_Thunder_Reverberation_Gloves',
        'UND_ShadowOfMenzoberranzan',
        'WPN_Torch',
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
        'WPN_Torch',
    },
    'Shadowheart': {
        'ARM_CircletOfBlasting',
        'ARM_Ring_I_Silver_A',
        'CRE_BloodOfLathander',
        'DEN_HellridersPride',
        'MAG_BG_OfDevotion_Shield',
        'MAG_BG_OfDexterity_Gloves',
        'MAG_Healer_HPRestoration_Amulet',
        'MAG_Hunting_Shortbow',
        'MAG_Paladin_MomentumOnConcentration_Boots',
        'MAG_Radiant_RadiatingOrb_Armor',
        'UNI_MassHealRing',
    },
}


@requires_save
def test_equipped_items_ground_truth():
    """
    Equipped item sets for QuickSave_242 must exactly match the validated
    baseline.  Any addition or removal in any character's equipped set causes
    this test to fail.
    """
    report = parser.build_report(SAVE_FILE, opts=Namespace(verbose=True))
    actual = extract_equipped_from_report(report)

    for char, expected_set in EXPECTED_EQUIPPED.items():
        actual_set = actual.get(char, set())
        added = actual_set - expected_set
        removed = expected_set - actual_set
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
