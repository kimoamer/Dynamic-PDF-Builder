"""
Golden fixtures: a structural fingerprint of each fixture's PDF + DOCX output.

    python -m dynamic_pdf.qa.golden tests/fixtures tests/golden            # verify
    python -m dynamic_pdf.qa.golden tests/fixtures tests/golden --update   # regenerate
    python -m dynamic_pdf.qa.golden tests/fixtures out/ --sheets           # + contact sheets

Fingerprints record what a reviewer cares about — profile, page count, PDF
outline, fonts, table sizes, DOCX heading/table structure and QA status —
rather than raw bytes, so they are stable across ReportLab timestamps.
"""
from __future__ import annotations

import io
import json
import os
import sys
from typing import Dict


def fingerprint(md_text: str) -> Dict:
    import pymupdf
    import docx
    from ..builder import DocumentBuilder
    from .pdf_checks import check_pdf
    b = DocumentBuilder.from_markdown(md_text).design()
    pdf = b.render()
    theme = b.last_render.theme
    sem = b.semantic()
    doc = pymupdf.open(stream=pdf, filetype="pdf")
    fonts = sorted({f[3].split("+")[-1] for p in doc for f in p.get_fonts()})
    sp = theme.spacing
    qa = check_pdf(pdf, margins={"left": sp.page_margin_left, "right": sp.page_margin_right},
                   heading_texts=[o.text for o in sem.outline])
    d = docx.Document(io.BytesIO(b.render_docx()))
    return {
        "profile": b.last_design.decision.profile.value,
        "direction": sem.direction,
        "pdf_pages": doc.page_count,
        "pdf_orientations": ["L" if p.rect.width > p.rect.height else "P" for p in doc],
        "pdf_outline": [[lvl, title, page] for lvl, title, page in doc.get_toc()],
        "pdf_fonts": fonts,
        "pdf_qa_errors": [f.code for f in qa.errors],
        "tables": [[len(t.rows), max([len(t.headers or [])] + [len(r) for r in t.rows])]
                   for t in sem.blocks if t.type == "table"],
        "docx_headings": [[p.style.name, p.text] for p in d.paragraphs if p.style.name.startswith("Heading")],
        "docx_tables": [[len(t.rows), len(t.columns)] for t in d.tables],
        "docx_sections": len(d.sections),
        "layout": b.design_explain()["layout"],
    }


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="python -m dynamic_pdf.qa.golden")
    ap.add_argument("fixtures")
    ap.add_argument("golden")
    ap.add_argument("--update", action="store_true")
    ap.add_argument("--sheets", action="store_true", help="also write page contact sheets (PDF + DOCX)")
    a = ap.parse_args(argv)
    os.makedirs(a.golden, exist_ok=True)
    failures = 0
    for name in sorted(f for f in os.listdir(a.fixtures) if f.endswith(".md")):
        with open(os.path.join(a.fixtures, name), encoding="utf-8") as f:
            md = f.read()
        fp = fingerprint(md)
        path = os.path.join(a.golden, name[:-3] + ".json")
        if a.update or not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                json.dump(fp, f, ensure_ascii=False, indent=1)
            print(f"wrote {path}")
        else:
            with open(path, encoding="utf-8") as f:
                want = json.load(f)
            diff = {k: (want.get(k), fp.get(k)) for k in set(want) | set(fp) if want.get(k) != fp.get(k)}
            if diff:
                failures += 1
                print(f"DIFF {name}: {json.dumps(diff, ensure_ascii=False)[:600]}")
            else:
                print(f"ok   {name}")
        if a.sheets:
            from ..builder import DocumentBuilder
            from .docx_checks import docx_to_pdf
            from .rasterize import contact_sheet, rasterize_pdf
            b = DocumentBuilder.from_markdown(md).design()
            stem = os.path.join(a.golden, "sheets", name[:-3])
            imgs = rasterize_pdf(b.render(), stem + "-pdf", dpi=60)
            contact_sheet(imgs, stem + "-pdf.png")
            dpdf = docx_to_pdf(b.render_docx())
            if dpdf:
                contact_sheet(rasterize_pdf(dpdf, stem + "-docx", dpi=60), stem + "-docx.png")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
