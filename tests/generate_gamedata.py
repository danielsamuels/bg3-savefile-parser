"""Regenerate the committed gamedata tables from an installed game.

Builds data/gamedata.json and data/effects.json (and their site copies in
ts/site/public/) from the local BG3 install (auto-detected, or
BG3_DATA_DIR). Run after a game patch or whenever bg3parser/gamedata.py or
bg3parser/effects.py learns a new table:

    uv run python tests/generate_gamedata.py
"""

import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from bg3parser.effects import build_effects_map  # noqa: E402
from bg3parser.gamedata import (  # noqa: E402
    CLASS_UUID_NAMES,
    build_displayname_maps,
    find_game_data_dir,
)


def main() -> None:
    # A pre-built table must not satisfy the build: this script creates it.
    os.environ.pop('BG3_GAMEDATA_JSON', None)
    os.environ.pop('BG3_EFFECTS_JSON', None)
    data_dir = find_game_data_dir()
    if data_dir is None:
        sys.exit('No BG3 install found; set BG3_DATA_DIR.')

    (
        guid_name,
        stats_name,
        spell_name,
        object_types,
        stats_to_slot,
        two_handed,
        sub_spells,
        quest_names,
        quest_objectives,
        action_resources,
        feat_names,
        subregions,
        stats_to_rarity,
    ) = build_displayname_maps(data_dir)

    payload = {
        'guid': guid_name,
        'stats': stats_name,
        'spells': spell_name,
        'object_types': sorted(object_types),
        'stats_slots': stats_to_slot,
        'two_handed': sorted(two_handed),
        'sub_spells': sorted(sub_spells),
        'quest_names': quest_names,
        'quest_objectives': quest_objectives,
        'action_resources': action_resources,
        'feat_names': feat_names,
        'subregions': subregions,
        'rarity': stats_to_rarity,
        'class_uuid_names': CLASS_UUID_NAMES,
    }
    blob = json.dumps(payload, separators=(',', ':'), ensure_ascii=False)
    for out in (
        PROJECT_ROOT / 'data' / 'gamedata.json',
        PROJECT_ROOT / 'ts' / 'site' / 'public' / 'gamedata.json',
    ):
        out.write_text(blob, encoding='utf-8')
        print(f'wrote {out} ({len(blob):,} bytes)')

    effects = json.dumps(build_effects_map(data_dir), separators=(',', ':'), ensure_ascii=False)
    for out in (
        PROJECT_ROOT / 'data' / 'effects.json',
        PROJECT_ROOT / 'ts' / 'site' / 'public' / 'effects.json',
    ):
        out.write_text(effects, encoding='utf-8')
        print(f'wrote {out} ({len(effects):,} bytes)')


if __name__ == '__main__':
    main()
