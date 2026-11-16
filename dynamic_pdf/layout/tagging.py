"""
Tagged PDF, opt-in (``meta.tagged`` / ``DocumentBuilder.meta(tagged=True)``): a structure tree
for assistive technology (F9). M14 spike, not PDF/UA.

While the pages are drawn, each tagged flowable is wrapped in a marked-content sequence
(``/P <</MCID n>> BDC ... EMC``) and recorded; running heads and feet are marked as
artifacts. After ReportLab has written the file, pikepdf adds ``/MarkInfo``, the
``/StructTreeRoot`` (Document > H1..H6, P, Figure with /Alt, Caption, L > LI > LBody,
Table > TR > TH/TD) and each page's ``/StructParents`` and ``/Tabs /S``.

Not yet tagged, so not PDF/UA: table rules and fills, list bullets, dividers and other
decoration are left outside both the tree and artifacts, and figures carry no /BBox.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Dict, List, Optional

_ROLE_TAG = {"body": "P", "caption": "Caption", "figure": "Figure", "list": "LI", "code": "P"}
_keys = itertools.count(1)


def new_key() -> int:
    return next(_keys)


@dataclass
class Item:
    tag: str
    key: object                  # pieces of one element (a split paragraph) share it
    page: int
    mcid: int
    alt: str = ""
    group: Optional[tuple] = None   # ("table", key, row) | ("list", key)


@dataclass
class Tagger:
    items: List[Item] = field(default_factory=list)
    _next: Dict[int, int] = field(default_factory=dict)
    _open: int = 0
    _seen_cells: set = field(default_factory=set)

    def begin(self, canv, tag: str, key, alt: str = "", group=None) -> bool:
        if self._open:                       # marked content with MCIDs does not nest
            return False
        page = canv.getPageNumber()
        mcid = self._next.get(page, 0)
        self._next[page] = mcid + 1
        canv._code.append(f"/{tag} <</MCID {mcid}>> BDC")
        self.items.append(Item(tag, key, page, mcid, alt, group))
        self._open = 1
        return True

    def artifact(self, canv) -> bool:
        if self._open:
            return False
        canv._code.append("/Artifact BMC")
        self._open = 1
        return True

    def end(self, canv) -> None:
        canv._code.append("EMC")
        self._open = 0

    def close(self, canv, mark: int, placed: bool) -> None:
        """End the sequence opened at ``canv._code[mark]``, or take it back when nothing was drawn."""
        if placed:
            return self.end(canv)
        del canv._code[mark]
        it = self.items.pop()
        self._next[it.page] = it.mcid
        self._open = 0

    def repeat_cell(self, cell) -> bool:
        """A header cell drawn again on the next page of a split table is an artifact."""
        if cell in self._seen_cells:
            return True
        self._seen_cells.add(cell)
        return False


def flowable_tag(f) -> Optional[tuple]:
    """(tag, key, alt, group) for a flowable that carries its role, or None."""
    cell = getattr(f, "_dpb_cell", None)
    if cell is not None:
        tkey, row, col, header = cell
        return ("TH" if header else "TD", (tkey, row, col), "", ("table", tkey, row))
    role = getattr(f, "_dpb_role", None)
    if role == "heading":
        return (f"H{min(6, max(1, getattr(f, '_dpb_level', 1)))}", _key(f), "", None)
    if role in _ROLE_TAG:
        group = ("list", getattr(f, "_dpb_block", None)) if role == "list" else None
        return (_ROLE_TAG[role], _key(f), getattr(f, "_dpb_alt", "") or "", group)
    return None


def _key(f):
    key = getattr(f, "_dpb_key", None)
    if key is None:
        key = f._dpb_key = new_key()
    return key


def draw_tagged(f, canv, draw) -> None:
    """Call ``draw()`` inside the marked content ``f`` asks for (when tagging is on)."""
    tagger = getattr(canv, "_dpb_tagger", None)
    info = flowable_tag(f) if tagger is not None else None
    if info is None:
        return draw()
    if info[0] == "TH" and tagger.repeat_cell(f):
        opened = tagger.artifact(canv)
    else:
        opened = tagger.begin(canv, info[0], info[1], info[2], info[3])
    try:
        return draw()
    finally:
        if opened:
            tagger.end(canv)


def artifact(canv, draw) -> None:
    """Running heads, feet and page decoration: content that is not part of the text."""
    tagger = getattr(canv, "_dpb_tagger", None)
    opened = tagger.artifact(canv) if tagger is not None else False
    try:
        return draw()
    finally:
        if opened:
            tagger.end(canv)


# ── after rendering: the structure tree ──────────────────────────────────

def add_structure(pdf_bytes: bytes, tagger: Tagger, lang: str = "en", title: str = "") -> bytes:
    import io
    import pikepdf
    from pikepdf import Array, Dictionary, Name, String

    with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
        root = pdf.make_indirect(Dictionary(Type=Name.StructTreeRoot))
        document = pdf.make_indirect(Dictionary(Type=Name.StructElem, S=Name.Document, P=root, K=Array()))
        root.K = Array([document])
        pages = list(pdf.pages)
        parents: Dict[int, Dict[int, object]] = {}
        elements: Dict[object, object] = {}
        groups: Dict[tuple, object] = {}

        def elem(tag, parent, **kw):
            e = pdf.make_indirect(Dictionary(Type=Name.StructElem, S=Name("/" + tag), P=parent, K=Array(), **kw))
            parent.K.append(e)
            return e

        for it in tagger.items:
            if it.page - 1 >= len(pages):
                continue
            page = pages[it.page - 1].obj
            e = elements.get(it.key)
            if e is None:
                parent = document
                if it.group and it.group[0] == "table":
                    _, tkey, row = it.group
                    table = groups.get(("table", tkey)) or groups.setdefault(("table", tkey), elem("Table", document))
                    parent = groups.get(("tr", tkey, row)) or groups.setdefault(("tr", tkey, row), elem("TR", table))
                elif it.group and it.group[0] == "list":
                    parent = groups.get(it.group) or groups.setdefault(it.group, elem("L", document))
                if it.tag == "LI":
                    li = elem("LI", parent)
                    e = elem("LBody", li)
                else:
                    extra = {"Alt": String(it.alt)} if it.tag == "Figure" and it.alt else {}
                    e = elem(it.tag, parent, **extra)
                elements[it.key] = e
            e.K.append(Dictionary(Type=Name.MCR, Pg=page, MCID=it.mcid))
            parents.setdefault(it.page - 1, {})[it.mcid] = e

        nums = Array()
        for index, page in enumerate(pages):
            page.obj.Tabs = Name.S
            if index in parents:
                page.obj.StructParents = index
                by_mcid = parents[index]
                nums.extend([index, pdf.make_indirect(Array([by_mcid[m] for m in sorted(by_mcid)]))])
        root.ParentTree = pdf.make_indirect(Dictionary(Nums=nums))
        root.ParentTreeNextKey = len(pages)
        pdf.Root.StructTreeRoot = root
        pdf.Root.MarkInfo = Dictionary(Marked=True)
        pdf.Root.Lang = String(lang or "en")
        pdf.Root.ViewerPreferences = Dictionary(DisplayDocTitle=True)
        if title:
            pdf.docinfo[Name.Title] = String(title)
        out = io.BytesIO()
        pdf.save(out, deterministic_id=True)
        return out.getvalue()
