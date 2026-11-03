"""
Adaptive layout planner — content-aware decisions a careful designer makes.

The planner reads the SemanticDocument and the chosen DesignPlan and records
*layout* decisions as block ``hints`` and theme adjustments. It never edits,
reorders or drops author content. Every decision is logged for
``design_explain()``.

Decisions
---------
* Measure: keep prose lines near 60–80 characters by widening margins on
  prose-led documents (not when wide tables need the room).
* Hierarchy: gentler heading ramp for deep outlines, bolder for shallow ones.
* Tables: content-measured column widths; numeric columns right-aligned;
  font stepped down (never below ``MIN_TABLE_SIZE``) when columns don't fit;
  landscape pages for tables that still don't fit; short tables kept whole.
* Lead paragraph: the opening paragraph of reports/proposals is set larger.
* Cover: long reports/proposals with a title but no cover get one built
  from metadata only (title, subtitle/description, author, date).
"""
from __future__ import annotations

import re
from typing import List, Optional

from pydantic import BaseModel, Field

from ..core.inline import plain_text
from ..core.normalize import SemanticDocument
from ..schema.blocks import CoverPageBlock
from ..schema.enums import Orientation, PageSize
from . import DesignPlan
from .measure import chars_per_line, column_metrics, fit_columns, wrap_ratio
from .profile import Profile

MIN_TABLE_SIZE = 7.5
_PAGE = {PageSize.A4: (595.28, 841.89), PageSize.LETTER: (612, 792), PageSize.LEGAL: (612, 1008)}
_NUMERIC = re.compile(r"^[\s$€£¥%+\-−(),.\d٠-٩]+$")
_PROSE_PROFILES = {Profile.PROPOSAL, Profile.ACADEMIC_REPORT, Profile.LETTER,
                   Profile.CORPORATE_MEMO, Profile.EXECUTIVE_REPORT, Profile.GENERAL}
_LEAD_PROFILES = {Profile.EXECUTIVE_REPORT, Profile.PROPOSAL}
_COVER_PROFILES = {Profile.EXECUTIVE_REPORT, Profile.PROPOSAL, Profile.FINANCIAL_REPORT,
                   Profile.DATA_REPORT, Profile.TECHNICAL_MANUAL}


class LayoutDecision(BaseModel):
    target: str
    decision: str


class LayoutPlan(BaseModel):
    decisions: List[LayoutDecision] = Field(default_factory=list)
    estimated_pages: float = 0.0
    measured_pages: Optional[int] = None
    trial_renders: int = 0          # PDF renders spent by fit_pages

    def log(self, target: str, decision: str):
        self.decisions.append(LayoutDecision(target=target, decision=decision))


def _content_width(sem: SemanticDocument, theme) -> float:
    w, h = _PAGE.get(sem.meta.page_size, _PAGE[PageSize.A4])
    if sem.meta.orientation == Orientation.LANDSCAPE:
        w, h = h, w
    sp = theme.spacing
    return w - sp.page_margin_left - sp.page_margin_right


def _estimate_pages(sem: SemanticDocument, theme, width: float) -> float:
    ty = theme.typography
    cpl = max(20.0, chars_per_line(width, ty.body_family, ty.base_size))
    lines = 0.0
    for b in sem.blocks:
        t = b.type
        if t in ("paragraph", "rich_text", "note", "quote", "callout"):
            lines += len(plain_text(getattr(b, "text", ""))) / cpl + 1.2
        elif t == "heading":
            lines += 3
        elif t in ("bullet_list", "numbered_list", "checklist"):
            lines += 1.4 * len(b.items) + 1
        elif t == "table":
            lines += 1.6 * (len(b.rows) + 1) + 2
        elif t == "code":
            lines += 0.8 * (b.code.count("\n") + 1) + 2
        elif t in ("chart", "diagram", "image", "mermaid"):
            lines += 16
        elif t in ("page_break", "cover_page", "table_of_contents"):
            lines += 45
        else:
            lines += 3
    w, h = _PAGE.get(sem.meta.page_size, _PAGE[PageSize.A4])
    usable = h - theme.spacing.page_margin_top - theme.spacing.page_margin_bottom - 60
    lines_per_page = usable / (ty.base_size * ty.line_height)
    return round(lines / max(1.0, lines_per_page), 2)


def plan_layout(sem: SemanticDocument, plan: DesignPlan) -> LayoutPlan:
    """Mutates ``sem`` blocks' hints and ``plan.theme``; returns logged decisions."""
    lp = LayoutPlan()
    theme = plan.theme
    ty, sp = theme.typography, theme.spacing
    profile = plan.decision.profile
    st = sem.stats

    # ── hierarchy: heading ramp adapts to outline depth ──
    if st.max_heading_level >= 4:
        ty.heading_scale = [min(s, r) for s, r in zip(ty.heading_scale, [1.7, 1.38, 1.18, 1.06, 1.0, 0.95])]
        lp.log("headings", f"outline is {st.max_heading_level} levels deep: compressed heading ramp")
    elif 0 < st.max_heading_level <= 2 and st.headings >= 2:
        ty.heading_scale[0] = max(ty.heading_scale[0], 1.9)
        lp.log("headings", "shallow outline: stronger H1 contrast")

    # ── measure: comfortable line length for prose-led documents ──
    width = _content_width(sem, theme)
    widest_table = 0.0
    for b in sem.blocks:
        if b.type == "table":
            mins, nats = column_metrics(b.headers or [], b.rows, ty.body_family, ty.base_size - 1)
            widest_table = max(widest_table, sum(nats))
    cpl = chars_per_line(width, ty.body_family, ty.base_size)
    if profile in _PROSE_PROFILES and cpl > 92 and widest_table < width * 0.9 and sem.direction == "ltr":
        target_w = width * 88 / cpl
        extra = (width - target_w) / 2
        sp.page_margin_left += extra
        sp.page_margin_right += extra
        lp.log("measure", f"{cpl:.0f} chars/line too long for reading; margins widened by "
                          f"{extra:.0f}pt each side (≈88 chars/line)")
        width = target_w
    else:
        lp.log("measure", f"{cpl:.0f} chars/line")

    # ── tables ──
    avail = width
    for i, b in enumerate(sem.blocks):
        if b.type != "table":
            continue
        hints = dict(b.hints or {})
        ncols = max([len(b.headers or [])] + [len(r) for r in b.rows] + [1])
        numeric = []
        for ci in range(ncols):
            vals = [plain_text(str(r[ci])) for r in b.rows if ci < len(r) and str(r[ci]).strip()]
            if vals and sum(bool(_NUMERIC.match(v)) for v in vals) / len(vals) >= 0.8:
                numeric.append(ci)
        hints["numeric_cols"] = numeric
        size = ty.base_size - 1
        fits = False
        fracs: Optional[List[float]] = None
        # dense tables get tighter cell padding (pt per side), shared by PDF and DOCX
        pad = 4.0 if ncols >= 7 else (6.0 if ncols >= 5 else 9.0)
        hints["cell_padding"] = pad
        while size >= MIN_TABLE_SIZE:
            mins, nats = column_metrics(b.headers or [], b.rows, ty.body_family, size, 2 * pad)
            fracs, fits = fit_columns(mins, nats, avail)
            # "fits" also requires readable cells: on average ≤ 2.2 lines per cell
            fits = fits and wrap_ratio(nats, fracs, avail) <= 1.8 and sum(mins) <= 0.85 * avail
            if fits:
                break
            size -= 0.5
        size = max(size, MIN_TABLE_SIZE)
        if not b.column_widths:
            hints["col_fractions"] = [round(f, 4) for f in fracs]
        hints["font_size"] = size
        what = f"table {i}: {ncols} cols, {len(b.rows)} rows; {size:g}pt"
        if not fits:
            land_w = _content_width(sem, theme) + (_PAGE[sem.meta.page_size][1] - _PAGE[sem.meta.page_size][0]) \
                if sem.meta.orientation != Orientation.LANDSCAPE else avail
            mins, nats = column_metrics(b.headers or [], b.rows, ty.body_family, MIN_TABLE_SIZE, 2 * pad)
            fracs2, fits2 = fit_columns(mins, nats, land_w)
            fits2 = fits2 and wrap_ratio(nats, fracs2, land_w) <= 1.8
            if sem.meta.orientation != Orientation.LANDSCAPE and ncols >= 5:
                hints["landscape"] = True
                hints["col_fractions"] = [round(f, 4) for f in fracs2] if not b.column_widths else None
                what += "; too wide for portrait → landscape page" + ("" if fits2 else " (cells wrap)")
            else:
                what += "; cells wrap at minimum size"
        if len(b.rows) <= 12:
            hints["keep_together"] = True
            what += "; kept on one page"
        else:
            what += "; splits across pages with repeated header"
        if numeric:
            what += f"; numeric columns {numeric} right-aligned"
        b.hints = hints
        lp.log("tables", what)

    # ── lead paragraph ──
    if profile in _LEAD_PROFILES:
        for b in sem.blocks:
            if b.type == "paragraph":
                if len(plain_text(b.text)) > 60:
                    b.hints = {**(b.hints or {}), "lead": True}
                    lp.log("lead", "opening paragraph set as a lead (larger, no indent)")
                break

    lp.estimated_pages = _estimate_pages(sem, theme, width)

    # ── cover page from metadata (only for long, titled reports) ──
    if (profile in _COVER_PROFILES and not st.has_cover and sem.meta.title
            and lp.estimated_pages >= 3):
        cover = CoverPageBlock(title=sem.meta.title,
                               subtitle=sem.meta.subject or sem.meta.description,
                               author=sem.meta.author)
        sem.blocks.insert(0, cover)
        lp.log("cover", f"~{lp.estimated_pages:.1f} pages with a title: cover built from metadata")
    return lp


# ─────────────────────────── page fit ───────────────────────────

def _tighten(theme, spacing: float, margins: float, leading_cut: float):
    sp, ty = theme.spacing, theme.typography
    sp.paragraph_spacing_after = round(sp.paragraph_spacing_after * spacing, 1)
    sp.block_gap = round(sp.block_gap * spacing, 1)
    sp.heading_spacing_before = [round(v * spacing, 1) for v in sp.heading_spacing_before]
    sp.heading_spacing_after = [round(v * spacing, 1) for v in sp.heading_spacing_after]
    sp.page_margin_top = max(42.0, round(sp.page_margin_top * margins, 1))
    sp.page_margin_bottom = max(42.0, round(sp.page_margin_bottom * margins, 1))
    ty.line_height = max(1.3, round(ty.line_height - leading_cut, 2))


def fit_pages(sem: SemanticDocument, plan: DesignPlan, policy=None, max_trials: int = 2) -> None:
    """Avoid a near-empty final page by tightening vertical rhythm (bounded).

    Measures a real PDF layout; accepts a tighter rhythm only if it removes
    the trailing page. Type size, content and order never change. Logs the
    outcome in the layout plan.
    """
    import io
    import warnings
    from ..layout.engine import LayoutEngine
    from .tokens import compile_tokens

    def trial(theme):
        if plan.layout is not None:
            plan.layout.trial_renders += 1
        eng = LayoutEngine(sem.to_document(), policy=policy, theme=theme)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            eng.render(io.BytesIO())
        return eng.page_count, eng.last_page_fill

    pages, fill = trial(plan.theme)
    lp = plan.layout
    if lp is not None:
        lp.measured_pages = pages
    # long documents: only a near-empty final page is worth fixing; short ones
    # (≤ 3 pages) are also tried because slack often sits before a kept group
    if pages < 2 or pages > 12 or fill is None or (fill > 0.3 and pages > 3):
        return
    for i, (s, m, lh) in enumerate([(0.8, 0.9, 0.05), (0.65, 0.8, 0.12)][:max_trials]):
        t = plan.theme.model_copy(deep=True)
        _tighten(t, s, m, lh)
        p2, _ = trial(t)
        if p2 < pages:
            plan.theme = t
            plan.tokens = compile_tokens(t)
            if lp is not None:
                lp.log("pagination", f"tightened vertical rhythm (step {i + 1}): {pages}→{p2} pages "
                                     f"(last page was {fill:.0%} full)")
                lp.measured_pages = p2
            return
    if lp is not None:
        lp.log("pagination", f"{pages} pages, last {fill:.0%} full; kept rhythm (tightening within "
                             "limits would not save a page)")
