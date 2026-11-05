"""
Page geometry captured from the layout engine itself.

``GeoFrame`` records the region every flowable actually occupies when the
ReportLab frame places it (page, frame, top/bottom, width), tagged with the
semantic block it came from and its role. This measures real occupied regions
— not just the lowest text position — without rasterizing or re-parsing the PDF.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from reportlab.platypus import Frame


@dataclass
class Region:
    page: int
    frame: str
    top: float            # y of the top edge (PDF coordinates, origin bottom-left)
    bottom: float
    x0: float
    x1: float
    block: Optional[int]  # index of the semantic block, None for engine flowables
    role: str             # heading | caption | table | figure | body | list | other
    level: int = 0        # heading level when role == heading
    extra_blocks: tuple = ()   # further blocks in this region (a run set in columns)
    chars: int = 0             # characters of a paragraph's text set in this region
    in_float: bool = False     # set beside other content, so its height says nothing of order

    @property
    def height(self) -> float:
        return max(0.0, self.top - self.bottom)


@dataclass
class PageInfo:
    number: int
    frame: str
    frame_top: float
    frame_bottom: float
    frame_x0: float
    frame_width: float
    landscape: bool = False

    @property
    def frame_height(self) -> float:
        return self.frame_top - self.frame_bottom


@dataclass
class Geometry:
    regions: List[Region] = field(default_factory=list)
    pages: Dict[int, PageInfo] = field(default_factory=dict)

    def reset(self):
        self.regions.clear()
        self.pages.clear()

    def fragments(self, block: int) -> List[tuple]:
        """Page, start and end offset of each placed piece of a block's text, in order."""
        out, start = [], 0
        for r in self.regions:
            if r.block == block and r.chars:
                out.append((r.page, start, start + r.chars))
                start += r.chars
        return out

    def by_page(self) -> Dict[int, List[Region]]:
        out: Dict[int, List[Region]] = {}
        for r in self.regions:
            out.setdefault(r.page, []).append(r)
        return out


def tag(flowables, block_index: int, role_of) -> None:
    """Attach block index + role to flowables (recursing into containers)."""
    for f in flowables or []:
        f._dpb_block = block_index
        if not hasattr(f, "_dpb_role"):
            f._dpb_role = role_of(f)
        inner = getattr(f, "_content", None)
        if isinstance(inner, list):
            tag(inner, block_index, role_of)


def content_extent(f, fx: float, fw: float):
    """Horizontal extent actually covered by a placed flowable: real line widths
    for paragraphs (respecting alignment), real widths for tables/images/drawings."""
    from reportlab.platypus import Paragraph
    try:
        if isinstance(f, Paragraph):
            widths = f.getActualLineWidths0() if hasattr(f, "blPara") else []
            st = f.style
            w = min(fw, (max(widths) if widths else fw) + st.leftIndent + st.rightIndent)
            align = st.alignment
            if align == 1:
                return fx + (fw - w) / 2, fx + (fw + w) / 2
            if align == 2:
                return fx + fw - w, fx + fw
            return fx, fx + w
        w = getattr(f, "_width", None) or getattr(f, "drawWidth", None) or getattr(f, "width", None)
        w = min(fw, float(w)) if w else fw
    except (TypeError, ValueError):     # e.g. HRFlowable width "100%"
        return fx, fx + fw
    h = str(getattr(f, "hAlign", "LEFT")).upper()
    off = (fw - w) / 2 if h == "CENTER" else (fw - w if h == "RIGHT" else 0.0)
    return fx + off, fx + off + w


def text_chars(f) -> int:
    """Characters of text in a paragraph or a piece of one."""
    from reportlab.platypus import Paragraph
    if not isinstance(f, Paragraph):
        return 0
    return len(f.getPlainText()) or _split_chars(f)


def _split_chars(f) -> int:
    """A piece of a split paragraph keeps its lines but not its fragments. Each line
    ending stands for the space it replaced."""
    lines = f.blPara.lines
    if f.blPara.kind == 0:
        return sum(len(" ".join(words)) + 1 for _, words in lines)
    return sum(sum(len(w.text) for w in line.words) + 1 for line in lines)


def union_area(rects) -> float:
    """Exact area of a union of axis-aligned rectangles (x0, x1, y0, y1)."""
    rects = [r for r in rects if r[1] > r[0] and r[3] > r[2]]
    if not rects:
        return 0.0
    ys = sorted({y for r in rects for y in (r[2], r[3])})
    area = 0.0
    for lo, hi in zip(ys, ys[1:]):
        spans = sorted((r[0], r[1]) for r in rects if r[2] <= lo and r[3] >= hi)
        covered, cur_s, cur_e = 0.0, None, None
        for s0, s1 in spans:
            if cur_e is None or s0 > cur_e:
                if cur_e is not None:
                    covered += cur_e - cur_s
                cur_s, cur_e = s0, s1
            else:
                cur_e = max(cur_e, s1)
        if cur_e is not None:
            covered += cur_e - cur_s
        area += covered * (hi - lo)
    return area


def union_length(intervals) -> float:
    """Total length of a union of 1-D intervals (lo, hi)."""
    total, cur_s, cur_e = 0.0, None, None
    for lo, hi in sorted(i for i in intervals if i[1] > i[0]):
        if cur_e is None or lo > cur_e:
            if cur_e is not None:
                total += cur_e - cur_s
            cur_s, cur_e = lo, hi
        else:
            cur_e = max(cur_e, hi)
    if cur_e is not None:
        total += cur_e - cur_s
    return total


class GeoFrame(Frame):
    """A Frame that records placed regions into a shared ``Geometry``."""

    geometry: Optional[Geometry] = None
    landscape = False

    def add(self, flowable, canv, trySplit=0):
        y0 = self._y
        at_top = getattr(self, "_atTop", 0)
        placed = super().add(flowable, canv, trySplit)
        geo = self.geometry
        children = getattr(flowable, "_dpb_children", None)
        if placed and geo is not None and children is not None:
            self._note_page(geo, canv)
            self._add_children(geo, canv, children)
        elif (placed and geo is not None and getattr(flowable, "_dpb_block", None) is not None
                and (y0 - self._y > 0.5 or getattr(flowable, "_dpb_role", "") in ("heading", "decorative"))):
            self._note_page(geo, canv)
            page = canv.getPageNumber()
            top = y0 - (0 if at_top else flowable.getSpaceBefore())
            bottom = self._y + flowable.getSpaceAfter()
            x0, x1 = content_extent(flowable, self._x1 + self._leftPadding,
                                    self._width - self._leftPadding - self._rightPadding)
            geo.regions.append(Region(page, self.id, top, max(bottom, self._y1), x0, x1,
                                      flowable._dpb_block,
                                      getattr(flowable, "_dpb_role", "other"),
                                      getattr(flowable, "_dpb_level", 0),
                                      getattr(flowable, "_dpb_extra_blocks", ()),
                                      text_chars(flowable)))
        return placed

    def _note_page(self, geo: Geometry, canv) -> None:
        page = canv.getPageNumber()
        if page not in geo.pages:
            geo.pages[page] = PageInfo(page, self.id, self._y2, self._y1, self._x1, self._width,
                                       self.landscape)

    def _add_children(self, geo: Geometry, canv, children) -> None:
        """Regions for what a composite drew, each where it really is. The composite
        itself adds none, so nothing is counted twice."""
        page = canv.getPageNumber()
        origin_x, origin_y = self._x1 + self._leftPadding, self._y
        for child, x, y, width, height, in_float in children:
            block = getattr(child, "_dpb_block", None)
            if block is None:
                continue
            x0, x1 = content_extent(child, origin_x + x, width)
            geo.regions.append(Region(page, self.id, origin_y + y + height, origin_y + y, x0, x1, block,
                                      getattr(child, "_dpb_role", "other"), 0, (), text_chars(child),
                                      in_float))

    def split(self, flowable, canv):
        parts = super().split(flowable, canv)
        blk = getattr(flowable, "_dpb_block", None)
        if blk is not None:
            for p in parts or []:
                if getattr(p, "_dpb_block", None) is None:
                    p._dpb_block = blk
                    p._dpb_role = getattr(flowable, "_dpb_role", "other")
                    p._dpb_level = getattr(flowable, "_dpb_level", 0)
        return parts
