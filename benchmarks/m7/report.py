"""
Build ``results.json``, ``report.md`` and the offline gallery from worker results.

    python benchmarks/m7/report.py OUT_DIR

Automated metrics only. Verdicts compare *score-independent* facts (pages,
underfilled pages, separated/pushed figures, QA errors, content checks,
measure) so a change in the internal score alone can never count as an
improvement; score-only gains are flagged.
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REASONS = ["whitespace", "page breaks", "table grouping", "figure placement", "hierarchy",
           "RTL / Arabic", "readability", "density", "DOCX fidelity", "other"]


def _load(out):
    res = {}
    for p in sorted(glob.glob(os.path.join(out, "results", "*.json"))):
        with open(p, encoding="utf-8") as f:
            r = json.load(f)
        res.setdefault(r["name"], {})[r["variant"]] = r
    return res


def facts(r) -> dict:
    """Score-independent quality facts of one rendered variant (lower is better, except where noted)."""
    c, lay = r["content"], r["layout"]
    seq = [c["pdf_sequence"], c["docx_sequence"]]
    return {
        "pages": r["pages"],
        "underfilled_pages": len(lay["underfilled_body_pages"]),
        "separated_figures": int(r["score"]["separated_figures"] or 0),
        "figures_after_gap": len(lay["figures_after_gap"]),
        "oversize_figures": len(lay["oversize_figures"]),
        "hard_errors": len(r["score"]["hard_errors"]),
        "pdf_qa_errors": len(r["pdf_qa"]["errors"]),
        "docx_qa_errors": len(r["docx_qa"]["errors"]),
        "missing_words": len(c["pdf_missing_words"]) + len(c["docx_missing_words"]),
        "sequence_defects": sum(len(s["missing"]) + len(s["duplicated"]) + len(s["reordered"]) for s in seq),
        "geometry_duplicates": len(lay["geometry_duplicates"]),
        "rtl_line_order_defects": len(r.get("rtl", {}).get("line_order_defects", [])),
        "symbol_font_spans": r.get("rtl", {}).get("symbol_font_text_spans", 0),
        "cpl_over_90": max(0.0, round((r["score"]["cpl"] or 0) - 90, 1)),
    }


def verdict(base, smart) -> tuple:
    if smart.get("composition", {}).get("strategy") == "baseline":
        return "unchanged (designed layout kept)", []
    fb, fs = facts(base), facts(smart)
    better = [k for k in fb if fs[k] < fb[k]]
    worse = [k for k in fb if fs[k] > fb[k]]
    notes = [f"{k} {fb[k]}→{fs[k]}" for k in better + worse]
    if better and not worse:
        v = "improved"
    elif worse and not better:
        v = "regressed"
    elif better and worse:
        v = "mixed"
    else:
        v = "no measurable change"
        if (smart["score"]["value"] or 0) > (base["score"]["value"] or 0) + 0.5:
            v += " (score-only gain — not counted)"
    return v, notes


def gates(res) -> list:
    """(gate, status, detail) across every document and variant."""
    rows = []

    def chk(name, bad):
        rows.append((name, "PASS" if not bad else "FAIL", "; ".join(bad[:6]) or "—"))
    allr = [(n, v, r) for n, d in res.items() for v, r in d.items()]
    chk("No missing words (PDF and DOCX)", [f"{n}/{v}: {r['content']['pdf_missing_words'][:3]}"
                                             f"{r['content']['docx_missing_words'][:3]}" for n, v, r in allr
                                             if r['content']['pdf_missing_words'] or r['content']['docx_missing_words']])
    chk("No duplicated / reordered / lost paragraphs", [
        f"{n}/{v}/{k}: {s}" for n, v, r in allr for k in ("pdf_sequence", "docx_sequence")
        for s in [r["content"][k]] if s["missing"] or s["duplicated"] or s["reordered"]] +
        [f"{n}/{v}: geometry dup {r['layout']['geometry_duplicates']}" for n, v, r in allr
         if r["layout"]["geometry_duplicates"]])
    chk("No hard layout violations (clipping, stranded heading, detached caption, order)",
        [f"{n}/{v}: {r['score']['hard_errors'][:2]}" for n, v, r in allr if r["score"]["hard_errors"]])
    chk("PDF QA has no errors", [f"{n}/{v}: {r['pdf_qa']['errors'][:2]}" for n, v, r in allr if r["pdf_qa"]["errors"]])
    chk("DOCX QA (LibreOffice layout) has no errors",
        [f"{n}/{v}: {r['docx_qa']['errors'][:2]}" for n, v, r in allr if r["docx_qa"]["errors"]])
    chk("DOCX QA actually verified (not UNVERIFIED)",
        [f"{n}/{v}: {r['docx_qa']['unverified']}" for n, v, r in allr if r["docx_qa"]["status"] == "unverified"])
    chk("Smart composition never regresses a document",
        [f"{n}: {verdict(d['baseline'], d['smart'])[1]}" for n, d in res.items()
         if "baseline" in d and "smart" in d and verdict(d["baseline"], d["smart"])[0] in ("regressed", "mixed")])
    chk("Every source table is an editable Word table",
        [f"{n}/{v}: {e['source_tables_editable']}/{e['source_tables']}" for n, v, r in allr
         for e in [r["docx_editability"]] if e["source_tables_editable"] < e["source_tables"]])
    chk("Every heading is a Word heading style",
        [f"{n}/{v}: {e['heading_styles']}/{e['source_headings']}" for n, v, r in allr
         for e in [r["docx_editability"]] if e["heading_styles"] < e["source_headings"]])
    chk("Arabic paragraphs right-aligned (RTL documents)",
        [f"{n}/{v}: {r['layout']['rtl_right_aligned_share']}" for n, v, r in allr
         if r["layout"]["rtl_right_aligned_share"] is not None and r["layout"]["rtl_right_aligned_share"] < 0.95])
    chk("Arabic paragraphs read top-to-bottom in the PDF (line order)",
        [f"{n}/{v}: {len(r['rtl']['line_order_defects'])}/{r['rtl']['arabic_paragraphs_checked']} out of order"
         for n, v, r in allr if r.get("rtl", {}).get("line_order_defects")])
    chk("No text drawn with a symbol font (box glyphs)",
        [f"{n}/{v}: {r['rtl']['symbol_font_text_spans']} span(s)" for n, v, r in allr
         if r.get("rtl", {}).get("symbol_font_text_spans")])
    chk("Arabic diacritics preserved (PDF / DOCX)",
        [f"{n}/{v}: source {r['rtl']['harakat_source']}, PDF {r['rtl']['harakat_pdf']}, DOCX {r['rtl']['harakat_docx']}"
         for n, v, r in allr if r.get("rtl", {}).get("harakat_source")
         and min(r["rtl"]["harakat_pdf"], r["rtl"]["harakat_docx"]) < r["rtl"]["harakat_source"]])
    chk("No network access during rendering", [f"{n}/{v}: {r['network_attempts']}" for n, v, r in allr
                                               if r["network_attempts"]])
    chk("No render diagnostics (degraded blocks)", [f"{n}/{v}: {r['diagnostics'][:1]}" for n, v, r in allr
                                                    if r["diagnostics"]])
    return rows


def _md_table(head, rows):
    return "\n".join(["| " + " | ".join(head) + " |", "|" + "---|" * len(head)] +
                     ["| " + " | ".join(str(c) for c in r) + " |" for r in rows])


def build(out: str):
    res = _load(out)
    perf = json.load(open(os.path.join(out, "perf.json"))) if os.path.exists(os.path.join(out, "perf.json")) else None
    with open(os.path.join(out, "results.json"), "w", encoding="utf-8") as f:
        json.dump({"documents": res, "perf": perf}, f, ensure_ascii=False, indent=1)
    L = ["# M7 benchmark report (automated)", "",
         "Generated by `benchmarks/m7/run.py`. Automated metrics only — no human ratings. Verdicts use "
         "score-independent facts; the internal layout score is shown for reference and never counts alone.", ""]
    rows = []
    for n, d in res.items():
        b, s = d.get("baseline"), d.get("smart")
        if not (b and s):
            continue
        v, notes = verdict(b, s)
        rows.append([n, b["category"], b["size"], f"{b['pages']} / {s['pages']}",
                     f"{b['score']['value']} / {s['score']['value']}", s["composition"]["strategy"],
                     f"{b['pdf_qa']['status']} / {s['pdf_qa']['status']}",
                     f"{b['docx_qa']['status']} / {s['docx_qa']['status']}", v, "; ".join(notes) or "—"])
    L += ["## Smart composition vs designed baseline", "",
          _md_table(["document", "category", "size", "pages B/S", "score B/S", "strategy", "PDF QA B/S",
                     "DOCX QA B/S", "verdict", "changed facts"], rows), ""]
    L += ["## Quality gates", "", _md_table(["gate", "status", "detail"], gates(res)), ""]
    frows = []
    for n, d in res.items():
        for v, r in d.items():
            fx = facts(r)
            lay = r["layout"]
            frows.append([n, v, fx["pages"], ", ".join(map(str, lay["underfilled_body_pages"])) or "—",
                          fx["separated_figures"], ", ".join(map(str, lay["figures_after_gap"])) or "—",
                          ", ".join(map(str, lay["oversize_figures"])) or "—", r["score"]["cpl"],
                          lay["rtl_right_aligned_share"] if lay["rtl_right_aligned_share"] is not None else "—",
                          ", ".join(r["pdf_qa"]["warnings"] + r["docx_qa"]["warnings"]) or "—"])
    L += ["## Layout facts per variant", "",
          "underfilled = body pages < 60 % filled; figures after gap = figure blocks starting a page after an "
          "underfilled body page; cpl = characters per body line (comfortable 55–90).", "",
          _md_table(["document", "variant", "pages", "underfilled pages", "separated figs", "figures after gap",
                     "oversize figs", "cpl", "RTL right-aligned", "QA warnings"], frows), ""]
    prow = []
    for n, d in res.items():
        for v, r in d.items():
            t, c = r["timing"], r.get("composition") or {}
            prow.append([n, r["size"], v, r["pages"], t["pdf_cold_s"], t["pdf_warm_s"], t["docx_cold_s"],
                         t["docx_warm_s"], r["memory"]["rss_peak_mb"], r["renders"],
                         c.get("candidates_considered", "—"), c.get("candidates_rendered", "—")])
    L += ["## Rendering performance (CPU-only, one process per document)", "",
          "cold = first render in a fresh process (includes lazy imports, font registration); warm = repeat "
          "with a new builder in the same process. renders = layout renders incl. design page-fit renders.", "",
          _md_table(["document", "size", "variant", "pages", "PDF cold s", "PDF warm s", "DOCX cold s",
                     "DOCX warm s", "peak RSS MB", "renders", "candidates", "rendered"], prow), ""]
    agg = []
    for size in ("small", "medium", "long"):
        for v in ("baseline", "smart"):
            rs = [d[v] for d in res.values() if v in d and d[v]["size"] == size]
            if rs:
                agg.append([size, v, len(rs), round(statistics.median(r["timing"]["pdf_warm_s"] for r in rs), 3),
                            round(max(r["timing"]["pdf_warm_s"] for r in rs), 3),
                            round(statistics.median(r["timing"]["docx_warm_s"] for r in rs), 3),
                            round(statistics.median(r["memory"]["rss_peak_mb"] for r in rs), 1),
                            round(max(r["memory"]["rss_peak_mb"] for r in rs), 1),
                            round(statistics.mean(r["renders"] for r in rs), 1)])
    L += ["### By size class", "", _md_table(["size", "variant", "docs", "PDF warm median s", "PDF warm max s",
                                              "DOCX warm median s", "peak RSS median MB", "peak RSS max MB",
                                              "mean renders"], agg), ""]
    if perf:
        L += ["## Packaging and import audit", "",
              f"* Python {perf['python']}, {perf['cpu_count']} CPU(s).",
              f"* `import dynamic_pdf`: median {perf['import_s_median']} s (min {perf['import_s_min']} s) over 7 "
              f"cold processes; peak RSS after import {perf['import_rss_mb_median']} MB.",
              f"* Modules loaded by `import dynamic_pdf`: {', '.join(perf['modules_loaded_by_import'])}.",
              f"* Heavy modules loaded after a text-only PDF + DOCX render: "
              f"{', '.join(perf['heavy_modules_after_text_only_render']) or 'none'}.",
              f"* Core dependency closure on disk: {perf['core_closure_mb']} MB; packages pulled in only by "
              f"Matplotlib: {perf['matplotlib_only_mb']} MB ({', '.join(perf['matplotlib_only_packages'])}).", "",
              _md_table(["package (all submodules)", "import self-time s"], perf["importtime_self_s_by_package"]), "",
              _md_table(["package", "version", "MB"], [[n, v["version"], v["mb"]]
                                                        for n, v in sorted(perf["core_closure"].items(),
                                                                           key=lambda kv: -(kv[1]["mb"] or 0))]), "",
              "Optional extras installed here (MB): " + ", ".join(f"{k} {v}" for k, v in
                                                                  perf["optional_installed_mb"].items()), ""]
    with open(os.path.join(out, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    gallery(out, res)


def gallery(out: str, res: dict):
    """Offline, blind A/B gallery; labels are stored in the browser and exported as JSON."""
    docs = []
    for n, d in res.items():
        if not ("baseline" in d and "smart" in d):
            continue
        flip = int(hashlib.sha256(n.encode()).hexdigest(), 16) % 2 == 1
        a, b = ("smart", "baseline") if flip else ("baseline", "smart")
        v, notes = verdict(d["baseline"], d["smart"])
        docs.append({"name": n, "category": d["baseline"]["category"], "size": d["baseline"]["size"],
                     "A": a, "B": b, "sheets": {k: d[k]["sheets"] for k in ("baseline", "smart")},
                     "pages": {k: d[k]["pages"] for k in ("baseline", "smart")},
                     "docx_pages": {k: d[k]["docx_qa"]["pages"] for k in ("baseline", "smart")},
                     "layout_id": {k: d[k]["layout_id"] for k in ("baseline", "smart")},
                     "facts": {k: facts(d[k]) for k in ("baseline", "smart")},
                     "score": {k: d[k]["score"]["value"] for k in ("baseline", "smart")},
                     "qa": {k: [d[k]["pdf_qa"]["status"], d[k]["docx_qa"]["status"]] for k in ("baseline", "smart")},
                     "strategy": d["smart"]["composition"]["strategy"], "verdict": v, "notes": notes,
                     "findings": {k: d[k]["pdf_qa"]["errors"] + d[k]["docx_qa"]["errors"] +
                                  [f"warning: {w}" for w in d[k]["pdf_qa"]["warnings"] + d[k]["docx_qa"]["warnings"]]
                                  for k in ("baseline", "smart")}})
    with open(os.path.join(HERE, "gallery_template.html"), encoding="utf-8") as f:
        tpl = f.read()
    page = tpl.replace("/*__DATA__*/null", json.dumps({"docs": docs, "reasons": REASONS}, ensure_ascii=False))
    os.makedirs(os.path.join(out, "gallery"), exist_ok=True)
    with open(os.path.join(out, "gallery", "index.html"), "w", encoding="utf-8") as f:
        f.write(page)


if __name__ == "__main__":
    build(os.path.abspath(sys.argv[1]))
