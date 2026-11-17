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
_LIVE_FIELDS = {"page", "pages", "section", "chapter"}
_MAX_SECTION_SAMPLES = 64
_MIN_LOGO_HEIGHT = 12.0
_LOGO_SHRINK = 0.75


class BandContentUnfit(DynamicPDFError):
    """Band content cannot be set whole within the limits its author gave."""


@dataclass(frozen=True)
class BandLoss:
    """Something a band would not show."""
    kind: str                # ellipsis, item_dropped, row_dropped, unknown_field
    text: str

    def describe(self) -> str:
        return f"{self.kind}: {self.text[:60]}"


def missing_fields(template: str, values: Dict[str, str], optional=()) -> List[str]:
    """Fields in ``template`` with no value, leaving out those filled in per page and
    those the author declared optional."""
    return [name for name in _FIELD.findall(template)
            if name not in _LIVE_FIELDS and name not in optional and not values.get(name)]


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
    width += 0.01                                # a slot sized to its text must hold it despite rounding
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
    rtl: bool = False                            # logos come first in reading order: at the right


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
    losses: List[BandLoss] = field(default_factory=list)
    reflowed: List[str] = field(default_factory=list)


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
        self.section_samples: List[str] = []

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

    def _cell(self, items, row, x, width, align, size, leading, values, warn, losses) -> Cell:
        cell = Cell(x, width, align, items=list(items), rtl=self.rtl)
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
            if isinstance(it, Logo):
                continue
            text = fill_fields(it, values)
            if not text:
                continue
            if budget <= 0:
                losses.append(BandLoss("item_dropped", it))
                continue
            lines, cut = wrap_text(self.theme, text, size, row.bold, max(text_room, 12), budget)
            cell.lines += lines
            cell.raw.append(it)
            budget -= len(lines)
            if cut:
                losses.append(BandLoss("ellipsis", it))
            if cut and warn:
                self.collector.warn("band_overflow", f"Band text was cut to fit its slot: {text[:60]}")
        logos_h = max((h for _, _, h, _ in cell.logos), default=0)
        cell.height = max(logos_h, len(cell.lines) * leading)
        return cell

    def layout(self, band: Band, width: float, values=None, warn: bool = False) -> BandLayout:
        """The band's rows. ``losses`` lists anything left out; a lossless system first
        moves slots and items onto rows of their own and shrinks logos to avoid that."""
        if not self.system.lossless:
            return self._layout(band, band.rows, width, values, warn)
        first = self._layout(band, band.rows, width, values, False)
        cuts = [x for x in first.losses if x.kind != "unknown_field"]
        if not cuts:
            return first
        rows = [r for spec in band.rows for r in self._split_row(spec)]
        split = self._layout(band, rows, width, values, False)
        split.reflowed.append("slots moved to their own rows")
        if any(x.kind == "row_dropped" for x in split.losses):
            small = self._layout(band, [self._smaller_logos(r) for r in rows], width, values, False)
            small.reflowed += split.reflowed + ["logos reduced"]
            split = small
        return split

    def _split_row(self, spec: BandRow) -> List[BandRow]:
        """One row for each text item, in reading order; logos stay with the first item
        of their slot. Only the last row keeps the rule."""
        left, center, right = spec.slots(self.rtl)
        slots = [("left", left), ("center", center), ("right", right)]
        pieces = []
        for side, items in reversed(slots) if self.rtl else slots:
            logos = [i for i in items if isinstance(i, Logo)]
            texts = [i for i in items if not isinstance(i, Logo)] or [None]
            for k, text in enumerate(texts):
                held = (logos if k == 0 else []) + ([text] if text is not None else [])
                if held:
                    pieces.append((side, held))
        common = spec.model_dump(exclude={"left", "center", "right", "start", "end", "rule_below"})
        last = len(pieces) - 1
        return [BandRow(**common, **{side: held}, rule_below=spec.rule_below and k == last)
                for k, (side, held) in enumerate(pieces)] or [spec]

    def _smaller_logos(self, spec: BandRow) -> BandRow:
        def smaller(item):
            if not isinstance(item, Logo):
                return item
            height = max(_MIN_LOGO_HEIGHT, item.max_height * _LOGO_SHRINK)
            return item.model_copy(update={"max_height": min(height, item.max_height)})
        return spec.model_copy(update={k: [smaller(i) for i in getattr(spec, k)]
                                       for k in ("left", "center", "right", "start", "end")})

    def _layout(self, band: Band, specs, width: float, values, warn: bool) -> BandLayout:
        merged = {**self.values, **SAMPLE, **(values or {})}
        rows, total, losses = [], 0.0, []
        for k, spec in enumerate(specs):
            size = self._size(spec)
            leading = size * (1.42 if self._has_arabic(spec, merged) else 1.26)
            left, center, right = spec.slots(self.rtl)
            nat = [self._natural(s, spec, size, merged) for s in (left, center, right)]
            lw, cw, rw = _column_widths(*nat, width)
            cells = []
            if left:
                cells.append(self._cell(left, spec, 0, lw, "left", size, leading, merged, warn, losses))
            if center:
                cells.append(self._cell(center, spec, (width - cw) / 2, cw, "center", size, leading, merged,
                                        warn, losses))
            if right:
                cells.append(self._cell(right, spec, width - rw, rw, "right", size, leading, merged, warn,
                                        losses))
            height = max([c.height for c in cells] + [leading if not cells else 0])
            if spec.fill:
                height += band.padding * 2
            if spec.rule_below:
                height += 3
            gap = band.row_gap if rows else 0
            if band.max_height and total + gap + height > band.max_height and rows:
                if warn:
                    self.collector.warn("band_overflow", "A band row was dropped to stay within max_height")
                losses += [BandLoss("row_dropped", _row_label(r)) for r in specs[k:]]
                break
            total += gap + height
            rows.append(Row(spec, cells, height, size, leading))
        accent = band.accent_height if band.accent_color else 0
        if self.system.lossless:
            losses += [BandLoss("unknown_field", name) for spec in specs
                       for item in _texts(spec)
                       for name in missing_fields(item, merged, self.system.optional_fields)]
        return BandLayout(rows, total + accent, accent, losses)

    def audit(self, width: float, sample=None) -> List[BandLoss]:
        """All that any band of the system would leave out, for every running title."""
        found: Dict[BandLoss, None] = {}
        heads, feet = self.system.bands()
        for band in heads + feet:
            for values in self._variants(width, sample):
                found.update(dict.fromkeys(self.layout(band, width, values).losses))
        return list(found)

    def _variants(self, width: float, sample) -> List[dict]:
        """The sample values, then each possible running title, widest first: a title
        with fewer letters can still be the wider one."""
        size = self.theme.typography.footer_text_size + 1
        titles = sorted(self.section_samples, key=lambda t: -text_width(self.theme, t, size, False))
        return [sample or {}] + [{"section": t, "chapter": t} for t in titles[:_MAX_SECTION_SAMPLES]]

    def _has_arabic(self, row: BandRow, values) -> bool:
        for items in (row.left, row.center, row.right, row.start, row.end):
            for it in items:
                if isinstance(it, str) and _ARABIC.search(fill_fields(it, values)):
                    return True
        return False


def _texts(spec: BandRow) -> List[str]:
    return [i for k in ("left", "center", "right", "start", "end") for i in getattr(spec, k)
            if isinstance(i, str)]


def _row_label(spec: BandRow) -> str:
    return " / ".join(_texts(spec)) or "logo row"


def margin_needs(maker: BandMaker, width: float, sample_values=None) -> Tuple[float, float]:
    """The page margins that clear the tallest header and footer in the system."""
    sys = maker.system
    heads, feet = sys.bands()
    variants = maker._variants(width, sample_values) if sys.lossless else [sample_values]
    top = max((maker.layout(b, width, v, warn=True).height for b in heads for v in variants), default=0)
    bottom = max((maker.layout(b, width, v, warn=True).height for b in feet for v in variants), default=0)
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
    # in reading order the logo leads: on the left, or on the right of the text in right-to-left documents
    text_right = start + text_w
    cursor = text_right + (_LOGO_GAP if cell.lines else 0) if cell.rtl else start
    for asset, w, h, _ in cell.logos:
        f = fit_image(asset, w, h)
        draw_media(canv, asset, f, cursor, top - (height + h) / 2)
        cursor += w + _LOGO_GAP
    block_h = len(cell.lines) * row.leading
    baseline = top - (height - block_h) / 2 - row.size * (1.02 if row.leading > row.size * 1.3 else 0.96)
    canv.setFillColor(HexColor(ink))
    for line in cell.lines:
        canv.setFont(font_for(theme, line, row.spec.bold), row.size)
        if cell.rtl and cell.logos:
            canv.drawRightString(text_right, baseline, line)
        elif cell.align == "right":
            canv.drawRightString(left + cell.width, baseline, line)
        elif cell.align == "center":
            canv.drawCentredString(left + cell.width / 2 + logos_w / 2, baseline, line)
        else:
            canv.drawString(cursor, baseline, line)
        baseline -= row.leading
