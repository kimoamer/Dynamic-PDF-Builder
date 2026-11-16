"""
M11 page-break optimizer: page facts with the optimizer off and on (offline, CPU-only).

    python benchmarks/m11/run.py                      # PDF facts: golden fixtures, M7 corpus, stress docs
    python benchmarks/m11/run.py --docx               # + DOCX page counts through LibreOffice
    python benchmarks/m11/run.py --docs policy_handbook,proposal --json out.json

For every document in ``design("auto")``: PDF pages, body pages under 60 % full and a
near-empty last page (under a third full), by the scoreboard's definitions
(``layout.breaks.page_facts``); with ``--docx`` the DOCX page count and near-empty last
page as LibreOffice lays it out, and the Word page count the calibration predicts.
Microsoft Word is not run: LibreOffice stands in for it.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
import warnings

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path[:0] = [ROOT, os.path.join(ROOT, "benchmarks", "m7"), os.path.join(ROOT, "tests")]


def _documents(only):
    import tempfile
    from dynamic_pdf import DocumentBuilder
    from corpus import CORPUS
    from stress_docs import STRESS
    out = {}
    for path in sorted(glob.glob(os.path.join(ROOT, "tests", "fixtures", "*.md"))):
        with open(path, encoding="utf-8") as f:
            text = f.read()
        out["fixture:" + os.path.basename(path)[:-3]] = lambda t=text: DocumentBuilder.from_markdown(t)
    for name, (_, _, make) in CORPUS.items():
        out[name] = make
    assets = tempfile.mkdtemp(prefix="m11-assets-")
    for name, make in STRESS.items():
        out["stress:" + name] = lambda m=make: m(assets)
    return {k: v for k, v in out.items() if not only or k.split(":")[-1] in only}


def docx_facts(data: bytes, theme):
    """(pages, near-empty last page) of a DOCX as LibreOffice lays it out, or None."""
    import pymupdf
    from dynamic_pdf.qa.docx_checks import docx_to_pdf
    pdf = docx_to_pdf(data)
    if not pdf:
        return None
    with pymupdf.open(stream=pdf, filetype="pdf") as d:
        sp = theme.spacing
        last = d[-1]
        top, bottom = sp.page_margin_top, last.rect.height - sp.page_margin_bottom
        ys = [b[3] for b in last.get_text("blocks") if b[4].strip() and top - 2 <= b[1] <= bottom + 2]
        fill = (max(ys) - top) / (bottom - top) if ys else 0.0
        return d.page_count, int(d.page_count > 1 and fill < 1 / 3)


def measure(make, docx: bool):
    from dynamic_pdf.layout.breaks import page_facts
    from dynamic_pdf.layout.word_fit import predict_word_pages
    b = make().design("auto")
    t = time.perf_counter()
    doc, theme = b._prepared()
    row = {"prepare_s": round(time.perf_counter() - t, 2), **page_facts(doc, theme)}
    row["log"] = [d.decision for d in b.last_design.layout.decisions if d.target == "pagination"]
    if docx:
        got = docx_facts(b.render_docx(), theme)
        if got:
            row["docx_pages"], row["docx_near_empty_last"] = got
        row["word_predicted"] = predict_word_pages(doc, theme)
    return row


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs", default="")
    ap.add_argument("--docx", action="store_true")
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    warnings.simplefilter("ignore")
    import dynamic_pdf.layout.breaks as B
    real = B.plan_document
    rows = {}
    for name, make in _documents({d for d in a.docs.split(",") if d}).items():
        B.plan_document = lambda *x, **k: ([], [], "off")
        off = measure(make, a.docx)
        B.plan_document = real
        on = measure(make, a.docx)
        rows[name] = {"off": off, "on": on}
        print(f"{name:32} pages {off['pages']:>2}→{on['pages']:<2} underfilled {off['underfilled']}→{on['underfilled']} "
              f"near-empty {off['near_empty_last']}→{on['near_empty_last']} parted {off['separated']}→{on['separated']}"
              + (f" | docx {off.get('docx_pages')}→{on.get('docx_pages')} near-empty "
                 f"{off.get('docx_near_empty_last')}→{on.get('docx_near_empty_last')} "
                 f"predicted {on.get('word_predicted')}" if a.docx else "")
              + f" | {off['prepare_s']}s→{on['prepare_s']}s", flush=True)
    total = {k: {s: sum(r[s].get(k) or 0 for r in rows.values()) for s in ("off", "on")}
             for k in ("pages", "underfilled", "near_empty_last", "separated", "docx_near_empty_last")}
    gained = sum(r["on"]["pages"] > r["off"]["pages"] for r in rows.values())
    differ = {s: sum(r[s].get("docx_pages") not in (None, r[s]["pages"]) for r in rows.values())
              for s in ("off", "on")}
    print("totals", json.dumps(total), "documents that gained a page:", gained,
          "PDF≠DOCX page count:", json.dumps(differ) if a.docx else "not measured")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump({"rows": rows, "totals": total, "gained": gained, "pdf_docx_differ": differ}, f, indent=1)


if __name__ == "__main__":
    main()
