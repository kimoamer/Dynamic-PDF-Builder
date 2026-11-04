"""
Layout archetypes: fit decisions shared by the PDF and DOCX renderers.

An archetype is an opt-in page composition with its own block type. Before
drawing, each one measures its content and returns a plan: type sizes, columns,
what moves to the following flow. When the content cannot fit, ``ok`` is False
and ``lower`` gives the same content as plain blocks, so no text is ever lost.

Proportions are relative to the page or text block. Nothing here reads a
reference document at run time.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import List, Optional

from ..schema.blocks import (BulletListBlock, HeadingBlock, MetricItem, MetricRowBlock, NoteBlock,
                             ParagraphBlock, TableBlock)
from ..schema.theme import Theme
from ..utils.color import contrast_ratio, hex_to_rgb, rgb_to_hex

ARCHETYPE_TYPES = ("section_opener", "performance_page", "parallel_ledger")

STRIP_RATIO = 0.30            # opener strip, share of the page width
OPENER_TOPS = (0.36, 0.30, 0.24)
MAX_TITLE_LINES = 4
MAX_POINTS = 6
MAX_CHAPTERS = 8
MAX_TILES = 8
MAX_TRENDS = 4
MAX_PERIODS = 6
MIN_GAP, MAX_GAP = 14.0, 44.0
EMPHASIS_SCALES = (1.3, 1.15, 1.0)
_ARABIC = re.compile("[؀-ۿݐ-ݿ]")


def is_rtl(text: Optional[str]) -> bool:
    from ..core.normalize import is_rtl_text
    return is_rtl_text(text or "")


def face(theme: Theme, text: str, bold: bool = False, heading: bool = True) -> str:
    """Registered font for one string: Arabic text takes the bundled Arabic face."""
    from ..fonts import get_font_name
    if is_rtl(text):
        return get_font_name("Amiri", bold=bold)
    ty = theme.typography
    return get_font_name(ty.heading_family if heading else ty.body_family, bold=bold)


def leading(text: str, ratio: float) -> float:
    """Line height ratio: Arabic needs room for its diacritics."""
    return max(ratio, 1.6) if _ARABIC.search(text or "") else ratio


def measure(theme: Theme, text: str, size: float, width: float, bold: bool = False,
            ratio: float = 1.3, heading: bool = True) -> float:
    """Height of ``text`` set at ``size`` in ``width``, with the renderer's own line breaking."""
    from reportlab.lib.styles import ParagraphStyle

    from ..layout.factory import Paragraph, _md_inline
    sty = ParagraphStyle("m", fontName=face(theme, text, bold, heading), fontSize=size,
                         leading=size * leading(text, ratio))
    return Paragraph(_md_inline(text), sty).wrap(width, 1e6)[1]


def text_width(theme: Theme, text: str, size: float, bold: bool = False) -> float:
    from reportlab.pdfbase.pdfmetrics import stringWidth
    return stringWidth(text, face(theme, text, bold), size)


def mix(hex_color: str, other: str, amount: float) -> str:
    a, b = hex_to_rgb(hex_color), hex_to_rgb(other)
    return rgb_to_hex(*(round(x + (y - x) * amount) for x, y in zip(a, b)))


def ink(theme: Theme) -> str:
    """The theme's primary colour, darkened until white text on it reads at 4.5:1."""
    color = theme.colors.primary
    for _ in range(12):
        if contrast_ratio(color, "#ffffff") >= 4.5:
            break
        color = mix(color, "#000000", 0.12)
    return color


def tint(theme: Theme, amount: float) -> str:
    return mix(ink(theme), "#ffffff", amount)


def arabic_digits(text: str) -> str:
    return text.translate(str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩"))


# ═════════════════════════ Section opener ═════════════════════════

@dataclass
class Part:
    """One line group of the opener, top to bottom. Colours are named, not fixed."""
    role: str                 # label | rule | title | title_alt | standfirst | standfirst_alt | point
    text: str = ""
    size: float = 0.0
    bold: bool = False
    ratio: float = 1.3
    before: float = 0.0
    color: str = "text"       # ink | text | muted
    far_edge: bool = False    # set from the edge opposite the page's reading start


@dataclass
class OpenerPlan:
    ok: bool
    rtl: bool = False
    strip: float = 0.0
    field_x: float = 0.0      # from the left edge of the page
    field_w: float = 0.0
    top: float = 0.0          # share of the page height
    title_size: float = 0.0
    parts: List[Part] = field(default_factory=list)
    chapters: List[str] = field(default_factory=list)
    spill: list = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


def _opener_parts(b, theme: Theme, label: Optional[str], title_size: float, points: List[str],
                  rtl: bool) -> List[Part]:
    base = theme.typography.base_size
    parts: List[Part] = []
    if label:
        size = base * (4.2 if len(label) <= 3 else 1.5)
        parts.append(Part("label", label, size, True, 1.1, 0, "ink"))
    parts.append(Part("rule", before=8))
    parts.append(Part("title", b.title, title_size, True, 1.14, 16, "text"))
    if b.title_alt:
        parts.append(Part("title_alt", b.title_alt, title_size * 0.74, True, 1.2, 10, "text",
                          far_edge=is_rtl(b.title_alt) != rtl))
    if b.standfirst:
        parts.append(Part("standfirst", b.standfirst, base * 1.2, False, 1.45, 18, "muted"))
    if b.standfirst_alt:
        parts.append(Part("standfirst_alt", b.standfirst_alt, base * 1.2, False, 1.45, 8, "muted",
                          far_edge=is_rtl(b.standfirst_alt) != rtl))
    for i, point in enumerate(points):
        parts.append(Part("point", point, base, False, 1.35, 16 if i == 0 else 7, "text",
                          far_edge=is_rtl(point) != rtl))
    return parts


def _parts_height(parts: List[Part], theme: Theme, width: float) -> float:
    total = 0.0
    for p in parts:
        total += p.before
        total += 1.0 if p.role == "rule" else measure(theme, p.text, p.size, width, p.bold, p.ratio,
                                                      heading=p.role in ("label", "title", "title_alt"))
    return total


def plan_opener(b, theme: Theme, page_w: float, page_h: float, label: Optional[str] = None) -> OpenerPlan:
    sp, base = theme.spacing, theme.typography.base_size
    rtl = is_rtl(b.title)
    strip = page_w * STRIP_RATIO
    gap = max(24.0, page_w * 0.05)
    far = sp.page_margin_left if rtl else sp.page_margin_right
    field_w = page_w - strip - gap - far
    field_x = far if rtl else strip + gap
    limit = page_h - sp.page_margin_bottom
    label = label or b.label
    shown = b.points[:MAX_POINTS]
    chapters = b.chapters if 2 <= len(b.chapters) <= MAX_CHAPTERS else []
    notes = []
    if b.chapters and not chapters:
        notes.append(f"{len(b.chapters)} chapters do not fit the strip: plain strip used")
    for keep in range(len(shown), -1, -1):
        for scale in (3.4, 3.0, 2.6, 2.2):
            size = base * scale
            line = size * leading(b.title, 1.14)
            if measure(theme, b.title, size, field_w, True, 1.14) > line * MAX_TITLE_LINES + 0.5:
                continue
            parts = _opener_parts(b, theme, label, size, shown[:keep], rtl)
            height = _parts_height(parts, theme, field_w)
            for top in OPENER_TOPS:
                if page_h * top + height <= limit:
                    spill = list(b.points[keep:])
                    if spill:
                        notes.append(f"{len(spill)} key point(s) moved to the following page")
                    return OpenerPlan(True, rtl, strip, field_x, field_w, top, size, parts, chapters,
                                      [BulletListBlock(items=spill)] if spill else [], notes)
    return OpenerPlan(False, rtl, notes=notes + ["title and standfirst do not fit the opener page"])


# ═════════════════════════ Performance page ═════════════════════════

@dataclass
class PerformancePlan:
    ok: bool
    rtl: bool = False
    hero_size: float = 0.0
    tile_cols: int = 0
    tile_rows: int = 0
    highlight_cols: int = 1
    highlights: List[str] = field(default_factory=list)
    gap: float = MIN_GAP
    spill: list = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


def trend_text(series, i: int) -> str:
    if series.display and i < len(series.display):
        return series.display[i]
    return f"{series.values[i]:,g}"


def trend_span(values: List[float]) -> tuple:
    """(zero, scale): bar geometry on a 0..1 axis. Negative values share one zero line."""
    lo, hi = min(0.0, min(values)), max(0.0, max(values))
    span = (hi - lo) or 1.0
    return -lo / span, 1.0 / span


def head_height(b, theme: Theme, width: float) -> float:
    base = theme.typography.base_size
    h = measure(theme, b.title, base * 2.4, width, True, 1.15)
    if b.eyebrow:
        h += measure(theme, b.eyebrow, base * 0.9, width, True, 1.3) + 4
    if b.standfirst:
        h += measure(theme, b.standfirst, base * 1.15, width, False, 1.4, heading=False) + 8
    return h


def hero_side_height(b, theme: Theme, width: float) -> float:
    base, hero = theme.typography.base_size, b.hero
    h = measure(theme, hero.label, base * 1.15, width, True, 1.3)
    if hero.delta:
        h += measure(theme, hero.delta, base * 0.95, width, True, 1.3) + 3
    if hero.note:
        h += measure(theme, hero.note, base * 0.9, width, False, 1.35, heading=False) + 3
    return h


def hero_band(b, size: float, theme: Theme, side: float) -> float:
    return max(size * leading(b.hero.value, 1.08), hero_side_height(b, theme, side)) + 8


def tile_height(tile, theme: Theme, width: float) -> float:
    base = theme.typography.base_size
    h = measure(theme, tile.value, base * 2.0, width, True, 1.15)
    h += measure(theme, tile.label, base * 0.88, width, False, 1.3, heading=False) + 2
    if tile.delta:
        h += measure(theme, tile.delta, base * 0.82, width, True, 1.3) + 2
    return h


def trend_row(theme: Theme) -> float:
    return theme.typography.base_size * 0.88 * 1.3 + 9


def trend_height(series, theme: Theme, width: float) -> float:
    base = theme.typography.base_size
    return (measure(theme, series.label, base * 0.95, width, True, 1.3) + 6
            + len(series.periods) * trend_row(theme))


def highlights_height(items: List[str], cols: int, theme: Theme, width: float) -> float:
    if not items:
        return 0.0
    base = theme.typography.base_size
    w = (width - 24 - 14 * (cols - 1)) / cols - 12
    per = math.ceil(len(items) / cols)
    tallest = 0.0
    for c in range(cols):
        col = items[c * per:(c + 1) * per]
        tallest = max(tallest, sum(measure(theme, t, base, w, False, 1.35, heading=False) + 5 for t in col))
    return tallest + 20


def _strata_height(b, plan: PerformancePlan, theme: Theme, width: float) -> tuple:
    heights = [head_height(b, theme, width)]
    side = width * 0.36
    heights.append(hero_band(b, plan.hero_size, theme, side))
    if b.tiles:
        cw = (width - 16 * (plan.tile_cols - 1)) / plan.tile_cols
        per_row = [max(tile_height(t, theme, cw) for t in b.tiles[r * plan.tile_cols:(r + 1) * plan.tile_cols])
                   for r in range(plan.tile_rows)]
        heights.append(sum(per_row) + 12 * plan.tile_rows)
    if b.trends:
        tw = (width - 18 * (len(b.trends) - 1)) / len(b.trends)
        heights.append(max(trend_height(s, theme, tw) for s in b.trends))
    if plan.highlights:
        heights.append(highlights_height(plan.highlights, plan.highlight_cols, theme, width))
    return sum(heights), len(heights) - 1


def plan_performance(b, theme: Theme, width: float, height: float) -> PerformancePlan:
    rtl = is_rtl(b.title)
    fail = PerformancePlan(False, rtl)
    if len(b.tiles) + len(b.trends) < 2:
        fail.notes.append("needs at least two metrics or trends beside the hero figure")
        return fail
    if len(b.tiles) > MAX_TILES or len(b.trends) > MAX_TRENDS:
        fail.notes.append(f"{len(b.tiles)} tiles and {len(b.trends)} trends exceed the page")
        return fail
    for s in b.trends:
        if not 2 <= len(s.periods) <= MAX_PERIODS or len(s.periods) != len(s.values):
            fail.notes.append(f"trend {s.label!r}: periods and values do not match")
            return fail
    plan = PerformancePlan(True, rtl, highlights=list(b.highlights))
    plan.highlight_cols = 2 if len(b.highlights) >= 4 else 1
    n = len(b.tiles)
    if n:
        cols = n if n <= 4 else math.ceil(n / 2)
        widest = max(text_width(theme, t.value, theme.typography.base_size * 2.0, True) for t in b.tiles)
        while cols > 2 and widest > (width - 16 * (cols - 1)) / cols - 4:
            cols -= 1
            plan.notes.append(f"tile values are wide: {cols} columns")
        plan.tile_cols, plan.tile_rows = cols, math.ceil(n / cols)
    unit = text_width(theme, b.hero.value, 1.0, True) or 1.0
    full = min(84.0, width * 0.6 / unit, height * 0.24 / 1.08)
    for keep_highlights in (True, False):
        if not keep_highlights:
            if not plan.highlights:
                break
            plan.spill = [BulletListBlock(items=plan.highlights)]
            plan.notes.append(f"{len(plan.highlights)} highlight(s) moved to the following flow")
            plan.highlights = []
        for scale in (1.0, 0.8, 0.65):
            plan.hero_size = full * scale
            total, gaps = _strata_height(b, plan, theme, width)
            room = height - total
            if room >= MIN_GAP * gaps:
                plan.gap = min(MAX_GAP, room / gaps)
                return plan
    fail.notes.append("the strata do not fit one page")
    return fail


# ═════════════════════════ Parallel ledger ═════════════════════════

@dataclass
class LedgerPlan:
    ok: bool
    rtl: bool = False
    bilingual: bool = False
    label_w: float = 0.0      # share of the width, each label column
    value_w: List[float] = field(default_factory=list)    # by period, in period order
    emphasis_size: float = 0.0
    notes: List[str] = field(default_factory=list)


def plan_ledger(b, theme: Theme, width: float) -> LedgerPlan:
    rows = [r for s in b.sections for r in s.rows]
    n = len(b.periods)
    first = b.sections[0].title if b.sections else ""
    bilingual = any(s.title_alt for s in b.sections) or any(r.label_alt for r in rows)
    plan = LedgerPlan(False, is_rtl(first) and not bilingual, bilingual)
    if not rows or not n:
        plan.notes.append("needs at least one section with rows")
        return plan
    if any(len(r.values) != n for r in rows):
        plan.notes.append("every row needs one value per period")
        return plan
    if not 0 <= b.emphasis < n:
        plan.notes.append("the emphasised period is out of range")
        return plan
    base = theme.typography.base_size
    pad = 12.0

    def need(i: int, size: float) -> float:
        cells = [r.values[i] for r in rows]
        wide = max(text_width(theme, c, size, i == b.emphasis or r.total) for c, r in zip(cells, rows))
        return max(wide, text_width(theme, b.periods[i], base * 0.9, True)) + pad

    for scale in EMPHASIS_SCALES:
        for share in ((0.29, 0.26, 0.24) if bilingual else (0.42, 0.36, 0.30)):
            labels = share * (2 if bilingual else 1)
            size = base * scale
            widths = [need(i, size if i == b.emphasis else base) for i in range(n)]
            room = width * (1 - labels)
            spare = room - sum(widths)
            if spare < 0:
                continue
            others = [w for i, w in enumerate(widths) if i != b.emphasis] or widths
            lift = min(spare, max(0.0, 1.25 * max(others) - widths[b.emphasis]))
            widths[b.emphasis] += lift
            widths = [w + (spare - lift) / n for w in widths]
            plan.ok, plan.label_w, plan.emphasis_size = True, share, size
            plan.value_w = [w / width for w in widths]
            if scale < EMPHASIS_SCALES[0]:
                plan.notes.append("long values: emphasis size reduced")
            return plan
    plan.notes.append("the values do not fit beside the labels")
    return plan


# ═════════════════════════ Plain-block fallback ═════════════════════════

def _lead(text: str) -> ParagraphBlock:
    return ParagraphBlock(text=text, hints={"lead": True})


def lower(block) -> list:
    """The same content as plain blocks: the fallback, and the 'before' in comparisons."""
    t = block.type
    if t == "section_opener":
        title = f"{block.label}  {block.title}" if block.label else block.title
        out = [HeadingBlock(id=block.id, text=title, level=1)]
        if block.title_alt:
            out.append(_lead(block.title_alt))
        for text in (block.standfirst, block.standfirst_alt):
            if text:
                out.append(_lead(text))
        if block.points:
            out.append(BulletListBlock(items=list(block.points)))
        return out
    if t == "performance_page":
        out = [HeadingBlock(id=block.id, text=block.title, level=1)]
        if block.eyebrow:
            out.append(ParagraphBlock(text=block.eyebrow))
        if block.standfirst:
            out.append(_lead(block.standfirst))
        figures = [block.hero] + list(block.tiles)
        for i in range(0, len(figures), 4):
            out.append(MetricRowBlock(metrics=[MetricItem(label=f.label, value=f.value, delta=f.delta)
                                               for f in figures[i:i + 4]]))
        for f in figures:
            if f.note:
                out.append(NoteBlock(text=f.note))
        for s in block.trends:
            out.append(TableBlock(headers=[s.label] + list(s.periods),
                                  rows=[[""] + [trend_text(s, i) for i in range(len(s.values))]]))
        if block.highlights:
            out.append(BulletListBlock(items=list(block.highlights)))
        return out
    if t == "parallel_ledger":
        out = []
        bilingual = any(r.label_alt for s in block.sections for r in s.rows)
        for s in block.sections:
            head = [block.label_header or ""] + list(block.periods)
            if bilingual:
                head.append(block.label_header_alt or "")
            rows = []
            for r in s.rows:
                row = [r.label] + list(r.values)
                if bilingual:
                    row.append(r.label_alt or "")
                rows.append(row)
            caption = f"{s.title} / {s.title_alt}" if s.title_alt else s.title
            out.append(TableBlock(headers=head, rows=rows, caption=caption))
            if s.note:
                out.append(NoteBlock(text=s.note))
        return out
    return [block]


def lowered(blocks: list) -> list:
    """A block list with every archetype replaced by its plain form."""
    out: list = []
    for b in blocks:
        if getattr(b, "type", None) in ARCHETYPE_TYPES:
            parts = lower(b)
            if out and b.type in ("section_opener", "performance_page"):
                from ..schema.blocks import PageBreakBlock
                parts = [PageBreakBlock()] + parts
            out.extend(parts)
        else:
            out.append(b)
    return out
