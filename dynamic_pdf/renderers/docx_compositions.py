"""
Editable DOCX forms of the composition blocks. Sizes come from design/archetypes.py, so one
spec gives the same composition in PDF and Word. Text stays live in table cells, and pictures
are native drawings.
"""
from __future__ import annotations

from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt

from ..design import archetypes as A
from ..media import fit_image, ingest
from . import docx_fields as F
from . import docx_media as M


def _row_height(row, height: float, exact: bool = False) -> None:
    props = row._tr.get_or_add_trPr()
    h = OxmlElement("w:trHeight")
    h.set(qn("w:val"), str(round(height * 20)))
    h.set(qn("w:hRule"), "exact" if exact else "atLeast")
    props.append(h)


class CompositionDocx:
    """Mixed into ``DocxRenderer``."""

    def _panel_text(self, cell, b, plan):
        base = self.theme.typography.base_size
        first = True

        def line(text, size, bold, ratio, after):
            nonlocal first
            p = self._line(cell, text, size, plan.ink, right=A.align(text) == 2, bold=bold, ratio=ratio, after=after)
            # indents, not cell margins: Word moves a table out by its first cell's margin
            p.paragraph_format.left_indent = p.paragraph_format.right_indent = Pt(plan.pad)
            if first:                              # the cell's empty first paragraph is not a line of text
                empty = cell.paragraphs[0]
                if not empty.text and empty._p is not p._p:
                    empty._p.getparent().remove(empty._p)
                first = False

        if b.eyebrow:
            line(b.eyebrow, base * 0.8, True, 1.3, 5)
        if b.title:
            line(b.title, base * 1.7, True, 1.2, 7)
        for text in b.paragraphs:
            line(text, A.panel_body(b, base), None, 1.45, 6)

    def _b_image_text_panel(self, c, b):
        width = self.content_width_pt
        plan = A.plan_panel(b, self.theme, width)
        plan.settle(A.estimate_panel_text(b, self.theme, plan.text_w))
        asset = ingest(b.image.src, self.col.policy.assets)
        t = A.panel_treatment(b)
        alt = b.image.alt_text or b.image.caption or "image"
        f = fit_image(asset, plan.image_w, plan.height, t)
        if plan.overlay:
            holder = M.tiny_paragraph(c)
            holder.paragraph_format.keep_with_next = True
            anchor = M.Anchor(h_from="column", v_from="paragraph", x=0, y=1, behind=True, wrap="none")
            M.add_drawing(holder.add_run(), asset, f, t, alt, self.next_shape(), anchor)
            inset = plan.panel_y
            widths = ([inset, plan.panel_w, width - inset - plan.panel_w] if plan.panel_x < width / 2
                      else [width - inset - plan.panel_w, plan.panel_w, inset])
            table = self._grid(c, widths, False, rows=3)
            for r, (row, height) in enumerate(zip(table.rows, (inset, plan.panel_h, inset))):
                _row_height(row, height, exact=height == inset)
                F.set_cant_split(row)
                for each in row.cells:
                    M.squeeze(each.paragraphs[0])
                    # the panel's rows stay on one page with the photo anchored over them
                    if r < 2:
                        each.paragraphs[0].paragraph_format.keep_with_next = True
            cell = table.rows[1].cells[1]
        else:
            image_first = plan.image_x == 0
            widths = [plan.image_w, plan.panel_w] if image_first else [plan.panel_w, plan.image_w]
            table = self._grid(c, widths, False)
            _row_height(table.rows[0], plan.height)
            pic, cell = (table.rows[0].cells[0], table.rows[0].cells[1]) if image_first else (
                table.rows[0].cells[1], table.rows[0].cells[0])
            para = pic.paragraphs[0]
            para.paragraph_format.space_before = para.paragraph_format.space_after = Pt(0)
            para.paragraph_format.line_spacing = 1.0    # an exact line would crop the picture
            para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = para.add_run()
            run.font.size = Pt(1)
            M.add_drawing(run, asset, f, t, alt, self.next_shape())
        F.set_cell_shading(cell, plan.fill)
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        self._panel_text(cell, b, plan)
        for text in filter(None, (b.image.caption, b.image.source)):
            self._line(c, text, self.theme.typography.base_size * 0.78, self.theme.colors.text_secondary,
                       right=A.align(text) == 2, before=3)
        self._spacer_after(c)

    def _b_figure_matrix(self, c, b):
        from .chart import chart_png
        base = self.theme.typography.base_size
        width = self.content_width_pt
        plan = A.plan_matrix(b, width)
        ink, muted = A.ink(self.theme), self.theme.colors.text_secondary
        if b.title:
            self._line(c, b.title, base * 1.3, ink, right=A.align(b.title) == 2, bold=True, ratio=1.25, after=6).paragraph_format.keep_with_next = True
        table = self._grid(c, [width / plan.columns] * plan.columns, False, rows=len(plan.rows))
        F.set_table_cell_margins(table, 140, 160, round(plan.gap * 10), round(plan.gap * 10))
        for r, row in enumerate(plan.rows):
            for i, cell in enumerate(row):
                target = table.rows[r].cells[i]
                F.set_cell_borders(target, top=("single", 5, self.theme.colors.border))
                if not cell:
                    continue
                title = A.cell_title(cell)
                right = A.cell_align(cell) == 2
                if title:
                    self._line(target, title, base * 0.95, ink, right=right, bold=True, ratio=1.25, after=3)
                if cell.chart is not None:
                    chart = A.cell_chart(cell, plan.cell_w, b.cell_height)
                    alt = f"{chart.chart_type} chart" + (f": {title}" if title else "")
                    self._picture(target, chart_png(chart, self.theme), alt, width_pt=plan.cell_w)
                if cell.value:
                    self._line(target, cell.value, base * 2.6, ink, right=right, bold=True, ratio=1.15)
                if cell.label:
                    self._line(target, cell.label, base * 0.86, muted, right=right)
                if cell.note:
                    self._line(target, cell.note, base * 0.78, muted, right=right, before=2)
                first = target.paragraphs[0]
                if not first.text and len(target.paragraphs) > 1 and not first._p.xpath(".//w:drawing"):
                    first._p.getparent().remove(first._p)
        if b.note:
            self._line(c, b.note, base * 0.8, muted, right=A.align(b.note) == 2, before=4)
        self._spacer_after(c)

    def _b_paired_row_columns(self, c, b):
        base = self.theme.typography.base_size
        width = self.content_width_pt
        gap = 20.0
        col = (width - gap) / 2
        ink, text, muted = A.ink(self.theme), self.theme.colors.text_primary, self.theme.colors.text_secondary
        header = bool(b.header_first or b.header_second)
        table = self._grid(c, [col, gap, col], False, rows=len(b.rows) + int(header))
        F.set_table_cell_margins(table, 100, 120, 0, 0)

        def fill(cell, value, size, color, bold, ratio=1.5):
            if value:
                self._line(cell, value, size, color, right=A.align(value) == 2, bold=bold, ratio=ratio)
                first = cell.paragraphs[0]
                if not first.text and len(cell.paragraphs) > 1:
                    first._p.getparent().remove(first._p)

        r = 0
        if header:
            left, right = A.paired_sides(b.header_first or "", b.header_second or "", b.rows)
            row = table.rows[0]
            F.set_repeat_table_header(row)
            fill(row.cells[0], left, base * 0.86, muted, True, 1.3)
            fill(row.cells[2], right, base * 0.86, muted, True, 1.3)
            for i in (0, 2):
                F.set_cell_borders(row.cells[i], bottom=("single", 6, ink))
            r = 1
        for item in b.rows:
            left, right = A.paired_sides(item.first, item.second, b.rows)
            row = table.rows[r]
            size, color = (base * 1.12, ink) if item.heading else (base, text)
            fill(row.cells[0], left, size, color, True if item.heading else None)
            fill(row.cells[2], right, size, color, True if item.heading else None)
            for i in (0, 2):
                F.set_cell_borders(row.cells[i], bottom=("single", 2, self.theme.colors.border))
            r += 1
        self._spacer_after(c)

