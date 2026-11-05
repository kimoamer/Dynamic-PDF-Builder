"""M7.10: the composition blocks, the engine's use of them, and the fixes they rest on."""
import io
import zipfile

import pymupdf
import pytest
from docx import Document
from PIL import Image, ImageDraw

from dynamic_pdf import DocumentBuilder
from dynamic_pdf.fonts.manager import covering_face, covers
from dynamic_pdf.design import archetypes as A
from dynamic_pdf.design.art_direction import _ledger, _pair
from dynamic_pdf.design.focal import focal_point
from dynamic_pdf.fonts import font_catalog, list_font_families
from dynamic_pdf.schema.blocks import (ChartBlock, FigureCell, FigureMatrixBlock, ImageBlock, ImageTextPanelBlock,
                                       PairedRow, PairedRowColumnsBlock, ParagraphBlock, TableBlock)
from dynamic_pdf.schema.theme import Theme

EN = "The north quay reopened in March after two years of work on the flood gates."
AR = "أُعيد افتتاح الرصيف الشمالي في مارس بعد عامين من العمل على بوابات الفيضان."


@pytest.fixture
def photo(tmp_path):
    p = tmp_path / "photo.png"
    img = Image.new("RGB", (800, 500), (40, 70, 100))
    ImageDraw.Draw(img).ellipse((600, 80, 700, 180), fill=(250, 220, 150))
    img.save(p)
    return str(p)


def pdf_text(data: bytes) -> str:
    with pymupdf.open(stream=data, filetype="pdf") as d:
        return " ".join(p.get_text() for p in d)


def docx_text(data: bytes) -> str:
    doc = Document(io.BytesIO(data))
    cells = [p.text for t in doc.tables for r in t.rows for c in r.cells for p in c.paragraphs]
    return " ".join(cells + [p.text for p in doc.paragraphs])


def charts(n=3):
    return [{"title": f"Series {i}", "chart": {"chart_type": "bar", "data": {"a": 1 + i, "b": 2}, "legend": False}}
            for i in range(n)]


@pytest.mark.parametrize("layout", ["split", "overlay"])
def test_panel_keeps_live_text_in_both_formats(photo, layout):
    b = DocumentBuilder().image_text_panel({"src": photo, "alt_text": "quay", "caption": "North quay"}, [EN],
                                           title="A quay rebuilt", layout=layout)
    assert "A quay rebuilt" in pdf_text(b.render())
    words = docx_text(b.render_docx())
    assert "A quay rebuilt" in words and "two years of work" in words and "North quay" in words


def test_a_panel_too_long_for_the_page_becomes_plain_blocks_with_every_word(photo):
    text = " ".join(["word"] * 900) + " lastword"
    b = DocumentBuilder().image_text_panel({"src": photo, "alt_text": "x"}, [text], title="Long")
    assert "lastword" in pdf_text(b.render())


def test_panel_moves_to_the_reading_start_in_arabic(photo):
    theme = Theme(name="t")
    en = ImageTextPanelBlock(image=ImageBlock(src=photo), paragraphs=[EN])
    ar = ImageTextPanelBlock(image=ImageBlock(src=photo), paragraphs=[AR])
    assert A.plan_panel(en, theme, 400).panel_x == 0
    assert A.plan_panel(ar, theme, 400).panel_x > 0


def test_panel_grows_to_hold_its_text(photo):
    plan = A.plan_panel(ImageTextPanelBlock(image=ImageBlock(src=photo), paragraphs=[EN]), Theme(name="t"), 400)
    plan.settle(500)
    assert plan.height >= 500 + 2 * plan.pad


def test_word_picture_line_is_not_exact_so_the_panel_image_is_not_cropped(photo):
    data = DocumentBuilder().image_text_panel({"src": photo, "alt_text": "x"}, [EN]).render_docx()
    doc = Document(io.BytesIO(data))
    holder = next(p for t in doc.tables for c in t.rows[0].cells for p in c.paragraphs if p._p.xpath(".//w:drawing"))
    assert holder.paragraph_format.line_spacing_rule is None or holder.paragraph_format.line_spacing == 1.0


def test_matrix_runs_from_the_right_in_arabic():
    cells = [FigureCell(title="الأول", value="1"), FigureCell(title="الثاني", value="2")]
    plan = A.plan_matrix(FigureMatrixBlock(figures=cells, columns=2), 400)
    assert [c.title for c in plan.rows[0]] == ["الثاني", "الأول"]


def test_matrix_drops_the_legend_of_a_single_series():
    cell = FigureCell(chart=ChartBlock(chart_type="bar", data={"a": 1, "b": 2}))
    assert A.cell_chart(cell, 200, 100).legend is False


def test_a_figure_takes_the_edge_of_its_cell_words():
    assert A.cell_align(FigureCell(title="الأول", value="٩٢٪", label="رضا العملاء")) == 2


def test_matrix_renders_every_title_in_both_formats():
    b = DocumentBuilder().figure_matrix(charts(3) + [{"value": "92%", "label": "satisfied"}], title="Measures", columns=2)
    words = pdf_text(b.render())
    assert all(t in words for t in ("Measures", "Series 0", "Series 2", "92%", "satisfied"))
    words = docx_text(b.render_docx())
    assert all(t in words for t in ("Measures", "Series 0", "Series 2", "92%", "satisfied"))


def test_paired_rows_put_arabic_on_the_right_whichever_comes_first():
    rows = [PairedRow(first=AR, second=EN)]
    assert A.paired_sides(AR, EN, rows) == (EN, AR)
    assert A.paired_sides(EN, AR, [PairedRow(first=EN, second=AR)]) == (EN, AR)


def test_paired_rows_keep_both_languages_and_repeat_the_header_in_word():
    rows = [{"first": EN, "second": AR}] * 3
    b = DocumentBuilder().paired_row_columns(rows, header_first="English", header_second="العربية")
    assert "flood gates" in pdf_text(b.render())
    data = b.render_docx()
    table = Document(io.BytesIO(data)).tables[0]
    assert len(table.rows) == 4
    assert table.rows[0]._tr.xpath(".//w:tblHeader")
    assert table.rows[1].cells[2].paragraphs[-1].text == AR


def test_paired_rows_split_across_pages_without_losing_text():
    long = " ".join(["line"] * 900)
    b = DocumentBuilder().paired_row_columns([{"first": long + " endmark", "second": AR}])
    assert "endmark" in pdf_text(b.render())


@pytest.mark.parametrize("block", [
    PairedRowColumnsBlock(rows=[PairedRow(first=EN, second=AR, heading=True)]),
    FigureMatrixBlock(figures=[FigureCell(title="t", value="1", label="l", note="n")], title="m", note="s"),
])
def test_lowering_keeps_every_word(block):
    flat = " ".join(str(getattr(b, "text", "")) for b in A.lower(block))
    if block.type == "paired_row_columns":
        assert EN in flat and AR in flat
    else:
        assert all(w in flat.split() for w in ("m", "t", "1", "l", "n", "s"))


def test_ledger_needs_labels_in_two_languages_and_only_figures_between():
    good = TableBlock(headers=["Item", "2025", "البند"], rows=[["Rent", "5", "إيجار"], ["Fees", "(7)", "رسوم"]], caption="Income")
    made = _ledger(good)
    assert made.periods == ["2025"] and made.sections[0].rows[1].label_alt == "رسوم"
    assert _ledger(good.model_copy(update={"headers": ["Item", "2025", "Label"]})) is None
    assert _ledger(good.model_copy(update={"rows": [["Rent", "high", "إيجار"], ["Fees", "7", "رسوم"]]})) is None
    assert _ledger(good.model_copy(update={"caption": None})) is None


def test_ledger_marks_the_footer_as_total():
    t = TableBlock(headers=["Item", "2025", "البند"], rows=[["Rent", "5", "إيجار"], ["Fees", "7", "رسوم"]],
                   caption="Income", footer_row=["Total", "12", "الإجمالي"])
    assert _ledger(t).sections[0].rows[-1].total


def test_pair_needs_one_paragraph_in_each_language():
    assert _pair(ParagraphBlock(text=EN), ParagraphBlock(text=AR))
    assert not _pair(ParagraphBlock(text=EN), ParagraphBlock(text=EN))
    assert not _pair(ParagraphBlock(text="**" + EN), ParagraphBlock(text=AR))


def test_engine_uses_the_compositions_without_touching_content(tmp_path):
    from benchmarks.m79.corpus import DOCUMENTS, make_assets
    assets = make_assets(str(tmp_path))
    b, brand = DOCUMENTS["bilingual_ports_review"](assets)
    made = b.design_variants(n=2, brand=brand, grammar=True)
    assert made.variants
    kinds = set()
    for v in made.variants:
        kinds |= {x.type for x in v.document.blocks}
        assert not v.report.hard_failures
    assert {"paired_row_columns", "parallel_ledger", "figure_matrix"} <= kinds


def test_without_a_grammar_nothing_is_composed(tmp_path):
    from benchmarks.m79.corpus import DOCUMENTS, make_assets
    b, brand = DOCUMENTS["transit_data_story"](make_assets(str(tmp_path)))
    made = b.design_variants(n=1, brand=brand)
    assert not {x.type for v in made.variants for x in v.document.blocks} & set(A.COMPOSITION_TYPES)


# ─── the fixes the compositions rest on ───

def test_a_heading_after_a_float_starts_below_it_in_word(photo):
    from dynamic_pdf.schema.media import MediaPlacement
    b = DocumentBuilder()
    b.image(photo, alt_text="x", placement=MediaPlacement(mode="floating", horizontal="right", width_ratio=0.4))
    b.paragraph(" ".join([EN] * 8))
    b.heading("Next section", 1)
    doc = Document(io.BytesIO(b.render_docx()))
    paras = doc.paragraphs
    at = next(i for i, p in enumerate(paras) if p.text == "Next section")
    assert any(br.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}clear") == "all"
               for p in paras[max(0, at - 2):at] for br in p._p.xpath(".//w:br"))


def test_focal_point_finds_the_bright_subject(photo):
    x, y = focal_point(photo)
    assert x > 0.6 and y < 0.5


def test_focal_point_of_a_flat_picture_is_the_centre(tmp_path):
    p = tmp_path / "flat.png"
    Image.new("RGB", (200, 200), (90, 90, 90)).save(p)
    assert focal_point(str(p)) == (0.5, 0.5)


def test_at_least_twenty_families_for_each_script():
    assert len(list_font_families("arabic")) >= 20
    assert len(list_font_families("latin")) >= 20


def test_every_bundled_family_records_its_licence():
    for name, row in font_catalog().items():
        assert row["licence"] == "OFL-1.1" or "OFL" in row["licence"], name
        assert row["files"], name


def test_a_chosen_arabic_family_reaches_the_pdf():
    b = DocumentBuilder().fonts(arabic="Cairo")
    b.paragraph(AR)
    with pymupdf.open(stream=b.render(), filetype="pdf") as d:
        assert any("Cairo" in f[3] for f in d[0].get_fonts())


def test_word_embeds_a_chosen_family_and_marks_it():
    b = DocumentBuilder().fonts(arabic="Cairo")
    b.paragraph(AR)
    with zipfile.ZipFile(io.BytesIO(b.render_docx())) as z:
        names = z.namelist()
        assert any(n.endswith(".odttf") for n in names)
        assert b"embedTrueTypeFonts" in z.read("word/settings.xml")
        assert b"Cairo" in z.read("word/fontTable.xml")


def test_default_word_output_embeds_nothing():
    b = DocumentBuilder()
    b.paragraph(EN)
    with zipfile.ZipFile(io.BytesIO(b.render_docx())) as z:
        assert not any(n.endswith(".odttf") for n in z.namelist())


def ledger_doc(**kw):
    rows = [{"label": "Rent", "label_alt": "إيجار", "values": ["5", "4"]},
            {"label": "Total", "label_alt": "الإجمالي", "values": ["9", "8"], "total": True}]
    return DocumentBuilder().parallel_ledger(periods=["2025", "2024"], label_header="Item", label_header_alt="البند",
                                             sections=[{"title": "Income", "rows": rows}], **kw)


def test_a_single_ledger_title_stands_above_the_column_heads():
    words = pymupdf.open(stream=ledger_doc(title_first=True).render(), filetype="pdf")[0].get_text("words")
    y = {w[4]: w[1] for w in words}
    assert y["Income"] < y["Item"] < y["Rent"]
    table = Document(io.BytesIO(ledger_doc(title_first=True).render_docx())).tables[0]
    assert table.rows[0].cells[0].text == "Income" and table.rows[1].cells[0].text == "Item"
    assert table.rows[2].cells[0].text == "Rent"
    assert all(r._tr.xpath("./w:trPr/w:tblHeader") for r in table.rows[:2])


def test_a_ledger_keeps_its_section_order_unless_asked():
    y = {w[4]: w[1] for w in pymupdf.open(stream=ledger_doc().render(), filetype="pdf")[0].get_text("words")}
    assert y["Item"] < y["Income"]


def test_a_total_stays_with_the_row_above_it_in_word():
    table = Document(io.BytesIO(ledger_doc().render_docx())).tables[0]
    assert table.rows[2].cells[0].paragraphs[0].paragraph_format.keep_with_next


def test_a_face_that_lacks_a_character_gives_way_to_one_of_its_kind():
    assert not covers("Tajawal", "٫") and covers("Tajawal", "ب")
    assert covering_face("Tajawal", "ب") == "Tajawal"
    swapped = covering_face("Tajawal", "٫٬٪")
    assert swapped != "Tajawal" and covers(swapped, "٫٬٪")
    assert covering_face("Amiri", "٫") == "Amiri"


def test_no_arabic_face_of_a_direction_draws_an_empty_box():
    b = DocumentBuilder().meta(title="تقرير").direction("rtl")
    b.heading("الأداء", 1).paragraph("بلغ العائد ١٢٫٤٨٪ من ٣٬٥٠٠ م³ هذا العام، وهو أعلى من العام الماضي بكثير.")
    for v in b.design_variants(n=3).variants:
        pdf = pymupdf.open(stream=v.pdf, filetype="pdf")
        assert not any("٫" in s["text"] and s["font"].endswith("Tajawal") for p in pdf for bl in p.get_text("dict")["blocks"]
                       for ln in bl.get("lines", []) for s in ln["spans"])


def test_charts_in_a_matrix_take_the_design_colours():
    b = DocumentBuilder().meta(title="Figures")
    b.heading("Trips", 1).paragraph("Trips rose on every mode this year, and most of all on the trams.")
    for name in ("Tram", "Bus"):
        b.chart("bar", {"2024": 4, "2025": 5}, title=name, legend=False)
    v = b.design_variants(n=1, grammar=True, families=["financial_data"]).variants[0]
    cells = [c for x in v.document.blocks if x.type == "figure_matrix" for c in x.figures]
    assert cells and all(c.chart.colors and len(set(c.chart.colors)) == 2 for c in cells)
