"""
M7.5 archetype comparison (reproducible, CPU-only, offline).

    python benchmarks/m75/run.py OUT_DIR [--docs a,b]

Every example is rendered twice from identical content, as PDF and as editable DOCX:

* ``before``: the archetype blocks lowered to the plain blocks the engine already had;
* ``after``: the archetype block itself.

The record holds page counts, PDF and DOCX QA, content integrity, Arabic checks and
render time. DOCX pages are rendered by LibreOffice where it is installed; without it
the DOCX is reported as unverified and the gallery shows PDF only. This module states
facts and shows pages: it never decides that one page looks better than another.
"""
from __future__ import annotations

import argparse
import html
import importlib.util
import io
import json
import os
import re
import sys
import time
import warnings
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path[:0] = [HERE, ROOT, os.path.join(ROOT, "scripts")]

from examples import EXAMPLES  # noqa: E402

VARIANTS = ("before", "after")
HARAKAT = re.compile("[ً-ْ]")
MAX_PAGES = 3


def _m7():
    spec = importlib.util.spec_from_file_location("m7_run", os.path.join(ROOT, "benchmarks", "m7", "run.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def docx_all_text(data: bytes) -> str:
    """Every text run of the body, text boxes included."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    paragraphs = re.findall(r"<w:p[ >].*?</w:p>", xml, re.S)
    pieces = (re.findall(r"<w:t(?: [^>]*)?>([^<]*)</w:t>|(<w:tab/>)", p) for p in paragraphs)
    return "\n".join("".join(text or " " for text, _ in line) for line in pieces)


def strip_of_pages(pdf: bytes, path: str, dpi: int = 62) -> None:
    """The first pages side by side, as real rendered pages."""
    import pymupdf
    from PIL import Image
    doc = pymupdf.open(stream=pdf, filetype="pdf")
    pages = []
    for i in range(min(MAX_PAGES, len(doc))):
        px = doc[i].get_pixmap(dpi=dpi)
        pages.append(Image.frombytes("RGB", (px.width, px.height), px.samples))
    sheet = Image.new("RGB", (sum(p.width + 6 for p in pages) - 6, max(p.height for p in pages)), (150, 150, 150))
    x = 0
    for p in pages:
        sheet.paste(p, (x, 0))
        x += p.width + 6
    sheet.save(path, quality=72, optimize=True)


def build(name: str, variant: str):
    from dynamic_pdf.design.archetypes import lowered
    b = EXAMPLES[name][1]()
    if variant == "before":
        b._blocks = lowered(b._blocks)
    return b


def measure(m7, name: str, variant: str, out: str) -> dict:
    warnings.simplefilter("ignore")
    import pymupdf
    from benchmark_compose import _keys, _source_words
    from dynamic_pdf.core.normalize import normalize
    from dynamic_pdf.design.archetypes import lowered
    from dynamic_pdf.qa import check_docx, check_pdf
    from dynamic_pdf.qa.loop import qa_context
    b = build(name, variant)
    t0 = time.perf_counter()
    pdf = b.render()
    t1 = time.perf_counter()
    docx = b.render_docx()
    t2 = time.perf_counter()
    doc, theme = b._prepared()
    outline = [o.text for o in normalize(doc).outline]
    sp = theme.spacing
    pqa = check_pdf(pdf, margins={"left": sp.page_margin_left, "right": sp.page_margin_right},
                    heading_texts=outline, **qa_context(doc, theme))
    dqa = check_docx(docx, heading_texts=outline, visual=True)
    plain = doc.model_copy(update={"blocks": lowered(doc.blocks)})
    words = _source_words(plain)
    raw = "\n".join(p.get_text() for p in pymupdf.open(stream=pdf, filetype="pdf"))
    dtext = docx_all_text(docx)
    source = json.dumps(doc.model_dump(mode="json", include={"blocks"}), ensure_ascii=False)
    diag = b.last_render.diagnostics.items
    record = {
        "name": name, "variant": variant, "archetype": EXAMPLES[name][0],
        "pdf_pages": pqa.pages, "docx_pages": dqa.pages,
        "pdf_qa": {"status": pqa.status, "errors": [f"{f.code}: {f.message}" for f in pqa.errors],
                   "warnings": sorted({f.code for f in pqa.findings if f.severity == "warning"})},
        "docx_qa": {"status": dqa.status, "unverified": dqa.unverified,
                    "errors": [f"{f.code}: {f.message}" for f in dqa.errors],
                    "warnings": sorted({f.code for f in dqa.findings if f.severity == "warning"})},
        "missing_words": {"pdf": sorted(words - (_keys(raw.replace("-\n", "")) | _keys(raw.replace("\n", ""))))[:20],
                          "docx": sorted(words - _keys(dtext))[:20]},
        "harakat": {"source": len(HARAKAT.findall(source)), "pdf": len(HARAKAT.findall(raw)),
                    "docx": len(HARAKAT.findall(dtext))},
        "archetype_notes": [d.message for d in diag if d.code.startswith("archetype")],
        "render_s": {"pdf": round(t1 - t0, 3), "docx": round(t2 - t1, 3)},
    }
    key = f"{name}-{variant}"
    for ext, data in (("pdf", pdf), ("docx", docx)):
        with open(os.path.join(out, "outputs", f"{key}.{ext}"), "wb") as f:
            f.write(data)
    record["images"] = {"pdf": f"img/{key}-pdf.jpg"}
    strip_of_pages(pdf, os.path.join(out, "gallery", record["images"]["pdf"]))
    rendered = getattr(dqa, "_pdf", None)
    if rendered:
        record["images"]["docx"] = f"img/{key}-docx.jpg"
        strip_of_pages(rendered, os.path.join(out, "gallery", record["images"]["docx"]))
    return record


def _row(r: dict) -> list:
    m = r["missing_words"]
    h = r["harakat"]
    return [r["variant"], r["pdf_pages"], r["docx_pages"] if r["docx_pages"] else "unverified", r["pdf_qa"]["status"],
            "unverified" if r["docx_qa"]["unverified"] else r["docx_qa"]["status"], f"{len(m['pdf'])} / {len(m['docx'])}",
            f"{h['source']} / {h['pdf']} / {h['docx']}", f"{r['render_s']['pdf']} / {r['render_s']['docx']}"]


HEAD = ["", "PDF pages", "DOCX pages", "PDF QA", "DOCX QA", "missing words PDF / DOCX",
        "harakat source / PDF / DOCX", "render s PDF / DOCX"]


def report(records: list, out: str) -> None:
    by = {}
    for r in records:
        by.setdefault(r["name"], {})[r["variant"]] = r
    with open(os.path.join(out, "results.json"), "w", encoding="utf-8") as f:
        json.dump({"format": "dynamic-pdf-builder/m75-comparison", "version": 1, "examples": by},
                  f, ensure_ascii=False, indent=1)
    md = ["# M7.5 archetype comparison", "",
          "Identical fictional content, before (plain blocks) and after (archetype). Facts only; "
          "the pages are in `gallery/index.html`.", ""]
    page = ["<!doctype html><meta charset='utf-8'><title>M7.5 archetype comparison</title><style>"
            "body{font:15px/1.5 system-ui,sans-serif;margin:24px;background:#fbfaf8;color:#222}"
            "h2{margin-top:36px}figure{margin:0 0 14px}figcaption{font-weight:600;margin-bottom:4px}"
            "img{max-width:100%;border:1px solid #ccc}.g{display:grid;grid-template-columns:1fr 1fr;gap:18px}"
            "table{border-collapse:collapse;margin:8px 0}td,th{border:1px solid #ccc;padding:3px 8px;text-align:left}"
            "</style><h1>M7.5 archetype comparison</h1><p>Identical fictional content. Before: the plain blocks the "
            "engine already had. After: the archetype. DOCX pages are the editable file rendered by LibreOffice.</p>"]
    for name, pair in by.items():
        md += [f"## {name} ({pair['after']['archetype']})", "", "| " + " | ".join(HEAD) + " |",
               "|" + "---|" * len(HEAD)]
        page.append(f"<h2>{html.escape(name)} ({html.escape(pair['after']['archetype'])})</h2><table><tr>"
                    + "".join(f"<th>{html.escape(h)}</th>" for h in HEAD) + "</tr>")
        for variant in VARIANTS:
            row = _row(pair[variant])
            md.append("| " + " | ".join(str(c) for c in row) + " |")
            page.append("<tr>" + "".join(f"<td>{html.escape(str(c))}</td>" for c in row) + "</tr>")
        page.append("</table><div class='g'>")
        for kind in ("pdf", "docx"):
            for variant in VARIANTS:
                src = pair[variant]["images"].get(kind)
                if src:
                    page.append(f"<figure><figcaption>{variant}, {kind.upper()}</figcaption>"
                                f"<img src='{src}' alt='{html.escape(name)} {variant} {kind}'></figure>")
        page.append("</div>")
        for variant in VARIANTS:
            r = pair[variant]
            for label, qa in (("PDF", r["pdf_qa"]), ("DOCX", r["docx_qa"])):
                md += [f"- {variant} {label} error: {e}" for e in qa["errors"]]
            md += [f"- {variant} fit note: {n}" for n in r["archetype_notes"]]
        md.append("")
    with open(os.path.join(out, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")
    with open(os.path.join(out, "gallery", "index.html"), "w", encoding="utf-8") as f:
        f.write("\n".join(page))


def failures(records: list) -> list:
    """What must hold for every 'after' page, in both formats."""
    bad = []
    for r in records:
        if r["variant"] != "after":
            continue
        tag = r["name"]
        bad += [f"{tag}: PDF {e}" for e in r["pdf_qa"]["errors"]] + [f"{tag}: DOCX {e}" for e in r["docx_qa"]["errors"]]
        bad += [f"{tag}: lost words in {k}: {v}" for k, v in r["missing_words"].items() if v]
        h = r["harakat"]
        bad += [f"{tag}: harakat lost in {k}" for k in ("pdf", "docx") if h[k] < h["source"]]
    return bad


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out")
    ap.add_argument("--docs", default=None)
    a = ap.parse_args(argv)
    out = os.path.abspath(a.out)
    for sub in ("outputs", os.path.join("gallery", "img")):
        os.makedirs(os.path.join(out, sub), exist_ok=True)
    m7 = _m7()
    net: list = []
    m7._guard_network(net)
    names = a.docs.split(",") if a.docs else list(EXAMPLES)
    records = []
    for name in names:
        for variant in VARIANTS:
            records.append(measure(m7, name, variant, out))
            print(name, variant, "ok", flush=True)
    report(records, out)
    bad = failures(records) + [f"network attempt: {n}" for n in net]
    print("\n".join(bad) if bad else f"{len(records)} renders: no failures")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
