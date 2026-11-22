"""
PDF drawing for the composition blocks: an image with a live text panel, a matrix of figures,
and rows that keep two languages side by side. Text goes through the factory ``Paragraph``,
so shaping, diacritics and bidi match every other block.
"""
from __future__ import annotations

from typing import List

from reportlab.lib.colors import HexColor
from reportlab.platypus import Spacer, Table, TableStyle
from reportlab.platypus.flowables import Flowable

from .. import policy as _diag
from ..design import archetypes as A
from ..layout.factory import create_flowables
from ..layout.media_flow import draw_media
from ..media import fit_image, ingest
from .archetypes import _text

MAX_PANEL_HEIGHT = 520.0


class _Panel(Flowable):
    """A picture and a text panel drawn as one unit, so they stay on one page."""

    def __init__(self, block, plan, asset, paras):
        super().__init__()
        self.block, self.plan, self.asset, self.paras = block, plan, asset, paras
        self.width, self.height = plan.width, plan.height

    def wrap(self, aw, ah):
        return self.width, self.height

    def draw(self):
        c, p = self.canv, self.plan
        t = A.panel_treatment(self.block)
        f = fit_image(self.asset, p.image_w, p.height, t)
        draw_media(c, self.asset, f, p.image_x, 0, t)
        c.saveState()
        c.setFillColor(HexColor(p.fill))
        if p.overlay:
            c.setFillAlpha(0.93)
        c.rect(p.panel_x, p.panel_y, p.panel_w, p.panel_h, stroke=0, fill=1)
        c.restoreState()
        top = p.panel_y + p.panel_h - (p.panel_h - p.text_h) / 2
        for para, gap in self.paras:
            h = para.wrap(p.text_w, 1e6)[1]
            para.drawOn(c, p.panel_x + p.pad, top - h)
            top -= h + gap


def _panel_text(block, theme, width: float, ink: str) -> tuple:
    """The panel's paragraphs with the gap under each, and their total height."""
    base = theme.typography.base_size
    out = []
    for text in filter(None, [block.eyebrow]):
        out.append((_text(theme, text, base * 0.8, ink, A.align(text), True), 5))
    if block.title:
        out.append((_text(theme, block.title, base * 1.7, ink, A.align(block.title), True, 1.2), 7))
    for text in block.paragraphs:
        out.append((_text(theme, text, A.panel_body(block, base), ink, A.align(text), False, 1.45, False), 6))
    height = sum(p.wrap(width, 1e6)[1] + gap for p, gap in out) - (out[-1][1] if out else 0)
    return out, height


def panel(block, theme, ctx) -> list:
    width = ctx.available_width
    plan = A.plan_panel(block, theme, width)
    paras, text_h = _panel_text(block, theme, plan.text_w, plan.ink)
    plan.settle(text_h)
    if plan.height > MAX_PANEL_HEIGHT:
        return fallback(block, theme, ctx, "the text is too long for a panel")
    asset = ingest(block.image.src, _diag.current().policy.assets)
    out: list = [_Panel(block, plan, asset, paras)]
    for text in filter(None, (block.image.caption, block.image.source)):
        out += [Spacer(1, 3), _text(theme, text, theme.typography.base_size * 0.78, theme.colors.text_secondary,
                                    A.align(text), False, 1.3, False)]
    return out + [Spacer(1, theme.spacing.block_gap)]


def _cell_flow(cell, theme, ctx, width: float, height: float, base: float) -> list:
    title = A.cell_title(cell)
    edge = A.cell_align(cell)
    out: list = []
    if title:
        out += [_text(theme, title, base * 0.95, A.ink(theme), edge, True, 1.25), Spacer(1, 3)]
    if cell.chart is not None:
        out += create_flowables(A.cell_chart(cell, width, height), theme, ctx)
    if cell.value:
        out.append(_text(theme, cell.value, base * 2.6, A.ink(theme), edge, True, 1.15))
    if cell.label:
        if cell.value:
            out.append(Spacer(1, 3))           # a large figure's descent clears the line under it
        out.append(_text(theme, cell.label, base * 0.86, theme.colors.text_secondary, edge, False, 1.3, False))
    if cell.note:
        out += [Spacer(1, 2), _text(theme, cell.note, base * 0.78, theme.colors.text_secondary, edge, False, 1.3, False)]
    return out


def matrix(block, theme, ctx) -> list:
    base = theme.typography.base_size
    width = ctx.available_width
    plan = A.plan_matrix(block, width)
    out: list = []
    if block.title:
        title = _text(theme, block.title, base * 1.3, A.ink(theme), A.align(block.title), True, 1.25)
        title.keepWithNext = 1
        out += [title, Spacer(1, 6)]
        out[-1].keepWithNext = 1
    pad = plan.gap / 2
    style = TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), pad), ("RIGHTPADDING", (0, 0), (-1, -1), pad),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LINEABOVE", (0, 0), (-1, -1), 0.6, HexColor(theme.colors.border)),
    ])
    for row in plan.rows:          # a table per row: what comes before stays with the first row alone
        cells = [_cell_flow(c, theme, ctx, plan.cell_w, block.cell_height, base) if c else "" for c in row]
        table = Table([cells], colWidths=[width / plan.columns] * plan.columns, hAlign="LEFT")
        table.setStyle(style)
        out.append(table)
    if block.note:
        out += [Spacer(1, 4), _text(theme, block.note, base * 0.8, theme.colors.text_secondary, A.align(block.note),
                                    False, 1.3, False)]
    return out + [Spacer(1, theme.spacing.block_gap)]


def paired(block, theme, ctx) -> list:
    base = theme.typography.base_size
    width = ctx.available_width
    gap = 20.0
    col = (width - gap) / 2
    ink, text, muted = A.ink(theme), theme.colors.text_primary, theme.colors.text_secondary
    data: List[list] = []
    style = [("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
             ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]
    repeat = 0
    if block.header_first or block.header_second:
        left, right = A.paired_sides(block.header_first or "", block.header_second or "", block.rows)
        data.append([_text(theme, left, base * 0.86, muted, A.align(left), True) if left else "", "",
                     _text(theme, right, base * 0.86, muted, A.align(right), True) if right else ""])
        style.append(("LINEBELOW", (0, 0), (0, 0), 0.8, HexColor(ink)))
        style.append(("LINEBELOW", (2, 0), (2, 0), 0.8, HexColor(ink)))
        repeat = 1
    for row in block.rows:
        left, right = A.paired_sides(row.first, row.second, block.rows)
        r = len(data)
        size, color = (base * 1.12, ink) if row.heading else (base, text)
        cells = [_text(theme, s, size, color, A.align(s), row.heading, 1.5, row.heading) if s else "" for s in (left, right)]
        data.append([cells[0], "", cells[1]])
        style.append(("LINEBELOW", (0, r), (0, r), 0.3, HexColor(theme.colors.border)))
        style.append(("LINEBELOW", (2, r), (2, r), 0.3, HexColor(theme.colors.border)))
    table = Table(data, colWidths=[col, gap, col], repeatRows=repeat, splitByRow=1, splitInRow=1, hAlign="LEFT")
    table.setStyle(TableStyle(style))
    return [table, Spacer(1, theme.spacing.block_gap)]


def fallback(block, theme, ctx, why: str) -> list:
    _diag.current().warn("composition_fallback", f"{block.type} rendered as plain blocks: {why}")
    out: list = []
    for b in A.lower(block):
        out += create_flowables(b, theme, ctx)
    return out


def render_composition(block, theme, ctx) -> list:
    return {"image_text_panel": panel, "figure_matrix": matrix, "paired_row_columns": paired}[block.type](block, theme, ctx)
