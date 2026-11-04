"""
Band layout for the slot-based headers and footers, shared by PDF and DOCX.

A band's columns and heights are worked out here once: PDF draws them, and DOCX uses
the same column widths for its table and the same heights for its margins, so the
body text starts in the same place in both.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from reportlab.lib.colors import HexColor
from reportlab.pdfbase.pdfmetrics import stringWidth

from ..fonts import get_font_name
from ..media import MediaAsset, ingest
from ..schema.page_system import Band, BandRow, Logo, PageSystem
from ..utils.errors import DynamicPDFError

_FIELD = re.compile(r"\{(\w+)\}")
_ARABIC = re.compile("[֐-ࣿיִ-﷿ﹰ-﻿]")
_COLUMN_GAP = 12.0
_LOGO_GAP = 7.0
SAMPLE = {"page": "000", "pages": "000"}


def fill_fields(text: str, values: Dict[str, str]) -> str:
    """Field values in ``text``. An unknown or empty field is dropped, with the
    separator it leaves behind, so an unset ``{period}`` cannot print as a stray dot."""
    out = _FIELD.sub(lambda m: str(values.get(m.group(1), "")), text)
    out = re.sub(r"(\s*[·|•]\s*){2,}", lambda m: m.group(1), out)
    return re.sub(r"^\s*[·|•]\s*|\s*[·|•]\s*$", "", out).strip()


def font_for(theme, text: str, bold: bool) -> str:
    if _ARABIC.search(text):
        return get_font_name(theme.typography.arabic_family or "Amiri", bold=bold)
    return get_font_name(theme.typography.body_family, bold=bold)


def text_width(theme, text: str, size: float, bold: bool) -> float:
    if _ARABIC.search(text):
        from .factory import _apply_rtl
        return stringWidth(_apply_rtl(text), font_for(theme, text, bold), size)
    return stringWidth(text, font_for(theme, text, bold), size)


def wrap_text(theme, text: str, size: float, bold: bool, width: float, max_lines: int):
    """Logical-order lines, and whether text had to be cut to fit."""
    lines, current = [], ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        if not current or text_width(theme, trial, size, bold) <= width:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    if len(lines) <= max_lines and all(text_width(theme, ln, size, bold) <= width for ln in lines):
        return lines, False
    lines = lines[:max_lines]
    last = lines[-1] if lines else ""
    while last and text_width(theme, last + "…", size, bold) > width:
        last = last[:-1].rstrip()
    if lines:
        lines[-1] = last + "…"
    return lines, True


@dataclass
class Cell:
    x: float
    width: float
    align: str                                   # left, center or right
    logos: List[Tuple[MediaAsset, float, float, Logo]] = field(default_factory=list)
    lines: List[str] = field(default_factory=list)
    raw: List[str] = field(default_factory=list)  # item templates, for live Word fields
    items: list = field(default_factory=list)
    height: float = 0


@dataclass
class Row:
    spec: BandRow
    cells: List[Cell]
    height: float
    size: float
    leading: float


@dataclass
class BandLayout:
    rows: List[Row]
    height: float
    accent: float


def _logo_size(asset: MediaAsset, logo: Logo) -> Tuple[float, float]:
    w = min(logo.max_width, logo.max_height * asset.aspect)
    return w, w / asset.aspect


def _column_widths(left: float, center: float, right: float, total: float) -> Tuple[float, float, float]:
    """Keep a centre slot on the page's centre line; sides take what remains. Without
    one, the wider side gives way only as far as it has to."""
    gap = _COLUMN_GAP
    if center:
        mid = min(center, total * 0.56)
        side = (total - mid - 2 * gap) / 2
        return (side if left else 0), mid, (side if right else 0)
    if not (left and right):
        return (total if left else 0), 0, (total if right else 0)
    room = total - gap
    if left + right <= room:
        return room - right, 0, right
    share = left / (left + right)
    lw = min(max(room * share, room * 0.3), room * 0.7)
    return lw, 0, room - lw


class BandMaker:
    """Lays out bands for one document."""

    def __init__(self, theme, system: PageSystem, rtl: bool, policy, collector, values=None):
        self.theme, self.system, self.rtl = theme, system, rtl
        self.policy, self.collector = policy, collector
        self.values = dict(values or {})
        self._assets: Dict[str, Optional[MediaAsset]] = {}

    def asset(self, logo: Logo) -> Optional[MediaAsset]:
        if logo.src not in self._assets:
            try:
                self._assets[logo.src] = ingest(logo.src, self.policy)
            except DynamicPDFError as e:
                self._assets[logo.src] = None
                self.collector.fail("asset_failed", f"Band logo: {e}", e)
        return self._assets[logo.src]

    def _size(self, row: BandRow) -> float:
        return row.size or max(7.5, self.theme.typography.footer_text_size + 1)

    def _natural(self, items, row: BandRow, size: float, values) -> float:
        logo_w, text_w = 0.0, 0.0
        for it in items:
            if isinstance(it, Logo):
                a = self.asset(it)
                if a:
                    logo_w += _logo_size(a, it)[0] + _LOGO_GAP
            else:
                text = fill_fields(it, values)
                text_w = max(text_w, text_width(self.theme, text, size, row.bold) if text else 0)
        return logo_w + text_w

    def _cell(self, items, row, x, width, align, size, leading, values, warn) -> Cell:
        cell = Cell(x, width, align, items=list(items))
        text_room = width
        for it in items:
            if isinstance(it, Logo):
                a = self.asset(it)
                if a:
                    w, h = _logo_size(a, it)
                    cell.logos.append((a, w, h, it))
                    text_room -= w + _LOGO_GAP
        budget = row.max_lines
        for it in items:
            if isinstance(it, Logo) or budget <= 0:
                continue
            text = fill_fields(it, values)
            if not text:
                continue
            lines, cut = wrap_text(self.theme, text, size, row.bold, max(text_room, 12), budget)
            cell.lines += lines
            cell.raw.append(it)
            budget -= len(lines)
            if cut and warn:
                self.collector.warn("band_overflow", f"Band text was cut to fit its slot: {text[:60]}")
        logos_h = max((h for _, _, h, _ in cell.logos), default=0)
        cell.height = max(logos_h, len(cell.lines) * leading)
        return cell

    def layout(self, band: Band, width: float, values=None, warn: bool = False) -> BandLayout:
        merged = {**self.values, **SAMPLE, **(values or {})}
        rows, total = [], 0.0
        for spec in band.rows:
            size = self._size(spec)
            leading = size * (1.42 if self._has_arabic(spec, merged) else 1.26)
            left, center, right = spec.slots(self.rtl)
            nat = [self._natural(s, spec, size, merged) for s in (left, center, right)]
            lw, cw, rw = _column_widths(*nat, width)
            cells = []
            if left:
                cells.append(self._cell(left, spec, 0, lw, "left", size, leading, merged, warn))
            if center:
                cells.append(self._cell(center, spec, (width - cw) / 2, cw, "center", size, leading, merged, warn))
            if right:
                cells.append(self._cell(right, spec, width - rw, rw, "right", size, leading, merged, warn))
            height = max([c.height for c in cells] + [leading if not cells else 0])
            if spec.fill:
                height += band.padding * 2
            if spec.rule_below:
                height += 3
            gap = band.row_gap if rows else 0
            if band.max_height and total + gap + height > band.max_height and rows:
                if warn:
                    self.collector.warn("band_overflow", "A band row was dropped to stay within max_height")
                break
            total += gap + height
            rows.append(Row(spec, cells, height, size, leading))
        accent = band.accent_height if band.accent_color else 0
        return BandLayout(rows, total + accent, accent)

    def _has_arabic(self, row: BandRow, values) -> bool:
        for items in (row.left, row.center, row.right, row.start, row.end):
            for it in items:
                if isinstance(it, str) and _ARABIC.search(fill_fields(it, values)):
                    return True
        return False


def margin_needs(maker: BandMaker, width: float, sample_values=None) -> Tuple[float, float]:
    """The page margins that clear the tallest header and footer in the system."""
    sys = maker.system
    heads, feet = sys.bands()
    top = max((maker.layout(b, width, sample_values, warn=True).height for b in heads), default=0)
    bottom = max((maker.layout(b, width, sample_values, warn=True).height for b in feet), default=0)
    return (top + sys.edge_distance + sys.body_gap if heads else 0,
            bottom + sys.edge_distance + sys.body_gap if feet else 0)


def pick_bands(sys: PageSystem, page: int, section: Optional[str]):
    """The header and footer for a page."""
    if page == 1 and sys.first_page == "none":
        return None, None
    if page == 1 and sys.first_page == "custom":
        return sys.first_header, sys.first_footer
    head, foot = sys.header, sys.footer
    if page % 2 == 0:
        head, foot = sys.even_header or head, sys.even_footer or foot
    override = sys.sections.get(section) if section else None
    if override:
        head, foot = override.header or head, override.footer or foot
    return head, foot


def readable_on(hex_fill: str) -> str:
    """Dark or light text for a filled row."""
    c = HexColor(hex_fill)
    lum = 0.2126 * c.red + 0.7152 * c.green + 0.0722 * c.blue
    return "#FFFFFF" if lum < 0.55 else "#1F2933"


def draw_band(canv, layout: BandLayout, band: Band, theme, x: float, top: float, page_w: float,
              is_header: bool) -> None:
    """Draw with the band's upper edge at ``top``, measured from the page bottom."""
    from .media_flow import draw_media
    from ..media import fit_image
    y = top
    canv.saveState()
    canv._dpb_bidi = True
    accent_on_top = (band.accent_edge == "outer") == is_header
    if layout.accent and accent_on_top:
        _accent(canv, band, x, y - layout.accent, page_w)
        y -= layout.accent
    default_ink = theme.colors.text_muted
    for k, row in enumerate(layout.rows):
        if k:
            y -= band.row_gap
        spec = row.spec
        span_x, span_w = (0, page_w) if band.bleed else (x, page_w - 2 * x)
        if spec.fill:
            canv.setFillColor(HexColor(spec.fill))
            canv.rect(span_x, y - row.height, span_w, row.height, fill=1, stroke=0)
        ink = spec.color or (readable_on(spec.fill) if spec.fill else default_ink)
        inner_h = row.height - (band.padding * 2 if spec.fill else 0) - (3 if spec.rule_below else 0)
        inner_top = y - (band.padding if spec.fill else 0)
        for cell in row.cells:
            _draw_cell(canv, cell, row, theme, x, inner_top, inner_h, ink, draw_media, fit_image)
        if spec.rule_below:
            canv.setStrokeColor(HexColor(spec.rule_color or theme.colors.border))
            canv.setLineWidth(spec.rule_width)
            canv.line(span_x if band.bleed else x, y - row.height + 0.5,
                      span_x + span_w, y - row.height + 0.5)
        y -= row.height
    if layout.accent and not accent_on_top:
        _accent(canv, band, x, y - layout.accent, page_w)
    canv._dpb_bidi = False
    canv.restoreState()


def _accent(canv, band: Band, x: float, y: float, page_w: float) -> None:
    canv.setFillColor(HexColor(band.accent_color))
    span_x, span_w = (0, page_w) if band.bleed else (x, page_w - 2 * x)
    canv.rect(span_x, y, span_w, band.accent_height, fill=1, stroke=0)


def _draw_cell(canv, cell: Cell, row: Row, theme, x0, top, height, ink, draw_media, fit_image) -> None:
    logos_w = sum(w + _LOGO_GAP for _, w, _, _ in cell.logos)
    text_w = max((text_width(theme, ln, row.size, row.spec.bold) for ln in cell.lines), default=0)
    used = logos_w + text_w - (_LOGO_GAP if cell.logos and not cell.lines else 0)
    left = x0 + cell.x
    start = {"left": left, "center": left + (cell.width - used) / 2,
             "right": left + cell.width - used}[cell.align]
    cursor = start
    for asset, w, h, _ in cell.logos:
        f = fit_image(asset, w, h)
        draw_media(canv, asset, f, cursor, top - (height + h) / 2)
        cursor += w + _LOGO_GAP
    block_h = len(cell.lines) * row.leading
    baseline = top - (height - block_h) / 2 - row.size * (1.02 if row.leading > row.size * 1.3 else 0.96)
    canv.setFillColor(HexColor(ink))
    for line in cell.lines:
        canv.setFont(font_for(theme, line, row.spec.bold), row.size)
        if cell.align == "right":
            canv.drawRightString(left + cell.width, baseline, line)
        elif cell.align == "center":
            canv.drawCentredString(left + cell.width / 2 + logos_w / 2, baseline, line)
        else:
            canv.drawString(cursor, baseline, line)
        baseline -= row.leading
