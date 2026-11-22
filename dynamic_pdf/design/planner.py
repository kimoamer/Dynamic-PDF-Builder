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
* Tables: content-measured column widths; each column's role read from its header and
  cells (period, identifier, category, figure, text), figures right-aligned;
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
from ..core.table_types import side_set, table_types
from ..core.normalize import SemanticDocument
from ..schema.blocks import CoverPageBlock
from ..schema.enums import Orientation, PageSize
from . import DesignPlan
from .measure import chars_per_line, column_metrics, fit_columns, wrap_ratio
from .profile import Profile

MIN_TABLE_SIZE = 7.5
COLUMN_GAP = 18.0
MIN_RUN_PARAGRAPHS = 3      # a column run is continuous prose, not a sentence or two
MIN_RUN_CHARS = 900
MIN_COLUMN_CPL = 40
_PAGE = {PageSize.A4: (595.28, 841.89), PageSize.LETTER: (612, 792), PageSize.LEGAL: (612, 1008)}
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
    trial_renders: int = 0          # PDF renders spent by fit_pages and fit_breaks

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
    if plan.recipe.heading_ramp_locked:
        lp.log("headings", "heading ramp set by the evidence recipe")
    elif st.max_heading_level >= 4:
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
    runs = _column_runs(sem, plan, width)
    if runs:
        lp.log("measure", f"{cpl:.0f} chars/line; columns set the measure of the long prose runs")
    elif profile in _PROSE_PROFILES and cpl > 92 and widest_table < width * 0.9 and sem.direction == "ltr":
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
        types = table_types(b)
        numeric = types.numeric_cols          # figures line up at the reading end; periods and codes do not
        hints["numeric_cols"] = numeric
        hints["column_roles"] = types.roles
        if types.total_rows or types.subtotal_rows:
            hints["total_rows"] = sorted(types.total_rows + types.subtotal_rows)
        if types.current_col is not None:
            hints["current_period_col"] = types.current_col
        size = ty.base_size - 1
        fits = False
        fracs: Optional[List[float]] = None
        # dense tables get tighter cell padding (pt per side), shared by PDF and DOCX
        pad = 4.0 if ncols >= 7 else (6.0 if ncols >= 5 else 9.0)
        hints["cell_padding"] = pad
        from ..core.table_types import measured_rows
        measured = measured_rows(b)              # a cell that runs over empty ones takes their room, not its column's
        b.hints = hints
        hints["side_headers"], hints["side_groups"] = _side_set(b, measured, ty.body_family, size, pad, avail)
        hints.update({k: v for k, v in b.hints.items() if k == "wrap_headers"})
        b.hints = hints
        measured = _width_rows(b, measured)
        while size >= MIN_TABLE_SIZE:
            mins, nats = _metrics(b, measured, ty.body_family, size, pad, avail)
            fracs, _ = fit_columns(mins, nats, avail)
            fits = _fits(mins, nats, avail)      # readable cells too: on average ≤ 2.2 lines per cell
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
            mins, nats = _metrics(b, measured, ty.body_family, MIN_TABLE_SIZE, pad, land_w)
            fracs2, fits2 = fit_columns(mins, nats, land_w)
            fits2 = fits2 and wrap_ratio(nats, fracs2, land_w) <= 1.8
            # prose wraps; figures, codes and periods cannot, so only they justify turning the page
            rigid = sum(r != "text" for r in types.roles)
            if sem.meta.orientation != Orientation.LANDSCAPE and ncols >= 5 and rigid >= 3:
                hints["landscape"] = True
                hints["col_fractions"] = [round(f, 4) for f in fracs2] if not b.column_widths else None
                what += "; too wide for portrait → landscape page" + ("" if fits2 else " (cells wrap)")
            else:
                what += "; cells wrap at minimum size"
        lines = _balanced_headers(b, hints, land_w if hints.get("landscape") else avail, ty.body_family, size, pad)
        if lines:
            hints["header_lines"] = lines
        if len(b.rows) <= 12:
            hints["keep_together"] = True
            what += "; kept on one page"
        else:
            what += "; splits across pages with repeated header"
        if numeric:
            what += f"; numeric columns {numeric} right-aligned"
        what += f"; columns: {types.summary()}"
        if hints["side_headers"] or hints["side_groups"]:
            what += f"; on their side: headers {hints['side_headers']}, merged labels {hints['side_groups']}"
        if types.chart_suggestion():
            what += f" (would also read as a {types.chart_suggestion()})"
        b.hints = hints
        lp.log("tables", what)

    # ── lead paragraph ──
    if profile in _LEAD_PROFILES:
        for k, b in enumerate(sem.blocks):
            if b.type == "paragraph":
                # a lead leads into more text in its section; alone, it is just larger body text
                rest = next((j for j in range(k + 1, len(sem.blocks)) if sem.blocks[j].type == "heading"), len(sem.blocks))
                if len(plain_text(b.text)) > 60 and any(x.type == "paragraph" for x in sem.blocks[k + 1:rest]):
                    b.hints = {**(b.hints or {}), "lead": True}
                    lp.log("lead", "opening paragraph set as a lead (larger, no indent)")
                break

    _mark_column_runs(sem, plan, runs, lp)
    _keep_intros_with_exhibits(sem, lp)
    lp.estimated_pages = _estimate_pages(sem, theme, width)

    # ── a paper does not number its abstract, references or acknowledgements ──
    if plan.recipe.paper:
        from ..core.keywords import pattern
        plain = pattern("sections", "unnumbered")
        for b in sem.blocks:
            if b.type == "heading" and plain.fullmatch(" ".join(plain_text(b.text).split()).lower()):
                b.hints = {**(b.hints or {}), "unnumbered": True}
    from .art_direction import _opens_with_title
    # ── the title is not a section: numbering starts at the heading after it ──
    if plan.section_numbering and _opens_with_title(sem):
        title = next(b for b in sem.blocks if b.type == "heading")
        title.hints = {**(title.hints or {}), "unnumbered": True}
    # ── a paper opens with its title and authors on page one, never on a cover ──
    if plan.recipe.paper and not st.has_cover and sem.meta.title and not _opens_with_title(sem):
        sem.blocks.insert(0, CoverPageBlock(title=sem.meta.title, subtitle=sem.meta.subject or sem.meta.description,
                                            author=sem.meta.author, hints={"title_block": True}))
        lp.log("title", "paper: title and authors set at the head of page one")
    # ── cover page from metadata (only for long, titled reports) ──
    elif (profile in _COVER_PROFILES and not st.has_cover and sem.meta.title
            and lp.estimated_pages >= 3):
        cover = CoverPageBlock(title=sem.meta.title,
                               subtitle=sem.meta.subject or sem.meta.description,
                               author=sem.meta.author)
        if _opens_with_title(sem):              # the cover says the title: the page after it does not repeat it
            sem.blocks.remove(next(b for b in sem.blocks if b.type == "heading"))
        sem.blocks.insert(0, cover)
        lp.log("cover", f"~{lp.estimated_pages:.1f} pages with a title: cover built from metadata")
    # ── a short document whose design has no header band still shows its title (a letter does not) ──
    elif (not plan.recipe.header_enabled and not st.has_cover and sem.meta.title and not _opens_with_title(sem)
            and profile != Profile.LETTER):
        sem.blocks.insert(0, CoverPageBlock(title=sem.meta.title, subtitle=sem.meta.subject or sem.meta.description,
                                            author=sem.meta.author, hints={"title_block": True}))
        lp.log("title", "no header band: the title set at the head of page one")
    return lp


# ─────────────────────────── column runs ───────────────────────────

def _column_runs(sem: SemanticDocument, plan: DesignPlan, width: float) -> List[List[int]]:
    """Runs of consecutive prose paragraphs long enough for columns. Left-to-right documents only."""
    n = plan.recipe.body_columns
    ty = plan.theme.typography
    if n < 2 or sem.direction != "ltr" or sem.stats.bilingual:
        return []
    if chars_per_line((width - COLUMN_GAP * (n - 1)) / n, ty.body_family, ty.base_size) < MIN_COLUMN_CPL:
        return []
    runs: List[List[int]] = []
    cur: List[int] = []
    for i, b in enumerate(sem.blocks + [None]):
        if b is not None and b.type == "paragraph" and not (b.hints or {}).get("keep_tail"):
            cur.append(i)
            continue
        if len(cur) >= MIN_RUN_PARAGRAPHS and sum(len(plain_text(sem.blocks[j].text)) for j in cur) >= MIN_RUN_CHARS:
            runs.append(cur)
        cur = []
    return runs


def _mark_column_runs(sem: SemanticDocument, plan: DesignPlan, runs: List[List[int]], lp: LayoutPlan) -> None:
    for k, run in enumerate(runs):
        kept = [i for i in run if not (sem.blocks[i].hints or {}).get("lead")]   # a lead stays full width
        if len(kept) < MIN_RUN_PARAGRAPHS:
            continue
        for i in kept:
            b = sem.blocks[i]
            b.hints = {**(b.hints or {}), "flow_run": k, "flow_columns": plan.recipe.body_columns,
                       "flow_gap": COLUMN_GAP}
        lp.log("columns", f"{len(kept)} paragraphs from block {kept[0]} set in "
                          f"{plan.recipe.body_columns} balanced columns")


# ─────────────────────────── exhibits ───────────────────────────

_EXHIBITS = ("table", "chart", "image", "diagram", "mermaid")
_INTRO_CHARS = 400       # a heading's short intro; longer text stands on its own


def _keep_intros_with_exhibits(sem: SemanticDocument, lp: LayoutPlan) -> None:
    """A heading already stays with the next block. When that block is a short
    intro, the intro must also stay with the table or figure it introduces;
    otherwise the heading ends one page and its exhibit opens the next."""
    blocks, kept = sem.blocks, 0
    for i, b in enumerate(blocks):
        if b.type not in _EXHIBITS:
            continue
        j, chars = i - 1, 0
        while j >= 0 and blocks[j].type == "paragraph" and chars < _INTRO_CHARS:
            chars += len(plain_text(blocks[j].text))
            j -= 1
        intro = range(j + 1, i)
        if not intro or chars >= _INTRO_CHARS or j < 0 or blocks[j].type != "heading":
            continue
        if any((blocks[k].hints or {}).get("flow_run") is not None for k in intro):
            continue
        for k in intro:
            blocks[k].hints = {**(blocks[k].hints or {}), "keep_with_next": True}
        kept += 1
    if kept:
        lp.log("exhibits", f"{kept} heading intro(s) kept with the table or figure they introduce")


# ─────────────────────────── contents ───────────────────────────

MIN_CONTENTS_PAGES = 4      # a contents page is navigation; a shorter document is read straight through


def drop_short_contents(sem: SemanticDocument, plan: DesignPlan) -> None:
    """Remove a contents page the design inserted when the measured document, without it,
    runs to fewer than ``MIN_CONTENTS_PAGES`` pages. A contents block the author wrote stays."""
    lp = plan.layout
    if not plan.toc_inserted or lp is None or lp.measured_pages is None:
        return
    pages = lp.measured_pages - 1                 # the inserted contents page ends with a page break
    floor = max(MIN_CONTENTS_PAGES, plan.recipe.toc_min_pages)
    if pages >= floor:
        return
    sem.blocks = [b for b in sem.blocks if not (b.type == "table_of_contents" and b.kind == "contents")]
    plan.toc_inserted = False
    note = (f"{pages} page{'s' if pages != 1 else ''} of content measured: no contents page "
            f"under {floor} pages unless the author adds one")
    if not any(d.target == "contents" and d.decision == note for d in lp.decisions):
        lp.log("contents", note)


# ─────────────────────────── page fit ───────────────────────────

def _tighten(theme, spacing: float, margins: float, leading_cut: float):
    sp, ty = theme.spacing, theme.typography
    sp.paragraph_spacing_after = round(sp.paragraph_spacing_after * spacing, 1)
    sp.block_gap = round(sp.block_gap * spacing, 1)
    sp.heading_spacing_before = [round(v * spacing, 1) for v in sp.heading_spacing_before]
    sp.heading_spacing_after = [round(v * spacing, 1) for v in sp.heading_spacing_after]
    sp.page_margin_top = max(42.0, round(sp.page_margin_top * margins, 1))
    sp.page_margin_bottom = max(42.0, round(sp.page_margin_bottom * margins, 1))
    ty.line_height = min(ty.line_height, max(1.3, round(ty.line_height - leading_cut, 2)))


SIDE = "MM"          # a side-set cell is measured across, as one line of text is wide


def _width_headers(b) -> list:
    """The header text a column's width answers to: a header set on its side takes a line's width."""
    side, _ = side_set(b)
    return [SIDE if ci in side else h for ci, h in enumerate(b.headers or [])]


def _width_rows(b, rows) -> list:
    """The cells a column's width answers to: a merged label set on its side takes a line's width."""
    _, groups = side_set(b)
    return [[SIDE if ci in groups and str(x).strip() else x for ci, x in enumerate(r)] for r in rows]


def _fits(mins, nats, avail) -> bool:
    """Every column at least its longest word, and cells read in about two lines or fewer."""
    fracs, fits = fit_columns(mins, nats, avail)
    return fits and wrap_ratio(nats, fracs, avail) <= 1.8 and sum(mins) <= 0.85 * avail


def _side_set(b, measured, family: str, size: float, pad: float, avail: float):
    """Which headers and which merged labels stand on their side, decided by need, as a typesetter would:

    - a merged label, when every label of its column runs down two rows or more, is long enough that
      setting it on its side saves its column most of its width, and fits the height of the rows it joins;
    - headers, when there are many columns (five or more), each after the first narrower than its header, and
      they fit level nowhere within 2pt of the table's size, even broken between their words into up to
      three even lines; level comes first. The first column names the rows: its
      header stays level. ``vertical_headers=True`` or ``False`` decides it instead.
    """
    from .measure import text_width
    n = max([len(b.headers or [])] + [len(r) for r in b.rows] + [1])
    line = size * 1.3
    row_h = line + 2 * (7 if pad >= 9 else 4)
    starts = {(r, c): k for r, c, k in b.merged_down}
    groups = []
    for c in sorted({c for _, c, _ in b.merged_down}):
        cells = [(r, plain_text(str(row[c]))) for r, row in enumerate(b.rows) if c < len(row) and str(row[c]).strip()]
        if cells and all((r, c) in starts and 3 * line < text_width(t, family, size) <= starts[(r, c)] * row_h - 8
                         for r, t in cells):
            groups.append(c)
    heads = [str(h) for h in b.headers or []]
    if not heads or b.vertical_headers is False:
        return [c for c in groups if c < len(heads)], groups
    stub = next((c for c in range(n) if c not in groups), 0)       # the column that names the rows
    every = [c for c in range(len(heads)) if c != stub]
    if b.vertical_headers is True:
        return every, groups
    rows = [[SIDE if ci in groups and x.strip() else x for ci, x in enumerate(r)] for r in measured]
    level = column_metrics([SIDE if c in groups else h for c, h in enumerate(heads)], rows, family, size, 2 * pad)
    side = column_metrics([SIDE if c in every else h for c, h in enumerate(heads)], rows, family, size, 2 * pad)
    narrow = all(level[0][c] > side[1][c] + 4 for c in every if c not in groups)    # the names, not the data
    # level first: a header may take up to three even lines, broken between its words, over its column's
    # data, and the table may come down 2pt to keep them level; only past that do they stand on their side
    level_heads = [SIDE if c in groups else h for c, h in enumerate(heads)]
    if n >= 5 and narrow and \
            not any(_fits(*_wrapped(level_heads, rows, family, size - k / 2, pad), avail) for k in range(5)):
        return every, groups
    b.hints = {**(b.hints or {}), "wrap_headers": n >= 5 and narrow}
    return [c for c in groups if c < len(heads)], groups


def _wrapped(heads, rows, family: str, size: float, pad: float):
    """(mins, naturals) with each header counted as up to three lines over its column's data."""
    dm, dn = column_metrics([""] * len(heads), rows, family, size, 2 * pad)
    hm, hn = column_metrics(heads, [], family, size, 2 * pad)
    mins = [max(a, h) for a, h in zip(dm, hm)]
    return mins, [max(d, h / 3, m) for d, h, m in zip(dn, hn, mins)]


def _metrics(b, rows, family: str, size: float, pad: float, avail: float):
    """Column widths' (mins, naturals); level headers over narrow data wrap, so count as up to three lines."""
    whole = column_metrics(_width_headers(b), rows, family, size, 2 * pad)
    if (b.hints or {}).get("wrap_headers") and sum(whole[1]) > avail:
        return _wrapped(_width_headers(b), rows, family, size, pad)
    return whole                                  # room for every header on one line: none wraps


def _balanced_headers(b, hints, avail: float, family: str, size: float, pad: float) -> dict:
    """{column: lines} for the level headers that wrap in their column, broken into as many lines as they
    need but as even as can be ("Single sign-on" over "Single sign-" / "on" reads as one name), as a
    typesetter balances a heading. Headers with inline markup are left to wrap as they fall."""
    from itertools import combinations
    from .measure import text_width
    fr = hints.get("col_fractions")
    if not fr or not b.headers:
        return {}
    side = set(hints.get("side_headers") or [])
    total = sum(fr) or 1.0
    out = {}
    for c, h in enumerate(b.headers):
        words = str(h).split()
        if c in side or c >= len(fr) or len(words) < 2 or re.search(r"[*_`\[\]<>\\]", str(h)):
            continue
        room = fr[c] / total * (avail - 1.0) - 2 * pad - 4        # the slack keeps a balanced line from re-wrapping
        w = lambda ws: text_width(" ".join(ws), family, size, bold=True)
        if w(words) <= room or max(w([x]) for x in words) > room:
            continue
        best = None
        for k in range(2, min(4, len(words) + 1)):                  # the fewest lines that fit, then the most even
            for cuts in combinations(range(1, len(words)), k - 1):
                parts = [words[a:z] for a, z in zip((0,) + cuts, cuts + (len(words),))]
                widest = max(w(p) for p in parts)
                if widest <= room and (best is None or widest < best[0]):
                    best = (widest, [" ".join(p) for p in parts])
            if best:
                break
        if best:
            out[c] = best[1]
    return out


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
        if lp is not None:
            if pages < 2:
                why = "fits on one page; nothing to tighten"
            elif pages > 12 or fill is None:
                why = "too long to save a page by tightening"
            else:
                why = f"last page {fill:.0%} full; worth keeping"
            lp.log("pagination", f"{pages} page{'s' if pages != 1 else ''}: {why}")
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
