"""M2: Arabic RTL and bilingual DOCX."""
import io
import zipfile
from docx.oxml.ns import qn
from dynamic_pdf import DocumentBuilder
from conftest import open_docx, docx_text, fixture_text


def _bidi(p):
    pPr = p._p.pPr
    return pPr is not None and pPr.find(qn("w:bidi")) is not None


def test_arabic_document_paragraphs_are_bidi_with_cs_font():
    data = DocumentBuilder.from_markdown(fixture_text("arabic_report.md")).design().render_docx()
    d = open_docx(data)
    arabic = [p for p in d.paragraphs if p.text.strip()]
    assert arabic and all(_bidi(p) for p in arabic)
    xml = zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml").decode()
    assert 'w:cs="Amiri"' in xml and "<w:rtl" in xml
    sect = d.sections[0]._sectPr
    assert sect.find(qn("w:bidi")) is not None
    for word in ("الملخص", "التنفيذي", "التوصيات", "الأتمتة"):
        assert word in docx_text(data)


def test_bilingual_paragraph_direction_per_paragraph_and_table_order():
    data = DocumentBuilder.from_markdown(fixture_text("bilingual.md")).render_docx()
    d = open_docx(data)
    by_text = {p.text: p for p in d.paragraphs if p.text}
    en = [p for t, p in by_text.items() if t.startswith("The board")][0]
    ar = [p for t, p in by_text.items() if t.startswith("وافق")][0]
    assert _bidi(ar) and not _bidi(en)
    table = d.tables[0]
    assert [c.text for c in table.rows[0].cells] == ["Item", "البند", "Amount"]
    assert table._tbl.tblPr.find(qn("w:bidiVisual")) is None    # English-led table keeps LTR order
    assert "12.5" in docx_text(data) and "SAR 12.5M" in docx_text(data)
