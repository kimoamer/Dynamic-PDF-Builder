"""
Results, report and blind gallery of the M7.4 comparison.

Automated facts only: this module never decides that a page looks better, and
every recipe's human review stays ``pending`` until exported judgments exist.
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
M7 = os.path.join(HERE, "..", "m7")
sys.path.insert(0, os.path.join(HERE, "..", ".."))

from dynamic_pdf.design import EVIDENCE_RECIPES  # noqa: E402
from dynamic_pdf.design.evidence_gate import safety_failures  # noqa: E402

FORMAT ="dynamic-pdf-builder/m74-human-preferences"
REASONS = ["hierarchy", "whitespace", "readability", "density", "columns", "tables", "page breaks",
           "RTL / Arabic", "DOCX fidelity", "other"]
MEASURE_MAX = 90          # chars per line above which the engine's readability score starts to fall


def load(out: str) -> dict:
    docs: dict = {}
    for p in sorted(glob.glob(os.path.join(out, "records", "*.json"))):
        with open(p, encoding="utf-8") as f:
            r = json.load(f)
        docs.setdefault(f"{r['recipe']}/{r['name']}", {})[r["variant"]] = r
    return {k: v for k, v in docs.items() if len(v) == 2}


def _seq_defects(r) -> int:
    c = r["content"]
    return sum(len(s["missing"]) + len(s["duplicated"]) + len(s["reordered"])
               for s in (c["pdf_sequence"], c["docx_sequence"]))


def facts(r) -> dict:
    t, d, rd = r["typography"], r["density"], r["readability"]
    rtl = r.get("rtl") or {}
    return {
        "PDF pages": r["pages"], "DOCX pages": r["docx_qa"]["pages"],
        "body size (pt)": t["body_size"], "leading": t["line_height"], "H1 / body": t["h1_ratio"],
        "chars per line (median)": rd["median_chars_per_line"],
        "readability score (engine heuristic)": rd["score_readability"],
        "line gaps clear of ink": r["line_clearance"]["clear_share"],
        "chars per page": d["chars_per_page"], "mean body page fill": d["mean_body_page_fill"],
        "underfilled body pages": d["underfilled_body_pages"],
        "tables": r["tables"]["tables"], "tables split across pages": r["tables"]["split_tables"],
        "pages with tables": r["tables"]["pages_with_tables"],
        "RTL paragraphs right-aligned": r["layout"]["rtl_right_aligned_share"],
        "RTL line order defects": len(rtl.get("line_order_defects", [])),
        "harakat source / PDF / DOCX": "/".join(str(rtl.get(k)) for k in ("harakat_source", "harakat_pdf", "harakat_docx")),
        "missing words PDF / DOCX": f"{len(r['content']['pdf_missing_words'])} / {len(r['content']['docx_missing_words'])}",
        "sequence defects": _seq_defects(r),
        "PDF QA": r["pdf_qa"]["status"], "DOCX QA": r["docx_qa"]["status"],
        "PDF render cold / warm (s)": f"{r['timing']['pdf_cold_s']} / {r['timing']['pdf_warm_s']}",
        "DOCX render cold / warm (s)": f"{r['timing']['docx_cold_s']} / {r['timing']['docx_warm_s']}",
        "peak memory (MB)": r["peak_rss_mb"],
    }


def assess(base: dict, prop: dict) -> dict:
    """Defects the recipe introduced, and measured changes in either direction."""
    gate = prop["gate"]
    defects = safety_failures(gate["baseline"], gate["proposed"]) if gate and gate["proposed"] else []
    for label, key in (("PDF", "pdf_qa"), ("DOCX", "docx_qa")):
        defects += [f"new {label} QA error: {e}" for e in prop[key]["errors"] if e not in base[key]["errors"]]
        defects += [f"new {label} QA warning: {w}" for w in prop[key]["warnings"] if w not in base[key]["warnings"]]
    c = prop["content"]
    if len(c["pdf_missing_words"]) > len(base["content"]["pdf_missing_words"]):
        defects.append("words missing from the PDF")
    if len(c["docx_missing_words"]) > len(base["content"]["docx_missing_words"]):
        defects.append("words missing from the DOCX")
    if _seq_defects(prop) > _seq_defects(base):
        defects.append("paragraph sequence defects")
    rtl_b, rtl_p = base.get("rtl") or {}, prop.get("rtl") or {}
    if len(rtl_p.get("line_order_defects", [])) > len(rtl_b.get("line_order_defects", [])):
        defects.append("RTL line order defects")
    if rtl_p.get("harakat_pdf") != rtl_b.get("harakat_pdf") or rtl_p.get("harakat_docx") != rtl_b.get("harakat_docx"):
        defects.append("harakat count changed")
    share_b, share_p = base["layout"]["rtl_right_aligned_share"], prop["layout"]["rtl_right_aligned_share"]
    if share_b is not None and (share_p is None or share_p < share_b):
        defects.append(f"RTL right alignment {share_b} → {share_p}")
    eb, ep = base["docx_editability"], prop["docx_editability"]
    for k in ("word_tables", "source_tables_editable", "heading_styles", "images", "text_chars"):
        if ep[k] < eb[k]:
            defects.append(f"DOCX {k} {eb[k]} → {ep[k]}")
    if prop["network_attempts"]:
        defects.append("network attempts")

    gains, costs = [], []
    cb, cp = base["readability"]["median_chars_per_line"], prop["readability"]["median_chars_per_line"]
    if cb and cp and cb > MEASURE_MAX >= cp:
        gains.append(f"chars per line {cb:g} → {cp:g}, back inside {MEASURE_MAX}")
    fb, fp = base["typography"]["body_size"], prop["typography"]["body_size"]
    if fp > fb:
        gains.append(f"body size {fb:g} → {fp:g} pt")
    elif fp < fb:
        costs.append(f"body size {fb:g} → {fp:g} pt")
    pb, pp = base["pages"], prop["pages"]
    if pp != pb:
        (gains if pp < pb else costs).append(f"pages {pb} → {pp}")
    sb, sp = base["tables"]["split_tables"], prop["tables"]["split_tables"]
    if sp != sb:
        (gains if sp < sb else costs).append(f"split tables {sb} → {sp}")
    rb, rp = base["readability"]["score_readability"], prop["readability"]["score_readability"]
    if rb is not None and rp is not None and abs(rp - rb) >= 0.03:
        (gains if rp > rb else costs).append(f"readability score {rb:.2f} → {rp:.2f}")
    kb, kp = base["line_clearance"]["clear_share"], prop["line_clearance"]["clear_share"]
    if kb is not None and kp is not None and kp < kb - 0.02:
        costs.append(f"line gaps clear of ink {kb:.0%} → {kp:.0%}")
    db, dp = base["density"]["mean_body_page_fill"], prop["density"]["mean_body_page_fill"]
    if db is not None and dp is not None and dp < db - 0.05:
        costs.append(f"mean body page fill {db:.2f} → {dp:.2f}")
    return {"defects": defects, "gains": gains, "costs": costs}


def summarise(docs: dict) -> dict:
    recipes: dict = {}
    for key, d in docs.items():
        name = key.split("/")[0]
        a = assess(d["baseline"], d["proposed"])
        spec = EVIDENCE_RECIPES[name]
        r = recipes.setdefault(name, {"status": spec.status, "status_reason": spec.status_reason, "documents": {},
                                      "human_review": {"status": "pending", "judgments": 0}})
        r["documents"][key.split("/")[1]] = a
    for r in recipes.values():
        items = r["documents"].values()
        r["documents_total"] = len(r["documents"])
        r["documents_with_defects"] = sum(bool(a["defects"]) for a in items)
        r["documents_with_gains_and_no_costs"] = sum(bool(a["gains"]) and not a["costs"] and not a["defects"]
                                                     for a in items)
    return recipes


def _table(head, rows):
    return "\n".join(["| " + " | ".join(head) + " |", "|" + "---|" * len(head)] +
                     ["| " + " | ".join(str(c) for c in row) + " |" for row in rows])


def report_md(docs: dict, recipes: dict) -> str:
    out = ["# M7.4 comparison: automated facts", "",
           "Identical content, rendered with the existing design (baseline) and with the recipe forced on "
           "(proposed). Human review is pending for every recipe: nothing here is a preference.", ""]
    for name, r in recipes.items():
        out += [f"## {name}", "", f"**Status: {r['status']}.** {r['status_reason']}.", "",
                f"{r['documents_total']} documents, {r['documents_with_defects']} with defects, "
                f"{r['documents_with_gains_and_no_costs']} with measured gains and no measured costs.", ""]
        rows = []
        for doc, a in r["documents"].items():
            b, p = docs[f"{name}/{doc}"]["baseline"], docs[f"{name}/{doc}"]["proposed"]
            rows.append([doc, f"{b['pages']} → {p['pages']}",
                         f"{b['typography']['body_size']:g}/{b['typography']['line_height']:g} → "
                         f"{p['typography']['body_size']:g}/{p['typography']['line_height']:g}",
                         f"{b['readability']['median_chars_per_line']} → {p['readability']['median_chars_per_line']}",
                         f"{b['density']['mean_body_page_fill']} → {p['density']['mean_body_page_fill']}",
                         f"{b['tables']['split_tables']} → {p['tables']['split_tables']}",
                         f"{b['pdf_qa']['status']} → {p['pdf_qa']['status']}",
                         f"{b['timing']['pdf_warm_s']} → {p['timing']['pdf_warm_s']}",
                         f"{b['peak_rss_mb']} → {p['peak_rss_mb']}"])
        out += [_table(["document", "pages", "size/leading", "chars per line", "body page fill", "split tables",
                        "PDF QA", "PDF warm s", "peak MB"], rows), ""]
        for doc, a in r["documents"].items():
            out.append(f"* **{doc}**: gains: {'; '.join(a['gains']) or 'none'}. Costs: {'; '.join(a['costs']) or 'none'}. "
                       f"Defects: {'; '.join(a['defects']) or 'none'}.")
        out.append("")
    return "\n".join(out)


def gallery(out: str, docs: dict, recipes: dict) -> None:
    """Offline, blind A/B gallery; judgments stay in the browser until exported as JSON."""
    items = []
    renderer = "no renderer on this machine; see the CI artifact"
    for key, d in docs.items():
        b, p = d["baseline"], d["proposed"]
        renderer = b.get("docx_renderer", renderer)
        recipe, doc = key.split("/")
        a = recipes[recipe]["documents"][doc]
        flip = int(hashlib.sha256(key.encode()).hexdigest(), 16) % 2 == 1
        first, second = ("proposed", "baseline") if flip else ("baseline", "proposed")
        items.append({"name": key, "category": recipe, "size": b["profile"], "A": first, "B": second,
                      "sheets": {k: d[k]["sheets"] for k in d},
                      "pages": {k: d[k]["pages"] for k in d},
                      "docx_pages": {k: d[k]["docx_qa"]["pages"] for k in d},
                      "layout_id": {k: d[k]["layout_id"] for k in d},
                      "facts": {k: facts(d[k]) for k in d},
                      "score": {k: d[k]["score"]["value"] for k in d},
                      "qa": {k: [d[k]["pdf_qa"]["status"], d[k]["docx_qa"]["status"]] for k in d},
                      "verdict": "defects found" if a["defects"] else "no defects found",
                      "notes": a["defects"] + a["gains"] + a["costs"],
                      "findings": {k: d[k]["pdf_qa"]["errors"] + d[k]["docx_qa"]["errors"] +
                                   [f"warning: {w}" for w in d[k]["pdf_qa"]["warnings"] + d[k]["docx_qa"]["warnings"]]
                                   for k in d}})
    with open(os.path.join(M7, "gallery_template.html"), encoding="utf-8") as f:
        tpl = f.read()
    data = {"docs": items, "reasons": REASONS, "variant": "proposed", "format": FORMAT, "docx_renderer": renderer,
            "storage_key": "m74-recipe-review-v1", "facts_label": "fact"}
    os.makedirs(os.path.join(out, "gallery"), exist_ok=True)
    with open(os.path.join(out, "gallery", "index.html"), "w", encoding="utf-8") as f:
        f.write(tpl.replace("/*__DATA__*/null", json.dumps(data, ensure_ascii=False)))


def build(out: str) -> None:
    docs = load(out)
    recipes = summarise(docs)
    keep = ("recipe", "name", "variant", "profile", "direction", "pages", "layout_id", "typography", "columns",
            "density", "readability", "line_clearance", "tables", "pdf_qa", "docx_qa", "timing", "peak_rss_mb",
            "rtl", "gate", "docx_renderer")
    res = {"format": "dynamic-pdf-builder/m74-comparison", "version": 1, "recipes": recipes,
           "documents": {k: {v: {f: r.get(f) for f in keep} for v, r in d.items()} for k, d in docs.items()}}
    with open(os.path.join(out, "results.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    with open(os.path.join(out, "report.md"), "w", encoding="utf-8") as f:
        f.write(report_md(docs, recipes))
    gallery(out, docs, recipes)


if __name__ == "__main__":
    build(os.path.abspath(sys.argv[1]))
