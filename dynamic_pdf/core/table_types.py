"""
What each column of a table holds, read from its header and cells. Nothing is changed.

Roles: ``period`` (years, quarters, months, dates, week numbers), ``identifier`` (codes,
invoice and account numbers, row numbers), ``category`` (short labels), ``text`` (prose),
and three kinds of figure: ``measure``, ``currency`` and ``percent``. Each column also
gets the unit and decimal precision its cells show. A table is ``periods_in_columns``
(headers are periods, as in a financial statement), ``periods_in_rows`` (one column of
periods, a time series) or ``records``. Rows labelled total or subtotal are found in
English and Arabic. Arabic-Indic digits are read as digits.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .inline import plain_text
from .keywords import pattern

FIGURES = ("measure", "currency", "percent")
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_NUM = re.compile(r"^(?P<sign>[+\-−–]?)\(?(?P<sign2>[+\-−]?)(?P<int>\d{1,3}(?:(?P<sep>[, ' ])\d{3})+|\d+)"
                  r"(?:\.(?P<dec>\d+))?\)?\s*(?P<suffix>k|m|mn|mm|bn|b|x|×|pp|bps|pts?)?\.?$", re.I)
_QTY_UNIT = re.compile(r"^(?P<n>.+?)\s*(?P<unit>hours?|hrs?|h|days?|weeks?|months?|years?|kg|g|t|km|m|cm|mm|ms|s|sec|"
                       r"min|mins|gb|mb|tb|kb|users?|pcs|units?|seats?|°c|kwh|mw|l|ml|ساعة|ساعات|يوم|أيام|كجم|كم)$", re.I)
_YEAR = re.compile(r"^(?:19|20)\d{2}$")
_PERIOD = re.compile(
    r"^(?:(?:fy|cy)\s?'?\d{2,4}[a-z]?"                                  # FY2024, FY24, CY'23
    r"|(?:19|20)\d{2}(?:\s?[/\-–]\s?(?:\d{2}|\d{4}))?\s?[aefpb]?"         # 2024, 2023/24, 2025E
    r"|(?:19|20)\d{2}\s?(?:م|هـ|ه)"                                     # 2024م
    r"|1[34]\d{2}\s?(?:هـ|ه)"                                           # 1445هـ
    r"|(?:q[1-4]|h[12])(?:\s*[\-/ ]?\s*(?:fy)?'?(?:\d{2}|\d{4}))?"       # Q1, Q3 2024, H1-24
    r"|(?:19|20)\d{2}\s*[\-/ ]?\s*(?:q[1-4]|h[12])"                     # 2024 Q1
    r"|\d{4}-\d{2}(?:-\d{2})?"                                          # 2024-03, 2024-03-31
    r"|\d{1,2}[/.]\d{1,2}[/.]\d{2,4}"                                   # 31/03/2024
    r"|(?:week|wk|w|month|day|year|sprint)\s?\d{1,3}"                   # Week 3
    r"|(?:الأسبوع|الشهر|اليوم|السنة|الربع)\s?\d{1,3}"
    r"|الربع (?:الأول|الثاني|الثالث|الرابع)(?:\s+\d{4})?"
    r"|(?:النصف|نصف السنة) (?:الأول|الثاني)(?:\s+\d{4})?"
    r")$", re.I)
_IDENT = re.compile(r"^(?:[#№]\s?\d+|[a-z]{1,6}[-_/]?\d[\w\-/.]*|\d+[-/][a-z]+[\w\-/]*|0\d{2,}|v\d+(?:\.\d+)+"
                    r"|[a-z][a-z0-9]*(?:[_.][a-z0-9]+)+|[0-9a-f]{7,40}|[a-z][\w.+-]*@[\w.-]+|/[\w/{}.:-]+"
                    r"|(?-i:[A-Z][A-Z0-9]+(?:[-_][A-Z0-9]+)+)|\d{3,}(?:-\d+)+)$", re.I)
_HEADER_UNIT = re.compile(r"\(([^)]{1,16})\)|\[([^\]]{1,16})\]|,\s*([^,]{1,12})$|\bin\s+([$€£]?\w{1,6})$")


@dataclass
class Column:
    role: str
    unit: Optional[str] = None
    precision: Optional[int] = None      # decimals shown, for figures

    @property
    def figure(self) -> bool:
        return self.role in FIGURES


@dataclass
class TableTypes:
    columns: List[Column]
    orientation: str                                  # periods_in_columns | periods_in_rows | records
    period_columns: List[int] = field(default_factory=list)   # columns headed by a period
    current_col: Optional[int] = None                 # the latest actual period, when periods run across
    total_rows: List[int] = field(default_factory=list)       # body rows labelled total
    subtotal_rows: List[int] = field(default_factory=list)

    @property
    def roles(self) -> List[str]:
        return [c.role for c in self.columns]

    @property
    def numeric_cols(self) -> List[int]:
        """Columns of figures: set to the reading end so their digits line up."""
        return [i for i, c in enumerate(self.columns) if c.figure]

    def summary(self) -> str:
        counts: dict = {}
        for r in self.roles:
            counts[r] = counts.get(r, 0) + 1
        out = ", ".join(f"{r}×{n}" if n > 1 else r for r, n in counts.items())
        if self.orientation != "records":
            out += f"; {self.orientation.replace('_', ' ')}"
        if self.total_rows or self.subtotal_rows:
            out += f"; {len(self.total_rows) + len(self.subtotal_rows)} total row(s)"
        return out

    def chart_suggestion(self) -> Optional[str]:
        """A chart that would suit this table. Only ever said, never drawn."""
        figs = self.numeric_cols
        if not figs:
            return None
        if self.orientation == "periods_in_rows":
            return "line chart over time"
        if self.orientation == "periods_in_columns":
            return "grouped bar chart by period"
        if any(c.role == "category" for c in self.columns) and len(figs) == 1:
            return "bar chart by category"
        return None


def ascii_digits(text: str) -> str:
    """Arabic-Indic digits and separators as ASCII, so one parser reads both."""
    return text.translate(_DIGITS).replace("٫", ".").replace("٬", ",").replace("٪", "%")


@dataclass
class Cell:
    kind: str                            # empty | percent | currency | number | year | period | identifier | label
    value: Optional[float] = None
    decimals: int = 0
    unit: Optional[str] = None
    grouped: Optional[bool] = None       # thousands separator shown (None when under 1000)
    words: int = 0


def _number(s: str) -> Optional[Tuple[float, int, Optional[str], Optional[bool]]]:
    m = _NUM.match(s.strip())
    if not m:
        return None
    digits = re.sub(r"\D", "", m["int"])
    dec = m["dec"] or ""
    value = float(f"{digits}.{dec}" if dec else digits)
    if (m["sign"] or m["sign2"]) in ("-", "−", "–") or (s.strip().startswith("(") and s.strip().endswith(")")):
        value = -value
    grouped = bool(m["sep"]) if abs(value) >= 1000 else None
    return value, len(dec), (m["suffix"] or None), grouped


def read_cell(raw: str) -> Cell:
    text = " ".join(plain_text(str(raw)).split())
    code = str(raw).strip().startswith("`") and str(raw).strip().endswith("`")
    if not text or pattern("tables", "placeholder").match(text):
        return Cell("empty")
    s = ascii_digits(text)
    if code:
        return Cell("identifier", words=1)
    if _YEAR.match(s):
        return Cell("year", value=float(s))
    if _PERIOD.match(s) or _is_month_date(s):
        return Cell("period")
    if "%" in s:
        n = _number(s.replace("%", "").strip())
        if n:
            return Cell("percent", value=n[0], decimals=n[1], unit="%", grouped=n[3])
    cur = pattern("tables", "currency").search(s)
    if cur:
        rest = (s[:cur.start()] + " " + s[cur.end():]).strip()
        n = _number(rest)
        if n:
            return Cell("currency", value=n[0], decimals=n[1], unit=cur.group(0).strip().upper(), grouped=n[3])
    n = _number(s)
    if n:
        return Cell("number", value=n[0], decimals=n[1], unit=n[2], grouped=n[3])
    q = _QTY_UNIT.match(s)
    if q and _number(q["n"]):
        n = _number(q["n"])
        return Cell("number", value=n[0], decimals=n[1], unit=q["unit"].lower(), grouped=n[3])
    if " " not in s and _IDENT.match(s):
        return Cell("identifier", words=1)
    return Cell("label", words=len(text.split()))


def _is_month_date(s: str) -> bool:
    months = pattern("tables", "months")
    m = months.search(s)
    if not m:
        return False
    rest = (s[:m.start()] + s[m.end():]).replace(",", " ").replace(".", " ").split()
    return len(rest) <= 2 and all(re.fullmatch(r"'?\d{1,4}(?:م|هـ)?", w) for w in rest)


def header_unit(header: str) -> Optional[str]:
    h = ascii_digits(plain_text(header or ""))
    m = _HEADER_UNIT.search(h)
    if not m:
        return None
    return next(g for g in m.groups() if g).strip()


def _year_of(header: str) -> Optional[Tuple[int, int, bool]]:
    """(year, sub-period, estimate) of a period header, for ordering."""
    s = ascii_digits(plain_text(header or "")).strip().lower()
    years = re.findall(r"(?:19|20)\d{2}|(?<=fy)\d{2}|(?<=fy')\d{2}|(?<=['/\-])\d{2}\b", s)
    if not years:
        return None
    y = years[-1]
    year = int(y) if len(y) == 4 else 2000 + int(y)
    sub = re.search(r"q([1-4])|h([12])", s)
    part = int(sub.group(1) or int(sub.group(2)) * 2) if sub else 0
    estimate = bool(re.search(r"\d\s?[efpb]$|estimate|forecast|budget|plan|target|توقع|مستهدف|تقديري", s))
    return year, part, estimate


def _role(header: str, cells: List[Cell], first: bool) -> Column:
    h = " ".join(plain_text(header or "").split())
    filled = [c for c in cells if c.kind != "empty"]
    unit = header_unit(h)
    if not filled:
        return Column("text")
    n = len(filled)
    share = lambda *kinds: sum(c.kind in kinds for c in filled) / n
    period_head = bool(h) and bool(pattern("tables", "period_header").search(h.lower()))
    ident_head = bool(h) and bool(pattern("tables", "identifier_header").search(h.lower()))
    money_head = bool(pattern("tables", "money_header").search(h)) or bool(
        unit and pattern("tables", "currency").search(ascii_digits(unit)))
    percent_head = bool(pattern("tables", "percent_header").search(h))
    if share("period") + share("year") >= 0.8 and (share("period") >= 0.5 or period_head or first or not h):
        return Column("period")
    if period_head and share("number") + share("year") >= 0.8 and all(
            c.decimals == 0 and (c.value or 0) >= 0 and (c.kind == "year" or c.value < 400) for c in filled):
        return Column("period")                     # week 7, day 28, year 2024 under a period header
    if ident_head and share("number", "identifier", "year") >= 0.8 and not money_head:
        return Column("identifier")
    figures = [c for c in filled if c.kind in ("percent", "currency", "number", "year")]
    # "4 h", "6 h", "8 h" down the first column are the rows' names (the levels compared),
    # not figures to line up: each cell carries its unit and no two are alike
    if (first and n >= 2 and all(c.kind == "number" and c.unit for c in filled)
            and len({(c.value, c.unit) for c in filled}) == n and not unit):
        return Column("category")
    if len(figures) / n >= 0.8:
        decimals = max(c.decimals for c in figures)
        units = [c.unit for c in figures if c.unit]
        if share("percent") > 0.5 or (percent_head and share("currency") == 0):
            return Column("percent", "%", decimals)
        if share("currency") > 0.5:
            return Column("currency", max(set(units), key=units.count) if units else unit, decimals)
        if money_head and not percent_head:
            return Column("currency", unit, decimals)
        return Column("measure", unit or (max(set(units), key=units.count) if units else None), decimals)
    if share("identifier") >= 0.6 or (ident_head and share("identifier", "label") >= 0.8
                                      and all(c.words <= 2 for c in filled)):
        return Column("identifier")
    words = [c.words for c in filled if c.kind == "label"] or [1]
    if sum(words) / len(words) <= 5 and max(words) <= 8:
        return Column("category")
    return Column("text")


def _row_label(row: Sequence[str], roles: List[str]) -> str:
    for ci, cell in enumerate(row):
        if ci < len(roles) and roles[ci] not in FIGURES and str(cell).strip():
            return " ".join(plain_text(str(cell)).split())
    return ""


def infer_table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> TableTypes:
    """Column roles, orientation, current period and total rows of one table."""
    headers = list(headers or [])
    ncols = max([len(headers)] + [len(r) for r in rows] + [1])
    cells = [[read_cell(r[ci]) if ci < len(r) else Cell("empty") for r in rows] for ci in range(ncols)]
    subtotal, total = pattern("tables", "subtotal"), pattern("tables", "total")
    labels = []
    # a total row, or an amount in words, is not data of its column, so roles are read without it
    for r in rows:
        first = next((plain_text(str(c)) for c in r if str(c).strip()), "")
        labels.append(first)
    in_words = pattern("tables", "in_words")
    is_total = [bool(subtotal.search(x) or total.search(x) or in_words.search(x)) for x in labels]
    body = [[c for c, t in zip(col, is_total) if not t] or col for col in cells]
    columns = [_role(headers[ci] if ci < len(headers) else "", body[ci], ci == 0) for ci in range(ncols)]
    roles = [c.role for c in columns]
    period_cols = [ci for ci in range(1, len(headers))
                   if read_cell(headers[ci]).kind in ("year", "period") and columns[ci].figure]
    if len(period_cols) >= 2:
        orientation = "periods_in_columns"
    elif roles[0] == "period":                       # each row is a period: a time series
        orientation = "periods_in_rows"
    else:
        orientation = "records"
    current = None
    if orientation == "periods_in_columns":
        dated = [(ci, _year_of(headers[ci])) for ci in period_cols]
        dated = [(ci, y) for ci, y in dated if y]
        actual = [(ci, y) for ci, y in dated if not y[2]] or dated
        if actual and len({y[1] > 0 for _, y in actual}) == 1:      # H2 next to FY: no one current period
            best = max(y[:2] for _, y in actual)
            hits = [ci for ci, y in actual if y[:2] == best]
            current = hits[0] if len(hits) == 1 else None
    totals, subs = [], []
    for ri, r in enumerate(rows):
        label = _row_label(r, roles)
        if subtotal.search(label):
            subs.append(ri)
        elif total.search(label):
            totals.append(ri)
    return TableTypes(columns=columns, orientation=orientation, period_columns=period_cols, current_col=current,
                      total_rows=totals, subtotal_rows=subs)


def table_types(block) -> TableTypes:
    return infer_table(block.headers or [], block.rows)


__all__ = ["Cell", "Column", "FIGURES", "TableTypes", "ascii_digits", "header_unit", "infer_table", "measured_rows",
           "read_cell", "row_spans", "table_types"]


def row_spans(block) -> Dict[int, Tuple[int, int, int]]:
    """Cells a row joins, as ``{row: (first, last, content)}`` over the data rows and then the
    footer row, in reading order. Only empty cells are joined, and only in these rows:

    - a total or subtotal row with its label first and its figure last: the label runs over the
      empty cells between them, as invoices and statements set it;
    - a row with its label first and a text last (an amount in words): the text runs over them;
    - a row with only its first cell (a group heading): that cell runs across the row.
    """
    rows = [list(r) for r in block.rows] + ([list(block.footer_row)] if block.footer_row else [])
    ncols = max([len(block.headers or [])] + [len(r) for r in rows] + [1])
    if ncols < 2:
        return {}
    totals = set(table_types(block).total_rows) | set(table_types(block).subtotal_rows)
    if block.footer_row:
        totals.add(len(rows) - 1)
    out: Dict[int, Tuple[int, int, int]] = {}
    for ri, row in enumerate(rows):
        cells = [str(row[ci]).strip() if ci < len(row) else "" for ci in range(ncols)]
        full = [ci for ci, c in enumerate(cells) if c]
        if full == [0]:
            out[ri] = (0, ncols - 1, 0)
        elif len(full) == 2 and full[0] == 0 and full[1] >= 2:
            last = full[1]
            kind = read_cell(cells[last]).kind
            if kind in ("number", "currency", "percent", "year"):
                if ri in totals:
                    out[ri] = (0, last - 1, 0)
            elif kind == "label" and len(cells[last]) > 12:
                out[ri] = (1, last, last)
    return out


def measured_rows(block) -> List[List[str]]:
    """The data rows as column widths should see them: a cell that runs over others is left out,
    since the cells it joins give it their room."""
    spans = row_spans(block)
    out = []
    for ri, row in enumerate(block.rows):
        row = [str(x) for x in row]
        if ri in spans:
            content = spans[ri][2]
            row = [("" if ci == content else x) for ci, x in enumerate(row)]
        out.append(row)
    return out
