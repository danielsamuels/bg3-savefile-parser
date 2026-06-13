"""Argument-aware forward-chaining evaluator for the Osiris rules.

Causation in Osiris flows through variable binding, so a name-matching graph
smears unrelated uses of a predicate together (the spike connected 83% of quest
outcomes to any event). This engine instead fires rules only under bindings
that actually satisfy their conditions, so an effect follows a cause only when
the arguments thread through.

PROC calls and events are modelled as facts (a `PROC_X(args)` action produces
the fact that triggers `PROC_X`'s definition), so the whole rule base is one
uniform forward-chaining system.

Honest limits (correctness notes):
- Retractions (`NOT X;` actions) are ignored: this is a reachability analysis
  ("can this quest outcome happen"), which is monotonic.
- Runtime/world queries we cannot evaluate from files (QRY_*, spatial checks)
  are assumed satisfiable, so results that depend on them are possibilities,
  not certainties.
"""

from collections import defaultdict
from dataclasses import dataclass

from .osiris_rules import Var


@dataclass(frozen=True)
class Fact:
    """A ground atom: a predicate applied to constant string arguments."""

    pred: str
    args: tuple


def is_assumed_builtin(pred: str) -> bool:
    """Runtime query predicates we cannot evaluate from files; assumed true."""
    return pred.startswith('QRY_')


def builtin_events(fact) -> list:
    """Osiris engine built-ins that emit events goal rules react to.

    The engine, not the goal scripts, links a built-in call to its event (e.g.
    the `Die` call fires the `Died` event, which the death-handling library
    rules consume). These are stable engine semantics, modelled as a small
    table so deterministic chains through them resolve.
    """
    if fact.pred == 'Die' and fact.args:
        return [Fact('Died', (fact.args[0],))]
    return []


def match_atom(atom, fact: Fact, binding: dict):
    """Unify a rule atom (with variables) against a ground fact. Returns the
    extended binding, or None if they cannot unify."""
    if atom.pred != fact.pred or len(atom.args) != len(fact.args):
        return None
    out = dict(binding)
    for term, value in zip(atom.args, fact.args, strict=True):
        if isinstance(term, Var):
            if term.name == '_':
                continue
            if term.name in out:
                if out[term.name] != value:
                    return None
            else:
                out[term.name] = value
        elif term.value != value:
            return None
    return out


def resolve(term, binding):
    """A term's constant value under a binding, or None if still unbound."""
    if isinstance(term, Var):
        return binding.get(term.name)
    return term.value


def compare(left, op, right) -> bool:
    """Evaluate a comparison on two ground values (numeric for ordering ops)."""
    if op == '==':
        return str(left) == str(right)
    if op == '!=':
        return str(left) != str(right)
    try:
        a, b = float(left), float(right)
    except (TypeError, ValueError):
        return True  # non-numeric ordering: can't decide, assume satisfiable
    if op == '<':
        return a < b
    if op == '>':
        return a > b
    if op == '<=':
        return a <= b
    if op == '>=':
        return a >= b
    return True


class Engine:
    """Forward-chaining evaluator over a set of parsed rules."""

    def __init__(self, rules):
        self.rules = rules
        # index: predicate -> rules with that predicate in a positive condition,
        # so a newly derived fact only re-checks the rules it could affect.
        self.by_pred = defaultdict(list)
        for rule in rules:
            preds = {c.atom.pred for c in rule.conditions if c.atom is not None and not c.negated}
            for p in preds:
                self.by_pred[p].append(rule)

    def solve(self, conditions, facts_by_pred, binding=None, i=0):
        """Yield every binding extending `binding` that satisfies conditions."""
        if binding is None:
            binding = {}
        if i == len(conditions):
            yield binding
            return
        cond = conditions[i]
        if cond.comparison is not None:
            left, op, right = cond.comparison
            lv, rv = resolve(left, binding), resolve(right, binding)
            if lv is None or rv is None or compare(lv, op, right=rv):
                yield from self.solve(conditions, facts_by_pred, binding, i + 1)
            return
        if cond.atom is None:
            yield from self.solve(conditions, facts_by_pred, binding, i + 1)
            return
        atom = cond.atom
        if cond.negated:
            matched = any(
                match_atom(atom, f, binding) is not None for f in facts_by_pred.get(atom.pred, ())
            )
            if not matched:
                yield from self.solve(conditions, facts_by_pred, binding, i + 1)
            return
        if is_assumed_builtin(atom.pred) and not facts_by_pred.get(atom.pred):
            yield from self.solve(conditions, facts_by_pred, binding, i + 1)
            return
        for f in facts_by_pred.get(atom.pred, ()):
            b2 = match_atom(atom, f, binding)
            if b2 is not None:
                yield from self.solve(conditions, facts_by_pred, b2, i + 1)

    def instantiate(self, atom, binding):
        """Ground a positive action atom under a binding, or None if unbound."""
        args = []
        for term in atom.args:
            v = resolve(term, binding)
            if v is None:
                return None
            args.append(v)
        return Fact(atom.pred, tuple(args))

    def fire(self, rule, facts_by_pred):
        """All facts a rule produces against the current fact base."""
        out = set()
        for binding in self.solve(rule.conditions, facts_by_pred):
            for action in rule.actions:
                if action.retract:
                    continue
                fact = self.instantiate(action.atom, binding)
                if fact is not None:
                    out.add(fact)
        return out

    def derive(self, initial_facts) -> set:
        """Forward-chain to the fixpoint of facts reachable from the seeds."""
        return self.consequences(initial_facts, ())

    def consequences(self, cause_facts, context_facts) -> set:
        """Facts newly derivable *because of* the cause, given a baseline context.

        `context_facts` (the save's live database) are matchable but are not
        propagated: they already fired their rules in the real game, so their
        effects are already in the save. Only `cause_facts` and what they derive
        drive forward chaining, so the work is bounded to the cause's downstream
        rather than the whole game state's closure. Returns just the delta (the
        consequences), not the context.
        """
        facts = set(context_facts)
        facts_by_pred = defaultdict(set)
        for f in facts:
            facts_by_pred[f.pred].add(f)
        derived: set = set()
        worklist: list = []

        def absorb(new):
            if new in facts:
                return
            facts.add(new)
            facts_by_pred[new.pred].add(new)
            derived.add(new)
            worklist.append(new)
            for ev in builtin_events(new):
                absorb(ev)

        for f in cause_facts:
            absorb(f)
        while worklist:
            fact = worklist.pop()
            for rule in self.by_pred.get(fact.pred, ()):
                for new in self.fire(rule, facts_by_pred):
                    absorb(new)
        # the seeds themselves are not consequences
        return derived - set(cause_facts)


def facts_from_databases(name_to_facts) -> set:
    """Convert a save's Osiris databases (osiris.read_story) into ground Facts.

    Each database row becomes a Fact keyed by the DB name with its column values
    as strings (GUIDs stay as-is, ints stringify), so rule conditions referring
    to live story state can match the save's actual facts.
    """
    out = set()
    for name, rows in name_to_facts.items():
        for row in rows:
            out.add(Fact(name, tuple(str(col.get('value')) for col in row)))
    return out
