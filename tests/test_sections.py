from argparse import Namespace

from bg3parser import sections


def make(**flags):
    """A namespace with every group flag present, defaulting False."""
    ns = Namespace(all=False, party=False)
    for g in sections.ALL_GROUPS:
        setattr(ns, g, False)
    for k, v in flags.items():
        setattr(ns, k, v)
    return ns


def test_all_groups_partition():
    # camp_chest is its own group; not in the companion set.
    assert sections.CAMP_CHEST not in sections.CAMP_COMPANION_GROUPS
    assert sections.CAMP_CHEST in sections.ALL_GROUPS
    # No duplicates across the registry.
    assert len(sections.ALL_GROUPS) == len(set(sections.ALL_GROUPS))


def test_expand_all_sets_everything():
    ns = make(all=True)
    sections.expand_shortcuts(ns)
    assert all(getattr(ns, g) for g in sections.ALL_GROUPS)


def test_expand_party_sets_only_party_shortcut():
    ns = make(party=True)
    sections.expand_shortcuts(ns)
    assert ns.characters and ns.equipment and ns.spells
    assert not ns.carried
    assert not ns.quests


def test_no_groups_selected_true_when_bare():
    assert sections.no_groups_selected(make()) is True


def test_no_groups_selected_false_with_one_flag():
    assert sections.no_groups_selected(make(equipment=True)) is False


def test_any_party_group():
    assert sections.any_party_group(make(equipment=True)) is True
    assert sections.any_party_group(make(camp_equipment=True)) is False


def test_any_camp_companion_group_excludes_chest():
    assert sections.any_camp_companion_group(make(camp_chest=True)) is False
    assert sections.any_camp_companion_group(make(camp_spells=True)) is True
