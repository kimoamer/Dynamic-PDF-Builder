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

WEIGHTS = {"utilization": 0.22, "balance": 0.12, "efficiency": 0.20, "readability": 0.20,
           "typography": 0.10, "placement": 0.10, "tables": 0.06}
MIN_BODY_PT = 9.0
MIN_TABLE_PT = 7.5
MIN_LEADING = 1.25


class PageMetric(BaseModel):
    page: int
    occupancy: float           # occupied region height / frame height
    intentional: bool          # short by design (forced break follows, last page…)
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
        if r.block is not None and r.block < last:
            errors.append(f"reading order broken at block {r.block} (after {last})")
            break
        last = max(last, r.block if r.block is not None else last)

    by_page: Dict[int, list] = {}
    for r in regs:
        by_page.setdefault(r.page, []).append(r)
    forced = forced_starts(doc)
    types = {i: b.type for i, b in enumerate(doc.blocks)}

    # ── per-page geometry ──
    page_metrics: List[PageMetric] = []
    occs, wasted_total = [], 0.0
    for idx, p in enumerate(pages):
        info = geo.pages[p]
        rs = by_page.get(p, [])
        occ = min(1.0, sum(r.height for r in rs) / max(1.0, info.frame_height))
        for r in rs:
            if r.bottom < info.frame_bottom - 1.5 or r.top > info.frame_top + 1.5:
                errors.append(f"region of block {r.block} clipped on page {p}")
        nxt = by_page.get(pages[idx + 1], []) if idx + 1 < len(pages) else []
        first_next = nxt[0] if nxt else None
        is_last = idx == len(pages) - 1
        intentional = (is_last or first_next is None or first_next.block in forced
                       or any(types.get(r.block) in FORCED_BREAK_AFTER for r in rs)
                       or (first_next.role == "heading" and first_next.level <= 1
                           and first_next.block is not None and first_next.block in forced)
                       or geo.pages[pages[idx + 1]].landscape != info.landscape)
        wasted = 0.0 if intentional else max(0.0, 0.62 - occ)
        wasted_total += wasted
        page_metrics.append(PageMetric(page=p, occupancy=round(occ, 3), intentional=intentional,
                                       wasted=round(wasted, 3)))
        if not intentional:
            occs.append(occ)
        # hard: stranded heading / detached caption at the bottom of a non-final page
        if rs and not is_last:
            tail = rs[-1]
            cont = [r for r in nxt if r.block == tail.block]
            if tail.role == "heading" and not cont:
                errors.append(f"heading (block {tail.block}) stranded at bottom of page {p}")
            if tail.role == "caption" and cont:
                errors.append(f"caption of block {tail.block} detached on page {p}")

    # ── soft metrics ──
    utilization = statistics.mean(occs) if occs else 1.0
    balance = 1.0 - min(1.0, statistics.pstdev(occs) * 2) if len(occs) > 1 else 1.0
    frame_h = statistics.mean(geo.pages[p].frame_height for p in pages)
    # lower bound on pages: content between forced starts packed perfectly
    segments: Dict[int, float] = {}
    seg = 0
    for r in regs:
        if r.block in forced and r.block is not None:
            seg = max(seg, r.block)
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
    raw = sum(WEIGHTS[k] * metrics[k] for k in WEIGHTS)
    score = round(100 * raw - 25 * wasted_total, 2)
    errors = list(dict.fromkeys(errors))
    return LayoutScore(valid=not errors, score=score, hard_errors=errors, metrics=metrics,
                       pages=page_metrics)
