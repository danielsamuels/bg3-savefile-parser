"""Tests for the LSX (game XML) parsing helpers and the gamedata extractors.

These are pure functions over inline LSX text, so they run in CI without a game
install and exercise the ElementTree-based parsing directly.
"""

from bg3parser import lsx
from bg3parser.gamedata import (
    parse_action_resources,
    parse_feat_names,
    parse_objective_texts,
    parse_quest_titles,
)


class TestLsxHelpers:
    def test_attrs_prefers_value_then_handle(self):
        root = lsx.parse(
            '<save><node id="X">'
            '<attribute id="A" type="FixedString" value="va"/>'
            '<attribute id="B" type="TranslatedString" handle="hb"/>'
            '</node></save>'
        )
        node = next(lsx.iter_nodes(root, 'X'))
        assert lsx.attrs(node) == {'A': 'va', 'B': 'hb'}

    def test_attrs_reads_only_direct_children(self):
        # A nested child node's attributes must not bleed into the parent.
        root = lsx.parse(
            '<save><node id="Parent">'
            '<attribute id="P" value="p"/>'
            '<children><node id="Child"><attribute id="C" value="c"/></node></children>'
            '</node></save>'
        )
        parent = next(lsx.iter_nodes(root, 'Parent'))
        assert lsx.attrs(parent) == {'P': 'p'}

    def test_iter_nodes_finds_nodes_at_any_depth(self):
        root = lsx.parse(
            '<save><region><node id="root"><children>'
            '<node id="Quest"><attribute id="QuestID" value="Q1"/></node>'
            '<node id="Quest"><attribute id="QuestID" value="Q2"/></node>'
            '</children></node></region></save>'
        )
        ids = [lsx.attrs(n).get('QuestID') for n in lsx.iter_nodes(root, 'Quest')]
        assert ids == ['Q1', 'Q2']


HANDLES = {'h_title': 'Save Mayrina', 'h_obj': 'Defeat the hag', 'h_empty': '%%% EMPTY'}


class TestParseQuestTitles:
    def test_resolves_title_handle(self):
        text = (
            '<save><node id="Quest">'
            '<attribute id="QuestID" value="HAG_HagSpawn"/>'
            '<attribute id="QuestTitle" handle="h_title"/>'
            '</node></save>'
        )
        assert parse_quest_titles(text, HANDLES) == {'HAG_HagSpawn': 'Save Mayrina'}

    def test_skips_placeholder_and_titleless_quests(self):
        text = (
            '<save>'
            '<node id="Quest"><attribute id="QuestID" value="Hidden"/>'
            '<attribute id="QuestTitle" handle="h_empty"/></node>'
            '<node id="Quest"><attribute id="QuestID" value="NoTitle"/></node>'
            '</save>'
        )
        assert parse_quest_titles(text, HANDLES) == {}


class TestParseObjectiveTexts:
    def test_resolves_description_regardless_of_attribute_order(self):
        # Description after ObjectiveID still resolves (order independence).
        text = (
            '<save><node id="Objective">'
            '<attribute id="ObjectiveID" value="HAG_HagSpawn_Hunt"/>'
            '<attribute id="Description" handle="h_obj"/>'
            '</node></save>'
        )
        assert parse_objective_texts(text, HANDLES) == {'HAG_HagSpawn_Hunt': 'Defeat the hag'}


class TestParseActionResources:
    def test_prefers_display_name_falls_back_to_internal(self):
        text = (
            '<save>'
            '<node id="ActionResourceDefinition">'
            '<attribute id="DisplayName" handle="h_title"/>'
            '<attribute id="Name" value="SpellSlot"/>'
            '<attribute id="UUID" value="uuid-1"/></node>'
            '<node id="ActionResourceDefinition">'
            '<attribute id="Name" value="Rage"/>'
            '<attribute id="UUID" value="uuid-2"/></node>'
            '</save>'
        )
        assert parse_action_resources(text, HANDLES) == {
            'uuid-1': 'Save Mayrina',
            'uuid-2': 'Rage',
        }

    def test_does_not_bleed_display_name_across_nodes(self):
        # The first node's DisplayName must not attach to the second's UUID;
        # the old regex grouped by document order and could do exactly that.
        text = (
            '<save>'
            '<node id="ActionResourceDefinition">'
            '<attribute id="DisplayName" handle="h_title"/>'
            '<attribute id="UUID" value="uuid-1"/></node>'
            '<node id="ActionResourceDefinition">'
            '<attribute id="UUID" value="uuid-2"/></node>'
            '</save>'
        )
        assert parse_action_resources(text, HANDLES) == {'uuid-1': 'Save Mayrina'}


class TestParseFeatNames:
    def test_prefers_display_name_falls_back_to_exact_match(self):
        text = (
            '<save>'
            '<node id="Feat">'
            '<attribute id="DisplayName" handle="h_title"/>'
            '<attribute id="ExactMatch" value="ActuallyName"/>'
            '<attribute id="FeatId" value="feat-1"/></node>'
            '<node id="Feat">'
            '<attribute id="ExactMatch" value="Athlete"/>'
            '<attribute id="FeatId" value="feat-2"/></node>'
            '</save>'
        )
        assert parse_feat_names(text, HANDLES) == {
            'feat-1': 'Save Mayrina',
            'feat-2': 'Athlete',
        }
