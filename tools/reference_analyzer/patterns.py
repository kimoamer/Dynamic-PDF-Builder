"""
Cross-document patterns, proposed as design recipes with evidence.

A pattern is *recurring* only when at least ``min_support`` distinct
documents show it; otherwise it is a single-document *observation*. Every
entry lists the documents and pages it rests on. All patterns are inferred
(``status: proposal — needs human review``); proposals describe roles and
ranges, never brand colours, artwork or page layouts to copy.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional



def _bin(v: float, edges: List[float], labels: List[str]) -> str:
    for e, lab in zip(edges, labels):
        if v <= e:
            return lab
    return labels[-1]


def _ev(f: dict, measured: dict, pages: Optional[List[int]] = None) -> dict:
    return {"doc_id": f["doc_id"], "file": f["file"], "pages": (pages or [p["page"] for p in f["pages"][:1]])[:20],
            "measured": measured}


def _text_pages(f):
    return [p["page"] for p in f["pages"] if p["chars"]["value"] >= 200][:20]


def _group(features: List[dict], key: Callable[[dict], Optional[str]], measured: Callable[[dict], dict],
           pages: Callable[[dict], List[int]]) -> Dict[str, List[dict]]:
    groups: Dict[str, List[dict]] = {}
    for f in features:
        k = key(f)
        if k is not None:
            groups.setdefault(k, []).append(_ev(f, measured(f), pages(f)))
    return groups


def template_families(features: List[dict]) -> List[List[dict]]:
    """Documents that are one template refilled: same page count and formats, same body size, same fonts
    and same top and side margins (the bottom moves with the text). They are separate records but one
    design, so they support a pattern once. Related documents of different length (a report and its
    summary edition) stay independent."""
    groups: Dict[tuple, List[dict]] = {}
    for f in features:
        fonts = sorted({x["family"] for p in f["pages"] for x in p["fonts"]["value"][:3]})
        sizes = sorted({(p["size"]["value"]["width_pt"], p["size"]["value"]["height_pt"]) for p in f["pages"]})
        margins = f["summary"]["margins_body_median"]["value"]
        if fonts and margins and len(f["pages"]) >= 2:
            key = (len(f["pages"]), tuple(sizes), f["summary"]["body_size"]["value"], tuple(fonts),
                   tuple(round(margins[k]) for k in ("top", "left", "right")))
            groups.setdefault(key, []).append(f)
    return [g for _, g in sorted(groups.items(), key=lambda kv: kv[1][0]["file"]) if len(g) > 1]


def build_patterns(features: List[dict], min_support: int = 2, content_id: Optional[Dict[str, str]] = None) -> dict:
    """``content_id`` maps doc_id → design identity (SHA-256, or a template family) so that copies and
    refills of one design count once as support. Compilations show in the evidence but support nothing."""
    S = lambda f, k: f["summary"][k]["value"]          # noqa: E731
    candidates = []

    # 1. body size
    for lab, ev in _group(features, lambda f: _bin(S(f, "body_size"), [9.4, 10.4, 11.4], ["≤9.4 pt", "9.5–10.4 pt",
                                                                                       "10.5–11.4 pt", "≥11.5 pt"])
                          if S(f, "body_size") else None,
                          lambda f: {"body_size_pt": S(f, "body_size")}, _text_pages).items():
        vals = [e["measured"]["body_size_pt"] for e in ev]
        candidates.append({"id": f"body-size-{lab}", "category": "typography",
                           "title": f"Body text set at {lab}",
                           "proposal": {"recipe_field": "base_size", "range_pt": [min(vals), max(vals)]},
                           "evidence": ev})
    # 2. leading
    for lab, ev in _group(features, lambda f: _bin(S(f, "line_spacing_body"), [1.25, 1.4, 1.55],
                                                   ["≤1.25×", "1.26–1.40×", "1.41–1.55×", ">1.55×"])
                          if S(f, "line_spacing_body") else None,
                          lambda f: {"line_height": S(f, "line_spacing_body")}, _text_pages).items():
        vals = [e["measured"]["line_height"] for e in ev]
        candidates.append({"id": f"leading-{lab}", "category": "typography", "title": f"Body leading {lab} the size",
                           "proposal": {"recipe_field": "line_height", "range": [min(vals), max(vals)]},
                           "evidence": ev})
    # 3. heading ramp
    for lab, ev in _group(features, lambda f: _bin(S(f, "heading_hierarchy")[0]["ratio_to_body"], [1.5, 2.0, 2.6],
                                                   ["H1 ≤1.5× body", "H1 1.5–2.0× body", "H1 2.0–2.6× body",
                                                    "H1 >2.6× body"]) if S(f, "heading_hierarchy") else None,
                          lambda f: {"levels": [[lv["size_pt"], lv["ratio_to_body"]] for lv in S(f, "heading_hierarchy")]},
                          lambda f: S(f, "heading_hierarchy")[0]["pages"]).items():
        ratios = [[lv[1] for lv in e["measured"]["levels"][:3]] for e in ev]
        candidates.append({"id": f"heading-ramp-{lab}", "category": "hierarchy", "title": f"Heading ramp with {lab}",
                           "proposal": {"recipe_field": "heading_scale",
                                        "h1_range": [min(r[0] for r in ratios), max(r[0] for r in ratios)],
                                        "levels_observed": sorted({len(r) for r in ratios})},
                           "evidence": ev})
    # 4. side margins (facing documents: odd-page values, i.e. inner/outer, not a mixed median)
    def side(f):
        return S(f, "facing_pages")["odd"] if S(f, "facing_pages") else S(f, "margins_body_median")
    for lab, ev in _group(features, lambda f: _bin(min(side(f)["left"], side(f)["right"]) * 25.4 / 72,
                                                   [12.5, 17.5, 22.5], ["≤12 mm", "13–17 mm", "18–22 mm", "≥23 mm"])
                          if side(f) else None,
                          lambda f: {"margins_pt": side(f), "facing": bool(S(f, "facing_pages"))},
                          _text_pages).items():
        candidates.append({"id": f"side-margins-{lab}", "category": "layout", "title": f"Side margins {lab}",
                           "proposal": {"recipe_field": "margins",
                                        "left_pt": [min(e["measured"]["margins_pt"]["left"] for e in ev),
                                                    max(e["measured"]["margins_pt"]["left"] for e in ev)],
                                        "right_pt": [min(e["measured"]["margins_pt"]["right"] for e in ev),
                                                     max(e["measured"]["margins_pt"]["right"] for e in ev)],
                                        "note": "body-text margins; running headers/footers excluded"},
                           "evidence": ev})
    # 5. facing pages / spreads
    ev = [_ev(f, S(f, "facing_pages"), _text_pages(f)) for f in features if S(f, "facing_pages")]
    if ev:
        candidates.append({"id": "facing-pages", "category": "layout", "title": "Mirrored (inner/outer) margins",
                           "proposal": {"layout_rule": "odd/even pages mirror inner and outer margins"},
                           "evidence": ev})
    ev = [_ev(f, {"spread_pages": len(S(f, "spreads"))}, [s["page"] for s in S(f, "spreads")])
          for f in features if S(f, "spreads")]
    if ev:
        candidates.append({"id": "spreads", "category": "layout", "title": "Two-page spreads as single sheets",
                           "proposal": {"layout_rule": "content composed across a facing pair"}, "evidence": ev})
    # 6. multi-column body
    ev = []
    for f in features:
        # the denominator is every text page: pages the column reading could not classify count against the share
        text = [p for p in f["pages"] if p["chars"]["value"] >= 200]
        classified = [p for p in text if p["columns"]["value"] and p["columns"]["confidence"] in ("high", "medium")]
        multi = [p["page"] for p in classified if p["columns"]["value"]["count"] >= 2]
        if text and len(multi) / len(text) >= 0.3:
            ev.append(_ev(f, {"multi_column_pages": len(multi), "text_pages": len(text),
                              "unclassified_pages": len(text) - len(classified),
                              "share_of_text_pages": round(len(multi) / len(text), 2)}, multi))
    if ev:
        candidates.append({"id": "multi-column-body", "category": "layout", "title": "Body text in two or more columns",
                           "proposal": {"layout_rule": "multi-column body text on ≥30 % of text pages"},
                           "evidence": ev})
    # 7. accent colour system (role only — no colour values are proposed)
    ev = []
    for f in features:
        acc = S(f, "accent_colors")
        if 1 <= len(acc) <= 3:
            ev.append(_ev(f, {"recurring_accent_colours": len(acc),
                              "pages_with_main_accent": acc[0]["pages"]}, acc[0]["first_pages"]))
    if ev:
        candidates.append({"id": "restrained-accent", "category": "colour",
                           "title": "One to three recurring accent colours",
                           "proposal": {"theme_rule": "a small accent set used consistently across pages "
                                                      "(roles only; brand colours are not copied)"},
                           "evidence": ev})
    # 8. tables
    ev = [_ev(f, S(f, "tables"), [p["page"] for p in f["pages"] if p["tables"]["value"]])
          for f in features if S(f, "tables")["count"]]
    banded = [e for e in ev if (e["measured"]["banded_share"] or 0) >= 0.5]
    header = [e for e in ev if (e["measured"]["header_fill_share"] or 0) >= 0.5]
    if banded:
        candidates.append({"id": "tables-banded", "category": "tables", "title": "Banded (zebra) table rows",
                           "proposal": {"table_rule": "alternating row fills"}, "evidence": banded})
    if header:
        candidates.append({"id": "tables-header-fill", "category": "tables", "title": "Filled table header row",
                           "proposal": {"table_rule": "header row with a fill"}, "evidence": header})
    pads = [e for e in ev if e["measured"]["padding_left_median_pt"] is not None]
    if pads:
        vals = [e["measured"]["padding_left_median_pt"] for e in pads]
        candidates.append({"id": "table-padding", "category": "tables", "title": "Measured table cell padding",
                           "proposal": {"table_rule": "horizontal cell padding",
                                        "range_pt": [min(vals), max(vals)]}, "evidence": pads})
    # 9. captions
    for where in ("below", "above"):
        def caption_pages(f):
            return [p["page"] for p in f["pages"] for i in p["images"]["value"] if i["nearest_text"]
                    and i["nearest_text"]["position"] == where and i["nearest_text"]["smaller_than_body"]]
        ev = [_ev(f, S(f, "images"), sorted(set(caption_pages(f)))) for f in features if S(f, "images")[f"caption_{where}"]]
        if ev:
            candidates.append({"id": f"captions-{where}", "category": "figures",
                               "title": f"Image captions set {where} the image in smaller type",
                               "proposal": {"figure_rule": f"caption {where} figure"}, "evidence": ev})
    # 10. RTL / bilingual
    for cls, title in (("arabic_rtl", "Arabic RTL documents"), ("bilingual", "Bilingual pages")):
        ev = []
        for f in features:
            n = S(f, "scripts").get(cls, 0)
            if n:
                al = {k: v for k, v in S(f, "alignment").items() if k.startswith("rtl:")}
                ev.append(_ev(f, {"pages": n, "rtl_block_alignment": al},
                              [p["page"] for p in f["pages"] if p["script"]["value"]["class"] == cls]))
        if ev:
            candidates.append({"id": f"script-{cls}", "category": "rtl", "title": title,
                               "proposal": {"layout_rule": "measured RTL block alignment per document"},
                               "evidence": ev})

    compilations = {f["doc_id"] for f in features if not S(f, "design_uniformity")["single_design"]}
    recurring, observations = [], []
    for c in candidates:
        c["support_docs"] = len({(content_id or {}).get(e["doc_id"], e["doc_id"]) for e in c["evidence"]
                                 if e["doc_id"] not in compilations})
        c["evidence_files"] = len(c["evidence"])
        c["basis"] = "inferred"
        c["status"] = "proposal — needs human review"
        c["confidence"] = "medium" if c["support_docs"] >= 3 else "low"
        (recurring if c["support_docs"] >= min_support else observations).append(c)
    recurring.sort(key=lambda c: (-c["support_docs"], c["id"]))
    observations.sort(key=lambda c: c["id"])
    return {"min_support_docs": min_support, "documents_analysed": len(features),
            "recurring": recurring, "observations": observations,
            "note": "Patterns are inferred from measured values and point to source pages. They are proposals for "
                    "human review, not measurements, and never imply aesthetic quality: how often a pattern occurs says "
                    "where it was seen, not that it is good. Do not copy commercial "
                    "branding, artwork or layouts into distributed runtime assets."}
