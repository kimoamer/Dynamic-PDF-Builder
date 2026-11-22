"""
Table and figure numbers, references by id, and lists of figures and tables.

Numbers are generated text: the author's captions and ``{ref:id}`` markers stay as written,
and the renderers set "Table 2" or "Figure 3" beside them. Numbering is on when the document
asks for it (``meta.exhibit_numbering``), refers to something with ``{ref:id}``, or has a list
of figures or tables. Then every captioned table and image, and every titled chart (and any
with an ``id``), is numbered in document order. A number the author set (``table_number``, ``figure_number``) is
kept. A reference to a heading reads its section number when sections are numbered and its
title otherwise.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

REF = re.compile(r"\{ref:([^}\s]+)\}")


@dataclass
class Exhibit:
    kind: str                 # "table" | "figure"
    number: int
    caption: str
    anchor: str               # bookmark the caption carries; references and lists link to it


@dataclass
class Numbering:
    on: bool = False
    exhibits: Dict[object, Exhibit] = field(default_factory=dict)
    refs: Dict[str, Tuple[str, Optional[str]]] = field(default_factory=dict)   # id -> (label, anchor)
    language: str = "en"
    notes: Dict[str, int] = field(default_factory=dict)          # footnote key -> its number

    def note(self, key: str) -> str:
        """A footnote's number, 1, 2, 3 in document order as Word numbers it; the key itself
        for a symbol mark ("*", "†") or one no footnote defines."""
        return str(self.notes.get(key, key))

    def of(self, block) -> Optional[Exhibit]:
        return self.exhibits.get(id(block)) or self.exhibits.get(_content_key(block))

    def listed(self, kind: str) -> List[Exhibit]:
        seen, out = set(), []
        for e in self.exhibits.values():
            if e.kind == kind and e.anchor not in seen:
                seen.add(e.anchor)
                out.append(e)
        return sorted(out, key=lambda e: e.number)

    def resolve(self, ref_id: str) -> Optional[Tuple[str, Optional[str]]]:
        return self.refs.get(ref_id)


def _content_key(block):
    """A key that survives a block being copied for layout (a floated image is)."""
    t = getattr(block, "type", None)
    if t == "image":
        return ("image", block.src, block.caption, block.id)
    if t == "table":
        return ("table", tuple(block.headers or []), block.caption, block.id, len(block.rows))
    if t == "chart":
        return ("chart", block.chart_type, block.title, block.id, str(block.data)[:200])
    return None


def numbered_note(marker: str) -> bool:
    """A footnote key Markdown numbers (``[^1]``, ``[^method]``); a one-character mark that
    is not a digit ("*", "†", "a") is shown as written."""
    return bool(re.fullmatch(r"[\w-]+", marker or "")) and (marker.isdigit() or len(marker) > 1)


def _walk(blocks):
    for b in blocks:
        if not hasattr(b, "type"):
            continue
        yield b
        for name in ("left", "right", "main_content", "sidebar_content"):
            kids = getattr(b, name, None)
            if isinstance(kids, list):
                yield from _walk(kids)
        if b.type == "three_column":
            for col in b.columns:
                yield from _walk(col)


def uses_numbering(doc) -> bool:
    if getattr(doc.meta, "exhibit_numbering", False):
        return True
    from .normalize import block_text
    for b in _walk(doc.blocks):
        if b.type == "table_of_contents" and getattr(b, "kind", "contents") != "contents":
            return True
        if b.type not in ("code", "math", "mermaid") and any("{ref:" in s for s in block_text(b)):
            return True
    return False


def number_document(doc) -> Numbering:
    """The numbers and reference labels of ``doc`` (a Document or SemanticDocument)."""
    from ..i18n import label
    from .inline import plain_text
    from .normalize import _slug
    lang = getattr(doc, "language", None) or (doc.meta.language or "en").split("-")[0].lower()
    out = Numbering(on=uses_numbering(doc), language=lang)
    counts = {"table": 0, "figure": 0}
    heads = [0] * 6
    used = set()
    for b in _walk(doc.blocks):
        if b.type == "footnote":
            if numbered_note(b.marker):
                out.notes.setdefault(b.marker, len(out.notes) + 1)
            continue
        if b.type == "heading":
            text = plain_text(b.text)
            counted = (doc.meta.section_numbering or b.numbered) and not (b.hints or {}).get("unnumbered")
            if counted:
                heads[b.level - 1] += 1
                heads[b.level:] = [0] * (6 - b.level)
            num = ".".join(str(n) for n in heads[:b.level] if n)
            shown = f"{label('section', lang)} {num}" if counted else text
            hid = b.id or _slug(text)
            if hid and hid not in out.refs:
                out.refs[hid] = (shown, b.id)        # only a heading with an id carries a bookmark
            continue
        if b.type == "math" and b.equation_number and b.id:
            out.refs[b.id] = (f"{label('equation', lang)} ({b.equation_number})", None)
            continue
        kind = {"table": "table", "image": "figure", "chart": "figure"}.get(b.type)
        if kind is None:
            continue
        caption = b.title if b.type == "chart" else b.caption      # a chart's title is its caption
        own = b.table_number if kind == "table" else getattr(b, "figure_number", None)
        if not (own or (out.on and (caption or b.id))):
            continue
        counts[kind] += 1
        n = own or counts[kind]
        anchor = b.id or f"{kind}-{n}"
        while anchor in used:
            anchor += "-"
        used.add(anchor)
        ex = Exhibit(kind, n, plain_text(caption or ""), anchor)
        out.exhibits[id(b)] = ex
        key = _content_key(b)
        if key is not None:
            out.exhibits.setdefault(key, ex)
        if b.id:
            out.refs[b.id] = (f"{label(kind, lang)} {n}", anchor)
    return out


def number_equations(blocks: list) -> list:
    """Displayed equations with an id get numbers in document order, as captions do; one the
    author numbered keeps its number and the count goes on from it. The list itself when none."""
    out, n, changed = [], 0, False
    for b in blocks:
        if getattr(b, "type", None) == "math" and not b.inline and (b.id or b.equation_number):
            n = b.equation_number or n + 1
            if b.equation_number != n:
                b = b.model_copy(update={"equation_number": n})
                changed = True
        out.append(b)
    return out if changed else blocks


def _signing(b) -> bool:
    kids = [k for name in ("left", "right") for k in (getattr(b, name, None) or [])]
    return getattr(b, "type", None) == "signature" or (
        getattr(b, "type", None) == "two_column" and kids and all(getattr(k, "type", None) == "signature"
                                                                  for k in kids))


def sign_introductions(blocks: list) -> list:
    """A preface signed by the signatures that follow it keeps them on its page: its page break
    moves to after them. The list itself when none is signed."""
    from ..schema.blocks import PageBreakBlock
    out, i, changed = [], 0, False
    while i < len(blocks):
        b = blocks[i]
        out.append(b)
        i += 1
        if (getattr(b, "type", None) == "introduction_page" and getattr(b, "position", "front") != "back"
                and i < len(blocks) and _signing(blocks[i])):
            out[-1] = b.model_copy(update={"hints": {**(b.hints or {}), "signed": True}})
            while i < len(blocks) and _signing(blocks[i]):
                out.append(blocks[i])
                i += 1
            if i < len(blocks):
                out.append(PageBreakBlock())
            changed = True
    return out if changed else blocks


def current() -> Optional[Numbering]:
    """The numbering of the document being rendered, or None outside a render."""
    from ..policy import _current
    col = _current.get()
    return getattr(col, "numbering", None) if col is not None else None


def exhibit_label(block) -> Tuple[Optional[str], Optional[str]]:
    """("Table 2", anchor) for a numbered table or image while rendering, else (None, None)."""
    from ..i18n import label
    num = current()
    ex = num.of(block) if num is not None else None
    if ex is None:
        own = getattr(block, "table_number", None) or getattr(block, "figure_number", None)
        if own:
            kind = "table" if block.type == "table" else "figure"
            return f"{label(kind, num.language if num else 'en')} {own}", None
        return None, None
    return f"{label(ex.kind, num.language)} {ex.number}", ex.anchor


def resolve_refs(text: str, link) -> str:
    """``text`` with each ``{ref:id}`` the current document resolves replaced by
    ``link(label, anchor)``. Outside a render, or for an id nothing carries, the marker
    stays as the author wrote it (``lint()`` reports it)."""
    if "{ref:" not in text:
        return text
    num = current()
    if num is None:
        return text

    def sub(m):
        hit = num.resolve(m.group(1))
        return link(*hit) if hit else m.group(0)
    return REF.sub(sub, text)


def ledger_refs(doc) -> Tuple[Tuple[str, str], ...]:
    """(id, label) of every reference the document makes: what readers see in its place."""
    num = number_document(doc)
    from .normalize import block_text
    ids = []
    for b in _walk(doc.blocks):
        if b.type in ("code", "math", "mermaid"):
            continue
        for s in block_text(b):
            ids += REF.findall(s)
    # a footnote key reads as its number: "^key" -> "2"
    return (tuple((i, num.refs[i][0]) for i in dict.fromkeys(ids) if i in num.refs)
            + tuple((f"^{k}", str(n)) for k, n in num.notes.items()))


__all__ = ["Exhibit", "Numbering", "REF", "current", "exhibit_label", "ledger_refs", "number_document",
           "resolve_refs", "uses_numbering"]
