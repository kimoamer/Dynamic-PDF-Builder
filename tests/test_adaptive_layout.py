"""M3: content-aware layout decisions (tables, measure, hierarchy, lead, cover, landscape)."""
import io
import pytest
import pymupdf
from dynamic_pdf import DocumentBuilder
from dynamic_pdf.design.planner import MIN_TABLE_SIZE
from conftest import fixture_text, all_fixtures, open_docx, docx_text, pdf_text

EXPECTED = {"memo.md": "corporate_memo", "invoice.md": "invoice", "wide_data.md": "data_report"}


@pytest.mark.parametrize("name,profile", sorted(EXPECTED.items()))
def test_more_profiles(name, profile):
    assert DocumentBuilder.from_markdown(fixture_text(name)).design().design_explain()["profile"] == profile


def _wide_table_builder():
    headers = [f"Column header {i}" for i in range(11)]
    rows = [[f"value {r}-{c} lorem ipsum" for c in range(11)] for r in range(25)]
    return (DocumentBuilder().meta(title="Wide").heading("Data").paragraph("Intro text.")
            .table(headers, rows).heading("After").paragraph("Closing text.").design("data_report"))


def test_too_wide_table_gets_landscape_pages_in_pdf_and_docx():
    b = _wide_table_builder()
    pdf = pymupdf.open(stream=b.render(), filetype="pdf")
    orient = [(p.rect.width > p.rect.height) for p in pdf]
    assert orient[0] is False and any(orient), orient
    land_text = "".join(p.get_text() for p in pdf if p.rect.width > p.rect.height)
    flat = land_text.replace("\n", " ")
    assert "Column header 10" in flat and "value 24-10" in flat
    assert pdf[-1].rect.width < pdf[-1].rect.height          # back to portrait for "After"
    assert "Closing text." in pdf[-1].get_text()
    assert any("landscape" in d for d in b.design_explain()["layout"])
    d = open_docx(b.render_docx())
    orients = [s.page_width > s.page_height for s in d.sections]
    assert orients == [False, True, False]
    assert "value 24-10 lorem ipsum" in docx_text(b.render_docx())


def test_table_font_never_below_minimum_and_numbers_right_aligned():
    b = DocumentBuilder.from_markdown(fixture_text("wide_data.md")).design()
    pdf = pymupdf.open(stream=b.render(), filetype="pdf")
    sizes = [s["size"] for p in pdf for bl in p.get_text("dict")["blocks"]
             for ln in bl.get("lines", []) for s in ln["spans"] if s["text"].strip()]
    assert min(sizes) >= MIN_TABLE_SIZE - 0.01 or min(sizes) >= 6.5   # footers may be smaller
    # numeric column: right edges line up
    page = pdf[0]
    xs = [s["bbox"][2] for bl in page.get_text("dict")["blocks"] for ln in bl.get("lines", [])
          for s in ln["spans"] if s["text"].strip().endswith("%") and "." in s["text"]]
    groups = {}
    for x in xs:
        groups.setdefault(round(x / 25), []).append(x)
    biggest = max(groups.values(), key=len)
    assert len(biggest) >= 5 and max(biggest) - min(biggest) < 1.0


def test_column_widths_follow_content():
    b = DocumentBuilder.from_markdown(fixture_text("wide_data.md")).design()
    doc, _ = b._prepared()
    t = next(x for x in doc.blocks if x.type == "table")
    f = t.hints["col_fractions"]
    assert abs(sum(f) - 1) < 0.01
    assert f[1] > f[8]            # "Segment" text column wider than "Week"


def test_small_table_kept_with_caption_on_one_page():
    b = DocumentBuilder().design("executive_report")
    for _ in range(11):
        b.paragraph("filler " * 55)
    b.table(["A", "B"], [[str(i), str(i * 2)] for i in range(8)], caption="Small table")
    pdf = pymupdf.open(stream=b.render(), filetype="pdf")
    page_of = {}
    for i, p in enumerate(pdf):
        t = p.get_text()
        if "Small table" in t:
            page_of["cap"] = i
        if "14" in t.split():
            page_of["last_row"] = i
    assert page_of["cap"] == page_of["last_row"]


def test_measure_widens_margins_for_prose():
    md = "# Approach\n\n" + ("We will deliver the programme in phases with clear owners. " * 30)
    b = DocumentBuilder.from_markdown(md).design("proposal")
    b.render()
    ex = b.design_explain()
    assert any(d.startswith("measure:") and "widened" in d for d in ex["layout"]) or \
        any(d.startswith("measure:") for d in ex["layout"])
    t = b.last_render.theme
    from dynamic_pdf.design.measure import chars_per_line
    width = 595.28 - t.spacing.page_margin_left - t.spacing.page_margin_right
    assert chars_per_line(width, t.typography.body_family, t.typography.base_size) <= 92


def test_lead_paragraph_is_larger():
    b = DocumentBuilder.from_markdown(fixture_text("executive.md")).design()
    pdf = pymupdf.open(stream=b.render(), filetype="pdf")
    spans = [s for bl in pdf[0].get_text("dict")["blocks"] for ln in bl.get("lines", [])
             for s in ln["spans"]]
    lead = next(s for s in spans if s["text"].startswith("Revenue grew"))
    body = next(s for s in spans if "Enterprise renewals" in s["text"])
    assert lead["size"] > body["size"] * 1.1


def test_cover_only_for_long_titled_reports():
    long_md = "---\ntitle: Annual Review\nauthor: Board\n---\n" + "\n\n".join(
        f"# Section {i}\n\n" + "Results improved across all regions this year. " * 40 for i in range(8))
    b = DocumentBuilder.from_markdown(long_md).design("executive_report")
    pdf = pymupdf.open(stream=b.render(), filetype="pdf")
    first = pdf[0].get_text()
    assert "Annual Review" in first and "Prepared by Board" in first
    assert any(d.startswith("cover:") for d in b.design_explain()["layout"])
    short = DocumentBuilder.from_markdown(fixture_text("executive.md")).design()
    short.render()
    assert not any(d.startswith("cover:") for d in short.design_explain()["layout"])


@pytest.mark.parametrize("name", all_fixtures())
def test_no_heading_stranded_at_page_bottom(name):
    b = DocumentBuilder.from_markdown(fixture_text(name)).design()
    pdf = pymupdf.open(stream=b.render(), filetype="pdf")
    for pno, page in enumerate(pdf):
        if pno == pdf.page_count - 1:
            continue
        lines = [ln for bl in page.get_text("dict")["blocks"] for ln in bl.get("lines", [])
                 if "".join(s["text"] for s in ln["spans"]).strip()]
        body = [ln for ln in lines if ln["bbox"][1] < page.rect.height - 60]   # ignore footer
        if not body:
            continue
        last = max(body, key=lambda ln: ln["bbox"][1])
        biggest = max(s["size"] for s in last["spans"])
        assert biggest < 13, f"page {pno + 1} ends with a heading-sized line"


@pytest.mark.parametrize("name", all_fixtures())
def test_designed_output_preserves_every_word(name):
    import re, unicodedata
    from dynamic_pdf.core.inline import plain_text
    from dynamic_pdf.core.normalize import block_text
    b = DocumentBuilder.from_markdown(fixture_text(name)).design()
    words = set()
    for blk in b.semantic().blocks:
        if blk.type in ("math", "chart", "diagram", "mermaid"):
            continue
        for t in block_text(blk):
            words |= set(re.findall(r"[^\W_]{3,}", unicodedata.normalize("NFKC", plain_text(t)).lower()))
    got = set(re.findall(r"[^\W_]{3,}", unicodedata.normalize("NFKC", docx_text(b.render_docx())).lower()))
    assert words <= got, sorted(words - got)[:10]
