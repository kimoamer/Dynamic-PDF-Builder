"""
Running paragraphs in balanced columns.

``ColumnFlow`` sets a run of consecutive paragraphs in side-by-side columns
inside the normal frame, so headings, tables and figures around the run stay at
full width. Columns are balanced when the run ends on the page; a run that does
not fit fills the columns that are left and continues on the next page. Columns
are drawn one after the other, so the PDF text order is the reading order.

Left-to-right text only: the planner never marks a right-to-left run.
"""
from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from reportlab.platypus import Flowable, Paragraph

_BALANCE_STEPS = 10     # bisection steps: about 0.3 pt on a 300 pt run
_MIN_LINES = 3          # lines a column needs before a run may start on this page

Placed = Tuple[Paragraph, float]


def _copy_tags(src, part) -> None:
    for a in ("_dpb_block", "_dpb_role", "_dpb_level"):
        if hasattr(src, a) and not hasattr(part, a):
            setattr(part, a, getattr(src, a))


class ColumnFlow(Flowable):
    def __init__(self, items: Sequence[Paragraph], columns: int = 2, gap: float = 18.0,
                 fixed: Optional[List[List[Placed]]] = None):
        super().__init__()
        self.items = list(items)
        self.columns = columns
        self.gap = gap
        self._fixed = fixed                 # head of a split: its columns are already decided
        self._cols: List[List[Placed]] = fixed or []
        self._wrapped = None
        self.spaceAfter = self.items[-1].getSpaceAfter() if self.items else 0
        blocks = sorted({b for b in (getattr(f, "_dpb_block", None) for f in self.items) if b is not None})
        if blocks:                          # one region stands for the run; the others are recorded with it
            self._dpb_block, self._dpb_extra_blocks = blocks[0], tuple(blocks[1:])
            self._dpb_role = "body"

    def _col_width(self, aW: float) -> float:
        return (aW - self.gap * (self.columns - 1)) / self.columns

    @staticmethod
    def _pour(items: List[Paragraph], w: float, h: float):
        """Fill one column of height ``h``: what was placed, and what is left."""
        placed: List[Placed] = []
        rest = list(items)
        y = 0.0
        while rest:
            f = rest[0]
            before = f.getSpaceBefore() if placed else 0.0
            fh = f.wrap(w, h)[1]
            room = h - y - before
            if fh <= room:
                placed.append((f, fh))
                y += before + fh + f.getSpaceAfter()
                rest.pop(0)
                continue
            parts = f.split(w, room) if room >= 2 * f.style.leading else []
            if len(parts) == 2:
                for part in parts:
                    _copy_tags(f, part)
                placed.append((parts[0], parts[0].wrap(w, room)[1]))
                rest[0] = parts[1]
            break
        return placed, rest

    def _layout(self, w: float, h: float):
        cols, rest = [], self.items
        for _ in range(self.columns):
            placed, rest = self._pour(rest, w, h)
            cols.append(placed)
        return cols, rest

    def _height(self, cols: List[List[Placed]]) -> float:
        tallest = 0.0
        for col in cols:
            y = 0.0
            for j, (f, fh) in enumerate(col):
                y += (f.getSpaceBefore() if j else 0.0) + fh + (f.getSpaceAfter() if j < len(col) - 1 else 0.0)
            tallest = max(tallest, y)
        return tallest

    def _balanced(self, w: float) -> float:
        """Smallest column height that holds the whole run."""
        total = sum(f.wrap(w, 1e6)[1] + f.getSpaceBefore() + f.getSpaceAfter() for f in self.items)
        lo, hi = total / self.columns, total
        for _ in range(_BALANCE_STEPS):
            mid = (lo + hi) / 2
            if self._layout(w, mid)[1]:
                lo = mid
            else:
                hi = mid
        return hi

    def wrap(self, aW, aH):
        self.width = self._width = aW
        if self._fixed is not None:
            self.height = self._height(self._fixed)
            return aW, self.height
        if self._wrapped and self._wrapped[0] == aW:
            self.height = self._wrapped[1]
        else:
            w = self._col_width(aW)
            h = self._balanced(w)
            self._cols, _ = self._layout(w, h)
            self.height = self._height(self._cols)
            self._wrapped = (aW, self.height)
        return aW, self.height

    def split(self, aW, aH):
        if self._fixed is not None or not self.items:
            return []
        leading = max(f.style.leading for f in self.items)
        if aH < _MIN_LINES * leading:
            return []
        cols, rest = self._layout(self._col_width(aW), aH)
        placed = [f for col in cols for f, _ in col]
        if not rest:
            return [self]
        if not placed:
            return []
        head = ColumnFlow(placed, self.columns, self.gap, fixed=cols)
        return [head, ColumnFlow(rest, self.columns, self.gap)]

    def draw(self):
        w = self._col_width(self.width)
        for i, col in enumerate(self._cols):
            x = i * (w + self.gap)
            y = self.height
            for j, (f, fh) in enumerate(col):
                y -= (f.getSpaceBefore() if j else 0.0) + fh
                f.drawOn(self.canv, x, y)
                y -= f.getSpaceAfter()


def column_flow(items: Sequence, columns: int, gap: float) -> list:
    """A run as one ``ColumnFlow``, or unchanged if anything in it is not a plain paragraph."""
    items = list(items)
    if items and all(isinstance(f, Paragraph) for f in items):
        return [ColumnFlow(items, columns, gap)]
    return items
