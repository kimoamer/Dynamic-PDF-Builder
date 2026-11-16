"""M14: Arabic text extraction, hyphenation, contrast, tagging, Word footnotes, QA without PyMuPDF."""
import io

import pymupdf
import pytest

from dynamic_pdf import DocumentBuilder

SRC = ("يسر إدارة الموارد البشرية إبلاغكم بتحديث سياسة العمل المرن اعتباراً من الأول من ديسمبر وذلك بعد تقييم "
       "التجربة التي استمرت ستة أشهر وأظهرت تحسناً في الإنتاجية ورضا الموظفين وتعاون الفرق المختلفة في جميع "
       "الإدارات والفروع الرئيسية للشركة")


def _text(pdf: bytes) -> str:
    return " ".join("".join(p.get_text() for p in pymupdf.open(stream=pdf, filetype="pdf")).split())


# ── F10: Arabic extracts as the letters the author wrote ─────────────────

@pytest.mark.parametrize("design", [False, True])
def test_verbatim_search_finds_arabic_source_text(design):
    heading = "سياسة العمل المرن"
    b = DocumentBuilder().meta(title="t", language="ar").direction("rtl").heading(heading).paragraph(SRC)
    if design:
        b.design()
    text = _text(b.render())
    assert not any(0xFB50 <= ord(c) <= 0xFEFF for c in text), "presentation forms in extracted text"
    assert heading in text
    assert SRC in text                      # verbatim: no NFKC, lam-alef ("إبلاغكم", "الأول") in order


def test_raw_extractor_reads_the_exact_mirror():
    pdfminer = pytest.importorskip("pdfminer.high_level")
    pdf = DocumentBuilder().meta(title="t", language="ar").direction("rtl").paragraph("إبلاغكم من الأول").render()
    raw = pdfminer.extract_text(io.BytesIO(pdf))
    assert "إبلاغكم"[::-1] in raw and "الأول"[::-1] in raw


def test_latin_fonts_keep_their_tounicode():
    from reportlab.pdfbase import ttfonts
    plain = ttfonts.makeToUnicodeCMap.__defaults__[0]
    subset = [0, 32, 65, 0x0628]
    assert ttfonts.makeToUnicodeCMap("X", subset) == plain("X", subset)
    assert "<01> <06270644>" in ttfonts.makeToUnicodeCMap("X", [0, 0xFEFB])   # lam-alef, visual order


# ── F11: hyphenation of justified left-to-right body text ────────────────

LONG = ("Internationalization considerations notwithstanding, telecommunications infrastructure "
        "modernization necessitates comprehensive interoperability characterization, institutional "
        "accountability mechanisms and multidisciplinary implementation responsibilities. ") * 4


def _lines(pdf: bytes):
    return [" ".join(s["text"] for s in ln["spans"]).rstrip()
            for p in pymupdf.open(stream=pdf, filetype="pdf")
            for b in p.get_text("dict")["blocks"] for ln in b.get("lines", [])]


def _hyphen_ends(lines):
    return [ln for ln in lines if ln.endswith("-") and ln[-2:-1].isalpha()]


def test_justified_probe_paragraph_hyphenates_and_keeps_every_word():
    from dynamic_pdf.qa.content_preservation import _dehyphenate
    b = DocumentBuilder().meta(title="t").paragraph(LONG)
    pdf = b.render()
    assert _hyphen_ends(_lines(pdf)), "no line of the probe broke at a hyphenation point"
    joined = " ".join(_dehyphenate("".join(p.get_text() for p in pymupdf.open(stream=pdf))).split())
    assert LONG.strip() in joined
    data, rep = DocumentBuilder().meta(title="t").paragraph(LONG).qa("pdf")
    assert rep.passed, rep.summary()


@pytest.mark.parametrize("make", [
    lambda b: b.heading("Internationalization considerations notwithstanding telecommunications "
                        "infrastructure modernization necessitates interoperability characterization"),
    lambda b: b.table(["Characterization"], [[LONG[:400]]]),
    lambda b: b.code("text", LONG[:300]),
    lambda b: b.bullet_list([LONG[:400]]),
])
def test_no_hyphenation_outside_body_paragraphs(make):
    pdf = make(DocumentBuilder().meta(title="t")).render()
    assert not _hyphen_ends(_lines(pdf))


def test_no_hyphenation_in_right_to_left_or_without_a_dictionary():
    from dynamic_pdf.layout.factory import _hyphenation_lang
    assert _hyphenation_lang("ar") == "" and _hyphenation_lang("en") == "en"
    pdf = DocumentBuilder().meta(title="t", language="ar").direction("rtl").paragraph(LONG).render()
    assert not _hyphen_ends(_lines(pdf))


def test_word_hyphenates_body_text_only():
    from docx.oxml.ns import qn
    from conftest import open_docx
    d = open_docx(DocumentBuilder().meta(title="t").heading("H").paragraph(LONG).render_docx())
    assert d.settings.element.find(qn("w:autoHyphenation")) is not None
    sup = lambda name: d.styles[name].element.pPr.find(qn("w:suppressAutoHyphens")).get(qn("w:val"))
    assert sup("Normal") == "1" and sup("Body Text") == "0"       # headings, tables, code inherit Normal
    rtl = open_docx(DocumentBuilder().meta(title="t", language="ar").direction("rtl").paragraph("نص").render_docx())
    assert rtl.settings.element.find(qn("w:autoHyphenation")) is None
