"""M10 references and numbering: table and figure numbers, {ref:id}, lists of figures and tables."""
import io
import re

import pytest

from dynamic_pdf import DocumentBuilder
from dynamic_pdf.core.content_ledger import build_content_ledger
from dynamic_pdf.qa.content_preservation import VERIFIED, check_preservation

pymupdf = pytest.importorskip("pymupdf")
docx = pytest.importorskip("docx")


@pytest.fixture
def photo(tmp_path):
    from PIL import Image
    path = tmp_path / "map.png"
    Image.new("RGB", (400, 240), (40, 90, 160)).save(path)
    return str(path)


def doc_md(photo):
    return f"""---
title: Results
---
[LOT]

[LOF]

# Method {{#method}}

As {{ref:tab-sales}} shows and {{ref:fig-map}} confirms (see {{ref:method}}), sales grew.

| Region | Sales |
|---|---|
| North | 10 |
| South | 20 |

Table: Sales by region {{#tab-sales}}

![A map of the two regions]({photo} "Regions"){{#fig-map}}

| A | B |
|---|---|
| 1 | 2 |

Table: Second table
"""


def pdf_text(data):
    with pymupdf.open(stream=data, filetype="pdf") as d:
        return [p.get_text() for p in d], [[l for l in p.get_links()] for p in d]


def test_markdown_ids_captions_and_lists(photo):
    b = DocumentBuilder.from_markdown(doc_md(photo))
    kinds = [(x.type, getattr(x, "kind", None), x.id) for x in b._blocks]
    assert kinds[:3] == [("table_of_contents", "tables", None), ("table_of_contents", "figures", None),
                         ("heading", None, "method")]
    table = b._blocks[4]
    assert (table.caption, table.id, table.hints) == ("Sales by region", "tab-sales", None)
    assert b._blocks[5].id == "fig-map" and b._blocks[5].caption == "Regions"
    assert b._meta.exhibit_numbering                     # "Table:" captions ask for numbers
    assert b._blocks[3].text.count("{ref:") == 3         # the author's text is kept as written


@pytest.mark.parametrize("design", [False, True])
def test_pdf_numbers_references_and_lists(photo, design):
    b = DocumentBuilder.from_markdown(doc_md(photo))
    if design:
        b.design()
    pages, links = pdf_text(b.render())
    body = "\n".join(pages)
    flat = " ".join(body.split())
    assert "As Table 1 shows and Figure 1 confirms" in flat
    assert "Table 1: Sales by region" in flat and "Table 2: Second table" in flat
    assert "Figure 1: Regions" in flat
    assert "{ref:" not in body
    lot = next(p for p in pages if "List of Tables" in p)
    assert "Table 2: Second table" in " ".join(lot.split())
    lof = next(p for p in pages if "List of Figures" in p)
    assert "Figure 1: Regions" in " ".join(lof.split())
    caption_page = next(i for i, p in enumerate(pages) if "Sales by region" in p and "North" in p)
    body_page = next(i for i, p in enumerate(pages) if "As Table 1" in " ".join(p.split()))
    assert any(l.get("page") == caption_page for l in links[body_page])


def test_docx_numbers_references_and_lists(photo):
    b = DocumentBuilder.from_markdown(doc_md(photo)).design()
    data = b.render_docx()
    d = docx.Document(io.BytesIO(data))
    texts = [p.text for p in d.paragraphs if p.text.strip()]
    assert any("As Table 1 shows and Figure 1 confirms" in t for t in texts)
    assert "Table 1: Sales by region" in texts and "Figure 1: Regions" in texts
    xml = d.element.xml
    anchors = set(re.findall(r'w:anchor="([^"]+)"', xml))
    marks = set(re.findall(r'w:bookmarkStart [^>]*w:name="([^"]+)"', xml))
    assert anchors and anchors <= marks


def test_content_ledger_and_preservation_still_pass(photo):
    b = DocumentBuilder.from_markdown(doc_md(photo)).design()
    designed, _ = b._prepared()
    ledger = build_content_ledger(designed)
    assert ("tab-sales", "Table 1") in ledger.refs and ("method", "Section 1") in ledger.refs
    # numbering adds nothing to the author's text: the same strings, {ref:id} markers included
    # (a title block the design builds from the metadata is not the numbering's doing)
    assert [e.text for e in ledger.entries if e.block_type != "cover_page"] == build_content_ledger(b.build()).strings()
    report = check_preservation(ledger, pdf=b.render(), docx=b.render_docx())
    assert report.status == VERIFIED, report.to_dict()


def test_unresolved_reference_stays_as_written_and_lint_reports_it():
    b = DocumentBuilder().heading("Intro").paragraph("See {ref:missing} and {ref:intro}.")
    pages, _ = pdf_text(b.render())
    assert "{ref:missing}" in pages[0]
    rules = [(w.rule, w.message) for w in b.lint()]
    assert any(r == "unresolved_ref" and "missing" in m for r, m in rules)
    assert not any("intro" in m for _, m in rules)


def test_numbering_is_off_unless_asked_and_author_numbers_are_kept():
    plain = DocumentBuilder().paragraph("Text.").table(["A"], [["1"]], caption="Plain caption")
    pages, _ = pdf_text(plain.render())
    assert "Table 1" not in pages[0] and "Plain caption" in pages[0]
    own = DocumentBuilder().exhibit_numbering().table(["A"], [["1"]], caption="First", table_number=7) \
        .table(["B"], [["2"]], caption="Second")
    pages, _ = pdf_text(own.render())
    flat = " ".join(pages[0].split())
    assert "Table 7: First" in flat and "Table 2: Second" in flat


def test_arabic_labels():
    b = DocumentBuilder().meta(language="ar").exhibit_numbering().heading("النتائج", ).paragraph(
        "انظر {ref:t1}.").table(["المنطقة", "المبيعات"], [["الرياض", "١٠"]], caption="المبيعات حسب المنطقة")
    b._blocks[-1].id = "t1"
    d = docx.Document(io.BytesIO(b.design().render_docx()))
    texts = [p.text for p in d.paragraphs]
    assert "انظر جدول 1." in texts and "جدول 1: المبيعات حسب المنطقة" in texts


def test_fluent_lists():
    b = (DocumentBuilder().list_of_tables().heading("Data").paragraph("Text.")
         .table(["A"], [["1"]], caption="Only table"))
    pages, _ = pdf_text(b.render())
    assert "List of Tables" in pages[0] and "Table 1: Only table" in " ".join(pages[0].split())


@pytest.mark.parametrize("heading", ["References", "Sources", "المراجع", None])
def test_a_reference_list_under_the_authors_heading_has_no_second_title(heading):
    entries = [{"key": "a", "authors": "Abara, T.", "title": "Retreat", "source": "J. Coastal Policy", "year": "2023"}]
    b = DocumentBuilder().heading("Intro").paragraph("Text.")
    if heading:
        b.heading(heading)
    b.bibliography(entries)
    pdf = " ".join(pdf_text(b.render())[0][0].split())
    words = [p.text for p in docx.Document(io.BytesIO(b.render_docx())).paragraphs if p.text.strip()]
    titles = (1 if heading else 0) + (0 if heading else 1)            # the author's heading, or the list's own title
    assert sum(w in ("References", "Sources", "المراجع") for w in words) == titles
    if heading != "المراجع":                    # extracted Arabic comes out in visual order; Word holds it as written
        assert pdf.count("References") + pdf.count("Sources") == titles
