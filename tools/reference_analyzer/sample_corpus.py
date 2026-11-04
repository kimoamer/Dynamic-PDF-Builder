"""
Synthetic reference corpus with known ground truth (tests and demonstration).

    python -m tools.reference_analyzer.sample_corpus OUT_DIR

Every file is generated locally by this repository (ReportLab, PyMuPDF,
dynamic_pdf) — no third-party documents. ``build()`` returns the ground
truth used to check the analyzer's measurements.
"""
from __future__ import annotations

import csv
import json
import os
import shutil
import sys

A4 = (595.28, 841.89)
LOREM = ("Quarterly results improved across all regions as operating costs fell and the new distribution "
         "network reached full capacity. Customer satisfaction rose for the third consecutive period, and the "
         "board approved the investment programme for the coming year. ")


def _known_geometry(path: str) -> dict:
    """3 A4 pages: 72 pt side margins, frames without padding, 10/14 pt body,
    18 pt bold headings, a ruled banded table, an image and an accent rule."""
    from PIL import Image as PILImage
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_JUSTIFY
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import BaseDocTemplate, Frame, Image, PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle
    W, H = A4
    left = right = 72.0
    top = bottom = 80.0
    accent = "#1F6FB2"

    def deco(c, d):
        c.saveState()
        c.setStrokeColor(colors.HexColor(accent))
        c.setLineWidth(1.0)
        c.line(left, H - 56, W - right, H - 56)
        c.restoreState()
    doc = BaseDocTemplate(path, pagesize=A4, title="Known Geometry Reference", author="reference_analyzer tests")
    frame = Frame(left, bottom, W - left - right, H - top - bottom, leftPadding=0, rightPadding=0,
                  topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(frames=[frame], onPage=deco)])
    body = ParagraphStyle("b", fontName="Helvetica", fontSize=10, leading=14, alignment=TA_JUSTIFY, spaceAfter=8)
    h1 = ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=18, leading=22, spaceAfter=10,
                        textColor=colors.HexColor(accent))
    img_path = path + ".png"
    PILImage.new("RGB", (600, 300), (90, 140, 200)).save(img_path)
    story = []
    for p in range(3):
        story.append(Paragraph(f"Section {p + 1} Overview", h1))
        for _ in range(4):
            story.append(Paragraph(LOREM * 2, body))
        if p == 1:
            data = [["Region", "Revenue", "Growth", "Share"]] + [[f"Region {i}", f"{100 + i * 7}", f"{i}.5%", f"{10 + i}%"]
                                                                  for i in range(1, 7)]
            t = Table(data, colWidths=[150, 100, 100, 101.28])
            t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                                   ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DDE6F0")),
                                   ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F2F2")]),
                                   ("FONT", (0, 0), (-1, -1), "Helvetica", 9),
                                   ("LEFTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 4)]))
            story += [Spacer(1, 6), t]
        if p == 2:
            story += [Spacer(1, 6), Image(img_path, width=300, height=150)]
        if p < 2:
            story.append(PageBreak())
    doc.build(story)
    os.remove(img_path)
    return {"pages": 3, "body_size": 10.0, "line_height": 1.4, "h1_size": 18.0, "margin_left": left,
            "margin_right": right, "table": {"page": 2, "rows": 7, "cols": 4, "banded": True, "header_fill": True,
                                             "padding_left": 6.0},
            "image": {"page": 3, "width": 300.0, "height": 150.0}, "accent": accent, "rule_y": 56.0}


def _builder_pdf(path: str, kind: str):
    from dynamic_pdf import DocumentBuilder
    ar = ("تهدف استراتيجية الشركة إلى خفض الفاقد المائي ورفع نسبة إعادة استخدام المياه المعالجة وتقديم جميع "
          "الخدمات الرئيسية عبر القنوات الرقمية مع المحافظة على جودة الخدمة وكفاءة التشغيل في جميع المناطق.")
    if kind == "arabic":
        b = DocumentBuilder().meta(title="تقرير تجريبي", language="ar").direction("rtl")
        for i in range(4):
            b.heading(f"القسم {i + 1}: الأداء التشغيلي")
            for _ in range(3):
                b.paragraph(ar)
    else:
        b = DocumentBuilder().meta(title="Bilingual sample — عينة ثنائية اللغة")
        for i in range(3):
            b.heading(f"Section {i + 1} | القسم {i + 1}")
            b.paragraph(LOREM * 2)
            b.paragraph(ar)
    with open(path, "wb") as f:
        f.write(b.render())


def _spread(path: str):
    import pymupdf
    doc = pymupdf.open()
    W, H = A4[0] * 2, A4[1]
    for n in range(2):
        page = doc.new_page(width=W, height=H)
        for half in (0, 1):
            x0 = half * A4[0] + 60
            rect = pymupdf.Rect(x0, 80, x0 + A4[0] - 120, H - 80)
            page.insert_textbox(rect, (LOREM * 6), fontsize=10, fontname="helv")
    doc.set_metadata({"title": "Spread sample"})
    doc.save(path)


def _facing(path: str):
    import pymupdf
    doc = pymupdf.open()
    for n in range(6):
        page = doc.new_page(width=A4[0], height=A4[1])
        inner, outer = 90, 50
        left, right = (inner, outer) if n % 2 == 0 else (outer, inner)   # page 1 is a right-hand page
        rect = pymupdf.Rect(left, 80, A4[0] - right, A4[1] - 80)
        page.insert_textbox(rect, LOREM * 9, fontsize=10, fontname="helv", align=3)
    doc.set_metadata({"title": "Facing pages sample"})
    doc.save(path)


def _scanned(path: str):
    import pymupdf
    src = pymupdf.open()
    p = src.new_page(width=A4[0], height=A4[1])
    p.insert_textbox(pymupdf.Rect(72, 72, A4[0] - 72, A4[1] - 72), LOREM * 8, fontsize=11, fontname="helv")
    png = p.get_pixmap(dpi=60).tobytes("png")
    doc = pymupdf.open()
    page = doc.new_page(width=A4[0], height=A4[1])
    page.insert_image(page.rect, stream=png)
    doc.set_metadata({"title": "Scanned sample"})
    doc.save(path)


def _report_pair(path_full: str, path_summary: str):
    """Two related documents (same title/publisher), different content and length —
    like a full annual report and its summary edition. Must stay separate records."""
    import pymupdf
    for path, pages, tag in ((path_full, 12, "full report"), (path_summary, 4, "summary")):
        doc = pymupdf.open()
        for n in range(pages):
            page = doc.new_page(width=A4[0], height=A4[1])
            page.insert_textbox(pymupdf.Rect(60, 60, A4[0] - 60, 110), f"Northwind Annual Report 2023 — {tag}",
                                fontsize=18, fontname="hebo")
            page.insert_textbox(pymupdf.Rect(60, 130, A4[0] - 60, A4[1] - 80),
                                f"[{tag}, page {n + 1}] " + LOREM * (8 if tag == "full report" else 5),
                                fontsize=10 if tag == "full report" else 11, fontname="helv")
        doc.set_metadata({"title": "Northwind Annual Report 2023", "author": "Northwind (fictional)"})
        doc.save(path)


def build(out: str) -> dict:
    """Write the corpus into ``out``; return ground truth keyed by file name."""
    os.makedirs(out, exist_ok=True)
    gt = {"known_geometry.pdf": _known_geometry(os.path.join(out, "known_geometry.pdf"))}
    shutil.copyfile(os.path.join(out, "known_geometry.pdf"), os.path.join(out, "known_geometry_copy.pdf"))
    _builder_pdf(os.path.join(out, "arabic_report.pdf"), "arabic")
    _builder_pdf(os.path.join(out, "bilingual.pdf"), "bilingual")
    _spread(os.path.join(out, "spread.pdf"))
    _facing(os.path.join(out, "facing_pages.pdf"))
    _scanned(os.path.join(out, "scanned.pdf"))
    os.makedirs(os.path.join(out, "annual"), exist_ok=True)
    _report_pair(os.path.join(out, "annual", "northwind_annual_report_2023.pdf"),
                 os.path.join(out, "annual", "northwind_annual_report_2023_summary.pdf"))
    with open(os.path.join(out, "corrupt.pdf"), "wb") as f:
        f.write(b"%PDF-1.7\n%broken\n1 0 obj << /Type /Catalog >>\n" + os.urandom(64))
    rv = os.path.join(out, "05-Reviewed")
    os.makedirs(rv, exist_ok=True)
    with open(os.path.join(rv, "known_geometry.json"), "w", encoding="utf-8") as f:
        json.dump({"license": "CC0 (synthetic test file)", "source": "generated by sample_corpus.py",
                   "reviewer": "test"}, f, indent=1)
    with open(os.path.join(rv, "catalog.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["filename", "license", "source"])
        w.writerow(["northwind_annual_report_2023.pdf", "fictional sample — internal use", "sample_corpus.py"])
        w.writerow(["northwind_annual_report_2023_summary.pdf", "fictional sample — internal use", "sample_corpus.py"])
    gt["spread.pdf"] = {"spread_pages": [1, 2]}
    gt["facing_pages.pdf"] = {"inner": 90, "outer": 50}
    gt["scanned.pdf"] = {"no_text_layer_pages": [1]}
    gt["annual/northwind_annual_report_2023.pdf"] = {"pages": 12}
    gt["annual/northwind_annual_report_2023_summary.pdf"] = {"pages": 4}
    return gt


if __name__ == "__main__":
    print(json.dumps(build(sys.argv[1]), indent=1))
