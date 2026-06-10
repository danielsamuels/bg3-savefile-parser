"""Locating save files on disk."""

import glob
import os

# ---------------------------------------------------------------------------
# Save-file auto-detection
# ---------------------------------------------------------------------------
#
# Saves live at  <profiles>/<Profile>/Savegames/Story/<Char>-<id>__<Name>/<Name>.lsv
# under a platform-specific BG3 profiles directory.  With no save given on the
# command line, the most recently modified .lsv across the known locations is
# used (override the search root with BG3_SAVE_DIR).


def candidate_profile_dirs() -> list[str]:
    home = os.path.expanduser('~')
    bg3 = "Larian Studios/Baldur's Gate 3/PlayerProfiles"
    dirs = [
        os.path.join(home, '.local/share', bg3),  # native Linux
        os.path.join(
            home,
            '.local/share/Steam/steamapps/compatdata/1086940/pfx/'
            'drive_c/users/steamuser/AppData/Local',
            bg3,
        ),  # Proton
        os.path.join(home, 'Documents', bg3),  # macOS
    ]
    local = os.environ.get('LOCALAPPDATA')
    if local:
        dirs.append(os.path.join(local, bg3))  # Windows
    return dirs


def glob_saves(roots: list[str], patterns: tuple[str, ...]) -> set[str]:
    """Return every .lsv path matching any pattern under any existing root."""
    found: set[str] = set()
    for root in roots:
        if not os.path.isdir(root):
            continue
        for pat in patterns:
            found.update(glob.glob(os.path.join(root, pat)))
    return found


def find_latest_save() -> str | None:
    """Return the path of the most recently modified .lsv, or None if none found."""
    env = os.environ.get('BG3_SAVE_DIR')
    roots = [env] if env else candidate_profile_dirs()
    # A root may be a PlayerProfiles dir, a Savegames/Story dir, or a single
    # save folder; these patterns match a .lsv at each of those depths.
    patterns = (
        '*/Savegames/Story/*/*.lsv',
        'Savegames/Story/*/*.lsv',
        'Story/*/*.lsv',
        '*/*.lsv',
        '*.lsv',
    )
    found = glob_saves(roots, patterns)
    if not found:
        return None
    return max(found, key=os.path.getmtime)


def find_save_by_token(token: str) -> str | None:
    """Find the most recently modified save whose name ends with _{token}.

    Accepts a bare number ("268") or a full save name ("QuickSave_268").
    Searches the same roots as find_latest_save().
    """
    env = os.environ.get('BG3_SAVE_DIR')
    roots = [env] if env else candidate_profile_dirs()
    patterns = (
        f'*/Savegames/Story/*_{token}/*_{token}.lsv',
        f'Savegames/Story/*_{token}/*_{token}.lsv',
        f'Story/*_{token}/*_{token}.lsv',
        f'*_{token}/*_{token}.lsv',
        f'*_{token}.lsv',
    )
    found = glob_saves(roots, patterns)
    if not found:
        return None
    return max(found, key=os.path.getmtime)
