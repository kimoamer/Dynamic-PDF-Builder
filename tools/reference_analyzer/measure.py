"""
Per-page measurements from a PDF's own objects (PyMuPDF).

Every value is reported with its unit, extraction method, confidence and basis:

* ``measured`` — read directly from PDF objects (page boxes, declared font
  names and sizes, colours, image placements, drawing paths);
* ``inferred`` — a heuristic over measured values (heading levels, columns,
  alignment, spreads, charts). Inferred values carry an explicit confidence.

Coordinates are PDF points (1 pt = 1/72 in) in PyMuPDF's top-left page space.
Nothing here judges aesthetics.
"""
from __future__ import annotations

import colorsys
import re
import statistics
import unicodedata
from typing import Dict, List, Optional, Tuple

MM = 25.4 / 72.0
_SUBSET = re.compile(r"^[A-Z]{6}\+")
_ARABIC = re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]")
_ARABIC_PRESENTATION = re.compile(r"[ﭐ-﷿ﹰ-﻿]")
_LATIN = re.compile(r"[A-Za-zÀ-ɏ]")
_WEIGHTS = [("extralight", 200), ("ultralight", 200), ("thin", 100), ("light", 300), ("book", 400),
            ("regular", 400), ("roman", 400), ("medium", 500), ("semibold", 600), ("demibold", 600),
            ("demi", 600), ("extrabold", 800), ("ultrabold", 800), ("heavy", 900), ("black", 900),
            ("bold", 700)]


def m(value, unit: Optional[str], method: str, confidence: str, basis: str = "measured") -> dict:
    """One reported value. confidence: high | medium | low."""
    return {"value": value, "unit": unit, "method": method, "confidence": confidence, "basis": basis}


def r1(x: float) -> float:
    return round(float(x), 1)


def r2(x: float) -> float:
    return round(float(x), 2)


# ───────────────────────────── fonts ─────────────────────────────

def font_info(name: str, flags: int) -> dict:
    """Family / weight / style from the embedded font name (+ span flags)."""
    clean = _SUBSET.sub("", name or "")
    low = clean.lower().replace(" ", "")
    weight, wsrc = None, None
    for tok, w in _WEIGHTS:
        if tok in low.split("-")[-1] or tok in low.split(",")[-1] or low.endswith(tok):
            weight, wsrc = w, "font name"
            break
    if weight is None and flags & 16:
        weight, wsrc = 700, "span bold flag"
    italic = bool(flags & 2) or any(t in low for t in ("italic", "oblique"))
    family = re.split(r"[-,]", clean)[0] if clean else ""
    family = re.sub(r"(MT|PS|Std|Pro|LT)$", "", family) or family
    return {"name": clean, "family": family, "weight": weight, "weight_source": wsrc, "italic": italic}


def _hex(c) -> Optional[str]:
    if c is None:
        return None
    if isinstance(c, int):
        return f"#{c:06X}"
    if isinstance(c, (tuple, list)) and len(c) >= 3:
        return "#" + "".join(f"{max(0, min(255, round(v * 255))):02X}" for v in c[:3])
    return None


def is_accent(hexcolor: Optional[str]) -> bool:
    """Saturated, mid-lightness colour (not black/white/grey)."""
    if not hexcolor:
        return False
    r, g, b = (int(hexcolor[i:i + 2], 16) / 255 for i in (1, 3, 5))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    return s > 0.25 and 0.12 < l < 0.9


# ───────────────────────────── geometry helpers ─────────────────────────────

def _union(boxes):
    boxes = [b for b in boxes if b]
    if not boxes:
        return None
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def _area(b) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def _merge_intervals(iv, gap=0.0):
    out = []
    for a, b in sorted(iv):
        if out and a <= out[-1][1] + gap:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def _script(text: str) -> Tuple[int, int]:
    return len(_ARABIC.findall(text)), len(_LATIN.findall(text))


# ───────────────────────────── raw extraction ─────────────────────────────

def extract_page(page) -> dict:
    """Raw objects of one page (pass 1). Kept compact; derived values come later."""
    W, H = page.rect.width, page.rect.height
    d = page.get_text("dict")
    blocks = []
    for bl in d.get("blocks", []):
        if bl.get("type") != 0:
            continue
        lines = []
        for ln in bl.get("lines", []):
            spans = [s for s in ln.get("spans", []) if s.get("text", "").strip()]
            if not spans:
                continue
            text = "".join(s["text"] for s in spans)
            main = max(spans, key=lambda s: len(s["text"]))
            lines.append({"bbox": tuple(ln["bbox"]), "text": text, "size": main["size"],
                          "font": main["font"], "flags": main["flags"], "color": _hex(main["color"]),
                          "origin_y": main["origin"][1], "dir": tuple(ln.get("dir", (1, 0))),
                          "spans": [(s["font"], s["size"], s["flags"], _hex(s["color"]), len(s["text"].strip()))
                                    for s in spans]})
        if lines:
            blocks.append({"bbox": tuple(bl["bbox"]), "lines": lines})
    images = []
    for im in page.get_image_info(xrefs=True):
        bb = tuple(im["bbox"])
        if _area(bb) < 4:
            continue
        images.append({"bbox": bb, "px": (im.get("width"), im.get("height"))})
    drawings = []
    try:
        for p in page.get_drawings():
            rect = p.get("rect")
            if rect is None:
                continue
            drawings.append({"bbox": (rect.x0, rect.y0, rect.x1, rect.y1), "fill": _hex(p.get("fill")),
                             "stroke": _hex(p.get("color")), "width": p.get("width") or 0.0,
                             "items": len(p.get("items", [])),
                             "kinds": "".join(sorted({it[0] for it in p.get("items", [])}))})
    except Exception:            # malformed content streams: reported as a warning upstream
        drawings = None
    tables = []
    try:
        found = page.find_tables(strategy="lines")
        for t in found.tables:
            cells = [c for c in (t.cells or []) if c]
            tables.append({"bbox": tuple(t.bbox), "rows": t.row_count, "cols": t.col_count,
                           "cells": [tuple(c) for c in cells],
                           "header_external": bool(getattr(t.header, "external", False)),
                           "empty_cells": sum(1 for c in (t.cells or []) if not c)})
    except Exception:
        tables = None
    return {"number": page.number + 1, "width": W, "height": H, "rotation": page.rotation,
            "mediabox": tuple(page.mediabox), "cropbox": tuple(page.cropbox),
            "blocks": blocks, "images": images, "drawings": drawings, "tables": tables}


# ───────────────────────────── derived (pass 2) ─────────────────────────────

def _alignment(lines, rtl: bool) -> Tuple[str, str]:
    """(alignment, confidence) of a text block from its line edges."""
    if len(lines) == 2:
        # two lines cannot separate "justified" from a flush edge: report only which edge is flush
        (l0, _, r0, _), (l1, _, r1_, _) = lines[0]["bbox"], lines[1]["bbox"]
        if abs(r0 - r1_) < 1.5 and abs(l0 - l1) > 3:
            return "right_or_justified", "medium"
        if abs(l0 - l1) < 1.5 and abs(r0 - r1_) > 3:
            return "left_or_justified", "medium"
        return "undetermined", "low"
    if len(lines) < 3:
        return "undetermined", "low"
    L = [ln["bbox"][0] for ln in lines]
    R = [ln["bbox"][2] for ln in lines]
    C = [(a + b) / 2 for a, b in zip(L, R)]
    body_L, body_R = L[:-1], R[:-1]          # last line of a justified paragraph is short
    sl, sr, sc = statistics.pstdev(body_L), statistics.pstdev(body_R), statistics.pstdev(C)
    conf = "high" if len(lines) >= 4 else "medium"
    if sl < 1.5 and sr < 1.5:
        return "justified", conf
    if sl < 1.5 and statistics.pstdev(R) > 3:
        return "left", conf
    if statistics.pstdev(R) < 1.5 and statistics.pstdev(L) > 3:
        return "right", conf
    if sc < 1.5:
        return "center", conf
    return "ambiguous", "low"


def running_key(line: dict, H: float, block_lines: int = 1, W: float = 1e9) -> Optional[Tuple[str, str]]:
    """Key of a line that could be a running header/footer: a short standalone line
    (block of ≤2 lines, ≤80 % of the page width) in the top/bottom 12 % of the page.
    Digits are normalised so page numbers match across pages."""
    if block_lines > 2 or (line["bbox"][2] - line["bbox"][0]) > 0.8 * W:
        return None
    y0, y1 = line["bbox"][1], line["bbox"][3]
    if y1 <= 0.12 * H:
        band = "top"
    elif y0 >= 0.88 * H:
        band = "bottom"
    else:
        return None
    return re.sub(r"[\d\u0660-\u0669]+", "#", line["text"].strip().lower()), band


def classify_page(raw: dict, body_size: Optional[float], running: frozenset = frozenset()) -> dict:
    """Derived per-page features with units, methods and confidence."""
    W, H = raw["width"], raw["height"]
    out: Dict[str, object] = {"page": raw["number"]}
    landscape = W > H
    out["size"] = m({"width_pt": r1(W), "height_pt": r1(H), "width_mm": r1(W * MM), "height_mm": r1(H * MM)},
                    "pt/mm", "page.rect (CropBox, rotation applied)", "high")
    out["orientation"] = m("landscape" if landscape else "portrait", None, "width vs height", "high")
    if raw["rotation"]:
        out["rotation"] = m(raw["rotation"], "deg", "page /Rotate", "high")

    blocks = raw["blocks"]
    text = "\n".join(ln["text"] for b in blocks for ln in b["lines"])
    n_chars = sum(1 for c in text if not c.isspace())
    ar, la = _script(text)
    out["chars"] = m(n_chars, "chars", "extracted text (non-space)", "high")

    # ── extraction quality ──
    bad = sum(1 for c in text if c == "�" or unicodedata.category(c) in ("Co", "Cn"))
    quality = []
    if n_chars and bad / n_chars > 0.02:
        quality.append("broken_text_extraction")
    if ar and len(_ARABIC_PRESENTATION.findall(text)) / max(1, ar) > 0.3:
        quality.append("arabic_presentation_forms")
    page_area = W * H
    big_images = [i for i in raw["images"] if _area(i["bbox"]) >= 0.85 * page_area]
    if big_images and n_chars < 50:
        quality.append("no_text_layer_scanned")
    elif big_images and n_chars >= 50:
        quality.append("full_page_image_with_text_layer")
    if raw["drawings"] is None:
        quality.append("drawings_unreadable")
    if raw["tables"] is None:
        quality.append("table_detection_failed")
    out["extraction"] = m(quality or ["ok"], None,
                          "U+FFFD/private-use share, Arabic presentation-form share, full-page images vs text",
                          "medium", "inferred")

    # ── scripts / direction ──
    letters = ar + la
    if not letters:
        script = "none"
    elif ar / letters >= 0.8:
        script = "arabic_rtl"
    elif la / letters >= 0.8:
        script = "latin_ltr"
    else:
        script = "bilingual"
    out["script"] = m({"class": script, "arabic_letters": ar, "latin_letters": la}, "chars",
                      "Unicode script of extracted letters (≥80 % one script, else bilingual)", "high"
                      if letters >= 200 else "medium", "inferred")

    # ── fonts ──
    fonts: Dict[Tuple, int] = {}
    for b in blocks:
        for ln in b["lines"]:
            for fname, size, flags, color, n in ln["spans"]:
                fi = font_info(fname, flags)
                key = (fi["family"], fi["name"], r1(size), fi["weight"], fi["weight_source"], fi["italic"])
                fonts[key] = fonts.get(key, 0) + n
    out["fonts"] = m([{"family": k[0], "font": k[1], "size_pt": k[2], "weight": k[3], "weight_source": k[4],
                       "italic": k[5], "chars": v} for k, v in sorted(fonts.items(), key=lambda kv: -kv[1])[:12]],
                     "pt", "span font name/size/flags; weight from the font name, else the bold flag", "high")

    # ── blocks: alignment, direction, headings, leading ──
    blk_out, leading = [], []
    for b in blocks:
        lines = b["lines"]
        btext = " ".join(ln["text"] for ln in lines)
        bar, bla = _script(btext)
        rtl = bar > bla
        size = statistics.median(ln["size"] for ln in lines)
        align, aconf = _alignment(lines, rtl)
        role = "text"
        if body_size and size >= body_size * 1.15 and len(lines) <= 3:
            role = "heading_candidate"
        elif body_size and size <= body_size * 0.85:
            role = "small_text"
        for a, c in zip(lines, lines[1:]):
            if abs(a["size"] - c["size"]) < 0.3 and a["dir"] == (1, 0) == c["dir"]:
                dy = c["origin_y"] - a["origin_y"]
                if 0.8 * a["size"] < dy < 3 * a["size"]:
                    leading.append((r1(a["size"]), dy / a["size"]))
        blk_out.append({"bbox": [r1(v) for v in b["bbox"]], "lines": len(lines), "size_pt": r1(size),
                        "direction": "rtl" if rtl else "ltr", "alignment": align, "alignment_confidence": aconf,
                        "role": role, "font": _SUBSET.sub("", max(lines, key=lambda x: len(x["text"]))["font"])})
    out["text_blocks"] = m(blk_out, "pt", "extracted text blocks; per-block alignment from line-edge spread "
                           "(own confidence), role from size vs document body size", "high", "measured+inferred")
    by_size: Dict[float, List[float]] = {}
    for s, ratio in leading:
        by_size.setdefault(s, []).append(ratio)
    out["line_spacing"] = m({str(s): {"ratio_median": r2(statistics.median(v)), "samples": len(v)}
                             for s, v in sorted(by_size.items()) if len(v) >= 3},
                            "× font size", "baseline distance of consecutive same-size lines in a block / size",
                            "high", "measured")

    # ── content box & margins ──
    drawings = raw["drawings"] or []
    bleed, background = [], []
    marks = []
    for dr in drawings:
        bb = dr["bbox"]
        if _area(bb) >= 0.5 * page_area and dr["fill"]:
            background.append(dr)
            continue
        touches = bb[0] <= 1 or bb[1] <= 1 or bb[2] >= W - 1 or bb[3] >= H - 1
        if touches:
            bleed.append(dr)
            continue
        marks.append(bb)
    text_box = _union([b["bbox"] for b in blocks])
    rk = lambda ln, b: running_key(ln, H, len(b["lines"]), W)   # noqa: E731
    run_lines = [(ln, rk(ln, b)) for b in blocks for ln in b["lines"] if rk(ln, b) in running]
    body_box = _union([ln["bbox"] for b in blocks for ln in b["lines"] if rk(ln, b) not in running])
    content = _union([b["bbox"] for b in blocks] + [i["bbox"] for i in raw["images"]
                                                     if _area(i["bbox"]) < 0.85 * page_area] + marks)

    def margins(box):
        if not box:
            return None
        return {"top": r1(box[1]), "bottom": r1(H - box[3]), "left": r1(box[0]), "right": r1(W - box[2]),
                "top_mm": r1(box[1] * MM), "bottom_mm": r1((H - box[3]) * MM),
                "left_mm": r1(box[0] * MM), "right_mm": r1((W - box[2]) * MM)}
    out["margins_text"] = m(margins(text_box), "pt", "page edge to union of extracted text lines "
                            "(includes running headers/footers)", "high" if text_box else "low")
    out["margins_body"] = m(margins(body_box), "pt", "page edge to union of text lines excluding running "
                            "headers/footers (lines repeated in the top/bottom 12 % on ≥50 % of pages)",
                            "high" if body_box else "low", "measured+inferred")
    out["running_elements"] = m([{"band": k[1], "bbox": [r1(v) for v in ln["bbox"]],
                                  "size_pt": r1(ln["size"])} for ln, k in run_lines], "pt",
                                "lines matching a running header/footer of this document", "medium", "inferred")
    out["margins_content"] = m(margins(content), "pt", "page edge to union of text, images and drawings "
                               "(full-page backgrounds and edge-touching bleed shapes excluded)",
                               "medium" if content else "low")
    out["content_box"] = [r1(v) for v in content] if content else None

    # ── body columns (inferred) ──
    body_blocks = [b for b in blocks if body_size and abs(statistics.median(ln["size"] for ln in b["lines"])
                                                          - body_size) <= 0.15 * body_size and len(b["lines"]) >= 2]
    cols = _merge_intervals([(b["bbox"][0], b["bbox"][2]) for b in body_blocks], gap=2)
    if body_blocks:
        gutters = [r1(b[0] - a[1]) for a, b in zip(cols, cols[1:])]
        conf = "high" if len(body_blocks) >= 4 else "medium" if len(body_blocks) >= 2 else "low"
        out["columns"] = m({"count": len(cols), "intervals": [[r1(a), r1(b)] for a, b in cols],
                            "gutters_pt": gutters}, "pt",
                           "disjoint horizontal extents of multi-line body-size text blocks", conf, "inferred")
    else:
        out["columns"] = m(None, None, "no multi-line body text on page", "low", "inferred")

    # ── density / whitespace ──
    text_area = sum(_area(b["bbox"]) for b in blocks)
    img_area = sum(_area(i["bbox"]) for i in raw["images"])
    out["density"] = m({"text_area_share": r2(min(1, text_area / page_area)),
                        "image_area_share": r2(min(1, img_area / page_area)),
                        "content_box_share": r2(_area(content) / page_area) if content else 0.0,
                        "chars_per_1000pt2": r2(n_chars / (page_area / 1000))},
                       "share of page area", "sum of block/image bounding boxes over page area "
                       "(overlaps double-counted)", "medium", "measured")

    # ── colours, backgrounds, rules, shapes ──
    text_colors: Dict[str, int] = {}
    for b in blocks:
        for ln in b["lines"]:
            for _, _, _, color, n in ln["spans"]:
                if color:
                    text_colors[color] = text_colors.get(color, 0) + n
    fills: Dict[str, float] = {}
    rules = []
    shapes = 0
    cw = (content[2] - content[0]) if content else W
    table_boxes = [t["bbox"] for t in raw["tables"] or []]

    def in_table(bb):
        return any(bb[0] >= t[0] - 1 and bb[2] <= t[2] + 1 and bb[1] >= t[1] - 1 and bb[3] <= t[3] + 1
                   for t in table_boxes)
    for dr in drawings:
        bb = dr["bbox"]
        if in_table(bb):          # cell borders and row fills belong to the table, not to rules/shapes
            if dr["fill"]:
                fills[dr["fill"]] = fills.get(dr["fill"], 0.0) + _area(bb)
            continue
        w, h = bb[2] - bb[0], bb[3] - bb[1]
        if dr["fill"]:
            fills[dr["fill"]] = fills.get(dr["fill"], 0.0) + _area(bb)
        thin_h, thin_v = h <= 2.5 and w >= 0.15 * cw, w <= 2.5 and h >= 0.1 * H
        if thin_h or thin_v:
            rules.append({"orientation": "horizontal" if thin_h else "vertical",
                          "length_pt": r1(w if thin_h else h),
                          "thickness_pt": r2(max(dr["width"], min(w, h))),
                          "color": dr["stroke"] or dr["fill"], "bbox": [r1(v) for v in bb]})
        elif dr["fill"] and _area(bb) < 0.5 * page_area:
            shapes += 1
    out["colors"] = m({"text": [{"color": c, "chars": n, "accent": is_accent(c)}
                                for c, n in sorted(text_colors.items(), key=lambda kv: -kv[1])[:8]],
                       "fills": [{"color": c, "area_pt2": round(a), "accent": is_accent(c)}
                                 for c, a in sorted(fills.items(), key=lambda kv: -kv[1])[:8]]},
                      "sRGB hex", "span colours (by characters) and filled-path colours (by area)", "high")
    out["backgrounds"] = m([{"color": dr["fill"], "share": r2(_area(dr["bbox"]) / page_area)} for dr in background],
                           None, "filled paths covering ≥50 % of the page", "high")
    out["rules"] = m(rules[:20], "pt", "drawing paths thinner than 2.5 pt and ≥15 % of the content width "
                     "(horizontal) or ≥10 % of page height (vertical)", "medium")
    out["shapes"] = m({"filled_shapes": shapes, "bleed_elements": len(bleed)}, "count",
                      "filled drawing paths (not rules/backgrounds); paths touching the page edge", "medium")

    # ── tables ──
    tabs = []
    for t in raw["tables"] or []:
        x0, y0, x1, y1 = t["bbox"]
        col_edges = sorted({r1(c[0]) for c in t["cells"]})
        widths = [r1(b - a) for a, b in zip(col_edges, col_edges[1:] + [r1(x1)])]
        pads = []
        for c in t["cells"]:
            inner = [ln["bbox"] for b in blocks for ln in b["lines"]
                     if ln["bbox"][0] >= c[0] - 0.5 and ln["bbox"][2] <= c[2] + 0.5
                     and ln["bbox"][1] >= c[1] - 0.5 and ln["bbox"][3] <= c[3] + 0.5]
            if inner:
                u = _union(inner)
                pads.append((u[0] - c[0], u[1] - c[1]))
        in_fills = [dr for dr in drawings if dr["fill"] and dr["bbox"][0] >= x0 - 1 and dr["bbox"][2] <= x1 + 1
                    and dr["bbox"][1] >= y0 - 1 and dr["bbox"][3] <= y1 + 1
                    and (dr["bbox"][2] - dr["bbox"][0]) >= 0.5 * (x1 - x0)]
        row_fills = sorted({(r1(dr["bbox"][1]), dr["fill"]) for dr in in_fills})
        header_fill = next((f for y, f in row_fills if y <= y0 + 2), None)
        body_fills = [f for y, f in row_fills if y > y0 + 2]
        banded = len(body_fills) >= 2 and len(set(body_fills)) >= 1 and len(body_fills) < t["rows"]
        conf = "medium" if t["empty_cells"] <= t["rows"] * t["cols"] * 0.3 else "low"
        tabs.append({"bbox": [r1(v) for v in t["bbox"]], "rows": t["rows"], "cols": t["cols"],
                     "column_widths_pt": widths[:t["cols"]],
                     "cell_padding_pt": {"left": r1(statistics.median(p[0] for p in pads)),
                                         "top": r1(statistics.median(p[1] for p in pads))} if pads else None,
                     "header_fill": header_fill, "banded_rows": banded, "confidence": conf})
    out["tables"] = m(tabs, "pt", "PyMuPDF find_tables(strategy='lines') — ruled tables only; "
                      "padding = cell edge to text; banding = full-width fills inside the table",
                      "medium", "inferred")

    # ── images and vector graphics ──
    imgs = []
    cbox = content or (0, 0, W, H)
    for im in raw["images"]:
        bb = im["bbox"]
        w, h = bb[2] - bb[0], bb[3] - bb[1]
        pos = ("full_bleed" if _area(bb) >= 0.85 * page_area else
               "full_width" if w >= 0.9 * (cbox[2] - cbox[0]) else
               "left" if (bb[0] + bb[2]) / 2 < W * 0.4 else "right" if (bb[0] + bb[2]) / 2 > W * 0.6 else "center")
        near = None
        for b in blocks:
            tb = b["bbox"]
            if tb[2] < bb[0] or tb[0] > bb[2]:
                continue
            gap_below, gap_above = tb[1] - bb[3], bb[1] - tb[3]
            for where, gap in (("below", gap_below), ("above", gap_above)):
                if 0 <= gap <= 24 and (near is None or gap < near["gap_pt"]):
                    size = statistics.median(ln["size"] for ln in b["lines"])
                    near = {"position": where, "gap_pt": r1(gap), "size_pt": r1(size),
                            "smaller_than_body": bool(body_size and size < body_size * 0.95)}
        dpi = None
        if im["px"][0] and w > 0:
            dpi = round(im["px"][0] / (w / 72))
        imgs.append({"bbox": [r1(v) for v in bb], "aspect": r2(w / h) if h else None, "placement": pos,
                     "effective_dpi": dpi, "nearest_text": near})
    out["images"] = m(imgs, "pt", "image placements (get_image_info); nearest text block within 24 pt "
                      "above/below = caption candidate", "high")
    regions = _vector_regions(drawings, rules, raw["tables"] or [], W, H)
    out["vector_graphics"] = m(regions, "pt", "clusters of ≥12 drawing paths outside tables/rules/backgrounds "
                               "(possible charts or diagrams)", "low", "inferred")
    return out


def _vector_regions(drawings, rules, tables, W, H):
    tb = [t["bbox"] for t in tables]
    pts = []
    for dr in drawings:
        bb = dr["bbox"]
        if _area(bb) >= 0.5 * W * H:
            continue
        if any(bb[0] >= t[0] - 1 and bb[2] <= t[2] + 1 and bb[1] >= t[1] - 1 and bb[3] <= t[3] + 1 for t in tb):
            continue
        pts.append(bb)
    regions: List[list] = []
    for bb in sorted(pts):
        for rg in regions:
            u = rg[0]
            if bb[0] <= u[2] + 6 and bb[2] >= u[0] - 6 and bb[1] <= u[3] + 6 and bb[3] >= u[1] - 6:
                rg[0] = _union([u, bb])
                rg[1] += 1
                break
        else:
            regions.append([bb, 1])
    out = []
    for bb, n in regions:
        if n >= 12 and _area(bb) > 2000:
            out.append({"bbox": [r1(v) for v in bb], "paths": n,
                        "aspect": r2((bb[2] - bb[0]) / (bb[3] - bb[1])) if bb[3] > bb[1] else None})
    return out


def spread_evidence(raw: dict) -> Optional[dict]:
    """A landscape page made of two facing pages: aspect ≈ two portrait pages and no
    text line crossing a central gutter. Inferred, medium confidence."""
    W, H = raw["width"], raw["height"]
    if W <= H:
        return None
    aspect = W / H
    if not 1.25 <= aspect <= 1.6:
        return None
    lines = [ln["bbox"] for b in raw["blocks"] for ln in b["lines"]]
    crossing = sum(1 for bb in lines if bb[0] < W / 2 - 4 and bb[2] > W / 2 + 4)
    left = sum(1 for bb in lines if bb[2] <= W / 2)
    right = sum(1 for bb in lines if bb[0] >= W / 2)
    if lines and crossing == 0 and left and right:
        return {"aspect": r2(aspect), "lines_left": left, "lines_right": right, "lines_crossing_center": 0}
    return None
