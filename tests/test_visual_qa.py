"""M4: visual/structural QA on real output, bounded auto-fix, golden fixtures."""
import io
import json
import os
import shutil
import zipfile
import pytest
import pymupdf
from dynamic_pdf import DocumentBuilder, QualityError
from dynamic_pdf.qa import check_pdf, check_docx, rasterize_pdf, contact_sheet
from conftest import fixture_text, all_fixtures

HERE = os.path.dirname(__file__)


@pytest.mark.parametrize("name", all_fixtures())
def test_all_fixtures_pass_pdf_qa(name):
    b = DocumentBuilder.from_markdown(fixture_text(name)).design()
    data, rep = b.qa("pdf")
    assert rep.passed, rep.summary()
    assert rep.pages == pymupdf.open(stream=data, filetype="pdf").page_count


@pytest.mark.parametrize("name", ["executive.md", "arabic_report.md", "wide_data.md"])
def test_docx_structural_and_visual_qa(name):
    b = DocumentBuilder.from_markdown(fixture_text(name)).design()
    data, rep = b.qa("docx", visual=bool(shutil.which("soffice")))
    assert rep.passed, rep.summary() + str([f.message for f in rep.errors])


def _synthetic_pdf(draw):
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    draw(page)
    return doc.tobytes()


def test_detects_clipping_overflow_and_overlap():
    def draw(p):
        p.insert_text((72, 100), "Normal line of body text", fontsize=11)
        p.insert_text((540, 200), "This line runs off the right edge of the page", fontsize=11)
        p.insert_text((300, 300), "into the margin", fontsize=11)
        p.insert_text((72, 400), "Overlapping text one", fontsize=11)
        p.insert_text((74, 401), "Overlapping text two", fontsize=11)
    rep = check_pdf(_synthetic_pdf(draw), margins={"left": 72, "right": 300})
    codes = {f.code for f in rep.findings}
    assert {"clipped_text", "overflow", "overlap"} <= codes
    assert not rep.passed


def test_overflow_is_judged_by_ink_not_by_the_font_box():
    """A line's box comes from font metrics, which for Arabic faces reach far past the glyphs.
    Blank glyph space over the margin is not text in the margin; drawn letters there are."""
    def blank_edge(p):          # leading spaces cross the margin, the letters start inside it
        p.insert_text((50, 200), "        Letters start inside the margin", fontsize=11)

    def inked_edge(p):
        p.insert_text((50, 200), "Letters start in the margin", fontsize=11)
    margins = {"left": 72, "right": 72}
    assert not [f for f in check_pdf(_synthetic_pdf(blank_edge), margins=margins).findings if f.code == "overflow"]
    found = [f for f in check_pdf(_synthetic_pdf(inked_edge), margins=margins).findings if f.code == "overflow"]
    assert found and "by" in found[0].message


def test_detects_blank_page_and_stranded_heading():
    doc = pymupdf.open()
    p1 = doc.new_page(width=595, height=842)
    p1.insert_text((72, 100), "Body text", fontsize=11)
    p1.insert_text((72, 780), "Results", fontsize=16)
    doc.new_page(width=595, height=842)
    p3 = doc.new_page(width=595, height=842)
    p3.insert_text((72, 100), "More", fontsize=11)
    rep = check_pdf(doc.tobytes(), heading_texts=["Results"])
    codes = [f.code for f in rep.findings]
    assert "stranded_heading" in codes and "blank_page" in codes


def test_autofix_collapses_redundant_page_break():
    b = DocumentBuilder().cover_page("Title").page_break().heading("Body").paragraph("text")
    data, rep = b.qa("pdf")
    assert rep.passed and rep.attempts == 2
    assert any("page break" in f for f in rep.fixes_applied)
    assert "Body" in pymupdf.open(stream=data, filetype="pdf")[1].get_text()


def test_autofix_moves_stranded_heading():
    b = DocumentBuilder()
    for _ in range(12):
        b.paragraph("filler " * 52)
    b.heading("Lonely Heading").page_break().paragraph("Next page content.")
    data, rep = b.qa("pdf")
    assert rep.passed, rep.summary()
    assert any("heading" in f for f in rep.fixes_applied)
    doc = pymupdf.open(stream=data, filetype="pdf")
    page = next(p for p in doc if "Lonely Heading" in p.get_text())
    assert page.get_text().strip().startswith("Lonely Heading") or \
        "filler" not in page.get_text()


def test_missing_glyphs_fail_strict_and_report_permissive():
    with pytest.raises(QualityError) as ei:
        DocumentBuilder().paragraph("Stars ★ and 你好").qa("pdf")
    assert "missing_glyph" in str(ei.value) or "no installed font" in str(ei.value)
    data, rep = DocumentBuilder().quality("permissive").paragraph("Greeting 你好").qa("pdf")   # ★ now has a face
    assert not rep.passed and rep.errors[0].code == "missing_glyph"


def test_glyph_fallback_draws_symbols_with_bundled_font():
    data = DocumentBuilder().paragraph("Check ✓ arrow → ≥").render()
    spans = [(s["font"], s["text"]) for p in pymupdf.open(stream=data, filetype="pdf")
             for bl in p.get_text("dict")["blocks"] for ln in bl.get("lines", []) for s in ln["spans"]]
    assert ("JetBrainsMono-Regular", "✓") in spans
    assert not any(f in ("ZapfDingbats", "Symbol") for f, _ in spans)


def test_docx_structural_checks_detect_corruption():
    rep = check_docx(b"not a zip", visual=False)
    assert rep.errors[0].code == "corrupt_package"
    good = DocumentBuilder().heading("H").paragraph("p").render_docx()
    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(good)) as zin, zipfile.ZipFile(buf, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/document.xml":
                data = data.replace(b'w:anchor', b'w:anchor', 1)
                data = data.replace(b"</w:body>", b'<w:p><w:hyperlink w:anchor="_nope"/></w:p></w:body>')
            zout.writestr(item, data)
    rep = check_docx(buf.getvalue(), visual=False)
    assert "broken_link" in [f.code for f in rep.errors]


def test_export_with_qa_attaches_reports(tmp_path):
    res = DocumentBuilder.from_markdown(fixture_text("invoice.md")).design().export_both(
        str(tmp_path), qa=True)
    assert res.qa["pdf"].passed
    # without LibreOffice the DOCX layout cannot be inspected: UNVERIFIED, never PASS
    expected = "pass" if shutil.which("soffice") else "unverified"
    assert res.qa["docx"].status == expected and not res.qa["docx"].errors
    assert res.status == ("ok" if expected == "pass" else "unverified")
    assert res.qa["pdf"].sha256 and len(res.qa["pdf"].sha256) == 64


def test_rasterize_and_contact_sheet(tmp_path):
    data = DocumentBuilder.from_markdown(fixture_text("financial.md")).design().render()
    imgs = rasterize_pdf(data, str(tmp_path / "pages"), dpi=40)
    assert len(imgs) == pymupdf.open(stream=data, filetype="pdf").page_count
    out = contact_sheet(imgs, str(tmp_path / "sheet.png"))
    from PIL import Image
    assert Image.open(out).width > 300


@pytest.mark.parametrize("name", all_fixtures())
def test_golden_fingerprints(name):
    from dynamic_pdf.qa.golden import fingerprint
    path = os.path.join(HERE, "golden", name[:-3] + ".json")
    with open(path, encoding="utf-8") as f:
        want = json.load(f)
    got = json.loads(json.dumps(fingerprint(fixture_text(name)), ensure_ascii=False))
    assert got == want, {k: (want.get(k), got.get(k)) for k in want if want.get(k) != got.get(k)}


def _two_pages(last_line: str, size: float) -> bytes:
    doc = pymupdf.open()
    p = doc.new_page(width=595, height=842)
    p.insert_text((72, 100), "Ordinary body text at the top of the page.", fontsize=11)
    p.insert_text((72, 760), last_line, fontsize=size)
    doc.new_page(width=595, height=842).insert_text((72, 100), "The next page continues.", fontsize=11)
    return doc.tobytes()


def test_a_sentence_ending_with_heading_words_is_not_a_stranded_heading():
    heads = ["Risk management"]
    ends_paragraph = check_pdf(_two_pages("updated risk management.", 11), heading_texts=heads)
    assert "stranded_heading" not in {f.code for f in ends_paragraph.findings}
    real = check_pdf(_two_pages("Risk management", 14), heading_texts=heads)
    assert "stranded_heading" in {f.code for f in real.findings}


def test_a_body_size_line_sharing_caption_words_is_not_a_detached_caption():
    caps = ["Table 3: Regional risk management"]
    body_line = check_pdf(_two_pages("regional risk management", 11), captions=caps, body_size=11)
    assert "detached_caption" not in {f.code for f in body_line.findings}
    caption = check_pdf(_two_pages("Table 3: Regional risk management", 9), captions=caps, body_size=11)
    assert "detached_caption" in {f.code for f in caption.findings}


def test_a_chapter_opening_page_with_a_short_strip_does_not_strand_the_next_chapter():
    """The strip names the next chapter below the opener's title; with two chapters that was read as a stranded heading."""
    from dynamic_pdf.qa.loop import qa_context
    b = DocumentBuilder()
    b.section_opener("Potential", chapters=["Potential", "Thermal energy"], current=0)
    b.paragraph("Sunlight reaches the upper atmosphere and part of it is reflected back to space. " * 6)
    b.heading("Thermal energy").paragraph("Solar thermal technologies heat water and space. " * 6)
    pdf = b.render()
    ctx = qa_context(b.last_render.document, b.last_render.theme)
    assert ctx["openers"] == ["Potential"]
    heads = ["Potential", "Thermal energy"]
    assert "stranded_heading" not in {f.code for f in check_pdf(pdf, heading_texts=heads, **ctx).findings}
    blind = check_pdf(pdf, heading_texts=heads, **{**ctx, "openers": []})       # the fault this guards against
    assert "stranded_heading" in {f.code for f in blind.findings}
    long = DocumentBuilder()                                   # a title long enough to run over two lines
    long.section_opener("Wind energy resources across the northern coastal plains", chapters=["Wind energy resources across the northern coastal plains", "Wind farms"], current=0)
    long.paragraph("Wind is air in motion. " * 20)
    long.heading("Wind farms").paragraph("A wind farm is a group of turbines. " * 12)
    pdf = long.render()
    found = check_pdf(pdf, heading_texts=["Wind farms"], **qa_context(long.last_render.document, long.last_render.theme))
    assert "stranded_heading" not in {f.code for f in found.findings}


def test_a_compound_word_keeps_its_hyphen_when_its_paragraph_runs_onto_the_next_page():
    """ReportLab dropped the author's hyphen when it joined the halves again: "by-product" became "byproduct"."""
    from reportlab.lib.enums import TA_JUSTIFY
    from reportlab.lib.styles import ParagraphStyle

    from dynamic_pdf.layout.factory import Paragraph
    style = ParagraphStyle("b", fontName="Helvetica", fontSize=10, leading=13, alignment=TA_JUSTIFY,
                           hyphenationLang="en_GB", hyphenationMinWordLength=8)
    text = ("Salt is <b>known</b> in the Balkans since long ago and it stays so today. Salt was the best-known "
            "food preservative, especially for meat, and brine as a by-product of it.")

    def words(p):
        return " ".join(" ".join(getattr(w, "text", w) if not isinstance(w, str) else w for w in
                                 (ln.words if hasattr(ln, "words") else ln[1])) for ln in p.blPara.lines)
    def broken(kind):
        tried, lost = 0, 0
        for width in range(120, 420, 6):
            for kept in range(1, 6):
                p = kind(text, style)
                p.wrap(width, 1000)
                parts = p.split(width, 13 * kept + 1)
                if len(parts) == 2:
                    parts[1].wrap(width, 1000)
                    whole = (words(parts[0]) + " " + words(parts[1])).replace("- ", "-")
                    tried += 1
                    lost += "byproduct" in whole or "stknown" in whole or "bestknown" in whole
        return tried, lost
    tried, lost = broken(Paragraph)
    assert tried > 50 and lost == 0
    # the correction is this library's own: a host's ReportLab paragraphs behave as ReportLab made them
    from reportlab.platypus import Paragraph as Theirs
    assert broken(Theirs)[1] > 0


def test_cells_set_side_by_side_do_not_merge_a_western_number_with_an_arabic_indic_one():
    from dynamic_pdf.qa.content_preservation import _LATIN
    assert _LATIN.findall("99٨ and 2024") == ["99", "٨", "and", "2024"]


def test_the_dots_that_lead_a_contents_line_are_not_counted_as_words():
    from dynamic_pdf.intelligence.facts import read_pdf
    doc = pymupdf.open()
    doc.new_page(width=595, height=842).insert_text((72, 100), "Summary . . . . . . . . . . . . 4", fontsize=11)
    assert read_pdf(doc.tobytes()).pages[0].words == 2
