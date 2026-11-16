"""
Deterministic layout scoring from page geometry.

Hard constraints (any violation ⇒ candidate invalid, never selected):
lost content, broken reading order, stranded headings, detached captions,
clipped regions, unreadable typography.

Soft metrics (0..1, higher is better) are combined with fixed weights:
region utilization, whitespace balance, pagination efficiency, readability,
typography consistency, figure/table placement — minus penalties for
accidental wasted space. Intentional whitespace (after a page break, cover,
table of contents, before a new top-level section, around an orientation
change, and the final page) is never penalized.
"""
from __future__ import annotations

import math
import statistics
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from .analysis import FORCED_BREAK_AFTER, NO_CONTENT
from .geometry import Geometry
from .objective import WEIGHTS as OBJECTIVE_WEIGHTS, layout_score

WEIGHTS = OBJECTIVE_WEIGHTS["layout"]     # the layout part of the one objective
MIN_BODY_PT = 9.0
MIN_TABLE_PT = 7.5
MIN_LEADING = 1.25
DENSE_CAP = 0.85               # area occupancy above this earns no extra utilization


class PageMetric(BaseModel):
    page: int
    occupancy: float           # union area of content rectangles / frame area
    fill: float = 0.0          # union of occupied vertical intervals / frame height
    role: str = "body"         # cover | toc | body | section_end | final
    intentional: bool          # short by design (not a body page)
    wasted: float              # accidental unused share (0 when intentional)


class LayoutScore(BaseModel):
    valid: bool
    score: float
    hard_errors: List[str] = Field(default_factory=list)
    metrics: Dict[str, float] = Field(default_factory=dict)
    pages: List[PageMetric] = Field(default_factory=list)


def readability(theme, width: Optional[float] = None) -> Dict[str, float]:
    from ..design.measure import chars_per_line
    from ..design.tokens import heading_size
    ty, sp = theme.typography, theme.spacing
    width = width or (595.28 - sp.page_margin_left - sp.page_margin_right)
    cpl = chars_per_line(width, ty.body_family, ty.base_size)
    # comfortable measure 55–90 cpl; size ≥ 10pt ideal; leading 1.35–1.65 ideal
    measure = 1.0 if 55 <= cpl <= 90 else max(0.0, 1 - min(abs(cpl - 55), abs(cpl - 90)) / 40)
    size = min(1.0, max(0.0, (ty.base_size - 8.0) / 2.0))
    lead = 1.0 if 1.35 <= ty.line_height <= 1.65 else max(0.0, 1 - min(abs(ty.line_height - 1.35),
                                                                      abs(ty.line_height - 1.65)) / 0.3)
    hs = [heading_size(theme, lv) for lv in (1, 2, 3)]
    ramp = 1.0 if hs[0] > hs[1] > hs[2] >= ty.base_size else 0.5
    return {"cpl": round(cpl, 1), "measure": round(measure, 3), "size": round(size, 3),
            "leading": round(lead, 3), "ramp": ramp}


def hard_typography_errors(theme, doc) -> List[str]:
    ty = theme.typography
    errs = []
    if ty.base_size < MIN_BODY_PT:
        errs.append(f"body text {ty.base_size}pt below {MIN_BODY_PT}pt")
    if ty.line_height < MIN_LEADING:
        errs.append(f"line height {ty.line_height} below {MIN_LEADING}")
    for b in doc.blocks:
        fs = (b.hints or {}).get("font_size")
        if b.type == "table" and fs and fs < MIN_TABLE_PT:
            errs.append(f"table text {fs}pt below {MIN_TABLE_PT}pt")
    return errs


def forced_starts(doc) -> set:
    """Block indices that start a new page by the author's structure
    (page breaks, cover, TOC, orientation changes)."""
    out = set()
    prev_land = False
    for i, b in enumerate(doc.blocks):
        if i > 0 and doc.blocks[i - 1].type in FORCED_BREAK_AFTER:
            out.add(i)
        land = bool((b.hints or {}).get("landscape"))
        if land != prev_land:
            out.add(i)
        prev_land = land
        # layout-added breaks (composer/QA hints) are *not* intentional: they
        # must earn their whitespace through the score like any other choice
    return out


def score_layout(geo: Geometry, doc, theme, *, typography_errors: Optional[List[str]] = None) -> LayoutScore:
    errors: List[str] = list(typography_errors if typography_errors is not None
                             else hard_typography_errors(theme, doc))
    regs = sorted(geo.regions, key=lambda r: (r.page, -r.top))
    pages = sorted(geo.pages)
    if not regs:
        return LayoutScore(valid=False, score=0.0, hard_errors=["no content rendered"])

    # ── content preservation & reading order ──
    seen = {r.block for r in regs}
    for extra in (getattr(r, "extra_blocks", ()) for r in regs):
        seen.update(extra or ())
    for i, b in enumerate(doc.blocks):
        if b.type not in NO_CONTENT and i not in seen:
            errors.append(f"block {i} ({b.type}) not placed")
    last = -1
    for r in regs:
        if r.in_float:
            continue
        if r.block is not None and r.block < last:
            errors.append(f"reading order broken at block {r.block} (after {last})")
            break
        last = max(last, r.block if r.block is not None else last)

    by_page: Dict[int, list] = {}
    for r in regs:
        by_page.setdefault(r.page, []).append(r)
    forced = forced_starts(doc)
    types = {i: b.type for i, b in enumerate(doc.blocks)}

    # ── per-page geometry (role-aware) ──
    from .geometry import union_area, union_length
    page_metrics: List[PageMetric] = []
    util_pages, fills, wasted_total = [], [], 0.0
    content_pages = []
    for idx, p in enumerate(pages):
        info = geo.pages[p]
        rs = by_page.get(p, [])
        for r in rs:
            if r.bottom < info.frame_bottom - 1.5 or r.top > info.frame_top + 1.5:
                errors.append(f"region of block {r.block} clipped on page {p}")
        dense = [r for r in rs if r.role not in ("space", "decorative")]
        # vertical fill: union of occupied y-intervals (no double counting)
        fill = min(1.0, union_length([(r.bottom, r.top) for r in dense]) / max(1.0, info.frame_height))
        # area occupancy: union of real content rectangles over the frame area
        frame_area = max(1.0, info.frame_height * info.frame_width)
        occ = min(1.0, union_area([(r.x0, r.x1, r.bottom, r.top) for r in dense]) / frame_area)
        kinds = {types.get(r.block) for r in dense}
        nxt = by_page.get(pages[idx + 1], []) if idx + 1 < len(pages) else []
        first_next = nxt[0] if nxt else None
        is_last = idx == len(pages) - 1
        if "cover_page" in kinds and kinds <= {"cover_page", "watermark", None}:
            role = "cover"
        elif "table_of_contents" in kinds and kinds <= {"table_of_contents", "page_break", None}:
            role = "toc"
        elif is_last:
            role = "final"
        elif (first_next is None or first_next.block in forced
              or any(types.get(r.block) in FORCED_BREAK_AFTER for r in rs)
              or geo.pages[pages[idx + 1]].landscape != info.landscape):
            role = "section_end"      # the author's structure ends this page early
        else:
            role = "body"
        wasted = 0.0
        if role == "body":
            wasted = max(0.0, 0.62 - fill)
            util_pages.append(occ)
            fills.append(fill)
        elif role == "final" and len(pages) > 1 and fill < 0.15:
            # a spill page holding only a few lines: partly accidental
            wasted = 0.15 - fill
        if role in ("final", "section_end", "body"):
            content_pages.append(occ)
        wasted_total += wasted
        page_metrics.append(PageMetric(page=p, occupancy=round(occ, 3), fill=round(fill, 3), role=role,
                                       intentional=role != "body", wasted=round(wasted, 3)))
        # hard: stranded heading / detached caption at the bottom of a non-final page
        if rs and not is_last:
            tail = [r for r in rs if r.role not in ("space", "decorative")][-1:] or rs[-1:]
            tail = tail[0]
            cont = [r for r in nxt if r.block == tail.block]
            whole_page = types.get(tail.block) in ("section_opener", "performance_page")
            if tail.role == "heading" and not cont and not whole_page:
                errors.append(f"heading (block {tail.block}) stranded at bottom of page {p}")
            if tail.role == "caption" and cont:
                errors.append(f"caption of block {tail.block} detached on page {p}")

    # ── soft metrics ──
    # Utilization counts body pages; a document without body pages (single page,
    # or cover + TOC + one page) is judged on its content pages — never a free 1.0.
    # Density beyond DENSE_CAP earns nothing: cramming is not rewarded.
    basis = util_pages or content_pages
    utilization = (statistics.mean(min(o, DENSE_CAP) for o in basis) / DENSE_CAP) if basis else 0.0
    balance = 1.0 - min(1.0, statistics.pstdev(fills) * 2) if len(fills) > 1 else 1.0
    frame_h = statistics.mean(geo.pages[p].frame_height for p in pages)
    # lower bound on pages: content between forced starts packed perfectly
    segments: Dict[int, float] = {}
    seg = 0
    for r in regs:
        if r.block in forced and r.block is not None:
            seg = max(seg, r.block)
        if r.role != "space":
            segments[seg] = segments.get(seg, 0.0) + r.height
    lower = sum(max(1, math.ceil(h / frame_h - 0.02)) for h in segments.values())
    efficiency = min(1.0, lower / len(pages))
    portrait = [geo.pages[p].frame_width for p in pages if not geo.pages[p].landscape]
    read = readability(theme, portrait[0] if portrait else None)
    readability_score = (read["measure"] + read["size"] + read["leading"]) / 3
    typography = read["ramp"]
    big_fig = [r for r in regs if r.role == "figure" and r.height > 0.8 * frame_h]
    # a figure/table whose heading or intro paragraph was left on the previous page
    first_page, last_page = {}, {}
    for r in regs:
        if r.block is None:
            continue
        first_page.setdefault(r.block, r.page)
        last_page[r.block] = r.page
    separated = 0
    for i, b in enumerate(doc.blocks):
        if b.type in ("image", "chart", "diagram", "mermaid", "table") and i > 0 and i in first_page:
            prev = doc.blocks[i - 1]
            if prev.type in ("paragraph", "heading") and last_page.get(i - 1, first_page[i]) < first_page[i] \
                    and i not in forced:
                separated += 1
    placement = 1.0 - min(1.0, 0.25 * len(big_fig) + 0.15 * separated)
    table_pieces = [r for r in regs if r.role == "table"]
    tiny = 0
    for k, r in enumerate(table_pieces):
        later = [t for t in table_pieces[k + 1:] if t.block == r.block]
        if later and r.height < 40:     # a table header + ≤1 row stranded on a page
            tiny += 1
    tables = 1.0 - min(1.0, 0.3 * tiny)
    metrics = {"utilization": round(utilization, 3), "balance": round(balance, 3),
               "efficiency": round(efficiency, 3), "readability": round(readability_score, 3),
               "typography": typography, "placement": round(placement, 3), "tables": round(tables, 3),
               "wasted": round(wasted_total, 3), "pages": float(len(pages)), "cpl": read["cpl"],
               "separated_figures": float(separated)}
    score = layout_score(metrics, wasted_total)
    errors = list(dict.fromkeys(errors))
    return LayoutScore(valid=not errors, score=score, hard_errors=errors, metrics=metrics,
                       pages=page_metrics)
