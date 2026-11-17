"""The three opt-in layout archetypes, in PDF and editable DOCX, and the correctness fixes made
for them. Every document here is fictional; nothing is derived from a reference PDF."""
import importlib.util
import io
import os
import re
import sys
import warnings
import zipfile

import pytest

pymupdf = pytest.importorskip("pymupdf")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path[:0] = [ROOT, os.path.join(ROOT, "benchmarks", "m74"), os.path.join(ROOT, "benchmarks", "m75")]

from docx import Document  # noqa: E402
from docx.enum.text import WD_ALIGN_PARAGRAPH  # noqa: E402
from docx.oxml.ns import qn  # noqa: E402
from docx.shared import Pt  # noqa: E402
from examples import EXAMPLES  # noqa: E402

from dynamic_pdf import DocumentBuilder  # noqa: E402
from dynamic_pdf.design import archetypes as A  # noqa: E402
from dynamic_pdf.layout.factory import _reshape  # noqa: E402
from dynamic_pdf.qa import check_docx, check_pdf  # noqa: E402
from dynamic_pdf.qa.docx_checks import _text_margins  # noqa: E402
from dynamic_pdf.qa.pdf_checks import _separate_lines  # noqa: E402
from dynamic_pdf.qa.loop import qa_context  # noqa: E402
from dynamic_pdf.renderers import docx_fields as F  # noqa: E402
from dynamic_pdf.schema.blocks import (  # noqa: E402
    ParallelLedgerBlock, PerformancePageBlock, SectionOpenerBlock)
from dynamic_pdf.themes import get_theme  # noqa: E402

HARAKAT = re.compile("[ً-ْ]")
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
THEME = get_theme("claude")
PAGE_W, PAGE_H = 595.0, 842.0
LEDGER = [{"title": "Income", "rows": [{"label": "Dues", "values": ["1", "2"]}]}]


def comparison():
    """benchmarks/m75/run.py by path: benchmarks/m74 has a run.py too."""
    spec = importlib.util.spec_from_file_location("m75_run", os.path.join(ROOT, "benchmarks", "m75", "run.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def builder(rtl=False):
    b = DocumentBuilder()
    b.meta(title="Fictional", language="ar" if rtl else "en")
    return b


def diagnostics(b, code):
    return [d for d in b.last_render.diagnostics.items if d.code == code]


def pages(pdf):
    return [p.get_text() for p in pymupdf.open(stream=pdf, filetype="pdf")]


# ─── every example, both formats ───

@pytest.fixture(scope="module", params=list(EXAMPLES))
def rendered(request):
    warnings.simplefilter("ignore")
    b = EXAMPLES[request.param][1]()
    return request.param, b, b.render(), b.render_docx()


def test_examples_pass_pdf_qa(rendered):
    _, b, pdf, _ = rendered
    doc, theme = b._prepared()
    sp = theme.spacing
    report = check_pdf(pdf, margins={"left": sp.page_margin_left, "right": sp.page_margin_right},
                       **qa_context(doc, theme))
    assert [f.message for f in report.errors] == []


def test_examples_are_valid_editable_docx(rendered):
    from dynamic_pdf.core.normalize import normalize
    _, b, _, docx = rendered
    doc, _ = b._prepared()
    report = check_docx(docx, heading_texts=[o.text for o in normalize(doc).outline], visual=False)
    assert [f.message for f in report.errors] == []
    assert not [f for f in report.findings if f.code == "missing_alt_text"]
    assert not Document(io.BytesIO(docx)).inline_shapes, "archetypes must stay native text, not pictures"


def test_examples_fit_without_a_fallback(rendered):
    _, b, _, _ = rendered
    assert not diagnostics(b, "archetype_fallback")


def test_diacritics_survive_in_both_formats(rendered):
    docx_all_text = comparison().docx_all_text
    _, b, pdf, docx = rendered
    source = HARAKAT.findall(str(b.build().model_dump()))
    assert len(HARAKAT.findall("".join(pages(pdf)))) >= len(source)
    assert len(HARAKAT.findall(docx_all_text(docx))) >= len(source)


def test_comparison_gate_catches_defects():
    failures = comparison().failures
    good = {"name": "x", "variant": "after", "pdf_qa": {"errors": []}, "docx_qa": {"errors": []},
            "missing_words": {"pdf": [], "docx": []}, "harakat": {"source": 3, "pdf": 3, "docx": 3}}
    assert failures([good]) == []
    assert failures([{**good, "harakat": {"source": 3, "pdf": 2, "docx": 3}}])
    assert failures([{**good, "missing_words": {"pdf": ["a"], "docx": []}}])
    assert failures([{**good, "docx_qa": {"errors": ["overflow"]}}])
    assert failures([{**good, "variant": "before", "docx_qa": {"errors": ["overflow"]}}]) == []


# ─── section opener ───

def test_opener_plan_uses_proportions_of_the_page():
    plan = A.plan_opener(SectionOpenerBlock(title="Operations"), THEME, PAGE_W, PAGE_H)
    assert plan.ok and plan.strip == pytest.approx(PAGE_W * A.STRIP_RATIO)
    narrow = A.plan_opener(SectionOpenerBlock(title="Operations"), THEME, 420.0, PAGE_H)
    assert narrow.strip == pytest.approx(420.0 * A.STRIP_RATIO)


def test_opener_strip_follows_the_reading_edge():
    ltr = A.plan_opener(SectionOpenerBlock(title="Operations"), THEME, PAGE_W, PAGE_H)
    rtl = A.plan_opener(SectionOpenerBlock(title="العمليات"), THEME, PAGE_W, PAGE_H)
    assert ltr.field_x > ltr.strip
    assert rtl.rtl and rtl.field_x + rtl.field_w < PAGE_W - rtl.strip


def test_opener_page_has_no_blank_page_before_it_and_no_running_header():
    b = builder()
    b.section_opener("Chapter", chapters=["One", "Two"], current=0)
    b.heading("Next", level=2).paragraph("Body text.")
    text = pages(b.render())
    assert "Chapter" in text[0] and "Page 1" not in text[0]
    assert "Page 2" in text[1]


def test_opener_after_content_starts_a_new_page():
    b = builder()
    b.paragraph("Before.")
    b.section_opener("Chapter")
    text = pages(b.render())
    assert len(text) == 2 and "Chapter" in text[1]


def test_opener_with_a_title_that_cannot_fit_falls_back_with_nothing_lost():
    title = "A very long chapter title that keeps going " * 12
    b = builder()
    b.section_opener(title, standfirst="Standfirst text.", points=["First point"])
    joined = " ".join("".join(pages(b.render())).split())
    assert diagnostics(b, "archetype_fallback")
    assert "Standfirst text." in joined and "First point" in joined
    docx = b.render_docx()
    assert "First point" in "\n".join(p.text for p in Document(io.BytesIO(docx)).paragraphs)


def test_opener_spills_extra_points_after_the_page():
    points = [f"Point number {i}" for i in range(A.MAX_POINTS + 3)]
    b = builder()
    b.section_opener("Chapter", points=points)
    text = pages(b.render())
    assert len(text) == 2
    assert all(p in "".join(text) for p in points)
    assert diagnostics(b, "archetype_fit")


def test_opener_appears_in_the_outline_and_as_a_word_heading():
    b = builder()
    b.section_opener("Chapter title", label="03")
    b.heading("Second", level=1)
    pdf = b.render()
    assert [t[1] for t in pymupdf.open(stream=pdf, filetype="pdf").get_toc()][:2] == ["Chapter title", "Second"]
    d = Document(io.BytesIO(b.render_docx()))
    head = [p for p in d.paragraphs if p.style.name == "Heading 1"]
    assert head[0].text == "Chapter title"


def test_opener_strip_is_page_anchored_editable_text():
    b = builder()
    b.section_opener("Chapter", chapters=["One", "Two", "Three"], current=1)
    b.paragraph("After.")
    d = Document(io.BytesIO(b.render_docx()))
    body = d.element.body
    boxes = list(body.iter(W + "txbxContent"))
    assert len(boxes) == 3
    assert ["".join(t.text for t in box.iter(W + "t")) for box in boxes] == ["01One", "02Two", "03Three"]
    wp = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"
    assert {e.get("relativeFrom") for e in body.iter(wp + "positionV")} == {"page"}
    ids = [e.get("id") for e in body.iter(wp + "docPr")]
    assert len(ids) == len(set(ids))


def test_opener_section_keeps_later_headers_and_margins():
    b = builder()
    b.paragraph("Before.")
    b.section_opener("Chapter")
    b.paragraph("After.")
    d = Document(io.BytesIO(b.render_docx()))
    first, opener, last = d.sections[0], d.sections[1], d.sections[-1]
    assert opener.different_first_page_header_footer and not last.different_first_page_header_footer
    assert opener.left_margin > first.left_margin
    assert last.left_margin == first.left_margin and last.right_margin == first.right_margin
    assert "Page" in "".join(p.text for p in last.footer.paragraphs)


def test_docx_opener_after_a_page_break_leaves_no_blank_page_marker():
    b = builder()
    b.paragraph("Before.")
    b.section_opener("Chapter")
    d = Document(io.BytesIO(b.render_docx()))
    host = d.paragraphs[0]._p
    assert host.pPr is not None and host.pPr.find(qn("w:sectPr")) is not None
    assert d.paragraphs[0].text == "Before."


# ─── performance page ───

HERO = {"value": "18.4m", "label": "tonnes"}
TILES = [{"value": "9", "label": "berths"}, {"value": "12", "label": "cranes"}]


def test_performance_hero_shrinks_for_a_long_value():
    short = A.plan_performance(PerformancePageBlock(title="T", hero=HERO, tiles=TILES), THEME, 480, 700)
    long = A.plan_performance(PerformancePageBlock(title="T", hero={"value": "1,234,567,890.55", "label": "t"},
                                                   tiles=TILES), THEME, 480, 700)
    assert short.ok and long.ok and long.hero_size < short.hero_size


def test_performance_tile_columns_follow_the_count():
    tile = {"value": "9", "label": "x"}
    assert A.plan_performance(PerformancePageBlock(title="T", hero=HERO, tiles=[tile] * 3), THEME, 480, 700).tile_cols == 3
    many = A.plan_performance(PerformancePageBlock(title="T", hero=HERO, tiles=[tile] * 8), THEME, 480, 700)
    assert many.tile_cols * many.tile_rows >= 8


def test_performance_with_too_many_tiles_falls_back_with_nothing_lost():
    tiles = [{"value": f"V{i}", "label": f"label {i}"} for i in range(A.MAX_TILES + 2)]
    b = builder()
    b.performance_page("Results", HERO, tiles=tiles)
    text = "".join(pages(b.render()))
    assert diagnostics(b, "archetype_fallback")
    assert all(t["value"] in text for t in tiles)


def test_performance_extra_highlights_spill_as_a_plain_list():
    items = [f"Long highlight number {i} " + "word " * 18 for i in range(40)]
    b = builder()
    b.performance_page("Results", HERO, highlights=items)
    text = " ".join("".join(pages(b.render())).split())
    assert all(f"highlight number {i} " in text for i in range(40))


def test_performance_trend_with_negative_values_keeps_a_common_baseline():
    zero, scale = A.trend_span([-14.0, -6.0, 3.0, 11.0])
    assert 0 < zero < 1
    assert zero + (-14.0) * scale >= -1e-9 and zero + 11.0 * scale <= 1 + 1e-9


def test_performance_bars_are_native_paragraphs_in_docx():
    b = builder()
    b.performance_page("Results", HERO, tiles=TILES,
                       trends=[{"label": "Rev", "periods": ["a", "b"], "values": [1, 2]}])
    d = Document(io.BytesIO(b.render_docx()))
    assert not d.inline_shapes
    assert any(p.paragraph_format.left_indent is not None or p._p.pPr is not None and
               p._p.pPr.find(qn("w:shd")) is not None for t in d.tables for c in t._cells for p in c.paragraphs)


def test_performance_title_is_a_body_heading_for_word_navigation():
    b = builder()
    b.performance_page("Results", HERO, tiles=TILES)
    assert [p.text for p in Document(io.BytesIO(b.render_docx())).paragraphs
            if p.style.name == "Heading 1"] == ["Results"]


# ─── parallel ledger ───

def test_ledger_columns_are_never_narrower_than_their_figures():
    rows = [{"label": "Total expenditure", "label_alt": "إجمالي المصروفات", "total": True,
             "values": ["(113,070)", "(109,600)", "(106,000)"]}]
    b = ParallelLedgerBlock(periods=["2026", "2025", "2024"], sections=[{"title": "S", "rows": rows}])
    width = 450.0
    plan = A.plan_ledger(b, THEME, width)
    assert plan.ok and plan.bilingual
    for i, value in enumerate(rows[0]["values"]):
        size = plan.emphasis_size if i == b.emphasis else THEME.typography.base_size
        assert plan.value_w[i] * width >= A.text_width(THEME, value, size, True)
    assert sum(plan.value_w) + plan.label_w * 2 == pytest.approx(1.0, abs=0.01)


def test_ledger_figures_stay_on_one_line():
    b = EXAMPLES["ledger_bilingual"][1]()
    text = pages(b.render())[0]
    assert "(109,600)" in text and "(106,000)" in text


def test_ledger_with_ragged_rows_falls_back():
    b = builder()
    b.parallel_ledger(["2026", "2025"], [{"title": "S", "rows": [{"label": "Dues", "values": ["1"]}]}])
    assert "Dues" in "".join(pages(b.render()))
    assert diagnostics(b, "archetype_fallback")


def test_ledger_with_values_wider_than_the_page_falls_back():
    periods = [str(2000 + i) for i in range(6)]
    b = ParallelLedgerBlock(periods=periods, sections=[{"title": "S", "rows": [
        {"label": "Dues", "values": ["1,234,567,890.00"] * len(periods)}]}])
    assert not A.plan_ledger(b, THEME, 450.0).ok


def test_ledger_docx_repeats_its_header_and_keeps_rows_whole():
    b = EXAMPLES["ledger_en"][1]()
    t = Document(io.BytesIO(b.render_docx())).tables[0]
    assert t.rows[0]._tr.trPr.find(qn("w:tblHeader")) is not None
    assert all(r._tr.trPr.find(qn("w:cantSplit")) is not None for r in t.rows if r._tr.trPr is not None)


def test_ledger_arabic_table_is_a_bidi_table_in_logical_order():
    d = Document(io.BytesIO(EXAMPLES["ledger_ar"][1]().render_docx()))
    t = d.tables[0]
    assert t._tbl.tblPr.find(qn("w:bidiVisual")) is not None
    assert t.rows[0].cells[1].text == "٢٠٢٦"


# ─── lowering, the fallback and the 'before' ───

def test_lower_keeps_every_figure_and_label():
    from dynamic_pdf.core.normalize import block_text
    b = PerformancePageBlock(title="T", hero={"value": "9", "label": "h", "note": "hero note"},
                             tiles=[{"value": "8", "label": "t"}], highlights=["win"],
                             trends=[{"label": "Rev", "periods": ["a"], "values": [1], "display": ["1.0"]}])
    text = " ".join(t for block in A.lower(b) for t in block_text(block))
    for word in ("hero note", "win", "Rev", "1.0"):
        assert word in text


def test_lowered_does_not_open_a_document_with_a_page_break():
    b = builder()
    b.section_opener("First")
    b.section_opener("Second")
    blocks = A.lowered(b._blocks)
    assert blocks[0].type == "heading"
    assert [x.type for x in blocks].count("page_break") == 1


def test_design_and_compose_accept_archetypes():
    b = builder().section_opener("Chapter").paragraph("Body text after the opener.")
    b.design()
    assert "Chapter" in "".join(pages(b.render()))
    assert b.render_docx()


# ─── default output ───

def test_documents_without_archetypes_keep_the_plain_page_callback():
    b = builder().paragraph("Plain.")
    assert not any(x.type in A.ARCHETYPE_TYPES for x in b.build().blocks)
    assert "Plain." in pages(b.render())[0]


def test_runtime_package_has_no_inference_dependency():
    root = os.path.join(ROOT, "dynamic_pdf")
    banned = re.compile(r"^\s*(?:import|from)\s+(torch|tensorflow|onnxruntime|transformers|openai|anthropic)\b", re.M)
    for folder, _, files in os.walk(root):
        if os.path.relpath(folder, root).split(os.sep)[0] == "ai":
            continue        # the opt-in ai extra; test_m13_ai proves nothing else imports it
        for name in files:
            if name.endswith(".py"):
                with open(os.path.join(folder, name), encoding="utf-8") as f:
                    assert not banned.search(f.read()), name


# ─── correctness fixes ───

def _exhibit_doc(intro, exhibit="table"):
    b = builder()
    b.heading("Results", level=1)
    b.paragraph(intro)
    if exhibit == "table":
        b.table(["A", "B"], [["1", "2"]])
    else:
        b.paragraph("Next paragraph that is not an exhibit.")
    b.design()
    doc, _ = b._prepared()
    return doc


def test_page_fill_counts_charts_drawn_as_vectors():
    b = builder()
    b.heading("Results", level=1).paragraph("Figure 1 shows the trend.")
    b.chart("line", data={"Jul": 1, "Aug": 2, "Sep": 3}, title="Figure 1")
    assert check_pdf(b.render()).page_fill[0] > 0.3


def test_short_intro_stays_with_the_table_it_introduces():
    doc = _exhibit_doc("The table below shows the result.")
    assert next(x for x in doc.blocks if x.type == "paragraph").hints.get("keep_with_next")


def test_long_intro_and_plain_flow_keep_their_freedom():
    long_doc = _exhibit_doc("Word " * 200)
    assert not (next(x for x in long_doc.blocks if x.type == "paragraph").hints or {}).get("keep_with_next")
    flow = _exhibit_doc("Short intro here.", exhibit="paragraph")
    assert not (next(x for x in flow.blocks if x.type == "paragraph").hints or {}).get("keep_with_next")


def test_heading_is_not_stranded_from_its_table():
    b = builder()
    for _ in range(36):
        b.paragraph("Filler line of ordinary text to bring the page close to its end.")
    b.heading("Exhibit heading", level=2)
    b.paragraph("The table below shows the result.")
    b.table(["Region", "Value"], [[f"R{i}", str(i)] for i in range(14)])
    b.design()
    text = pages(b.render())
    page = next(i for i, t in enumerate(text) if "Exhibit heading" in t)
    assert "Region" in text[page]


def test_arabic_chart_title_is_shaped_and_set_in_an_arabic_face():
    from dynamic_pdf.renderers import chart
    from dynamic_pdf.schema.blocks import ChartBlock
    title = "الأحجام الفصلية"
    block = ChartBlock(chart_type="bar", title=title, data={"أ": 1, "ب": 2})
    fig = chart._RENDERERS["bar"](chart._sized(block), THEME)
    chart._shape_arabic(fig, block)
    text = fig.axes[0].get_title()
    if chart._shapes_itself():                   # Matplotlib joins and orders the letters: it gets them as written
        assert text == title
    else:
        assert text != title and any("ﭐ" <= c <= "ﻼ" for c in text)
    assert "Amiri" in fig.axes[0].title.get_fontfamily()


def test_latin_chart_is_untouched():
    from dynamic_pdf.renderers import chart
    from dynamic_pdf.schema.blocks import ChartBlock
    block = ChartBlock(chart_type="bar", title="Volume", data={"a": 1, "b": 2})
    fig = chart._RENDERERS["bar"](chart._sized(block), THEME)
    before = fig.axes[0].title.get_fontfamily()
    chart._shape_arabic(fig, block)
    assert fig.axes[0].get_title() == "Volume" and fig.axes[0].title.get_fontfamily() == before


def test_bidi_paragraph_justification_is_mirrored_for_word():
    d = Document()
    rtl = d.add_paragraph("نص")
    F.set_paragraph_bidi(rtl)
    rtl.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    ltr = d.add_paragraph("text")
    ltr.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    centred = d.add_paragraph("نص")
    F.set_paragraph_bidi(centred)
    centred.alignment = WD_ALIGN_PARAGRAPH.CENTER
    F.mirror_bidi_justification(d.element.body)
    assert rtl.alignment == WD_ALIGN_PARAGRAPH.LEFT      # 'left' is the start edge of a bidi paragraph
    assert ltr.alignment == WD_ALIGN_PARAGRAPH.RIGHT
    assert centred.alignment == WD_ALIGN_PARAGRAPH.CENTER


def test_rendered_arabic_docx_stores_start_edge_justification():
    b = builder(rtl=True)
    b.heading("عنوان عربي", level=1).paragraph("نص عربي قصير.")
    d = Document(io.BytesIO(b.render_docx()))
    head = next(p for p in d.paragraphs if p.style.name == "Heading 1")
    assert head._p.pPr.find(qn("w:bidi")) is not None
    assert head.alignment in (WD_ALIGN_PARAGRAPH.LEFT, None)


def test_arabic_sizes_and_weight_reach_complex_script_runs():
    d = Document()
    run = d.add_paragraph().add_run("٢٠٢٦")
    F.set_complex_script_format(run, 18, True)
    rpr = run._r.rPr
    assert rpr.find(qn("w:szCs")).get(qn("w:val")) == "36"
    assert rpr.find(qn("w:bCs")).get(qn("w:val")) == "1"


def test_complex_script_formatting_leaves_latin_runs_alone():
    b = builder()
    b.paragraph("Plain English.").heading("English heading", level=1)
    assert b"w:szCs" not in zipfile.ZipFile(io.BytesIO(b.render_docx())).read("word/document.xml")


def test_rtl_list_labels_stay_inside_the_margin():
    b = builder(rtl=True)
    b.numbered_list(["البند الأول", "البند الثاني"]).bullet_list(["نقطة"])
    d = Document(io.BytesIO(b.render_docx()))
    items = [p for p in d.paragraphs if p.style.name == "List Paragraph"]
    assert items[0].paragraph_format.left_indent > items[2].paragraph_format.left_indent > 0
    assert all(p.paragraph_format.first_line_indent < 0 for p in items)
    tags = [e.tag for e in items[0]._p.pPr]
    assert tags.index(qn("w:numPr")) < tags.index(qn("w:bidi")) < tags.index(qn("w:ind"))
    ltr = builder()
    ltr.bullet_list(["point"])
    item = next(p for p in Document(io.BytesIO(ltr.render_docx())).paragraphs if p.style.name == "List Paragraph")
    assert item.paragraph_format.left_indent is None


def test_arabic_subtitle_cancels_the_slant_and_tracking_of_its_style():
    b = builder(rtl=True)
    b.cover_page("التقرير", subtitle="شركة افتراضية")
    p = next(p for p in Document(io.BytesIO(b.render_docx())).paragraphs if p.style.name == "Subtitle")
    assert p.runs[0]._r.rPr.find(qn("w:spacing")).get(qn("w:val")) == "0"
    assert p.runs[0]._r.rPr.find(qn("w:iCs")).get(qn("w:val")) == "0"


def test_arabic_digits_in_an_archetype_carry_the_requested_size():
    d = Document(io.BytesIO(EXAMPLES["ledger_ar"][1]().render_docx()))
    sizes = {e.get(qn("w:val")) for e in d.tables[0].rows[2].cells[1]._tc.iter(qn("w:szCs"))}
    assert sizes and min(int(s) for s in sizes) > 2 * THEME.typography.base_size


def test_columns_at_the_end_of_a_document_leave_no_blank_page():
    from extra_docs import editorial_briefing
    b = editorial_briefing()
    b.design(recipe="editorial_executive", recipe_gate="preview")
    d = Document(io.BytesIO(b.render_docx()))
    last = d.paragraphs[-1]
    assert last.text == "" and last.paragraph_format.line_spacing == Pt(1)


def test_docx_margin_check_uses_the_outermost_text_edges():
    d = Document()
    first = d.sections[0]
    first.left_margin = first.right_margin = Pt(200)
    second = d.add_section()
    second.left_margin = second.right_margin = Pt(60)
    assert _text_margins(d) == {"left": 60, "right": 60}
    F.add_page_text_box(d.add_paragraph(), 50, 0, 0, 100, 800, "#112233", (24, 10, 8, 0))
    margins = _text_margins(d)
    assert margins["left"] == pytest.approx(24)


def test_docx_overlap_ignores_tall_font_boxes_but_not_real_collisions():
    tall_a, tall_b = ((0, 0, 100, 30), "a", 12.0), ((0, 18, 100, 48), "b", 12.0)
    drawn_over = ((0, 2, 100, 32), "c", 12.0)
    assert _separate_lines(tall_a, tall_b)
    assert not _separate_lines(tall_a, drawn_over)


def test_reshaper_cache_keeps_diacritics_and_is_pure():
    text = "نَقَلَت هيئةُ الميناء"
    assert _reshape(text) == _reshape(text)
    assert HARAKAT.findall(_reshape(text)) == HARAKAT.findall(text)
