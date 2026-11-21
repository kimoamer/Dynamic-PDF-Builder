"""Defects a full annual report (photos, bubbles, every chart, footnotes, a signed foreword) showed,
each pinned to what a reader sees."""
import io
import zipfile

import pytest
from PIL import Image

from dynamic_pdf import DocumentBuilder

fitz = pytest.importorskip("fitz")


def _photo(tmp_path, w=400, h=600):
    p = tmp_path / "photo.jpg"
    Image.new("RGB", (w, h), "#5a7d9a").save(p)
    return str(p)


def _text(pdf: bytes) -> str:
    return "".join(page.get_text() for page in fitz.open(stream=pdf, filetype="pdf"))


def test_a_captioned_photo_in_a_column_renders(tmp_path):
    # KeepTogether reports a huge height to force a split, and a table cell cannot split
    b = DocumentBuilder()
    b.two_column(left=[{"type": "image", "src": _photo(tmp_path), "alt_text": "a", "caption": "Photo credit"}],
                 right=["Text beside it."], ratio=0.42)
    assert "Photo credit" in _text(b.render())


def test_charts_without_colours_take_the_brand():
    from dynamic_pdf.renderers.chart import _branded
    from dynamic_pdf.schema.blocks import ChartBlock
    from dynamic_pdf.themes import get_theme
    theme = get_theme("government")
    theme.colors.primary, theme.colors.accent = "#0B5E91", "#F2A900"
    picked = _branded(ChartBlock(chart_type="bar", data={"a": 1}), theme).colors
    assert picked[:2] == ["#0b5e91", "#f2a900"] and len(picked) >= 8
    assert _branded(ChartBlock(chart_type="bar", data={"a": 1}, colors=["#123456"]), theme).colors == ["#123456"]


def test_text_on_a_fill_takes_the_ink_with_more_contrast():
    from dynamic_pdf.layout.page_system import readable_on
    from dynamic_pdf.utils.color import contrast_ratio, legible
    assert readable_on("#009EB2") == readable_on("#F2A900") == "#1F2933"
    assert readable_on("#0B5E91") == "#FFFFFF"
    assert contrast_ratio(legible("#00C853"), "#ffffff") >= 4.5


def test_a_labelled_footnote_is_numbered_in_pdf_and_word():
    md = "Reach is counted once.[^method]\n\n[^method]: Programme registers, checked by country offices.\n"
    b = DocumentBuilder.from_markdown(md)
    text = _text(b.render())
    assert "method" not in text and "1" in text
    xml = zipfile.ZipFile(io.BytesIO(b.render_docx())).read("word/document.xml").decode()
    assert "customMarkFollows" not in xml and "footnoteReference" in xml


def test_a_signed_foreword_keeps_its_signature_on_its_page():
    b = DocumentBuilder()
    b.preface_page("A short foreword.", title="Foreword")
    b.signature("Amara Mensah", title="Director-General")
    b.heading("Next section", 1)
    b.paragraph("Body.")
    pages = [p.get_text() for p in fitz.open(stream=b.render(), filetype="pdf")]
    assert "Amara Mensah" in pages[0] and "Next section" not in pages[0]


def test_word_value_axis_starts_at_zero_in_round_steps():
    from dynamic_pdf.renderers.docx_chart import _ceiling, _step, chart_xml
    for top in (12.4, 1.42, 812, 0.3):
        c = _ceiling({"a": [top]}, False)
        assert abs(c / _step(c) - round(c / _step(c))) < 1e-6 and c / _step(c) <= 8
    xml = chart_xml("stacked_bar", ["2025", "2026"], {"a": [5.2, 7.9], "b": [2.1, 3.8]}, ["#0B5E91", "#F2A900"], title=None, x_label=None, y_label=None, legend=True, font="Arial", arabic_font="Arial", workbook=False).decode()
    assert '<c:min val="0"/>' in xml and "<c:majorUnit" in xml


def test_shape_label_reads_markdown_and_progress_values_keep_their_form():
    b = DocumentBuilder()
    b.shape("circle", width=140, height=140, fill_color="#0B5E91", label="**12.4M**\nchildren in school")
    b.progress_bar([{"label": "Girls", "value": 49.2}, {"label": "Teachers", "value": 86000, "max_value": 90000}])
    text = _text(b.render())
    assert "12.4M" in text and "**" not in text
    assert "49.2" in text and "86,000" in text


def test_a_heading_followed_by_a_vector_chart_is_not_stranded():
    b = DocumentBuilder()
    b.paragraph("Intro. " * 40)
    b.heading("Learning", 2)
    b.chart("bar", {"a": 1, "b": 2, "c": 3}, title="Children in school")
    _, report = b.qa("pdf")
    assert not [f for f in report.findings if f.code == "stranded_heading"]


def test_a_picture_in_a_word_column_fits_the_column(tmp_path):
    from docx import Document as Docx
    b = DocumentBuilder()
    b.two_column(left=[{"type": "shape", "shape_type": "circle", "width": 300, "height": 300, "fill_color": "#0B5E91"}],
                 right=["Beside it."], ratio=0.3)
    doc = Docx(io.BytesIO(b.render_docx()))
    cell = doc.tables[0].rows[0].cells[0]
    pic = cell._tc.xpath(".//wp:extent")[0]
    assert int(pic.get("cx")) <= cell.width
