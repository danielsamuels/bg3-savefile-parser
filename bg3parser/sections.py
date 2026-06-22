"""Canonical registry of report group flags, shared by the CLI and renderer.

Each grouping in the text report is opt-in via its own boolean flag on the
argparse namespace. This module is the single place that lists them and knows
how the --party and --all shortcuts expand, so cli.py and render.py never drift.
"""

# Per-character active-party groups (render-gated; data is always gathered).
PARTY_GROUPS = ('characters', 'equipment', 'spells', 'carried')

# Camp companion groups, symmetric to the active party. The camp chest is a
# container, not a per-character group, so it is tracked separately.
CAMP_COMPANION_GROUPS = ('camp_characters', 'camp_equipment', 'camp_spells', 'camp_carried')
CAMP_CHEST = 'camp_chest'

# Top-level groups. save_info/limits are render-gated; quests/vendors/all_items
# carry real gathering cost and are gather-gated in gather_report.
TOPLEVEL_GROUPS = ('save_info', 'quests', 'vendors', 'all_items', 'limits')

ALL_GROUPS = PARTY_GROUPS + CAMP_COMPANION_GROUPS + (CAMP_CHEST,) + TOPLEVEL_GROUPS

# --party reproduces the old default report: active party identity, gear, spells.
PARTY_SHORTCUT = ('characters', 'equipment', 'spells')


def group_on(opts, name: str) -> bool:
    return bool(getattr(opts, name, False))


def expand_shortcuts(opts) -> None:
    """Apply --all and --party to the namespace in place."""
    if getattr(opts, 'all', False):
        for g in ALL_GROUPS:
            setattr(opts, g, True)
    if getattr(opts, 'party', False):
        for g in PARTY_SHORTCUT:
            setattr(opts, g, True)


def any_party_group(opts) -> bool:
    return any(group_on(opts, g) for g in PARTY_GROUPS)


def any_camp_companion_group(opts) -> bool:
    return any(group_on(opts, g) for g in CAMP_COMPANION_GROUPS)


def no_groups_selected(opts) -> bool:
    return not any(group_on(opts, g) for g in ALL_GROUPS)
