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
