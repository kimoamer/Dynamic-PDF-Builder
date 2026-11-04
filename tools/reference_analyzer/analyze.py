"""Document-level analysis: two passes per PDF, then summaries and recipe mapping."""
from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from typing import Dict, List, Optional

from .measure import classify_page, extract_page, is_accent, m, r1, r2, running_key, spread_evidence


def running_elements(raws: List[dict]) -> frozenset:
    """Header/footer lines repeated (digits normalised) on ≥50 % of pages (min. 2 pages)."""
    if len(raws) < 2:
        return frozenset()
    cnt: Counter = Counter()
    for raw in raws:
        cnt.update({k for b in raw["blocks"] for ln in b["lines"]
                    for k in [running_key(ln, raw["height"], len(b["lines"]), raw["width"])] if k})
    need = max(2, -(-len(raws) // 2))
    return frozenset(k for k, n in cnt.items() if n >= need)

# DesignRecipe fields this analysis can fill from measurements (dynamic_pdf/design/recipes.py)
RECIPE_FIELDS = ("base_size", "line_height", "heading_scale", "margins")


def body_size_of(raws: List[dict]) -> Optional[float]:
    """Character-weighted most common span size (0.5 pt bins)."""
    c: Counter = Counter()
    for raw in raws:
        for b in raw["blocks"]:
            for ln in b["lines"]:
                for _, size, _, _, n in ln["spans"]:
                    c[round(size * 2) / 2] += n
    return c.most_common(1)[0][0] if c else None


def _median(v):
    v = [x for x in v if x is not None]
    return r1(statistics.median(v)) if v else None


def _heading_levels(pages: List[dict], body: float) -> List[dict]:
    sizes: Dict[float, List[int]] = defaultdict(list)
    for pg in pages:
        for b in pg["text_blocks"]["value"]:
            if b["role"] == "heading_candidate":
                sizes[round(b["size_pt"] * 2) / 2].append(pg["page"])
    clusters: List[list] = []
    for s in sorted(sizes, reverse=True):
        if clusters and clusters[-1][0] - s <= 0.6:
            clusters[-1][1].extend(sizes[s])
        else:
            clusters.append([s, list(sizes[s])])
    out = []
    for size, pgs in clusters:
        if len(pgs) < 2 and len(pages) > 3:
            continue                          # a one-off (cover title, pull quote) is not a level
        out.append({"size_pt": size, "ratio_to_body": r2(size / body), "occurrences": len(pgs),
                    "pages": sorted(set(pgs))[:30]})
    for i, lv in enumerate(out[:6], 1):
        lv["level"] = i
    return out[:6]


def _nearest_recipe(cand: dict) -> Optional[dict]:
    try:
        from dynamic_pdf.design.recipes import RECIPES
    except Exception:
        return None
    best = None
    for prof, rc in RECIPES.items():
        d = 0.0
        if cand.get("base_size"):
            d += abs(rc.base_size - cand["base_size"]) / 2
        if cand.get("line_height"):
            d += abs(rc.line_height - cand["line_height"]) / 0.2
        if cand.get("heading_scale"):
            d += abs(rc.heading_scale[0] - cand["heading_scale"][0]) / 0.5
        if cand.get("margins"):
            d += sum(abs(a - b) for a, b in zip(rc.margins, cand["margins"])) / 4 / 18
        if best is None or d < best[0]:
            best = (d, prof.value, rc)
    if not best:
        return None
    d, name, rc = best
    return {"profile": name, "distance": r2(d), "recipe": {"base_size": rc.base_size, "line_height": rc.line_height,
                                                           "heading_scale": rc.heading_scale[:3],
                                                           "margins": list(rc.margins)}}


def analyze_document(path: str, rec: dict, progress=None) -> dict:
    """design-features record for one readable PDF (+ warnings)."""
    import pymupdf
    warns: List[dict] = []
    raws = []
    with pymupdf.open(path) as doc:
        for p in doc:
            try:
                raws.append(extract_page(p))
            except Exception as e:
                warns.append({"page": p.number + 1, "code": "page_extraction_failed", "severity": "warning",
                              "message": f"{type(e).__name__}: {e}"})
            if progress:
                progress(p.number + 1, doc.page_count)
    body = body_size_of(raws)
    running = running_elements(raws)
    pages = [classify_page(raw, body, running) for raw in raws]
    spreads = []
    for raw in raws:
        ev = spread_evidence(raw)
        if ev:
            spreads.append({"page": raw["number"], **ev})

    # ── page-level warnings ──
    for pg in pages:
        q = pg["extraction"]["value"]
        for code in q:
            if code != "ok":
                sev = "warning" if code in ("broken_text_extraction", "no_text_layer_scanned") else "info"
                warns.append({"page": pg["page"], "code": code, "severity": sev,
                              "message": {"broken_text_extraction": "extracted text has replacement/private-use "
                                                                    "characters — font measurements kept, text unreliable",
                                          "arabic_presentation_forms": "Arabic extracted as presentation forms "
                                                                       "(normalise with NFKC; order may be visual)",
                                          "no_text_layer_scanned": "page is a full-page image with no text layer "
                                                                   "(scanned) — typography not measurable",
                                          "full_page_image_with_text_layer": "full-page image with a text layer "
                                                                             "(possibly OCR) — geometry is approximate",
                                          "drawings_unreadable": "vector drawings could not be read",
                                          "table_detection_failed": "table detection failed"}.get(code, code)})
        amb = [b for b in pg["text_blocks"]["value"] if b["alignment"] == "ambiguous"]
        if len(amb) >= 3:
            warns.append({"page": pg["page"], "code": "ambiguous_alignment", "severity": "info",
                          "message": f"{len(amb)} multi-line blocks with no consistent alignment"})
    for sp in spreads:
        warns.append({"page": sp["page"], "code": "spread_detected", "severity": "info",
                      "message": "landscape page with two halves and no text across the centre — likely a "
                                 "two-page spread; margins and columns are measured on the whole sheet"})

    # one warning per code with its pages (a 200-page document must stay reviewable)
    grouped: Dict[tuple, dict] = {}
    for w in warns:
        g = grouped.setdefault((w["code"], w["severity"]), {"code": w["code"], "severity": w["severity"],
                                                            "message": w["message"], "pages": []})
        if w.get("page"):
            g["pages"].append(w["page"])
    warns = []
    for g in grouped.values():
        n = len(g["pages"])
        if g["code"] == "ambiguous_alignment":
            g["message"] = "multi-line blocks with no consistent alignment"
        g["page_count"] = n
        g["pages"] = g["pages"][:60]
        if n:
            g["page"] = g["pages"][0]
        warns.append(g)

    # ── document summaries ──
    text_pages = [pg for pg in pages if pg["chars"]["value"] >= 200]
    lead = [float(pg["line_spacing"]["value"][str(r1(body))]["ratio_median"]) for pg in pages
            if body and str(r1(body)) in pg["line_spacing"]["value"]]
    levels = _heading_levels(pages, body) if body else []

    def margin_stats(sel, key="margins_body"):
        ms = [pg[key]["value"] for pg in sel if pg[key]["value"]]
        return {k: _median([x[k] for x in ms]) for k in ("top", "bottom", "left", "right")} if ms else None
    odd = margin_stats([p for p in text_pages if p["page"] % 2 == 1])
    even = margin_stats([p for p in text_pages if p["page"] % 2 == 0])
    allm = margin_stats(text_pages)
    alltext = margin_stats(text_pages, "margins_text")
    facing = None
    if odd and even and len(text_pages) >= 4:
        dl, dr = odd["left"] - even["left"], odd["right"] - even["right"]
        if abs(dl) >= 6 and abs(dr) >= 6 and dl * dr < 0:
            facing = m({"odd": odd, "even": even, "inner_minus_outer_pt": r1(abs(dl))}, "pt",
                       "median body margins of odd vs even pages are mirrored", "medium", "inferred")
    col_counts = Counter(pg["columns"]["value"]["count"] for pg in text_pages
                         if pg["columns"]["value"] and pg["columns"]["confidence"] in ("high", "medium"))
    align = Counter()
    for pg in text_pages:
        for b in pg["text_blocks"]["value"]:
            if b["role"] == "text" and b["alignment_confidence"] != "low":
                align[(b["direction"], b["alignment"])] += 1
    scripts = Counter(pg["script"]["value"]["class"] for pg in pages)
    accent_pages: Dict[str, set] = defaultdict(set)
    for pg in pages:
        c = pg["colors"]["value"]
        for t in c["text"] + c["fills"]:
            if t["accent"]:
                accent_pages[t["color"]].add(pg["page"])
        for rl in pg["rules"]["value"]:
            if is_accent(rl["color"]):
                accent_pages[rl["color"]].add(pg["page"])
    need = max(2, round(0.2 * len(pages)))
    accents = [{"color": c, "pages": len(p), "first_pages": sorted(p)[:10]}
               for c, p in sorted(accent_pages.items(), key=lambda kv: -len(kv[1])) if len(p) >= need][:6]
    tables = [t for pg in pages for t in pg["tables"]["value"]]
    images = [dict(i, page=pg["page"]) for pg in pages for i in pg["images"]["value"]]
    rules = [dict(rl, page=pg["page"]) for pg in pages for rl in pg["rules"]["value"]
             if rl["orientation"] == "horizontal"]

    cand = {"base_size": body, "line_height": r2(statistics.median(lead)) if lead else None,
            "heading_scale": [lv["ratio_to_body"] for lv in levels[:3]] or None,
            "margins": [allm["top"], allm["bottom"], allm["left"], allm["right"]] if allm else None}
    summary = {
        "body_size": m(body, "pt", "character-weighted most common font size (0.5 pt bins)",
                       "high" if body else "low"),
        "heading_hierarchy": m(levels, "pt", "multi-line ≤3 blocks ≥1.15× body size, sizes clustered within "
                               "0.6 pt, ≥2 occurrences, ordered by size", "medium", "inferred"),
        "line_spacing_body": m(cand["line_height"], "× body size",
                               "median of per-page baseline-distance ratios at body size",
                               "high" if len(lead) >= 3 else "low", "measured"),
        "margins_body_median": m(allm, "pt", "median body-text margins (running headers/footers excluded) over "
                                 "pages with ≥200 characters", "high" if allm else "low", "measured+inferred"),
        "margins_text_median": m(alltext, "pt", "median margins of all text incl. running headers/footers",
                                 "high" if alltext else "low"),
        "running_elements": m([{"band": b, "text_pattern": t[:60]} for t, b in sorted(running, key=lambda k: (k[1], k[0]))],
                              None, "top/bottom-band lines repeated on ≥50 % of pages (digits normalised)",
                              "medium", "inferred"),
        "facing_pages": facing or m(None, None, "odd/even margins not mirrored (or <4 text pages)", "medium",
                                    "inferred"),
        "spreads": m(spreads, None, "landscape pages ~2 portrait pages wide with no text across the centre",
                     "medium", "inferred"),
        "viewer_page_layout": m(rec.get("page_layout"), None, "document catalog /PageLayout", "high"),
        "columns": m(dict(sorted(col_counts.items())), "pages", "pages by body column count "
                     "(high/medium confidence pages only)", "medium", "inferred"),
        "alignment": m({f"{d}:{a}": n for (d, a), n in sorted(align.items())}, "blocks",
                       "body blocks by direction and alignment", "medium", "inferred"),
        "scripts": m(dict(sorted(scripts.items())), "pages", "pages by script class", "high", "inferred"),
        "accent_colors": m(accents, "pages", f"saturated colours used in text, fills or rules on ≥{need} pages",
                           "high", "measured"),
        "rules": m({"pages_with_horizontal_rules": len({rl.get('page') for rl in rules}) if rules else 0,
                    "count": len(rules), "thickness_median_pt": r2(statistics.median(r["thickness_pt"] for r in rules))
                    if rules else None}, "pt", "thin horizontal drawing paths", "medium"),
        "tables": m({"count": len(tables), "banded_share": r2(sum(t["banded_rows"] for t in tables) / len(tables))
                     if tables else None,
                     "header_fill_share": r2(sum(bool(t["header_fill"]) for t in tables) / len(tables))
                     if tables else None,
                     "padding_left_median_pt": _median([t["cell_padding_pt"]["left"] for t in tables
                                                        if t["cell_padding_pt"]]),
                     "padding_top_median_pt": _median([t["cell_padding_pt"]["top"] for t in tables
                                                       if t["cell_padding_pt"]])},
                    "pt", "ruled tables (find_tables lines strategy)", "medium", "inferred"),
        "images": m({"count": len(images), "placement": dict(Counter(i["placement"] for i in images)),
                     "caption_below": sum(1 for i in images if i["nearest_text"] and
                                          i["nearest_text"]["position"] == "below"
                                          and i["nearest_text"]["smaller_than_body"]),
                     "caption_above": sum(1 for i in images if i["nearest_text"] and
                                          i["nearest_text"]["position"] == "above"
                                          and i["nearest_text"]["smaller_than_body"])},
                    None, "image placements; caption = smaller-than-body text within 24 pt", "medium", "inferred"),
        "vector_graphics": m(sum(len(pg["vector_graphics"]["value"]) for pg in pages), "regions",
                             "clusters of drawing paths (possible charts/diagrams)", "low", "inferred"),
    }
    cand_clean = {k: v for k, v in cand.items() if v}
    recipe = {"fields": cand_clean, "mapped_to": "dynamic_pdf.design.recipes.DesignRecipe "
                                                 "(margins = top, bottom, left, right in pt)",
              "nearest_existing_recipe": _nearest_recipe(cand_clean), "basis": "inferred",
              "status": "proposal — needs human review"}
    return {"doc_id": rec["doc_id"], "file": rec["file"], "summary": summary, "recipe_candidate": recipe,
            "pages": pages}, warns


def preview_pages(features: dict, limit: int) -> List[int]:
    """Deterministic, representative pages: first, then pages with tables, images,
    vector graphics, spreads, multi-column text, distinct scripts; then evenly spaced."""
    pages = features["pages"]
    chosen: List[int] = []

    def add(n):
        if n not in chosen and len(chosen) < limit:
            chosen.append(n)
    if pages:
        add(pages[0]["page"])
    for key in ("tables", "images", "vector_graphics"):
        for pg in pages:
            if pg[key]["value"]:
                add(pg["page"])
                break
    for sp in features["summary"]["spreads"]["value"]:
        add(sp["page"])
        break
    for pg in pages:
        if pg["columns"]["value"] and pg["columns"]["value"]["count"] >= 2:
            add(pg["page"])
            break
    seen = set()
    for pg in pages:
        cls = pg["script"]["value"]["class"]
        if cls not in seen:
            seen.add(cls)
            add(pg["page"])
    n = len(pages)
    for k in range(1, limit + 1):
        if n:
            add(pages[min(n - 1, round(k * (n - 1) / (limit + 1)))]["page"])
    return sorted(chosen)
