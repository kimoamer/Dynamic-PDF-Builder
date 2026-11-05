"""
Layout analysis: measure every block with real font metrics at the frame
width, then simulate pagination to *predict* a layout before rendering it.

Measurement builds the same flowables the renderer would (sharing the
request-local figure cache) and wraps them at the target width, so paragraph,
list and table heights are exact; only page-break placement is simulated.
The simulator emits the same ``Region`` objects the real renderer records, so
one scoring function serves predicted and rendered layouts.
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Dict, List, Tuple

from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus.flowables import KeepTogether

from ..schema.enums import Orientation, PageSize
from .geometry import Geometry, PageInfo, Region

_PAGE = {PageSize.A4: (595.28, 841.89), PageSize.LETTER: (612, 792), PageSize.LEGAL: (612, 1008)}
FORCED_BREAK_AFTER = {"page_break", "cover_page", "table_of_contents", "introduction_page"}
NO_CONTENT = {"page_break", "spacer", "watermark", "divider"}


@dataclass
class BlockMeasure:
    index: int
    type: str
    role: str
    height: float            # full height incl. spacing at the frame width
    min_piece: float         # smallest first piece if split (== height if unsplittable)
    splittable: bool
    keep_with_next: bool
    level: int = 0
    landscape: bool = False
    break_before: bool = False
    tail: float = 0.0        # height of the last lines kept with the next block (keep-tail hint)


@dataclass
class FrameGeometry:
    width: float
    height: float
    land_width: float
    land_height: float
    left: float
    bottom: float


def page_size(doc) -> Tuple[float, float]:
    w, h = _PAGE.get(doc.meta.page_size, _PAGE[PageSize.A4])
    return (h, w) if doc.meta.orientation == Orientation.LANDSCAPE else (w, h)


def frame_geometry(doc, theme, policy=None) -> FrameGeometry:
    """The body frame the renderer will use, bands included."""
    from ..layout.page_envelope import resolve_page_envelope
    env = resolve_page_envelope(doc, theme, policy)
    lw, lh = env.landscape_size
    return FrameGeometry(env.width, env.height, lw - env.left - env.right, lh - env.top - env.bottom,
                         env.left, env.bottom)


def _flowable_height(f, canv, width: float, avail: float) -> float:
    from reportlab.platypus.doctemplate import ActionFlowable
    from reportlab.platypus.flowables import UseUpSpace
    if isinstance(f, (ActionFlowable, UseUpSpace)):
        return 0.0          # page breaks / template switches occupy no content height
    w, h = f.wrapOn(canv, width, avail)
    if isinstance(f, KeepTogether) or h >= 0xfffff:
        h = sum(_flowable_height(c, canv, width, avail) for c in f._content)
        return h
    return h + f.getSpaceBefore() + f.getSpaceAfter()


def _min_piece(f, canv, width: float, full: float) -> Tuple[bool, float]:
    """(splittable, height of the smallest acceptable first piece)."""
    if isinstance(f, KeepTogether):
        return False, full
    for frac in (0.1, 0.2, 0.35, 0.5):
        try:
            parts = f.splitOn(canv, width, full * frac)
        except Exception:
            parts = []
        if parts and len(parts) > 1:
            return True, _flowable_height(parts[0], canv, width, full)
    return False, full


def measure_blocks(doc, theme, policy=None, cache=None) -> Tuple[List[BlockMeasure], FrameGeometry]:
    """Measure every top-level block at the frame width (landscape blocks at
    the landscape width) using the renderer's own flowables."""
    from .. import policy as _policy
    from ..layout.engine import _landscape_indices, _role_for
    from ..layout.factory import RenderContext, create_flowables
    from ..policy import DiagnosticCollector, RenderPolicy

    fg = frame_geometry(doc, theme, policy)
    canv = Canvas(io.BytesIO())
    col = DiagnosticCollector(policy or RenderPolicy(error_mode="permissive"))
    token = _policy.activate(col)
    out: List[BlockMeasure] = []
    try:
        lang = "ar" if (doc.meta.rtl or doc.meta.direction == "rtl") else (doc.meta.language or "en")[:2]
        ctx = RenderContext(available_width=fg.width, section_numbering=doc.meta.section_numbering,
                            available_height=fg.height, language=lang)
        ctx.cache = cache
        col.language = lang
        land = _landscape_indices(doc.blocks)
        for i, b in enumerate(doc.blocks):
            is_land = i in land
            width = fg.land_width if is_land else fg.width
            avail = fg.land_height if is_land else fg.height
            ctx.available_width = width
            flows = create_flowables(b, theme, ctx) or []
            role_of = _role_for(b)
            heights = [_flowable_height(f, canv, width, avail) for f in flows]
            total = sum(heights)
            roles = [role_of(f) for f in flows]
            level = next((getattr(f, "_dpb_level", 0) for f in flows if getattr(f, "_toc_entry", None)), 0)
            tail_h = 0.0
            last = flows[-1] if flows else None    # (before split probes alter it)
            if getattr(last, "_dpb_keep_tail", 0) and hasattr(last, "blPara"):
                n_lines = len(getattr(last.blPara, "lines", []) or [])
                if n_lines - last._dpb_keep_tail >= 2:
                    tail_h = last._dpb_keep_tail * last.style.leading + last.getSpaceAfter()
                else:                       # too short to split: it moves whole
                    tail_h = heights[-1]
            splittable, piece = (False, total)
            if flows and b.type not in ("heading",):
                big = flows[-1]
                s, p = _min_piece(big, canv, width, heights[-1])
                if s:
                    splittable, piece = True, sum(heights[:-1]) + p
            keep = any(getattr(f, "keepWithNext", 0) for f in flows[:1]) or b.type == "heading"
            # a block is one item in the simulation: its role is that of its main
            # flowable (a caption travels with its table/figure via keep-with-next)
            main_role = next((r for r in roles if r not in ("caption", "other", "structure", "space")),
                             next((r for r in roles if r != "space"), "space"))
            out.append(BlockMeasure(i, b.type, main_role, total, piece, splittable,
                                    bool(keep), level, is_land,
                                    bool((b.hints or {}).get("break_before")), tail_h))
    finally:
        _policy.deactivate(token)
    return out, fg


def simulate(measures: List[BlockMeasure], fg: FrameGeometry) -> Geometry:
    """Greedy pagination with keep-with-next groups and split points.

    Produces predicted Regions (same shape as the renderer's records)."""
    geo = Geometry()
    page = 1
    land = False

    def frame_h():
        return fg.land_height if land else fg.height

    def open_page(p, landscape):
        geo.pages[p] = PageInfo(p, "land" if landscape else "main", fg.bottom + (fg.land_height if landscape else fg.height),
                                fg.bottom, fg.left, fg.land_width if landscape else fg.width, landscape)

    open_page(page, land)
    used = 0.0
    forced_next = False

    def _tail_moves(mj, j, used, remaining, H):
        """Mirror of the engine's keep-tail split: the whole intro fits here but the
        block it introduces (its first acceptable piece) does not."""
        if not mj.tail or used <= 0 or j + 1 >= n or mj.type in FORCED_BREAK_AFTER:
            return False
        nx = measures[j + 1]
        if nx.landscape != land or nx.break_before:
            return False
        need = nx.min_piece if nx.splittable else nx.height
        return used + remaining + need > H and min(mj.tail, remaining) + need <= H
    i, n = 0, len(measures)
    while i < n:
        m = measures[i]
        if m.landscape != land or forced_next or m.break_before:
            if used > 0:
                page += 1
                used = 0.0
            land = m.landscape
            forced_next = False
            if page not in geo.pages:
                open_page(page, land)
        if m.type == "page_break":
            forced_next = True
            i += 1
            continue
        # keep-with-next group: this block (+ following kept blocks) + first piece of the next
        group_h = 0.0
        j = i
        while j < n - 1 and measures[j].keep_with_next and measures[j].type == "heading":
            group_h += measures[j].height
            j += 1
        need = (group_h + measures[j].min_piece) if j > i else (m.min_piece if m.splittable else m.height)
        H = frame_h()
        if used > 0 and used + need > H:
            page += 1
            used = 0.0
            open_page(page, land)
        top_of = lambda u: fg.bottom + H - u   # noqa: E731
        for k in range(i, j):          # the kept headings
            mk = measures[k]
            geo.regions.append(Region(page, "sim", top_of(used), top_of(used + mk.height), fg.left,
                                      fg.left + fg.width, mk.index, "heading", mk.level))
            used += mk.height
        mj = measures[j]
        remaining = mj.height
        while remaining > 0:
            H = frame_h()
            room = H - used
            if remaining <= room + 0.5 and _tail_moves(mj, j, used, remaining, H):
                # keep-tail intro: its last lines move on with the block it introduces
                head = remaining - mj.tail
                if head > 0.5:
                    geo.regions.append(Region(page, "sim", top_of(used), top_of(used + head), fg.left,
                                              fg.left + fg.width, mj.index, mj.role, mj.level))
                page += 1
                used = 0.0
                open_page(page, land)
                remaining = min(remaining, mj.tail)
                continue
            if remaining <= room + 0.5:
                geo.regions.append(Region(page, "sim", top_of(used), top_of(used + remaining), fg.left,
                                          fg.left + fg.width, mj.index, mj.role, mj.level))
                used += remaining
                remaining = 0
            elif mj.splittable and room >= min(mj.min_piece, remaining):
                geo.regions.append(Region(page, "sim", top_of(used), top_of(H), fg.left,
                                          fg.left + fg.width, mj.index, mj.role, mj.level))
                remaining -= room
                page += 1
                used = 0.0
                open_page(page, land)
            elif used == 0:            # taller than a page and unsplittable: clipped in reality
                geo.regions.append(Region(page, "sim", top_of(0), top_of(min(remaining, H)), fg.left,
                                          fg.left + fg.width, mj.index, mj.role, mj.level))
                used = min(remaining, H)
                remaining = 0
            else:
                page += 1
                used = 0.0
                open_page(page, land)
        if mj.type in FORCED_BREAK_AFTER:
            forced_next = True
        i = j + 1
    return geo


def block_types(doc) -> Dict[int, str]:
    return {i: b.type for i, b in enumerate(doc.blocks)}
