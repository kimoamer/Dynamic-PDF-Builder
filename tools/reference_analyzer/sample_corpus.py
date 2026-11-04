"""
Synthetic reference corpus with known ground truth (tests and demonstration).

    python -m tools.reference_analyzer.sample_corpus OUT_DIR

Every file is generated locally by this repository (ReportLab, PyMuPDF,
dynamic_pdf) — no third-party documents. ``build()`` returns the ground
truth used to check the analyzer's measurements.
"""
from __future__ import annotations

import csv
import hashlib
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


def _wrapped(text: str, width: float, size: float, count: int) -> list:
    """``count`` lines of helvetica text no wider than ``width``."""
    import pymupdf
    words, lines, cur = (text * 40).split(), [], ""
    for w in words:
        if pymupdf.get_text_length(f"{cur} {w}".strip(), fontname="helv", fontsize=size) > width:
            lines.append(cur)
            cur = w
            if len(lines) == count:
                break
        else:
            cur = f"{cur} {w}".strip()
    return lines


def _long_report(path: str):
    """6 pages: two columns of 9.7 pt text on 13.58 pt baselines (1.4×), a head at one position whose
    text changes with the section, a footer in three pieces across the page, a vertical side tab."""
    import pymupdf
    doc = pymupdf.open()
    W, H = A4
    for n in range(6):
        page = doc.new_page(width=W, height=H)
        page.insert_text((60, 40), ("Operations review", "Market overview", "Outlook and risks")[n // 2],
                         fontsize=9, fontname="helv")
        for x0 in (60, 310):
            for i, line in enumerate(_wrapped(LOREM, 225, 9.7, 46)):
                page.insert_text((x0, 90 + i * 13.58), line, fontsize=9.7, fontname="helv")
        for x, t in ((40, "Northwind Holdings"), (250, "Annual review"), (530, str(n + 1))):
            page.insert_text((x, H - 22), t, fontsize=8, fontname="helv")
        page.insert_text((16, 560), "Annual review section tab", fontsize=8, fontname="helv", rotate=90)
    doc.set_metadata({"title": "Long report sample"})
    doc.save(path)


def _spread_sheets(path: str):
    """4 sheets of two facing A4 pages (outer 60 pt, inner 30 pt); a footer runs across the centre;
    sheet 3 has text on its left half only."""
    import pymupdf
    doc = pymupdf.open()
    W, H = A4[0] * 2, A4[1]
    for n in range(4):
        page = doc.new_page(width=W, height=H)
        for half, (left, right) in enumerate(((60, 30), (30, 60))):
            if n == 2 and half == 1:
                continue
            page.insert_textbox(pymupdf.Rect(half * A4[0] + left, 80, (half + 1) * A4[0] - right, H - 80),
                                LOREM * 9, fontsize=10, fontname="helv", align=3)
        page.insert_text((360, H - 30), f"Northwind Holdings annual review, a footer running across the fold {n + 1}",
                         fontsize=12, fontname="helv")
    doc.set_metadata({"title": "Spread sheets sample"})
    doc.save(path)


def _landscape_slides(path: str):
    """3 A4 landscape pages with two text panels: single pages, not spreads."""
    import pymupdf
    doc = pymupdf.open()
    W, H = A4[1], A4[0]
    for _ in range(3):
        page = doc.new_page(width=W, height=H)
        for x0 in (50, W / 2 + 20):
            page.insert_textbox(pymupdf.Rect(x0, 70, x0 + W / 2 - 70, H - 70), LOREM * 4, fontsize=11, fontname="helv")
    doc.set_metadata({"title": "Landscape slides sample"})
    doc.save(path)


def _garbled(path: str):
    """Arabic stored through a broken font encoding: the text layer reads as accented Latin."""
    import pymupdf
    junk = ("تهدف استراتيجية الشركة إلى خفض الفاقد المائي ورفع نسبة إعادة استخدام المياه المعالجة وتقديم الخدمات "
            ).encode("cp1256").decode("latin-1")
    doc = pymupdf.open()
    page = doc.new_page(width=A4[0], height=A4[1])
    page.insert_textbox(pymupdf.Rect(72, 72, A4[0] - 72, A4[1] - 72), junk * 8, fontsize=10, fontname="helv")
    doc.set_metadata({"title": "Garbled text layer sample"})
    doc.save(path)


def _png(w: int, h: int, rgb: tuple) -> bytes:
    import io

    from PIL import Image as PILImage
    buf = io.BytesIO()
    PILImage.new("RGB", (w, h), rgb).save(buf, "PNG")
    return buf.getvalue()


def _mixed_media(path: str):
    """7 pages. p1: a 360×200 pt picture stored as 6×5 tiles. p2, p5: full-page photo openers with a
    40 pt title. p3, p4, p6, p7: text pages with 16 pt headings; p3, p4 also a thin header band with a small
    line under it, p6, p7 a 48 pt numeral."""
    import pymupdf
    doc = pymupdf.open()
    W, H = A4
    tile, photo, band = _png(60, 40, (90, 140, 200)), _png(120, 170, (60, 90, 70)), _png(400, 20, (20, 60, 120))
    for n in range(1, 8):
        page = doc.new_page(width=W, height=H)
        if n in (2, 5):
            page.insert_image(page.rect, stream=photo)
            page.insert_text((70, 200), "Part", fontsize=40, fontname="hebo", color=(1, 1, 1))
            continue
        if n == 1:
            for r in range(5):
                for c in range(6):
                    page.insert_image(pymupdf.Rect(100 + c * 60, 340 + r * 40, 160 + c * 60, 380 + r * 40), stream=tile)
            page.insert_textbox(pymupdf.Rect(70, 80, W - 70, 330), LOREM * 3, fontsize=10, fontname="helv")
            continue
        if n in (3, 4):
            page.insert_image(pymupdf.Rect(50, 24, W - 50, 44), stream=band)
            page.insert_text((70, 60), "Section note", fontsize=8, fontname="helv")
        else:
            page.insert_text((70, 70), "2024", fontsize=48, fontname="hebo")
        page.insert_text((70, 110), "Results", fontsize=16, fontname="hebo")
        page.insert_textbox(pymupdf.Rect(70, 130, W - 70, H - 80), LOREM * 8, fontsize=10, fontname="helv")
    doc.set_metadata({"title": "Mixed media sample"})
    doc.save(path)


def _ruled_tables(path: str):
    """p1: 6×3 table of right-aligned numbers, 4 pt from the cell edge, ruled with thin filled paths and
    without any cell fill; a one-row framed box. p2: 6×3 table filled cell by cell: header and bands.
    p3: a plain 6×3 table."""
    import pymupdf
    doc = pymupdf.open()
    W, H = A4
    xs, grey = (60, 260, 400, 530), (0.4, 0.4, 0.4)

    def rule(page, x0, y0, x1, y1):
        page.draw_rect(pymupdf.Rect(x0, y0, x1, y1), color=None, fill=grey, width=0)

    def grid(page, ys):
        for y in ys:
            rule(page, xs[0], y, xs[-1] + 0.6, y + 0.6)
        for x in xs:
            rule(page, x, ys[0], x + 0.6, ys[-1] + 0.6)
    first = doc.new_page(width=W, height=H)
    first.insert_textbox(pymupdf.Rect(60, 60, W - 60, 90), LOREM, fontsize=10, fontname="helv")
    ys = [110 + i * 22 for i in range(7)]
    for r in range(6):
        for c in range(3):
            t = f"{(r + 1) * (c + 2) * 137:,}"
            x = xs[c + 1] - 4 - pymupdf.get_text_length(t, fontname="helv", fontsize=10)
            first.insert_text((x, ys[r] + 15), t, fontsize=10, fontname="helv")
    grid(first, ys)
    grid(first, [320, 350])
    first.insert_text((66, 339), "Figures in thousands", fontsize=10, fontname="helv")
    first.insert_textbox(pymupdf.Rect(60, 380, W - 60, H - 80), LOREM * 6, fontsize=10, fontname="helv")
    second = doc.new_page(width=W, height=H)
    second.insert_textbox(pymupdf.Rect(60, 60, W - 60, 90), LOREM, fontsize=10, fontname="helv")
    for r in range(6):
        fill = (0.1, 0.3, 0.5) if r == 0 else (0.9, 0.9, 0.9) if r % 2 == 0 else None
        for c in range(3):
            if fill:
                second.draw_rect(pymupdf.Rect(xs[c], ys[r], xs[c + 1], ys[r + 1]), color=None, fill=fill, width=0)
            second.insert_text((xs[c] + 6, ys[r] + 15), f"Row {r} item {c}", fontsize=10, fontname="helv")
    grid(second, ys)
    second.insert_textbox(pymupdf.Rect(60, 280, W - 60, H - 80), LOREM * 6, fontsize=10, fontname="helv")
    third = doc.new_page(width=W, height=H)
    for r in range(6):
        for c in range(3):
            third.insert_text((xs[c] + 6, ys[r] + 15), f"Plain {r} item {c}", fontsize=10, fontname="helv")
    grid(third, ys)
    third.insert_textbox(pymupdf.Rect(60, 280, W - 60, H - 80), LOREM * 6, fontsize=10, fontname="helv")
    doc.set_metadata({"title": "Ruled tables sample"})
    doc.save(path)


def _template_refill(path: str, company: str):
    """One fictional-company template: 3 pages of 9 pt text, only the name changes."""
    import pymupdf
    doc = pymupdf.open()
    for n in range(3):
        page = doc.new_page(width=A4[0], height=A4[1])
        page.insert_textbox(pymupdf.Rect(66, 80, A4[0] - 66, A4[1] - 90),
                            (f"{company} profile page {n + 1}. " + LOREM) * 8, fontsize=9, fontname="helv", align=3)
    doc.set_metadata({"title": f"{company} profile"})
    doc.save(path)


def _compilation(path: str):
    """Pages from three unrelated formats bound together."""
    import pymupdf
    doc = pymupdf.open()
    for w, h in ((A4[0], A4[1]), (612, 792), (960, 540), (A4[0], A4[1]), (612, 792), (960, 540)):
        page = doc.new_page(width=w, height=h)
        page.insert_textbox(pymupdf.Rect(60, 60, w - 60, h - 60), LOREM * 4, fontsize=12, fontname="helv")
    doc.set_metadata({"title": "Compilation sample"})
    doc.save(path)


def _reviewed_index(out: str, rv: str):
    """A rights index and a features dump for one PDF, plus records that must not match their PDFs."""
    sha = hashlib.sha256(open(os.path.join(out, "facing_pages.pdf"), "rb").read()).hexdigest()
    with open(os.path.join(rv, "observed-features.json"), "w", encoding="utf-8") as f:
        json.dump({"note": "per-page observations", "documents": [
            {"id": "S-1", "original_relative_path": "facing_pages.pdf", "sha256": sha, "pdf_pages": 6,
             "sampled_page_details": [{"page": 1, "text_start": "sample text kept out of the catalogue"}]}]}, f, indent=1)
    with open(os.path.join(rv, "rights-index.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "file", "pages", "rights_status", "rights_evidence", "sha256"])
        w.writerow(["S-1", "facing_pages.pdf", "6", "study only", "generated by sample_corpus.py", sha])
        w.writerow(["S-2", "spread.pdf", "2", "must not apply: other bytes", "", "0" * 64])
        w.writerow(["S-3", "bilingual.pdf", "99", "synthetic", "", ""])
        w.writerow(["S-4", "archive/scanned.pdf", "1", "must not apply: other folder", "", ""])


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
    _long_report(os.path.join(out, "long_report.pdf"))
    _spread_sheets(os.path.join(out, "spread_sheets.pdf"))
    _landscape_slides(os.path.join(out, "landscape_slides.pdf"))
    _garbled(os.path.join(out, "garbled.pdf"))
    _mixed_media(os.path.join(out, "mixed_media.pdf"))
    _ruled_tables(os.path.join(out, "ruled_tables.pdf"))
    _template_refill(os.path.join(out, "template_alpha.pdf"), "Alpha Works")
    _template_refill(os.path.join(out, "template_gamma.pdf"), "Gamma Works")
    _compilation(os.path.join(out, "compilation.pdf"))
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
    _reviewed_index(out, rv)
    gt["spread.pdf"] = {"spread_pages": [1, 2]}
    gt["long_report.pdf"] = {"pages": 6, "columns": 2, "line_height": 1.4, "margin_left": 60, "margin_top": 90}
    gt["spread_sheets.pdf"] = {"spread_pages": [1, 2, 3, 4], "outer": 60, "inner": 30}
    gt["ruled_tables.pdf"] = {"padding": 4.0}
    gt["facing_pages.pdf"] = {"inner": 90, "outer": 50}
    gt["scanned.pdf"] = {"no_text_layer_pages": [1]}
    gt["annual/northwind_annual_report_2023.pdf"] = {"pages": 12}
    gt["annual/northwind_annual_report_2023_summary.pdf"] = {"pages": 4}
    return gt


if __name__ == "__main__":
    print(json.dumps(build(sys.argv[1]), indent=1))
