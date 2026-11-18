"""
PDF drawing for compositions an art direction asks for. A block reaches this module only
through its hints, so a document that was not art-directed never does. Text goes through
the factory ``Paragraph``, which keeps shaping, diacritics and bidi as everywhere else.
"""
from __future__ import annotations

import re
from typing import List, Optional

from reportlab.lib.colors import HexColor
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import HRFlowable, KeepTogether, PageBreak, Spacer, Table, TableStyle
from reportlab.platypus.flowables import Flowable, PageBreakIfNotEmpty

from ..design import archetypes as A
from ..fonts import get_font_name

_FRAME_PADDING = 12.0        # platypus frames keep 6 pt each side inside the given width
_ARABIC = re.compile("[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")


def has_arabic(text: Optional[str]) -> bool:
    return bool(_ARABIC.search(text or ""))


def font_for(theme, text: str, bold: bool = False, heading: bool = True) -> str:
    """A face that has every glyph of ``text``: mixed lines take the Arabic face, which also
    carries Latin."""
    if has_arabic(text):
        return get_font_name(theme.typography.arabic_family or "Amiri", bold=bold)
    ty = theme.typography
    return get_font_name(ty.heading_family if heading else ty.body_family, bold=bold)


def _style(theme, text: str, size: float, color: str, align: int, bold=False, ratio=1.25,
           heading=True, after: float = 0.0) -> ParagraphStyle:
    return ParagraphStyle("art", fontName=font_for(theme, text, bold, heading), fontSize=size,
                          leading=size * A.leading(text, ratio), textColor=HexColor(color),
                          alignment=align, spaceAfter=after, allowWidows=0, allowOrphans=0)


def _para(theme, text: str, size: float, color: str, align: int, **kw):
    from .factory import Paragraph, _md_inline
    return Paragraph(_md_inline(text), _style(theme, text, size, color, align, **kw))


class DesignedHeading(Flowable):
    """A heading on a slab, under a heavy rule, or hung out into the margin."""

    def __init__(self, para, *, fill=None, rule=None, rule_width=2.5, pad_x=0.0, pad_y=0.0,
                 bleed=False, reach_left=0.0, reach_right=0.0, text_left=0.0, text_right=0.0, before=0.0,
                 after=0.0, side="top", rtl=False):
        super().__init__()
        self.side, self.rtl = side, rtl             # where the rule goes: top, bottom, or the start edge
        self.para, self.fill, self.rule, self.rule_width = para, fill, rule, rule_width
        self.pad_x, self.pad_y, self.bleed = pad_x, pad_y, bleed
        self.reach_left, self.reach_right = reach_left, reach_right      # fill and rule go this far past the frame
        self.text_left, self.text_right = text_left, text_right          # the text may too
        self.before, self.after = before, after
        self.keepWithNext = 1

    def wrap(self, aW, aH):
        self.w = aW
        self.bar = (self.rule_width + 9) if self.rule and self.side == "start" else 0.0
        inner = aW + self.text_left + self.text_right - 2 * self.pad_x - self.bar
        self.text_h = self.para.wrap(inner, aH)[1]
        self.top_gap = (self.rule_width + 9) if self.rule and self.side == "top" else 0.0
        self.low_gap = (self.rule_width + 6) if self.rule and self.side == "bottom" else 0.0
        self.h = self.text_h + 2 * self.pad_y + self.top_gap + self.low_gap
        return aW, self.h

    def getSpaceBefore(self):
        return self.before

    def getSpaceAfter(self):
        return self.after

    def draw(self):
        c = self.canv
        x0, x1 = -self.reach_left, self.w + self.reach_right
        if self.bleed:                              # to the page edges, wherever the frame sits
            left = c.absolutePosition(0, 0)[0]
            x0, x1 = -left, c._pagesize[0] - left
        if self.fill:
            c.setFillColor(HexColor(self.fill))
            c.rect(x0, 0, x1 - x0, self.h, fill=1, stroke=0)
        if self.rule:
            c.setStrokeColor(HexColor(self.rule))
            c.setLineWidth(self.rule_width)
            if self.side == "start":
                x = x1 - self.rule_width / 2 if self.rtl else x0 + self.rule_width / 2
                c.line(x, 0, x, self.h)
            else:
                y = self.h - self.rule_width / 2 if self.side == "top" else self.rule_width / 2
                short = (x1 - x0) * 0.78 if self.side == "bottom" else 0.0     # under the words, a short rule
                c.line(x0 + (short if self.rtl else 0), y, x1 - (0 if self.rtl else short), y)
        self.para.drawOn(c, self.pad_x - self.text_left + (0 if self.rtl else self.bar), self.pad_y + self.low_gap)


def designed_heading(block, display: str, theme, fs: float, color: str, rtl: bool, before: float,
                     after: float):
    """The flowable for a heading whose hints name a treatment."""
    hints = block.hints or {}
    kind = hints.get("opener")
    size = fs * float(hints.get("scale", 1.0))
    align = 2 if rtl else 0
    bold = hints.get("weight", "bold") == "bold"
    if kind == "slab":
        fill = hints.get("fill") or A.ink(theme)
        para = _para(theme, display, size, "#ffffff", align, bold=bold, ratio=1.2)
        bleed = bool(hints.get("bleed"))
        return DesignedHeading(para, fill=fill, pad_x=0.0 if bleed else 12.0, pad_y=size * 0.62, bleed=bleed,
                               before=before, after=after + 6)
    para = _para(theme, display, size, color, align, bold=bold, ratio=1.18)
    if kind in ("bar", "under"):                 # a bar down the start edge, or a short rule under the words
        return DesignedHeading(para, rule=hints.get("rule") or A.ink(theme), rule_width=3.5 if kind == "bar" else 2.0,
                               side="start" if kind == "bar" else "bottom", rtl=rtl, before=before, after=after + 2)
    hang = float(hints.get("hang", 0.0))
    left, right = (0.0, hang) if rtl else (hang, 0.0)
    return DesignedHeading(para, rule=hints.get("rule") or (A.ink(theme) if kind == "rule" else None),
                           rule_width=float(hints.get("rule_width", 2.5)), reach_left=left, reach_right=right,
                           text_left=left, text_right=right, before=before, after=after)


def _short_rule(color: str, rtl: bool, thickness: float = 3.0, width: str = "18%"):
    return HRFlowable(width=width, thickness=thickness, color=HexColor(color), hAlign="RIGHT" if rtl else "LEFT",
                      spaceBefore=0, spaceAfter=14)


def statement(block, theme, ctx) -> list:
    """A sentence set large: inline as a pull statement, or alone on its page."""
    hints = block.hints or {}
    whole_page = hints.get("statement") == "page"
    rtl = A.is_rtl(block.text)
    base = theme.typography.base_size
    size = base * float(hints.get("scale", 2.5 if whole_page else 1.7))
    color = hints.get("color") or A.ink(theme)
    align = 2 if rtl else 0
    bold = hints.get("weight", "regular") == "bold"
    parts: list = [_short_rule(hints.get("rule") or theme.colors.accent, rtl),
                   _para(theme, block.text, size, color, align, bold=bold, ratio=1.24, after=size * 0.5)]
    if block.attribution:
        text = block.attribution if has_arabic(block.attribution) else f"— {block.attribution}"
        parts.append(_para(theme, text, base, theme.colors.text_secondary, align, heading=False, ratio=1.4))
    if not whole_page:
        gap = theme.spacing.block_gap * 1.6
        return [Spacer(1, gap), KeepTogether(parts), Spacer(1, gap)]
    frame_h = ctx.available_height or 640.0
    out: list = [] if ctx.first_block else [PageBreakIfNotEmpty()]
    out += [Spacer(1, frame_h * float(hints.get("drop", 0.34)))] + parts
    if not ctx.last_block:
        out.append(PageBreak())
    return out


def metric_strip(block, theme, width: float, style: str) -> list:
    """KPIs under heavy rules, or reversed out of a band of colour. The figure leads."""
    rtl = any(A.is_rtl(m.label) for m in block.metrics)
    base = theme.typography.base_size
    dark = A.ink(theme)
    filled = style == "band"
    band = style in ("band", "tint", "boxed")     # the figures stand in from the edge of a box
    value_ink = "#ffffff" if filled else dark
    label_ink = "#ffffff" if filled else theme.colors.text_secondary
    align = 2 if rtl else 0
    n = max(1, len(block.metrics))
    vsize = base * float((block.hints or {}).get("value_scale", 2.5 if n <= 3 else 2.1))
    gap = 12.0
    col = (width - _FRAME_PADDING - gap * (n - 1)) / n
    inner = col - (16 if band else 0)
    while vsize > base * 1.3 and any(
            _para(theme, m.value, vsize, value_ink, align, bold=True, ratio=1.15).wrap(inner, 9999)[1] > vsize * 1.6
            for m in block.metrics):
        vsize *= 0.93                             # a figure stays on one line
    cells = []
    # Amiri's line box reaches well above its letters
    drop = 13 if any(has_arabic(m.label) for m in block.metrics) else 7
    for m in block.metrics:
        parts = [_para(theme, m.value, vsize, value_ink, align, bold=True, ratio=1.15, after=drop),
                 _para(theme, m.label, base * 0.86, label_ink, align, heading=False, ratio=1.3)]
        if m.delta:
            parts.append(_para(theme, m.delta, base * 0.8, label_ink, align, bold=True, heading=False, ratio=1.4))
        cells.append(parts)
    if rtl:
        cells.reverse()
    row: List[object] = []
    widths: List[float] = []
    for i, cell in enumerate(cells):
        if i:
            row.append("")
            widths.append(gap)
        row.append(cell)
        widths.append(col)
    cmds = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 8 if band else 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8 if band else 0),
            ("TOPPADDING", (0, 0), (-1, -1), 10), ("BOTTOMPADDING", (0, 0), (-1, -1), 10)]
    if style in ("band", "tint"):
        cmds.append(("BACKGROUND", (0, 0), (-1, -1), HexColor(dark if filled else A.tint(theme, 0.9))))
    elif style == "boxed":
        for i in range(0, 2 * n - 1, 2):
            cmds += [("BOX", (i, 0), (i, 0), 0.6, HexColor(theme.colors.border)),
                     ("LINEABOVE", (i, 0), (i, 0), 2.4, HexColor(theme.colors.accent))]
    else:
        for i in range(0, 2 * n - 1, 2):
            cmds.append(("LINEABOVE", (i, 0), (i, 0), 2.0, HexColor(dark)))
    t = Table([row], colWidths=widths, style=TableStyle(cmds))
    t.hAlign = "RIGHT" if rtl else "LEFT"
    t.spaceBefore = theme.spacing.block_gap * 0.5
    t.spaceAfter = theme.spacing.block_gap * 1.5
    return [t]


def table_commands(design: str, theme, rows: int, columns: int, has_header: bool, has_footer: bool,
                   pad: float, current: Optional[int], rtl: bool) -> list:
    """Table style for a named design: hierarchy from rules and tone instead of a grid."""
    dark = HexColor(A.ink(theme))
    hair = HexColor(theme.colors.border)
    tone = HexColor(A.tint(theme, 0.9))
    last = rows - 1
    v = 6 if pad >= 9 else 3.5
    cmds = [("ALIGN", (0, 0), (-1, -1), "LEFT"), ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), v), ("BOTTOMPADDING", (0, 0), (-1, -1), v),
            ("LEFTPADDING", (0, 0), (-1, -1), pad * 0.6), ("RIGHTPADDING", (0, 0), (-1, -1), pad * 0.6)]
    first_body = 1 if has_header else 0
    if design == "booktabs":                 # a paper's table: three rules and no lines between rows
        cmds += [("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5)]
        cmds.append(("LINEABOVE", (0, 0), (-1, 0), 1.0, dark))
        if has_header:
            cmds.append(("LINEBELOW", (0, 0), (-1, 0), 0.6, dark))
        cmds.append(("LINEBELOW", (0, last), (-1, last), 1.0, dark))
        if has_footer:
            cmds.append(("LINEABOVE", (0, last), (-1, last), 0.6, dark))
        return cmds
    cmds.append(("LINEBELOW", (0, first_body), (-1, last), 0.3, hair))
    if design == "ledger":
        cmds.append(("LINEABOVE", (0, 0), (-1, 0), 1.6, dark))
        if has_header:
            cmds.append(("LINEBELOW", (0, 0), (-1, 0), 0.7, dark))
        cmds.append(("LINEBELOW", (0, last), (-1, last), 1.6, dark))
    else:                                    # "open": one line under the header, nothing else heavy
        if has_header:
            cmds.append(("LINEBELOW", (0, 0), (-1, 0), 1.1, dark))
            if design == "tinted":
                cmds.append(("BACKGROUND", (0, 0), (-1, 0), tone))
    if has_footer:
        cmds.append(("LINEABOVE", (0, last), (-1, last), 0.9, dark))
    if current is not None and 0 <= current < columns:
        x = columns - 1 - current if rtl else current
        cmds.insert(0, ("BACKGROUND", (x, 0), (x, last), tone))
    return cmds


class Masthead(Flowable):
    """A title block in a band of colour running to the page edges: a short document's
    opening, in place of a cover page."""

    def __init__(self, paras, fill: Optional[str], pad: float, after: float, edges=None, rtl=False):
        super().__init__()
        self.paras, self.fill, self.pad, self.after = paras, fill, pad, after
        self.edges, self.rtl = edges or {}, rtl     # {top | bottom | start | end: (colour, width)}

    def wrap(self, aW, aH):
        self.w = aW
        self.inset = 16.0 if "start" in self.edges else 0.0
        self.top = 0.0 if self.fill else (self.pad if "top" in self.edges else 0.0)
        self.heights = [p.wrap(aW - 2 * self.inset, aH)[1] + p.style.spaceAfter for p in self.paras]
        self.h = sum(self.heights) + self.pad + self.top
        return aW, self.h

    def getSpaceAfter(self):
        return self.after

    def draw(self):
        c = self.canv
        x, y0 = c.absolutePosition(0, 0)
        width, height = c._pagesize
        if self.fill:                               # a band to the page edges, with a strip along its foot
            c.setFillColor(HexColor(self.fill))
            c.rect(-x, 0, width, height - y0, fill=1, stroke=0)
            if "bottom" in self.edges:
                color, weight = self.edges["bottom"]
                c.setFillColor(HexColor(color))
                c.rect(-x, 0, width, weight, fill=1, stroke=0)
        else:                                       # on the paper: rules round the title
            lines = {"top": (0, self.h, self.w, self.h), "bottom": (0, 0, self.w, 0),
                     "start": (self.w, 0, self.w, self.h) if self.rtl else (0, 0, 0, self.h),
                     "end": (0, 0, 0, self.h) if self.rtl else (self.w, 0, self.w, self.h)}
            for side, (color, weight) in self.edges.items():
                c.setStrokeColor(HexColor(color))
                c.setLineWidth(weight)
                c.line(*lines[side])
        y = self.h - self.top
        for p, h in zip(self.paras, self.heights):
            y -= h
            p.drawOn(c, self.inset, y + p.style.spaceAfter)


def masthead_spec(block, theme):
    """(fill or None, ink, centred, edges) of the masthead a design asked for, for both renderers."""
    hints = block.hints or {}
    style = hints.get("masthead")
    main = block.background_color or A.ink(theme)
    accent = hints.get("rule") or theme.colors.accent
    return {
        "strip": (main, "#ffffff", False, {"bottom": (accent, 5.0)}),
        "tint": (A.mix(main, "#ffffff", 0.88), main, False, {"bottom": (main, 2.5)}),
        "rule": (None, main, False, {"top": (main, 4.0)}),
        "centred": (None, main, True, {"top": (main, 0.8), "bottom": (main, 0.8)}),
        "bar": (None, main, False, {"start": (main, 7.0)}),
        "framed": (None, main, True, {side: (main, 1.2) for side in ("top", "bottom", "start", "end")}),
    }.get(style, (main, block.text_color or "#ffffff", False, {}))


def masthead(block, theme, ctx) -> list:
    rtl = A.is_rtl(block.title) or ctx.page_geometry.rtl
    base = theme.typography.base_size
    fill, ink, centred, edges = masthead_spec(block, theme)
    align = 1 if centred else 2 if rtl else 0
    size = base * float((block.hints or {}).get("title_scale", 2.5))
    paras = [_para(theme, block.title, size, ink, align, bold=True, ratio=1.15, after=size * 0.3)]
    if block.subtitle:
        paras.append(_para(theme, block.subtitle, base * 1.15, ink, align, heading=False, ratio=1.35, after=4))
    if block.author:
        paras.append(_para(theme, block.author, base * 0.9, ink, align, heading=False, ratio=1.4, after=0))
    return [Masthead(paras, fill, 18.0, theme.spacing.block_gap * 2, edges, rtl)]
