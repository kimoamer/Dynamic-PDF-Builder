"""
Narrow, tested OOXML helpers for features python-docx does not expose:
fields (PAGE, NUMPAGES, TOC), bookmarks, hyperlinks, bidi/RTL, shading,
borders, repeating table headers, list numbering instances, VML watermark.
"""
from __future__ import annotations

import re
from typing import Optional

from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.opc.constants import RELATIONSHIP_TYPE as RT


# ─────────────────────────── generic ───────────────────────────

def _get_or_add(parent, tag: str, before: Optional[tuple] = None):
    el = parent.find(qn(tag))
    if el is None:
        el = OxmlElement(tag)
        if before:
            for b in before:
                ref = parent.find(qn(b))
                if ref is not None:
                    ref.addprevious(el)
                    return el
        parent.append(el)
    return el


def set_cell_shading(cell, fill_hex: str) -> None:
    tcPr = cell._tc.get_or_add_tcPr()
    shd = _get_or_add(tcPr, "w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill_hex.lstrip("#").upper())


def set_paragraph_shading(paragraph, fill_hex: str) -> None:
    pPr = paragraph._p.get_or_add_pPr()
    shd = _get_or_add(pPr, "w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill_hex.lstrip("#").upper())


def set_run_shading(run, fill_hex: str) -> None:
    rPr = run._r.get_or_add_rPr()
    shd = _get_or_add(rPr, "w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill_hex.lstrip("#").upper())


def set_paragraph_border(paragraph, side: str = "bottom", color: str = "DDE2E8",
                         size_eighths: int = 6, space: int = 1) -> None:
    pPr = paragraph._p.get_or_add_pPr()
    pbdr = _get_or_add(pPr, "w:pBdr")
    el = _get_or_add(pbdr, f"w:{side}")
    el.set(qn("w:val"), "single")
    el.set(qn("w:sz"), str(size_eighths))
    el.set(qn("w:space"), str(space))
    el.set(qn("w:color"), color.lstrip("#").upper())


def set_cell_borders(cell, **sides) -> None:
    """sides: top/left/bottom/right/insideH/insideV = (val, size_eighths, color) or None=nil."""
    tcPr = cell._tc.get_or_add_tcPr()
    borders = _get_or_add(tcPr, "w:tcBorders")
    for side, spec in sides.items():
        el = _get_or_add(borders, f"w:{side}")
        if spec is None:
            el.set(qn("w:val"), "nil")
        else:
            val, sz, color = spec
            el.set(qn("w:val"), val)
            el.set(qn("w:sz"), str(sz))
            el.set(qn("w:space"), "0")
            el.set(qn("w:color"), color.lstrip("#").upper())


def set_table_borders(table, color: str = "DDE2E8", size: int = 4, inside_v: bool = True,
                      outer: bool = True) -> None:
    tblPr = table._tbl.tblPr
    borders = _get_or_add(tblPr, "w:tblBorders")
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        el = _get_or_add(borders, f"w:{side}")
        off = (side == "insideV" and not inside_v) or (side in ("top", "left", "bottom", "right") and not outer)
        if off or size == 0:
            el.set(qn("w:val"), "nil")
        else:
            el.set(qn("w:val"), "single")
            el.set(qn("w:sz"), str(size))
            el.set(qn("w:space"), "0")
            el.set(qn("w:color"), color.lstrip("#").upper())


def set_table_width_pct(table, pct: int = 100) -> None:
    tblPr = table._tbl.tblPr
    tblW = _get_or_add(tblPr, "w:tblW")
    tblW.set(qn("w:type"), "pct")
    tblW.set(qn("w:w"), str(int(pct * 50)))


def set_table_cell_margins(table, top=60, bottom=60, left=100, right=100) -> None:
    tblPr = table._tbl.tblPr
    mar = _get_or_add(tblPr, "w:tblCellMar")
    for side, v in (("top", top), ("bottom", bottom), ("left", left), ("right", right)):
        el = _get_or_add(mar, f"w:{side}")
        el.set(qn("w:w"), str(v))
        el.set(qn("w:type"), "dxa")


def set_repeat_table_header(row) -> None:
    trPr = row._tr.get_or_add_trPr()
    el = _get_or_add(trPr, "w:tblHeader")
    el.set(qn("w:val"), "true")


def set_cant_split(row) -> None:
    trPr = row._tr.get_or_add_trPr()
    el = _get_or_add(trPr, "w:cantSplit")
    el.set(qn("w:val"), "true")


def set_table_bidi(table) -> None:
    el = _get_or_add(table._tbl.tblPr, "w:bidiVisual")
    el.set(qn("w:val"), "1")


def set_table_layout_fixed(table) -> None:
    el = _get_or_add(table._tbl.tblPr, "w:tblLayout")
    el.set(qn("w:type"), "fixed")


# ─────────────────────────── bidi / fonts ───────────────────────────

def set_paragraph_bidi(paragraph, on: bool = True) -> None:
    pPr = paragraph._p.get_or_add_pPr()
    el = _get_or_add(pPr, "w:bidi")
    el.set(qn("w:val"), "1" if on else "0")


def set_run_fonts(run, ascii_font: Optional[str] = None, cs_font: Optional[str] = None,
                  rtl: bool = False, bidi_lang: Optional[str] = None) -> None:
    rPr = run._r.get_or_add_rPr()
    rFonts = _get_or_add(rPr, "w:rFonts")
    if ascii_font:
        for a in ("w:ascii", "w:hAnsi", "w:eastAsia"):
            rFonts.set(qn(a), ascii_font)
    if cs_font:
        rFonts.set(qn("w:cs"), cs_font)
    if rtl:
        el = _get_or_add(rPr, "w:rtl")
        el.set(qn("w:val"), "1")
    if bidi_lang:
        lang = _get_or_add(rPr, "w:lang")
        lang.set(qn("w:bidi"), bidi_lang)


def set_style_fonts(style, ascii_font: Optional[str], cs_font: Optional[str],
                    bidi_lang: Optional[str] = None, cs_size_half_pts: Optional[int] = None) -> None:
    rPr = style.element.get_or_add_rPr()
    rFonts = _get_or_add(rPr, "w:rFonts")
    if ascii_font:
        for a in ("w:ascii", "w:hAnsi", "w:eastAsia"):
            rFonts.set(qn(a), ascii_font)
        for a in ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme"):
            if rFonts.get(qn(a)) is not None:
                del rFonts.attrib[qn(a)]
    if cs_font:
        rFonts.set(qn("w:cs"), cs_font)
    if cs_size_half_pts:
        szCs = _get_or_add(rPr, "w:szCs")
        szCs.set(qn("w:val"), str(cs_size_half_pts))
    if bidi_lang:
        lang = _get_or_add(rPr, "w:lang")
        lang.set(qn("w:bidi"), bidi_lang)


# ─────────────────────────── fields ───────────────────────────

def add_field(paragraph, instr: str, placeholder: str = "", run_props=None):
    """Append a complex field (e.g. ``PAGE``, ``NUMPAGES``) to ``paragraph``."""
    def _run():
        r = paragraph.add_run()
        if run_props:
            run_props(r)
        return r
    r1 = _run()
    fc = OxmlElement("w:fldChar")
    fc.set(qn("w:fldCharType"), "begin")
    fc.set(qn("w:dirty"), "true")
    r1._r.append(fc)
    r2 = _run()
    it = OxmlElement("w:instrText")
    it.set(qn("xml:space"), "preserve")
    it.text = f" {instr} "
    r2._r.append(it)
    r3 = _run()
    fc = OxmlElement("w:fldChar")
    fc.set(qn("w:fldCharType"), "separate")
    r3._r.append(fc)
    r4 = _run()
    r4.text = placeholder
    r5 = _run()
    fc = OxmlElement("w:fldChar")
    fc.set(qn("w:fldCharType"), "end")
    r5._r.append(fc)
    return r4


def begin_field(paragraph, instr: str) -> None:
    r = paragraph.add_run()
    fc = OxmlElement("w:fldChar")
    fc.set(qn("w:fldCharType"), "begin")
    fc.set(qn("w:dirty"), "true")
    r._r.append(fc)
    r = paragraph.add_run()
    it = OxmlElement("w:instrText")
    it.set(qn("xml:space"), "preserve")
    it.text = f" {instr} "
    r._r.append(it)
    r = paragraph.add_run()
    fc = OxmlElement("w:fldChar")
    fc.set(qn("w:fldCharType"), "separate")
    r._r.append(fc)


def end_field(paragraph) -> None:
    r = paragraph.add_run()
    fc = OxmlElement("w:fldChar")
    fc.set(qn("w:fldCharType"), "end")
    r._r.append(fc)


def enable_update_fields_on_open(document) -> None:
    settings = document.settings.element
    el = _get_or_add(settings, "w:updateFields")
    el.set(qn("w:val"), "true")


# ─────────────────────────── bookmarks & links ───────────────────────────

_BM_RE = re.compile(r"[^A-Za-z0-9_]")


def bookmark_name(anchor_id: str) -> str:
    name = "_" + _BM_RE.sub("_", anchor_id)
    return name[:40]


class BookmarkCounter:
    def __init__(self):
        self.n = 0

    def next(self) -> int:
        self.n += 1
        return self.n


def add_bookmark(paragraph, name: str, counter: BookmarkCounter) -> None:
    bid = str(counter.next())
    start = OxmlElement("w:bookmarkStart")
    start.set(qn("w:id"), bid)
    start.set(qn("w:name"), name)
    end = OxmlElement("w:bookmarkEnd")
    end.set(qn("w:id"), bid)
    p = paragraph._p
    pPr = p.find(qn("w:pPr"))
    if pPr is not None:
        pPr.addnext(start)
    else:
        p.insert(0, start)
    p.append(end)


def add_hyperlink(paragraph, href: str, text: str, style_run=None):
    """External (http/mailto) or internal (#anchor → bookmark) hyperlink with a styled run."""
    hl = OxmlElement("w:hyperlink")
    if href.startswith("#"):
        hl.set(qn("w:anchor"), bookmark_name(href[1:]))
    else:
        r_id = paragraph.part.relate_to(href, RT.HYPERLINK, is_external=True)
        hl.set(qn("r:id"), r_id)
    hl.set(qn("w:history"), "1")
    run = paragraph.add_run(text)
    if style_run:
        style_run(run)
    try:
        run.style = paragraph.part.document.styles["Hyperlink"]
    except KeyError:
        pass
    paragraph._p.remove(run._r)
    hl.append(run._r)
    paragraph._p.append(hl)
    return run


# ─────────────────────────── numbering ───────────────────────────

_BULLETS = ["•", "–", "◦", "•", "–", "◦", "•", "–", "◦"]
_ORDERED_FMTS = ["decimal", "lowerLetter", "lowerRoman"] * 3


class ListNumbering:
    """Creates two abstract list definitions (bullet, ordered) and one numbering
    instance per list, so every ordered list restarts at its own ``start``."""

    def __init__(self, document, indent_twips: int = 360, bullet_font: str = "Arial"):
        self.numbering = document.part.numbering_part.element
        self.indent = indent_twips
        self.bullet_font = bullet_font
        self._abs = {}

    def _next_id(self, tag: str, attr: str) -> int:
        ids = [int(el.get(qn(attr))) for el in self.numbering.findall(qn(tag))]
        return (max(ids) + 1) if ids else 1

    def _abstract(self, ordered: bool) -> int:
        if ordered in self._abs:
            return self._abs[ordered]
        aid = self._next_id("w:abstractNum", "w:abstractNumId")
        absn = OxmlElement("w:abstractNum")
        absn.set(qn("w:abstractNumId"), str(aid))
        mlt = OxmlElement("w:multiLevelType")
        mlt.set(qn("w:val"), "hybridMultilevel")
        absn.append(mlt)
        for lvl in range(9):
            el = OxmlElement("w:lvl")
            el.set(qn("w:ilvl"), str(lvl))
            st = OxmlElement("w:start")
            st.set(qn("w:val"), "1")
            el.append(st)
            fmt = OxmlElement("w:numFmt")
            fmt.set(qn("w:val"), _ORDERED_FMTS[lvl] if ordered else "bullet")
            el.append(fmt)
            txt = OxmlElement("w:lvlText")
            txt.set(qn("w:val"), f"%{lvl + 1}." if ordered else _BULLETS[lvl])
            el.append(txt)
            jc = OxmlElement("w:lvlJc")
            jc.set(qn("w:val"), "left")
            el.append(jc)
            pPr = OxmlElement("w:pPr")
            ind = OxmlElement("w:ind")
            ind.set(qn("w:left"), str(self.indent * (lvl + 1)))
            ind.set(qn("w:hanging"), str(self.indent))
            pPr.append(ind)
            el.append(pPr)
            if not ordered:
                rPr = OxmlElement("w:rPr")
                rf = OxmlElement("w:rFonts")
                for a in ("w:ascii", "w:hAnsi", "w:cs"):
                    rf.set(qn(a), self.bullet_font)
                rPr.append(rf)
                el.append(rPr)
            absn.append(el)
        # abstractNum elements must precede num elements
        first_num = self.numbering.find(qn("w:num"))
        if first_num is not None:
            first_num.addprevious(absn)
        else:
            self.numbering.append(absn)
        self._abs[ordered] = aid
        return aid

    def new_instance(self, ordered: bool, start: int = 1) -> int:
        aid = self._abstract(ordered)
        nid = self._next_id("w:num", "w:numId")
        num = OxmlElement("w:num")
        num.set(qn("w:numId"), str(nid))
        an = OxmlElement("w:abstractNumId")
        an.set(qn("w:val"), str(aid))
        num.append(an)
        if ordered:
            ov = OxmlElement("w:lvlOverride")
            ov.set(qn("w:ilvl"), "0")
            so = OxmlElement("w:startOverride")
            so.set(qn("w:val"), str(start))
            ov.append(so)
            num.append(ov)
        self.numbering.append(num)
        return nid

    @staticmethod
    def apply(paragraph, num_id: int, level: int) -> None:
        pPr = paragraph._p.get_or_add_pPr()
        numPr = _get_or_add(pPr, "w:numPr")
        ilvl = _get_or_add(numPr, "w:ilvl")
        ilvl.set(qn("w:val"), str(min(level, 8)))
        nid = _get_or_add(numPr, "w:numId")
        nid.set(qn("w:val"), str(num_id))


# ─────────────────────────── watermark ───────────────────────────

def add_text_watermark(header, text: str, color: str = "C0C0C0", opacity: float = 0.3) -> None:
    from docx.oxml import parse_xml
    from xml.sax.saxutils import quoteattr
    p = header.paragraphs[0] if header.paragraphs else header.add_paragraph()
    xml = (
        '<w:r xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office">'
        '<w:pict><v:shape id="DPBWatermark" o:spid="_x0000_s2049" type="#_x0000_t136" '
        'style="position:absolute;margin-left:0;margin-top:0;width:468pt;height:117pt;'
        'rotation:315;z-index:-251654144;mso-position-horizontal:center;'
        'mso-position-horizontal-relative:margin;mso-position-vertical:center;'
        'mso-position-vertical-relative:margin" o:allowincell="f" '
        f'fillcolor="#{color.lstrip("#")}" stroked="f">'
        f'<v:fill opacity="{opacity:.2f}"/>'
        f'<v:textpath style="font-family:&quot;Arial&quot;;font-size:1pt" string={quoteattr(text)}/>'
        '</v:shape></w:pict></w:r>'
    )
    p._p.append(parse_xml(xml))


def set_alt_text(inline_shape, description: str, title: str = "") -> None:
    docPr = inline_shape._inline.docPr
    docPr.set("descr", description[:2000])
    if title:
        docPr.set("title", title[:200])
