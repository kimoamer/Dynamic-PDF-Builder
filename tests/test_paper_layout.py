"""An academic document is set as a paper: checked on the rendered PDF and the DOCX."""
import io
import zipfile

import pymupdf
import pytest
from docx import Document as Word

from dynamic_pdf import DocumentBuilder
from stress_docs import academic_paper


@pytest.fixture(scope="module")
def pdf():
    return pymupdf.open(stream=academic_paper().design("auto").render(), filetype="pdf")


@pytest.fixture(scope="module")
def word():
    return Word(io.BytesIO(academic_paper().design("auto").render_docx()))


def _lines(page):
    out = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            spans = [s for s in line["spans"] if s["text"].strip()]
            if spans:
                out.append(("".join(s["text"] for s in line["spans"]).strip(), spans[0], line["bbox"]))
    return out


def test_page_one_opens_with_title_authors_abstract_and_the_first_section(pdf):
    first = pdf[0].get_text()
    for expected in ("Sleep Duration and Short-Term Recall", "A. Rahman, J. Smith", "Abstract", "1 Introduction"):
        assert expected in first
    assert "Prepared by" not in first and "Table of Contents" not in "".join(p.get_text() for p in pdf)
    title = next(l for l in _lines(pdf[0]) if l[0].startswith("Sleep Duration"))
    mid = (title[2][0] + title[2][2]) / 2
    assert abs(mid - pdf[0].rect.width / 2) < 3            # centred
    assert len(pdf) == 4                                      # was 5, one of them a contents page


def test_abstract_is_plain_with_run_in_labels(pdf):
    page = pdf[0]
    assert not [d for d in page.get_drawings() if d["rect"].width > 100]      # no box, no bar, no fill
    assert any(t.startswith("Background: Sleep supports") for t, _, _ in _lines(page))


def test_paragraphs_are_told_apart_by_indent_alone(pdf):
    lines = _lines(pdf[0])
    left = min(bb[0] for t, _, bb in lines if t.startswith("recall was scored"))
    first = next(bb for t, _, bb in lines if t.startswith("Introduction paragraph 1"))
    second = next(bb for t, _, bb in lines if t.startswith("Introduction paragraph 2"))
    assert abs(first[0] - left) < 1 and second[0] - left > 10          # flush under the heading, then indented
    until = next(bb for t, _, bb in lines if t == "2 Methods")[1]
    body = [bb for t, s, bb in lines if abs(s["size"] - 11.5) < 0.1 and first[1] <= bb[1] < until]
    steps = {round(b[1] - a[1], 1) for a, b in zip(body, body[1:])}
    assert len(steps) == 1                                               # no gap between paragraphs


def test_table_is_ruled_not_boxed_and_captioned_above(pdf):
    page = next(p for p in pdf if "Recall by condition" in p.get_text())
    lines = _lines(page)
    caption = next(bb for t, _, bb in lines if t.startswith("Table 1: Recall by condition"))
    header = next(bb for t, _, bb in lines if t == "Condition")
    assert caption[1] < header[1]
    last_row = next(bb for t, _, bb in lines if t == "8 h")
    rules = [d["rect"] for d in page.get_drawings() if d["rect"].height < 2 and d["rect"].width > 100
             and caption[1] < d["rect"].y0 < last_row[3] + 10]
    assert len({round(r.y0) for r in rules}) == 3                        # top, under the header, bottom
    assert not [d for d in page.get_drawings() if d.get("fill") and d["rect"].height > 8
                and caption[1] < d["rect"].y0 < header[1] + 100 and d["fill"] != (1.0, 1.0, 1.0)]
    width = max(r.width for r in rules)
    assert width < (page.rect.width - 144) * 0.8                         # as wide as its content
    assert abs((rules[0].x0 + rules[0].x1) / 2 - page.rect.width / 2) < 3
    condition = next(bb for t, _, bb in lines if t == "4 h")
    assert abs(condition[0] - header[0]) < 1                             # the stub column reads from the left


def test_figure_is_numbered_captioned_below_and_grey(pdf):
    page = next(p for p in pdf if "Mean recall by condition" in p.get_text())
    caption = next(bb for t, _, bb in _lines(page) if t.startswith("Figure 1: Mean recall by condition"))
    assert sum("Mean recall by condition" in t for t, _, _ in _lines(page)) == 1      # not also inside the figure
    from dynamic_pdf.renderers.chart import chart_png
    from PIL import Image
    doc, theme = academic_paper().design("auto")._prepared()
    chart = next(b for b in doc.blocks if b.type == "chart")
    img = Image.open(io.BytesIO(chart_png(chart, theme))).convert("RGB").resize((60, 40))
    assert all(abs(r - g) < 12 and abs(g - b) < 12 for r, g, b in img.getdata())
    bar_top = min(d["rect"].y0 for d in page.get_drawings() if d["rect"].width > 30 and d["rect"].height > 30)
    assert bar_top < caption[1]


def test_references_carry_the_numbers_the_text_cites(pdf):
    last = pdf[-1].get_text()
    assert "[1] Bates" in last and "[2] Walker" in last
    assert any(t == "References" for t, _, _ in _lines(pdf[-1]))


def test_abstract_and_references_headings_are_not_numbered():
    md = "---\ntitle: Effects of Sleep\ndoc_type: academic\n---\n# Abstract\n\nWe study sleep.\n\n# Introduction\n\n" \
         "Prior work.\n\n# Methods\n\nTwo groups.\n\n# References\n\n1. Smith (2020).\n"
    text = pymupdf.open(stream=DocumentBuilder.from_markdown(md).design("auto").render(), filetype="pdf")[0].get_text()
    heads = [ln.strip() for ln in text.splitlines() if ln.strip() in
             ("Abstract", "1 Abstract", "1 Introduction", "2 Introduction", "2 Methods", "References", "4 References")]
    assert heads == ["Abstract", "1 Introduction", "2 Methods", "References"]


def test_docx_is_set_the_same_way(word):
    paras = word.paragraphs
    texts = [p.text for p in paras]
    title = next(p for p in paras if p.text == "Sleep Duration and Short-Term Recall")
    assert title.alignment == 1                                           # centred
    assert "A. Rahman, J. Smith" in texts and not any("Prepared by" in t for t in texts)
    assert any(t.startswith("Background: Sleep supports") for t in texts)        # not inside a boxed table cell
    assert "Table 1: Recall by condition" in texts and "Figure 1: Mean recall by condition" in texts
    assert any(t.startswith("[1] Bates") for t in texts)
    heads = [p.text for p in paras if p.style.name.startswith("Heading")]
    assert heads[:2] == ["1  Introduction", "2  Methods"] and heads[-1] == "References"
    body = word.element.body
    before_intro = body.xml.split("Introduction")[0]
    assert 'w:type="page"' not in before_intro                             # the text follows on page one
    table = word.tables[0]
    assert len(word.tables) == 1 and "w:shd" not in table._tbl.xml         # one table, the data; nothing filled
    first = next(p for p in paras if p.text.startswith("Introduction paragraph 1"))
    assert first.paragraph_format.first_line_indent == 0


def test_variants_of_a_paper_recommend_the_paper_setting_and_others_never_get_it():
    made = academic_paper().design_variants(n=3)
    assert made.recommended.id == "academic_paper" and made.recommended.valid
    from conftest import fixture_text
    proposal = DocumentBuilder.from_markdown(fixture_text("proposal.md"))
    assert "academic_paper" not in [v.id for v in proposal.design_variants(n=5).variants]


def test_a_title_block_does_not_end_its_page_in_the_forecast():
    from dynamic_pdf.intelligence.analysis import forces_break
    doc, _ = academic_paper().design("auto")._prepared()
    cover = doc.blocks[0]
    assert cover.type == "cover_page" and (cover.hints or {}).get("title_block") and not forces_break(cover)


def test_other_documents_are_untouched_by_the_paper_conventions():
    from conftest import fixture_text
    doc, theme = DocumentBuilder.from_markdown(fixture_text("proposal.md")).design("auto")._prepared()
    assert not theme.decorations.paper and not doc.meta.exhibit_numbering
