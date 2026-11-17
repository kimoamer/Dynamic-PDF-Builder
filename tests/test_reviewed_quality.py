"""Human-review fixes: deterministic quality bounds independent of AI labels."""
import io

import pytest
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn

from dynamic_pdf import DocumentBuilder
from dynamic_pdf.design.reviewed_quality import PALETTES, SIZE, apply_reviewed_quality
from dynamic_pdf.design.art_direction import direct
from dynamic_pdf.design.directions import DIRECTIONS
from dynamic_pdf.schema.theme import Theme


@pytest.mark.parametrize("script", ["ltr", "rtl", "bilingual"])
def test_reviewed_standard_sizes_margins_and_palette(script):
    theme = Theme(name="overstyled")
    theme.spacing.page_margin_left = 150
    theme.spacing.page_margin_right = 35
    notes = apply_reviewed_quality(theme, script=script, palette="forest")
    title, h1, h2, h3, body, caption, note = SIZE[script]
    assert (theme.typography.title_size, theme.typography.heading_h1_size,
            theme.typography.heading_h2_size, theme.typography.heading_h3_size) == (title, h1, h2, h3)
    assert theme.typography.base_size == body
    assert theme.typography.caption_size == caption
    assert theme.typography.note_size == note
    assert theme.spacing.page_margin_left == 80
    assert theme.spacing.page_margin_right == 64
    assert theme.colors.primary == PALETTES["forest"][0]
    assert notes and "human-reviewed" in notes[0]


def test_custom_brand_colours_remain_intact():
    theme = Theme(name="branded")
    theme.colors.primary = "#17362D"
    theme.colors.accent = "#AA8800"
    apply_reviewed_quality(theme, script="ltr", preserve_brand=True)
    assert theme.colors.primary == "#17362D"
    assert theme.colors.accent == "#AA8800"
    assert theme.typography.base_size == 11.5


def test_intelligent_design_uses_reviewed_standard():
    b = DocumentBuilder().meta(title="Report").heading("Highlights").paragraph("Several results were recorded.")
    assert b.design(None)._prepared()[1] is None
    b.design("executive_report")
    _, theme = b._prepared()
    assert theme.typography.base_size == 11.5
    assert theme.typography.heading_h1_size == 17
    assert theme.colors.primary in {v[0] for v in PALETTES.values()}


def test_art_direction_applies_reviewed_standard():
    b = DocumentBuilder().meta(title="Annual report").heading("Results").paragraph("A measurable improvement.")
    designed = direct(b.semantic(), DIRECTIONS["editorial_modern"])
    assert designed.theme.typography.base_size == 11.5
    assert designed.theme.typography.title_size == 26
    assert 64 <= designed.theme.spacing.page_margin_left <= 80
    assert designed.theme.colors.primary == PALETTES["slate"][0]


def test_plan_typography_reports_the_size_on_the_page():
    # financial_data's recipe asks for 9.6pt; the reviewed standard sets 11.5pt, and the plan must say so
    b = DocumentBuilder().meta(title="Annual report").heading("Results").paragraph("A measurable improvement.")
    designed = direct(b.semantic(), DIRECTIONS["financial_data"])
    ty = designed.theme.typography
    assert designed.plan.typography.endswith(f" {ty.base_size:g}/{ty.line_height:g}")


def test_docx_body_justified_and_arabic_caption_uses_complex_script_size():
    b = (DocumentBuilder().meta(title="تقرير", language="ar").direction("rtl")
         .heading("النتائج").paragraph("تحسنت المؤشرات الاقتصادية والاجتماعية خلال هذا العام.")
         .table(["البند", "القيمة"], [["العدد", "١٢٠"]], caption="نتائج القياس"))
    d = Document(io.BytesIO(b.render_docx()))
    body = next(p for p in d.paragraphs if p.style.name == "Body Text" and p.text)
    assert body.alignment == WD_ALIGN_PARAGRAPH.JUSTIFY
    assert d.styles["Body Text"].paragraph_format.alignment == WD_ALIGN_PARAGRAPH.JUSTIFY
    cap = d.styles["Caption"]
    assert cap.element.rPr.rFonts.get(qn("w:cs")) == "Amiri"
    assert cap.element.rPr.find(qn("w:szCs")) is not None


def _raw_percent_line(positions, text):
    chars = [{"c": char, "bbox": (x, 0.0, x + 5.0, 10.0)} for char, x in zip(text, positions)]
    return {"blocks": [{"lines": [{"spans": [{"chars": chars}]}]}]}


def test_visual_percent_checker_detects_wrong_side_and_allows_left():
    from dynamic_pdf.qa.percent_geometry import misplaced_arabic_percent
    # Arabic numeral at x=10..15; sign at x=15..20 is WRONG.
    wrong = _raw_percent_line([10, 15], "٤٪")
    assert len(list(misplaced_arabic_percent(wrong))) == 1
    # Sign at x=5..10 is to the LEFT and is correct.
    right = _raw_percent_line([10, 5], "٤٪")
    assert not list(misplaced_arabic_percent(right))
    # A normal English-only 4% must not be treated as Arabic.
    english = _raw_percent_line([10, 15], "4%")
    assert not list(misplaced_arabic_percent(english))


def test_visual_percent_checker_keeps_ascii_percent_in_arabic_context():
    from dynamic_pdf.qa.percent_geometry import misplaced_arabic_percent
    wrong = _raw_percent_line([10, 15], "٤%")
    assert len(list(misplaced_arabic_percent(wrong))) == 1


def test_pdf_body_style_justifies_without_forcing_final_line():
    from dynamic_pdf.layout.factory import _body_style
    theme = Theme(name="test")
    style = _body_style(theme)
    assert style.alignment == 4  # ReportLab TA_JUSTIFY
