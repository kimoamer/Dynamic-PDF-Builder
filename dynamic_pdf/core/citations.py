"""
Citations from a BibTeX library: ``[@smith2024]`` in the text, the reference list built from what
is cited.

    [@smith2024]            (Smith, 2024)        or  [1]
    [@smith2024, p. 12]     (Smith, 2024, p. 12) or  [1, p. 12]
    [@smith2024; @lee2023]  (Smith, 2024; Lee, 2023) or [1], [2]

Two styles: ``apa`` (author and year; the list in author order) and ``ieee`` (numbers in the order
of first citation; the list in that order). The list holds the cited entries only. It fills the
document's reference list that has no entries of its own (Markdown ``[REFERENCES]``), or is added
at the end. A key the library does not have stays as written, and ``lint()`` reports it.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

CITE = re.compile(r"\[(@[^\[\]]+?)\]")
_ONE = re.compile(r"^\s*@([\w:.\-/]+)\s*(?:,\s*(.+?))?\s*$")
_SKIP_TYPES = {"code", "math", "mermaid", "diagram", "qrcode", "shape", "bibliography", "citation"}
_SKIP_FIELDS = {"type", "id", "src", "url", "key", "style", "language", "hints", "lang", "chart_type", "color",
                "colors", "variant", "icon", "align", "alignment", "vertical_headers"}


# ── BibTeX ─────────────────────────────────────────────────────────────────────────────

def _latex(text: str) -> str:
    """Field text without TeX: braces, escapes and dashes as a reader sees them."""
    text = re.sub(r"\\[`'^\"~=.]\{?(\w)\}?", r"\1", text)          # accents: keep the letter
    text = text.replace("\\&", "&").replace("\\%", "%").replace("\\_", "_").replace("\\$", "$")
    text = text.replace("---", "—").replace("--", "–").replace("~", " ")
    text = re.sub(r"\\[a-zA-Z]+\s*", "", text)
    return " ".join(text.replace("{", "").replace("}", "").split())


def parse_bibtex(text: str) -> Dict[str, Dict[str, str]]:
    """``{key: {"type": "article", "author": ..., "title": ..., ...}}``. ``@string``,
    ``@comment`` and ``@preamble`` are skipped; field names are lower case."""
    out: Dict[str, Dict[str, str]] = {}
    pos = 0
    while True:
        m = re.compile(r"@(\w+)\s*([{(])").search(text, pos)
        if not m:
            break
        kind, close = m.group(1).lower(), "}" if m.group(2) == "{" else ")"
        depth, i = 1, m.end()
        while i < len(text) and depth:
            depth += {"{": 1, "}": -1}.get(text[i], 0) if close == "}" else {"(": 1, ")": -1}.get(text[i], 0)
            i += 1
        body, pos = text[m.end():i - 1], i
        if kind in ("string", "comment", "preamble"):
            continue
        key, _, rest = body.partition(",")
        fields: Dict[str, str] = {"type": kind}
        j = 0
        while j < len(rest):
            f = re.compile(r"\s*([\w-]+)\s*=\s*").match(rest, j)
            if not f:
                break
            name, j = f.group(1).lower(), f.end()
            if j < len(rest) and rest[j] in "{\"":
                opener, depth, k = rest[j], 0, j
                while k < len(rest):
                    ch = rest[k]
                    if opener == "{":
                        depth += (ch == "{") - (ch == "}")
                        if depth == 0:
                            break
                    elif ch == '"' and k > j and rest[k - 1] != "\\":
                        break
                    k += 1
                value, j = rest[j + 1:k], k + 1
            else:
                v = re.compile(r"[^,]*").match(rest, j)
                value, j = v.group(0).strip(), v.end()
            if name in ("author", "editor"):       # {World Health Organization}: one name, not a family "Organization"
                value = " and ".join(_corporate(n) for n in re.split(r"\s+and\s+", value))
            fields[name] = _latex(value)
            c = re.compile(r"\s*,?").match(rest, j)
            j = c.end()
        if key.strip():
            out[key.strip()] = fields
    return out


# ── names ──────────────────────────────────────────────────────────────────────────────

_WHOLE = "\ue000"           # a space inside an organisation's name, until the name is read


def _corporate(name: str) -> str:
    """A name wholly in braces is an organisation's: its spaces are marked so it is never split."""
    n = name.strip()
    if n.startswith("{") and n.endswith("}") and "{" not in n[1:-1] and "}" not in n[1:-1]:
        return n[1:-1].replace(" ", _WHOLE)
    return name


def _people(field: str) -> List[Tuple[str, str]]:
    """(family, given) for each name of a BibTeX ``author`` field."""
    people = []
    for name in re.split(r"\s+and\s+", field.strip()):
        name = name.strip()
        if not name:
            continue
        if _WHOLE in name and " " not in name:     # an organisation: the whole name, no initials
            family, given = name.replace(_WHOLE, " "), ""
        elif "," in name:
            family, _, given = name.partition(",")
        else:
            parts = name.split()
            family, given = parts[-1], " ".join(parts[:-1])
        people.append((family.strip(), given.strip()))
    return people


def _initials(given: str) -> str:
    return " ".join(f"{p[0]}." for p in re.split(r"[\s-]+", given) if p and p[0].isalpha())


def _authors(entry: dict, style: str) -> str:
    people = _people(entry.get("author") or entry.get("editor") or "")
    if not people:
        return entry.get("organization") or entry.get("institution") or entry.get("publisher") or "Anon."
    if style == "ieee":
        names = [f"{_initials(g)} {f}".strip() for f, g in people]
        return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    names = [f"{f}, {_initials(g)}".strip(", ") for f, g in people]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + ", & " + names[-1]


def _source(entry: dict) -> str:
    """Where the work appeared: a journal with its volume, issue and pages, a book's publisher..."""
    pages = entry.get("pages", "").replace("--", "–")
    if entry.get("journal"):
        s = entry["journal"]
        if entry.get("volume"):
            s += f", {entry['volume']}" + (f"({entry['number']})" if entry.get("number") else "")
        return s + (f", {pages}" if pages else "")
    if entry.get("booktitle"):
        return f"In {entry['booktitle']}" + (f" (pp. {pages})" if pages else "")
    return entry.get("publisher") or entry.get("school") or entry.get("institution") or entry.get("howpublished") or entry.get("url", "")


def _short(entry: dict) -> str:
    """The author part of an author-year citation: Smith, Smith & Lee, Smith et al."""
    people = _people(entry.get("author") or entry.get("editor") or "")
    if not people:
        return entry.get("organization") or entry.get("title", "Anon.")[:30]
    if len(people) == 1:
        return people[0][0]
    if len(people) == 2:
        return f"{people[0][0]} & {people[1][0]}"
    return f"{people[0][0]} et al."


# ── documents ──────────────────────────────────────────────────────────────────────────

def _cites(text: str) -> List[List[Tuple[str, Optional[str]]]]:
    out = []
    for m in CITE.finditer(text):
        parts = [_ONE.match(p) for p in m.group(1).split(";")]
        if all(parts):
            out.append([(p.group(1), p.group(2)) for p in parts])
    return out


def _walk_strings(value, fn):
    if isinstance(value, str):
        return fn(value)
    if isinstance(value, list):
        return [_walk_strings(v, fn) for v in value]
    if isinstance(value, dict):
        return {k: (v if k in _SKIP_FIELDS else _walk_strings(v, fn)) for k, v in value.items()}
    return value


def apply_citations(blocks: list, library: Dict[str, Dict[str, str]], style: str = "apa") -> list:
    """The blocks with each citation written in ``style`` and the reference list filled with the
    entries cited. The list itself when nothing is cited."""
    from ..schema.blocks import BibliographyBlock, BibliographyEntry
    style = "ieee" if style in ("ieee", "numeric", "vancouver") else "apa"
    texts = [b for b in blocks if getattr(b, "type", None) not in _SKIP_TYPES]
    order: List[str] = []
    for b in texts:
        dumped = repr(b.model_dump(exclude={"hints"}))
        if "[@" in dumped:
            for cite in _cites(dumped):
                order += [k for k, _ in cite if k in library and k not in order]
    if not order:
        return blocks
    cited = order if style == "ieee" else sorted(order, key=lambda k: (_short(library[k]).lower(), library[k].get("year", "")))
    number = {k: i for i, k in enumerate(order, 1)}

    def write(m):
        parts = [_ONE.match(p) for p in m.group(1).split(";")]
        if not all(parts) or any(p.group(1) not in library for p in parts):
            return m.group(0)                                  # an unknown key stays for lint to report
        if style == "ieee":
            return ", ".join(f"[{number[p.group(1)]}" + (f", {p.group(2)}" if p.group(2) else "") + "]" for p in parts)
        return "(" + "; ".join(f"{_short(library[p.group(1)])}, {library[p.group(1)].get('year', 'n.d.')}"
                               + (f", {p.group(2)}" if p.group(2) else "") for p in parts) + ")"

    out = []
    for b in blocks:
        if getattr(b, "type", None) not in _SKIP_TYPES:
            dumped = b.model_dump()
            if "[@" in repr(dumped):
                b = type(b).model_validate(_walk_strings(dumped, lambda s: CITE.sub(write, s) if "[@" in s else s))
        out.append(b)
    entries = [BibliographyEntry(key=k, authors=_authors(library[k], style), title=library[k].get("title", k),
                                 source=_source(library[k]), year=library[k].get("year", "n.d."),
                                 doi=library[k].get("doi") or None) for k in cited]
    for i, b in enumerate(out):
        if getattr(b, "type", None) == "bibliography" and not b.entries:
            out[i] = b.model_copy(update={"entries": entries, "style": style})
            return out
    return out + [BibliographyBlock(entries=entries, style=style)]


def unresolved(text: str) -> List[str]:
    """Keys still written as citations: the library does not have them."""
    return [k for cite in _cites(text) for k, _ in cite]
