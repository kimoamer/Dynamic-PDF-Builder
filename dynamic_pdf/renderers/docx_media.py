"""
DOCX output of the shared media model: native inline and anchored drawings, and the
slot-based header and footer bands.

Everything stays a Word object: pictures keep their whole source with a crop on top,
text stays text, and page numbers and running titles are live fields. Page layers go
in the header part, which is how Word repeats a drawing on every page; a section with
its own layers or bands gets its own header part.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

from docx.enum.table import WD_ROW_HEIGHT_RULE
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.opc.packuri import PackURI
from docx.opc.part import Part
from docx.oxml import parse_xml
from docx.oxml.ns import qn
from docx.shared import Pt
from PIL import Image

from ..media import (Fitted, MediaAsset, PageGeometry, fit_image, page_box, page_position, raster_bytes)
from ..schema.media import ImageTreatment
from ..schema.page_system import Band, Logo
from . import docx_fields as F
from .docx_styles import rgb, word_font

_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_SVG_EXT = "{96DAC541-7B7A-43D3-8B79-37D633B846F1}"
_SVG_NS = "http://schemas.microsoft.com/office/drawing/2016/SVG/main"
_ARABIC = re.compile("[֐-ࣿיִ-﷿ﹰ-﻿]")
_LIVE = {"page": "PAGE", "pages": "NUMPAGES"}
_Z_BASE = 251658240                      # Word's own starting point for stacking
_FADED_MAX_EDGE = 2400


def emu(pt: float) -> int:
    return int(round(pt * 12700))


@dataclass
class Anchor:
    """Where a drawing floats. ``x`` and ``y`` are points from their reference."""
    h_from: str = "page"                 # page, margin or column
    v_from: str = "page"                 # page, margin or paragraph
    x: Optional[float] = 0
    y: float = 0
    align: Optional[str] = None          # left, center or right, in place of x
    behind: bool = True
    wrap: str = "none"                   # none, square or top_bottom
    gutter: float = 0
    z: int = 1


def _anchor_element(inline, a: Anchor):
    if a.wrap == "square":
        wrap = '<wp:wrapSquare wrapText="bothSides"/>'
    elif a.wrap == "top_bottom":
        wrap = "<wp:wrapTopAndBottom/>"
    else:
        wrap = "<wp:wrapNone/>"
    pos_h = f"<wp:align>{a.align}</wp:align>" if a.align else f"<wp:posOffset>{emu(a.x or 0)}</wp:posOffset>"
    dist = emu(a.gutter)
    element = parse_xml(
        f'<wp:anchor xmlns:wp="{_WP}" distT="0" distB="{dist // 2}" distL="{dist}" distR="{dist}" '
        f'simplePos="0" relativeHeight="{max(1, a.z + _Z_BASE)}" behindDoc="{int(a.behind)}" locked="0" '
        'layoutInCell="1" allowOverlap="1"><wp:simplePos x="0" y="0"/>'
        f'<wp:positionH relativeFrom="{a.h_from}">{pos_h}</wp:positionH>'
        f'<wp:positionV relativeFrom="{a.v_from}"><wp:posOffset>{emu(a.y)}</wp:posOffset></wp:positionV>'
        f'{wrap}</wp:anchor>')
    children = {c.tag: c for c in inline}
    wrap_el = element[-1]
    extent = children[qn("wp:extent")]
    wrap_el.addprevious(extent)
    effect = children.get(qn("wp:effectExtent"))
    if effect is None:
        effect = parse_xml(f'<wp:effectExtent xmlns:wp="{_WP}" l="0" t="0" r="0" b="0"/>')
    wrap_el.addprevious(effect)
    for tag in ("wp:docPr", "wp:cNvGraphicFramePr", "a:graphic"):
        element.append(children[qn(tag)])
    return element


@lru_cache(maxsize=4)
def _faded(data: bytes, opacity: float) -> bytes:
    """The picture with its opacity in the pixels. LibreOffice ignores DrawingML alpha
    on anchored pictures, and this reads the same everywhere. A faded image carries
    no fine detail, so a very large one is reduced to keep the PNG reasonable."""
    with Image.open(io.BytesIO(data)) as source:
        image = source.convert("RGBA")
    image.thumbnail((_FADED_MAX_EDGE, _FADED_MAX_EDGE))
    image.putalpha(image.getchannel("A").point(lambda v: round(v * opacity)))
    out = io.BytesIO()
    image.save(out, "PNG", optimize=True)
    return out.getvalue()


def _embed_svg(run, blip, svg: bytes) -> None:
    """The SVG beside its PNG: Word 2016 and later draw the vector, others the PNG."""
    part = run.part
    package = part.package
    name = package.next_partname("/word/media/image%d.svg")
    svg_part = Part(PackURI(str(name)), "image/svg+xml", svg, package)
    rid = part.relate_to(svg_part, RT.IMAGE)
    blip.append(parse_xml(
        f'<a:extLst xmlns:a="{_A}"><a:ext uri="{_SVG_EXT}"><asvg:svgBlip xmlns:asvg="{_SVG_NS}" '
        f'xmlns:r="{_R}" r:embed="{rid}"/></a:ext></a:extLst>'))


def add_drawing(run, asset: MediaAsset, fitted: Fitted, treatment: Optional[ImageTreatment], alt: str,
                shape_id: int, anchor: Optional[Anchor] = None):
    """A native picture in ``run``: inline, or floating when ``anchor`` is given."""
    t = treatment or ImageTreatment()
    data = raster_bytes(asset)
    if t.opacity < 1:
        data = _faded(data, t.opacity)
    shape = run.add_picture(io.BytesIO(data), width=Pt(fitted.width), height=Pt(fitted.height))
    F.set_alt_text(shape, alt or "image")
    inline = shape._inline
    inline.docPr.set("id", str(shape_id))
    inline.docPr.set("name", f"Picture {shape_id}")
    pic = inline.graphic.graphicData.pic
    fill = pic.find(qn("pic:blipFill"))
    blip = fill.find(qn("a:blip"))
    left, top, right, bottom = fitted.crop
    if any(fitted.crop):
        old = fill.find(qn("a:srcRect"))
        if old is not None:
            fill.remove(old)
        blip.addnext(parse_xml(
            f'<a:srcRect xmlns:a="{_A}" l="{round(left * 100000)}" t="{round(top * 100000)}" '
            f'r="{round(right * 100000)}" b="{round(bottom * 100000)}"/>'))
    if asset.is_vector and t.opacity >= 1:
        _embed_svg(run, blip, asset.svg)
    sp = pic.find(qn("pic:spPr"))
    if t.rotation:
        sp.find(qn("a:xfrm")).set("rot", str(round((t.rotation % 360) * 60000)))
    if t.border_width:
        color = (t.border_color or "#9AA3AE").lstrip("#").upper()
        sp.append(parse_xml(f'<a:ln xmlns:a="{_A}" w="{emu(t.border_width)}"><a:solidFill>'
                            f'<a:srgbClr val="{color}"/></a:solidFill></a:ln>'))
    if t.shadow:
        sp.append(parse_xml(
            f'<a:effectLst xmlns:a="{_A}"><a:outerShdw blurRad="63500" dist="38100" dir="2700000" '
            'algn="tl" rotWithShape="0"><a:srgbClr val="000000"><a:alpha val="28000"/></a:srgbClr>'
            '</a:outerShdw></a:effectLst>'))
    if anchor is not None:
        element = _anchor_element(inline, anchor)
        inline.getparent().replace(inline, element)
    return shape


def tiny_paragraph(container):
    """A paragraph that takes almost no height, to hold anchors."""
    p = container.add_paragraph()
    squeeze(p)
    return p


def squeeze(p, height: float = 1.0) -> None:
    fmt = p.paragraph_format
    fmt.space_before = fmt.space_after = Pt(0)
    fmt.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    fmt.line_spacing = Pt(height)


def floating_table(container, width_pt: float, side: str, gutter: float):
    """A one-cell table text wraps around, for a float with a caption: the caption
    stays a real paragraph beside its picture."""
    t = container.add_table(rows=1, cols=1)
    F.set_table_borders(t, size=0)
    F.set_table_cell_margins(t, 0, 0, 0, 0)
    F.set_table_layout_fixed(t)
    t.autofit = False
    t.rows[0].cells[0].width = Pt(width_pt)
    t.columns[0].width = Pt(width_pt)
    twips = int(gutter * 20)
    tblPr = t._tbl.tblPr
    pos = parse_xml(
        '<w:tblpPr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        f'w:leftFromText="{twips}" w:rightFromText="{twips}" w:topFromText="0" w:bottomFromText="{twips // 2}" '
        f'w:vertAnchor="text" w:horzAnchor="margin" w:tblpXSpec="{side}" w:tblpY="1"/>')
    style = tblPr.find(qn("w:tblStyle"))
    if style is not None:
        style.addnext(pos)
    else:
        tblPr.insert(0, pos)
    return t


def page_geometry(renderer, section=None) -> PageGeometry:
    sec = section or renderer.doc.sections[0]
    return PageGeometry(sec.page_width.pt, sec.page_height.pt, sec.left_margin.pt, sec.right_margin.pt,
                        sec.top_margin.pt, sec.bottom_margin.pt, renderer.rtl_doc)


def add_layer(renderer, paragraph, block, geo: PageGeometry, asset: MediaAsset) -> None:
    """A page layer as a page-anchored drawing."""
    w, h = page_box(geo, block.placement)
    f = fit_image(asset, w, h, block.treatment)
    x, y = page_position(geo, block.placement, w, h)
    anchor = Anchor(x=x + f.x, y=y + f.y, behind=block.layer == "behind", z=block.placement.z_index)
    add_drawing(paragraph.add_run(), asset, f, block.treatment, block.alt_text or "Page image",
                renderer.next_shape(), anchor)


# ─────────────────────────── header and footer bands ───────────────────────────

def _column_widths(cells, width: float):
    """Table columns from the layout's cells, which sit left to right."""
    edges = [0.0]
    for a, b in zip(cells, cells[1:]):
        edges.append(((a.x + a.width) + b.x) / 2)
    edges.append(width)
    return [edges[i + 1] - edges[i] for i in range(len(cells))]


class BandWriter:
    def __init__(self, renderer, maker, sample):
        self.r, self.maker, self.sample = renderer, maker, sample
        self.theme = renderer.theme

    def _style(self, row, ink):
        font = word_font(self.r.tokens.fonts.body)

        def style(run, text=""):
            run.font.size = Pt(row.size)
            run.font.bold = row.spec.bold
            run.font.color.rgb = rgb(ink)
            F.set_run_fonts(run, font, None)
            if F.has_complex_script(text):
                F.set_run_fonts(run, None, word_font(self.theme.typography.arabic_family or "Amiri"), rtl=True)
                F.set_complex_script_format(run, row.size, row.spec.bold)
        return style

    def _text(self, p, template: str, style) -> None:
        """Text with live fields left as Word fields."""
        from ..layout.page_system import fill_fields
        values = {**self.maker.values, **self.sample}
        for key in ("page", "pages", "section", "chapter"):
            values[key] = f"\x00{key}\x00"
        for part in re.split("\x00(\\w+)\x00", fill_fields(template, values)):
            if part in _LIVE:
                F.add_field(p, _LIVE[part], "1", lambda r: style(r))
            elif part in ("section", "chapter"):
                level = self.r.band_heading_level(part)
                sample = self.sample.get(part, "")
                F.add_field(p, f'STYLEREF "Heading {level}"', sample, lambda r, s=sample: style(r, s))
            elif part:
                style(p.add_run(part), part)

    def _cell(self, tc, cell, row, style) -> None:
        """Logos and text in one cell; each text item starts its own line."""
        align = {"left": WD_ALIGN_PARAGRAPH.LEFT, "center": WD_ALIGN_PARAGRAPH.CENTER,
                 "right": WD_ALIGN_PARAGRAPH.RIGHT}[cell.align]
        p = tc.paragraphs[0]
        started = False

        def prepare(par, text=""):
            par.alignment = align
            fmt = par.paragraph_format
            fmt.space_before = fmt.space_after = Pt(0)
            fmt.line_spacing_rule = WD_LINE_SPACING.EXACTLY
            fmt.line_spacing = Pt(row.leading)
            if _ARABIC.search(text):
                F.set_paragraph_bidi(par)

        logos = {id(item): (a, w, h) for a, w, h, item in cell.logos}
        for item in cell.items:
            if isinstance(item, Logo):
                if id(item) in logos:
                    asset, w, h = logos[id(item)]
                    prepare(p)
                    p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
                    add_drawing(p.add_run(), asset, fit_image(asset, w, h), None,
                                item.alt_text or "Logo", self.r.next_shape())
                    p.add_run("  ")
                    started = True
        lines = [i for i in cell.items if isinstance(i, str)]
        for k, template in enumerate(lines):
            from ..layout.page_system import fill_fields
            text = fill_fields(template, {**self.maker.values, **self.sample})
            if not text and not re.search(r"\{(page|pages|section|chapter)\}", template):
                continue
            par = p if not started else tc.add_paragraph()
            started = True
            prepare(par, text)
            self._text(par, template, style)

    def write(self, part, band: Band, geo: PageGeometry, is_header: bool, layers=()) -> None:
        part.is_linked_to_previous = False
        width = geo.width - geo.left - geo.right
        layout = self.maker.layout(band, width, self.sample)
        lead = part.paragraphs[0]
        squeeze(lead, max(1.0, layout.accent))
        for block, asset in layers:
            add_layer(self.r, lead, block, geo, asset)
        system = self.maker.system
        top = system.edge_distance if is_header else geo.height - system.edge_distance - layout.height
        accent_first = (band.accent_edge == "outer") == is_header
        if layout.accent:
            y = top if accent_first else top + layout.height - layout.accent
            x, w = (0, geo.width) if band.bleed else (geo.left, width)
            F.add_page_text_box(lead, self.r.next_shape(), x, y, w, band.accent_height,
                                band.accent_color, description="Accent band")
        y = top + (layout.accent if accent_first else 0)
        for k, row in enumerate(layout.rows):
            if k:
                y += band.row_gap
                squeeze(part.add_paragraph(), max(1.0, band.row_gap))
            self._row(part, row, band, width, geo, lead, y)
            y += row.height
        squeeze(part.add_paragraph())

    def _row(self, part, row, band, width, geo, lead, y) -> None:
        from ..layout.page_system import readable_on
        spec = row.spec
        cells = sorted(row.cells, key=lambda c: c.x)
        if not cells:
            squeeze(part.add_paragraph(), row.height)
            return
        widths = _column_widths(cells, width)
        if self.r.rtl_doc:
            # A right-to-left section reverses a plain table in LibreOffice but not in
            # Word. A table marked right-to-left reads the same in both.
            cells, widths = cells[::-1], widths[::-1]
        table = part.add_table(1, len(cells), Pt(width))
        if self.r.rtl_doc:
            F.set_table_bidi(table)
        F.set_table_borders(table, size=0)
        F.set_table_cell_margins(table, 0, 0, 0, 0)
        F.set_table_layout_fixed(table)
        table.autofit = False
        tr = table.rows[0]
        tr.height = Pt(row.height)
        tr.height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
        ink = spec.color or (readable_on(spec.fill) if spec.fill else self.theme.colors.text_muted)
        style = self._style(row, ink)
        for tc, col_w, cell in zip(tr.cells, widths, cells):
            tc.width = Pt(col_w)
            if spec.fill and not band.bleed:
                F.set_cell_shading(tc, spec.fill)
            if spec.rule_below:
                color = spec.rule_color or self.theme.colors.border
                F.set_cell_borders(tc, bottom=("single", max(2, round(spec.rule_width * 8)), color))
            tc.vertical_alignment = 1
            self._cell(tc, cell, row, style)
        for col, col_w in zip(table.columns, widths):
            col.width = Pt(col_w)
        if spec.fill and band.bleed:
            F.add_page_text_box(lead, self.r.next_shape(), 0, y, geo.width, row.height, spec.fill,
                                description="Band fill")
