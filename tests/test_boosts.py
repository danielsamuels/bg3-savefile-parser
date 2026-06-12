"""translate_boosts: functor strings to tooltip-style English."""

import pytest

from bg3parser.boosts import translate_boosts

CASES = [
    ('AC(1)', ['+1 Armour Class']),
    ('Ability(Charisma, 2, 22)', ['+2 Charisma (up to 22)']),
    ('Ability(Charisma, -1)', ['-1 Charisma']),
    ('Ability(Constitution, 2, 20, true)', ['+2 Constitution (up to 20)']),
    ('AbilityOverrideMinimum(Intelligence,19)', ['Raises Intelligence to 19 (unless higher)']),
    ('Advantage(Skill,Perception)', ['Advantage on Perception checks']),
    ('Advantage(SavingThrow, Constitution)', ['Advantage on Constitution saving throws']),
    ('Disadvantage(Skill,Stealth)', ['Disadvantage on Stealth checks']),
    ('Skill(Perception,2)', ['+2 to Perception checks']),
    ('RollBonus(SavingThrow, 1, Strength)', ['+1 to Strength saving throws']),
    ('RollBonus(SavingThrow, 1)', ['+1 to saving throws']),
    ('Resistance(Fire, Resistant)', ['Resistance to Fire damage']),
    ('Resistance(Bludgeoning, Vulnerable)', ['Vulnerable to Bludgeoning damage']),
    ('IgnoreResistance(Piercing,Resistant)', ['Ignores Piercing resistance']),
    ('WeaponEnchantment(2)', ['Weapon enchantment +2']),
    ('WeaponProperty(Magical)', ['Magical weapon']),
    ('WeaponDamage(1d10, Necrotic)', ['Extra 1d10 Necrotic damage']),
    ('CharacterWeaponDamage(1d6,Necrotic)', ['Extra 1d6 Necrotic damage']),
    ('Proficiency(Battleaxes)', ['Proficiency with Battleaxes']),
    ('ProficiencyBonus(SavingThrow,Wisdom)', ['Add proficiency bonus to Wisdom saving throws']),
    ('SpellSaveDC(1)', ['+1 Spell Save DC']),
    ('ActionResource(Movement,3,0)', ['+3m movement speed']),
    ('StatusImmunity(BURNING)', ['Immune to BURNING']),
    ('IgnoreFallDamage()', ['Immune to fall damage']),
    ('FallDamageMultiplier(0)', ['No fall damage']),
    ('CannotBeDisarmed()', ['Cannot be disarmed']),
    ('Invulnerable()', ['Invulnerable']),
    ('ItemReturnToOwner()', ['Returns to its owner when thrown']),
    # Bookkeeping the game never shows is suppressed outright.
    ('Tag(CAMPSUPPLIES)', []),
    ('HiddenDuringCinematic()', []),
    ('CriticalHit(AttackTarget,Failure,Never);CriticalHit(AttackTarget,Success,Never)', []),
    # Unknown functors and odd records fall back to their raw text.
    ('DamageReduction(All, Threshold, 1000)', ['DamageReduction(All, Threshold, 1000)']),
    ('CriticalHit(AttackRoll,Success,Always)', ['CriticalHit(AttackRoll,Success,Always)']),
    ('Advantage(AllAbilities)', ['Advantage(AllAbilities)']),
    ('NotAFunctor', ['NotAFunctor']),
]


@pytest.mark.parametrize(('raw', 'expected'), CASES)
def test_translate_boosts(raw, expected):
    assert translate_boosts(raw) == expected


def test_spell_names_and_multi_segment():
    lines = translate_boosts(
        'UnlockSpell(Shout_BootsOfSpeed);Resistance(Cold, Resistant);Tag(X)',
        spell_names={'Shout_BootsOfSpeed': 'Click Heels'},
    )
    assert lines == ['Grants spell: Click Heels', 'Resistance to Cold damage']


def test_unlock_spell_falls_back_to_stats_name():
    assert translate_boosts('UnlockSpell(Target_Mystery)') == ['Grants spell: Target_Mystery']


def test_known_conditions_become_parentheticals():
    known = translate_boosts(
        "IF(not HasPassive('MediumArmorMaster', context.Source)):Disadvantage(Skill,Stealth)",
        passive_names={'MediumArmorMaster': 'Medium Armour Master'},
    )
    assert known == ['Disadvantage on Stealth checks (unless you have Medium Armour Master)']
    positive = translate_boosts("IF(HasPassive('X', context.Source)):AC(1)")
    assert positive == ['+1 Armour Class (if you have X)']
    conc = translate_boosts('IF(IsConcentrating(context.Source)):WeaponDamage(1d4,Poison)')
    assert conc == ['Extra 1d4 Poison damage (while concentrating)']


def test_unknown_conditions_keep_their_raw_text():
    lines = translate_boosts(
        "IF (Tagged('ACT2_TWN_HOSPITAL_NURSE',context.Source)):UnlockSpell(Target_Surgery)"
    )
    assert lines == [
        "If Tagged('ACT2_TWN_HOSPITAL_NURSE',context.Source): Grants spell: Target_Surgery"
    ]


def test_empty_and_blank_input():
    assert translate_boosts('') == []
    assert translate_boosts(' ; ; ') == []
