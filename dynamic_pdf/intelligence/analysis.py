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
from reportlab.platypus.tables import Table

from ..schema.enums import Orientation, PageSize
from ..layout.page_envelope import FRAME_PADDING
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
    ink: float = 0.0         # drawn height without spacing (what a page's fill counts)
    space_before: float = 0.0   # ``height`` = space_before + body + space_after
    body: float = 0.0
    space_after: float = 0.0
    x0: float = 0.0          # horizontal extent of the content, from the frame's start edge
    x1: float = 0.0          # (0, 0): the full frame width
    rows: tuple = ()         # a splittable table's row heights: it breaks only between rows
    repeat: int = 0          # header rows repeated on every later piece
    pre: float = 0.0         # height above the table's first row (caption, space before)
    post: float = 0.0        # space after the table
    lead: float = 0.0        # space above and below the content: the frame spends it,
    trail: float = 0.0       # but the renderer's regions do not cover it
    skip: float = 0.0        # space before the first flowable, which a frame drops at its top


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


def _flowable_height(f, canv, width: float, avail: float, spacing: bool = True) -> float:
    from reportlab.platypus.doctemplate import ActionFlowable
    from reportlab.platypus.flowables import UseUpSpace
    if isinstance(f, (ActionFlowable, UseUpSpace)):
        return 0.0          # page breaks / template switches occupy no content height
    w, h = f.wrapOn(canv, width, avail)
    if isinstance(f, KeepTogether) or h >= 0xfffff:
        h = sum(_flowable_height(c, canv, width, avail, spacing) for c in f._content)
        return h
    return h + (f.getSpaceBefore() + f.getSpaceAfter() if spacing else 0.0)


def _outer_space(flows) -> Tuple[float, float]:
    """Space before the first and after the last flowable that takes room. A frame drops the
    first at a page top, and the last need not fit at a page foot."""
    from reportlab.platypus.doctemplate import ActionFlowable
    from reportlab.platypus.flowables import UseUpSpace
    real = [f for f in flows if not isinstance(f, (ActionFlowable, UseUpSpace))]
    if not real:
        return 0.0, 0.0
    first, last = real[0], real[-1]
    before = _outer_space(first._content)[0] if isinstance(first, KeepTogether) else first.getSpaceBefore()
    after = _outer_space(last._content)[1] if isinstance(last, KeepTogether) else last.getSpaceAfter()
    return before, after


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
    from ..layout.factory import FRAME_PADDING, RenderContext, create_flowables
    from ..policy import DiagnosticCollector, RenderPolicy
    from .geometry import content_extent

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
            # the frame sets them inside its padding: build and measure there, as the engine does (F6)
            width, avail = width - 2 * FRAME_PADDING, avail - 2 * FRAME_PADDING
            ctx.available_width = width
            flows = create_flowables(b, theme, ctx) or []
            role_of = _role_for(b)
            heights = [_flowable_height(f, canv, width, avail) for f in flows]
            total = sum(heights)
            ink = sum(_flowable_height(f, canv, width, avail, False) for f in flows
                      if type(f).__name__ not in ("Spacer", "CondPageBreak"))
            before, after = _outer_space(flows)
            roles = [role_of(f) for f in flows]
            # the width the content really covers, as the renderer records it (F6)
            spans = [content_extent(f, 0.0, width) for f, r in zip(flows, roles) if r != "space"]
            x0, x1 = (min(a for a, _ in spans), max(b for _, b in spans)) if spans else (0.0, 0.0)
            content = [k for k, r in enumerate(roles) if r != "space"]
            lead = trail = skip = 0.0
            if content:
                lead = sum(heights[:content[0]]) + flows[content[0]].getSpaceBefore()
                trail = sum(heights[content[-1] + 1:]) + flows[content[-1]].getSpaceAfter()
                skip = flows[0].getSpaceBefore()
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
            rows, repeat, pre, post = (), 0, 0.0, 0.0
            if flows and b.type not in ("heading",):
                big = flows[-1]
                if isinstance(big, Table) and getattr(big, "_rowHeights", None) and getattr(big, "splitByRow", 1):
                    rows, repeat = tuple(big._rowHeights), int(getattr(big, "repeatRows", 0) or 0)
                    pre, post = sum(heights[:-1]) + big.getSpaceBefore(), big.getSpaceAfter()
                s, p = _min_piece(big, canv, width, heights[-1])
                if s:
                    splittable, piece = True, sum(heights[:-1]) + p
                else:
                    rows = ()
            keep = any(getattr(f, "keepWithNext", 0) for f in flows[:1]) or b.type == "heading"
            # a block is one item in the simulation: its role is that of its main
            # flowable (a caption travels with its table/figure via keep-with-next)
            main_role = next((r for r in roles if r not in ("caption", "other", "structure", "space")),
                             next((r for r in roles if r != "space"), "space"))
            out.append(BlockMeasure(i, b.type, main_role, total, piece, splittable,
                                    bool(keep), level, is_land,
                                    bool((b.hints or {}).get("break_before") or (b.hints or {}).get("page_start")),
                                    tail_h, ink, before, max(0.0, total - before - after), after, x0, x1,
                                    rows, repeat, pre, post, lead, trail, skip))
    finally:
        _policy.deactivate(token)
    return out, fg


def _span(m: BlockMeasure, fg: FrameGeometry, landscape: bool) -> Tuple[float, float]:
    """Where a block's content sits across the frame (its measured extent, or the full width)."""
    left = fg.left + FRAME_PADDING
    if m.x1 > m.x0:
        return left + m.x0, left + m.x1
    return left, left + (fg.land_width if landscape else fg.width) - 2 * FRAME_PADDING


def _row_piece(m: BlockMeasure, start: int, room: float):
    """(height, next row) of the piece of a table that fits in ``room``. A table breaks only
    between rows, the first piece holds at least one row below the header, and every later
    piece repeats the header. None when no such piece fits."""
    rows = m.rows
    base = m.pre if start == 0 else sum(rows[:m.repeat])
    k = start
    while k < len(rows) and base + rows[k] <= room + 0.5:
        base += rows[k]
        k += 1
    if k <= (m.repeat if start == 0 else start):
        return None
    return base, k


def simulate(measures: List[BlockMeasure], fg: FrameGeometry) -> Geometry:
    """Greedy pagination with keep-with-next groups and split points.

    Produces predicted Regions (same shape as the renderer's records)."""
    geo = Geometry()
    page = 1
    land = False

    def frame_h():          # the height inside the frame's padding, as the renderer fills it
        return (fg.land_height if land else fg.height) - 2 * FRAME_PADDING

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
        top_of = lambda u: fg.bottom + FRAME_PADDING + H - u   # noqa: E731

        def place(mm, start, end, first=True, last=True, role=None):
            """A region as the renderer records it: content only, without the block's outer spaces."""
            lo = start + (mm.lead if first else 0.0)
            hi = end - (mm.trail if last else 0.0)
            if hi - lo < 0.5:
                lo, hi = start, end
            geo.regions.append(Region(page, "sim", top_of(lo), top_of(hi), *_span(mm, fg, land), mm.index,
                                      role or mm.role, mm.level))

        for k in range(i, j):          # the kept headings
            mk = measures[k]
            used -= mk.skip if used == 0 else 0.0     # a frame drops the space before at its top
            place(mk, used, used + mk.height, role="heading")
            used += mk.height
        mj = measures[j]
        remaining = mj.height
        row_at = 0
        used -= mj.skip if used == 0 else 0.0
        while remaining > 0:
            first = remaining == mj.height and row_at == 0
            H = frame_h()
            room = H - used
            if remaining <= room + 0.5 and _tail_moves(mj, j, used, remaining, H):
                # keep-tail intro: its last lines move on with the block it introduces
                head = remaining - mj.tail
                if head > 0.5:
                    place(mj, used, used + head, first, last=False)
                page += 1
                used = 0.0
                open_page(page, land)
                remaining = min(remaining, mj.tail)
                continue
            if remaining <= room + 0.5:
                place(mj, used, used + remaining, first)
                used += remaining
                remaining = 0
            elif mj.rows and room >= min(mj.min_piece, remaining) and _row_piece(mj, row_at, room):
                cut, row_at = _row_piece(mj, row_at, room)
                place(mj, used, used + cut, first, last=False)
                remaining = sum(mj.rows[:mj.repeat]) + sum(mj.rows[row_at:]) + mj.post
                page += 1
                used = 0.0
                open_page(page, land)
            elif mj.rows and used > 0 and room >= min(mj.min_piece, remaining):
                page += 1                # not one row fits beside what is here
                used = 0.0
                open_page(page, land)
            elif mj.splittable and room >= min(mj.min_piece, remaining):
                place(mj, used, H, first, last=False)
                remaining -= room
                page += 1
                used = 0.0
                open_page(page, land)
            elif used <= 0:            # taller than a page and unsplittable: clipped in reality
                place(mj, 0.0, min(remaining, H), first)
                used = min(remaining, H)
                remaining = 0
            else:
                page += 1
                used = 0.0
                open_page(page, land)
                used -= mj.skip if first else 0.0
        if mj.type in FORCED_BREAK_AFTER:
            forced_next = True
        i = j + 1
    return geo


def block_types(doc) -> Dict[int, str]:
    return {i: b.type for i, b in enumerate(doc.blocks)}
