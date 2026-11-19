"""
Every table of a document as a workbook: one sheet a table, numbers as numbers in the format the
document writes them, and each formula as a working spreadsheet formula. The PDF is to read, the
DOCX to edit, the workbook to calculate with. Needs openpyxl (the ``xlsx`` extra).

A formula is written as the author wrote it: the document names cells as a spreadsheet does
(the header is row 1), so ``=B2*C2`` means the same cell in the sheet. Word's ``ABOVE`` and
``LEFT`` become the ranges they stand for, and ``WORDS`` (which no spreadsheet has) its text.
"""
from __future__ import annotations

import io
import re
from typing import Optional

from ..core.formulas import col_letter, is_formula
from ..core.inline import plain_text
from ..core.table_types import read_cell

_BAD_NAME = re.compile(r"[\[\]:*?/\\]")


def _number_format(text: str) -> Optional[str]:
    """The spreadsheet format that writes a number as ``text`` does, or None for text."""
    cell = read_cell(text)
    if cell.kind not in ("number", "currency", "percent") or cell.value is None:
        return None
    core = ("#,##0" if cell.grouped is not False else "0") + ("." + "0" * cell.decimals if cell.decimals else "")
    plain = plain_text(text).strip()
    if cell.kind == "percent":           # a change written with its sign keeps it: +16%, -3%, 0%
        return f"+{core}%;-{core}%;{core}%" if plain.startswith("+") else core + "%"
    fmt = core
    if cell.kind == "currency" and cell.unit:
        unit = cell.unit
        found = re.search(re.escape(unit), plain, re.I)
        if found and found.start() == 0:
            fmt = f'"{plain[:found.end()]} "{core}' if not plain[found.end():found.end() + 1].isdigit() else f'"{plain[:found.end()]}"{core}'
        elif found:
            fmt = f'{core}" {plain[found.start():found.end()]}"'
    if plain.startswith("(") and plain.endswith(")"):
        fmt = f"{fmt};({fmt})"
    return fmt


def _value(text: str):
    cell = read_cell(text)
    if cell.kind in ("number", "currency") and cell.value is not None:
        return cell.value
    if cell.kind == "percent" and cell.value is not None:
        return cell.value / 100
    return plain_text(text)


def _expand(formula: str, grid, r: int, c: int) -> str:
    """Word's ABOVE and LEFT as the ranges they cover in this table."""
    def numeric(row, col):
        text = str(grid[row][col] or "") if col < len(grid[row]) else ""
        return is_formula(text) or read_cell(text).kind in ("number", "currency", "percent", "year")

    def span(name):
        cells, row, col = [], r, c
        while True:
            row, col = (row - 1, col) if name == "ABOVE" else (row, col - 1)
            if row < 1 or col < 0:
                break
            text = str(grid[row][col] or "") if col < len(grid[row]) else ""
            if numeric(row, col):
                cells.append((row, col))
            elif text.strip():
                break
        if not cells:
            return "0"
        (r0, c0), (r1, c1) = cells[-1], cells[0]
        return f"{col_letter(c0)}{r0 + 1}:{col_letter(c1)}{r1 + 1}"
    return re.sub(r"\b(ABOVE|LEFT)\b", lambda m: span(m.group(1)), formula, flags=re.I)


def _sheet_name(caption: Optional[str], n: int, used: set) -> str:
    base = _BAD_NAME.sub(" ", plain_text(caption or "")).strip()[:28] or f"Table {n}"
    name, k = base, 2
    while name.lower() in used:
        name = f"{base[:26]} {k}"
        k += 1
    used.add(name.lower())
    return name


def render_xlsx(source_blocks, computed_blocks, meta) -> bytes:
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
    except ImportError as e:
        from ..utils.errors import MissingDependencyError
        raise MissingDependencyError('the workbook needs openpyxl: pip install "dynamic-pdf-builder[xlsx]"') from e
    tables = [(s, d) for s, d in zip(source_blocks, computed_blocks) if getattr(s, "type", None) == "table"]
    if not tables:
        raise ValueError("the document has no tables to put in a workbook")
    wb = Workbook()
    wb.remove(wb.active)
    rtl = (meta.language or "").lower().startswith("ar") or meta.rtl or meta.direction == "rtl"
    used: set = set()
    for n, (src, done) in enumerate(tables, 1):
        ws = wb.create_sheet(_sheet_name(src.caption, n, used))
        ws.sheet_view.rightToLeft = rtl
        grid = [list(src.headers)] + [list(r) for r in src.rows] + ([list(src.footer_row)] if src.footer_row else [])
        shown = [list(done.headers)] + [list(r) for r in done.rows] + ([list(done.footer_row)] if done.footer_row else [])
        widths = [0] * max(len(row) for row in grid)
        for r, row in enumerate(grid):
            for c, raw in enumerate(row):
                text = str(raw or "")
                seen = str(shown[r][c]) if c < len(shown[r]) else text
                cell = ws.cell(row=r + 1, column=c + 1)
                if r and is_formula(text) and not re.match(r"\s*=\s*WORDS\s*\(", text, re.I):
                    cell.value = "=" + _expand(text.strip()[1:], grid, r, c)
                    fmt = _number_format(seen)
                elif r:
                    cell.value = _value(seen)
                    fmt = _number_format(seen)
                else:
                    cell.value = plain_text(text)
                    cell.font = Font(bold=True)
                    cell.fill = PatternFill("solid", fgColor="EEEEEE")
                    fmt = None
                if fmt:
                    cell.number_format = fmt
                if src.footer_row and r == len(grid) - 1:
                    cell.font = Font(bold=True)
                cell.alignment = Alignment(wrap_text=len(seen) > 40, vertical="top")
                widths[c] = max(widths[c], min(len(plain_text(seen)), 40))
        for c, w in enumerate(widths):
            ws.column_dimensions[col_letter(c)].width = max(8, w + 2)
        ws.freeze_panes = "A2"
        # printed, the sheet is one page wide: a wide table turns the page rather than losing columns
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
        if sum(max(8, w + 2) for w in widths) > 95:
            ws.page_setup.orientation = "landscape"
    wb.properties.title = meta.title or None
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
