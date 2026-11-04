"""
M7.6 media and page-system comparison (reproducible, CPU-only, offline).

    python benchmarks/m76/run.py OUT_DIR [--docs a,b]

Every example is rendered from identical content, as PDF and as editable DOCX: ``before``
without the media model and page system, ``after`` with them. DOCX pages are rendered by
LibreOffice where it is installed; without it the DOCX is reported as unverified. This
module states facts and shows pages: it never decides that one page looks better.
"""
from __future__ import annotations

import argparse
import html
import importlib.util
import json
import os
import re
import sys
import tempfile
import time
import tracemalloc
import warnings

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path[:0] = [ROOT, os.path.join(ROOT, "scripts")]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


assets = _load("m76_assets", os.path.join(HERE, "assets.py"))
examples = _load("m76_examples", os.path.join(HERE, "examples.py"))

EXAMPLES = examples.EXAMPLES
VARIANTS = ("before", "after")
HARAKAT = re.compile("[ً-ْ]")
# Failures this example exists to provoke, which must each be reported.
EXPECTED = {"image_failures": {"image_low_resolution", "block_render_failed"}}


def strip_of_pages(pdf: bytes, path: str, dpi: int = 58, pages: int = 4) -> None:
    import pymupdf
    from PIL import Image
    doc = pymupdf.open(stream=pdf, filetype="pdf")
    chosen = list(range(min(pages, doc.page_count)))
    if doc.page_count > pages:
        chosen[-1] = doc.page_count - 1
    images = []
    for i in chosen:
        pix = doc[i].get_pixmap(dpi=dpi)
        images.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
    strip = Image.new("RGB", (sum(i.width + 6 for i in images), max(i.height for i in images)), "#8a8f96")
    x = 0
    for image in images:
        strip.paste(image, (x, 0))
        x += image.width + 6
    strip.save(path, quality=82)


def docx_text(data: bytes) -> str:
    import io
    import zipfile
    out = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for name in z.namelist():
            if re.match(r"word/(document|header\d*|footer\d*)\.xml$", name):
                xml = z.read(name).decode("utf-8")
                for p in re.findall(r"<w:p[ >].*?</w:p>", xml, re.S):
                    out.append("".join(re.findall(r"<w:t(?: [^>]*)?>([^<]*)</w:t>", p)))
    return "\n".join(out)


def measure(a, name: str, variant: str, out: str) -> dict:
    warnings.simplefilter("ignore")
    import pymupdf
    from benchmark_compose import _keys
    from dynamic_pdf.core.normalize import block_text, normalize
    from dynamic_pdf.qa import check_docx, check_pdf
    from dynamic_pdf.qa.loop import qa_context
    from dynamic_pdf.themes import get_theme
    from dynamic_pdf.qa.media_checks import check_docx_media, check_pdf_media, docx_media_summary
    rich = variant == "after"
    kit = EXAMPLES[name][1](a, rich)
    b = kit.b
    t0 = time.perf_counter()
    pdf = b.render_bytes()
    pdf_diag = [d.code for d in b.last_render.diagnostics.items]
    t1 = time.perf_counter()
    docx = b.render_docx_bytes() if hasattr(b, "render_docx_bytes") else b.render_docx()
    t2 = time.perf_counter()
    docx_diag = [d.code for d in b.last_render.diagnostics.items]
    tracemalloc.start()
    EXAMPLES[name][1](a, rich).b.render_bytes()
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    doc, theme = b._prepared()
    theme = theme or get_theme(doc.theme)
    outline = [o.text for o in normalize(doc).outline]
    sp = theme.spacing
    pqa = check_pdf(pdf, margins={"left": sp.page_margin_left, "right": sp.page_margin_right},
                    heading_texts=outline, **qa_context(doc, theme))
    dqa = check_docx(docx, heading_texts=outline, visual=True)
    words = _keys(" ".join(
        t for block in doc.blocks if block.type not in ("page_media", "page_section")
        for t in block_text(block.model_copy(update={"alt_text": None}) if block.type == "image" else block)))
    raw = "\n".join(p.get_text() for p in pymupdf.open(stream=pdf, filetype="pdf"))
    dtext = docx_text(docx)
    source = json.dumps(doc.model_dump(mode="json", include={"blocks"}), ensure_ascii=False)
    rendered = getattr(dqa, "_pdf", None)
    record = {
        "name": name, "variant": variant, "title": EXAMPLES[name][0],
        "pdf_pages": pqa.pages, "docx_pages": dqa.pages,
        "pdf_qa": {"status": pqa.status, "errors": [f"{f.code}: {f.message}" for f in pqa.errors],
                   "warnings": sorted({f.code for f in pqa.findings if f.severity == "warning"})},
        "docx_qa": {"status": dqa.status, "unverified": dqa.unverified,
                    "errors": [f"{f.code}: {f.message}" for f in dqa.errors],
                    "warnings": sorted({f.code for f in dqa.findings if f.severity == "warning"})},
        "media": {"pdf": check_pdf_media(pdf), "docx": check_docx_media(docx),
                  # LibreOffice exports a cropped picture whole under a clip, so its box
                  # says nothing about what is visible: only the shape test applies.
                  "lo_pdf": [f for f in check_pdf_media(rendered) if f["code"] != "text_under_image"]
                  if rendered else None},
        "docx_structure": docx_media_summary(docx),
        "missing_words": {"pdf": sorted(words - (_keys(raw.replace("-\n", "")) | _keys(raw.replace("\n", ""))))[:20],
                          "docx": sorted(words - _keys(dtext))[:20]},
        "harakat": {"source": len(HARAKAT.findall(source)), "pdf": len(HARAKAT.findall(raw)),
                    "docx": len(HARAKAT.findall(dtext))},
        "diagnostics": {"pdf": sorted(set(pdf_diag)), "docx": sorted(set(docx_diag))},
        "render_s": {"pdf": round(t1 - t0, 3), "docx": round(t2 - t1, 3)},
        "python_heap_peak_mb": round(peak / 2**20, 1),
        "size_kb": {"pdf": round(len(pdf) / 1024), "docx": round(len(docx) / 1024)},
    }
    key = f"{name}-{variant}"
    for ext, data in (("pdf", pdf), ("docx", docx)):
        with open(os.path.join(out, "outputs", f"{key}.{ext}"), "wb") as f:
            f.write(data)
    record["images"] = {"pdf": f"img/{key}-pdf.jpg"}
    strip_of_pages(pdf, os.path.join(out, "gallery", record["images"]["pdf"]))
    if rendered:
        record["images"]["docx"] = f"img/{key}-docx.jpg"
        strip_of_pages(rendered, os.path.join(out, "gallery", record["images"]["docx"]))
    return record


def failures(records: list) -> list:
    out = []
    for r in records:
        tag = f"{r['name']}/{r['variant']}"
        if r["pdf_qa"]["errors"]:
            out.append(f"{tag}: PDF QA {r['pdf_qa']['errors'][:2]}")
        if r["docx_qa"]["errors"]:
            out.append(f"{tag}: DOCX QA {r['docx_qa']['errors'][:2]}")
        if r["variant"] == "before":
            continue
        for kind in ("pdf", "docx", "lo_pdf"):
            if r["media"][kind]:
                out.append(f"{tag}: media {kind} {r['media'][kind][:2]}")
        if r["name"] not in EXPECTED and (r["missing_words"]["pdf"] or r["missing_words"]["docx"]):
            out.append(f"{tag}: missing words {r['missing_words']}")
        h = r["harakat"]
        if h["source"] and not (h["docx"] >= h["source"] and h["pdf"]):
            out.append(f"{tag}: diacritics lost {h}")
        for code in EXPECTED.get(r["name"], ()):
            if code not in r["diagnostics"]["pdf"] or code not in r["diagnostics"]["docx"]:
                out.append(f"{tag}: expected diagnostic {code} missing")
    return out


def report(records: list, out: str) -> None:
    lines = ["# M7.6 media and page-system results", "",
             "Facts from one run. `before` is the same content without the media model or page system.", "",
             "| Example | Variant | PDF pp | DOCX pp (LO) | PDF QA | DOCX QA | Inline | Anchored | Fields | PDF s | DOCX s | Heap MB | PDF KB | DOCX KB |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in records:
        s = r["docx_structure"]
        lines.append(f"| {r['name']} | {r['variant']} | {r['pdf_pages']} | {r['docx_pages']} | {r['pdf_qa']['status']} "
                     f"| {r['docx_qa']['status']} | {s['inline']} | {s['anchored']} | {s['live_fields']} "
                     f"| {r['render_s']['pdf']} | {r['render_s']['docx']} | {r['python_heap_peak_mb']} "
                     f"| {r['size_kb']['pdf']} | {r['size_kb']['docx']} |")
    with open(os.path.join(out, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    with open(os.path.join(out, "results.json"), "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=1)
    body = ["<!doctype html><meta charset=utf-8><title>M7.6 gallery</title>",
            "<style>body{font:15px system-ui;margin:24px;max-width:1500px}img{max-width:100%;display:block;"
            "margin:4px 0 14px}h2{margin-top:36px}small{color:#555}</style><h1>M7.6 gallery</h1>",
            "<p>Rendered pages from one run. No quality judgement is implied.</p>"]
    for name in dict.fromkeys(r["name"] for r in records):
        body.append(f"<h2>{html.escape(EXAMPLES[name][0])}</h2>")
        for r in records:
            if r["name"] == name:
                for kind, src in r["images"].items():
                    label = {"pdf": "PDF", "docx": "DOCX through LibreOffice"}[kind]
                    body.append(f"<small>{r['variant']}: {label}</small><img src='{src}' alt='{name} {kind}'>")
    with open(os.path.join(out, "gallery", "index.html"), "w", encoding="utf-8") as f:
        f.write("\n".join(body))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("out")
    parser.add_argument("--docs", default="")
    args = parser.parse_args(argv)
    for sub in ("outputs", os.path.join("gallery", "img")):
        os.makedirs(os.path.join(args.out, sub), exist_ok=True)
    names = [n for n in args.docs.split(",") if n] or list(EXAMPLES)
    records = []
    with tempfile.TemporaryDirectory() as tmp:
        a = assets.make(tmp)
        for name in names:
            for variant in VARIANTS:
                record = measure(a, name, variant, args.out)
                records.append(record)
                print(name, variant, record["pdf_pages"], record["docx_pages"], record["pdf_qa"]["status"],
                      record["docx_qa"]["status"], flush=True)
    report(records, args.out)
    problems = failures(records)
    for p in problems:
        print("FAIL", p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
