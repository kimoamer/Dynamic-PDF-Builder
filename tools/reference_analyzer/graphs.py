"""
Page composition graphs: every reference page as nodes and relations in normalized
coordinates, built from the measurements already taken (design-features.json and
visual-page-index.json). Nothing here stores page text or pixels, and no field says a
page looks good.

A box is ``[x0, y0, x1, y1]`` in 0..1 of the page, top-left origin. ``start`` boxes are
the same box read from the page's inline start, so a right-to-left page and its
left-to-right counterpart can be compared.
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Sequence, Tuple

FORMAT = "dynamic-pdf-builder/m77-page-composition-graphs"
VERSION = 1
NUMBER_END = re.compile(r"[\d٠-٩]{1,4}$")
ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

# Family tests run in this order; the first that matches names the page. ``families`` are
# composition families; direction, bilingual setting and dense bands are facets beside them.
FAMILIES = {
    "blank_or_notice": "Blank page or a short centred notice",
    "cover_image": "Cover led by an image or a full colour field",
    "cover_type": "Cover led by type",
    "back_cover": "Closing page: colophon, contact or back cover",
    "contents": "Contents list",
    "section_opener": "Section or chapter opener",
    "statement": "One large statement or figure with little else",
    "kpi_dashboard": "Figures or tiles set as a dashboard",
    "full_bleed_image": "Image filling the page",
    "image_split": "Page divided between image and text",
    "image_inset": "Text page carrying smaller images",
    "infographic": "Diagram or infographic led page",
    "data_story": "Chart with commentary",
    "financial_table": "Table filling most of the page",
    "table_in_text": "Table set inside running text",
    "editorial_asymmetric": "Unequal columns or an offset text block",
    "multi_column_text": "Two or more equal text columns",
    "single_column_text": "One text column",
}


def _v(x):
    return x.get("value") if isinstance(x, dict) and "value" in x else x


def _load(path: str):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _box(b: Sequence[float], w: float, h: float) -> List[float]:
    return [round(min(1.0, max(0.0, v)), 3) for v in (b[0] / w, b[1] / h, b[2] / w, b[3] / h)]


def _area(b: Sequence[float]) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def _overlap(a: Sequence[float], b: Sequence[float]) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return max(0.0, w) * max(0.0, h)


def _flip(b: Sequence[float]) -> List[float]:
    return [round(1 - b[2], 3), b[1], round(1 - b[0], 3), b[3]]


def _group_text(blocks: List[dict], w: float, h: float) -> List[dict]:
    """Runs of text: neighbouring blocks in one column merge, so a page is a few nodes,
    not one per line. Headings stay separate."""
    out: List[dict] = []
    for b in sorted(blocks, key=lambda t: (round(t["bbox"][0] / w, 2), t["bbox"][1])):
        box = _box(b["bbox"], w, h)
        kind = "heading" if b.get("role") == "heading_candidate" else (
            "small_text" if b.get("role") == "small_text" else "paragraph")
        last = out[-1] if out else None
        if (last and kind != "heading" and last["type"] == kind and abs(last["box"][0] - box[0]) < 0.02
                and 0 <= box[1] - last["box"][3] < 0.03):
            last["box"] = [min(last["box"][0], box[0]), last["box"][1], max(last["box"][2], box[2]), box[3]]
            last["lines"] += b.get("lines", 1)
            continue
        out.append({"type": kind, "box": box, "lines": b.get("lines", 1), "size_pt": b.get("size_pt"),
                    "dir": b.get("direction")})
    return out


def _direction(script: Optional[str], hint: Optional[str]) -> str:
    return {"latin_ltr": "ltr", "arabic_rtl": "rtl", "bilingual": "bilingual"}.get(script or "", hint or "unknown")


def _running(items: List[dict], band: str, w: float, h: float) -> Optional[dict]:
    mine = [_box(e["bbox"], w, h) for e in items if e.get("band") == band]
    if not mine:
        return None
    return {"type": "header" if band == "top" else "footer",
            "box": [min(b[0] for b in mine), min(b[1] for b in mine), max(b[2] for b in mine), max(b[3] for b in mine)],
            "items": len(mine)}


def page_graph(feat: dict, index: dict, repeated_marks: set) -> dict:
    """One page as a graph. ``repeated_marks`` holds image boxes seen on several pages."""
    size = _v(feat["size"])
    w, h = size["width_pt"], size["height_pt"]
    geo, raster = index.get("geometry") or {}, index.get("raster") or {}
    script = _v(feat["script"]) or {}
    direction = _direction(script.get("class"), None)
    if direction == "unknown" and script.get("font_hint"):
        direction = {"arabic": "rtl", "latin": "ltr"}.get(script["font_hint"], "unknown")
    run = _v(feat["running_elements"]) or []
    nodes: List[dict] = []
    for band in ("top", "bottom"):
        n = _running(run, band, w, h)
        if n:
            nodes.append(n)
    run_boxes = [_box(e["bbox"], w, h) for e in run]
    texts = [t for t in (_v(feat["text_blocks"]) or [])
             if not any(_overlap(_box(t["bbox"], w, h), r) > 0.6 * max(_area(_box(t["bbox"], w, h)), 1e-6) for r in run_boxes)]
    nodes += _group_text(texts, w, h)
    for im in _v(feat["images"]) or []:
        box = _box(im["bbox"], w, h)
        a = _area(box)
        key = tuple(round(v, 2) for v in box)
        mark = a < 0.03 and (key in repeated_marks or box[1] < 0.14 or box[3] > 0.88)
        nodes.append({"type": "logo" if mark else "image", "box": box, "bleed": min(box[0], box[1], 1 - box[2], 1 - box[3]) < 0.005})
    for t in _v(feat["tables"]) or []:
        nodes.append({"type": "table", "box": _box(t["bbox"], w, h), "rows": t.get("rows"), "cols": t.get("cols"),
                      "header_fill": bool(t.get("header_fill")), "banded": bool(t.get("banded_rows"))})
    for v in _v(feat["vector_graphics"]) or []:
        box = _box(v["bbox"], w, h)
        if _area(box) >= 0.01:
            nodes.append({"type": "chart_or_figure", "box": box})
    for r in _v(feat["rules"]) or []:
        if r.get("thickness_pt", 0) >= 1.5 or r.get("length_pt", 0) >= 0.5 * w:
            nodes.append({"type": "rule", "box": _box(r["bbox"], w, h), "thick": r.get("thickness_pt", 0) >= 1.5})
    empty = raster.get("largest_empty") or {}
    if empty.get("share", 0) >= 0.12:
        nodes.append({"type": "whitespace", "box": empty["box"], "share": empty["share"]})
    if geo.get("numeric_big"):
        nodes.append({"type": "kpi_group", "count": geo["numeric_big"], "box": None})
    for i, n in enumerate(nodes):
        n["id"] = i
    edges = _relations(nodes)
    anchor = _anchor(nodes)
    columns = _v(feat["columns"]) or {}
    lefts = Counter(round(n["box"][0], 2) for n in nodes if n["box"] and n["type"] in ("paragraph", "heading", "table", "image"))
    return {
        "ref": f"{index['doc_id']}:{index['page']}", "doc": index["doc_id"], "page": index["page"],
        "aspect": round(w / h, 3), "direction": direction, "nodes": nodes, "edges": edges, "anchor": anchor,
        "grid": {"columns": columns.get("count", 0),
                 "gutters": [round(g / w, 3) for g in columns.get("gutters_pt", [])],
                 "column_widths": [round((b - a) / w, 3) for a, b in columns.get("intervals", [])],
                 "alignment_lines": [x for x, c in lefts.most_common(4) if c >= 2]},
        "background": {"color": raster.get("background"), "dark": (raster.get("background_luminance") or 1) < 0.35,
                       "tinted": (raster.get("background_luminance") or 1) < 0.92},
        "measures": {"text_share": geo.get("text_share", 0), "image_share": geo.get("image_share", 0),
                     "largest_image": geo.get("largest_image", 0), "table_share": geo.get("table_share", 0),
                     "vector_share": geo.get("vector_share", 0), "ink": raster.get("ink_share", 0),
                     "chars": geo.get("chars", 0), "max_size_pt": geo.get("max_size_pt", 0),
                     "display_ratio": geo.get("display_ratio", 0), "column_ratio": geo.get("column_ratio", 0),
                     "numeric_big": geo.get("numeric_big", 0), "numeric_mid": geo.get("numeric_mid", 0),
                     "quote_blocks": geo.get("quote_blocks", 0), "statement_blocks": geo.get("statement_blocks", 0),
                     "balance_lr": (raster.get("balance") or {}).get("left_right", 0),
                     "edge_contact": max((raster.get("edge_contact") or {"x": 0}).values()),
                     "colourfulness": raster.get("colourfulness", 0), "empty": empty.get("share", 0),
                     "header_items": sum(1 for e in run if e.get("band") == "top"),
                     "footer_items": sum(1 for e in run if e.get("band") == "bottom")},
        "labels": [x["label"] for x in index.get("labels") or []],
        "layout_type": index.get("layout_type"), "cluster": index.get("cluster"),
        "cluster_in_document": (index.get("cluster_size") or {}).get("document", 1),
    }


def _relations(nodes: List[dict]) -> List[list]:
    """``[a, relation, b]``. Reading neighbours only, so the graph stays small."""
    body = [n for n in nodes if n.get("box") and n["type"] not in ("whitespace", "rule")]
    edges: List[list] = []
    order = sorted(body, key=lambda n: (n["box"][1], n["box"][0]))
    for a, b in zip(order, order[1:]):
        if a["box"][3] <= b["box"][1] + 0.01:
            edges.append([a["id"], "above", b["id"]])
        else:
            edges.append([a["id"], "beside", b["id"]])
        if abs(a["box"][0] - b["box"][0]) < 0.01:
            edges.append([a["id"], "aligned_start", b["id"]])
    for n in body:
        if n["type"] in ("image", "table", "chart_or_figure"):
            for t in body:
                if t["type"] != "small_text":
                    continue
                near = min(abs(t["box"][1] - n["box"][3]), abs(n["box"][1] - t["box"][3]))
                if near < 0.03 and min(t["box"][2], n["box"][2]) > max(t["box"][0], n["box"][0]):
                    edges.append([t["id"], "caption_of", n["id"]])
            if n["type"] == "image":
                for t in body:
                    if t["type"] in ("heading", "paragraph") and _overlap(t["box"], n["box"]) > 0.7 * max(_area(t["box"]), 1e-6):
                        edges.append([t["id"], "over", n["id"]])
    return edges


def _anchor(nodes: List[dict]) -> Optional[dict]:
    """The heaviest thing on the page: area, with headings and images counted up."""
    weight = {"image": 1.0, "table": 0.8, "chart_or_figure": 0.9, "heading": 3.0, "paragraph": 0.25}
    best = max((n for n in nodes if n.get("box") and n["type"] in weight),
               key=lambda n: _area(n["box"]) * weight[n["type"]], default=None)
    if best is None:
        return None
    b = best["box"]
    return {"node": best["id"], "type": best["type"], "centre": [round((b[0] + b[2]) / 2, 3), round((b[1] + b[3]) / 2, 3)]}


def _contents_page(page, position: float, table_share: float) -> bool:
    """A contents list: early in the document, lines ending in numbers that climb."""
    if position > 0.12 or table_share > 0.3:
        return False
    tail = []
    for line in page.get_text().splitlines():
        m = NUMBER_END.search(line.strip())
        if m:
            tail.append(int(m.group().translate(ARABIC_DIGITS)))
    if len(tail) < 5:
        return False
    rising = sum(b >= a for a, b in zip(tail, tail[1:]))
    return rising / (len(tail) - 1) >= 0.7 and tail[-1] > tail[0]


def family_of(g: dict, count: int, contents: bool) -> Tuple[str, str]:
    """(family, the test that placed it). Measured rules, so a new page is placed the same way."""
    m = {k: v or 0 for k, v in g["measures"].items()}
    L, kinds = set(g["labels"]), Counter(n["type"] for n in g["nodes"])
    first, last = g["page"] == 1, g["page"] == count
    if m["chars"] < 80 and m["ink"] < 0.03 and m["largest_image"] < 0.1:
        return "blank_or_notice", "under 80 characters and 3% ink"
    if first or "cover_title" in L:
        if m["largest_image"] >= 0.3 or g["background"]["dark"] or m["edge_contact"] >= 0.5:
            return "cover_image", "first page or cover label, with a large image or colour field"
        return "cover_type", "first page or cover label, type led"
    if last and m["chars"] < 900:
        return "back_cover", "last page, under 900 characters"
    if contents:
        return "contents", "lines ending in page numbers"
    if "section_opener" in L and m["chars"] < 1200:
        return "section_opener", "opener label, under 1200 characters"
    if m["numeric_big"] >= 3 or "kpi_dashboard" in L:
        return "kpi_dashboard", "three or more large figures"
    if m["chars"] < 700 and m["display_ratio"] >= 2 and m["largest_image"] < 0.45:
        return "statement", "under 700 characters at display size"
    if m["largest_image"] >= 0.62 or "full_bleed" in L:
        return "full_bleed_image", "image over 62% of the page, or full-bleed label"
    if m["table_share"] >= 0.4 or "financial_table" in L:
        return "financial_table", "table over 40% of the page"
    if "split_image_text" in L or (m["image_share"] >= 0.22 and m["chars"] >= 200):
        return "image_split", "split label, or image over 22% with text"
    if "infographic" in L or m["vector_share"] >= 0.4:
        return "infographic", "infographic label, or vectors over 40%"
    if "data_story" in L or kinds["chart_or_figure"] >= 1 and m["vector_share"] >= 0.1:
        return "data_story", "data-story label, or a chart over 10%"
    if m["table_share"] >= 0.08:
        return "table_in_text", "table of 8-40%"
    if m["image_share"] >= 0.03:
        return "image_inset", "images of 3-22%"
    if "editorial_asymmetric" in L:
        return "editorial_asymmetric", "unequal column label"
    if g["grid"]["columns"] >= 2:
        return "multi_column_text", "two or more columns"
    return "single_column_text", "default"


def _facets(g: dict) -> List[str]:
    m = {k: v or 0 for k, v in g["measures"].items()}
    out = [f"dir:{g['direction']}"]
    if m["header_items"] + m["footer_items"] >= 4 or max(m["header_items"], m["footer_items"]) >= 3:
        out.append("dense_bands")
    if any(n["type"] == "logo" for n in g["nodes"]):
        out.append("logo")
    if g["background"]["dark"]:
        out.append("dark_page")
    elif g["background"]["tinted"]:
        out.append("tinted_page")
    if m["edge_contact"] >= 0.5:
        out.append("bleed")
    if m["quote_blocks"]:
        out.append("pull_quote")
    return out


def _repeated_marks(features: dict) -> Dict[str, set]:
    """Small images in one place on three or more pages of a document: marks, not pictures."""
    out: Dict[str, set] = {}
    for d in features["documents"]:
        seen: Counter = Counter()
        for p in d["pages"]:
            size = _v(p["size"])
            for im in _v(p["images"]) or []:
                seen[tuple(round(v, 2) for v in _box(im["bbox"], size["width_pt"], size["height_pt"]))] += 1
        out[d["doc_id"]] = {k for k, c in seen.items() if c >= 3}
    return out


def build(analysis_dir: str, references_dir: Optional[str] = None) -> dict:
    """All pages. ``references_dir`` adds the contents-page test, which needs the page text."""
    features = _load(os.path.join(analysis_dir, "design-features.json"))
    index = _load(os.path.join(analysis_dir, "visual", "visual-page-index.json"))
    by_ref = {(p["doc_id"], p["page"]): p for p in index["pages"]}
    marks = _repeated_marks(features)
    pages: List[dict] = []
    documents = []
    for d in features["documents"]:
        count = len(d["pages"])
        pdf = None
        if references_dir:
            import pymupdf
            path = os.path.join(references_dir, d["file"])
            pdf = pymupdf.open(path) if os.path.exists(path) else None
        mine = []
        for p in d["pages"]:
            g = page_graph(p, by_ref[(d["doc_id"], p["page"])], marks[d["doc_id"]])
            contents = bool(pdf) and _contents_page(pdf[p["page"] - 1], (p["page"] - 1) / count, g["measures"]["table_share"] or 0)
            g["family"], g["family_test"] = family_of(g, count, contents)
            g["facets"] = _facets(g)
            mine.append(g)
        if pdf:
            pdf.close()
        for i, g in enumerate(mine):
            g["rhythm"] = {"previous": mine[i - 1]["family"] if i else None,
                           "next": mine[i + 1]["family"] if i + 1 < count else None,
                           "position": round(i / max(1, count - 1), 3)}
        pages += mine
        documents.append({"doc_id": d["doc_id"], "file": d["file"], "pages": count})
    return {"format": FORMAT, "version": VERSION,
            "note": "Normalized geometry and relations only: no page text, no pixels. Families come from measured "
                    "rules; they are not quality judgments.",
            "families": FAMILIES, "documents": documents, "pages": pages}


def family_table(graphs: dict) -> Dict[str, dict]:
    """Pages, weighted pages and documents per family. A page in a template cluster counts
    for its share of that cluster, so repeated templates do not outvote distinct pages."""
    out: Dict[str, dict] = defaultdict(lambda: {"pages": 0, "weighted": 0.0, "documents": set()})
    for g in graphs["pages"]:
        row = out[g["family"]]
        row["pages"] += 1
        row["weighted"] += 1 / max(1, g.get("cluster_in_document") or 1)
        row["documents"].add(g["doc"])
    return {k: {"pages": v["pages"], "weighted": round(v["weighted"], 1), "documents": len(v["documents"])}
            for k, v in sorted(out.items(), key=lambda kv: -kv[1]["pages"])}
