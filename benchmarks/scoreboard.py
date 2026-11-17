"""
One scoreboard over one corpus: every fixture in ``tests/fixtures`` and the stress documents
the tests use.

    python benchmarks/scoreboard.py OUT_DIR [--docs a,b] [--quick] [--no-office]
                                    [--budgets benchmarks/scoreboard_baseline.json]
                                    [--write-baseline benchmarks/scoreboard_baseline.json]

For each document it measures the stable designed export, the page forecast against the real
render, three variants (timed, as a caller would run them) and every applicable direction
(gates, pages, LibreOffice page counts). It writes ``scoreboard.json`` and ``scoreboard.md``.

``--budgets FILE`` compares the summary with the ``budgets`` of a committed baseline and exits
with status 1 when a number regressed beyond them. ``--write-baseline FILE`` stores this run as
the baseline, with budgets derived from it. These are measurements, not judgements of beauty.
"""
from __future__ import annotations

import argparse
import glob
import io
import itertools
import json
import os
import statistics
import sys
import tempfile
import time
import tracemalloc
import warnings

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

SCOREBOARD_VERSION = 1
NEAR_EMPTY_FILL = 0.25          # the last page's content ends in its top quarter
# summary metric -> (better: "higher" | "lower", allowed slack when deriving budgets)
METRICS = {
    "gate_pass_rate": ("higher", 0.0),
    "near_empty_last_pages": ("lower", 0),
    "page_growth_max": ("lower", 0.1),
    "docx_page_parity": ("higher", 0.02),      # a rate over the designs that passed, whose number varies
    "forecast_page_exact": ("higher", 0.0),
    "forecast_score_mae": ("lower", 0.25),
    "variants3_median_s": ("lower", "x2"),       # timing varies by machine and load
    "peak_mb_max": ("lower", "x1.5"),
    "valid_variants_mean": ("higher", 0.2),      # a slow machine can run out of the time budget
}


def corpus():
    """Name -> function(asset_dir) returning a fresh DocumentBuilder."""
    from dynamic_pdf import DocumentBuilder
    from stress_docs import STRESS
    out = {}
    for path in sorted(glob.glob(os.path.join(ROOT, "tests", "fixtures", "*.md"))):
        with open(path, encoding="utf-8") as f:
            text = f.read()
        out[os.path.splitext(os.path.basename(path))[0]] = lambda d, t=text: DocumentBuilder.from_markdown(t)
    out.update({f"stress_{k}": v for k, v in STRESS.items()})
    return out


def _facts(pdf: bytes) -> dict:
    from tools.design_learning.layout_facts import measure
    return measure(pdf)


def _near_empty(facts: dict) -> bool:
    return facts.get("pages", 0) > 1 and facts.get("last_page_fill", 1.0) < NEAR_EMPTY_FILL


def _office_pages(docx: bytes):
    from dynamic_pdf.qa.docx_checks import docx_to_pdf
    import pymupdf
    pdf = docx_to_pdf(docx)
    if not pdf:
        return None
    with pymupdf.open(stream=pdf, filetype="pdf") as d:
        return d.page_count


def _forecast(b) -> dict:
    """Predicted pages and score of the designed layout, against its real render."""
    from dynamic_pdf.intelligence.analysis import measure_blocks, simulate
    from dynamic_pdf.intelligence.geometry import Geometry
    from dynamic_pdf.intelligence.scoring import score_layout
    from dynamic_pdf.layout.engine import LayoutEngine
    from dynamic_pdf.themes import get_theme
    doc, theme = b._prepared_base()
    theme = theme or get_theme(doc.theme)
    ms, fg = measure_blocks(doc, theme, b._policy, {})
    pred_geo = simulate(ms, fg)
    pred = score_layout(pred_geo, doc, theme)
    geo = Geometry()
    LayoutEngine(doc, policy=b._policy, theme=theme, geometry=geo).render(io.BytesIO())
    real = score_layout(geo, doc, theme)
    return {"predicted_pages": len(pred_geo.pages), "pages": len(geo.pages),
            "predicted_score": pred.score, "score": real.score,
            "score_error": round(abs(pred.score - real.score), 2),
            "predicted_utilization": pred.metrics.get("utilization"), "utilization": real.metrics.get("utilization")}


def _distance(a: dict, b: dict) -> float:
    """How far apart two rendered designs are, on a few measured facts scaled to about 0..1."""
    keys = {"body_size": 12, "pages": 10, "cover_image_share": 1, "cover_colour_share": 1, "opener_page_share": 1,
            "page_kind_entropy": 2, "image_share_mean": 0.5, "text_share_mean": 0.5, "font_faces": 6,
            "largest_to_body": 4, "band_words_mean": 20}
    return round(sum(min(1.0, abs(a.get(k, 0) - b.get(k, 0)) / s) for k, s in keys.items()) / len(keys), 3)


def run_doc(name, make, asset_dir, office: bool, quick: bool, ranker=None) -> dict:
    from dynamic_pdf.design.directions import DIRECTIONS
    row = {"doc": name}
    # stable designed export, the default of export()
    b = make(asset_dir)
    plain = b.render()
    import pymupdf
    with pymupdf.open(stream=plain, filetype="pdf") as d:
        row["plain_pages"] = d.page_count
    b = make(asset_dir)
    with tempfile.TemporaryDirectory() as tmp:
        res = b.export(os.path.join(tmp, "out.pdf"), qa=True)
        with open(res.pdf_path, "rb") as f:
            pdf = f.read()
        facts = _facts(pdf)
        docx = b.render_docx()
    row["export"] = {"status": res.status, "pages": res.page_count, "near_empty_last_page": _near_empty(facts),
                     "page_growth": round(res.page_count / row["plain_pages"], 3)}
    if office:
        row["export"]["office_pages"] = _office_pages(docx)
    row["forecast"] = _forecast(make(asset_dir))
    # three variants, timed the way a caller runs them
    b = make(asset_dir)
    t = time.perf_counter()
    vs = b.design_variants(n=3, ranker=ranker)
    sel = vs.stats.get("selection") or {}
    row["variants3"] = {"seconds": round(time.perf_counter() - t, 2), "renders": vs.stats.get("renders"),
                        "recommended": vs.recommended.id if vs.recommended else None,
                        "statuses": [v.report.status for v in vs],
                        # which selector chose, and whether a learned one replaced the fixed choice
                        "selector": sel.get("selector"), "abstained": bool(sel.get("abstained")),
                        "overrode": sel.get("selector") == "learned" and vs.recommended is not None
                        and sel.get("deterministic_choice") != vs.recommended.id,
                        "model": sel.get("model"), "fallback_reason": sel.get("fallback_reason")}
    if quick:
        return row
    # every applicable direction: gates, pages, Word parity through LibreOffice
    b = make(asset_dir)
    tracemalloc.start()
    t = time.perf_counter()
    every = b.design_variants(n=len(DIRECTIONS), office=office)
    seconds = time.perf_counter() - t
    peak = tracemalloc.get_traced_memory()[1] / 2 ** 20
    tracemalloc.stop()
    designs = []
    for v in every:
        rep = v.report
        item = {"direction": v.id, "status": rep.status, "pages": rep.pages,
                "failures": rep.hard_failures[:3]}
        if v.valid and v.pdf:
            f = _facts(v.pdf)
            item.update(near_empty_last_page=_near_empty(f), page_growth=round(rep.pages / row["plain_pages"], 3),
                        facts=f)
            if rep.office:
                item["office_pages"] = rep.office.get("pages")
        designs.append(item)
    valid = [d for d in designs if d["status"] == "valid"]
    pairs = list(itertools.combinations(valid, 2))
    row["directions"] = {"seconds": round(seconds, 2), "peak_mb": round(peak, 1), "designs": designs,
                         "diversity": round(statistics.mean(_distance(a["facts"], b["facts"]) for a, b in pairs), 3)
                         if pairs else 0.0}
    for d in designs:
        d.pop("facts", None)
    return row


def summarize(rows) -> dict:
    designs = [d for r in rows for d in r.get("directions", {}).get("designs", [])]
    attempted = [d for d in designs if d["status"] != "not_rendered"]
    per_direction = {}
    for d in attempted:
        ok, n = per_direction.get(d["direction"], (0, 0))
        per_direction[d["direction"]] = (ok + (d["status"] == "valid"), n + 1)
    valid = [d for d in designs if d["status"] == "valid"]
    parity = [(r["export"]["pages"], r["export"].get("office_pages")) for r in rows]
    parity += [(d["pages"], d.get("office_pages")) for d in valid]
    parity = [(a, b) for a, b in parity if b is not None]
    fc = [r["forecast"] for r in rows]
    statuses = {}
    for r in rows:
        statuses[r["export"]["status"]] = statuses.get(r["export"]["status"], 0) + 1
    variant_statuses = {}
    for d in designs:
        variant_statuses[d["status"]] = variant_statuses.get(d["status"], 0) + 1
    growth = [r["export"]["page_growth"] for r in rows] + [d["page_growth"] for d in valid]
    times = [r["variants3"]["seconds"] for r in rows]
    peaks = [r["directions"]["peak_mb"] for r in rows if "directions" in r]
    return {
        "docs": len(rows),
        "gate_pass_rate": round(len(valid) / len(attempted), 3) if attempted else None,
        "gate_pass_by_direction": {k: f"{ok}/{n}" for k, (ok, n) in sorted(per_direction.items())},
        "near_empty_last_pages": sum(r["export"]["near_empty_last_page"] for r in rows)
        + sum(d["near_empty_last_page"] for d in valid),
        "page_growth_mean": round(statistics.mean(growth), 3),
        "page_growth_max": round(max(growth), 3),
        "docx_page_parity": round(sum(a == b for a, b in parity) / len(parity), 3) if parity else None,
        "docx_page_mismatches": sum(a != b for a, b in parity),
        "docx_designs_compared": len(parity),
        "forecast_page_exact": round(sum(f["predicted_pages"] == f["pages"] for f in fc) / len(fc), 3),
        "forecast_score_mae": round(statistics.mean(f["score_error"] for f in fc), 2),
        "forecast_score_max_error": max(f["score_error"] for f in fc),
        "forecast_utilization_over": sum((f["predicted_utilization"] or 0) > (f["utilization"] or 0) + 0.005
                                         for f in fc),
        "variants3_median_s": round(statistics.median(times), 2),
        "variants3_max_s": max(times),
        "selector": {"learned": sum(r["variants3"].get("selector") == "learned" for r in rows),
                     "overrode": sum(bool(r["variants3"].get("overrode")) for r in rows),
                     "abstained": sum(bool(r["variants3"].get("abstained")) for r in rows),
                     "refused": sum(bool(r["variants3"].get("fallback_reason")) for r in rows)},
        "peak_mb_max": max(peaks) if peaks else None,
        "valid_variants_mean": round(len(valid) / len(rows), 2) if designs else None,
        "diversity_mean": round(statistics.mean(r["directions"]["diversity"] for r in rows), 3)
        if all("directions" in r for r in rows) else None,
        "export_status": statuses,
        "variant_status": variant_statuses,
    }


def budgets_from(summary: dict) -> dict:
    out = {}
    for key, (better, slack) in METRICS.items():
        value = summary.get(key)
        if value is None:
            continue
        if isinstance(slack, str):
            limit = round(value * float(slack[1:]), 2)
        else:
            limit = round(value - slack if better == "higher" else value + slack, 3)
        out[key] = {"min" if better == "higher" else "max": limit}
    return out


def compare(summary: dict, budgets: dict) -> list:
    """Every budget the summary breaks."""
    out = []
    for key, rule in budgets.items():
        value = summary.get(key)
        if value is None:
            continue
        if "min" in rule and value < rule["min"]:
            out.append(f"{key} {value} below its budget {rule['min']}")
        if "max" in rule and value > rule["max"]:
            out.append(f"{key} {value} above its budget {rule['max']}")
    return out


def markdown(summary: dict, rows) -> str:
    lines = ["# Scoreboard", "", "Measurements of rendered pages; nothing here is a judgement of beauty.", "",
             "| Metric | Value |", "| --- | --- |"]
    for k, v in summary.items():
        lines.append(f"| {k} | {json.dumps(v, ensure_ascii=False) if isinstance(v, dict) else v} |")
    lines += ["", "| Document | Plain pages | Export | Forecast pages | Score error | 3 variants (s) "
              "| Valid directions |",
              "| --- | --- | --- | --- | --- | --- | --- |"]
    for r in rows:
        e, f = r["export"], r["forecast"]
        valid = [d["direction"] for d in r.get("directions", {}).get("designs", []) if d["status"] == "valid"]
        lines.append(f"| {r['doc']} | {r['plain_pages']} | {e['pages']} p, {e['status']} | "
                     f"{f['predicted_pages']}/{f['pages']} | {f['score_error']} | {r['variants3']['seconds']} | "
                     f"{', '.join(valid) if 'directions' in r else '-'} |")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("out")
    ap.add_argument("--docs", default="", help="comma-separated document names (default: all)")
    ap.add_argument("--quick", action="store_true", help="skip the every-direction pass")
    ap.add_argument("--no-office", action="store_true", help="skip LibreOffice page counts")
    ap.add_argument("--budgets", default=None, help="baseline JSON whose budgets this run must meet")
    ap.add_argument("--ranker", default=None, help='learned selector for the three-variant pass: "auto" or a model file')
    ap.add_argument("--write-baseline", default=None, help="store this run as the baseline")
    a = ap.parse_args(argv)
    os.environ.setdefault("SOURCE_DATE_EPOCH", "1767225600")
    from dynamic_pdf.qa.docx_checks import office_version
    office = not a.no_office and bool(office_version())
    docs = corpus()
    names = [n for n in a.docs.split(",") if n] or list(docs)
    os.makedirs(a.out, exist_ok=True)
    rows = []
    with tempfile.TemporaryDirectory() as assets, warnings.catch_warnings():
        warnings.simplefilter("ignore")
        docs[names[0]](assets).render()                  # warm imports and fonts outside the timings
        for name in names:
            t = time.perf_counter()
            rows.append(run_doc(name, docs[name], assets, office, a.quick, a.ranker))
            print(f"{name}: {time.perf_counter() - t:.1f}s", flush=True)
    summary = summarize(rows)
    summary["office"] = office
    result = {"version": SCOREBOARD_VERSION, "summary": summary, "documents": rows}
    with open(os.path.join(a.out, "scoreboard.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    with open(os.path.join(a.out, "scoreboard.md"), "w", encoding="utf-8") as f:
        f.write(markdown(summary, rows))
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    if a.write_baseline:
        result["budgets"] = budgets_from(summary)
        history = {}
        if os.path.exists(a.write_baseline):           # earlier baselines stay on record
            with open(a.write_baseline, encoding="utf-8") as f:
                history = json.load(f).get("history", {})
        with open(a.write_baseline, "w", encoding="utf-8") as f:
            json.dump({**{k: result[k] for k in ("version", "summary", "budgets")}, "history": history}, f,
                      ensure_ascii=False, indent=1)
    if a.budgets:
        with open(a.budgets, encoding="utf-8") as f:
            budgets = json.load(f).get("budgets", {})
        if a.quick:      # the every-direction numbers were not measured
            budgets = {k: v for k, v in budgets.items() if summary.get(k) is not None}
        broken = compare(summary, budgets)
        for b in broken:
            print(f"REGRESSION: {b}", file=sys.stderr)
        return 1 if broken else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
