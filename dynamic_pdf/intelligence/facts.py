"""
``PageFacts``: one measured description of a rendered document.

It joins what used to be measured in three places: the page image and text signals of the
visual critique, the document facts of the learning dataset, and the geometry metrics the
layout score reads from the renderer's own regions. Each PDF is opened and rasterized once.
Scoring, the critique, the variant ranker and the scoreboard all read these facts.

Everything here is a measurement. None of it says whether a page is good, and none of it
comes from a reviewer. Reading the PDF needs PyMuPDF (the ``qa`` extra); without it the
facts say so and hold only what the renderer recorded.
"""
from __future__ import annotations

import math
import re
import statistics
from collections import Counter
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

FACTS_VERSION = 2          # 1: tools/design_learning/layout_facts.py, before the facts were joined

# page image
GRID_W, GRID_H = 24, 34
# page text
ARABIC = re.compile(r"[؀-ۿﭐ-﷿ﹰ-﻿]")
HEAD, FOOT = 0.09, 0.92            # outside these bands of the page sit running headers and footers
GAP = 0.12                         # an empty stretch this share of the page high counts as a gap
COLUMN_GAP = 1.5                   # a gap this many times the type size separates two columns


class PageSignals(BaseModel):
    page: int
    ink: float                   # share of the page's cells that are not blank
    void: float                  # tallest fully blank band, as a share of the page height
    tail: float                  # blank share below the last content
    image_share: float
    words: int
    largest_type: float
    first_line: str = ""


class PageFacts(BaseModel):
    """Measured facts of one rendered document. ``version`` changes whenever a fact's meaning does."""

    version: int = FACTS_VERSION
    available: bool = True                                  # False: the PDF could not be read
    pages: List[PageSignals] = Field(default_factory=list)  # per page, from the page image and text
    document: Dict[str, float] = Field(default_factory=dict)  # whole-document facts from the PDF
    layout: Dict[str, float] = Field(default_factory=dict)    # metrics from the renderer's regions
    layout_pages: List[dict] = Field(default_factory=list)    # per page: occupancy, fill, role, waste
    layout_errors: List[str] = Field(default_factory=list)    # hard faults found in the regions
    thumbs: List[List[int]] = Field(default_factory=list, exclude=True)   # page images on a coarse grid

    @property
    def page_count(self) -> int:
        return len(self.pages) or len(self.layout_pages) or int(self.document.get("pages", 0))


# ── reading one page ───────────────────────────────────────────────────────────────────

def _cells(page, pymupdf) -> List[List[bool]]:
    """Which cells of a coarse grid hold anything but the page background."""
    from PIL import Image
    pix = page.get_pixmap(dpi=36, colorspace=pymupdf.csGRAY, alpha=False)
    img = Image.frombytes("L", (pix.width, pix.height), pix.samples)
    small = img.resize((GRID_W * 4, GRID_H * 4))
    # a cell holds ink when any of its 4 x 4 pixels is darker than 232: mark those, then pool exactly
    marks = small.point(lambda v: 255 if v < 232 else 0).reduce(4).tobytes()
    return [[marks[gy * GRID_W + gx] > 0 for gx in range(GRID_W)] for gy in range(GRID_H)]


def _signals(number: int, page, cells, blocks) -> PageSignals:
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
    for block in blocks:
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


def _columns(spans: List[dict]) -> List[List[dict]]:
    """PyMuPDF joins two columns that share a baseline into one line. A wide gap parts them again."""
    parts: List[List[dict]] = []
    for s in sorted(spans, key=lambda s: s["bbox"][0]):
        if parts and s["bbox"][0] - parts[-1][-1]["bbox"][2] <= COLUMN_GAP * s["size"]:
            parts[-1].append(s)
        else:
            parts.append([s])
    return parts


def _text_page(p, blocks) -> dict:
    W, H = p.rect.width, p.rect.height
    area = W * H
    pics = []
    for info in p.get_image_info():
        x0, y0, x1, y1 = info["bbox"]
        x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, W), min(y1, H)
        if x1 > x0 and y1 > y0:
            pics.append((x0, y0, x1, y1))
    fills = [d["rect"] for d in p.get_drawings() if d.get("fill") is not None and d["rect"].width > 0.3 * W]
    lines = []
    for block in blocks:
        for line in block.get("lines", ()):
            spans = [s for s in line["spans"] if s["text"].strip()]
            for part in _columns(spans):
                lines.append({"x0": min(s["bbox"][0] for s in part), "y0": min(s["bbox"][1] for s in part),
                              "x1": max(s["bbox"][2] for s in part), "y1": max(s["bbox"][3] for s in part),
                              "text": "".join(s["text"] for s in part),
                              "size": max(s["size"] for s in part), "font": part[0]["font"],
                              "origin": part[0].get("origin", (0, part[0]["bbox"][3]))[1]})
    body = [ln for ln in lines if HEAD * H < ln["y0"] and ln["y1"] < FOOT * H]
    bands = [ln for ln in lines if ln not in body]
    boxes = sorted([(ln["y0"], ln["y1"]) for ln in body] + [(y0, y1) for _, y0, _, y1 in pics])
    gaps, edge = [], HEAD * H
    for y0, y1 in boxes:
        if y0 - edge > GAP * H:
            gaps.append((y0 - edge) / H)
        edge = max(edge, y1)
    bottom = edge / H
    image_share = min(1.0, sum((x1 - x0) * (y1 - y0) for x0, y0, x1, y1 in pics) / area)
    text_share = min(1.0, sum((ln["x1"] - ln["x0"]) * (ln["y1"] - ln["y0"]) for ln in body) / area)
    tinted = min(1.0, sum(r.width * r.height for r in fills) / area)
    kind = ("image" if image_share > 0.35 else "colour" if tinted > 0.3 else
            "mixed" if image_share > 0.08 else "sparse" if text_share < 0.12 else "text")
    return {"W": W, "H": H, "lines": body, "bands": bands, "gaps": gaps, "bottom": bottom, "kind": kind,
            "image_share": image_share, "text_share": text_share, "tinted": tinted}


# ── whole-document facts ───────────────────────────────────────────────────────────────

def _entropy(items: List[str]) -> float:
    n = len(items)
    return round(-sum(c / n * math.log2(c / n) for c in Counter(items).values()), 3) if n else 0.0


def _run(items: List[str]) -> int:
    best = cur = 0
    last = None
    for x in items:
        cur = cur + 1 if x == last else 1
        best, last = max(best, cur), x
    return best


def _mean(xs: List[float]) -> float:
    return round(sum(xs) / len(xs), 3) if xs else 0.0


def _arabic(pages: List[dict]) -> Dict[str, float]:
    rows = [(ln, p["W"]) for p in pages for ln in p["lines"]]
    ar = [(ln, w) for ln, w in rows if ARABIC.search(ln["text"])]
    if not ar:
        return {"arabic_line_share": 0.0, "arabic_right_edge_share": 0.0, "both_scripts_side_by_side": 0.0}
    right = sum(1 for ln, w in ar if w - ln["x1"] < ln["x0"])
    side = 0
    for p in pages:
        for a in p["lines"]:
            if ARABIC.search(a["text"]) and any(
                    not ARABIC.search(b["text"]) and abs(a["y0"] - b["y0"]) < 3 and b["x1"] < a["x0"] for b in p["lines"]):
                side += 1
    return {"arabic_line_share": round(len(ar) / len(rows), 3), "arabic_right_edge_share": round(right / len(ar), 3),
            "both_scripts_side_by_side": round(side / len(ar), 3)}


def _leading(pages: List[dict], body: float) -> float:
    """Line height of the body text on the page, as a multiple of its size: the median distance
    between the baselines of a wrapped body line and the next line of its column. 0.0 when no
    body line wraps (every paragraph one line long), so the page cannot tell."""
    steps = []
    for p in pages:
        lines = sorted((ln for ln in p["lines"] if abs(ln["size"] - body) < 0.05),
                       key=lambda ln: (round(ln["x0"]), ln["origin"]))
        edge = {}
        for ln in lines:
            edge[round(ln["x0"])] = max(edge.get(round(ln["x0"]), 0.0), ln["x1"])
        for a, b in zip(lines, lines[1:]):
            step = b["origin"] - a["origin"]
            wrapped = a["x1"] >= edge[round(a["x0"])] - 3 * body      # a full line: its paragraph goes on
            if wrapped and abs(a["x0"] - b["x0"]) < 2 and 0.9 * body < step < 2.2 * body:
                steps.append(step)
    return round(statistics.median(steps) / body, 2) if steps and body else 0.0


def _document(pages: List[dict], plain_pages: Optional[int]) -> Dict[str, float]:
    if not pages:
        return {"facts_version": FACTS_VERSION, "pages": 0}
    sizes = Counter()
    for p in pages:
        for ln in p["lines"]:
            sizes[round(ln["size"], 1)] += len(ln["text"])
    body = sizes.most_common(1)[0][0] if sizes else 0.0
    inner = pages[1:] or pages
    cover = pages[0]
    kinds = [p["kind"] for p in inner]
    tops = [min((ln for ln in p["lines"]), key=lambda ln: ln["y0"], default=None) for p in inner]
    openers = [t for t in tops if t and body and t["size"] >= body * 1.5]
    band_words = [sum(len(ln["text"].split()) for ln in p["bands"]) for p in inner]
    last = pages[-1]
    interior = pages[:-1] or pages
    facts = {
        "facts_version": FACTS_VERSION,
        "pages": len(pages),
        "page_growth": round(len(pages) / plain_pages, 3) if plain_pages else 0.0,
        # cover and section openers
        "cover_image_share": round(cover["image_share"], 3),
        "cover_colour_share": round(cover["tinted"], 3),
        "cover_title_to_body": round(max((ln["size"] for ln in cover["lines"] + cover["bands"]), default=0) / body, 2) if body else 0.0,
        "cover_words": sum(len(ln["text"].split()) for ln in cover["lines"] + cover["bands"]),
        "opener_page_share": round(len(openers) / len(inner), 3),
        # rhythm
        "page_kind_entropy": _entropy(kinds),
        "page_kinds": len(set(kinds)),
        "longest_same_kind_run": _run(kinds),
        # image and text balance
        "image_share_mean": _mean([p["image_share"] for p in inner]),
        "text_share_mean": _mean([p["text_share"] for p in inner]),
        "pages_without_image_share": round(sum(p["image_share"] < 0.02 for p in inner) / len(inner), 3),
        # whitespace: a gap inside a page is unexplained; room at the foot of a page before a break is not
        "interior_gap_pages": sum(bool(p["gaps"]) for p in inner),
        "largest_interior_gap": round(max((g for p in inner for g in p["gaps"]), default=0.0), 3),
        "mean_page_bottom": _mean([p["bottom"] for p in interior]),
        "short_pages_before_last": sum(p["bottom"] < 0.55 for p in interior[1:]),
        "last_page_fill": round(last["bottom"], 3),
        "last_page_words": sum(len(ln["text"].split()) for ln in last["lines"]),
        # bands
        "band_words_mean": _mean(band_words),
        "band_words_spread": round(max(band_words) - min(band_words), 1) if band_words else 0.0,
        # type
        "body_size": body,
        "distinct_sizes": len([s for s, n in sizes.items() if n >= 12]),
        "largest_to_body": round(max(sizes, default=0) / body, 2) if body else 0.0,
        "font_faces": len({ln["font"] for p in pages for ln in p["lines"]}),
        "body_leading": _leading(pages, body),
    }
    facts.update(_arabic(pages))
    return facts


# ── entry points ───────────────────────────────────────────────────────────────────────

def read_pdf(data: bytes, *, plain_pages: Optional[int] = None, image: bool = True) -> PageFacts:
    """Open ``data`` once and measure every page. ``image=False`` skips the page images
    (the ink grid), for callers that need only the text and geometry facts."""
    try:
        import pymupdf
    except ImportError:
        return PageFacts(available=False)
    out = PageFacts()
    text_pages = []
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        for i, page in enumerate(doc, 1):
            blocks = page.get_text("dict")["blocks"]
            if image:
                cells = _cells(page, pymupdf)
                out.thumbs.append([int(c) for row in cells for c in row])
                out.pages.append(_signals(i, page, cells, blocks))
            text_pages.append(_text_page(page, blocks))
    out.document = _document(text_pages, plain_pages)
    return out


def with_layout(facts: PageFacts, score) -> PageFacts:
    """Add the renderer's geometry, as the layout score measured it (a ``LayoutScore``)."""
    facts.layout = dict(score.metrics)
    facts.layout["score"] = score.score
    facts.layout_pages = [p.model_dump() for p in score.pages]
    facts.layout_errors = list(score.hard_errors)
    return facts


def measure_render(pdf: bytes, geometry, doc, theme, *, plain_pages: Optional[int] = None) -> PageFacts:
    """Facts of one render: the PDF read once, plus the regions the renderer recorded."""
    from .scoring import score_layout
    return with_layout(read_pdf(pdf, plain_pages=plain_pages), score_layout(geometry, doc, theme))


__all__ = ["FACTS_VERSION", "PageFacts", "PageSignals", "measure_render", "read_pdf", "with_layout"]
