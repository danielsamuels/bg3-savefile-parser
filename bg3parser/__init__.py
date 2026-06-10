"""bg3parser — a pure-Python reader for Baldur's Gate 3 .lsv save files.

Subpackages by layer:
  lsf        LSF/LSOF binary resource format (nodes, attributes, values)
  lspk       LSPK package container (frames, SaveInfo.json, meta.lsf, thumbnail)
  lsmf       the LSMF ECS blob (components, spell books, containers)
  osiris     Osiris story-engine state (quests, goals, story flags)
  party      party characters and per-character item classification
  gamedata   display-name / stat resolution from installed game data
  discovery  locating save files on disk
  report     report assembly
  cli        command-line entry point
"""

from .cli import main as main
from .discovery import *  # noqa: F403
from .gamedata import *  # noqa: F403
from .lsf import *  # noqa: F403
from .lsmf import *  # noqa: F403
from .lspk import *  # noqa: F403
from .osiris import *  # noqa: F403
from .party import *  # noqa: F403
from .report import *  # noqa: F403
