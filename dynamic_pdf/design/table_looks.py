"""Word's table style gallery as table looks: Plain Table 1-5, Grid Table 1-7 and List Table 1-7, each Grid
and List look in black or one of six accents (``style="Grid Table 4 Accent 2"``, or ``grid-table-4-accent-2``).

A look answers, for each cell, its fill, text colour, weight and slant, and the rules on its four sides. The
PDF and the Word renderer both draw from it, so a table looks alike in both and in either direction: sides are
logical (``start`` is where a line begins reading, ``end`` where it stops), and the first column, which names
the rows, is the one at the start. The six accents are the theme's own colours, as Word takes its accents
from the document's theme. The looks follow Word's 2013 gallery closely, not to the point.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

Rule = Tuple[str, float]          # colour, width in points

_NAME = re.compile(r"^\s*(plain|grid|list)[\s_-]*(?:table)?[\s_-]*([1-7])(?:[\s_-]*(?:light|dark|colou?rful))?"
                   r"(?:[\s_-]*accent[\s_-]*([1-6]))?\s*$", re.I)


def parse(name: Optional[str]) -> Optional[Tuple[str, int, int]]:
    """(family, level, accent) for a Word gallery name, or None for any other table style."""
    m = _NAME.match(name or "")
    if not m or (m.group(1).lower() == "plain" and int(m.group(2)) > 5):
        return None
    return m.group(1).lower(), int(m.group(2)), int(m.group(3) or 0)


def _mix(a: str, b: str, share: float) -> str:
    """``share`` of colour ``a``, the rest ``b``."""
    a, b = a.lstrip("#"), b.lstrip("#")
    out = [round(int(a[i:i + 2], 16) * share + int(b[i:i + 2], 16) * (1 - share)) for i in (0, 2, 4)]
    return "#" + "".join(f"{v:02X}" for v in out)


def accents(theme) -> List[str]:
    """Word's black and six accents, from the theme (or brand) colours."""
    from ..renderers.chart import _branded
    from ..schema.blocks import ChartBlock
    picked = _branded(ChartBlock(chart_type="bar", data={"a": 1}), theme).colors if theme is not None else []
    return ["#000000"] + [c.upper() for c in (picked + ["#4472C4", "#ED7D31", "#A5A5A5", "#FFC000", "#5B9BD5",
                                                         "#70AD47"])[:6]]


@dataclass
class Cell:
    fill: Optional[str] = None
    color: Optional[str] = None       # None: the body text colour
    bold: bool = False
    italic: bool = False
    rules: Dict[str, Rule] = field(default_factory=dict)    # top, bottom, start, end


@dataclass
class Look:
    family: str
    level: int
    c: str                            # the accent
    ink: str                          # the body text colour

    def tint(self, share: float) -> str:
        return _mix(self.c, "#FFFFFF", share)

    def shade(self, share: float) -> str:
        return _mix(self.c, "#000000", 1 - share)

    def cell(self, r: int, col: int, rows: int, cols: int, header: bool, footer: bool) -> Cell:
        """The look of cell (r, col): r counts the header row if there is one; col 0 names the rows."""
        f, n = self.family, self.level
        head = header and r == 0
        foot = footer and r == rows - 1
        body_r = r - (1 if header else 0)
        band = not head and not foot and body_r % 2 == 0
        first = col == 0 and not head
        top, bottom, start, end = r == 0, r == rows - 1, col == 0, col == cols - 1
        grey = self.c == "#000000"
        line, light = (("#BFBFBF" if grey else self.tint(0.6)), 0.5), (self.tint(0.6), 0.5)
        x = Cell(bold=head or (first and not (f == "plain" and n == 2)))
        sides = {"top": top, "bottom": bottom, "start": start, "end": end}

        def outer(rule, which=("top", "bottom", "start", "end")):
            for s in which:
                if sides[s]:
                    x.rules[s] = rule

        def inner(rule, h=True, v=True):
            if h and not bottom:
                x.rules["bottom"] = rule
            if v and not end:
                x.rules["end"] = rule

        if f == "plain":
            fill_band = "#F2F2F2"
            if n == 1:
                outer(("#BFBFBF", 0.5)); inner(("#BFBFBF", 0.5))
                x.fill = fill_band if band else None
            elif n == 2:
                outer(("#7F7F7F", 0.5), ("top", "bottom")); inner(("#BFBFBF", 0.5), v=False)
            elif n in (3, 5):
                x.fill = fill_band if band else None
                x.italic = n == 5 and (head or first)
                if head:
                    x.rules["bottom"] = ("#7F7F7F", 0.5)
                if first or (head and col == 0 and n == 5):
                    x.rules["end"] = ("#7F7F7F", 0.5)
            else:
                x.fill = fill_band if band else None
        elif f == "grid":
            if n in (1, 3, 4, 6):
                outer(light); inner(light)
            elif n in (2, 7):
                inner(light)
                outer(light, ("top", "bottom") if n == 2 else ())
            if n == 5:
                outer(("#FFFFFF", 0.5)); inner(("#FFFFFF", 0.5))
                x.fill = self.c if (head or first) else (self.tint(0.4) if band else self.tint(0.2))
                x.color = "#FFFFFF" if (head or first) else None
            elif n == 4:
                x.fill = self.c if head else (self.tint(0.2) if band else None)
                x.color = "#FFFFFF" if head else None
            elif n in (2, 3, 6, 7):
                x.fill = self.tint(0.2) if band else None
            if head and n in (1, 2, 6, 7):
                x.rules["bottom"] = (self.tint(0.6) if n in (1, 6) else self.c, 1.5 if n in (1, 2) else 1.0)
            if n in (6, 7):
                x.color = x.color or self.shade(0.75)
            if n == 7:
                x.italic = head or first
                x.bold = x.bold and not head
        else:                               # list
            if n == 1:
                x.fill = self.tint(0.2) if band else None
                if head:
                    x.rules["bottom"] = light
            elif n == 2:
                outer(light, ("top", "bottom")); inner(light, v=False)
                x.fill = self.tint(0.2) if band else None
            elif n == 3:
                outer((self.c, 1.0))
                x.fill = self.c if head else None
                x.color = "#FFFFFF" if head else None
            elif n == 4:
                outer(light); inner(light, v=False)
                x.fill = self.c if head else (self.tint(0.2) if band else None)
                x.color = "#FFFFFF" if head else None
            elif n == 5:
                x.fill, x.color = self.c, "#FFFFFF"
                if head:
                    x.rules["bottom"] = ("#FFFFFF", 1.5)
                if first:
                    x.rules["end"] = ("#FFFFFF", 0.5)
            elif n == 6:
                outer((self.c, 1.0), ("top", "bottom"))
                x.fill = self.tint(0.2) if band else None
                x.color = self.shade(0.75)
                if head:
                    x.rules["bottom"] = (self.c, 1.0)
            else:
                x.fill = self.tint(0.2) if band else None
                x.color = self.shade(0.75)
                x.italic = head or first
                x.bold = x.bold and not head
                if head:
                    x.rules["bottom"] = light
                if first:
                    x.rules["end"] = light
        if foot:                            # a total row: set bold under a rule, as Word's Total Row
            x.bold = True
            x.rules["top"] = (self.c if not grey else "#000000", 1.0)
            if x.fill and not (f == "list" and n == 5):
                x.fill = None
        if x.fill:                          # white text only on a fill dark enough for it (a gold header is not)
            from ..layout.page_system import readable_on
            if readable_on(x.fill) == "#FFFFFF":
                x.color = "#FFFFFF"
            elif x.color == "#FFFFFF":
                x.color = None
        return x


def look_for(style: Optional[str], theme) -> Optional[Look]:
    """The look a table's ``style`` names, or None for the library's own table styles."""
    got = parse(style)
    if got is None:
        return None
    family, level, accent = got
    ink = getattr(getattr(theme, "colors", None), "text_primary", "#1A1A2E") if theme is not None else "#1A1A2E"
    return Look(family, level, accents(theme)[accent], ink)
