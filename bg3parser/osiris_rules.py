"""Faithful Osiris rule parser: the game's quest/story logic as structured rules.

Parses the readable goal scripts (Story/RawFiles/Goals/*.txt) into rules with
variables, casts, negation, comparisons, and actions, so an argument-aware
evaluator can trace cause and effect precisely (name-only matching smears
unrelated uses of the same predicate together; see the spike findings).
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Var:
    """An Osiris rule variable (`_Char`) or the anonymous wildcard (`_`)."""

    name: str


@dataclass(frozen=True)
class Const:
    """A constant term: string literal, GUID, number, or enum. `type` is the
    cast that preceded it (e.g. CHARACTER, FLAG), or None."""

    value: str
    type: str | None = None


@dataclass(frozen=True)
class Atom:
    """A predicate applied to argument terms, e.g. DB_Positions(_Char, "Group")."""

    pred: str
    args: tuple


@dataclass
class Condition:
    """One LHS condition: a (possibly negated) atom, or a comparison."""

    atom: Atom | None
    negated: bool = False
    comparison: tuple | None = None  # (left_term, op, right_term)


@dataclass
class Action:
    """One RHS action: an atom, optionally a retraction (`NOT ...;`)."""

    atom: Atom
    retract: bool = False


@dataclass
class Rule:
    kind: str  # 'IF' | 'PROC' | 'QRY'
    trigger: Atom | None
    conditions: list
    actions: list
    source: str = ''


COMMENT_RE = re.compile(r'//[^\n]*')
KB_RE = re.compile(r'KBSECTION(.*?)(?:ENDEXITSECTION|EXITSECTION|\Z)', re.DOTALL)
ATOM_RE = re.compile(r'^([A-Za-z_][A-Za-z0-9_]*)\s*\((.*)\)\s*$', re.DOTALL)
CAST_RE = re.compile(r'^\(([A-Za-z]+)\)\s*(.*)$', re.DOTALL)
COMP_RE = re.compile(r'^(.*?)\s*(==|!=|<=|>=|<|>)\s*(.*)$', re.DOTALL)
NAME_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


def split_args(s: str) -> list:
    """Split an argument list on top-level commas, respecting quotes and the
    parens of casts like (CHARACTER)."""
    args, cur, depth, inq = [], '', 0, False
    for ch in s:
        if ch == '"':
            inq = not inq
            cur += ch
        elif inq:
            cur += ch
        elif ch == '(':
            depth += 1
            cur += ch
        elif ch == ')':
            depth -= 1
            cur += ch
        elif ch == ',' and depth == 0:
            args.append(cur)
            cur = ''
        else:
            cur += ch
    if cur.strip():
        args.append(cur)
    return [a.strip() for a in args]


def parse_term(s: str):
    """Parse one argument term: a Var (`_x`) or a Const, casts stripped."""
    s = s.strip()
    typ = None
    m = CAST_RE.match(s)
    if m:
        typ, s = m.group(1), m.group(2).strip()
    if s.startswith('_'):
        return Var(s)
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return Const(s[1:-1], typ)
    return Const(s, typ)


def parse_atom(s: str):
    """Parse `Name(args)` or a bare `Name` into an Atom, or None."""
    s = s.strip()
    m = ATOM_RE.match(s)
    if m:
        return Atom(m.group(1), tuple(parse_term(a) for a in split_args(m.group(2))))
    if NAME_RE.match(s):
        return Atom(s, ())
    return None


def parse_condition(s: str):
    negated = False
    if s.startswith('NOT '):
        negated, s = True, s[4:].strip()
    atom = parse_atom(s)
    if atom is not None:
        return Condition(atom=atom, negated=negated)
    m = COMP_RE.match(s)
    if m and '(' not in m.group(2):  # avoid splitting an atom's nested content
        return Condition(
            atom=None,
            negated=negated,
            comparison=(parse_term(m.group(1)), m.group(2), parse_term(m.group(3))),
        )
    return Condition(atom=None, negated=negated)


def parse_head(head: str):
    lines = [ln.strip() for ln in head.strip().splitlines() if ln.strip()]
    kind = 'IF'
    if lines and lines[0] in ('IF', 'PROC', 'QRY'):
        kind, lines = lines[0], lines[1:]
    conds, cur = [], []
    for ln in lines:
        if ln in ('AND', 'OR'):
            if cur:
                conds.append(' '.join(cur))
                cur = []
        else:
            cur.append(ln)
    if cur:
        conds.append(' '.join(cur))
    return kind, [parse_condition(c) for c in conds]


def parse_body(body: str):
    actions = []
    for stmt in body.split(';'):
        s = ' '.join(stmt.split())
        if not s:
            continue
        retract = False
        if s.startswith('NOT '):
            retract, s = True, s[4:].strip()
        atom = parse_atom(s)
        if atom is not None:
            actions.append(Action(atom=atom, retract=retract))
    return actions


def parse_rules(text: str, source: str = '') -> list:
    """Parse all KBSECTION rules out of one goal-script's text."""
    text = COMMENT_RE.sub('', text)
    m = KB_RE.search(text)
    kb = m.group(1) if m else text
    rules = []
    for block in re.split(r'\n\s*\n', kb):
        if 'THEN' not in block:
            continue
        head, _, body = block.partition('THEN')
        kind, conds = parse_head(head)
        actions = parse_body(body)
        if not conds and not actions:
            continue
        trigger = conds[0].atom if conds and conds[0].atom else None
        rules.append(Rule(kind, trigger, conds, actions, source))
    return rules
