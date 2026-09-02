import json
from pathlib import Path
from unittest import mock

from bg3parser.cli import main
from bg3parser.model import CharacterReport, ItemRef, SaveReport, SpellRef
from bg3parser.render import render_json
from bg3parser.telemetry import render_telemetry_v1, telemetry_v1


def sample_report() -> SaveReport:
    return SaveReport(
        source='/Users/parser/private/QuickSave_1.lsv',
        save_info={
            'save_name': "Night's End",
            'save_id': 'volatile-save-id',
            'saved_at': '2026-09-02 01:21:51 UTC',
            'game_version': '4.1.1.7398727',
            'level': 'SCL_Main_A',
            'difficulty': 'RulesetHonour',
            'leader': "Lae'zel",
            'game_id': 'regenerated-id',
            'mods': ['Zed', 'Alpha', 'Alpha'],
            'camp_supplies': 247,
            'short_rests': {'remaining': 2, 'max': 2},
            'inspiration': 4,
            'tadpoles_available': 3,
            'recipes': ['Recipe_B', 'Recipe_A'],
        },
        characters=[
            CharacterReport(
                name='Shadowheart',
                race='HalfElf_High',
                classes=[{'Main': 'Cleric', 'Sub': 'DeathDomain'}],
                level=8,
                xp=39592,
                location='Campsite',
                abilities={'str': 13, 'dex': 18, 'con': 14, 'int': 10, 'wis': 18, 'cha': 8},
                hp={'current': 42, 'max': 59, 'temp': 0, 'temp_max': 0},
                concentration={'id': 'Target_SpiritGuardians', 'name': 'Spirit Guardians'},
                resources=[
                    {
                        'guid': 'resource-3',
                        'name': 'Spell Slot',
                        'level': 3,
                        'current': 2,
                        'max': 3,
                        'replenish': 'LongRest',
                    },
                    {
                        'guid': 'resource-1',
                        'name': 'Channel Divinity',
                        'level': None,
                        'current': 1,
                        'max': 1,
                        'replenish': 'ShortRest',
                    },
                ],
                spells=[
                    SpellRef(
                        'Projectile_Fireball',
                        'Fireball',
                        prepared=True,
                        source=0,
                        level=3,
                    )
                ],
                illithid_powers=['Luck of the Far Realms', 'Favourable Beginnings'],
                reactions=['War Caster', 'Attack of Opportunity'],
                feats=[{'guid': 'feat-1', 'name': 'War Caster', 'level': 4, 'picks': []}],
                equipped=[
                    ItemRef('MAG_Item', 'item-1', 'Luminous Armour', 'Breast', (2,), 'armour')
                ],
                carried=[
                    ItemRef('OBJ_Potion_Healing', 'potion-1', 'Potion of Healing', count=2),
                    ItemRef('OBJ_Potion_Healing', 'potion-1', 'Potion of Healing', count=1),
                ],
            ),
            CharacterReport(
                name='Gale',
                race='Human',
                classes=[{'Main': 'Wizard'}],
                level=8,
                xp=None,
                location='camp',
                at_camp=True,
            ),
        ],
        story={
            'approval': [{'name': 'Gale', 'rating': 100}],
            'dating': ['Gale'],
            'tadpoles': [],
        },
        quests={
            'failed': False,
            'version': 1,
            'active': [{'id': 'q2', 'name': 'Quest 2', 'objective': None}],
            'closed': [{'id': 'q1', 'name': 'Quest 1', 'objective': 'Done'}],
            'global_flags': ['internal'],
        },
        names_resolved=True,
    )


def test_telemetry_v1_maps_only_contract_fields_deterministically() -> None:
    report = sample_report()

    first = render_telemetry_v1(report)
    second = render_telemetry_v1(report)
    data = json.loads(first)

    assert first == second
    assert first.endswith('\n')
    assert list(data) == [
        'schema_version',
        'save',
        'campaign',
        'party',
        'camp',
        'relationships',
        'quests',
        'tactical',
    ]
    assert data['save']['saved_at'] == '2026-09-02T01:21:51Z'
    assert data['save']['mods'] == ['Alpha', 'Zed']
    assert data['party'][0]['classes'] == [{'name': 'Cleric', 'subclass': 'DeathDomain'}]
    assert [resource['name'] for resource in data['party'][0]['resources']] == [
        'Channel Divinity',
        'Spell Slot',
    ]
    assert data['party'][0]['inventory'][0]['count'] == 3
    assert data['relationships'] == [{'name': 'Gale', 'approval': 100, 'dating': True}]
    assert data['tactical']['in_combat'] is None
    assert data['tactical']['enemies'] == []
    assert '/Users/parser' not in first
    assert 'volatile-save-id' not in first
    assert 'regenerated-id' not in first
    assert 'global_flags' not in first
    assert 'slot_rank' not in first


def test_existing_full_json_is_unchanged_and_remains_parser_shaped() -> None:
    data = json.loads(render_json(sample_report()))

    assert data['source'].endswith('QuickSave_1.lsv')
    assert data['save_info']['game_id'] == 'regenerated-id'
    assert data['characters'][0]['classes'][0] == {'Main': 'Cleric', 'Sub': 'DeathDomain'}
    assert data['characters'][0]['resources'][0]['guid'] == 'resource-3'


def test_existing_json_cli_still_emits_full_parser_shape(tmp_path: Path) -> None:
    save = tmp_path / 'save.lsv'
    save.touch()
    with (
        mock.patch('sys.argv', ['bg3save', str(save), '--json']),
        mock.patch('bg3parser.cli.extract_frames', return_value={}),
        mock.patch('bg3parser.cli.gather_report', return_value=sample_report()),
        mock.patch('builtins.print') as output,
    ):
        main()

    data = json.loads(output.call_args_list[-1].args[0])
    assert data['source'].endswith('QuickSave_1.lsv')
    assert data['save_info']['game_id'] == 'regenerated-id'
    assert 'schema_version' not in data


def test_telemetry_cli_can_emit_or_write_a_sidecar(tmp_path: Path) -> None:
    save = tmp_path / 'save.lsv'
    save.touch()
    text_path = tmp_path / 'briefing.md'
    telemetry_path = tmp_path / 'current.json.tmp'

    with (
        mock.patch('sys.argv', ['bg3save', str(save), '--telemetry-json']),
        mock.patch('bg3parser.cli.extract_frames', return_value={}),
        mock.patch('bg3parser.cli.gather_report', return_value=sample_report()),
        mock.patch('builtins.print') as output,
    ):
        main()
    assert json.loads(output.call_args_list[-1].args[0])['schema_version'] == 1

    with (
        mock.patch(
            'sys.argv',
            [
                'bg3save',
                str(save),
                str(text_path),
                '--characters',
                '--telemetry-json',
                str(telemetry_path),
            ],
        ),
        mock.patch('bg3parser.cli.extract_frames', return_value={}),
        mock.patch('bg3parser.cli.gather_report', return_value=sample_report()),
    ):
        main()
    assert text_path.read_text().startswith('BG3 Save File Report')
    assert json.loads(telemetry_path.read_text())['schema_version'] == 1


def test_mapping_function_returns_plain_structure() -> None:
    assert telemetry_v1(sample_report())['schema_version'] == 1
