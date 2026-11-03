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


class GeoFrame(Frame):
    """A Frame that records placed regions into a shared ``Geometry``."""

    geometry: Optional[Geometry] = None
    landscape = False

    def add(self, flowable, canv, trySplit=0):
        y0 = self._y
        at_top = getattr(self, "_atTop", 0)
        placed = super().add(flowable, canv, trySplit)
        geo = self.geometry
        if (placed and geo is not None and getattr(flowable, "_dpb_block", None) is not None
                and (y0 - self._y > 0.5 or getattr(flowable, "_dpb_role", "") == "heading")):
            page = canv.getPageNumber()
            if page not in geo.pages:
                geo.pages[page] = PageInfo(page, self.id, self._y2, self._y1, self._x1, self._width,
                                           self.landscape)
            top = y0 - (0 if at_top else flowable.getSpaceBefore())
            bottom = self._y + flowable.getSpaceAfter()
            try:
                width = min(self._width, float(getattr(flowable, "width", 0) or self._width))
            except (TypeError, ValueError):      # e.g. HRFlowable width "100%"
                width = self._width
            geo.regions.append(Region(page, self.id, top, max(bottom, self._y1), self._x1,
                                      self._x1 + width, flowable._dpb_block,
                                      getattr(flowable, "_dpb_role", "other"),
                                      getattr(flowable, "_dpb_level", 0)))
        return placed

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
