"""
Benchmark smart composition against the M5 engine on identical inputs.

    python scripts/benchmark_compose.py OUT_DIR [--sheets]

For every document: pages, accidental wasted space, region occupancy, hard
layout defects, PDF QA errors, readability, content preservation (PDF and
DOCX), DOCX structural QA, wall/CPU time, peak traced memory and render
attempts. Writes OUT_DIR/benchmark.json and OUT_DIR/benchmark.md; with
--sheets also before/after page contact sheets (PDF and DOCX).
"""
import io
import json
import os
import re
import sys
import time
import tracemalloc
import unicodedata
import warnings

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tests"))
sys.path.insert(0, os.path.join(HERE, ".."))

# letters only per script; digits separately (PyMuPDF glues Arabic-Indic digits and the
# Arabic percent sign to neighbouring words when extracting RTL lines - verified visually)
_TOKEN = re.compile(r"[A-Za-z]{3,}|[\u0621-\u064A\u0671-\u06D3]{3,}|[0-9\u0660-\u0669]{3,}")


def _keys(text):
    text = "".join(c for c in unicodedata.normalize("NFKC", text) if unicodedata.category(c) != "Mn")
    return {min(w, w[::-1]) for w in _TOKEN.findall(text.lower())}


def _source_words(doc):
    from dynamic_pdf.core.inline import plain_text
    from dynamic_pdf.core.normalize import block_text
    words = set()
    for blk in doc.blocks:
        if blk.type in ("math", "chart", "diagram", "mermaid"):
            continue
        visible = blk.model_copy(update={"alt_text": None}) if blk.type == "image" else blk
        for t in block_text(visible):
            words |= _keys(plain_text(t))
    return words


def _measure(builder_factory, smart: bool, assets: str):
    import pymupdf
    from dynamic_pdf.intelligence.geometry import Geometry
    from dynamic_pdf.intelligence.scoring import score_layout
    from dynamic_pdf.layout.engine import LayoutEngine
    from dynamic_pdf.qa import check_docx, check_pdf
    from dynamic_pdf.qa.loop import qa_context
    from conftest import docx_text
    # timing run (no tracing overhead)
    b = builder_factory(assets).design()
    if smart:
        b.compose("smart")
    t0, c0 = time.perf_counter(), time.process_time()
    pdf = b.render()
    wall, cpu = time.perf_counter() - t0, time.process_time() - c0
    # separate memory run (tracemalloc slows Python, so it is not timed)
    bm = builder_factory(assets).design()
    if smart:
        bm.compose("smart")
    tracemalloc.start()
    bm.render()
    peak = tracemalloc.get_traced_memory()[1] / 2 ** 20
    tracemalloc.stop()
    doc, theme = b._prepared()
    # geometry of the delivered PDF (re-measured identically for both engines)
    geo = Geometry()
    LayoutEngine(doc, theme=theme, geometry=geo).render(io.BytesIO())
    s = score_layout(geo, doc, theme)
    sp = theme.spacing
    qa = check_pdf(pdf, margins={"left": sp.page_margin_left, "right": sp.page_margin_right},
                   heading_texts=[o.text for o in b.semantic().outline], **qa_context(doc, theme))
    words = _source_words(b.build())
    raw = "\n".join(p.get_text() for p in pymupdf.open(stream=pdf, filetype="pdf"))
    pdf_missing = words - (_keys(raw.replace("-\n", "")) | _keys(raw.replace("\n", "")))
    dx = b.render_docx()
    docx_missing = words - _keys(docx_text(dx))
    drep = check_docx(dx, heading_texts=[o.text for o in b.semantic().outline], visual=False)
    comp = b.last_composition
    layout = getattr(b.last_design, "layout", None) if b.last_design else None
    fit = getattr(layout, "trial_renders", 0) or 0
    comp_renders = (comp.render_attempts + comp.repair_renders) if comp else 1
    return {
        "pages": qa.pages, "score": s.score, "valid": s.valid, "hard_errors": len(s.hard_errors),
        "wasted": s.metrics["wasted"], "utilization": s.metrics["utilization"],
        "readability": s.metrics["readability"], "cpl": s.metrics["cpl"],
        "qa_errors": len(qa.errors), "qa_warnings": len([f for f in qa.findings if f.severity == "warning"]),
        "pdf_words_missing": len(pdf_missing), "docx_words_missing": len(docx_missing),
        "docx_structural": drep.status if not drep.unverified else ("pass" if not drep.errors else "fail"),
        "wall_s": round(wall, 3), "cpu_s": round(cpu, 3), "peak_mb": round(peak, 1),
        "renders": fit + comp_renders, "fit_renders": fit,
        "separated": s.metrics.get("separated_figures", 0.0),
        "body_fill": round(sum(p.fill for p in s.pages if p.role == "body") /
                           max(1, len([p for p in s.pages if p.role == "body"])), 3),
        "status": comp.status if comp else "m5",
        "strategy": comp.strategy if comp else "m5", "pdf": pdf, "docx": dx,
    }


def main():
    warnings.simplefilter("ignore")
    from conftest import all_fixtures, fixture_text
    from dynamic_pdf import DocumentBuilder
    from stress_docs import STRESS
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    assets = os.path.join(out, "assets")
    jobs = dict(STRESS)
    for n in all_fixtures():
        jobs["fx_" + n[:-3]] = (lambda d, n=n: DocumentBuilder.from_markdown(fixture_text(n)))
    rows = {}
    for name, make in jobs.items():
        m5 = _measure(make, False, assets)
        m6 = _measure(make, True, assets)
        if "--sheets" in sys.argv:
            from dynamic_pdf.qa import contact_sheet, docx_to_pdf, rasterize_pdf
            for tag, m in (("m5", m5), ("m6", m6)):
                imgs = rasterize_pdf(m["pdf"], os.path.join(out, name, tag, "pdf"), dpi=45)
                contact_sheet(imgs[:12], os.path.join(out, f"{name}-{tag}-pdf.png"), columns=6, thumb_width=200)
                dpdf = docx_to_pdf(m["docx"])
                if dpdf:
                    dimgs = rasterize_pdf(dpdf, os.path.join(out, name, tag, "docx"), dpi=45)
                    contact_sheet(dimgs[:12], os.path.join(out, f"{name}-{tag}-docx.png"), columns=6,
                                  thumb_width=200)
        for m in (m5, m6):
            m.pop("pdf"), m.pop("docx")
        rows[name] = {"m5": m5, "m6": m6}
        print(name, json.dumps({k: (m5[k], m6[k]) for k in ("pages", "score", "wasted", "utilization",
                                                             "qa_errors", "renders", "wall_s", "peak_mb")}))
    with open(os.path.join(out, "benchmark.json"), "w") as f:
        json.dump(rows, f, indent=1)
    cols = ["pages", "score", "wasted", "utilization", "body_fill", "separated", "readability",
            "hard_errors", "qa_errors", "pdf_words_missing", "docx_words_missing", "renders",
            "wall_s", "cpu_s", "peak_mb"]
    lines = ["| document | strategy | " + " | ".join(cols) + " |", "|---|---|" + "---|" * len(cols)]
    for name, r in rows.items():
        cells = [f"{r['m5'][c]} → {r['m6'][c]}" if r['m5'][c] != r['m6'][c] else f"{r['m6'][c]}" for c in cols]
        lines.append(f"| {name} | {r['m6']['strategy']} | " + " | ".join(cells) + " |")
    with open(os.path.join(out, "benchmark.md"), "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
