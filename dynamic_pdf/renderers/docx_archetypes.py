"""
Editable DOCX forms of the layout archetypes. The fit decisions are the PDF's
(design/archetypes.py), so one content spec gives the same composition in both.

Everything stays native: titles are real Heading 1 paragraphs outside any table,
so they reach the navigation pane and the TOC; the opener strip is a stack of
page-anchored text boxes whose text can be edited; bars are shaded paragraphs,
not pictures.
"""
from __future__ import annotations

import re

from docx.enum.section import WD_SECTION
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_LINE_SPACING, WD_TAB_ALIGNMENT
from docx.shared import Pt
from docx.oxml import OxmlElement
from docx.table import _Cell
from docx.text.paragraph import Paragraph

from ..core.inline import plain_text
from ..design import archetypes as A
from . import docx_fields as F


ARABIC = re.compile("[\u0600-\u06ff]")
ARABIC_ROOM = 0.85                 # Amiri's natural lines are taller than the PDF's planned leading


class _TextBox:
    """Just enough of a container for ``_para``: the body of a text box."""

    def __init__(self, content, parent):
        self.content, self.parent = content, parent

    def add_paragraph(self, text="", style=None):
        p = OxmlElement("w:p")
        self.content.append(p)
        para = Paragraph(p, self.parent)
        if style:
            para.style = style
        return para


class ArchetypeDocx:
    """Mixed into ``DocxRenderer``; uses its ``_para``, ``_runs`` and ``_block_safe``."""

    # ─── shared helpers ───

    def _fit_notes(self, name: str, plan) -> None:
        for note in plan.notes:
            self.col.warn("archetype_fit", f"{name}: {note}")

    def _plain(self, c, b, plan) -> None:
        self.col.warn("archetype_fallback", f"{b.type} rendered as plain blocks: "
                                            f"{'; '.join(plan.notes) or 'content does not fit'}")
        for child in A.lower(b):
            self._block_safe(c, child)

    def _last_block(self) -> bool:
        return self.col.block_index == len(self.sem.blocks) - 1

    def _line(self, c, text: str, size: float, color: str, *, right: bool, bold=None, ratio=1.3,
              before=0.0, after=0.0, style="Normal"):
        """One text group with the exact size and line height of the PDF."""
        p = self._para(c, style, text)
        pf = p.paragraph_format
        pf.space_before, pf.space_after = Pt(before), Pt(after)
        pf.first_line_indent = None
        pf.line_spacing = Pt(size * A.leading(text, ratio))
        if ARABIC.search(text):                  # exact height would clip Amiri's marks in Word
            pf.line_spacing_rule = WD_LINE_SPACING.AT_LEAST
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT if right else WD_ALIGN_PARAGRAPH.LEFT
        self._runs(p, text, bold=bold, size=size, color=color)
        return p

    def _title(self, p, b, text: str) -> None:
        if b.id:
            F.add_bookmark(p, F.bookmark_name(b.id), self.bm)
        self.headings_rendered.append(plain_text(text))

    def _next_h1(self):
        if not self.sem.meta.section_numbering:
            return None
        self.heading_counters[0] += 1
        for i in range(1, 6):
            self.heading_counters[i] = 0
        return str(self.heading_counters[0])

    def _gap(self, c, height: float) -> None:
        p = c.add_paragraph()
        p.paragraph_format.space_before = p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.line_spacing = Pt(max(1.0, height))

    def _fresh_page(self) -> bool:
        kids = [k for k in self.doc.element.body if k.tag != F.qn("w:sectPr")]
        if not kids:
            return True
        last = kids[-1]
        return last.tag == F.qn("w:p") and bool(last.xpath(".//w:br[@w:type='page']"))

    def _page_section(self):
        """A section starting on a new page, with nothing left behind on the page before."""
        body = self.doc.element.body
        if not [k for k in body if k.tag != F.qn("w:sectPr")]:
            return self.doc.sections[0]
        sec = self.doc.add_section(WD_SECTION.NEW_PAGE)
        marker = body.xpath("./w:p[last()]")[-1]      # python-docx parks the break in an empty paragraph
        before = marker.getprevious()
        if (before is not None and before.tag == F.qn("w:p")
                and not before.xpath("./w:pPr/w:sectPr")):
            for br in before.xpath(".//w:br[@w:type='page']"):
                run = br.getparent()
                run.getparent().remove(run)           # the section break is the page break now
            before.get_or_add_pPr().append(marker.pPr.find(F.qn("w:sectPr")))
            body.remove(marker)
        return sec

    # ─── section opener ───

    def _b_section_opener(self, c, b):
        if isinstance(c, _Cell):
            return self._plain(c, b, A.OpenerPlan(False, notes=["not available inside a column"]))
        now = self.doc.sections[-1]
        number = self._next_h1()
        pw, ph = now.page_width.pt, now.page_height.pt
        plan = A.plan_opener(b, self.theme, pw, ph, number if not b.label else None)
        self._fit_notes("Section opener", plan)
        if not plan.ok:
            if number:
                self.heading_counters[0] -= 1
            return self._plain(c, b, plan)
        keep = {a: getattr(now, a) for a in ("top_margin", "bottom_margin", "left_margin", "right_margin")}
        width = self.content_width_pt
        sec = self._page_section()
        sec.top_margin = Pt(ph * plan.top)
        sec.bottom_margin = keep["bottom_margin"]
        sec.left_margin = Pt(plan.field_x)
        sec.right_margin = Pt(pw - plan.field_x - plan.field_w)
        sec.different_first_page_header_footer = True  # one page long: no header, no footer
        sec.first_page_header.is_linked_to_previous = False
        sec.first_page_footer.is_linked_to_previous = False
        self.content_width_pt = plan.field_w
        colors = {"ink": A.ink(self.theme), "text": self.theme.colors.text_primary,
                  "muted": self.theme.colors.text_secondary}
        host = None
        for i, part in enumerate(plan.parts):
            if part.role == "rule":
                p = c.add_paragraph()
                p.paragraph_format.space_before, p.paragraph_format.space_after = Pt(part.before), Pt(0)
                p.paragraph_format.line_spacing = Pt(1)
                F.set_paragraph_border(p, "bottom", self.theme.colors.border, 6, 0)
                continue
            title = part.role == "title"
            p = self._line(c, part.text, part.size, colors[part.color], right=plan.rtl != part.far_edge,
                           bold=part.bold or None, ratio=part.ratio, before=0 if i == 0 else part.before,
                           style="Heading 1" if title else "Normal")
            host = host if host is not None else p
            if title:
                self._title(p, b, f"{number}  {b.title}" if number else b.title)
        self._strip(host, b, plan, pw, ph)
        self.content_width_pt = width
        if plan.spill or not self._last_block():
            nxt = self._page_section()
            for attr, value in keep.items():
                setattr(nxt, attr, value)
            nxt.different_first_page_header_footer = False
        for child in plan.spill:
            self._block_safe(c, child)

    def _strip(self, host, b, plan, pw: float, ph: float) -> None:
        """One text box per chapter, from the top of the page to the bottom. A floating
        table cannot do this: renderers stop it at the bottom margin."""
        theme, sp = self.theme, self.theme.spacing
        chapters = plan.chapters or [""]
        n = len(chapters)
        x = pw - plan.strip if plan.rtl else 0.0
        margin = sp.page_margin_right if plan.rtl else sp.page_margin_left
        insets = (14.0, 16.0, margin, 0) if plan.rtl else (margin, 16.0, 14.0, 0)
        dark = A.ink(theme)
        base = theme.typography.base_size
        for i, name in enumerate(chapters):
            current = i == b.current or not plan.chapters
            height = ph / n - (0 if i == n - 1 else 1)
            content = F.add_page_text_box(host, self.doc.part.next_id, x, i * ph / n, plan.strip, height,
                                          dark if current else A.tint(theme, 0.9), insets,
                                          f"Chapter band: {name}" if name else "Chapter band")
            box = _TextBox(content, self.doc._body)
            fg = "#ffffff" if current else dark
            if not name:
                box.add_paragraph()              # a text box must hold a paragraph
                continue
            number = f"{i + 1:02d}"
            if plan.rtl:
                number = A.arabic_digits(number)
            self._line(box, number, base * 0.9, fg, right=plan.rtl, bold=True, after=3)
            self._line(box, name, base * 0.88, fg, right=plan.rtl, bold=current or None, ratio=1.25)

    # ─── performance page ───

    def _b_performance_page(self, c, b):
        if isinstance(c, _Cell):
            return self._plain(c, b, A.PerformancePlan(False, notes=["not available inside a column"]))
        sec = self.doc.sections[-1]
        width = self.content_width_pt
        height = sec.page_height.pt - sec.top_margin.pt - sec.bottom_margin.pt
        if A.is_rtl(b.title):
            height *= ARABIC_ROOM
        plan = A.plan_performance(b, self.theme, width, height)
        self._fit_notes("Performance page", plan)
        if not plan.ok:
            return self._plain(c, b, plan)
        theme, rtl = self.theme, plan.rtl
        base = theme.typography.base_size
        dark, text, muted = A.ink(theme), theme.colors.text_primary, theme.colors.text_secondary
        number = self._next_h1()
        fresh = self._fresh_page()
        p = None
        if b.eyebrow:
            p = self._line(c, b.eyebrow, base * 0.9, dark, right=rtl, bold=True, after=4)
            p.paragraph_format.page_break_before = not fresh
        h = self._line(c, b.title, base * 2.4, text, right=rtl, bold=True, ratio=1.15, style="Heading 1")
        if p is None:
            h.paragraph_format.page_break_before = not fresh
        self._title(h, b, f"{number}  {b.title}" if number else b.title)
        if b.standfirst:
            self._line(c, b.standfirst, base * 1.15, muted, right=rtl, ratio=1.4, before=8)
        self._gap(c, plan.gap)
        self._hero(c, b, plan, width, dark, text, muted)
        if b.tiles:
            self._gap(c, plan.gap)
            self._tiles(c, b, plan, width, dark, text, muted)
        if b.trends:
            self._gap(c, plan.gap)
            self._trends(c, b, plan, width, dark, text, muted)
        if plan.highlights:
            self._gap(c, plan.gap)
            self._highlights(c, plan, width)
        for child in plan.spill:
            self._block_safe(c, child)
        if not plan.spill and not self._last_block():
            p = c.add_paragraph()
            p.paragraph_format.space_before = p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.line_spacing = Pt(1)
            p.add_run().add_break(WD_BREAK.PAGE)

    def _grid(self, c, widths, rtl: bool, rows: int = 1):
        t = c.add_table(rows=rows, cols=len(widths))
        F.set_table_width_pct(t, 100)
        F.set_table_borders(t, size=0)
        F.set_table_layout_fixed(t)
        F.set_table_cell_margins(t, 0, 0, 0, 0)
        if rtl:
            F.set_table_bidi(t)
        for ci, w in enumerate(widths):
            t.columns[ci].width = Pt(w)
            for row in t.rows:
                row.cells[ci].width = Pt(w)
        for row in t.rows:
            F.set_cant_split(row)
        return t

    def _hero(self, c, b, plan, width, dark, text, muted):
        theme, hero, rtl = self.theme, b.hero, plan.rtl
        base = theme.typography.base_size
        side = width * 0.36
        t = self._grid(c, [width - side, side], rtl)
        big, small = t.rows[0].cells
        big.vertical_alignment = small.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.BOTTOM
        self._line(big, hero.value, plan.hero_size, dark, right=rtl, bold=True, ratio=1.08)
        self._line(small, hero.label, base * 1.15, text, right=rtl, bold=True)
        if hero.delta:
            self._line(small, hero.delta, base * 0.95, dark, right=rtl, bold=True, before=3)
        if hero.note:
            self._line(small, hero.note, base * 0.9, muted, right=rtl, ratio=1.35, before=3)

    def _tiles(self, c, b, plan, width, dark, text, muted):
        theme, rtl, cols, gap = self.theme, plan.rtl, plan.tile_cols, 16.0
        base = theme.typography.base_size
        tw = (width - gap * (cols - 1)) / cols
        widths = [w for i in range(cols) for w in ((tw, gap) if i < cols - 1 else (tw,))]
        t = self._grid(c, widths, rtl, plan.tile_rows)
        for r in range(plan.tile_rows):
            cells = t.rows[r].cells
            for cell in cells:
                F.set_cell_borders(cell, top=("single", 16, dark))
                F.set_cell_margins(cell, top=160, bottom=120)
            for i in range(cols):
                k = r * cols + i
                if k >= len(b.tiles):
                    continue
                tile, cell = b.tiles[k], cells[i * 2]
                self._line(cell, tile.value, base * 2.0, text, right=rtl, bold=True, ratio=1.15)
                self._line(cell, tile.label, base * 0.88, muted, right=rtl, before=2)
                if tile.delta:
                    self._line(cell, tile.delta, base * 0.82, dark, right=rtl, bold=True, before=2)

    def _trends(self, c, b, plan, width, dark, text, muted):
        theme, rtl = self.theme, plan.rtl
        base = theme.typography.base_size
        n, gap = len(b.trends), 18.0
        tw = (width - gap * (n - 1)) / n
        widths = [w for i in range(n) for w in ((tw, gap) if i < n - 1 else (tw,))]
        t = self._grid(c, widths, rtl)
        cells = t.rows[0].cells
        size = base * 0.88
        prior = A.tint(theme, 0.62)
        for i, s in enumerate(b.trends):
            cell = cells[i * 2]
            self._line(cell, s.label, base * 0.95, text, right=rtl, bold=True, after=6)
            zero, scale = A.trend_span(s.values)
            for k, period in enumerate(s.periods):
                current = k == len(s.periods) - 1
                fg = text if current else muted
                p = self._line(cell, period, size, fg, right=rtl, bold=current or None)
                p.paragraph_format.tab_stops.add_tab_stop(Pt(tw), WD_TAB_ALIGNMENT.RIGHT)
                self._runs(p, "\t" + A.trend_text(s, k), bold=current or None, size=size, color=fg)
                self._bar(cell, tw, zero, s.values[k] * scale, dark if current else prior, rtl)

    def _bar(self, cell, width, zero, value, color, rtl):
        """A shaded paragraph between two indents: a bar that stays native and editable."""
        start, end = sorted((zero, zero + value))
        if rtl:
            start, end = 1 - end, 1 - start
        end = max(end, start + 0.75 / width)
        p = cell.add_paragraph()
        pf = p.paragraph_format
        pf.space_before, pf.space_after = Pt(1), Pt(3)
        pf.line_spacing = Pt(5)
        pf.left_indent, pf.right_indent = Pt(start * width), Pt((1 - end) * width)
        pf.first_line_indent = None
        F.set_paragraph_shading(p, color)

    def _highlights(self, c, plan, width):
        rtl, cols = plan.rtl, plan.highlight_cols
        t = self._grid(c, [width / cols] * cols, rtl)
        per = -(-len(plan.highlights) // cols)
        cells = t.rows[0].cells
        for i in range(cols):
            F.set_cell_shading(cells[i], A.tint(self.theme, 0.93))
            F.set_cell_margins(cells[i], 160, 120, 200, 200)
            self._list_items(cells[i], plan.highlights[i * per:(i + 1) * per], ordered=False)

    # ─── parallel ledger ───

    def _b_parallel_ledger(self, c, b):
        width = self.content_width_pt
        plan = A.plan_ledger(b, self.theme, width)
        self._fit_notes("Parallel ledger", plan)
        if not plan.ok:
            return self._plain(c, b, plan)
        theme, base = self.theme, self.theme.typography.base_size
        dark, text, muted = A.ink(theme), theme.colors.text_primary, theme.colors.text_secondary
        border, n = theme.colors.border, len(b.periods)
        second = 1 if plan.bilingual else 0
        ncols = 1 + n + second
        emph = 1 + b.emphasis
        count = 1 + sum(1 + len(s.rows) + (1 if s.note else 0) for s in b.sections)
        t = c.add_table(rows=count, cols=ncols)
        F.set_table_width_pct(t, 100)
        F.set_table_borders(t, size=0)
        F.set_table_layout_fixed(t)
        F.set_table_cell_margins(t, 60, 60, 120, 120)
        if plan.rtl:
            F.set_table_bidi(t)                  # logical order reads from the right edge
        widths = [plan.label_w * width] + [w * width for w in plan.value_w]
        if second:
            widths.append(plan.label_w * width)
        for ci, w in enumerate(widths):
            t.columns[ci].width = Pt(w)
            for row in t.rows:
                row.cells[ci].width = Pt(w)
        split = (ncols - 1) // 2

        def values(cells, row, bold):
            for i, v in enumerate(row.values):
                on = i == b.emphasis
                size = plan.emphasis_size if on else base
                self._line(cells[1 + i], v, size, text if on or bold else muted, right=True,
                           bold=True if on or bold else None, ratio=1.25)

        r = 0
        head = t.rows[0]
        F.set_repeat_table_header(head)
        F.set_cant_split(head)
        cells = head.cells
        size = base * 0.9
        if b.label_header:
            self._line(cells[0], b.label_header, size, muted, right=plan.rtl, bold=True)
        if second and b.label_header_alt:
            self._line(cells[-1], b.label_header_alt, size, muted, right=True, bold=True)
        for i, period in enumerate(b.periods):
            self._line(cells[1 + i], period, size, dark if i == b.emphasis else muted, right=True, bold=True)
        for cell in cells:
            F.set_cell_borders(cell, bottom=("single", 6, dark))
        F.set_cell_shading(cells[emph], A.tint(theme, 0.92))
        for s in b.sections:
            r += 1
            row = t.rows[r]
            F.set_cant_split(row)
            if second:
                left = t.cell(r, 0).merge(t.cell(r, split))
                right = t.cell(r, split + 1).merge(t.cell(r, ncols - 1))
                F.set_cell_shading(left, dark)
                F.set_cell_shading(right, dark)
                self._line(left, s.title, base * 1.02, "#ffffff", right=False, bold=True).paragraph_format.keep_with_next = True
                if s.title_alt:
                    self._line(right, s.title_alt, base * 1.02, "#ffffff", right=True, bold=True).paragraph_format.keep_with_next = True
            else:
                bar = t.cell(r, 0).merge(t.cell(r, ncols - 1))
                F.set_cell_shading(bar, dark)
                self._line(bar, s.title, base * 1.02, "#ffffff", right=plan.rtl, bold=True).paragraph_format.keep_with_next = True
            for k, data in enumerate(s.rows):
                r += 1
                row = t.rows[r]
                F.set_cant_split(row)
                cells = row.cells
                bold = data.total or None
                p = self._line(cells[0], data.label, base, text, right=plan.rtl, bold=bold)
                if k == 0:
                    p.paragraph_format.keep_with_next = True   # a section bar keeps two rows with it
                if second and data.label_alt:
                    self._line(cells[-1], data.label_alt, base, text, right=True, bold=bold)
                values(cells, data, data.total)
                F.set_cell_shading(cells[emph], A.tint(theme, 0.92))
                for cell in cells:
                    sides = {"bottom": ("single", 3, border)}
                    if data.total:
                        sides["top"] = ("single", 7, dark)
                    F.set_cell_borders(cell, **sides)
            if s.note:
                r += 1
                F.set_cant_split(t.rows[r])
                note = t.cell(r, 0).merge(t.cell(r, ncols - 1))
                self._line(note, s.note, base * 0.82, muted, right=A.is_rtl(s.note))
        self._spacer_after(c)
