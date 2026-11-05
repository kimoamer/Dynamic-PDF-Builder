"""
Measured facts about a rendered document, for the preference dataset.

Everything here is read from a PDF: positions, sizes, fonts and image boxes. None of it says
whether a page is good, and none of it comes from a reviewer. Reviewer judgments stay in
ai-preferences.jsonl, so a trainer can never confuse the two.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Dict, List, Optional

ARABIC = re.compile(r"[؀-ۿﭐ-﷿ﹰ-﻿]")
HEAD, FOOT = 0.09, 0.92            # outside these bands of the page sit running headers and footers
GAP = 0.12                         # an empty stretch this share of the page high counts as a gap
COLUMN_GAP = 1.5                   # a gap this many times the type size separates two columns
FACTS_VERSION = 1


def _columns(spans: List[dict]) -> List[List[dict]]:
    """PyMuPDF joins two columns that share a baseline into one line. A wide gap parts them again."""
    parts: List[List[dict]] = []
    for s in sorted(spans, key=lambda s: s["bbox"][0]):
        if parts and s["bbox"][0] - parts[-1][-1]["bbox"][2] <= COLUMN_GAP * s["size"]:
            parts[-1].append(s)
        else:
            parts.append([s])
    return parts


def _page(p) -> dict:
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
    for block in p.get_text("dict")["blocks"]:
        for line in block.get("lines", ()):
            spans = [s for s in line["spans"] if s["text"].strip()]
            for part in _columns(spans):
                lines.append({"x0": min(s["bbox"][0] for s in part), "y0": min(s["bbox"][1] for s in part),
                              "x1": max(s["bbox"][2] for s in part), "y1": max(s["bbox"][3] for s in part),
                              "text": "".join(s["text"] for s in part),
                              "size": max(s["size"] for s in part), "font": part[0]["font"]})
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


def measure(pdf: bytes, plain_pages: Optional[int] = None) -> Dict[str, float]:
    import pymupdf
    with pymupdf.open(stream=pdf, filetype="pdf") as d:
        pages = [_page(p) for p in d]
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
    }
    facts.update(_arabic(pages))
    return facts


__all__ = ["FACTS_VERSION", "measure"]
