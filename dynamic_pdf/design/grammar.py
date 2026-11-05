"""
The approved design grammar: reviewed layout rules the art director can follow.

The grammar is opt-in. ``design_variants(grammar=True)`` loads ``approved_grammar.json``
from this package; nothing else reads it, and without it every design is what it was.
The file holds abstract rules only. Reference PDFs, page graphs and evidence stay offline.

A rule changes a design by overriding fields of a ``Direction`` and setting numeric
``extras``. Each design slot takes the first rule that fits the document, and every rule
used is reported so that its effect can be traced in the result.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, fields, replace
from typing import Dict, List, Optional, Sequence, Tuple, Union

from .directions import Direction

FORMAT = "dynamic-pdf-builder/approved-design-grammar"
PACKAGED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "approved_grammar.json")
_DIRECTION_FIELDS = {f.name for f in fields(Direction)} - {"id", "name", "summary", "extras"}


class GrammarError(ValueError):
    """The grammar file cannot be used. Nothing from it is applied."""


@dataclass(frozen=True)
class Rule:
    id: str
    slot: str
    when: Dict
    overrides: Dict
    extras: Dict[str, float]
    safe_fallback: str = ""


@dataclass(frozen=True)
class Grammar:
    version: str
    rules: Tuple[Rule, ...]
    approval: Dict = field(default_factory=dict)
    source: str = ""

    def ids(self) -> List[str]:
        return [r.id for r in self.rules]


def _rule(row: dict) -> Rule:
    engine = row.get("engine")
    if not engine:
        raise GrammarError(f"rule {row.get('id')!r} has no engine section")
    overrides = dict(engine.get("direction") or {})
    unknown = set(overrides) - _DIRECTION_FIELDS
    if unknown:
        raise GrammarError(f"rule {row['id']!r} sets unknown direction fields {sorted(unknown)}")
    return Rule(id=row["id"], slot=row["slot"], when=dict(row.get("when") or {}), overrides=overrides,
                extras={k: float(v) for k, v in (engine.get("extras") or {}).items()},
                safe_fallback=row.get("safe_fallback", ""))


def load(path: Optional[str] = None) -> Grammar:
    """Read an approved grammar. Anything not marked approved is refused."""
    path = path or PACKAGED
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        raise GrammarError(f"cannot read grammar {path!r}: {e}") from e
    if data.get("format") != FORMAT:
        raise GrammarError(f"{path!r} is not an approved grammar file")
    if data.get("status") != "approved" or not data.get("approval"):
        raise GrammarError(f"{path!r} has not been approved")
    rules = tuple(_rule(r) for r in data.get("rules") or ())
    if len({r.id for r in rules}) != len(rules):
        raise GrammarError(f"{path!r} repeats a rule id")
    return Grammar(version=str(data.get("version", "")), rules=rules, approval=data["approval"], source=path)


def resolve(grammar: Union[None, bool, str, Grammar]) -> Optional[Grammar]:
    if grammar is None or grammar is False:
        return None
    if isinstance(grammar, Grammar):
        return grammar
    return load(None if grammar is True else grammar)


def _fits(rule: Rule, brief, direction: Direction, title: str) -> bool:
    w = rule.when
    sections = len([s for s in brief.sections if s.role != "appendix"])
    tests = (
        ("directions", lambda v: direction.id in v),
        ("language", lambda v: brief.language in v),
        ("min_pages", lambda v: brief.estimated_pages >= v),
        ("max_pages", lambda v: brief.estimated_pages <= v),
        ("min_sections", lambda v: sections >= v),
        ("min_photos", lambda v: brief.photos >= v),
        ("min_tables", lambda v: brief.tables >= v),
        ("min_metrics", lambda v: brief.metrics >= v),
        ("max_title_chars", lambda v: len(title) <= v),
    )
    return all(test(w[key]) for key, test in tests if key in w)


def overlay(grammar: Grammar, direction: Direction, brief, title: str = "",
            only: Optional[Sequence[str]] = None) -> Tuple[Direction, List[str]]:
    """``direction`` with the rules that fit this document, and the ids of those rules."""
    changes: Dict = {}
    extras = dict(direction.extras)
    used: List[str] = []
    slots = set()
    for rule in grammar.rules:
        if rule.slot in slots or (only is not None and rule.id not in only):
            continue
        if _fits(rule, brief, direction, title or ""):
            slots.add(rule.slot)
            changes.update(rule.overrides)
            extras.update(rule.extras)
            used.append(rule.id)
    if not used:
        return direction, []
    return replace(direction, extras=extras, **changes), used
