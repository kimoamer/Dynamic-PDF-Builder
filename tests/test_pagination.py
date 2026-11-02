"""P0-01 / P1-01: real page totals, heading continuity, linked page-aware TOC."""
import re
import pytest
from dynamic_pdf import DocumentBuilder
from conftest import open_pdf


def _doc(theme, pages_of_text):
    b = DocumentBuilder(theme=theme)
    for i in range(pages_of_text):
        b.heading(f"Chapter {i + 1}").paragraph("word " * 650)
    return b


@pytest.mark.parametrize("n_sections", [0, 1, 4, 12])
def test_page_n_of_total_is_final(total_theme, n_sections):
    b = DocumentBuilder(theme=total_theme).paragraph("Short.")
    for i in range(n_sections):
        b.heading(f"Chapter {i + 1}").paragraph("word " * 650)
    doc = open_pdf(b.render())
    total = doc.page_count
    assert b.last_render.page_count == total
    for i, page in enumerate(doc, start=1):
        text = page.get_text()
        assert "?" not in re.findall(r"Page \S+ of (\S+)", text)
        assert f"Page {i} of {total}" in text, (i, total, text[-200:])


def test_one_and_ten_page_documents(total_theme):
    one = open_pdf(DocumentBuilder(theme=total_theme).paragraph("one").render())
    assert one.page_count == 1
    assert "Page 1 of 1" in one[0].get_text()
    b = DocumentBuilder(theme=total_theme)
    for i in range(10):
        b.paragraph(f"page {i}").page_break()
    ten = open_pdf(b.render())
    assert ten.page_count >= 10
    assert f"Page {ten.page_count} of {ten.page_count}" in ten[-1].get_text()


def test_toc_at_front_has_final_page_numbers_and_links():
    b = DocumentBuilder().table_of_contents(depth=2)
    for i in range(3):
        b.heading(f"Section {i}").paragraph("lorem ipsum " * 400)
        b.heading(f"Detail {i}", level=2).paragraph("detail")
        b.heading(f"Deep {i}", level=3).paragraph("deep")
    doc = open_pdf(b.render())
    outline = doc.get_toc()
    titles = {t[1]: t[2] for t in outline}
    toc_text = doc[0].get_text()
    # every H1/H2 after the TOC is listed; H3 is beyond depth=2
    for i in range(3):
        assert f"Section {i}" in toc_text
        assert f"Detail {i}" in toc_text
        assert f"Deep {i}" not in toc_text
    # page numbers in the TOC match where the headings actually are
    for i in range(3):
        page_no = titles[f"Section {i}"]
        assert f"Section {i}" in doc[page_no - 1].get_text()
        assert re.search(rf"\b{page_no}\b", toc_text)
    links = [l for l in doc[0].get_links() if l.get("kind") == 1]   # LINK_GOTO
    assert len(links) >= 6
    targets = {l["page"] for l in links}
    assert targets <= set(range(doc.page_count))
    assert "Place this block" not in toc_text


def test_heading_never_stranded_at_page_bottom():
    b = DocumentBuilder()
    # fill most of the first page, then a heading followed by a long paragraph
    for _ in range(9):
        b.paragraph("filler " * 60)
    b.heading("Kept Heading").paragraph("body " * 300)
    doc = open_pdf(b.render())
    for page in doc:
        blocks = [bl for bl in page.get_text("blocks") if bl[4].strip()]
        last = blocks[-1][4] if blocks else ""
        if "Kept Heading" in last and page.number < doc.page_count - 1:
            pytest.fail("heading is the last text on its page")


def test_outline_handles_skipped_levels():
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        b = DocumentBuilder().heading("Top").heading("Skipped", level=3).paragraph("x")
        doc = open_pdf(b.render())
    assert [t[1] for t in doc.get_toc()] == ["Top", "Skipped"]
