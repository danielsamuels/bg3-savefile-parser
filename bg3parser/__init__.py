"""bg3parser — a pure-Python reader for Baldur's Gate 3 .lsv save files.

Public API: parse a save with gather_report() and render it with
render_text() / render_json(), or use build_report() for text in one call.
Everything else lives in the layer modules and is importable from them:

  lsf        LSF/LSOF binary resource format (nodes, attributes, values)
  lspk       LSPK package container (frames, SaveInfo.json, meta.lsf, thumbnail)
  lsmf       the LSMF ECS blob (components, spell books, containers)
  osiris     Osiris story-engine state (quests, goals, story flags)
  party      party characters and per-character item classification
  gamedata   display-name / stat resolution from installed game data
  discovery  locating save files on disk
  model      report model (gather_report -> SaveReport)
  render     text / JSON views over the model
  cli        command-line entry point
"""

from .cli import main
from .discovery import find_latest_save, find_save_by_token
from .gamedata import DisplayNames
from .lspk import extract_frames
from .model import CharacterReport, ItemRef, SaveReport, SpellRef, gather_report
from .render import render_json, render_text
from .report import build_report

__all__ = [
    'CharacterReport',
    'DisplayNames',
    'ItemRef',
    'SaveReport',
    'SpellRef',
    'build_report',
    'extract_frames',
    'find_latest_save',
    'find_save_by_token',
    'gather_report',
    'main',
    'render_json',
    'render_text',
]
