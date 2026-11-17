"""
Computed table cells: a cell that starts with ``=`` holds a formula, written as in a spreadsheet.

    | Item   | Qty | Price  | Amount    |
    |--------|-----|--------|-----------|
    | Paper  | 3   | 12.50  | =B2*C2    |
    | Toner  | 2   | 310.00 | =B3*C3    |
    | VAT    |     | 15%    | =SUM(D2:D3)*C4 |
    | Total  |     |        | =SUM(ABOVE) |
    | In words | | | =WORDS(D5, "SAR") |

Cells are named as a spreadsheet names them: columns A, B, C ... and rows from 1, the header row,
so a formula means the same here, in Word and in an exported workbook. ``ABOVE`` and ``LEFT`` are
Word's: the numbers above in the column, or to the left in the row, up to the first cell that is
not a number. Functions: SUM, AVERAGE, MIN, MAX, COUNT, ROUND, ABS, and WORDS (the amount in
words, see ``core.words``). ``15%`` is 0.15. Arithmetic is decimal, so 0.1 + 0.2 is 0.3, and
ROUND rounds half away from zero, as spreadsheets do.

A result is written as its column writes numbers: the same decimals, thousands separators,
currency, percent sign and digits (Arabic-Indic digits stay Arabic-Indic).
"""
from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, DivisionByZero, InvalidOperation
from typing import Dict, List, Optional, Tuple

from ..utils.errors import DynamicPDFError

_TOKEN = re.compile(r'\s*(?:(?P<str>"[^"]*")|(?P<ref>\$?[A-Z]{1,2}\$?\d+(?::\$?[A-Z]{1,2}\$?\d+)?)(?![A-Za-z(])'
                    r"|(?P<num>\d+(?:\.\d+)?)|(?P<name>[A-Za-z_]+)|(?P<op>[-+*/(),%]))")
_NUMBER_SPAN = re.compile(r"[-−–(]?[0-9٠-٩][0-9٠-٩,٬]*(?:[.٫][0-9٠-٩]+)?\)?")
_INDIC = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")
FUNCTIONS = ("SUM", "AVERAGE", "MIN", "MAX", "COUNT", "ROUND", "ABS", "WORDS")


class FormulaError(DynamicPDFError, ValueError):
    """A formula that cannot be computed; the message names the table and the cell."""


def is_formula(text) -> bool:
    return isinstance(text, str) and text.strip().startswith("=") and len(text.strip()) > 1


def col_letter(i: int) -> str:
    return chr(65 + i) if i < 26 else chr(64 + i // 26) + chr(65 + i % 26)


def _col_index(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n - 1


def _cell_of(ref: str) -> Tuple[int, int]:
    """(row, column), both 0-based, of ``B3``; row 0 is the header row."""
    m = re.fullmatch(r"\$?([A-Z]{1,2})\$?(\d+)", ref)
    return int(m.group(2)) - 1, _col_index(m.group(1))


class _Table:
    """The grid of one table, with each formula computed once, in the order references need."""

    def __init__(self, grid: List[List[str]], label: str, language: str):
        self.grid, self.label, self.language = grid, label, language
        self.values: Dict[Tuple[int, int], object] = {}
        self.busy: set = set()
        self.seen: Dict[Tuple[int, int], list] = {}      # the literal cells each formula read, for its format
        self.looks: Dict[Tuple[int, int], tuple] = {}    # the (text, cell) each result is written as
        self.texts: Dict[Tuple[int, int], str] = {}

    def raw(self, r: int, c: int, where: str = "") -> str:
        if r < 0 or r >= len(self.grid) or c < 0 or c >= len(self.grid[r]):
            raise FormulaError(f"{where or self.label}: {col_letter(c)}{r + 1} is outside the table")
        return str(self.grid[r][c] or "")

    def number(self, r: int, c: int, reader: list, where: str = "") -> Optional[Decimal]:
        """The cell as a number, or None when it holds none (text, or empty)."""
        text = self.raw(r, c, where)
        if is_formula(text):
            v = self.compute(r, c)
            if isinstance(v, Decimal) and self.looks.get((r, c)):
                reader.append(self.looks[(r, c)])     # a result read by another passes its look on
            return v if isinstance(v, Decimal) else None
        from .table_types import read_cell
        cell = read_cell(text)
        if cell.value is None or cell.kind not in ("number", "currency", "percent", "year"):
            return None
        reader.append((text, cell))
        v = Decimal(str(cell.value))
        return v / 100 if cell.kind == "percent" else v

    def compute(self, r: int, c: int):
        if (r, c) in self.values:
            return self.values[(r, c)]
        where = f"{self.label}: {col_letter(c)}{r + 1}"
        if (r, c) in self.busy:
            raise FormulaError(f"{where}: the formula refers back to itself")
        self.busy.add((r, c))
        try:
            reader: list = []
            value = _Parser(self, r, c, reader, where).run(self.raw(r, c).strip()[1:])
        finally:
            self.busy.discard((r, c))
        self.values[(r, c)], self.seen[(r, c)] = value, reader
        if isinstance(value, Decimal):
            # the result as written is the look of whatever reads it next
            from .table_types import read_cell
            self.texts[(r, c)] = format_result(value, self, r, c)
            self.looks[(r, c)] = (self.texts[(r, c)], read_cell(self.texts[(r, c)]))
        else:
            self.texts[(r, c)] = str(value)
        return value


class _Parser:
    def __init__(self, table: _Table, r: int, c: int, reader: list, where: str):
        self.t, self.r, self.c, self.reader, self.where = table, r, c, reader, where

    def fail(self, why: str):
        raise FormulaError(f"{self.where}: {why}")

    def run(self, text: str):
        self.tokens, pos = [], 0
        while pos < len(text):
            m = _TOKEN.match(text, pos)
            if not m or m.end() == pos:
                if text[pos:].strip():
                    self.fail(f"cannot read {text[pos:].strip()[:20]!r}")
                break
            kind = m.lastgroup
            self.tokens.append((kind, m.group(kind)))
            pos = m.end()
        self.i = 0
        try:
            value = self.expr(top=True)
        except (DivisionByZero, InvalidOperation, ZeroDivisionError):
            self.fail("division by zero")
        if self.i < len(self.tokens):
            self.fail(f"unexpected {self.tokens[self.i][1]!r}")
        return value

    def peek(self):
        return self.tokens[self.i] if self.i < len(self.tokens) else (None, None)

    def take(self, value=None):
        kind, v = self.peek()
        if kind is None or (value is not None and v != value):
            self.fail(f"expected {value!r}" if value else "the formula ends too soon")
        self.i += 1
        return kind, v

    def expr(self, top=False):
        value = self.term(top)
        while self.peek()[1] in ("+", "-"):
            op = self.take()[1]
            value = self.num(value) + self.num(self.term()) if op == "+" else self.num(value) - self.num(self.term())
        return value

    def term(self, top=False):
        value = self.unary(top)
        while self.peek()[1] in ("*", "/"):
            op = self.take()[1]
            right = self.num(self.unary())
            value = self.num(value) * right if op == "*" else self.num(value) / right
        return value

    def unary(self, top=False):
        if self.peek()[1] in ("-", "+"):
            sign = self.take()[1]
            v = self.num(self.unary())
            return -v if sign == "-" else v
        value = self.atom(top)
        while self.peek()[1] == "%":
            self.take()
            value = self.num(value) / 100
        return value

    def num(self, v) -> Decimal:
        if isinstance(v, list):
            if len(v) != 1:
                self.fail("a range can be used only inside a function such as SUM")
            v = v[0]
        if not isinstance(v, Decimal):
            self.fail("WORDS gives text, which cannot be calculated with; use it alone in its cell")
        return v

    def atom(self, top=False):
        kind, v = self.take()
        if kind == "num":
            return Decimal(v)
        if kind == "ref":
            if ":" in v:
                return self.range(v)
            r, c = _cell_of(v)
            n = self.t.number(r, c, self.reader, self.where)
            return n if n is not None else (Decimal(0) if not self.t.raw(r, c).strip() else self.fail(
                f"{v} holds text, not a number"))
        if v == "(":
            value = self.expr()
            self.take(")")
            return value
        if kind == "name":
            name = v.upper()
            if name in ("ABOVE", "LEFT"):
                return self.direction(name)
            if name not in FUNCTIONS:
                self.fail(f"unknown function {v}; known: {', '.join(FUNCTIONS)}")
            return self.call(name, top)
        self.fail(f"unexpected {v!r}")

    def range(self, v: str) -> list:
        (r0, c0), (r1, c1) = (_cell_of(x) for x in v.split(":"))
        out = []
        for r in range(min(r0, r1), max(r0, r1) + 1):
            for c in range(min(c0, c1), max(c0, c1) + 1):
                n = self.t.number(r, c, self.reader, self.where)
                if n is not None:
                    out.append(n)
        return out

    def direction(self, name: str) -> list:
        """Word's ABOVE and LEFT: the numbers next to this cell, up to the first that is not one."""
        out, r, c = [], self.r, self.c
        while True:
            r, c = (r - 1, c) if name == "ABOVE" else (r, c - 1)
            if r < 1 or c < 0:
                break
            n = self.t.number(r, c, self.reader)
            if n is None:
                if not self.t.raw(r, c).strip():
                    continue                         # an empty cell does not end the run
                break
            out.append(n)
        return out

    def call(self, name: str, top: bool):
        self.take("(")
        args = []
        if self.peek()[1] != ")":
            while True:
                kind, v = self.peek()
                if kind == "str":
                    self.take()
                    args.append(v[1:-1])
                else:
                    args.append(self.expr())
                if self.peek()[1] != ",":
                    break
                self.take(",")
        self.take(")")
        if name == "WORDS":
            if not top or self.i < len(self.tokens):
                self.fail("WORDS gives text: use it alone, as =WORDS(D6) or =WORDS(D6, \"SAR\")")
            if not args or isinstance(args[0], str):
                self.fail("WORDS needs the amount first")
            texts = [a for a in args[1:] if isinstance(a, str)]
            currency = next((a for a in texts if len(a) == 3 and a.isalpha()), None) or self.currency()
            language = next((a for a in texts if a.lower() in ("ar", "en")), self.t.language)
            from .words import amount_in_words
            try:
                return amount_in_words(self.num(args[0]), language, currency)
            except ValueError as e:
                self.fail(str(e))
        if name == "ROUND":
            if len(args) not in (1, 2):
                self.fail("ROUND takes a number and the decimals to keep")
            places = int(self.num(args[1])) if len(args) == 2 else 0
            return self.num(args[0]).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
        if name == "ABS":
            return abs(self.num(args[0]))
        numbers = [n for a in args for n in (a if isinstance(a, list) else [self.num(a)])]
        if name == "COUNT":
            return Decimal(len(numbers))
        if name == "SUM":
            return sum(numbers, Decimal(0))
        if not numbers:
            self.fail(f"{name} has no numbers to work on")
        return {"AVERAGE": lambda: sum(numbers, Decimal(0)) / len(numbers), "MIN": lambda: min(numbers),
                "MAX": lambda: max(numbers)}[name]()

    def currency(self) -> Optional[str]:
        """The currency code of the cells read, when they share one the words know."""
        from .words import CURRENCIES
        units = {cell.unit for _, cell in self.reader if cell.kind == "currency" and cell.unit}
        return units.pop() if len(units) == 1 and next(iter(units)) in CURRENCIES else None


# ── writing a result as its column writes numbers ──────────────────────────────────────

def _template(table: _Table, r: int, c: int):
    """The literal number cell whose look a result copies: its column's first, else one it read.
    A ratio of what it read (a division) is not in their unit, so it copies nothing it read."""
    from .table_types import read_cell
    for row in range(1, len(table.grid)):
        text = table.raw(row, c) if c < len(table.grid[row]) else ""
        if text and not is_formula(text):
            cell = read_cell(text)
            if cell.kind in ("number", "currency", "percent") and cell.value is not None:
                return text, cell
    read = table.seen.get((r, c)) or []
    numbers = [(t, cell) for t, cell in read if cell.kind in ("number", "currency")]
    if numbers and "/" not in table.raw(r, c):
        return max(numbers, key=lambda tc: tc[1].decimals)
    return None


def format_result(value, table: _Table, r: int, c: int) -> str:
    if not isinstance(value, Decimal):
        return str(value)
    found = _template(table, r, c)
    read = table.seen.get((r, c)) or []
    column = [table.raw(row, c) for row in range(1, len(table.grid)) if c < len(table.grid[row])]
    if found is None:
        places = 2 if "/" in table.raw(r, c) else max([cell.decimals for _, cell in read] + [0])
        return _digits(value, places, _grouping(column + [t for t, _ in read]), indic=False)
    text, cell = found
    if cell.kind == "percent":
        value = value * 100
    grouped = _grouping(column + [t for t, _ in read] + [text])
    indic = bool(re.search("[٠-٩]", text))
    parens = any(t.strip().startswith("(") and t.strip().endswith(")") for t in column + [t for t, _ in read])
    number = _digits(abs(value) if parens else value, cell.decimals, grouped, indic)
    if parens and value < 0:
        number = f"({number})"
    m = _NUMBER_SPAN.search(text)
    return text[:m.start()] + number + text[m.end():] if m else number


def _grouping(texts) -> bool:
    """Thousands separators as the cells show them; a table that shows none either way gets them."""
    from .table_types import read_cell
    seen = [read_cell(t).grouped for t in texts if t and not is_formula(t)]
    return True if True in seen else False if False in seen else True


def _digits(value: Decimal, places: int, grouped: bool, indic: bool) -> str:
    q = value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    out = f"{q:,.{places}f}" if grouped else f"{q:.{places}f}"
    if indic:
        out = out.replace(",", "٬").replace(".", "٫").translate(_INDIC)
    return out


# ── documents ──────────────────────────────────────────────────────────────────────────

def compute_table(block, language: str = "en", strict: bool = True, index: int = 0):
    """The table with every formula cell replaced by its result, or the block itself when it
    has none. ``strict=False`` writes ``#ERROR`` where a formula cannot be computed."""
    rows = [list(r) for r in block.rows]
    footer = list(block.footer_row) if block.footer_row else None
    if not any(is_formula(x) for row in rows + ([footer] if footer else []) for x in row):
        return block
    grid = [list(block.headers)] + rows + ([footer] if footer else [])
    label = f"table {index}" + (f" ({block.caption})" if block.caption else "")
    table = _Table(grid, label, language)
    out = [list(row) for row in grid]
    for r, row in enumerate(grid):
        for c, text in enumerate(row):
            if r and is_formula(text):
                try:
                    table.compute(r, c)
                    out[r][c] = table.texts[(r, c)]
                except FormulaError:
                    if strict:
                        raise
                    out[r][c] = "#ERROR"
    update = {"rows": out[1:len(rows) + 1]}
    if footer:
        update["footer_row"] = out[-1]
    return block.model_copy(update=update)


VALUE = re.compile(r"\{=([A-Za-z][\w:.-]*)!\$?([A-Z]{1,2})\$?(\d+)\}")


def link_values(blocks: list) -> list:
    """Text that quotes a table cell, ``{=invoice!D7}``, shows what the cell shows (its result,
    when it holds a formula), so a figure in the prose cannot drift from its table. A table is
    named by its id; an unknown table or cell stays as written and ``lint()`` reports it."""
    grids = {b.id: [list(b.headers)] + [list(r) for r in b.rows] + ([list(b.footer_row)] if b.footer_row else [])
             for b in blocks if getattr(b, "type", None) == "table" and getattr(b, "id", None)}

    def cell(m):
        grid = grids.get(m.group(1))
        r, c = int(m.group(3)) - 1, _col_index(m.group(2))
        if grid is None or r >= len(grid) or c >= len(grid[r]):
            return m.group(0)
        return str(grid[r][c])

    from .citations import _SKIP_TYPES, _walk_strings
    out, changed = [], False
    for b in blocks:
        if getattr(b, "type", None) not in _SKIP_TYPES and getattr(b, "type", None) != "table" and "{=" in repr(b.model_dump()):
            b = type(b).model_validate(_walk_strings(b.model_dump(), lambda s: VALUE.sub(cell, s) if "{=" in s else s))
            changed = True
        out.append(b)
    return out if changed else blocks


def compute_blocks(blocks: list, language: str = "en", strict: bool = True) -> list:
    """The blocks with their tables' formulas computed. The list itself when there are none, so
    a document without formulas costs one scan."""
    out, changed, n = [], False, 0
    for b in blocks:
        if getattr(b, "type", None) == "table":
            n += 1
            done = compute_table(b, language, strict, n)
            changed |= done is not b
            out.append(done)
        else:
            out.append(b)
    return out if changed else blocks
