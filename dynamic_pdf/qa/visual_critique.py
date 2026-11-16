"""
A look at rendered pages, in two separate parts.

``hard_failures`` are facts: lost words, clipped text, stranded headings, unsafe page
geometry. A design with any of them is rejected. ``heuristics`` are measurements of the
page image, such as empty bands or how alike neighbouring pages are. They steer
refinement and rank valid designs, but they are not aesthetic judgement: they cannot tell
good whitespace from bad, and no human has calibrated them.

The page signals come from ``PageFacts`` (``dynamic_pdf.intelligence.facts``), so a PDF
is read and rasterized once however often it is judged. Reading the page image needs
PyMuPDF (the ``qa`` extra). Without it the critique says so and carries no heuristics.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from pydantic import BaseModel, Field

from ..intelligence.facts import GRID_H, GRID_W, PageFacts, PageSignals, read_pdf  # noqa: F401 (re-exported)

MIN_BODY_SIZE = 7.0
MAX_WORDS_PER_PAGE = 950
SPARSE_INK = 0.05
ALIKE = 0.93
HEURISTIC_LABEL = "heuristic measurement of page images, not a human or aesthetic judgement"


class Observation(BaseModel):
    code: str
    page: Optional[int] = None
    note: str


class VisualCritique(BaseModel):
    label: str = HEURISTIC_LABEL
    available: bool = True
    pages: List[PageSignals] = Field(default_factory=list)
    heuristics: Dict[str, float] = Field(default_factory=dict)
    observations: List[Observation] = Field(default_factory=list)
    hard_failures: List[str] = Field(default_factory=list)

    @property
    def index(self) -> float:
        """A single number for ordering valid designs. Not a quality grade."""
        from ..intelligence.objective import visual_index
        return visual_index(self.heuristics)


def _alike(a: Sequence[int], b: Sequence[int]) -> float:
    return sum(x == y for x, y in zip(a, b)) / max(1, len(a))


def critique_facts(facts: PageFacts, *, intended: Sequence[int] = ()) -> VisualCritique:
    """Judge measured pages. ``intended`` lists pages whose emptiness was planned (a cover,
    an opening page, a statement), which are not reported as sparse."""
    if not facts.available:
        return VisualCritique(available=False, observations=[Observation(
            code="unreviewed", note="PyMuPDF is not installed, so the page images were not measured")])
    out = VisualCritique(pages=list(facts.pages))
    thumbs = facts.thumbs
    pages = out.pages
    n = len(pages)
    body = [p for p in pages if p.page not in intended]
    sparse = [p for p in body if p.ink < SPARSE_INK or (p.tail > 0.55 and p.page != n)]
    pairs = [(a, b) for a, b in zip(thumbs, thumbs[1:])]
    alike = [i + 1 for i, (a, b) in enumerate(pairs) if _alike(a, b) >= ALIKE]
    rounded = {tuple(sum(t[r * GRID_W * 4 + c] for c in range(GRID_W * 4)) // 12 for r in range(GRID_H // 4))
               for t in thumbs}
    sizes = sorted(p.largest_type for p in pages if p.largest_type)
    median = sizes[len(sizes) // 2] if sizes else 1.0
    out.heuristics = {
        "pages": float(n),
        "sparse_share": round(len(sparse) / max(1, len(body)), 3),
        "alike_share": round(len(alike) / max(1, len(pairs)), 3),
        "page_variety": round(len(rounded) / max(1, n), 3),
        "type_contrast": round((sizes[-1] if sizes else 1.0) / max(1.0, min(sizes[0] if sizes else 1.0, median)), 2),
        "image_share": round(sum(p.image_share for p in pages) / max(1, n), 3),
        "last_page_ink": pages[-1].ink if pages else 0.0,
    }
    for p in sparse:
        out.observations.append(Observation(code="sparse_page", page=p.page,
                                            note=f"page {p.page}: {round(p.tail * 100)}% blank below the content"))
    for i in alike:
        out.observations.append(Observation(code="alike_pages", page=i,
                                            note=f"pages {i} and {i + 1} have nearly the same shape"))
    return out


def critique_pdf(data: bytes, *, intended: Sequence[int] = ()) -> VisualCritique:
    """Measure every page and judge it (see ``critique_facts``)."""
    return critique_facts(read_pdf(data), intended=intended)


def hard_failures(*, content: Sequence[str], pdf_report=None, docx_report=None, preservation=None,
                  layout_errors: Sequence[str] = (), media: Sequence[Dict] = (),
                  smallest_type: Optional[float] = None, critique: Optional[VisualCritique] = None) -> List[str]:
    """Everything that rejects a design, with no room for taste."""
    out = [f"content: {c}" for c in content]
    out += [f"layout: {e}" for e in layout_errors]
    for report, name in ((pdf_report, "pdf"), (docx_report, "docx")):
        if report is not None:
            out += [f"{name}: {f.code}: {f.message}" for f in report.errors]
    if preservation is not None:
        from .content_preservation import FAILED
        for layer in preservation.layers:
            if layer.status == FAILED:
                out += [f"preservation {layer.name}: {x}" for x in layer.details]
    out += [f"media: {m.get('code')}: {m.get('message', '')}" for m in media if m.get("severity") == "error"]
    if smallest_type is not None and smallest_type < MIN_BODY_SIZE:
        out.append(f"density: body type {smallest_type:g} pt is below {MIN_BODY_SIZE:g} pt")
    if critique is not None:
        out += [f"density: page {p.page} holds {p.words} words" for p in critique.pages
                if p.words > MAX_WORDS_PER_PAGE]
    return out
