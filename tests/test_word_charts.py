"""Charts reach Word as native charts: editable data and formatting, real text labels."""
import builtins
import io
import zipfile

import pytest
from lxml import etree

from dynamic_pdf import DocumentBuilder
from dynamic_pdf.utils.errors import BlockRenderError

C = "{http://schemas.openxmlformats.org/drawingml/2006/chart}"
MULTI = {"categories": ["Q1", "Q2"], "series": {"2024": [3, 4], "2025": [4, 6]}}


def parts(b):
    with zipfile.ZipFile(io.BytesIO(b.render_docx())) as z:
        return {n: z.read(n) for n in z.namelist()}


def chart(b, n=1):
    return etree.fromstring(parts(b)[f"word/charts/chart{n}.xml"])


@pytest.mark.parametrize("kind, data, element, extra", [
    ("bar", {"North": 4, "South": 6}, "barChart", ("barDir", "col")),
    ("horizontal_bar", {"North": 4, "South": 6}, "barChart", ("barDir", "bar")),
    ("grouped_bar", MULTI, "barChart", ("grouping", "clustered")),
    ("stacked_bar", MULTI, "barChart", ("grouping", "stacked")),
    ("line", MULTI, "lineChart", None),
    ("area", {"Jan": 1, "Feb": 2}, "areaChart", None),
    ("pie", {"A": 60, "B": 40}, "pieChart", None),
    ("donut", {"A": 60, "B": 40}, "doughnutChart", ("holeSize", "50")),
])
def test_each_common_type_is_a_word_chart_of_its_kind(kind, data, element, extra):
    b = DocumentBuilder().chart(kind, data, title="T")
    files = parts(b)
    root = etree.fromstring(files["word/charts/chart1.xml"])
    body = root.find(f".//{C}{element}")
    assert body is not None
    if extra:
        assert body.find(f"{C}{extra[0]}").get("val") == extra[1]
    assert b"<pic:pic" not in files["word/document.xml"] and b"<c:chart " in files["word/document.xml"]


def test_the_chart_holds_the_values_names_and_colours_the_pdf_draws():
    root = chart(DocumentBuilder().chart("grouped_bar", MULTI, title="Sales", colors=["#112233", "#445566"]))
    sers = root.findall(f".//{C}ser")
    assert [s.find(f".//{C}tx//{C}v").text for s in sers] == ["2024", "2025"]
    assert [v.text for v in sers[1].findall(f"{C}val//{C}v")] == ["4", "6"]
    assert [v.text for v in sers[0].findall(f"{C}cat//{C}v")] == ["Q1", "Q2"]
    assert b"112233" in etree.tostring(sers[0]) and b"445566" in etree.tostring(sers[1])
    assert "Sales" in "".join(root.find(f".//{C}title").itertext())


def test_word_can_edit_the_data_in_the_embedded_workbook():
    pytest.importorskip("openpyxl")
    from openpyxl import load_workbook
    files = parts(DocumentBuilder().chart("bar", {"North": 4, "South": 6}))
    assert b'Target="../embeddings/Microsoft_Excel_Worksheet1.xlsx"' in files["word/charts/_rels/chart1.xml.rels"]
    ws = load_workbook(io.BytesIO(files["word/embeddings/Microsoft_Excel_Worksheet1.xlsx"])).active
    assert [[c.value for c in r] for r in ws.iter_rows()] == [[None, "Value"], ["North", 4], ["South", 6]]
    assert b"<c:f>Sheet1!$B$2:$B$3</c:f>" in files["word/charts/chart1.xml"]


def test_without_openpyxl_the_chart_carries_its_values_alone(monkeypatch):
    real = builtins.__import__

    def no_openpyxl(name, *a, **k):
        if name == "openpyxl":
            raise ImportError("no openpyxl")
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", no_openpyxl)
    files = parts(DocumentBuilder().chart("pie", {"A": 60, "B": 40}))
    xml = files["word/charts/chart1.xml"]
    assert b"<c:numLit>" in xml and b"externalData" not in xml and not [n for n in files if "embeddings" in n]


def test_a_rare_type_stays_a_picture_with_its_alt_text():
    files = parts(DocumentBuilder().chart("funnel", {"Visits": 100, "Carts": 40, "Orders": 10}, title="Funnel"))
    assert not [n for n in files if n.startswith("word/charts/")]
    assert b"<pic:pic" in files["word/document.xml"] and b'descr="funnel chart: Funnel' in files["word/document.xml"]


def test_data_the_chart_cannot_draw_is_refused_as_before():
    with pytest.raises(BlockRenderError, match="one series"):
        DocumentBuilder().chart("bar", MULTI).render_docx()


def test_a_numbered_chart_keeps_its_title_for_the_caption_and_has_alt_text():
    from dynamic_pdf.schema.blocks import ChartBlock
    b = DocumentBuilder().add_block(ChartBlock(chart_type="bar", data={"A": 1, "B": 2}, title="Revenue", id="rev"))
    b.paragraph("See {ref:rev}.")
    files = parts(b)
    assert etree.fromstring(files["word/charts/chart1.xml"]).find(f".//{C}chart/{C}title") is None
    doc = files["word/document.xml"].decode()
    assert 'descr="bar chart: Revenue. Data: A: 1; B: 2"' in doc and "Revenue" in doc     # the caption under it
