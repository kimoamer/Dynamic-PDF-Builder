"""
PDF drawing for the layout archetypes. Fit decisions live in design/archetypes.py;
this module only places what the plan decided. Text goes through the factory
``Paragraph``, so shaping, diacritics and bidi match every other block.
"""
from __future__ import annotations

from typing import List, Optional

from reportlab.lib.colors import HexColor
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import PageBreak, Spacer, Table, TableStyle
from reportlab.platypus.flowables import Flowable, PageBreakIfNotEmpty

from .. import policy as _diag
from ..design import archetypes as A
from ..layout.factory import Paragraph, _md_inline, _strip_markdown, create_flowables


def _text(theme, text: str, size: float, color: str, align: int, bold=False, ratio=1.3,
          heading=True) -> Paragraph:
    sty = ParagraphStyle("arch", fontName=A.face(theme, text, bold, heading), fontSize=size,
                         leading=size * A.leading(text, ratio), textColor=HexColor(color),
                         alignment=align, allowWidows=0, allowOrphans=0)
    return Paragraph(_md_inline(text), sty)


def _place(c, para: Paragraph, x: float, top: float, width: float) -> float:
    """Draw ``para`` with its top edge at ``top``; returns its height."""
    h = para.wrap(width, 1e6)[1]
    para.drawOn(c, x, top - h)
    return h


def _new_page(ctx) -> list:
    return [] if ctx.first_block else [PageBreakIfNotEmpty()]


def _colors(theme) -> dict:
    return {"ink": A.ink(theme), "text": theme.colors.text_primary, "muted": theme.colors.text_secondary}


# ═════════════════════════ Section opener ═════════════════════════

class SectionOpener(Flowable):
    """Draws in page coordinates on a page of its own. The frame sees a 1 pt line,
    and ``canv._dpb_bare`` tells the page handler to skip the header and footer."""

    def __init__(self, block, theme, plan: A.OpenerPlan, toc_entry):
        super().__init__()
        self.block, self.theme, self.plan = block, theme, plan
        self._toc_entry = toc_entry

    def wrap(self, aW, aH):
        return aW, 1

    def draw(self):
        c = self.canv
        x0, y0 = c.absolutePosition(0, 0)
        c.saveState()
        c.translate(-x0, -y0)
        c._dpb_bare = True
        w, h = c._pagesize
        self._strip(c, w, h)
        self._field(c, h)
        c.restoreState()

    def _strip(self, c, w, h):
        plan, theme = self.plan, self.theme
        x = w - plan.strip if plan.rtl else 0
        dark = A.ink(theme)
        chapters = plan.chapters
        if not chapters:
            c.setFillColor(HexColor(dark))
            c.rect(x, 0, plan.strip, h, fill=1, stroke=0)
            return
        n, base = len(chapters), theme.typography.base_size
        band = h / n
        sp = theme.spacing
        tx = x + 14 if plan.rtl else sp.page_margin_left
        tw = plan.strip - 14 - (sp.page_margin_right if plan.rtl else sp.page_margin_left)
        align = 2 if plan.rtl else 0
        for i, name in enumerate(chapters):
            current = i == self.block.current
            top = h - i * band
            c.setFillColor(HexColor(dark if current else A.tint(theme, 0.9)))
            c.rect(x, top - band + 0.75, plan.strip, band - 1.5, fill=1, stroke=0)
            fg = "#ffffff" if current else dark
            number = f"{i + 1:02d}"
            if plan.rtl:
                number = A.arabic_digits(number)
            y = top - 18
            y -= _place(c, _text(theme, number, base * 0.9, fg, align, True), tx, y, tw) + 3
            _place(c, _text(theme, name, base * 0.88, fg, align, current, 1.25), tx, y, tw)

    def _field(self, c, h):
        plan, theme = self.plan, self.theme
        colors = _colors(theme)
        y = h * (1 - plan.top)
        for p in plan.parts:
            y -= p.before
            if p.role == "rule":
                c.setStrokeColor(HexColor(theme.colors.border))
                c.setLineWidth(0.75)
                c.line(plan.field_x, y, plan.field_x + plan.field_w, y)
                y -= 1
                continue
            right = plan.rtl != p.far_edge
            para = _text(theme, p.text, p.size, colors[p.color], 2 if right else 0, p.bold, p.ratio,
                         heading=p.role in ("label", "title", "title_alt"))
            y -= _place(c, para, plan.field_x, y, plan.field_w)


def _opener(block, theme, ctx) -> list:
    number = ctx.next_heading_number(1) if ctx.section_numbering else None
    w, h = ctx.page_size
    plan = A.plan_opener(block, theme, w, h, number if not block.label else None)
    for note in plan.notes:
        _diag.current().warn("archetype_fit", f"Section opener: {note}")
    if not plan.ok:
        return _fallback(block, theme, ctx, plan, restore_number=bool(number))
    ctx.toc_entries.append((1, block.title))
    title = f"{number}  {block.title}" if number else block.title
    out: list = _new_page(ctx) + [SectionOpener(block, theme, plan, (1, _strip_markdown(title), block.id))]
    if plan.spill or not ctx.last_block:
        out.append(PageBreak())
    for b in plan.spill:
        out += create_flowables(b, theme, ctx)
    return out


# ═════════════════════════ Performance page ═════════════════════════

class PerformancePage(Flowable):
    def __init__(self, block, theme, plan: A.PerformancePlan, toc_entry):
        super().__init__()
        self.block, self.theme, self.plan = block, theme, plan
        self._toc_entry = toc_entry
        self.width = self.height = 0.0

    def wrap(self, aW, aH):
        total, gaps = A._strata_height(self.block, self.plan, self.theme, aW)
        self.width, self.height = aW, total + gaps * self.plan.gap
        return aW, self.height

    def _x(self, x: float, w: float) -> float:
        """Mirror a box measured from the reading start."""
        return self.width - x - w if self.plan.rtl else x

    def draw(self):
        c, b, plan, theme = self.canv, self.block, self.plan, self.theme
        W, base = self.width, theme.typography.base_size
        dark, text, muted = A.ink(theme), theme.colors.text_primary, theme.colors.text_secondary
        align = 2 if plan.rtl else 0
        y = self.height
        if b.eyebrow:
            y -= _place(c, _text(theme, b.eyebrow, base * 0.9, dark, align, True), 0, y, W) + 4
        y -= _place(c, _text(theme, b.title, base * 2.4, text, align, True, 1.15), 0, y, W)
        if b.standfirst:
            y -= 8
            y -= _place(c, _text(theme, b.standfirst, base * 1.15, muted, align, False, 1.4, False), 0, y, W)
        y -= plan.gap
        y = self._hero(c, y, W, dark, text, muted, align, base)
        if b.tiles:
            y -= plan.gap
            y = self._tiles(c, y, W, dark, text, muted, align, base)
        if b.trends:
            y -= plan.gap
            y = self._trends(c, y, W, dark, text, muted, align, base)
        if plan.highlights:
            y -= plan.gap
            self._highlights(c, y, W, text, align)

    def _hero(self, c, y, W, dark, text, muted, align, base):
        b, plan, theme = self.block, self.plan, self.theme
        hero, side = b.hero, W * 0.36
        band = A.hero_band(b, plan.hero_size, theme, side)
        para = _text(theme, hero.value, plan.hero_size, dark, align, True, 1.08)
        _place(c, para, self._x(0, W - side - 12), y, W - side - 12)
        sy = y - (band - 8 - A.hero_side_height(b, theme, side))        # hangs from the band's foot
        sx = self._x(W - side, side)
        sy -= _place(c, _text(theme, hero.label, base * 1.15, text, align, True), sx, sy, side)
        if hero.delta:
            sy -= 3
            sy -= _place(c, _text(theme, hero.delta, base * 0.95, dark, align, True), sx, sy, side)
        if hero.note:
            sy -= 3
            _place(c, _text(theme, hero.note, base * 0.9, muted, align, False, 1.35, False), sx, sy, side)
        return y - band

    def _tiles(self, c, y, W, dark, text, muted, align, base):
        b, plan, theme = self.block, self.plan, self.theme
        cols, gap = plan.tile_cols, 16
        cw = (W - gap * (cols - 1)) / cols
        for r in range(plan.tile_rows):
            row = b.tiles[r * cols:(r + 1) * cols]
            c.setStrokeColor(HexColor(dark))
            c.setLineWidth(2)
            c.line(0, y, W, y)
            top = y - 10
            tallest = 0.0
            for i, t in enumerate(row):
                x = self._x(i * (cw + gap), cw)
                ty = top
                ty -= _place(c, _text(theme, t.value, base * 2.0, text, align, True, 1.15), x, ty, cw)
                ty -= 2
                ty -= _place(c, _text(theme, t.label, base * 0.88, muted, align, False, 1.3, False), x, ty, cw)
                if t.delta:
                    ty -= 2
                    _place(c, _text(theme, t.delta, base * 0.82, dark, align, True), x, ty, cw)
                tallest = max(tallest, A.tile_height(t, theme, cw))
            y = top - tallest - 2
        return y

    def _trends(self, c, y, W, dark, text, muted, align, base):
        b, theme = self.block, self.theme
        n, gap = len(b.trends), 18
        tw = (W - gap * (n - 1)) / n
        row_h = A.trend_row(theme)
        size = base * 0.88
        tallest = 0.0
        prior = A.tint(theme, 0.62)
        for i, s in enumerate(b.trends):
            x = self._x(i * (tw + gap), tw)
            ty = y
            ty -= _place(c, _text(theme, s.label, base * 0.95, text, align, True), x, ty, tw) + 6
            zero, scale = A.trend_span(s.values)
            for k, period in enumerate(s.periods):
                current = k == len(s.periods) - 1
                fg = text if current else muted
                _place(c, _text(theme, period, size, fg, align, current, 1.3, False), x, ty, tw)
                _place(c, _text(theme, A.trend_text(s, k), size, fg, 0 if align else 2, current), x, ty, tw)
                by = ty - size * 1.3 - 6
                c.setFillColor(HexColor(dark if current else prior))
                self._bar(c, x, by, tw, zero, s.values[k] * scale)
                ty -= row_h
            tallest = max(tallest, A.trend_height(s, theme, tw))
        return y - tallest

    def _bar(self, c, x, y, width, zero, value):
        """A 5 pt bar on a 0..1 axis from the reading edge; zero is shared by the series."""
        start, end = sorted((zero, zero + value))
        if self.plan.rtl:
            start, end = 1 - end, 1 - start
        c.rect(x + start * width, y, max(0.75, (end - start) * width), 5, fill=1, stroke=0)

    def _highlights(self, c, y, W, text, align):
        plan, theme = self.plan, self.theme
        base = theme.typography.base_size
        items, cols = plan.highlights, plan.highlight_cols
        h = A.highlights_height(items, cols, theme, W)
        c.setFillColor(HexColor(A.tint(theme, 0.93)))
        c.rect(0, y - h, W, h, fill=1, stroke=0)
        cw = (W - 24 - 14 * (cols - 1)) / cols
        per = -(-len(items) // cols)
        for col in range(cols):
            x = self._x(12 + col * (cw + 14), cw)
            ty = y - 10
            for t in items[col * per:(col + 1) * per]:
                c.setFillColor(HexColor(A.ink(theme)))
                c.rect(x + cw - 4 if align else x, ty - base * 0.95, 4, 4, fill=1, stroke=0)
                para = _text(theme, t, base, text, align, False, 1.35, False)
                ty -= _place(c, para, x if align else x + 12, ty, cw - 12) + 5


def _performance(block, theme, ctx) -> list:
    plan = A.plan_performance(block, theme, ctx.usable_width, ctx.usable_height or 640.0)
    for note in plan.notes:
        _diag.current().warn("archetype_fit", f"Performance page: {note}")
    if not plan.ok:
        return _fallback(block, theme, ctx, plan)
    ctx.toc_entries.append((1, block.title))
    title = block.title
    if ctx.section_numbering:
        title = f"{ctx.next_heading_number(1)}  {title}"
    out: list = _new_page(ctx) + [PerformancePage(block, theme, plan, (1, _strip_markdown(title), block.id))]
    if plan.spill:
        for b in plan.spill:
            out += create_flowables(b, theme, ctx)
    elif not ctx.last_block:
        out.append(PageBreak())
    return out


# ═════════════════════════ Parallel ledger ═════════════════════════

def _ledger(block, theme, ctx) -> list:
    width = ctx.available_width
    plan = A.plan_ledger(block, theme, width)
    for note in plan.notes:
        _diag.current().warn("archetype_fit", f"Parallel ledger: {note}")
    if not plan.ok:
        return _fallback(block, theme, ctx, plan)
    base = theme.typography.base_size
    n = len(block.periods)
    dark, text, muted = A.ink(theme), theme.colors.text_primary, theme.colors.text_secondary
    order: List[int] = list(range(n))
    if plan.rtl:
        order.reverse()
    first = 1 if (plan.bilingual or not plan.rtl) else 0      # the first value column
    ncols = n + (2 if plan.bilingual else 1)
    last_label = ncols - 1 if (plan.bilingual or plan.rtl) else None
    emph = first + order.index(block.emphasis)
    widths = [0.0] * ncols
    for vis, i in enumerate(order):
        widths[first + vis] = plan.value_w[i] * width
    if first:
        widths[0] = plan.label_w * width
    if last_label is not None:
        widths[last_label] = plan.label_w * width

    def label_cell(t, right, bold=False, color=text, size=base):
        return _text(theme, t or "", size, color, 2 if right else 0, bold, 1.3, False) if t else ""

    def value_cell(v, col, bold=False, color=None):
        on = col == emph
        return _text(theme, v, plan.emphasis_size if on else base, color or (text if on else muted), 2,
                     bold or on, 1.25, False)

    def row(left, right, values, bold=False, head=False):
        cells: list = [""] * ncols
        if first:
            cells[0] = left
        if last_label is not None:
            cells[last_label] = right
        for vis, i in enumerate(order):
            cells[first + vis] = values[i]
        return cells

    head_size = base * 0.9
    hdr = row(label_cell(block.label_header, False, True, muted, head_size),
              label_cell(block.label_header_alt if plan.bilingual else block.label_header, True, True, muted, head_size)
              if last_label is not None else "",
              [_text(theme, p, head_size, dark if i == block.emphasis else muted, 2, True) for i, p in enumerate(block.periods)])
    if plan.rtl:
        hdr[last_label] = label_cell(block.label_header, True, True, muted, head_size)
    top = 1 if block.title_first and len(block.sections) == 1 else 0     # where the column heads sit
    data = [] if top else [hdr]
    style = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5),
        ("LINEBELOW", (0, top), (-1, top), 0.75, HexColor(dark)),
        ("BACKGROUND", (emph, 0), (emph, -1), HexColor(A.tint(theme, 0.92))),
    ]
    split = (ncols - 1) // 2
    for s in block.sections:
        r = len(data)
        right = plan.rtl
        bar: list = [""] * ncols
        title = _text(theme, s.title, base * 1.02, "#ffffff", 2 if right else 0, True)
        if plan.bilingual:
            bar[0] = title
            bar[split + 1] = _text(theme, s.title_alt or "", base * 1.02, "#ffffff", 2, True) if s.title_alt else ""
            style += [("SPAN", (0, r), (split, r)), ("SPAN", (split + 1, r), (-1, r))]
        else:
            bar[0] = title
            style.append(("SPAN", (0, r), (-1, r)))
        style += [("BACKGROUND", (0, r), (-1, r), HexColor(dark)),
                  ("NOSPLIT", (0, r), (-1, min(r + 2, r + len(s.rows))))]
        data.append(bar)
        if top:
            data.append(hdr)
        for row_data in s.rows:
            r = len(data)
            b = row_data.total
            values = [value_cell(v, first + order.index(i), b, text if b else None)
                      for i, v in enumerate(row_data.values)]
            if plan.bilingual:
                left, end = label_cell(row_data.label, False, b), label_cell(row_data.label_alt, True, b)
            elif plan.rtl:
                left, end = "", label_cell(row_data.label, True, b)
            else:
                left, end = label_cell(row_data.label, False, b), ""
            data.append(row(left, end, values))
            style.append(("LINEBELOW", (0, r), (-1, r), 0.35, HexColor(theme.colors.border)))
            if b:
                style += [("LINEABOVE", (0, r), (-1, r), 0.9, HexColor(dark)),
                          ("NOSPLIT", (0, r - 1), (-1, r))]      # a total never stands alone on a page
        if s.note:
            r = len(data)
            note = [""] * ncols
            note[0] = _text(theme, s.note, base * 0.82, muted, 2 if A.is_rtl(s.note) else 0, False, 1.3, False)
            style += [("SPAN", (0, r), (-1, r)), ("BACKGROUND", (0, r), (-1, r), HexColor(theme.colors.background))]
            data.append(note)
    table = Table(data, colWidths=widths, repeatRows=1 + top, splitByRow=1, hAlign="LEFT")
    table.setStyle(TableStyle(style))
    return [table, Spacer(1, theme.spacing.block_gap)]


# ═════════════════════════ Entry ═════════════════════════

def _fallback(block, theme, ctx, plan, restore_number: bool = False) -> list:
    _diag.current().warn("archetype_fallback",
                         f"{block.type} rendered as plain blocks: {'; '.join(plan.notes) or 'content does not fit'}")
    if restore_number:
        ctx.heading_counters[0] -= 1
    out: list = []
    for b in A.lower(block):
        out += create_flowables(b, theme, ctx)
    return out


def render_archetype(block, theme, ctx) -> Optional[list]:
    return {"section_opener": _opener, "performance_page": _performance,
            "parallel_ledger": _ledger}[block.type](block, theme, ctx)
