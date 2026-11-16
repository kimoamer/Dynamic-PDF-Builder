"""
Page-break optimizer: choose where pages end by dynamic programming, not first fit.

ReportLab fills each page as far as it can, then moves on. With keep rules (a heading
with what follows it, a short table on one page) that greedy choice can leave a page
two thirds full, or end a document on a page with three lines. Block heights are
measured with the renderer's own flowables (``intelligence.analysis.measure_blocks``),
so the possible break points of a run of blocks are known before rendering. This module
scores every way to break that run (``plan_segment``) and keeps the best:

* never more pages than the natural layout (pages count first, then badness);
* badness: underfilled body pages, a near-empty last page, splits (a kept table split
  costs more than a paragraph), and a lead-in paragraph parted from its exhibit;
* a heading (or any block marked keep-with-next) never ends a page.

The plan reaches ReportLab as block hints only where it differs from what ReportLab
would do anyway: ``page_start`` (a page break before the block if the page is not
empty) and dropping a table's ``keep_together`` so it may split with its header
repeated. ``optimize_breaks`` verifies the hinted layout on a real render and keeps it
only when no page is gained and the measured page facts improve; otherwise the document
is returned unchanged. Author content is never touched.

Word gets the decisions that do not depend on ReportLab's line breaks: a released table's
rows are no longer kept with the next one, so Word may split it too. ``page_start`` is
PDF only: Word breaks lines differently, and on LibreOffice the same page starts added a
DOCX page in 2 of the 3 documents that had any (``benchmarks/m11``).
"""
from __future__ import annotations

import io
import warnings
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

EPS = 0.5                     # pt of slack when deciding that a block fits
MARGIN = 12.0                 # pt a planned split of a kept table must spare (the model is not exact)
UNDER = 0.62                  # a body page under this fill counts as underfilled (scoreboard: 0.6)
NEAR_EMPTY = 1 / 3            # a last page under this fill is near-empty
SPLIT_COST = {"text": 2.0, "list": 2.0}    # any other kind: 4
RELEASE_COST = 20.0           # a short table that was kept on one page now splits
PARTED_COST = 25.0            # a lead-in paragraph ends a page, its exhibit starts the next
EXHIBITS = {"table", "image", "chart", "diagram", "mermaid"}
SUPPORTED = {"heading", "paragraph", "bullet_list", "numbered_list", "checklist", "definition_list",
             "table", "code", "callout", "quote", "image", "chart", "diagram", "math", "divider",
             "spacer", "note", "rich_text", "footnote", "metric_row", "abstract", "bibliography",
             "signature", "timeline", "legend", "progress_bar", "score_display", "badge", "qrcode",
             "page_break", "cover_page", "table_of_contents", "introduction_page", "watermark"}
FROZEN_HINTS = ("flow_run", "min_space_before", "landscape", "columns")


@dataclass
class Item:
    """One block as the optimizer sees it (heights in pt)."""
    height: float                       # height without the outer spacing
    ink: Optional[float] = None         # drawn height; defaults to ``height``
    space_before: float = 0.0           # dropped at a page top; overlaps the space after above
    space_after: float = 0.0            # need not fit at a page foot
    splittable: bool = False            # ReportLab may split it at a page end
    min_piece: float = 0.0              # smallest first piece of a split
    keep_with_next: bool = False        # no page may end after it
    releasable: bool = False            # kept on one page by a soft rule; the plan may split it
    split_extra: float = 0.0            # height a continuation adds (a repeated table header)
    kind: str = "text"                  # text | heading | list | exhibit | other
    index: int = -1                     # block index in the document

    def __post_init__(self):
        if self.ink is None:
            self.ink = self.height


@dataclass
class PagePlan:
    start: int
    end: int                            # first item of the next page (== start item when split)
    fill: float
    split: Optional[int] = None         # item split at the foot of this page
    natural: bool = True                # what ReportLab does from this page start anyway


@dataclass
class SegmentPlan:
    pages: List[PagePlan]
    badness: float
    natural_pages: int
    natural_badness: float
    page_starts: List[int] = field(default_factory=list)   # items that must open a page (hint)
    releases: List[int] = field(default_factory=list)      # releasable items the plan splits
    facts: tuple = ()                                      # forecast (see ``_facts``) of the plan
    natural_facts: tuple = ()                              # ... and of the natural breaks

    @property
    def gain(self) -> bool:
        """The plan is forecast to improve a page fact, not only the badness."""
        return any(a < b for a, b in zip(self.facts, self.natural_facts))


def _under(fill: float) -> float:
    return 100.0 * (1.0 - fill) ** 2 + (60.0 if fill < UNDER else 0.0)


def _tail(fill: float, final: bool) -> float:
    return 80.0 + 300.0 * (NEAR_EMPTY - fill) if final and fill < NEAR_EMPTY else 0.0


def _options(items: List[Item], H: float, j: int, rem: Optional[float]):
    """Every way to end the page that starts at item ``j`` (``rem``: height of ``j`` carried
    over from a split), as [end, carried, ink, split, natural, cost]."""
    n = len(items)
    used = ink = above = 0.0
    k = j
    out = []
    while k < n:
        it = items[k]
        h = rem if (k == j and rem is not None) else it.height
        part_ink = it.ink * (h / it.height) if it.height else 0.0
        if used:                                         # as ReportLab's Frame (overlapAttachedSpace)
            used += max(it.space_before - above, 0.0)
        # the engine's keep group (heading + what follows) must fit with its last space after
        tail = it.space_after if k > j and items[k - 1].keep_with_next else 0.0
        if used + h + tail <= H + EPS:
            used += h + it.space_after
            above = it.space_after
            ink += part_ink
            k += 1
            if k < n and not items[k - 1].keep_with_next:
                parted = PARTED_COST if items[k].kind == "exhibit" and items[k - 1].kind == "text" else 0.0
                out.append([k, None, ink, None, False, parted])
            continue
        room = H - used
        rest = h - room
        need = it.min_piece + (0.0 if it.splittable else MARGIN)
        if (it.splittable or it.releasable) and room >= need and EPS < rest < h - it.split_extra:
            cost = SPLIT_COST.get(it.kind, 4.0) if it.splittable else RELEASE_COST
            out.append([k, rest + it.split_extra, ink + part_ink * room / h, k, it.splittable, cost])
        if not any(o[4] for o in out):
            bounds = [o for o in out if o[3] is None]
            if bounds:
                bounds[-1][4] = True                    # ReportLab moves the block (and its keep chain)
            elif k == j:
                out.append([k + 1, None, ink + part_ink, None, True, 0.0])   # taller than a page: set alone
            else:
                out.append([k, None, ink, None, True, 0.0])   # a keep chain from the page top overflows
        return out
    out.append([n, None, ink, None, True, 0.0])                    # the segment ends here
    return out


def _page_cost(opt, n: int, H: float, final: bool) -> float:
    end, carried, ink, _, _, cost = opt
    fill = ink / H if H else 0.0
    return cost + (_tail(fill, final) if end >= n and carried is None else _under(fill))


def _natural(items: List[Item], H: float) -> list:
    """The page options ReportLab takes by itself, page by page."""
    out, j, rem = [], 0, None
    while j < len(items):
        opt = next(o for o in _options(items, H, j, rem) if o[4])
        out.append(opt)
        j, rem = opt[0], opt[1]
    return out


def _facts(opts: list, n: int, H: float, final: bool) -> Tuple[int, int, int, int]:
    """Forecast of the scoreboard's page facts: (pages, underfilled body pages, near-empty
    last page, lead-ins parted from their exhibit)."""
    fills = [o[2] / H if H else 0.0 for o in opts]
    near = int(final and len(opts) > 1 and fills[-1] < NEAR_EMPTY)
    return (len(opts), sum(f < 0.6 for f in fills[:-1]), near,
            sum(o[3] is None and o[5] == PARTED_COST for o in opts[:-1]))


def natural_pages(items: List[Item], H: float, final: bool = True) -> Tuple[int, float, float]:
    """(pages, badness, fill of the last page) of the run as ReportLab breaks it by itself."""
    opts = _natural(items, H)
    bad = sum(_page_cost(o, len(items), H, final) for o in opts)
    return len(opts), round(bad, 6), round(opts[-1][2] / H, 3) if opts and H else 0.0


def plan_segment(items: List[Item], H: float, final: bool = True) -> SegmentPlan:
    """Best break points for a run of items that starts on a fresh page.

    ``final``: the run ends the document (its last page should not be near-empty);
    otherwise the author's structure ends its last page and it costs nothing."""
    n = len(items)
    memo: Dict[Tuple[int, Optional[float]], tuple] = {}

    def best(j: int, rem: Optional[float]) -> tuple:
        if j >= n:
            return (0, 0.0, 0, None)
        key = (j, None if rem is None else round(rem, 2))
        if key in memo:
            return memo[key]
        res = None
        for opt in _options(items, H, j, rem):
            sub = best(opt[0], opt[1])
            cand = (1 + sub[0], round(_page_cost(opt, n, H, final) + sub[1], 6), (0 if opt[4] else 1) + sub[2], opt)
            if res is None or cand[:3] < res[:3]:
                res = cand
        memo[key] = res
        return res

    total = best(0, None)
    pages: List[PagePlan] = []
    j, rem = 0, None
    starts, releases, chosen = [], [], []
    while j < n:
        _, _, _, opt = best(j, rem)
        chosen.append(opt)
        end, carried, ink, split, nat, _ = opt
        pages.append(PagePlan(j, end, round(ink / H, 3) if H else 0.0, split, nat))
        if not nat:
            if split is not None:
                if not items[split].splittable:
                    releases.append(split)
            elif end < n:
                starts.append(end)
        j, rem = end, carried
    natural = _natural(items, H)
    nat_bad = round(sum(_page_cost(o, n, H, final) for o in natural), 6)
    return SegmentPlan(pages, total[1] if n else 0.0, len(natural), nat_bad, starts, releases,
                       _facts(chosen, n, H, final), _facts(natural, n, H, final))


# ───────────────────────────── documents ─────────────────────────────

@dataclass
class BreakReport:
    applied: bool = False
    reason: str = ""
    page_starts: List[int] = field(default_factory=list)    # block indices
    releases: List[int] = field(default_factory=list)       # block indices
    before: Dict = field(default_factory=dict)
    after: Dict = field(default_factory=dict)
    renders: int = 0
    rendered: Optional[tuple] = field(default=None, repr=False)

    def summary(self) -> str:
        if not self.applied:
            return f"page breaks: kept the natural breaks ({self.reason})"
        moves = []
        if self.page_starts:
            moves.append(f"{len(self.page_starts)} page(s) end earlier")
        if self.releases:
            moves.append(f"{len(self.releases)} short table(s) may split")
        b, a = self.before, self.after
        parted = (f", exhibits parted from their lead-in {b['separated']}→{a['separated']}"
                  if b.get("separated") != a.get("separated") else "")
        return (f"page breaks: {', '.join(moves)}; pages {b.get('pages')}→{a.get('pages')}, underfilled "
                f"{b.get('underfilled')}→{a.get('underfilled')}, near-empty last page "
                f"{b.get('near_empty_last')}→{a.get('near_empty_last')}{parted}")


def _items(doc, theme, policy=None, cache=None):
    """(runs of (items, ends the document, frozen), usable frame height) from measured blocks.
    A run starts on a fresh page; a frozen run holds something the model does not cover."""
    from ..intelligence.analysis import FORCED_BREAK_AFTER, NO_CONTENT, measure_blocks
    from ..layout.engine import _uses_media_model
    if _uses_media_model(doc.blocks):
        return None, 0.0
    ms, fg = measure_blocks(doc, theme, policy, cache)
    kept = [i for i, b in enumerate(doc.blocks) if b.type == "table" and (b.hints or {}).get("keep_together")]
    released: Dict[int, object] = {}
    if kept:
        loose = doc.model_copy(deep=True)
        loose.blocks = [loose.blocks[i] for i in kept]
        for b in loose.blocks:
            b.hints = {k: v for k, v in b.hints.items() if k != "keep_together"}
        rel, _ = measure_blocks(loose, theme, policy, cache)
        released = dict(zip(kept, rel))
    segments: List[Tuple[list, bool, bool]] = []
    cur: List[Item] = []
    frozen = False
    for m, b in zip(ms, doc.blocks):
        hints = b.hints or {}
        starts = m.break_before or hints.get("drop") or (
            m.index > 0 and doc.blocks[m.index - 1].type in FORCED_BREAK_AFTER)
        if starts and cur:
            segments.append((cur, False, frozen))
            cur, frozen = [], False
        if b.type not in SUPPORTED or any(hints.get(h) for h in FROZEN_HINTS) or m.tail:
            frozen = True
        if b.type == "page_break":
            continue
        kind = ("heading" if b.type == "heading" else "exhibit" if b.type in EXHIBITS
                else "list" if m.role == "list" else "text" if m.role == "body" else "other")
        r = released.get(m.index)
        rows = len(getattr(b, "rows", []) or []) + 1
        cur.append(Item(m.body, 0.0 if b.type in NO_CONTENT else m.ink, m.space_before, m.space_after,
                        splittable=m.splittable,
                        min_piece=m.min_piece if m.splittable else (r.min_piece if r is not None else m.height),
                        keep_with_next=b.type == "heading" or bool(hints.get("keep_with_next")),
                        releasable=bool(r is not None and r.splittable),
                        split_extra=m.ink / rows if b.type == "table" else 0.0, kind=kind, index=m.index))
    if cur:
        segments.append((cur, True, frozen))
    from .factory import FRAME_PADDING
    return segments, fg.height - 2 * FRAME_PADDING


def plan_document(doc, theme, policy=None, cache=None) -> Tuple[List[int], List[int], str]:
    """(blocks that open a page, kept tables that may split, why nothing changed)."""
    segments, H = _items(doc, theme, policy, cache)
    if segments is None:
        return [], [], "page layers or images placed on the page are not modelled"
    starts, releases = [], []
    for items, final, frozen in segments:
        if frozen or not items:
            continue
        sp = plan_segment(items, H, final)
        if not sp.gain:                 # a lateral move is not worth a verifying render
            continue
        starts += [items[k].index for k in sp.page_starts]
        releases += [items[k].index for k in sp.releases]
    return starts, releases, "" if starts or releases else "they are already the best the model finds"


def without_page_starts(doc):
    """A copy of ``doc`` without the PDF page starts, for another layout (Word, another rhythm)."""
    out = doc.model_copy(deep=True)
    for b in out.blocks:
        if (b.hints or {}).get("page_start"):
            b.hints = {k: v for k, v in b.hints.items() if k != "page_start"}
    return out


def forecast(doc, theme, policy=None, cache=None) -> Optional[Tuple[int, float]]:
    """(pages, fill of the last page) as ReportLab would break ``doc`` by itself, from measured
    blocks and no render; None where something on the pages is not modelled."""
    segments, H = _items(doc, theme, policy, cache)
    if segments is None or any(frozen for _, _, frozen in segments):
        return None
    pages, fill = 0, 0.0
    for items, final, _ in segments:
        if items:
            n, _, fill = natural_pages(items, H, final)
            pages += n
    return pages, fill


def with_breaks(doc, starts, releases):
    """A copy of ``doc`` carrying the plan as hints. Content is not touched."""
    out = doc.model_copy(deep=True)
    for i in starts:
        b = out.blocks[i]
        b.hints = {**(b.hints or {}), "page_start": True}
    for i in releases:
        b = out.blocks[i]
        b.hints = {k: v for k, v in (b.hints or {}).items() if k != "keep_together"}
    return out


def page_facts(doc, theme, policy=None) -> Dict:
    """Score-independent page facts of a real render (the scoreboard's definitions)."""
    return _render(doc, theme, policy)[0]


def _render(doc, theme, policy=None):
    """(page facts, PDF bytes, geometry) of a real render."""
    from ..intelligence.geometry import Geometry
    from .engine import LayoutEngine
    geo, buf = Geometry(), io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        LayoutEngine(doc, policy=policy, theme=theme, geometry=geo).render(buf)
    return facts_of(geo, doc, theme), buf.getvalue(), geo


def facts_of(geo, doc, theme) -> Dict:
    from ..intelligence.scoring import score_layout
    s = score_layout(geo, doc, theme)
    final = [p for p in s.pages if p.role == "final"]
    return {"pages": len(s.pages),
            "underfilled": sum(p.role == "body" and p.fill < 0.6 for p in s.pages),
            "near_empty_last": int(bool(final and len(s.pages) > 1 and final[0].fill < NEAR_EMPTY)),
            "separated": int(s.metrics.get("separated_figures", 0)),
            "wasted": s.metrics.get("wasted", 0.0),
            "errors": len(s.hard_errors)}


def _better(a: Dict, b: Dict) -> bool:
    """``a`` (hinted) is at least as good as ``b`` (natural) on every fact and better on one."""
    keys = ("pages", "errors", "underfilled", "near_empty_last", "separated")
    if any(a[k] > b[k] for k in keys):
        return False
    return any(a[k] < b[k] for k in keys) or a["wasted"] < b["wasted"] - 0.01


def optimize_breaks(doc, theme, policy=None, cache=None, natural=None) -> Tuple[object, BreakReport]:
    """(document with page-break hints, report). Falls back to ``doc`` unless a real
    render confirms the plan. ``natural``: the geometry of ``doc`` already rendered, which
    saves a render; ``report.rendered`` holds (PDF, geometry) of the hinted render."""
    rep = BreakReport()
    starts, releases, why = plan_document(doc, theme, policy, cache)
    if not starts and not releases:
        rep.reason = why
        return doc, rep
    cand = with_breaks(doc, starts, releases)
    rep.before = facts_of(natural, doc, theme) if natural is not None else page_facts(doc, theme, policy)
    rep.after, pdf, geo = _render(cand, theme, policy)
    rep.renders = 1 if natural is not None else 2
    rep.rendered = (pdf, geo)
    rep.page_starts, rep.releases = starts, releases
    if not _better(rep.after, rep.before):
        rep.reason = "the real render did not confirm the plan"
        return doc, rep
    rep.applied = True
    return cand, rep


def fit_breaks(doc, plan, policy=None) -> Optional[Tuple[List[int], List[int]]]:
    """The verified break plan (page starts, released tables) for a designed document, or
    None. Logged in the design's layout plan."""
    try:
        _, rep = optimize_breaks(doc, plan.theme, policy)
    except Exception as e:                 # never let the optimizer break a valid designed render
        rep = BreakReport(reason=f"optimizer failed ({type(e).__name__})")
    lp = plan.layout
    if lp is not None:
        lp.trial_renders += rep.renders
        if rep.applied:
            lp.log("pagination", rep.summary())
            lp.measured_pages = rep.after["pages"]
    return (rep.page_starts, rep.releases) if rep.applied else None
