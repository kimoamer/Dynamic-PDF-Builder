"""M7.1 PDF correctness gate: Arabic line order, mixed-script glyphs, diacritics, QA."""
import io
import re
import unicodedata

import pymupdf
import pytest

from dynamic_pdf import DocumentBuilder
from conftest import docx_text, open_docx

SRC = ("يسر إدارة الموارد البشرية إبلاغكم بتحديث سياسة العمل المرن اعتباراً من الأول من ديسمبر وذلك بعد تقييم "
       "التجربة التي استمرت ستة أشهر وأظهرت تحسناً في الإنتاجية ورضا الموظفين وتعاون الفرق المختلفة في جميع "
       "الإدارات والفروع الرئيسية للشركة")
SRC2 = ("وقد حققت الشركة نمواً ملحوظاً خلال الربع الثالث بدعم من توسع شبكة التوزيع وارتفاع رضا العملاء "
        "وتحسن كفاءة التحصيل وانخفاض تكاليف الطاقة واستمرار برامج التدريب والتأهيل للكوادر الوطنية")
HARAKAT = re.compile("[ً-ْ]")


def _key(w: str) -> str:
    w = "".join(c for c in unicodedata.normalize("NFKC", w) if c.isalnum() and unicodedata.category(c) != "Mn")
    return min(w, w[::-1])              # extraction order of RTL glyphs is not significant


def _unique_positions(text: str) -> dict:
    words = [_key(w) for w in text.split()]
    return {w: i for i, w in enumerate(words) if words.count(w) == 1}


def _rtl_lines(pdf: bytes, positions: dict, pages=None):
    """Source positions of recognised words, per line top-to-bottom, each line read right-to-left."""
    out = []
    doc = pymupdf.open(stream=pdf, filetype="pdf")
    for pno in pages if pages is not None else range(doc.page_count):
        ws = doc[pno].get_text("words")
        for y in sorted({round(w[3]) for w in ws}):
            row = sorted([w for w in ws if round(w[3]) == y], key=lambda w: -w[2])
            idx = [positions[_key(w[4])] for w in row if _key(w[4]) in positions]
            if idx:
                out.append(idx)
    return out


def _assert_reading_order(lines, min_lines=2):
    assert len(lines) >= min_lines, lines
    flat = [i for ln in lines for i in ln]
    assert flat == sorted(flat), f"words out of reading order: {lines}"


def _fonts(pdf: bytes) -> set:
    return {s["font"] for p in pymupdf.open(stream=pdf, filetype="pdf")
            for b in p.get_text("dict")["blocks"] for ln in b.get("lines", []) for s in ln["spans"]}


# ── line order ──────────────────────────────────────────────────────────

def test_rtl_paragraph_lines_read_top_to_bottom_right_to_left():
    pdf = DocumentBuilder().meta(title="t", language="ar").direction("rtl").paragraph(SRC).render()
    _assert_reading_order(_rtl_lines(pdf, _unique_positions(SRC)), min_lines=3)


def test_arabic_paragraph_in_ltr_document_keeps_reading_order():
    pdf = DocumentBuilder().meta(title="t").paragraph("English intro.").paragraph(SRC).design().render()
    _assert_reading_order(_rtl_lines(pdf, _unique_positions(SRC)), min_lines=2)


def test_paragraph_split_across_pages_keeps_order_and_direction():
    b = DocumentBuilder().meta(title="t", language="ar").direction("rtl")
    filler = "نص تمهيدي قصير " * 12
    for _ in range(33):           # the paragraph starts 2 lines above the page end
        b.paragraph(filler)
    long_text = SRC + " " + SRC2
    b.paragraph(long_text)
    pdf = b.render()
    pages = pymupdf.open(stream=pdf).page_count
    assert pages >= 2
    lines = _rtl_lines(pdf, _unique_positions(long_text))
    on_last = _rtl_lines(pdf, _unique_positions(long_text), pages=[pages - 1])
    assert on_last and len(on_last) < len(lines), "paragraph was not split across pages"
    _assert_reading_order(lines, min_lines=4)


def test_ltr_text_is_untouched():
    from dynamic_pdf.layout import factory as F
    from reportlab.lib.styles import ParagraphStyle
    p = F.Paragraph("Plain English text, nothing to reorder.", ParagraphStyle("x"))
    assert p._bidi_base() is None
    p.wrap(200, 500)
    line = p.blPara.lines[0]
    assert F._visual_line(line, p.blPara.kind, "L") is line


# ── glyphs, diacritics ──────────────────────────────────────────────────

@pytest.mark.parametrize("design", [False, True])
def test_mixed_script_heading_has_real_glyphs(design):
    b = DocumentBuilder().meta(title="t").quality("permissive").heading("Risks | إدارة المخاطر").paragraph("Body.")
    if design:
        b.design()
    data, rep = b.qa("pdf")
    assert not (_fonts(data) & {"ZapfDingbats", "Symbol"})
    assert "Amiri-Bold" in _fonts(data) or "Amiri-Regular" in _fonts(data)
    assert rep.passed, rep.summary()
    heading_line = [ln for ln in _rtl_lines(data, _unique_positions("إدارة المخاطر")) if ln]
    assert heading_line == [[0, 1]]


def test_long_mixed_heading_wraps_inside_the_margins():
    h = "Performance Overview and Strategic Outlook | نظرة عامة على الأداء والتوقعات الاستراتيجية للعام"
    data, rep = DocumentBuilder().meta(title="t").quality("permissive").heading(h).paragraph("Body.").qa("pdf")
    assert not [f for f in rep.errors if f.code in ("overflow", "clipped_text", "missing_glyph")], rep.summary()


def test_arabic_diacritics_survive_in_pdf_and_docx():
    text = "كتابٌ مُفيدٌ جداً واعتباراً من اليوم"
    b = DocumentBuilder().meta(title="t", language="ar").direction("rtl").paragraph(text)
    n = len(HARAKAT.findall(text))
    pdf_text = "".join(p.get_text() for p in pymupdf.open(stream=b.render(), filetype="pdf"))
    assert len(HARAKAT.findall(pdf_text)) == n
    assert len(HARAKAT.findall(docx_text(b.render_docx()))) == n


def test_callout_title_quote_attribution_and_toc_keep_reading_order():
    title, attribution, heading = "تنبيه مهم للموظفين", "إدارة الموارد البشرية", "سياسة العمل المرن"
    b = (DocumentBuilder().meta(title="t", language="ar").direction("rtl").table_of_contents()
         .heading(heading).callout("نص التنبيه.", title=title).quote("اقتباس قصير.", attribution=attribution))
    pdf = b.render()
    for text in (title, attribution, heading):          # heading: body and TOC entry
        full = list(range(len(text.split())))
        lines = _rtl_lines(pdf, _unique_positions(text))
        assert full in lines and all(ln == sorted(ln) for ln in lines), (text, lines)


# ── QA ──────────────────────────────────────────────────────────────────

def test_pdf_qa_rejects_text_drawn_with_a_symbol_font():
    from reportlab.pdfgen.canvas import Canvas
    from dynamic_pdf.qa import check_pdf
    buf = io.BytesIO()
    c = Canvas(buf)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(72, 700, "Risks |")
    c.setFont("ZapfDingbats", 16)
    c.drawString(140, 700, "IIIII III")
    c.save()
    rep = check_pdf(buf.getvalue(), margins={"left": 54, "right": 54})
    assert rep.status == "fail" and any(f.code == "missing_glyph" for f in rep.errors)


# ── editable DOCX ───────────────────────────────────────────────────────

def test_docx_keeps_logical_text_heading_styles_and_bidi():
    heading = "Risks | إدارة المخاطر"
    b = (DocumentBuilder().meta(title="t", language="ar").direction("rtl")
         .heading(heading).paragraph(SRC).paragraph("كتابٌ مُفيدٌ"))
    data = b.render_docx()
    d = open_docx(data)
    heads = [p for p in d.paragraphs if p.style.name.startswith("Heading")]
    assert any(p.text.endswith(heading) for p in heads)
    body = [p for p in d.paragraphs if p.text == SRC]
    assert body, "Arabic paragraph is not stored as editable logical text"
    W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    assert body[0]._p.pPr is not None and body[0]._p.pPr.find(W + "bidi") is not None
    assert "كتابٌ مُفيدٌ" in docx_text(data)


# ── justified right-to-left paragraphs ─────────────────────────────────

def _paragraph_lines(pdf: bytes):
    """Body lines of a one-paragraph page, top to bottom (PyMuPDF may split one paragraph
    into several blocks, so blocks are not used)."""
    page = pymupdf.open(stream=pdf, filetype="pdf")[0]
    lines = [ln["bbox"] for b in page.get_text("dict")["blocks"] for ln in b.get("lines", [])
             if 40 < ln["bbox"][1] < page.rect.height - 60]
    return [sorted(lines, key=lambda b: b[1])]


@pytest.mark.parametrize("text", [SRC, SRC.replace("الموارد البشرية", "**الموارد البشرية**")])
def test_justified_rtl_paragraph_ends_its_last_line_on_the_right(text):
    """ReportLab justifies as if text ran left to right, which set the short last line of an
    Arabic paragraph flush left. Arabic paragraphs also take no first-line indent, as in DOCX."""
    from dynamic_pdf.themes import get_theme
    assert get_theme("claude").spacing.first_line_indent > 0     # the classic theme indents Latin text
    lines = _paragraph_lines(DocumentBuilder().paragraph(text).render())[0]
    assert len(lines) >= 2
    right = max(b[2] for b in lines)
    left = min(b[0] for b in lines)
    first, last = lines[0], lines[-1]
    assert first[2] == pytest.approx(right, abs=2) and first[0] == pytest.approx(left, abs=2)
    assert last[2] == pytest.approx(right, abs=2)                # the last line ends at the right
    assert last[0] > left + 20                                   # and is not stretched


def test_rtl_first_line_indent_sits_at_the_right_edge():
    """A style that does indent an Arabic paragraph indents it from the right."""
    from reportlab.lib.styles import ParagraphStyle
    from dynamic_pdf.layout.factory import Paragraph, _plain_markup
    para = Paragraph(_plain_markup(SRC), ParagraphStyle("t", fontName="Amiri", fontSize=11, leading=16,
                                                         alignment=4, firstLineIndent=30))
    para.wrap(400, 800)
    from reportlab.pdfgen.canvas import Canvas
    buf = io.BytesIO()
    c = Canvas(buf)
    para.drawOn(c, 50, 400)
    c.save()
    page = pymupdf.open(stream=buf.getvalue(), filetype="pdf")[0]
    lines = sorted((ln["bbox"] for b in page.get_text("dict")["blocks"] for ln in b.get("lines", [])),
                   key=lambda b: b[1])
    right, left = max(b[2] for b in lines), min(b[0] for b in lines)
    assert right - lines[0][2] == pytest.approx(30, abs=2) and lines[0][0] == pytest.approx(left, abs=2)
    assert lines[-1][2] == pytest.approx(right, abs=2)


def test_justified_ltr_paragraph_is_unchanged_by_the_rtl_fix():
    lines = next(ls for ls in _paragraph_lines(DocumentBuilder().paragraph("Plain English text. " * 20).render())
                 if len(ls) >= 2)
    left = min(b[0] for b in lines)
    assert lines[0][0] > left + 20 and lines[-1][0] == pytest.approx(left, abs=2)
