"""Defects seen on rendered pages in the first real-API review, each checked on the page."""
import io
import zipfile

import pymupdf

from dynamic_pdf import DocumentBuilder
from dynamic_pdf.design.art_direction import direct
from dynamic_pdf.design.directions import DIRECTIONS

LONG = ("The migration keeps every report running while the warehouse moves, so analysts see no gap "
        "in their numbers at any point of the programme. ")


def _lines(pdf):
    page = pymupdf.open(stream=pdf, filetype="pdf")[0]
    out = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            spans = [s for s in line["spans"] if s["text"].strip()]
            if spans:
                out.append(("".join(s["text"] for s in spans).strip(), spans[0]["size"], line["bbox"]))
    return page, out


def test_a_table_stays_inside_the_text_column():
    # tables were sized to the frame, not the text inside its padding, and ran 11 pt past it
    b = (DocumentBuilder().meta(title="Proposal").heading("Deliverables").paragraph(LONG)
         .table(["Deliverable", "Due"], [["Assessment report", "Week 3"], ["Migrated pipelines", "Week 12"]]))
    from dynamic_pdf.themes import get_theme
    v = b.design_variants(families=["editorial_modern"]).variants[0]
    for pdf, theme in ((b.render(), get_theme("claude")), (v.pdf, v.theme)):
        page, _ = _lines(pdf)
        column_right = page.rect.width - theme.spacing.page_margin_right - 6     # inside the frame padding
        rules = [d["rect"] for d in page.get_drawings() if d["rect"].height < 3 and d["rect"].width > 100]
        assert rules and max(r.x1 for r in rules) <= column_right + 0.5


def test_a_section_of_one_paragraph_gets_no_lead():
    b = DocumentBuilder().meta(title="Proposal")
    for t in ("Approach", "Timeline", "Investment"):
        b.heading(t).paragraph(LONG)
    made = direct(b.semantic(), DIRECTIONS["editorial_modern"])
    assert not any((x.hints or {}).get("lead") for x in made.document.blocks if x.type == "paragraph")


def test_a_lead_sets_ragged_so_it_neither_stretches_nor_hyphenates():
    b = DocumentBuilder().meta(title="Q3 Performance Review").heading("Executive Summary", numbered=True).paragraph(
        "Revenue grew **18%** year over year to $42.1M, driven by enterprise renewals. See the dashboard for detail.")
    b.paragraph(LONG)
    made = direct(b.semantic(), DIRECTIONS["corporate_conservative"])
    from dynamic_pdf.layout.engine import LayoutEngine
    buf = io.BytesIO()
    LayoutEngine(made.document, theme=made.theme).render(buf)
    _, lines = _lines(buf.getvalue())
    assert not any(t.endswith("-") for t, _, _ in lines)


def test_nested_list_items_keep_the_list_size_and_spacing():
    b = DocumentBuilder().bullet_list([{"text": "Renewals reached 94%", "children": ["Mid-market held at 88%"]},
                                       "Churn fell to 2.1%", "Margin improved to 71%"])
    _, lines = _lines(b.render())
    rows = [(t, size, bb[1]) for t, size, bb in lines if t not in ("•", "–") and not t.startswith("Page ")]
    assert len({round(size, 1) for _, size, _ in rows}) == 1
    gaps = [round(b2 - b1) for (_, _, b1), (_, _, b2) in zip(rows, rows[1:])]
    assert max(gaps) - min(gaps) <= 1, gaps


def _arabic_list():
    return (DocumentBuilder().direction("rtl").meta(title="التقرير", language="ar")
            .paragraph("نمت الإيرادات بنسبة ١٨٪ خلال العام.")
            .numbered_list(["توسيع فريق المبيعات", "الاستثمار في الأتمتة"])
            .bullet_list([{"text": "ارتفاع رضا العملاء", "children": ["خاصة في قطاع المؤسسات"]}]))


def test_arabic_list_numbers_follow_the_documents_digits():
    pdf = _arabic_list().render()
    text = pymupdf.open(stream=pdf, filetype="pdf")[0].get_text()
    assert "١" in text and "٢" in text and "\n1\n" not in text
    with zipfile.ZipFile(io.BytesIO(_arabic_list().render_docx())) as z:
        assert 'w:val="hindiNumbers"' in z.read("word/numbering.xml").decode()


def test_an_arabic_nested_marker_moves_in_with_its_text():
    # the dash stayed at the list's outer edge while only its words moved in
    _, lines = _lines(_arabic_list().render())
    child = next((t, bb) for t, _, bb in lines if "خاصة" in t)
    parent = next((t, bb) for t, _, bb in lines if "ارتفاع" in t)
    assert "–" in child[0]                          # extracted on the same line: beside its words
    assert child[1][2] < parent[1][2] - 10          # and further in than the parent's marker


def test_arabic_heading_numbers_follow_the_documents_digits():
    b = (DocumentBuilder().direction("rtl").meta(title="التقرير", language="ar").section_numbering(True)
         .heading("الملخص التنفيذي").paragraph("نمت الإيرادات بنسبة ١٨٪ خلال العام."))
    text = pymupdf.open(stream=b.render(), filetype="pdf")[0].get_text()
    line = next(ln for ln in text.splitlines() if "الملخص" in ln)
    assert "١" in line and "1" not in line
    from docx import Document as Word
    heads = [p.text for p in Word(io.BytesIO(b.render_docx())).paragraphs if p.style.name.startswith("Heading")]
    assert heads and heads[0].startswith("١")


def test_english_headings_in_a_bilingual_document_keep_western_numbers():
    b = (DocumentBuilder().meta(title="Board update").section_numbering(True).heading("Overview")
         .paragraph("الميزانية ٢٠٢٧ بقيمة ١٢٫٥ مليون."))
    from docx import Document as Word
    heads = [p.text for p in Word(io.BytesIO(b.render_docx())).paragraphs if p.style.name.startswith("Heading")]
    assert heads[0].startswith("1")


def test_a_drop_cap_only_where_text_wraps_around_it():
    # with no lead to stop it, a one-line paragraph opened on a lone giant capital
    def caps(paragraph):
        b = DocumentBuilder().meta(title="Proposal").heading("Approach").paragraph(paragraph)
        b.heading("Timeline").paragraph("Phase one starts in January.")
        pdf = b.design_variants(families=["editorial_modern"]).variants[0].pdf
        _, lines = _lines(pdf)
        return [t for t, size, _ in lines if size > 25 and len(t) == 1]
    assert caps("We will migrate the legacy warehouse in three phases with no downtime.") == []
    assert caps(LONG * 4)                      # a long opening paragraph keeps its drop cap
