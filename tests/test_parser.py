"""
Tests for the bg3parser package.

Two save files are bundled in tests/fixtures/:
  quicksave_maia.lsv                — full party, mid-campaign (primary fixture)
  autosave_shadowheart_tutorial.lsv — solo Shadowheart, tutorial / Nautiloid

Run with:
    uv run pytest
"""

import json
import os
import re
import sys
from argparse import Namespace
from pathlib import Path
from unittest import mock

import pytest

# ---------------------------------------------------------------------------
# Make the project root importable regardless of working directory
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import bg3parser as parser  # noqa: E402
from bg3parser import gamedata, lsf, lsmf, lspk, party, render, report_views  # noqa: E402

# ---------------------------------------------------------------------------
# Save-file fixture paths
# ---------------------------------------------------------------------------

FIXTURE_DIR = Path(__file__).parent / 'fixtures'
QUICKSAVE_MAIA = str(FIXTURE_DIR / 'quicksave_maia.lsv')
SHADOWHEART_TUTORIAL = str(FIXTURE_DIR / 'autosave_shadowheart_tutorial.lsv')
# Saves bundled by their original quicksave index, so tests can refer to the
# in-game ground truth for that specific save.
QUICKSAVE_292 = str(FIXTURE_DIR / 'quicksave_292.lsv')  # Karlach dual-wields
QUICKSAVE_294 = str(FIXTURE_DIR / 'quicksave_294.lsv')  # Wyll: stale Phalar Aluve


def build_report(save_path, opts=None):
    """Test convenience: gather the model and render it as text."""
    return parser.render_text(parser.gather_report(save_path, opts=opts), opts)


def gather_model(save_path, opts=None):
    """Test convenience: gather the report model without rendering."""
    return parser.gather_report(save_path, opts=opts)


# ---------------------------------------------------------------------------
# Golden-file helpers for the text render (see TestTextOutputFormat)
# ---------------------------------------------------------------------------

GOLDEN_DIR = FIXTURE_DIR / 'expected'


def render_golden(save_path, opts=None):
    """Render the text report deterministically for golden comparison.

    The display-name resolver is pinned to the no-install fallback so the output
    is byte-identical on any machine (CI has no game data installed, a dev box
    might), and the Source line's absolute path is normalised to the fixture's
    basename.
    """
    empty = gamedata.DisplayNames({}, {}, {})
    with mock.patch.object(gamedata.DisplayNames, 'load', return_value=empty):
        text = build_report(save_path, opts)
    return re.sub(r'(?m)^Source: .*$', f'Source: {Path(save_path).name}', text, count=1)


def assert_golden(name, text):
    """Compare `text` to the committed golden fixture `name`.

    Regenerate every golden after an intentional formatting change with:
        BG3_UPDATE_GOLDEN=1 uv run pytest
    """
    path = GOLDEN_DIR / name
    if os.environ.get('BG3_UPDATE_GOLDEN'):
        path.parent.mkdir(exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return
    assert path.exists(), f'missing golden {name}; run BG3_UPDATE_GOLDEN=1 to create it'
    expected = path.read_text(encoding='utf-8')
    assert text == expected, (
        f'{name} differs from its golden fixture; '
        f're-run with BG3_UPDATE_GOLDEN=1 to regenerate if the change is intended'
    )


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------


def test_smoke_model():
    """gather_report() must complete and return a well-formed model."""
    model = gather_model(QUICKSAVE_MAIA)
    char_names = {c.name for c in model.characters}
    assert {'Maia (player)', 'Wyll', 'Karlach', 'Shadowheart'} <= char_names
    total_equipped = sum(len(c.equipped) for c in model.characters)
    assert total_equipped >= 30, f'Expected at least 30 total equipped items, got {total_equipped}'


def test_smoke_text_output():
    """render_text() must produce a non-empty report containing character names."""
    report = build_report(QUICKSAVE_MAIA)
    assert isinstance(report, str)
    assert len(report) > 1000
    for name in ['Maia (player)', 'Wyll', 'Karlach', 'Shadowheart']:
        assert name in report, f'Expected {name!r} in text output'


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
    model = gather_model(QUICKSAVE_MAIA)
    actual = {
        char.name: {item.stats for item in char.equipped}
        for char in model.characters
        if char.name in EXPECTED_EQUIPPED
    }
    game_data_available = gamedata.DisplayNames.load().available

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


class TestFmtClass:
    """Tests for fmt_class()."""

    def test_main_only(self):
        assert render.fmt_class({'Main': 'Fighter'}) == 'Fighter'

    def test_main_and_sub(self):
        assert render.fmt_class({'Main': 'Cleric', 'Sub': 'TrickeryDomain'}) == (
            'Cleric / TrickeryDomain'
        )

    def test_empty_sub_omitted(self):
        assert render.fmt_class({'Main': 'Barbarian', 'Sub': ''}) == 'Barbarian'

    def test_missing_keys_graceful(self):
        assert render.fmt_class({}) == ''

    def test_sub_without_main(self):
        # Edge case: Sub set but Main empty — separator still used
        assert render.fmt_class({'Main': '', 'Sub': 'SomeSub'}) == ' / SomeSub'


class TestIsEquipmentType:
    """Tests for is_equipment_type()."""

    def test_weapon_is_equipment(self):
        assert party.is_equipment_type('WPN_Longsword') is True

    def test_armor_is_equipment(self):
        assert party.is_equipment_type('ARM_HalfPlate_Body') is True

    def test_magic_item_is_equipment(self):
        assert party.is_equipment_type('MAG_Evasive_Shoes') is True

    def test_consumable_not_equipment(self):
        assert party.is_equipment_type('CONS_Mushrooms_Bonecap') is False

    def test_obj_not_equipment(self):
        assert party.is_equipment_type('OBJ_Keychain') is False

    def test_gold_not_equipment(self):
        assert party.is_equipment_type('GOLD_Pile') is False

    def test_scroll_not_equipment(self):
        assert party.is_equipment_type('SCR_SomeScroll') is False

    def test_scroll_long_form_not_equipment(self):
        assert party.is_equipment_type('SCROLL_Fireball') is False

    def test_empty_string_not_equipment(self):
        assert party.is_equipment_type('') is False

    def test_underwear_not_equipment(self):
        assert party.is_equipment_type('ARM_Underwear_Elves') is False

    def test_camp_body_not_equipment(self):
        assert party.is_equipment_type('ARM_Camp_Body') is False

    def test_backpack_not_equipment(self):
        assert party.is_equipment_type('OBJ_Bag_AlchemyPouch_Backpack') is False

    def test_loot_prefix_not_equipment(self):
        assert party.is_equipment_type('LOOT_Gem') is False

    def test_key_prefix_not_equipment(self):
        assert party.is_equipment_type('KEY_IronKey') is False


# ---------------------------------------------------------------------------
# Unit tests for split_equipped_carried (object_type_stats filter)
# ---------------------------------------------------------------------------


class TestSplitEquippedCarried:
    """Tests for split_equipped_carried()."""

    EQUIPPED_FLAG = 0x04000000

    def test_status_equipped_wins(self):
        items = [('WPN_Sword', 0, 'g1')]
        equipped, carried, undetermined = party.split_equipped_carried(
            items,
            status_equipped={'WPN_Sword'},
        )
        assert equipped == [('WPN_Sword', 'g1')]
        assert carried == []
        assert undetermined == []

    def test_flag_bit_equipped(self):
        items = [('WPN_Sword', self.EQUIPPED_FLAG, 'g1')]
        equipped, carried, undetermined = party.split_equipped_carried(
            items,
            status_equipped=set(),
        )
        assert equipped == [('WPN_Sword', 'g1')]

    def test_non_equipment_always_carried(self):
        items = [('CONS_Potion', self.EQUIPPED_FLAG, 'g1')]
        equipped, carried, undetermined = party.split_equipped_carried(
            items,
            status_equipped=set(),
        )
        assert carried == [('CONS_Potion', 'g1')]
        assert equipped == []

    def test_object_type_overrides_flag(self):
        # A FOR_DangerousBook-like item: has the Flags bit but is type Object.
        items = [('FOR_DangerousBook', self.EQUIPPED_FLAG, 'g1')]
        equipped, carried, undetermined = party.split_equipped_carried(
            items,
            status_equipped=set(),
            object_type_stats=frozenset({'FOR_DangerousBook'}),
        )
        assert carried == [('FOR_DangerousBook', 'g1')]
        assert equipped == []

    def test_object_type_overrides_status(self):
        items = [('UNI_CONT_PuzzleBox', 0, 'g1')]
        equipped, carried, undetermined = party.split_equipped_carried(
            items,
            status_equipped={'UNI_CONT_PuzzleBox'},
            object_type_stats=frozenset({'UNI_CONT_PuzzleBox'}),
        )
        assert carried == [('UNI_CONT_PuzzleBox', 'g1')]
        assert equipped == []

    def test_equipment_without_signal_is_undetermined(self):
        items = [('ARM_Boots', 0, 'g1')]
        equipped, carried, undetermined = party.split_equipped_carried(
            items,
            status_equipped=set(),
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
        kept_flags, kept_ecs, demoted = party.resolve_slot_conflicts(
            flags_eq,
            ecs_eq,
            stats_to_slot,
            {},
            {},
            {},
        )
        assert set(kept_flags) == {('WPN_Sword', 'g1')}
        assert set(kept_ecs) == {('ARM_Boots', 'g2')}
        assert demoted == []

    def test_flags_beats_ecs_for_same_slot(self):
        # Flags item and ECS item both claim the Chest slot — flags wins.
        flags_eq = [('ARM_Splint', 'g1')]
        ecs_eq = [('ARM_HalfPlate', 'g2')]
        stats_to_slot = {'ARM_Splint': 'Chest', 'ARM_HalfPlate': 'Chest'}
        kept_flags, kept_ecs, demoted = party.resolve_slot_conflicts(
            flags_eq,
            ecs_eq,
            stats_to_slot,
            {},
            {},
            {},
        )
        assert ('ARM_Splint', 'g1') in kept_flags
        assert ('ARM_HalfPlate', 'g2') in demoted
        assert ('ARM_HalfPlate', 'g2') not in kept_ecs

    def test_ring_slot_allows_two(self):
        flags_eq = [('MAG_Ring1', 'g1'), ('MAG_Ring2', 'g2')]
        ecs_eq: list = []
        stats_to_slot = {'MAG_Ring1': 'Ring', 'MAG_Ring2': 'Ring'}
        kept_flags, kept_ecs, demoted = party.resolve_slot_conflicts(
            flags_eq,
            ecs_eq,
            stats_to_slot,
            {},
            {},
            {},
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
        kept_flags, kept_ecs, demoted = party.resolve_slot_conflicts(
            flags_eq,
            ecs_eq,
            stats_to_slot,
            stats_to_entity,
            guid_to_rows,
            membership_count,
        )
        assert len(kept_flags) == 2
        assert len(demoted) == 1
        # Highest MC (g1=40, g2=38) should be kept; g3=36 demoted.
        assert ('MAG_Ring3', 'g3') in demoted

    def test_no_slot_info_passes_through(self):
        # Items with no slot data are not touched by conflict resolution.
        flags_eq = [('UNK_Item', 'g1')]
        ecs_eq = [('UNK_Item2', 'g2')]
        kept_flags, kept_ecs, demoted = party.resolve_slot_conflicts(
            flags_eq,
            ecs_eq,
            {},
            {},
            {},
            {},
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
        kept_flags, kept_ecs, demoted = party.resolve_slot_conflicts(
            flags_eq,
            ecs_eq,
            stats_to_slot,
            stats_to_entity,
            guid_to_rows,
            membership_count,
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
        kept_flags, kept_ecs, demoted = party.resolve_slot_conflicts(
            flags_eq,
            ecs_eq,
            stats_to_slot,
            stats_to_entity,
            guid_to_rows,
            membership_count,
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
        kept_flags, kept_ecs, demoted = party.resolve_slot_conflicts(
            flags_eq,
            ecs_eq,
            stats_to_slot,
            stats_to_entity,
            guid_to_rows,
            membership_count,
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
        kept_flags, kept_ecs, demoted = party.resolve_slot_conflicts(
            flags_eq,
            ecs_eq,
            stats_to_slot,
            stats_to_entity,
            guid_to_rows,
            membership_count,
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
            'UND_SwordInStone': 'e_sword',
            'Quest_Lantern': 'e_lantern',
            'WPN_Torch': 'e_torch',
            'WPN_Pitchfork': 'e_pitch',
        }
        guid_to_rows = {'e_sword': [1], 'e_lantern': [2], 'e_torch': [3], 'e_pitch': [4]}
        membership_count = {1: 40, 2: 41, 3: 5, 4: 5}  # lantern has higher MC but sword has status
        kept_flags, kept_ecs, demoted = party.resolve_slot_conflicts(
            flags_eq,
            ecs_eq,
            stats_to_slot,
            stats_to_entity,
            guid_to_rows,
            membership_count,
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
        kept_flags, kept_ecs, demoted = party.resolve_slot_conflicts(
            flags_eq,
            ecs_eq,
            stats_to_slot,
            stats_to_entity,
            guid_to_rows,
            membership_count,
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
        kept_flags, kept_ecs, demoted = party.resolve_slot_conflicts(
            flags_eq,
            ecs_eq,
            stats_to_slot,
            stats_to_entity,
            guid_to_rows,
            membership_count,
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
        kept_flags, kept_ecs, demoted = party.resolve_slot_conflicts(
            flags_eq,
            [],
            stats_to_slot,
            stats_to_entity,
            guid_to_rows,
            membership_count,
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
        kept_flags, kept_ecs, demoted = party.resolve_slot_conflicts(
            flags_eq,
            ecs_eq,
            stats_to_slot,
            {},
            {},
            {},
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
        kept_flags, kept_ecs, demoted = party.resolve_slot_conflicts(
            flags_eq,
            ecs_eq,
            stats_to_slot,
            {},
            {},
            {},
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
        kept_flags, kept_ecs, demoted = party.resolve_slot_conflicts(
            flags_eq,
            ecs_eq,
            stats_to_slot,
            {},
            {},
            {},
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

        eq, ca, undet = party.ecs_resolve_equipped(
            undetermined,
            {},
            guid_to_rows,
            membership_count,
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

        eq, ca, undet = party.ecs_resolve_equipped(
            undetermined,
            {},
            guid_to_rows,
            membership_count,
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

        eq, ca, undet = party.ecs_resolve_equipped(
            undetermined,
            {},
            guid_to_rows,
            membership_count,
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
            {
                'name': 'Creator',
                'parent': 2,
                'children': [],
                'attrs': {
                    'Entity': d['entity'],
                    'TemplateID': d.get('template', ''),
                },
            }
            for d in items_data
        )
        nodes.extend(
            {
                'name': 'Item',
                'parent': 3,
                'children': [],
                'attrs': {
                    'Translate': d['translate'],
                    'Stats': d['stats'],
                },
            }
            for d in items_data
        )
        return nodes

    def test_basic_mapping(self):
        nodes = self._make_nodes(
            [
                {'entity': 'ent-1', 'translate': (1.0, 2.0, 3.0), 'stats': 'WPN_Sword'},
                {'entity': 'ent-2', 'translate': (4.0, 5.0, 6.0), 'stats': 'ARM_Boots'},
            ]
        )
        result = party.build_instance_entity_map(nodes)
        assert result[((1.0, 2.0, 3.0), 'WPN_Sword')] == 'ent-1'
        assert result[((4.0, 5.0, 6.0), 'ARM_Boots')] == 'ent-2'

    def test_empty_when_no_items_root(self):
        nodes = [{'name': 'Other', 'parent': -1, 'children': [], 'attrs': {}}]
        assert party.build_instance_entity_map(nodes) == {}

    def test_skips_missing_fields(self):
        # An item with no Stats field should not appear in the result.
        nodes = self._make_nodes(
            [
                {'entity': 'ent-1', 'translate': (1.0, 2.0, 3.0), 'stats': ''},
            ]
        )
        result = party.build_instance_entity_map(nodes)
        assert result == {}


# ---------------------------------------------------------------------------
# Integration tests using bundled fixture save files
# ---------------------------------------------------------------------------


def test_save_info():
    """--save-info section must appear and contain recognisable fields."""
    report = build_report(QUICKSAVE_MAIA, opts=Namespace(save_info=True))
    assert 'Save Name' in report
    assert 'Game Ver' in report
    assert 'Leader' in report


def test_no_spells():
    """--no-spells must omit the spells/abilities section; default keeps it."""
    assert 'Spells/Abilities' in build_report(QUICKSAVE_MAIA)
    report = build_report(QUICKSAVE_MAIA, opts=Namespace(no_spells=True))
    assert 'Spells/Abilities' not in report
    assert 'Equipped' in report  # the rest of the character section survives


def test_quests():
    """--quests must parse the Osiris story state and emit a quests section."""
    report = build_report(QUICKSAVE_MAIA, opts=Namespace(quests=True))
    assert 'QUEST & STORY STATE' in report
    # The Osiris version line proves the parser reached the binary format.
    assert 'Osiris version:' in report
    # A mid-campaign save should have at least a handful of in-progress quests.
    assert 'Quests in progress' in report


def test_thumbnail(tmp_path):
    """extract_thumbnail must write a valid WebP file and return dimensions."""
    frames = parser.extract_frames(QUICKSAVE_MAIA)
    out = tmp_path / 'thumb.webp'
    dims = lspk.extract_thumbnail(frames, str(out))
    assert out.exists()
    assert out.stat().st_size > 0
    # All observed saves use VP8X extended WebP.
    assert out.read_bytes()[:4] == b'RIFF'
    assert dims is not None
    w, h = dims
    assert w > 0 and h > 0


def test_carried():
    """--carried must emit a Carried / personal inventory section."""
    report = build_report(QUICKSAVE_MAIA, opts=Namespace(carried=True))
    assert 'Carried / personal inventory' in report


def test_exact_spellbooks():
    """Known class abilities must be present in each character's exact spell book."""
    model = gather_model(QUICKSAVE_MAIA)
    chars = {c.name: c for c in model.characters}
    assert 'Projectile_EldritchBlast' in {s.id for s in chars['Wyll'].spells}
    assert any('Shout_Rage' in s.id for s in chars['Karlach'].spells)


def test_spells_folded_in_text():
    """Default text output must fold sub-spells and basic actions with a count."""
    report = build_report(QUICKSAVE_MAIA)
    assert 'heuristic' not in report
    assert 'basic actions' in report


def test_all_spells_flag():
    """--all-spells must list everything: no folded sub-spell/basic-action counts."""
    report = build_report(QUICKSAVE_MAIA, opts=Namespace(all_spells=True))
    assert 'Spells/Abilities (' in report
    assert 'sub-spells' not in report
    assert 'basic actions' not in report


def test_gather_report_model_and_json():
    """The report model must be JSON-serialisable and structurally complete."""
    model = parser.gather_report(QUICKSAVE_MAIA, opts=Namespace(save_info=True))
    data = json.loads(parser.render_json(model))
    assert data['save_info']['save_name']
    chars = {c['name'] for c in data['characters']}
    assert {'Wyll', 'Karlach', 'Shadowheart'} <= chars
    wyll = next(c for c in data['characters'] if c['name'] == 'Wyll')
    assert any(s['id'] == 'Projectile_EldritchBlast' for s in wyll['spells'])
    assert wyll['equipped'] and wyll['carried']
    assert all('stats' in i and 'template_guid' in i for i in wyll['equipped'])


def test_parse_lsmf_spellbooks_direct():
    """parse_lsmf_spellbooks must return many non-trivial books from the blob."""
    frames = parser.extract_frames(QUICKSAVE_MAIA)
    nodes0 = lsf.parse_lsof(lsf.decomp_frame(frames['Globals.lsf']))
    blob = next(
        nd['attrs']['NewAge'] for nd in nodes0 if nd['name'] == 'NewAge' and nd['parent'] == -1
    )
    books = lsmf.parse_lsmf_spellbooks(blob)
    assert len(books) > 100  # party + NPCs all carry spell books
    classes = lsmf.parse_lsmf_classes(blob)
    named = {gamedata.CLASS_UUID_NAMES.get(c) for cls in classes.values() for c, _s, _l in cls}
    assert {'Warlock', 'Barbarian', 'Cleric', 'Fighter'} <= named


def test_stats_entity_link():
    """The template link must give the exact stats entity for every known character."""
    frames = parser.extract_frames(QUICKSAVE_MAIA)
    nodes0 = lsf.parse_lsof(lsf.decomp_frame(frames['Globals.lsf']))
    blob = next(
        nd['attrs']['NewAge'] for nd in nodes0 if nd['name'] == 'NewAge' and nd['parent'] == -1
    )
    wanted = {g.lower(): n for g, n in party.PARTY_ORIGINS.items()}
    wanted[party.PLAYER_CHAR_TEMPLATE.lower()] = '__player__'
    ents = lsmf.parse_lsmf_stats_entities(blob, wanted)
    # Ground-truth rows for this fixture (independently verified): the link
    # agrees with class-build matching for the whole party and camp.
    expected = {
        '__player__': 71,
        'Wyll': 250,
        'Karlach': 73,
        'Shadowheart': 75,
        'Astarion': 249,
        'Gale': 61,
        'Halsin': 58,
    }
    assert {k: ents[k] for k in expected} == expected
    classes = lsmf.parse_lsmf_classes(blob)
    levels = {'__player__': 7, 'Wyll': 7, 'Karlach': 7, 'Shadowheart': 7}
    levels |= {'Astarion': 6, 'Gale': 6, 'Halsin': 5}
    for name, lvl in levels.items():
        assert sum(level for _, _, level in classes[ents[name]]) == lvl, name


def test_honour_mode_dark_urge():
    """Honour-mode Dark Urge save: the Durge avatar is the player, fully attributed."""
    report = build_report(
        str(FIXTURE_DIR / 'honour_durge_nautiloid.lsv'), opts=Namespace(save_info=True)
    )
    assert 'RulesetHonour' in report
    assert 'The Dark Urge (player)' in report
    assert 'Sorcerer / StormSorcery' in report
    assert 'Quarterstaff' in report  # equipment attributed via the Durge template
    assert 'DarkUrge' not in report  # raw origin string never shown


def test_quicksave_328_identical_builds_and_hireling():
    """Save 328 ground truth: Maia and Shadowheart share an identical build
    (Cleric/LightDomain 7) yet get distinct sheets via the entity link, and
    the hireling resolves to his custom name with items attributed."""
    report = build_report(str(FIXTURE_DIR / 'quicksave_328.lsv'), opts=Namespace(save_info=True))
    assert 'Sir Fuzzalump (hireling)' in report
    assert 'ambiguous' not in report.split('CAMP COMPANIONS')[0]  # party section
    maia = report.split('Maia (player)')[1].split('Karlach')[0]
    sh = report.split('Shadowheart')[1].split('Sir Fuzzalump')[0]
    assert 'Cleric / LightDomain' in maia and 'Cleric / LightDomain' in sh
    assert 'WIS 18' in maia and 'DEX 18' in sh  # distinct sheets, same build
    assert '52/52' in maia and '59/59' in sh


def test_portraits_ground_truth():
    """Embedded portraits pair with creation-order names (Dan verified by eye)."""
    from bg3parser.lsmf import parse_lsmf_portraits

    def blob_of(path):
        frames = parser.extract_frames(path)
        nodes0 = lsf.parse_lsof(lsf.decomp_frame(frames['Globals.lsf']))
        return next(
            nd['attrs']['NewAge'] for nd in nodes0 if nd['name'] == 'NewAge' and nd['parent'] == -1
        )

    ports, guardian = parse_lsmf_portraits(blob_of(str(FIXTURE_DIR / 'quicksave_328.lsv')))
    assert [n for n, _ in ports] == [
        'Gale',
        'Maia',
        'Shadowheart',
        'Wyll',
        'Astarion',
        'Sir Fuzzalump',
        'Karlach',
        "Lae'zel",
    ]
    assert all(img[:4] == b'RIFF' for _, img in ports)
    assert guardian is not None and guardian[:4] == b'RIFF'

    ports, guardian = parse_lsmf_portraits(blob_of(QUICKSAVE_MAIA))
    assert [n for n, _ in ports] == [
        'Astarion',
        'Wyll',
        'Gale',
        'Maia',
        'Karlach',
        'Shadowheart',
        "Lae'zel",
    ]
    assert guardian is not None


def test_all_items():
    """--all-items must emit the full level inventory section."""
    report = build_report(QUICKSAVE_MAIA, opts=Namespace(all_items=True))
    assert 'ALL ITEMS ON CURRENT LEVEL' in report
    assert 'items total' in report


def test_limits():
    """--limits must emit the known-limitations note."""
    report = build_report(QUICKSAVE_MAIA, opts=Namespace(limits=True))
    assert 'LIMITS' in report
    assert 'Spell attribution' in report


def test_main_stdout(capsys):
    """main() with a save path must print the report to stdout."""
    with mock.patch('sys.argv', ['bg3save', QUICKSAVE_MAIA]):
        parser.main()
    captured = capsys.readouterr()
    assert 'BG3 Save File Report' in captured.out
    assert len(captured.out) > 1000


def test_main_output_file(tmp_path):
    """main() with an output path must write the report to the file."""
    out = tmp_path / 'report.txt'
    with mock.patch('sys.argv', ['bg3save', QUICKSAVE_MAIA, str(out)]):
        parser.main()
    assert out.exists()
    content = out.read_text(encoding='utf-8')
    assert 'BG3 Save File Report' in content


# ---------------------------------------------------------------------------
# Text output format tests
# ---------------------------------------------------------------------------


ALL_SECTION_OPTS = Namespace(
    save_info=True,
    quests=True,
    all_items=True,
    carried=True,
    limits=True,
)


class TestTextOutputFormat:
    """Golden-file tests for the plain-text render.

    The whole rendered report is compared byte-for-byte against a committed
    fixture under tests/fixtures/expected/, so any formatting change — spacing,
    ordering, a moved section — shows up as a reviewable diff rather than slipping
    past a handful of substring checks.

    Name resolution is pinned to the no-install fallback (internal names), the
    only output that is identical on every machine. Resolved-name output (friendly
    names, [Slot] annotations, spell folding) is exercised separately by
    TestResolvedRender, which is skipped unless a game install is detected.

    Regenerate every golden after an intentional formatting change with:
        BG3_UPDATE_GOLDEN=1 uv run pytest
    """

    def test_maia_default(self):
        assert_golden('maia_default.txt', render_golden(QUICKSAVE_MAIA))

    def test_maia_all_sections(self):
        assert_golden(
            'maia_all_sections.txt',
            render_golden(QUICKSAVE_MAIA, ALL_SECTION_OPTS),
        )

    def test_shadowheart_default(self):
        assert_golden(
            'shadowheart_default.txt',
            render_golden(SHADOWHEART_TUTORIAL, Namespace(quests=True)),
        )


# ---------------------------------------------------------------------------
# Enhanced render checks — only where a game install resolves display names.
# A full golden would drift across game-data versions, so these assert that the
# resolver-dependent rendering branches fire, not exact bytes.
# ---------------------------------------------------------------------------

GAME_DATA_AVAILABLE = gamedata.DisplayNames.load().available


@pytest.mark.skipif(not GAME_DATA_AVAILABLE, reason='no game install to resolve names')
class TestResolvedRender:
    """Exercises the rendering branches that only fire with resolved names."""

    def test_slot_annotations_present(self):
        report = build_report(QUICKSAVE_MAIA, opts=Namespace(verbose=True))
        assert re.search(
            r'\[(?:Breast|Helmet|Cloak|Gloves|Boots|Amulet|Ring|'
            r'Melee Main Weapon|Ranged Main Weapon)\]',
            report,
        )

    def test_friendly_names_replace_internal(self):
        # With a resolver, equipped lines should not be bare internal stats names.
        report = build_report(QUICKSAVE_MAIA)
        assert 'Phalar Aluve' in report
        assert 'WPN_Phalar_Aluve' not in report

    def test_spell_folding_in_header(self):
        report = build_report(QUICKSAVE_MAIA)
        assert re.search(r'Spells/Abilities \(\d+;.*(?:sub-spells|basic actions)', report)

    def test_all_spells_disables_folding(self):
        report = build_report(QUICKSAVE_MAIA, opts=Namespace(all_spells=True))
        assert not re.search(r'\+\d+ (?:sub-spells|basic actions)', report)


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
    report = build_report(SHADOWHEART_TUTORIAL)
    assert isinstance(report, str)
    assert len(report) > 500
    assert 'Shadowheart' in report


def test_shadowheart_quests():
    """Osiris parsing must work on the tutorial save's StorySave.bin."""
    report = build_report(SHADOWHEART_TUTORIAL, opts=Namespace(quests=True))
    assert 'QUEST & STORY STATE' in report
    assert 'Osiris version:' in report


# ---------------------------------------------------------------------------
# Equipment-block (ContainerSlotData cluster) classification — saves 292/294
# ---------------------------------------------------------------------------


class TestEquipmentCluster:
    """Unit tests for party.equipment_cluster()."""

    def test_tight_block(self):
        assert party.equipment_cluster([950, 952, 949, 956]) == (941, 964)

    def test_outlier_trimmed(self):
        # A single anchor far from the block (e.g. a stale-flagged item whose
        # slot has no competitor) must not stretch the window.
        lo, hi = party.equipment_cluster([174, 176, 179, 181, 183, 301])
        assert lo <= 174 and hi >= 183
        assert hi < 290

    def test_too_few_anchors(self):
        assert party.equipment_cluster([5]) is None
        assert party.equipment_cluster([]) is None


@pytest.mark.skipif(not GAME_DATA_AVAILABLE, reason='cluster anchors need stat-file slots')
def test_quicksave_292_karlach_dual_wield():
    """In-game ground truth for QuickSave_292: Karlach dual-wields the
    Githyanki Shortsword (main hand) with a Dagger (off hand); Jorgoral's
    Greatsword carries a stale equip bit but sits in a bag."""
    model = gather_model(QUICKSAVE_292)
    karlach = next(c for c in model.characters if c.name == 'Karlach')
    slots = {it.stats: it.slot for it in karlach.equipped}
    assert slots.get('WPN_Shortsword_Gith') == 'Melee Main Weapon'
    assert slots.get('WPN_Dagger') == 'Melee Offhand Weapon'
    assert 'MAG_Colossal_Greatsword' not in slots
    carried = {it.stats for it in karlach.carried}
    assert 'MAG_Colossal_Greatsword' in carried


@pytest.mark.skipif(not GAME_DATA_AVAILABLE, reason='cluster anchors need stat-file slots')
def test_quicksave_294_wyll_stale_phalar_and_shoes():
    """In-game ground truth for QuickSave_294: Wyll wields the Knife of the
    Undermountain King; Phalar Aluve has a stale equip bit but is in his
    inventory; the Evasive Shoes (no LSF signal at all) are equipped."""
    model = gather_model(QUICKSAVE_294)
    wyll = next(c for c in model.characters if c.name == 'Wyll')

    # Maia's lute is equipped (in-game verified) although its
    # ContainerSlotData row sits mid-backpack: an equipped instrument stays
    # in the grid, so the cluster rule must not demote virtual slots.
    maia = next(c for c in model.characters if c.name.startswith('Maia'))
    assert 'ARM_Instrument_Lute' in {it.stats for it in maia.equipped}

    slots = {it.stats: it.slot for it in wyll.equipped}
    assert slots.get('MAG_Duergar_Sword_KingsKnife') == 'Melee Main Weapon'
    assert slots.get('MAG_Safeguard_Shield') == 'Melee Offhand Weapon'
    assert slots.get('MAG_Evasive_Shoes') == 'Boots'
    assert 'UND_SwordInStone' not in slots
    carried = {it.stats for it in wyll.carried}
    assert 'UND_SwordInStone' in carried
    assert 'ARM_Boots_Leather' in carried
    assert 'MAG_Fire_HeatOnTakingFireDamage_Amulet' in carried


@pytest.mark.skipif(not GAME_DATA_AVAILABLE, reason='cluster anchors need stat-file slots')
def test_quicksave_296_duplicate_shortswords():
    """In-game ground truth for QuickSave_296: Karlach dual-wields two plain
    Shortswords while two more (identical stats name and template) sit in her
    inventory — per-instance classification via each copy's own
    ContainerSlotData rows."""
    model = gather_model(str(FIXTURE_DIR / 'quicksave_296.lsv'))
    karlach = next(c for c in model.characters if c.name == 'Karlach')
    swords = [it for it in karlach.equipped if it.stats == 'WPN_Shortsword']
    assert sorted(it.slot for it in swords) == [
        'Melee Main Weapon',
        'Melee Offhand Weapon',
    ]
    carried_swords = [it for it in karlach.carried if it.stats == 'WPN_Shortsword']
    assert len(carried_swords) == 2


def test_quicksave_296_stack_amounts():
    """In-game ground truth: Maia carries 766 gold, Wyll 2017, and Karlach's
    three Soul Coins are three single (unstacked) copies."""
    model = gather_model(str(FIXTURE_DIR / 'quicksave_296.lsv'))

    def counts(char_name, stats):
        char = next(c for c in model.characters if c.name.startswith(char_name))
        return [it.count for it in char.carried if it.stats == stats]

    assert counts('Maia', 'OBJ_GoldCoin') == [766]
    assert counts('Wyll', 'OBJ_GoldPile') == [2017]
    assert counts('Karlach', 'GLO_SoulCoin') == [1, 1, 1]


@pytest.mark.skipif(not GAME_DATA_AVAILABLE, reason='slot labels need stat-file slots')
def test_quicksave_286_physical_attachment_ground_truth():
    """In-game ground truth for QuickSave_286: Maia wields the Halberd of
    Vigilance (the flagged moonlantern stays carried) and Wyll wields the
    Knife of the Undermountain King (Phalar Aluve's equip bit is stale)."""
    model = gather_model(str(FIXTURE_DIR / 'quicksave_286.lsv'))
    maia = next(c for c in model.characters if c.name.startswith('Maia'))
    slots = {it.stats: it.slot for it in maia.equipped}
    assert slots.get('MAG_PoR_OfVigilance_Halberd') == 'Melee Main Weapon'
    assert 'Quest_SCL_MoonlanternWithPixie' not in slots
    wyll = next(c for c in model.characters if c.name == 'Wyll')
    slots = {it.stats: it.slot for it in wyll.equipped}
    assert slots.get('MAG_Duergar_Sword_KingsKnife') == 'Melee Main Weapon'
    assert 'UND_SwordInStone' not in slots


@pytest.mark.skipif(not GAME_DATA_AVAILABLE, reason='slot labels need stat-file slots')
def test_quicksave_291_ring_order_ground_truth():
    """In-game ground truth for QuickSave_291 (checked on Karlach's panel):
    of her two rings, the one with the earlier ContainerSlotData row sits in
    the first (upper) ring slot."""
    model = gather_model(str(FIXTURE_DIR / 'quicksave_291.lsv'))
    karlach = next(c for c in model.characters if c.name == 'Karlach')
    slots = {it.stats: it.slot for it in karlach.equipped}
    assert slots.get('MAG_Harpers_RingOfProjection') == 'Ring'
    assert slots.get('MAG_FlamingFist_ScoutRing') == 'Ring 2'


def test_quicksave_302_multi_member_stacks():
    """In-game ground truth for QuickSave_302: Maia has 4 Karabasan's Gifts
    and Karlach 3 Soul Coins — multi-member stack records must not multiply
    each copy by a group total (4 copies were rendering as x16)."""
    model = gather_model(str(FIXTURE_DIR / 'quicksave_302.lsv'))
    maia = next(c for c in model.characters if c.name.startswith('Maia'))
    gifts = [it.count for it in maia.carried if it.stats == 'UNI_LOW_KarabasansGift_Grenade']
    assert gifts == [1, 1, 1, 1]
    karlach = next(c for c in model.characters if c.name == 'Karlach')
    coins = [it.count for it in karlach.carried if it.stats == 'GLO_SoulCoin']
    assert coins == [1, 1, 1]


@pytest.mark.skipif(not GAME_DATA_AVAILABLE, reason='item filters need slots and rarity')
def test_report_views_item_filters():
    """The magic/equipment filters and the slot-keyed equipped view."""
    model = gather_model(QUICKSAVE_MAIA)
    dn = gamedata.DisplayNames.load()

    magic = report_views.save_view(model, dn, ('party', 'camp_chest'), 'summary', 'magic', 'none')
    equip = report_views.save_view(
        model, dn, ('party', 'camp_chest'), 'summary', 'equipment', 'none'
    )
    every = report_views.save_view(model, dn, ('party', 'camp_chest'), 'summary', 'all', 'none')

    # Filters nest: magic ⊆ equipment ⊆ all.
    def chest_names(view):
        return [i['name'] for i in view['camp_chest']['items']]

    assert set(chest_names(magic)) <= set(chest_names(equip))
    assert len(chest_names(equip)) <= len(chest_names(every))
    # Every magic-filtered item is equippable and rarer than common.
    for item in magic['camp_chest']['items']:
        assert item.get('slot') and item.get('rarity')

    for char in magic['party']:
        eq = char['equipped']
        # Canonical slots always reported; entries carry names.
        assert set(report_views.CANONICAL_SLOTS) <= set(eq)
        worn = [v for v in eq.values() if isinstance(v, dict)]
        assert all(v.get('name') for v in worn)
        # Gold is folded into one number, never listed as an item.
        assert all(i['name'] not in ('Gold', 'Gold Pile') for i in char.get('carried', []))
        assert isinstance(char.get('gold', 0), int)
        # Ability scores ride along in the summary.
        assert set(char.get('abilities', {})) in (set(), {'str', 'dex', 'con', 'int', 'wis', 'cha'})


def test_item_effects_table():
    """The effects table resolves known item tooltips (Hellrider's Pride)."""
    from bg3parser.effects import Effects

    fx = Effects.load()
    if not fx.available:
        pytest.skip('no game install or BG3_EFFECTS_JSON')
    lines = fx.lines('DEN_HellridersPride')
    assert any('Helm' in ln and 'heal another creature' in ln for ln in lines)
    # Plain weapons carry their damage line; unknown stats return nothing.
    assert any(ln.startswith('Damage: 1d6') for ln in fx.lines('WPN_Shortsword'))
    assert fx.lines('NOT_A_REAL_STATS_NAME') == []


def test_mcp_item_info_and_effects():
    """item_info answers 'what does X do'; parse_save annotates on request."""
    pytest.importorskip('mcp')
    from bg3parser import mcp_server

    if not mcp_server.shared_effects().available:
        pytest.skip('no game install or BG3_EFFECTS_JSON')
    batch = mcp_server.item_info(['hellrider', 'spellsparkler'])
    pride = next(h for h in batch['hellrider'] if h['stats'] == 'DEN_HellridersPride')
    assert pride['slot'] == 'Gloves'
    assert any('heal another creature' in ln for ln in pride['effects'])
    assert any('Lightning Charge' in ln for h in batch['spellsparkler'] for ln in h['effects'])

    report = mcp_server.parse_save(
        QUICKSAVE_MAIA, sections=['party'], items='magic', quests=False, effects=True
    )
    annotated = [
        it
        for c in report['party']
        for it in list(c['equipped'].values()) + c.get('carried', [])
        if isinstance(it, dict) and it.get('effects')
    ]
    assert annotated, 'expected at least one effects-annotated item'
    # Without the flag, no effects keys appear.
    plain = mcp_server.parse_save(QUICKSAVE_MAIA, sections=['party'], quests=False)
    assert 'effects' not in str(plain)


def test_quicksave_341_chest_stack_total():
    """In-game ground truth for QuickSave_341: the camp chest holds a stack
    of 5 Scrolls of Revivify, stored as a 3-member stack record whose entry
    amounts sum to 5 — the record total is the in-game count, with the
    surplus credited to the first member (was reported as 3)."""
    model = gather_model(str(FIXTURE_DIR / 'quicksave_341.lsv'))
    scrolls = sum(it.count for it in model.camp_chest or [] if it.stats == 'OBJ_Scroll_Revivify')
    assert scrolls == 5


def test_mcp_server_tools():
    """The MCP tools resolve fixtures and return the view shape."""
    pytest.importorskip('mcp')
    from bg3parser import mcp_server

    report = mcp_server.parse_save(QUICKSAVE_MAIA, quests=False)
    assert report['save_info']['save_name'] == 'QuickSave_242'
    assert report['party'] and report['camp_companions']
    assert all(not c.get('at_camp') for c in report['party'])
    assert all(c['at_camp'] for c in report['camp_companions'])
    assert 'quests' not in report
    with pytest.raises(FileNotFoundError):
        mcp_server.parse_save('no-such-save-xyz')
    with pytest.raises(ValueError, match='sections'):
        mcp_server.parse_save(QUICKSAVE_MAIA, sections=['no-such-section'])
    with pytest.raises(ValueError, match='detail'):
        mcp_server.parse_save(QUICKSAVE_MAIA, detail='everything')


def test_mcp_server_sections_and_detail():
    """Sections gate the output; summary trims what full keeps."""
    pytest.importorskip('mcp')
    from bg3parser import mcp_server

    meta_only = mcp_server.parse_save(QUICKSAVE_MAIA, sections=['meta'], quests=False)
    assert 'save_info' in meta_only
    assert 'party' not in meta_only and 'camp_chest' not in meta_only

    summary = mcp_server.parse_save(QUICKSAVE_MAIA, sections=['party'], quests=False)
    full = mcp_server.parse_save(QUICKSAVE_MAIA, sections=['party'], detail='full', quests=False)
    s_maia = next(c for c in summary['party'] if c['name'].startswith('Maia'))
    f_maia = next(c for c in full['party'] if c['name'].startswith('Maia'))
    # Summary keys gear by slot; canonical slots are always present.
    assert set(report_views.CANONICAL_SLOTS) <= set(s_maia['equipped'])
    assert 'spells' not in s_maia and 'template_guid' not in str(s_maia)
    # Full keeps the dataclass shape: spell book entries with prepared flags.
    assert isinstance(f_maia['equipped'], list)
    assert any(s.get('prepared') is not None for s in f_maia['spells'] or [])


def test_mcp_server_parse_cache():
    """A second call on the same save reuses the parsed report; a changed
    fingerprint or a quest upgrade reparses."""
    pytest.importorskip('mcp')
    from bg3parser import mcp_server

    mcp_server.parse_cache.clear()
    calls = []
    real_gather = mcp_server.gather_report

    def counting_gather(path, frames=None, opts=None):
        calls.append(getattr(opts, 'quests', False))
        return real_gather(path, frames=frames, opts=opts)

    with mock.patch.object(mcp_server, 'gather_report', counting_gather):
        mcp_server.parse_save(QUICKSAVE_MAIA, quests=False)
        mcp_server.parse_save(QUICKSAVE_MAIA, detail='full', items='magic', quests=False)
        assert calls == [False]
        # Wanting quests upgrades the cached quest-less report...
        mcp_server.parse_save(QUICKSAVE_MAIA, sections=['quests'])
        assert calls == [False, True]
        # ...and the upgraded report serves quest-less calls too.
        mcp_server.parse_save(QUICKSAVE_MAIA, quests=False)
        assert calls == [False, True]
    mcp_server.parse_cache.clear()
