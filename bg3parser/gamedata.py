"""Display-name and stat resolution from installed game data."""

import hashlib
import json
import os
import re
import struct

from . import lsx
from .lsf import parse_lsof
from .lspk import lspk_extract, lspk_filelist

# Class / subclass UUIDs from the game's ClassDescriptions.lsx (Shared.pak).
# These are static shipped constants; embedded so exact spell-book attribution
# works without a game install. Used to match LSMF ClassesComponent entries
# against the (Main, Sub) class names in the save's Info.json.
CLASS_UUID_NAMES = {
    'e6a0eb75-7a01-4f40-8563-24ba2615e99b': 'AbjurationSchool',
    'b36d247e-d39f-4ae9-9476-3ec315c55789': 'Ancients',
    'ede4778e-7602-440f-9075-b4bc8dc31cea': 'ArcaneTrickster',
    '733ddf8c-9ec4-4c5a-85e3-c70fd3df3c24': 'Archfey',
    'b53a8061-f31d-4985-adfe-d4d691a918d9': 'Assassin',
    'd8cadb42-0ff9-4049-afaf-e5d78d06a399': 'Barbarian',
    '92cd50b6-eb1b-4824-8adb-853e90c34c90': 'Bard',
    'e668c6f1-5149-4b10-ab7e-3637ed444066': 'BattleMaster',
    '6fd9547d-cc28-400e-bfa9-3a85baa70f24': 'BeastMaster',
    '32eee7d8-1b2f-4de5-b9ee-78fbd286c6ef': 'BerserkerPath',
    '0a01dc6b-ab1a-4c0e-8a5e-4787fe1f2caf': 'Champion',
    '7458da78-34b7-4150-a42f-37197ab04510': 'CircleOfTheLand',
    '3eab0689-e51b-4634-a690-0375d3cb2716': 'CircleOfTheMoon',
    '4b61af6c-4a44-436e-aa0a-0d11a2d6b8ee': 'CircleOfTheSpores',
    '114e7aee-d1d4-4371-8d90-8a2080592faf': 'Cleric',
    '7a3feb8d-dda7-46ec-9029-1f302f537432': 'ConjurationSchool',
    '1c761ad0-6f5f-409e-ac1d-ddf6f85c1fc4': 'Devotion',
    '7577b0e1-a517-4f82-8f72-05a227dc5e88': 'DivinationSchool',
    '36286b0a-26f9-4b4e-9311-fd1404301d20': 'DraconicBloodline',
    '457d0a6e-9da8-4f95-a225-18382f0e94b5': 'Druid',
    'b722614a-303f-411a-bb19-a1882ad1f4cc': 'EldritchKnight',
    '46d31950-6917-444e-ac87-706702825215': 'EnchantmentSchool',
    'c059dca1-c17d-4dce-8260-83ede5070eac': 'EvocationSchool',
    '8866db28-7dda-4fd6-93ed-20eca16314f0': 'Fiend',
    '721dfac3-92d4-41f5-b773-b7072a86232f': 'Fighter',
    '22894c32-54cf-49ea-b366-44bfcf01bb2a': 'FourElements',
    'd5f10e55-84e3-409b-aa64-2098c9550319': 'GloomStalker',
    'e1e4a21f-9405-46ec-81a0-ccc8d58d9736': 'GreatOldOne',
    '0aa1cff9-c45f-4d00-a95b-99a7aa96dd06': 'Hunter',
    '436c9e1a-3a39-48dd-b753-7cee1bd19c00': 'IllusionSchool',
    'ebe18794-b5e1-41c4-befa-4b9d6922b0ec': 'KnowledgeDomain',
    '4b5da2f5-b999-4623-8bff-a63df5560fb3': 'LifeDomain',
    'c54d7591-b305-4f22-b2a7-1bf5c4a3470a': 'LightDomain',
    'd21368ac-c776-465c-9dcf-6123dd52734f': 'LoreCollege',
    'c4598bdb-fc07-40dd-a62c-90cc138bd76f': 'Monk',
    '6dec76d0-df22-411c-8a78-3d6fb843ae50': 'NatureDomain',
    'fbb8347b-20e3-4846-ba91-0552cd12fc5f': 'NecromancySchool',
    '6fb3831e-45d8-4b30-9714-6fe73988921b': 'Oathbreaker',
    '2a5e3097-384c-4d29-8d6e-054fdfd26b80': 'OpenHand',
    'ff4d9497-023c-434a-bd14-82fc367e991c': 'Paladin',
    '36be18ba-23db-4dff-bfa6-ae105ce43144': 'Ranger',
    'e8b1eab0-ef11-40a2-8a0b-cee8d062bf2a': 'Rogue',
    'bf46d73f-d406-4cb8-9a1d-e6e758ca02c7': 'Shadow',
    '784001e2-c96d-4153-beb6-2adbef5abc92': 'Sorcerer',
    'd379fdae-b401-4731-8d50-277c73919ae3': 'StormSorcery',
    'c4bd5252-d68a-4330-9431-5e8ab24c5f29': 'SwordsCollege',
    '89bacf1b-8f15-4972-ada7-bf59c7c78441': 'TempestDomain',
    '32c7b8df-a6ec-4848-a9db-c0dce781beb9': 'Thief',
    '2e585948-d775-451d-b58b-15b75321d11e': 'TotemWarriorPath',
    'a12f2924-30b4-4185-9db9-2c5b383ff449': 'TransmutationSchool',
    'f013d01b-3310-43f7-81bf-a51130442b5e': 'TrickeryDomain',
    '2b46330d-0ada-4eb5-a131-3d250a41ca6a': 'ValorCollege',
    '3cc3d397-c47d-4966-87ae-88827f73f645': 'Vengeance',
    'b9ccf90e-b35b-4b73-b896-8ed2d32ae8c6': 'WarDomain',
    'b4225a4b-4bbe-4d97-9e3c-4719dbd1487c': 'Warlock',
    '14374d37-a70e-41a8-9dc5-85a23f8b5dd2': 'WildMagic',
    'd6bf00fc-3518-4d63-ba8b-03532c1abc4d': 'WildMagicPath',
    'a865965f-501b-46e9-9eaa-7748e8c04d09': 'Wizard',
}


# Root-template _merged.lsf files, in load order (later overrides earlier).
ROOT_TEMPLATE_FILES = [
    ('Shared.pak', 'Public/Shared/RootTemplates/_merged.lsf'),
    ('Shared.pak', 'Public/SharedDev/RootTemplates/_merged.lsf'),
    ('Gustav.pak', 'Public/GustavDev/RootTemplates/_merged.lsf'),
    ('Gustav.pak', 'Public/Gustav/RootTemplates/_merged.lsf'),
    ('Gustav.pak', 'Public/Honour/RootTemplates/_merged.lsf'),
    ('GustavX.pak', 'Public/GustavX/RootTemplates/_merged.lsf'),
]


LOCA_PAK = 'Localization/English.pak'


LOCA_FILE = 'Localization/English/english.loca'


STAT_ITEM_PAKS = ['Shared.pak', 'Gustav.pak', 'GustavX.pak']


STAT_ITEM_FILE_RE = re.compile(r'/Stats/Generated/Data/(?:Armor|Weapon|Object)\.txt$')


# Journal quest definitions: QuestID -> QuestTitle localisation handle.
QUEST_PROTOTYPE_FILES = [
    ('Gustav.pak', 'Mods/GustavDev/Story/Journal/quest_prototypes.lsx'),
]

# Journal objective definitions: ObjectiveID -> Description handle. The save
# stores each quest's current ObjectiveID directly (Journal/QuestsProgress).
OBJECTIVE_PROTOTYPE_FILES = [
    ('Gustav.pak', 'Mods/GustavDev/Story/Journal/objective_prototypes.lsx'),
]


# Action resources (spell slots, rage charges, ki...): UUID -> display name.
ACTION_RESOURCE_FILES = [
    ('Shared.pak', 'Public/Shared/ActionResourceDefinitions/ActionResourceDefinitions.lsx'),
    ('Shared.pak', 'Public/SharedDev/ActionResourceDefinitions/ActionResourceDefinitions.lsx'),
]

# Feats: FeatId UUID -> display name (FeatDescriptions.lsx pairs them).
FEAT_DESCRIPTION_FILES = [
    ('Shared.pak', 'Public/Shared/Feats/FeatDescriptions.lsx'),
    ('Shared.pak', 'Public/SharedDev/Feats/FeatDescriptions.lsx'),
]


# Subregion display names ("SHA_Temple_SUB" -> "Gauntlet of Shar"): LSF v3
# localization key files mapping subregion UUID strings to loca handles.
SUBREGION_LOCALIZATION_FILES = [
    ('Gustav.pak', 'Mods/Gustav/Localization/Act1_Subregions.lsf'),
    ('Gustav.pak', 'Mods/GustavDev/Localization/Act1b_Subregions.lsf'),
    ('Gustav.pak', 'Mods/GustavDev/Localization/Act2_Subregions.lsf'),
    ('Gustav.pak', 'Mods/GustavDev/Localization/Act3_Subregions.lsf'),
    ('Gustav.pak', 'Mods/GustavDev/Localization/Waypointshrines2.lsf'),
    ('Gustav.pak', 'Mods/Gustav/Localization/Waypointshrines.lsf'),
]


# Bump when the resolver logic changes so a stale cache is not silently reused.
DISPLAYNAME_SCHEMA_VERSION = 16


def find_game_data_dir() -> str | None:
    """Locate the BG3 Data directory, or None if not found."""
    env = os.environ.get('BG3_DATA_DIR')
    if env and os.path.isdir(env):
        return env
    candidates = [
        '~/.local/share/Steam/steamapps/common/Baldurs Gate 3/Data',
        '~/.steam/steam/steamapps/common/Baldurs Gate 3/Data',
        '~/Library/Application Support/Steam/steamapps/common/Baldurs Gate 3/Data',
        'C:/Program Files (x86)/Steam/steamapps/common/Baldurs Gate 3/Data',
    ]
    for c in candidates:
        p = os.path.expanduser(c)
        if os.path.isdir(p):
            return p
    return None


def parse_loca(blob: bytes) -> dict[str, str]:
    """Parse an english.loca blob into {handle: text}."""
    sig, num, texts_off = struct.unpack_from('<4sII', blob, 0)
    if sig != b'LOCA':
        raise ValueError(f'not a LOCA file ({sig!r})')
    pos = 12
    entries = []
    for _ in range(num):
        key = blob[pos : pos + 64].split(b'\x00')[0].decode('latin1')
        pos += 64
        pos += 2  # version (uint16)
        length = struct.unpack_from('<I', blob, pos)[0]
        pos += 4
        entries.append((key, length))
    out = {}
    tp = texts_off
    for key, length in entries:
        out[key] = blob[tp : tp + length - 1].decode('utf-8', 'replace').strip()
        tp += length
    return out


def _resolved_label(handle: str | None, fallback: str | None, handle_to_text: dict[str, str]):
    """Localised text for a handle, falling back to an internal name.

    Hidden/internal entries carry a '%%%' placeholder string; those are treated
    as unresolved so the internal fallback (or nothing) is used instead.
    """
    title = handle_to_text.get(handle or '')
    if title and '%%%' not in title:
        return title
    return fallback


def parse_lsx_label_map(
    lsx_text: str,
    handle_to_text: dict[str, str],
    *,
    key: str,
    handle: str,
    fallback: str | None = None,
) -> dict[str, str]:
    """Map a `key` attribute to a resolved label across an LSX file's nodes.

    For every node carrying the `key` attribute, the `handle` attribute is
    resolved through the loca map (falling back to the raw `fallback` attribute
    when one is named); nodes without a usable label are skipped.
    """
    out: dict[str, str] = {}
    for node in lsx.all_nodes(lsx.parse(lsx_text)):
        a = lsx.attrs(node)
        key_val = a.get(key)
        if not key_val:
            continue
        fb = a.get(fallback) if fallback else None
        label = _resolved_label(a.get(handle), fb, handle_to_text)
        if label:
            out[key_val] = label
    return out


def parse_quest_titles(lsx_text: str, handle_to_text: dict[str, str]) -> dict[str, str]:
    """Map QuestID -> resolved QuestTitle from quest_prototypes.lsx."""
    return parse_lsx_label_map(lsx_text, handle_to_text, key='QuestID', handle='QuestTitle')


def parse_objective_texts(lsx_text: str, handle_to_text: dict[str, str]) -> dict[str, str]:
    """Map ObjectiveID -> resolved Description from objective_prototypes.lsx."""
    return parse_lsx_label_map(lsx_text, handle_to_text, key='ObjectiveID', handle='Description')


def parse_action_resources(lsx_text: str, handle_to_text: dict[str, str]) -> dict[str, str]:
    """Map a resource UUID -> DisplayName (or internal Name) from ActionResourceDefinitions.lsx."""
    return parse_lsx_label_map(
        lsx_text, handle_to_text, key='UUID', handle='DisplayName', fallback='Name'
    )


def parse_feat_names(lsx_text: str, handle_to_text: dict[str, str]) -> dict[str, str]:
    """Map a FeatId -> DisplayName (or internal ExactMatch) from FeatDescriptions.lsx."""
    return parse_lsx_label_map(
        lsx_text, handle_to_text, key='FeatId', handle='DisplayName', fallback='ExactMatch'
    )


def cache_path(data_dir: str) -> str:
    sig_parts = []
    for pak in {p for p, _ in ROOT_TEMPLATE_FILES} | {LOCA_PAK}:
        fp = os.path.join(data_dir, pak)
        try:
            st = os.stat(fp)
            sig_parts.append(f'{pak}:{st.st_mtime_ns}:{st.st_size}')
        except OSError:
            pass
    sig_parts.append(f'schema:{DISPLAYNAME_SCHEMA_VERSION}')
    sig = hashlib.md5('|'.join(sorted(sig_parts)).encode()).hexdigest()[:16]
    cdir = os.path.join(
        os.environ.get('XDG_CACHE_HOME', os.path.expanduser('~/.cache')),
        'bg3-savefile-parser',
    )
    os.makedirs(cdir, exist_ok=True)
    return os.path.join(cdir, f'displaynames-{sig}.json')


def build_displayname_maps(
    data_dir: str,
) -> tuple[
    dict[str, str],
    dict[str, str],
    dict[str, str],
    frozenset[str],
    dict[str, str],
    frozenset[str],
    frozenset[str],
    dict[str, str],
    dict[str, str],
    dict[str, str],
    dict[str, str],
    dict[str, str],
    dict[str, str],
]:
    """Build display-name and item-stat maps from installed game data.

    Returns (guid->name, stats->name, spell_id->name, object_type_stats, stats_to_slot,
    two_handed_stats, sub_spells, quest_names, quest_objectives, action_resources,
    feat_names, subregions, stats_to_rarity).

    Results are cached under XDG_CACHE_HOME keyed on the source paks' mtime/size,
    so the ~1 s parse only happens after a game update.

    BG3_GAMEDATA_JSON overrides everything: it points at a pre-built cache
    file (the committed data/gamedata.json), used where no game is installed
    (CI, the TypeScript port's build, other machines).
    """
    cache = os.environ.get('BG3_GAMEDATA_JSON') or cache_path(data_dir)
    try:
        with open(cache, encoding='utf-8') as fh:
            data = json.load(fh)
        return (
            data['guid'],
            data['stats'],
            data.get('spells', {}),
            frozenset(data.get('object_types', [])),
            data.get('stats_slots', {}),
            frozenset(data.get('two_handed', [])),
            frozenset(data.get('sub_spells', [])),
            data.get('quest_names', {}),
            data.get('quest_objectives', {}),
            data.get('action_resources', {}),
            data.get('feat_names', {}),
            data.get('subregions', {}),
            data.get('rarity', {}),
        )
    except (OSError, ValueError, KeyError):
        pass

    handle_to_text = parse_loca(lspk_extract(os.path.join(data_dir, LOCA_PAK), LOCA_FILE))

    def _read_lsx(pak: str, name: str) -> str | None:
        try:
            return lspk_extract(os.path.join(data_dir, pak), name).decode('utf-8', 'replace')
        except (OSError, KeyError, ValueError):
            return None

    # Quest titles (QuestID -> QuestTitle) from quest_prototypes.lsx.
    quest_names: dict[str, str] = {}
    for pak, name in QUEST_PROTOTYPE_FILES:
        text = _read_lsx(pak, name)
        if text is not None:
            quest_names.update(parse_quest_titles(text, handle_to_text))

    # Objective texts (ObjectiveID -> Description) from objective_prototypes.lsx.
    quest_objectives: dict[str, str] = {}
    for pak, name in OBJECTIVE_PROTOTYPE_FILES:
        text = _read_lsx(pak, name)
        if text is not None:
            quest_objectives.update(parse_objective_texts(text, handle_to_text))

    # Action resources (UUID -> display/internal name).
    action_resources: dict[str, str] = {}
    for pak, name in ACTION_RESOURCE_FILES:
        text = _read_lsx(pak, name)
        if text is not None:
            action_resources.update(parse_action_resources(text, handle_to_text))

    # Feats (FeatId -> display/internal name).
    feat_names: dict[str, str] = {}
    for pak, name in FEAT_DESCRIPTION_FILES:
        text = _read_lsx(pak, name)
        if text is not None:
            feat_names.update(parse_feat_names(text, handle_to_text))

    # Subregion (and waypoint shrine) display names from the localization
    # key files: TranslatedStringKey nodes carry {UUID, Content handle}.
    subregions: dict[str, str] = {}
    for pak, name in SUBREGION_LOCALIZATION_FILES:
        try:
            for nd in parse_lsof(lspk_extract(os.path.join(data_dir, pak), name)):
                u, c = nd['attrs'].get('UUID'), nd['attrs'].get('Content')
                if u and c:
                    title = handle_to_text.get(c)
                    if title and '%%%' not in title:
                        subregions[u] = title
        except (OSError, KeyError, ValueError):
            continue

    guid_handle: dict[str, str] = {}  # template GUID -> own DisplayName handle ('' if none)
    guid_parent: dict[str, str] = {}  # template GUID -> ParentTemplateId
    stats_guids: dict[str, list[str]] = {}  # stats name -> template GUIDs, in file order
    for pak, name in ROOT_TEMPLATE_FILES:
        try:
            nodes = parse_lsof(lspk_extract(os.path.join(data_dir, pak), name))
        except (OSError, KeyError, ValueError):
            continue
        for nd in nodes:
            if nd['name'] != 'GameObjects':
                continue
            key = nd['attrs'].get('MapKey')
            if not key:
                continue
            guid_handle[key] = nd['attrs'].get('DisplayName', '')
            guid_parent[key] = nd['attrs'].get('ParentTemplateId', '')
            stats = nd['attrs'].get('Stats', '')
            if stats:
                stats_guids.setdefault(stats, []).append(key)

    def resolve_guid_handle(guid: str) -> str:
        cur = guid
        for _ in range(32):  # follow ParentTemplateId until a DisplayName is set
            h = guid_handle.get(cur)
            if h:
                return h
            par = guid_parent.get(cur)
            if not par or par == cur:
                return ''
            cur = par
        return ''

    guid_name: dict[str, str] = {}
    for guid in guid_handle:
        h = resolve_guid_handle(guid)
        txt = handle_to_text.get(h) if h else None
        if txt:
            guid_name[guid] = txt

    # Stats names resolve through the same ParentTemplateId chain: templates
    # like UNI_SCL_MoonlanternWithPixie carry no DisplayName of their own and
    # inherit it from their base template.
    stats_name: dict[str, str] = {}
    for stats, guids in stats_guids.items():
        for g in guids:
            h = resolve_guid_handle(g)
            txt = handle_to_text.get(h) if h else None
            if txt:
                stats_name[stats] = txt
                break

    # Spell stat files: Spell_*.txt from all item paks. Upcast variants and
    # item-granted spells inherit DisplayName through the `using` chain, so
    # entries without their own handle resolve via their parents.
    spell_raw: dict[str, dict] = {}
    for pak_name in STAT_ITEM_PAKS:
        pak_path = os.path.join(data_dir, pak_name)
        try:
            with open(pak_path, 'rb') as fh:
                flist = lspk_filelist(fh)
            spell_files = sorted(
                k for k in flist if re.search(r'/Stats/Generated/Data/Spell_.*\.txt$', k)
            )
        except (OSError, ValueError):
            continue
        for sf in spell_files:
            try:
                text = lspk_extract(pak_path, sf).decode('utf-8', errors='replace')
            except (OSError, KeyError, ValueError):
                continue
            for block_match in re.finditer(r'^new entry "([^"]+)"', text, re.MULTILINE):
                entry_name = block_match.group(1)
                start = block_match.end()
                next_block = re.search(r'^new entry', text[start:], re.MULTILINE)
                block_text = text[start : start + (next_block.start() if next_block else len(text))]
                dn_m = re.search(r'data "DisplayName" "([^";]+)', block_text)
                using_m = re.search(r'^using "([^"]+)"', block_text, re.MULTILINE)
                using = using_m.group(1) if using_m and using_m.group(1) != entry_name else None
                # Sub-spells (e.g. each Disguise Self appearance) declare the
                # container spell they belong to; '' explicitly detaches.
                cont_m = re.search(r'data "SpellContainerID" "([^"]*)"', block_text)
                prev = spell_raw.get(entry_name)
                if prev is None:
                    spell_raw[entry_name] = {
                        'display': dn_m.group(1) if dn_m else None,
                        'using': using,
                        'container': cont_m.group(1) if cont_m else None,
                    }
                else:
                    if prev['display'] is None and dn_m:
                        prev['display'] = dn_m.group(1)
                    if using:
                        prev['using'] = using
                    if prev['container'] is None and cont_m:
                        prev['container'] = cont_m.group(1)

    spell_name: dict[str, str] = {}
    sub_spell_list: list[str] = []
    for entry_name in spell_raw:
        cur: str | None = entry_name
        seen: set[str] = set()
        while cur and cur not in seen:
            seen.add(cur)
            info = spell_raw.get(cur)
            if info is None:
                break
            if info['display']:
                txt = handle_to_text.get(info['display'])
                if txt:
                    spell_name[entry_name] = txt
                break
            cur = info['using']
        # A spell is a sub-spell if the first SpellContainerID declared along
        # its using-chain is non-empty.
        cur = entry_name
        seen = set()
        while cur and cur not in seen:
            seen.add(cur)
            info = spell_raw.get(cur)
            if info is None:
                break
            if info['container'] is not None:
                if info['container']:
                    sub_spell_list.append(entry_name)
                break
            cur = info['using']

    # Item stat files: Armor.txt / Weapon.txt / Object.txt from item paks.
    # Used to (a) identify Object-type items that cannot be equipped, and
    # (b) resolve the equipment slot for each item (following the `using` chain).
    stat_raw: dict[str, dict] = {}
    for pak_name in STAT_ITEM_PAKS:
        pak_path = os.path.join(data_dir, pak_name)
        try:
            with open(pak_path, 'rb') as fh:
                flist2 = lspk_filelist(fh)
            item_files = sorted(k for k in flist2 if STAT_ITEM_FILE_RE.search(k))
            for sf in item_files:
                text = lspk_extract(pak_path, sf).decode('utf-8', errors='replace')
                for bm in re.finditer(r'^new entry "([^"]+)"', text, re.MULTILINE):
                    name = bm.group(1)
                    start = bm.end()
                    nb = re.search(r'^new entry', text[start:], re.MULTILINE)
                    block = text[start : start + (nb.start() if nb else len(text))]
                    type_m = re.search(r'^type "([^"]+)"', block, re.MULTILINE)
                    using_m = re.search(r'^using "([^"]+)"', block, re.MULTILINE)
                    slot_m = re.search(r'^data "Slot" "([^"]+)"', block, re.MULTILINE)
                    wp_m = re.search(r'^data "Weapon Properties" "([^"]+)"', block, re.MULTILINE)
                    rarity_m = re.search(r'^data "Rarity" "([^"]+)"', block, re.MULTILINE)
                    new_using = using_m.group(1) if using_m else None
                    prev = stat_raw.get(name)
                    if prev is None:
                        stat_raw[name] = {
                            'type': type_m.group(1) if type_m else None,
                            'using': new_using,
                            'slot': slot_m.group(1) if slot_m else None,
                            'weapon_props': wp_m.group(1) if wp_m else None,
                            'rarity': rarity_m.group(1) if rarity_m else None,
                        }
                    else:
                        # Honour-mode patches use `using "SameName"` for value-only
                        # overrides; skip self-referential `using` to avoid loops.
                        if new_using and new_using != name:
                            prev['using'] = new_using
                        if type_m:
                            prev['type'] = type_m.group(1)
                        if slot_m:
                            prev['slot'] = slot_m.group(1)
                        if wp_m:
                            prev['weapon_props'] = wp_m.group(1)
                        if rarity_m:
                            prev['rarity'] = rarity_m.group(1)
        except (OSError, KeyError, ValueError):
            pass

    object_type_stats_list = [n for n, d in stat_raw.items() if d.get('type') == 'Object']

    def resolve_slot(name: str, depth: int = 0) -> str | None:
        if depth > 24:
            return None
        entry = stat_raw.get(name)
        if not entry:
            return None
        if entry['slot']:
            return entry['slot']
        parent = entry.get('using')
        if parent and parent != name:
            return resolve_slot(parent, depth + 1)
        return None

    stats_to_slot: dict[str, str] = {}
    for name in stat_raw:
        s = resolve_slot(name)
        if s:
            stats_to_slot[name] = s

    def resolve_weapon_props(name: str, depth: int = 0) -> str | None:
        if depth > 24:
            return None
        entry = stat_raw.get(name)
        if not entry:
            return None
        if entry.get('weapon_props'):
            return entry['weapon_props']
        parent = entry.get('using')
        if parent and parent != name:
            return resolve_weapon_props(parent, depth + 1)
        return None

    two_handed_stats_list = [n for n in stat_raw if 'Twohanded' in (resolve_weapon_props(n) or '')]

    def resolve_rarity(name: str, depth: int = 0) -> str | None:
        if depth > 24:
            return None
        entry = stat_raw.get(name)
        if not entry:
            return None
        if entry.get('rarity'):
            return entry['rarity']
        parent = entry.get('using')
        if parent and parent != name:
            return resolve_rarity(parent, depth + 1)
        return None

    # Absent rarity means Common; only the magic tiers are stored.
    stats_to_rarity: dict[str, str] = {}
    for name in stat_raw:
        r = resolve_rarity(name)
        if r and r != 'Common':
            stats_to_rarity[name] = r

    try:
        with open(cache, 'w', encoding='utf-8') as fh:
            json.dump(
                {
                    'guid': guid_name,
                    'stats': stats_name,
                    'spells': spell_name,
                    'object_types': object_type_stats_list,
                    'stats_slots': stats_to_slot,
                    'two_handed': two_handed_stats_list,
                    'sub_spells': sub_spell_list,
                    'quest_names': quest_names,
                    'quest_objectives': quest_objectives,
                    'action_resources': action_resources,
                    'feat_names': feat_names,
                    'subregions': subregions,
                    'rarity': stats_to_rarity,
                },
                fh,
            )
    except OSError:
        pass
    return (
        guid_name,
        stats_name,
        spell_name,
        frozenset(object_type_stats_list),
        stats_to_slot,
        frozenset(two_handed_stats_list),
        frozenset(sub_spell_list),
        quest_names,
        quest_objectives,
        action_resources,
        feat_names,
        subregions,
        stats_to_rarity,
    )


class DisplayNames:
    """Resolves internal item/spell identifiers to 'Display Name (INTERNAL_NAME)'."""

    def __init__(
        self,
        guid_name: dict[str, str],
        stats_name: dict[str, str],
        spell_name: dict[str, str] | None = None,
        object_type_stats: frozenset[str] | None = None,
        stats_to_slot: dict[str, str] | None = None,
        two_handed_stats: frozenset[str] | None = None,
        sub_spells: frozenset[str] | None = None,
        quest_names: dict[str, str] | None = None,
        quest_objectives: dict[str, str] | None = None,
        action_resources: dict[str, str] | None = None,
        feat_names: dict[str, str] | None = None,
        subregions: dict[str, str] | None = None,
        stats_to_rarity: dict[str, str] | None = None,
    ):
        self._guid = guid_name
        self._stats = stats_name
        self._spells = spell_name or {}
        self.object_type_stats: frozenset[str] = object_type_stats or frozenset()
        self.stats_to_slot: dict[str, str] = stats_to_slot or {}
        self.two_handed_stats: frozenset[str] = two_handed_stats or frozenset()
        self.sub_spells: frozenset[str] = sub_spells or frozenset()
        self.quest_names: dict[str, str] = quest_names or {}
        self.quest_objectives: dict[str, str] = quest_objectives or {}
        self.action_resources: dict[str, str] = action_resources or {}
        self.feat_names: dict[str, str] = feat_names or {}
        self.subregions: dict[str, str] = subregions or {}
        self.stats_to_rarity: dict[str, str] = stats_to_rarity or {}
        self.verbose = False  # set to True to append (INTERNAL_NAME) after display names

    @classmethod
    def load(cls) -> 'DisplayNames':
        data_dir = find_game_data_dir()
        if not data_dir and not os.environ.get('BG3_GAMEDATA_JSON'):
            return cls({}, {}, {})
        try:
            return cls(*build_displayname_maps(data_dir or ''))
        except Exception:  # never let display-name resolution break the report
            return cls({}, {}, {})

    @property
    def available(self) -> bool:
        return bool(self._guid or self._stats)

    def name_for(self, stats: str, guid: str = '') -> str | None:
        """Return the display name for an item, preferring the precise GUID."""
        if guid and guid in self._guid:
            return self._guid[guid]
        return self._stats.get(stats)

    def rarity_for(self, stats: str) -> str | None:
        """Item rarity above Common (Uncommon/Rare/VeryRare/Legendary), or None."""
        return self.stats_to_rarity.get(stats)

    def fmt(self, stats: str, guid: str = '') -> str:
        dn = self.name_for(stats, guid)
        if dn:
            return f'{dn} ({stats})' if self.verbose else dn
        return stats

    def resource_name_for(self, uuid: str) -> str | None:
        """Display name for an action-resource UUID, or None."""
        return self.action_resources.get(uuid)

    def feat_name_for(self, uuid: str) -> str | None:
        """Display name for a feat UUID, or None."""
        return self.feat_names.get(uuid)

    def subregion_name_for(self, subregion_id: str) -> str | None:
        """Display name for a subregion or waypoint id, or None."""
        return self.subregions.get(subregion_id)

    def quest_name_for(self, quest_id: str) -> str | None:
        """Return the journal title for a quest, or None if unresolved."""
        return self.quest_names.get(quest_id)

    def quest_objective_for(self, objective_id: str) -> str | None:
        """Return the journal text for an objective, or None if unresolved."""
        return self.quest_objectives.get(objective_id)

    def spell_name_for(self, spell_id: str) -> str | None:
        """Return the display name for a spell, or None if unresolved."""
        return self._spells.get(spell_id)

    def fmt_spell(self, spell_id: str) -> str:
        dn = self._spells.get(spell_id)
        if dn:
            return f'{dn} ({spell_id})' if self.verbose else dn
        return spell_id
