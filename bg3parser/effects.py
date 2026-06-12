"""Item effect extraction: tooltip-grade text from the game's stat files.

An item's mechanics live in three places, all resolved through the same
`using` inheritance chain as slots and rarity:

- `PassivesOnEquip` / `StatusOnEquip` name entries in Passive.txt /
  Status_*.txt, whose DisplayName/Description handles localize to the
  tooltip text the game shows ("Helm's Protection: When you heal another
  creature, ...").
- `Boosts` / `DefaultBoosts`: machine-readable functor strings ("AC(1)",
  "UnlockSpell(Target_MistyStep)"), translated to tooltip English by
  boosts.translate_boosts; the raw string is kept under `boosts_raw`.
- Weapon damage and armour class fields, for swap comparisons.

build_effects_map() returns {stats name: record} for every entry that has
any of those; results are cached like the display-name table, and
BG3_EFFECTS_JSON points consumers at the committed data/effects.json on
machines without a game install.
"""

import hashlib
import json
import os
import re

from .boosts import split_top, translate_boosts
from .gamedata import (
    LOCA_FILE,
    LOCA_PAK,
    STAT_ITEM_FILE_RE,
    STAT_ITEM_PAKS,
    find_game_data_dir,
    parse_loca,
)
from .lspk import lspk_extract, lspk_filelist

# Bump when the extraction logic changes so stale caches are not reused.
EFFECTS_SCHEMA_VERSION = 2

PASSIVE_STATUS_FILE_RE = re.compile(r'/Stats/Generated/Data/(?:Passive|Status_[A-Z]+)\.txt$')
SPELL_FILE_RE = re.compile(r'/Stats/Generated/Data/Spell_.*\.txt$')

CHAIN_LIMIT = 24


def parse_stat_blocks(text: str) -> dict[str, dict[str, str]]:
    """All `new entry` blocks of a stats file as {name: {field: value}}."""
    out: dict[str, dict[str, str]] = {}
    for bm in re.finditer(r'^new entry "([^"]+)"', text, re.MULTILINE):
        start = bm.end()
        nb = re.search(r'^new entry', text[start:], re.MULTILINE)
        block = text[start : start + (nb.start() if nb else len(text))]
        fields = dict(re.findall(r'^data "([^"]+)" "([^"]*)"', block, re.MULTILINE))
        using_m = re.search(r'^using "([^"]+)"', block, re.MULTILINE)
        if using_m:
            fields['__using'] = using_m.group(1)
        prev = out.get(bm.group(1))
        if prev is None:
            out[bm.group(1)] = fields
        else:
            # Later files (load order) override field-by-field; self-referential
            # `using` (Honour-mode value patches) must not introduce loops.
            if fields.get('__using') == bm.group(1):
                fields.pop('__using')
            prev.update(fields)
    return out


def chain_field(entries: dict[str, dict], name: str, field: str) -> str | None:
    """A field's value, following the `using` chain until set."""
    cur: str | None = name
    for _ in range(CHAIN_LIMIT):
        e = entries.get(cur or '')
        if e is None:
            return None
        if field in e and e[field] != '':
            return e[field]
        nxt = e.get('__using')
        if not nxt or nxt == cur:
            return None
        cur = nxt
    return None


def display_names(entries: dict[str, dict], handle_to_text: dict[str, str]) -> dict[str, str]:
    """{stats name: localized DisplayName}, following the `using` chain."""
    out: dict[str, str] = {}
    for name in entries:
        handle = (chain_field(entries, name, 'DisplayName') or '').split(';')[0]
        txt = handle_to_text.get(handle)
        if txt:
            out[name] = txt
    return out


def prettify_param(param: str) -> str:
    """'DealDamage(2, Piercing)' -> '2 Piercing'; 'Distance(12)' -> '12 m'."""
    param = param.strip()
    m = re.fullmatch(r'(\w+)\((.*)\)', param)
    if not m:
        return param
    fn, args = m.group(1), m.group(2).strip()
    if fn == 'Distance':
        return f'{args} m'
    return args.replace(',', ' ').replace('  ', ' ')


def localized_effect(
    fields: dict[str, str], handle_to_text: dict[str, str]
) -> dict[str, str] | None:
    """{name, desc} for a passive/status entry, or None without a description."""

    def text(field: str) -> str | None:
        handle = fields.get(field, '').split(';')[0]
        t = handle_to_text.get(handle)
        return t if t and '%%%' not in t else None

    desc = text('Description')
    if not desc:
        return None
    params = split_top(fields.get('DescriptionParams', ''))
    for i, p in enumerate(params, start=1):
        desc = desc.replace(f'[{i}]', prettify_param(p))
    desc = re.sub(r'<[^>]+>', '', desc)  # strip markup tags (<LSTag ...> etc.)
    return {'name': text('DisplayName') or '', 'desc': desc}


def cache_path(data_dir: str) -> str:
    sig_parts = [f'schema:{EFFECTS_SCHEMA_VERSION}']
    for pak in {*STAT_ITEM_PAKS, LOCA_PAK}:
        fp = os.path.join(data_dir, pak)
        try:
            st = os.stat(fp)
            sig_parts.append(f'{pak}:{st.st_mtime_ns}:{st.st_size}')
        except OSError:
            pass
    sig = hashlib.md5('|'.join(sorted(sig_parts)).encode()).hexdigest()[:16]
    cdir = os.path.join(
        os.environ.get('XDG_CACHE_HOME', os.path.expanduser('~/.cache')),
        'bg3-savefile-parser',
    )
    os.makedirs(cdir, exist_ok=True)
    return os.path.join(cdir, f'effects-{sig}.json')


def build_effects_map(data_dir: str) -> dict[str, dict]:
    """{stats name: {passives, statuses, boosts, boosts_raw, damage, ac}} from game data."""
    cache = os.environ.get('BG3_EFFECTS_JSON') or cache_path(data_dir)
    try:
        with open(cache, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        pass

    handle_to_text = parse_loca(lspk_extract(os.path.join(data_dir, LOCA_PAK), LOCA_FILE))

    items: dict[str, dict[str, str]] = {}
    effects_src: dict[str, dict[str, str]] = {}  # passives and statuses share a namespace
    spells_src: dict[str, dict[str, str]] = {}
    for pak_name in STAT_ITEM_PAKS:
        pak_path = os.path.join(data_dir, pak_name)
        try:
            with open(pak_path, 'rb') as fh:
                flist = lspk_filelist(fh)
        except (OSError, ValueError):
            continue
        for f in sorted(flist):
            target = None
            if STAT_ITEM_FILE_RE.search(f):
                target = items
            elif PASSIVE_STATUS_FILE_RE.search(f):
                target = effects_src
            elif SPELL_FILE_RE.search(f):
                target = spells_src
            if target is None:
                continue
            try:
                text = lspk_extract(pak_path, f).decode('utf-8', 'replace')
            except (OSError, KeyError, ValueError):
                continue
            for name, fields in parse_stat_blocks(text).items():
                prev = target.get(name)
                if prev is None:
                    target[name] = fields
                else:
                    if fields.get('__using') == name:
                        fields.pop('__using')
                    prev.update(fields)

    spell_names = display_names(spells_src, handle_to_text)
    passive_names = display_names(effects_src, handle_to_text)

    out: dict[str, dict] = {}
    for name in items:
        rec: dict = {}
        passives = chain_field(items, name, 'PassivesOnEquip')
        if passives:
            resolved = [
                eff
                for p in passives.split(';')
                if p.strip() and (fields := effects_src.get(p.strip()))
                if (eff := localized_effect(fields, handle_to_text))
            ]
            if resolved:
                rec['passives'] = resolved
        statuses = chain_field(items, name, 'StatusOnEquip')
        if statuses:
            resolved = [
                eff
                for s in statuses.split(';')
                if s.strip() and (fields := effects_src.get(s.strip()))
                if (eff := localized_effect(fields, handle_to_text))
            ]
            if resolved:
                rec['statuses'] = resolved
        boosts = ';'.join(
            b
            for b in (chain_field(items, name, 'Boosts'), chain_field(items, name, 'DefaultBoosts'))
            if b
        )
        if boosts:
            rec['boosts_raw'] = boosts
            lines = translate_boosts(boosts, spell_names, passive_names)
            if lines:
                rec['boosts'] = lines
        damage = chain_field(items, name, 'Damage')
        if damage:
            dtype = chain_field(items, name, 'Damage Type') or ''
            rec['damage'] = f'{damage} {dtype}'.strip()
        ac = chain_field(items, name, 'ArmorClass')
        if ac:
            rec['ac'] = int(ac) if ac.isdigit() else ac
        if rec:
            out[name] = rec

    try:
        with open(cache, 'w', encoding='utf-8') as fh:
            json.dump(out, fh)
    except OSError:
        pass
    return out


class Effects:
    """Lookup of an item's effect record by stats name."""

    def __init__(self, table: dict[str, dict]):
        self.table = table

    @classmethod
    def load(cls) -> 'Effects':
        data_dir = find_game_data_dir()
        if not data_dir and not os.environ.get('BG3_EFFECTS_JSON'):
            return cls({})
        try:
            return cls(build_effects_map(data_dir or ''))
        except Exception:  # effect resolution must never break a report
            return cls({})

    @property
    def available(self) -> bool:
        return bool(self.table)

    def for_stats(self, stats: str) -> dict | None:
        return self.table.get(stats)

    def lines(self, stats: str) -> list[str]:
        """The record flattened to display lines ('Name: description.')."""
        rec = self.table.get(stats)
        if not rec:
            return []
        out = [
            f'{eff["name"]}: {eff["desc"]}' if eff['name'] else eff['desc']
            for eff in rec.get('passives', []) + rec.get('statuses', [])
        ]
        if 'damage' in rec:
            out.append(f'Damage: {rec["damage"]}')
        if 'ac' in rec:
            out.append(f'Armour Class: {rec["ac"]}')
        boosts = rec.get('boosts')
        if isinstance(boosts, list):  # legacy artifacts held a raw string here
            out.extend(boosts)
        return out
