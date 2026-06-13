"""Quest dependency graph: the game's DB_QuestDef_* quest interaction tables.

Built on demand from the local game install (the Osiris goal scripts that ship
as readable source under Story/RawFiles/Goals/*.txt), so an agent can answer
"which quests should I prioritise" with grounded facts. See
docs/superpowers/specs/2026-06-13-quest-dependency-graph-design.md.
"""

import re
from dataclasses import dataclass


@dataclass
class QuestDefStmt:
    """One parsed DB_QuestDef_* statement: its kind suffix and cleaned args."""

    kind: str
    args: list[str]


# A DB_QuestDef_* statement ends in `);`. Argument casts like (FLAG), (ITEM),
# (CHARACTER) carry their own parens but no commas, so anchoring on the trailing
# `);` (DOTALL, for multi-line statements) avoids truncating at a cast.
STATEMENT_RE = re.compile(r'DB_QuestDef_(\w+)\((.*?)\);', re.DOTALL)
CAST_RE = re.compile(r'^\([A-Z]+\)')
LINE_COMMENT_RE = re.compile(r'//[^\n]*')


def clean_arg(arg: str) -> str:
    """Strip whitespace, a leading type cast, and surrounding quotes."""
    arg = CAST_RE.sub('', arg.strip())
    if len(arg) >= 2 and arg[0] == '"' and arg[-1] == '"':
        arg = arg[1:-1]
    return arg


def parse_questdef_statements(text: str) -> list[QuestDefStmt]:
    """Parse all DB_QuestDef_* statements out of Osiris goal-script text."""
    text = LINE_COMMENT_RE.sub('', text)
    out = []
    for kind, raw_args in STATEMENT_RE.findall(text):
        args = [clean_arg(a) for a in raw_args.split(',')]
        out.append(QuestDefStmt(kind=kind, args=args))
    return out
