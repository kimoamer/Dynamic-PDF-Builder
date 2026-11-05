"""
A look at rendered pages, in two separate parts.

``hard_failures`` are facts: lost words, clipped text, stranded headings, unsafe page
geometry. A design with any of them is rejected. ``heuristics`` are measurements of the
page image, such as empty bands or how alike neighbouring pages are. They steer
refinement and rank valid designs, but they are not aesthetic judgement: they cannot tell
good whitespace from bad, and no human has calibrated them.

Reading the page image needs PyMuPDF (the ``qa`` extra). Without it the critique says so
and carries no heuristics.
"""
from __future__ import annotations

import io
from typing import Dict, List, Optional, Sequence

from pydantic import BaseModel, Field

GRID_W, GRID_H = 24, 34
MIN_BODY_SIZE = 7.0
MAX_WORDS_PER_PAGE = 950
SPARSE_INK = 0.05
ALIKE = 0.93
HEURISTIC_LABEL = "heuristic measurement of page images, not a human or aesthetic judgement"


class PageSignals(BaseModel):
    page: int
    ink: float                   # share of the page's cells that are not blank
    void: float                  # tallest fully blank band, as a share of the page height
    tail: float                  # blank share below the last content
    image_share: float
    words: int
    largest_type: float
    first_line: str = ""


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
        h = self.heuristics
        if not h:
            return 0.0
        score = 60.0
        score += 14 * h.get("page_variety", 0)
        score += 10 * min(h.get("type_contrast", 1), 3.5) / 3.5
        score += 8 * min(h.get("image_share", 0) / 0.15, 1)
        score -= 22 * h.get("sparse_share", 0)
        score -= 18 * h.get("alike_share", 0)
        score -= 10 * max(0.0, 0.25 - h.get("last_page_ink", 1) * 2)
        return round(score, 2)


def _cells(page, pymupdf) -> List[List[bool]]:
    """Which cells of a coarse grid hold anything but the page background."""
    from PIL import Image
    pix = page.get_pixmap(dpi=36, colorspace=pymupdf.csGRAY, alpha=False)
    img = Image.frombytes("L", (pix.width, pix.height), pix.samples)
    small = img.resize((GRID_W * 4, GRID_H * 4))
    data = small.load()
    out = []
    for gy in range(GRID_H):
        row = []
        for gx in range(GRID_W):
            lo = min(data[gx * 4 + i, gy * 4 + j] for i in range(4) for j in range(4))
            row.append(lo < 232)
        out.append(row)
    return out


def _thumb(cells) -> List[int]:
    return [int(c) for row in cells for c in row]


def _alike(a: Sequence[int], b: Sequence[int]) -> float:
    return sum(x == y for x, y in zip(a, b)) / max(1, len(a))


def _signals(number: int, page, cells) -> PageSignals:
    h = GRID_H
    filled_rows = [any(row) for row in cells]
    # running heads and feet sit in the outer rows; they are not page content
    body = filled_rows[3:h - 3]
    run = best = 0
    for filled in body:
        run = 0 if filled else run + 1
        best = max(best, run)
    last = max((i for i, f in enumerate(body) if f), default=-1)
    area = page.rect.width * page.rect.height
    images = 0.0
    for info in page.get_image_info():
        x0, y0, x1, y1 = info["bbox"]
        images += max(0.0, x1 - x0) * max(0.0, y1 - y0)
    largest, words, first = 0.0, 0, ""
    top = page.rect.height * 0.09
    bottom = page.rect.height * 0.92
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                if not span["text"].strip():
                    continue
                largest = max(largest, span["size"])
                words += len(span["text"].split())
                if not first and top <= span["bbox"][1] <= bottom:
                    first = span["text"].strip()
    return PageSignals(page=number, ink=round(sum(map(sum, cells)) / (GRID_W * h), 3),
                       void=round(best / h, 3), tail=round((len(body) - 1 - last) / h, 3),
                       image_share=round(min(1.0, images / area), 3), words=words, largest_type=round(largest, 1),
                       first_line=first[:80])


def critique_pdf(data: bytes, *, intended: Sequence[int] = ()) -> VisualCritique:
    """Measure every page. ``intended`` lists pages whose emptiness was planned (a cover,
    an opening page, a statement), which are not reported as sparse."""
    try:
        import pymupdf
    except ImportError:
        return VisualCritique(available=False, observations=[Observation(
            code="unreviewed", note="PyMuPDF is not installed, so the page images were not measured")])
    out = VisualCritique()
    thumbs = []
    with pymupdf.open(stream=io.BytesIO(data).getvalue(), filetype="pdf") as doc:
        for i, page in enumerate(doc, 1):
            cells = _cells(page, pymupdf)
            thumbs.append(_thumb(cells))
            out.pages.append(_signals(i, page, cells))
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
