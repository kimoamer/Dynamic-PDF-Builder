"""
Layout candidates: bounded, renderer-compatible variations of the designed
layout. Each candidate is a deterministic transform of (document, theme) —
theme rhythm/geometry plus block layout hints. Content, order and semantics
are never touched; only spacing, measure, grouping and break policy change.

* balanced   — the designed layout with section-aware breaks and figures
               allowed to shrink (≤ 20 %) instead of jumping to the next page.
* compact    — tighter vertical rhythm and margins (within readability
               limits), short list items set in two columns.
* editorial  — generous measure and rhythm; long top-level sections open on
               a new page.
* data       — wider text block for tables/charts, denser tables, figures
               allowed to shrink, short lists in two columns.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

from pydantic import BaseModel, Field

from ..core.inline import plain_text
from ..design.measure import chars_per_line
from .analysis import BlockMeasure


class Candidate(BaseModel):
    name: str
    reason: str
    changes: List[str] = Field(default_factory=list)

    model_config = {"arbitrary_types_allowed": True}


def _scale_rhythm(theme, k: float):
    sp = theme.spacing
    sp.paragraph_spacing_after = round(sp.paragraph_spacing_after * k, 1)
    sp.block_gap = round(sp.block_gap * k, 1)
    sp.heading_spacing_before = [round(v * k, 1) for v in sp.heading_spacing_before]
    sp.heading_spacing_after = [round(v * k, 1) for v in sp.heading_spacing_after]


def _set_measure(theme, page_w: float, lo: float, hi: float) -> str:
    """Adjust side margins so body lines hold lo..hi characters (bounded)."""
    sp, ty = theme.spacing, theme.typography
    width = page_w - sp.page_margin_left - sp.page_margin_right
    cpl = chars_per_line(width, ty.body_family, ty.base_size)
    target = min(max(cpl, lo), hi)
    if abs(target - cpl) < 1:
        return f"measure kept at {cpl:.0f} cpl"
    new_w = width * target / cpl
    side = max(42.0, min(110.0, (page_w - new_w) / 2))
    sp.page_margin_left = sp.page_margin_right = round(side, 1)
    return f"measure {cpl:.0f}→{target:.0f} cpl (side margins {side:.0f}pt)"


def _short_list(block) -> bool:
    items = getattr(block, "items", None) or []
    if len(items) < 8:
        return False
    for it in items:
        txt = it if isinstance(it, str) else it.text
        if (not isinstance(it, str) and it.children) or len(plain_text(txt)) > 38:
            return False
    return True


class CandidateInvalid(ValueError):
    """The transform would break a hard constraint (e.g. a table no longer fits)."""


def _refit_tables(doc, theme, base_theme, page_w: float) -> List[str]:
    """Re-plan table columns for the candidate's own text width so no header or
    word is broken mid-word by columns sized for a different width."""
    from ..design.measure import column_metrics, fit_columns, wrap_ratio
    from .analysis import _PAGE
    from ..schema.enums import PageSize
    sp, sp0 = theme.spacing, base_theme.spacing
    if (sp.page_margin_left, sp.page_margin_right) == (sp0.page_margin_left, sp0.page_margin_right):
        return []
    page_h = max(_PAGE.get(doc.meta.page_size, _PAGE[PageSize.A4]))
    out = []
    for i, b in enumerate(doc.blocks):
        h = dict(b.hints or {})
        if b.type != "table" or b.column_widths or "col_fractions" not in h:
            continue
        width = (page_h if h.get("landscape") else page_w) - sp.page_margin_left - sp.page_margin_right
        size = h.get("font_size", theme.typography.base_size - 1)
        mins, nats = column_metrics(b.headers or [], b.rows, theme.typography.body_family, size,
                                    2 * h.get("cell_padding", 6))
        fr, fits = fit_columns(mins, nats, width)
        if not fits or wrap_ratio(nats, fr, width) > 2.2:
            raise CandidateInvalid(f"table {i} does not fit the candidate's {width:.0f}pt text width")
        h["col_fractions"] = [round(f, 4) for f in fr]
        b.hints = h
        out.append(i)
    return [f"{len(out)} table(s) re-fitted to the new text width"] if out else []


def _hint(block, **kw):
    block.hints = {**(block.hints or {}), **kw}


def apply(name: str, doc, theme, page_w: float, measures: List[BlockMeasure]) -> Tuple[object, object, List[str]]:
    """Return (doc', theme', changes) for candidate ``name``."""
    d = doc.model_copy(deep=True)
    t = theme.model_copy(deep=True)
    changes: List[str] = []
    ty = t.typography

    def figures(min_scale: float):
        n = 0
        for b in d.blocks:
            if b.type in ("image", "chart", "diagram"):
                _hint(b, shrink_to_fit=min_scale)
                n += 1
        if n:
            changes.append(f"{n} figure(s) may shrink to {min_scale:.0%} to fill the page")

    def section_breaks(min_space: float):
        n = 0
        for b in d.blocks:
            if b.type == "heading" and b.level <= 1:
                _hint(b, min_space_before=min_space)
                n += 1
        if n:
            changes.append(f"top-level headings start a new page when < {min_space:.0%} of it remains")

    def list_columns():
        n = 0
        for b in d.blocks:
            if b.type in ("bullet_list", "numbered_list", "checklist") and _short_list(b):
                _hint(b, columns=2)
                n += 1
        if n:
            changes.append(f"{n} list(s) of short items set in two columns")

    def group_intros():
        """Keep a section's short intro with the figure/table it introduces."""
        n = 0
        blocks = d.blocks
        for i, b in enumerate(blocks):
            if b.type not in ("image", "chart", "diagram", "mermaid", "table"):
                continue
            j, chars = i - 1, 0
            while j >= 0 and blocks[j].type == "paragraph" and chars < 400 and i - j <= 2:
                chars += len(plain_text(blocks[j].text))
                j -= 1
            intro = list(range(j + 1, i))
            ends_colon = intro and plain_text(blocks[intro[-1]].text).rstrip().endswith(":")
            if intro and chars < 400 and (j >= 0 and blocks[j].type == "heading" or ends_colon):
                for k in intro:
                    _hint(blocks[k], keep_with_next=True)
                n += 1
        if n:
            changes.append(f"{n} section intro(s) kept with the figure/table they introduce")

    def compact_charts():
        """Chart-heavy documents: re-draw charts natively at a size that lets a
        heading + intro + chart appear twice per page. Text in the chart keeps
        its point size; never below 2.6 in tall or the chart's own size."""
        charts = [b for b in d.blocks if b.type == "chart"]
        if len(charts) < 2:
            return
        from .analysis import frame_geometry
        fg = frame_geometry(d, t)
        target_h = max(2.6, min(4.0, (fg.height / 2 - 110) / 72))
        max_w = fg.width / 72
        n = 0
        for b in charts:
            if b.height > target_h + 0.05 or b.width > max_w:
                square = b.chart_type in ("pie", "donut", "gauge")
                h = min(b.height, target_h)
                w = min(b.width, max_w, h * 1.25 if square else max_w)
                _hint(b, figure_size=[round(w, 2), round(h, 2)])
                n += 1
        if n:
            changes.append(f"{n} chart(s) re-drawn at {target_h:.1f} in tall (native text size kept)")

    group_intros()
    if name in ("balanced", "data", "compact"):
        compact_charts()
    if name == "balanced":
        changes.append(_set_measure(t, page_w, 55, 85))
        section_breaks(0.18)
        figures(0.8)
    elif name == "compact":
        _scale_rhythm(t, 0.8)
        sp = t.spacing
        sp.page_margin_top = max(48.0, round(sp.page_margin_top * 0.85, 1))
        sp.page_margin_bottom = max(48.0, round(sp.page_margin_bottom * 0.85, 1))
        ty.line_height = max(1.35, round(ty.line_height - 0.06, 2))
        changes.append("vertical rhythm ×0.8, top/bottom margins ×0.85, leading −0.06 (≥1.35)")
        changes.append(_set_measure(t, page_w, 60, 92))
        list_columns()
        figures(0.75)
    elif name == "editorial":
        _scale_rhythm(t, 1.12)
        ty.line_height = min(1.65, round(ty.line_height + 0.05, 2))
        changes.append("vertical rhythm ×1.12, leading +0.05 (≤1.65)")
        changes.append(_set_measure(t, page_w, 55, 72))
        # long top-level sections open on a fresh page
        heights: Dict[int, float] = {}
        cur = None
        for m in measures:
            if m.type == "heading" and m.level <= 1:
                cur = m.index
                heights[cur] = 0.0
            elif cur is not None:
                heights[cur] += m.height
        long_sections = [i for i, h in heights.items() if h > 420]
        if len(long_sections) >= 2:
            for i in long_sections[1:]:
                _hint(d.blocks[i], break_before=True)
            changes.append(f"{len(long_sections) - 1} long section(s) open on a new page")
        else:
            section_breaks(0.25)
    elif name == "data":
        sp = t.spacing
        sp.page_margin_left = sp.page_margin_right = max(46.0, min(sp.page_margin_left, 54.0))
        _scale_rhythm(t, 0.9)
        changes.append("side margins ≤54pt for tables and charts, rhythm ×0.9")
        list_columns()
        figures(0.75)
    else:
        raise ValueError(f"unknown candidate {name!r}")
    changes += _refit_tables(d, t, theme, page_w)
    return d, t, [c for c in changes if c]


def choose(sem_stats, profile: str, est_pages: float, max_candidates: int = 4) -> List[Candidate]:
    """Pick candidates from document structure and purpose (deterministic)."""
    out = [Candidate(name="balanced", reason="baseline-preserving refinement for every document")]
    data_heavy = (sem_stats.tables >= 2 or sem_stats.table_rows >= 30 or sem_stats.charts >= 2
                  or profile in ("data_report", "financial_report", "invoice"))
    prose_led = (profile in ("proposal", "academic_report", "letter", "executive_report", "general")
                 and sem_stats.words >= 400 and not data_heavy)
    if data_heavy:
        out.append(Candidate(name="data", reason=f"{sem_stats.tables} tables / {sem_stats.table_rows} rows / "
                                                f"{sem_stats.charts} charts"))
    if est_pages > 1.0:
        out.append(Candidate(name="compact", reason=f"~{est_pages:.1f} pages: test whether a tighter "
                                                    "rhythm removes partial pages"))
    if prose_led or (est_pages >= 6 and sem_stats.headings >= 6):
        out.append(Candidate(name="editorial", reason="prose-led or long, sectioned document"))
    return out[:max_candidates]
