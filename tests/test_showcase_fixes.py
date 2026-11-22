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


# What two real agents, given only the MCP server, ran into.

def test_an_arabic_percent_sign_sits_after_its_number_even_at_line_start():
    from dynamic_pdf.qa.percent_geometry import misplaced_arabic_percent
    md = "---\nlanguage: ar\n---\n\n- **40٪** دفعة مقدمة عند توقيع العقد.\n- 30% عند التسليم.\n"
    b = DocumentBuilder.from_markdown(md)
    pages = fitz.open(stream=b.render(), filetype="pdf")
    assert not [t for p in pages for _, t in misplaced_arabic_percent(p.get_text("rawdict"))]
    xml = zipfile.ZipFile(io.BytesIO(b.render_docx())).read("word/document.xml").decode()
    assert "40؜٪" in xml and "30؜%" in xml


def test_a_quote_is_a_document_type_and_chart_colours_stay_apart():
    from dynamic_pdf.design.profile import Profile, resolve_profile_name
    from dynamic_pdf.renderers.chart import _alike
    assert resolve_profile_name("quote") == resolve_profile_name("quotation") == Profile.INVOICE
    assert _alike((0.106, 0.212, 0.365), (0.118, 0.251, 0.686))        # navy and royal blue
    assert not _alike((0.106, 0.212, 0.365), (0.949, 0.663, 0.0))       # navy and gold


def test_the_mcp_review_sends_the_pages_and_render_checks_what_it_writes(tmp_path):
    pytest.importorskip("mcp")
    import asyncio
    from dynamic_pdf.ai import mcp_server as M
    server = M.build_server(str(tmp_path))
    got = asyncio.run(server.call_tool("review", {"markdown": "# Title\n\nText.\n"}))
    assert [c.type for c in got.content] == ["text", "image"] and not got.is_error
    assert M.render(markdown="# Title\n\nText.\n", filename="a.pdf", out_dir=str(tmp_path))["status"] == "ok"


def test_a_pdf_footnote_sits_at_the_foot_of_the_page_of_its_reference():
    para = "Revenue grew in every region this year, led by the north, while costs held below plan. " * 5
    md = (f"# Review\n\nMargin rose.[^margin]\n\n[^margin]: Margin is revenue less cost, over revenue.\n\n"
          + "\n\n".join([para] * 4) + "\n")
    page = fitz.open(stream=DocumentBuilder.from_markdown(md).render(), filetype="pdf")[0]
    lines = [(ln["bbox"][1], "".join(s["text"] for s in ln["spans"]))
             for bl in page.get_text("dict")["blocks"] for ln in bl.get("lines", [])]
    note = next(y for y, t in lines if "Margin is revenue" in t)
    body = max(y for y, t in lines if "Revenue grew" in t)
    assert note > body + 20 and note > page.rect.height * 0.75      # below the text, at the foot


def test_review_reads_the_word_file_and_a_minus_takes_a_proportional_face(tmp_path):
    import shutil
    b = DocumentBuilder.from_markdown("# Review\n\nMargin fell −1.2 points.\n")
    spans = {c["c"]: s["font"] for page in fitz.open(stream=b.render(), filetype="pdf")
             for bl in page.get_text("rawdict")["blocks"] for ln in bl.get("lines", [])
             for s in ln["spans"] for c in s["chars"]}
    assert "Mono" not in spans["−"]
    if not (shutil.which("soffice") or shutil.which("libreoffice")):
        pytest.skip("LibreOffice is not available")
    got = b.review(str(tmp_path), format="docx")
    assert got["passed"] and len(got["images"]) == got["pages"] >= 1


def test_a_footnote_at_the_foot_of_the_page_counts_as_laid_out_for_the_gates():
    md = "# Paper\n\nWe study recall.[^1]\n\n[^1]: Data available on request.\n\n## Methods\n\nTwo groups.\n"
    variants = DocumentBuilder.from_markdown(md).design_variants(n=3).variants
    assert variants and all(v.valid for v in variants), [v.report.hard_failures for v in variants]


def test_the_forecast_lets_two_spaces_between_blocks_overlap_as_the_frame_does():
    from dynamic_pdf.intelligence.analysis import measure_blocks, simulate
    b = DocumentBuilder.from_markdown("# A\n\nText.\n\n## B\n\n1. One\n2. Two\n3. Three\n\nMore text.\n")
    doc, theme = b._prepared_base()
    ms, fg = measure_blocks(doc, theme, b._policy, {})
    geo = simulate(ms, fg)
    tops = {r.block: r.top for r in geo.regions}
    i = next(k for k, blk in enumerate(doc.blocks) if blk.type == "numbered_list")
    gap = tops[i - 1] - tops[i] - (ms[i - 1].height - ms[i - 1].space_after)
    assert gap <= max(ms[i - 1].space_after, ms[i].space_before) + 0.5


def _page_with_span(doc, text):
    return next((i for i, p in enumerate(doc) for b in p.get_text("dict")["blocks"] for ln in b.get("lines", [])
                 if any(s["text"].strip() == text for s in ln["spans"])), None)


@pytest.mark.parametrize("row", [1, 45, 88])
def test_a_note_in_a_long_table_sits_on_its_references_page(row):
    body = "\n".join((f"| Row {k}[^row-note] | {k * 10} |" if k == row else f"| Row {k} | {k * 10} |")
                     for k in range(1, 90))
    md = f"| Item | Value |\n|---|---:|\n{body}\n\n[^row-note]: Note for this row.\n"
    doc = fitz.open(stream=DocumentBuilder.from_markdown(md).render(), filetype="pdf")
    note = next(i for i, p in enumerate(doc) if "Note for this row" in p.get_text())
    assert _page_with_span(doc, f"Row {row}") == note and len(doc) > 2


def test_a_note_at_the_start_of_a_long_paragraph_sits_on_its_first_page():
    para = "Opening sentence with a source.[^p] " + "Revenue grew in every region, led by the north. " * 150
    doc = fitz.open(stream=DocumentBuilder.from_markdown(para + "\n\n[^p]: Note for the opening.\n").render(),
                    filetype="pdf")
    assert len(doc) > 2 and "Note for the opening" in doc[0].get_text() and "Opening sentence" in doc[0].get_text()


VERTICAL_MD = """| Feature | Starter plan | Professional plan | Enterprise plan |
|---|:-:|:-:|:-:|
| Single sign-on | — | ✓ | ✓ |
| Audit log | — | — | ✓ |

Table: Plans compared {#tbl-plans .vertical-headers}
"""


def test_vertical_headers_stand_on_their_side_in_pdf_word_and_the_workbook():
    import openpyxl
    b = DocumentBuilder.from_markdown(VERTICAL_MD)
    table = b.build().blocks[0]
    assert table.vertical_headers and table.caption == "Plans compared" and table.id == "tbl-plans"
    page = fitz.open(stream=b.render(), filetype="pdf")[0]
    dirs = {"".join(s["text"] for s in ln["spans"]).strip(): ln["dir"]
            for bl in page.get_text("dict")["blocks"] for ln in bl.get("lines", [])}
    assert abs(dirs["Starter plan"][1]) > 0.99 and abs(dirs["Feature"][0]) > 0.99   # side-set; the first level
    xml = zipfile.ZipFile(io.BytesIO(b.render_docx())).read("word/document.xml").decode()
    assert xml.count('w:textDirection w:val="tbRl"') == 3
    ws = openpyxl.load_workbook(io.BytesIO(b.render_xlsx())).worksheets[0]
    assert [ws.cell(1, c).alignment.text_rotation for c in range(1, 5)] == [0, 180, 180, 180]


def test_an_arabic_word_table_keeps_its_headers_level_and_says_why(tmp_path):
    md = "---\nlanguage: ar\n---\n\n| الميزة | الباقة الأساسية |\n|---|:-:|\n| الدخول الموحد | ✓ |\n\nTable: مقارنة {.vertical-headers}\n"
    with pytest.warns(RuntimeWarning, match="vertical_headers_level"):
        res = DocumentBuilder.from_markdown(md).export(str(tmp_path / "a.docx"))
    xml = zipfile.ZipFile(str(tmp_path / "a.docx")).read("word/document.xml").decode()
    assert "w:textDirection" not in xml
    assert [d["code"] for d in res.diagnostics] == ["vertical_headers_level"]
