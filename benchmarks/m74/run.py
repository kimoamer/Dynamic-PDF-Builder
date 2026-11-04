"""
M7.4 evidence-recipe comparison (reproducible, CPU-only, offline).

    python benchmarks/m74/run.py OUT_DIR [--recipes a,b] [--docs a,b] [--jobs N]

For every recipe and document, a fresh worker process renders identical content
twice, as PDF and as editable DOCX:

* ``baseline``: ``design()``, the existing behaviour;
* ``proposed``: ``design(recipe=..., recipe_gate="preview")``, the recipe forced on.

Each record holds page counts, density, readability measured from the PDF,
table pagination, Arabic RTL and text-integrity checks, PDF and DOCX QA,
latency and peak memory. DOCX pages are rendered by LibreOffice where it is
installed (CI); without it the DOCX QA is reported as unverified and the gallery
says so. ``report.py`` then writes the results, the report and the blind
A/B/Tie gallery. No preference is ever generated here.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import statistics
import subprocess
import sys
import time
import warnings
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
M7 = os.path.join(ROOT, "benchmarks", "m7")
sys.path[:0] = [HERE, M7, ROOT, os.path.join(ROOT, "tests"), os.path.join(ROOT, "scripts")]

VARIANTS = ("baseline", "proposed")
PAIRS = {
    "financial_corporate": ("financial_statements", "business_memo"),
    "editorial_executive": ("editorial_briefing", "en_executive_report", "proposal"),
    "arabic_bilingual": ("ar_annual_report", "ar_financial_statements", "ar_memo", "bilingual_board_report"),
}
SHEET_PAGES = 8


def factory(name: str):
    if name == "editorial_briefing":
        from extra_docs import editorial_briefing
        return editorial_briefing
    from corpus import CORPUS
    return CORPUS[name][2]


def peak_rss_mb() -> float:
    """Peak resident memory of this process, on Unix and Windows."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                (n, ctypes.c_size_t) for n in (
                    "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage",
                    "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
        c = Counters()
        c.cb = ctypes.sizeof(c)
        psapi, kernel = ctypes.WinDLL("psapi"), ctypes.WinDLL("kernel32")
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(c), c.cb)
        return round(c.PeakWorkingSetSize / (1024 * 1024), 1)
    import resource
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(peak / (1024 * 1024) if sys.platform == "darwin" else peak / 1024, 1)


def body_lines(pdf: bytes, body_size: float):
    """Lines set at body size: (page index, characters, x0, top, x1, bottom)."""
    import pymupdf
    out = []
    for i, page in enumerate(pymupdf.open(stream=pdf, filetype="pdf")):
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                spans = line["spans"]
                text = "".join(s["text"] for s in spans).strip()
                if text and abs(max(s["size"] for s in spans) - body_size) <= 0.3:
                    out.append((i, len(text), *line["bbox"]))
    return out


def readability(pdf: bytes, body_size: float) -> dict:
    """Characters per line of full body lines, measured from the rendered PDF."""
    lens = sorted(line[1] for line in body_lines(pdf, body_size) if line[1] >= 20)
    if not lens:
        return {"lines": 0, "median_chars_per_line": None, "p90_chars_per_line": None}
    return {"lines": len(lens), "median_chars_per_line": statistics.median(lens),
            "p90_chars_per_line": lens[int(len(lens) * 0.9)]}


def line_clearance(pdf: bytes, body_size: float, max_pages: int = SHEET_PAGES) -> dict:
    """Share of adjacent body lines with a clear pixel row between their ink (at 150 dpi).

    Line boxes overlap by font metrics alone, so ink is read from the page image,
    inside the horizontal range the two lines share."""
    import pymupdf
    doc = pymupdf.open(stream=pdf, filetype="pdf")
    scale = 150 / 72
    gaps = clear = 0
    pages: dict = {}
    for line in body_lines(pdf, body_size):
        if line[0] < max_pages:
            pages.setdefault(line[0], []).append(line[2:])
    for i, lines in pages.items():
        pix = doc[i].get_pixmap(matrix=pymupdf.Matrix(scale, scale), colorspace=pymupdf.csGRAY)
        stride, data = pix.stride, pix.samples
        lines.sort(key=lambda b: (b[1], b[0]))
        for k, a in enumerate(lines):
            nxt = [b for b in lines[k + 1:] if 0.5 * body_size < b[1] - a[1] <= 2.2 * body_size
                   and min(a[2], b[2]) - max(a[0], b[0]) > 40]
            if not nxt:
                continue
            b = min(nxt, key=lambda x: x[1])
            x0, x1 = int(max(a[0], b[0]) * scale), int(min(a[2], b[2]) * scale)
            r0, r1 = int((a[1] + a[3]) / 2 * scale), min(int((b[1] + b[3]) / 2 * scale), pix.height - 1)
            gaps += 1
            if any(min(data[r * stride + x0:r * stride + x1]) > 200 for r in range(r0, r1)):
                clear += 1
    return {"gaps": gaps, "clear_share": round(clear / gaps, 3) if gaps else None}


def table_facts(geo, doc) -> dict:
    from dynamic_pdf.design.evidence_gate import split_tables
    tables = {i for i, b in enumerate(doc.blocks) if b.type == "table"}
    pages = {r.page for r in geo.regions if r.block in tables and r.role == "table"}
    return {"tables": len(tables), "split_tables": split_tables(geo, doc), "pages_with_tables": len(pages)}


def density(score, pdf_chars: int, pages: int) -> dict:
    body = [p.fill for p in score.pages if p.role == "body"]
    return {"chars_per_page": round(pdf_chars / max(pages, 1)),
            "mean_body_page_fill": round(statistics.mean(body), 3) if body else None,
            "underfilled_body_pages": sum(f < 0.6 for f in body),
            "utilization": score.metrics.get("utilization")}


def sheet(pdf: bytes, work_dir: str, out_jpg: str, cols: int = 4, width: int = 340) -> int:
    """Contact sheet of the first pages, as real rendered pages."""
    import pymupdf
    from PIL import Image
    from dynamic_pdf.qa import contact_sheet, rasterize_pdf
    src = pymupdf.open(stream=pdf, filetype="pdf")
    if len(src) > SHEET_PAGES:
        src.select(list(range(SHEET_PAGES)))
    imgs = rasterize_pdf(src.tobytes(), work_dir, dpi=90)
    png = out_jpg[:-4] + ".png"
    contact_sheet(imgs, png, columns=cols, thumb_width=width)
    Image.open(png).convert("RGB").save(out_jpg, quality=70, optimize=True)
    os.remove(png)
    return len(imgs)


def measure(recipe: str, name: str, variant: str, out: str) -> dict:
    warnings.simplefilter("ignore")
    import importlib.util
    spec = importlib.util.spec_from_file_location("m7_run", os.path.join(M7, "run.py"))
    m7 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m7)
    net: list = []
    m7._guard_network(net)
    make = factory(name)

    def build():
        b = make()
        return b.design(recipe=recipe, recipe_gate="preview") if variant == "proposed" else b.design()

    b = build()
    t0 = time.perf_counter()
    pdf = b.render()
    pdf_cold = time.perf_counter() - t0
    t1 = time.perf_counter()
    docx = b.render_docx()
    docx_cold = time.perf_counter() - t1
    peak = peak_rss_mb()
    b2 = build()
    t2 = time.perf_counter()
    b2.render()
    pdf_warm = time.perf_counter() - t2
    t3 = time.perf_counter()
    b2.render_docx()
    docx_warm = time.perf_counter() - t3

    # ── verification (not timed) ──
    import pymupdf
    from benchmark_compose import _keys, _source_words
    from conftest import docx_text
    from dynamic_pdf.core.normalize import normalize
    from dynamic_pdf.intelligence.geometry import Geometry
    from dynamic_pdf.intelligence.scoring import score_layout
    from dynamic_pdf.layout.engine import LayoutEngine
    from dynamic_pdf.qa import check_docx, check_pdf
    from dynamic_pdf.qa.loop import glyph_findings, qa_context
    doc, theme = b._prepared()
    geo = Geometry()
    LayoutEngine(doc, theme=theme, geometry=geo).render(io.BytesIO())
    score = score_layout(geo, doc, theme)
    sem = normalize(doc)
    sp = theme.spacing
    pqa = check_pdf(pdf, margins={"left": sp.page_margin_left, "right": sp.page_margin_right},
                    heading_texts=[o.text for o in sem.outline], **qa_context(doc, theme))
    pqa.findings += glyph_findings(sem, theme)
    dqa = check_docx(docx, heading_texts=[o.text for o in sem.outline], visual=True)
    src = b.build()
    words = _source_words(src)
    raw = "\n".join(p.get_text() for p in pymupdf.open(stream=pdf, filetype="pdf"))
    pdf_missing = sorted(words - (_keys(raw.replace("-\n", "")) | _keys(raw.replace("\n", ""))))
    dtext = docx_text(docx)
    docx_missing = sorted(words - _keys(dtext))
    fps = m7._fingerprints(doc)
    ty = theme.typography
    outcome = getattr(b.last_design, "recipe_outcome", None)
    plan = b.last_design
    rec = {
        "recipe": recipe, "name": name, "variant": variant, "profile": plan.decision.profile.value,
        "direction": plan.decision.direction,
        "pages": pqa.pages,
        "layout_id": hashlib.sha256(json.dumps(sorted(
            (r.page, r.block if r.block is not None else -1, round(r.top), round(r.bottom)) for r in geo.regions
        )).encode()).hexdigest()[:16],
        "typography": {"body_family": ty.body_family, "body_size": ty.base_size, "line_height": ty.line_height,
                       "h1_size": plan.tokens.heading_sizes[0],
                       "h1_ratio": round(plan.tokens.heading_sizes[0] / ty.base_size, 2)},
        "columns": [d.decision for d in plan.layout.decisions if d.target == "columns"],
        "density": density(score, len("".join(raw.split())), pqa.pages),
        "readability": {**readability(pdf, ty.base_size), "score_readability": score.metrics.get("readability")},
        "line_clearance": line_clearance(pdf, ty.base_size),
        "tables": table_facts(geo, doc),
        "score": {"value": score.score, "valid": score.valid, "hard_errors": score.hard_errors},
        "rtl": m7._rtl_checks(pdf, geo, doc, dtext),
        "layout": m7._geometry_facts(geo, score, doc),
        "pdf_qa": {"status": pqa.status, "errors": [f"{f.code}: {f.message}" for f in pqa.errors],
                   "warnings": sorted({f.code for f in pqa.findings if f.severity == "warning"})},
        "docx_qa": {"status": dqa.status, "pages": dqa.pages, "unverified": dqa.unverified,
                    "errors": [f"{f.code}: {f.message}" for f in dqa.errors],
                    "warnings": sorted({f.code for f in dqa.findings if f.severity == "warning"})},
        "content": {"source_words": len(words), "pdf_missing_words": pdf_missing[:20],
                    "docx_missing_words": docx_missing[:20],
                    "pdf_sequence": m7._sequence_check(fps, raw, ltr_only=True),
                    "docx_sequence": m7._sequence_check(fps, dtext, ltr_only=False)},
        "docx_editability": m7._docx_editability(docx, doc),
        "timing": {"pdf_cold_s": round(pdf_cold, 3), "docx_cold_s": round(docx_cold, 3),
                   "pdf_warm_s": round(pdf_warm, 3), "docx_warm_s": round(docx_warm, 3)},
        "peak_rss_mb": peak,
        "gate": outcome.model_dump() if outcome is not None else None,
        "network_attempts": net,
    }
    key = f"{recipe}-{name}-{variant}"
    os.makedirs(os.path.join(out, "outputs"), exist_ok=True)
    os.makedirs(os.path.join(out, "gallery", "img"), exist_ok=True)
    for ext, data in (("pdf", pdf), ("docx", docx)):
        with open(os.path.join(out, "outputs", f"{key}.{ext}"), "wb") as f:
            f.write(data)
    rec["sheets"] = {"pdf": f"img/{key}-pdf.jpg"}
    sheet(pdf, os.path.join(out, "work", key, "pdf"), os.path.join(out, "gallery", rec["sheets"]["pdf"]))
    docx_pdf = getattr(dqa, "_pdf", None)
    if docx_pdf:
        rec["docx_renderer"] = "LibreOffice"
        rec["sheets"]["docx"] = f"img/{key}-docx.jpg"
        sheet(docx_pdf, os.path.join(out, "work", key, "docx"), os.path.join(out, "gallery", rec["sheets"]["docx"]))
    with open(os.path.join(out, "records", key + ".json"), "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=1)
    return rec


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out")
    ap.add_argument("--recipes", default=",".join(PAIRS))
    ap.add_argument("--docs", default=None)
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--worker", nargs=3, metavar=("RECIPE", "DOC", "VARIANT"), help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    out = os.path.abspath(a.out)
    os.makedirs(os.path.join(out, "records"), exist_ok=True)
    if a.worker:
        measure(*a.worker, out)
        return 0
    only = set(a.docs.split(",")) if a.docs else None
    jobs = [(r, n, v) for r in a.recipes.split(",") for n in PAIRS[r] if not only or n in only for v in VARIANTS]

    def run(job):
        p = subprocess.run([sys.executable, os.path.abspath(__file__), out, "--worker", *job],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        print(" ".join(job), "ok" if p.returncode == 0 else "FAILED\n" + p.stderr[-1500:], flush=True)
        return p.returncode

    with ThreadPoolExecutor(a.jobs) as pool:
        failed = sum(1 for rc in pool.map(run, jobs) if rc)
    from report import build
    build(out)
    shutil.rmtree(os.path.join(out, "work"), ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
