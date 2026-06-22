from bg3parser import sections
from bg3parser.cli import build_parser


def parse(argv):
    return build_parser().parse_args(argv)


def test_every_group_has_a_flag():
    p = build_parser()
    opts = p.parse_args(['save.lsv'])
    for g in sections.ALL_GROUPS:
        assert hasattr(opts, g), f'missing flag for group {g}'
        assert getattr(opts, g) is False


def test_party_shortcut_present():
    opts = parse(['save.lsv', '--party'])
    assert opts.party is True


def test_all_shortcut_present():
    opts = parse(['save.lsv', '--all'])
    assert opts.all is True


def test_camp_chest_flag_dest():
    opts = parse(['save.lsv', '--camp-chest'])
    assert opts.camp_chest is True


def test_no_spells_flag_removed():
    import pytest

    with pytest.raises(SystemExit):
        parse(['save.lsv', '--no-spells'])
