"""Boost functors rendered as the English a tooltip would show.

The game's stat files describe item mechanics as functor strings
("AC(1);UnlockSpell(Shout_BootsOfSpeed)"). translate_boosts() turns one
into display lines ("+1 Armour Class", "Grants spell: Click Heels").
Bookkeeping the game never surfaces (Tag, HiddenDuringCinematic, the
can't-be-crit pair on world objects) is suppressed; functors and IF()
conditions outside the known vocabulary fall back to their raw text so
nothing disappears silently. Build-time only: effects.py calls this while
building effects.json, where spell and passive display names are at hand.
"""

import re

FUNCTOR_RE = re.compile(r'(\w+)\s*\((.*)\)$', re.DOTALL)

HAS_PASSIVE_RE = re.compile(r"(not\s+)?HasPassive\(\s*'([^']+)'\s*,\s*context\.Source\s*\)")

ROLL_TARGETS = {
    'SavingThrow': 'saving throws',
    'Attack': 'attack rolls',
    'MeleeWeaponAttack': 'melee attack rolls',
    'RangedWeaponAttack': 'ranged attack rolls',
    'SkillCheck': 'skill checks',
    'RawAbility': 'ability checks',
}

RESIST_STATES = {
    'Resistant': 'Resistance to {0} damage',
    'Vulnerable': 'Vulnerable to {0} damage',
    'Immune': 'Immunity to {0} damage',
}


def split_top(raw: str, sep: str = ';') -> list[str]:
    """Split on top-level separators (functor args nest in parentheses)."""
    parts, depth, cur = [], 0, ''
    for ch in raw:
        if ch == sep and depth == 0:
            parts.append(cur)
            cur = ''
            continue
        depth += ch == '('
        depth -= ch == ')'
        cur += ch
    if cur.strip():
        parts.append(cur)
    return parts


def peel_condition(seg: str) -> tuple[str | None, str]:
    """('cond', 'Functor(...)') from 'IF(cond):Functor(...)', else (None, seg)."""
    m = re.match(r'IF\s*\(', seg)
    if not m:
        return None, seg
    depth, i = 1, m.end()
    while i < len(seg) and depth:
        depth += seg[i] == '('
        depth -= seg[i] == ')'
        i += 1
    rest = seg[i:].lstrip()
    if depth or not rest.startswith(':'):
        return None, seg
    return seg[m.end() : i - 1].strip(), rest[1:].strip()


def translate_condition(cond: str, passive_names: dict[str, str]) -> str | None:
    """English for a known IF() condition, None outside the vocabulary."""
    m = HAS_PASSIVE_RE.fullmatch(cond)
    if m:
        name = passive_names.get(m.group(2), m.group(2))
        return ('unless you have ' if m.group(1) else 'if you have ') + name
    if re.fullmatch(r'IsConcentrating\(\s*context\.Source\s*\)', cond):
        return 'while concentrating'
    return None


def signed(n: str) -> str:
    return n if n.startswith(('-', '+')) else f'+{n}'


def suppressed(fn: str, args: list[str]) -> bool:
    """Boosts the game itself never shows on a tooltip."""
    if fn in ('Tag', 'HiddenDuringCinematic'):
        return True
    return (
        fn == 'CriticalHit' and len(args) == 3 and args[0] == 'AttackTarget' and args[2] == 'Never'
    )


def render_functor(fn: str, args: list[str], spell_names: dict[str, str]) -> str | None:
    """English for a known functor, None when outside the vocabulary."""
    try:
        if fn == 'AC':
            return f'{signed(args[0])} Armour Class'
        if fn == 'Ability':
            line = f'{signed(args[1])} {args[0]}'
            if len(args) > 2 and args[2]:
                line += f' (up to {args[2]})'
            return line
        if fn == 'AbilityOverrideMinimum':
            return f'Raises {args[0]} to {args[1]} (unless higher)'
        if fn in ('Advantage', 'Disadvantage'):
            if args[0] == 'Skill':
                return f'{fn} on {args[1]} checks'
            if args[0] == 'SavingThrow':
                what = f'{args[1]} saving throws' if len(args) > 1 else 'saving throws'
                return f'{fn} on {what}'
            return None
        if fn == 'Skill':
            return f'{signed(args[1])} to {args[0]} checks'
        if fn == 'RollBonus':
            what = ROLL_TARGETS.get(args[0], f'{args[0]} rolls')
            if args[0] == 'SavingThrow' and len(args) > 2:
                what = f'{args[2]} saving throws'
            return f'{signed(args[1])} to {what}'
        if fn == 'Resistance':
            tpl = RESIST_STATES.get(args[1])
            return tpl.format(args[0]) if tpl else None
        if fn == 'IgnoreResistance':
            return f'Ignores {args[0]} resistance'
        if fn == 'UnlockSpell':
            return f'Grants spell: {spell_names.get(args[0], args[0])}'
        if fn == 'WeaponEnchantment':
            return f'Weapon enchantment +{args[0]}'
        if fn == 'WeaponProperty':
            return 'Magical weapon' if args[0] == 'Magical' else None
        if fn in ('WeaponDamage', 'CharacterWeaponDamage'):
            dtype = f' {args[1]}' if len(args) > 1 else ''
            return f'Extra {args[0]}{dtype} damage'
        if fn == 'Proficiency':
            return f'Proficiency with {args[0]}'
        if fn == 'ProficiencyBonus':
            return (
                f'Add proficiency bonus to {args[1]} saving throws'
                if args[0] == 'SavingThrow'
                else None
            )
        if fn == 'SpellSaveDC':
            return f'{signed(args[0])} Spell Save DC'
        if fn == 'ActionResource':
            return f'{signed(args[1])}m movement speed' if args[0] == 'Movement' else None
        if fn == 'StatusImmunity':
            return f'Immune to {args[0]}'
        if fn == 'IgnoreFallDamage':
            return 'Immune to fall damage'
        if fn == 'FallDamageMultiplier':
            return 'No fall damage' if args[0] == '0' else None
        if fn == 'CannotBeDisarmed':
            return 'Cannot be disarmed'
        if fn == 'Invulnerable':
            return 'Invulnerable'
        if fn == 'ItemReturnToOwner':
            return 'Returns to its owner when thrown'
    except IndexError:
        return None
    return None


def translate_boosts(
    raw: str,
    spell_names: dict[str, str] | None = None,
    passive_names: dict[str, str] | None = None,
) -> list[str]:
    """The raw Boosts field as display lines; suppressed entries drop out."""
    spell_names = spell_names or {}
    passive_names = passive_names or {}
    out: list[str] = []
    for seg in split_top(raw):
        seg = seg.strip()
        if not seg:
            continue
        cond, body = peel_condition(seg)
        m = FUNCTOR_RE.fullmatch(body)
        if m:
            arg_text = m.group(2).strip()
            args = [a.strip() for a in split_top(arg_text, ',')] if arg_text else []
            if suppressed(m.group(1), args):
                continue
            line = render_functor(m.group(1), args, spell_names) or body
        else:
            line = body
        if cond is not None:
            known = translate_condition(cond, passive_names)
            line = f'{line} ({known})' if known else f'If {cond}: {line}'
        out.append(line)
    return out
