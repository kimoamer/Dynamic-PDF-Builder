"""M2: genuine, editable DOCX — real styles, lists, tables, fields, links."""
import io
import zipfile
import pytest
from docx.oxml.ns import qn
from dynamic_pdf import DocumentBuilder, AssetError, BlockRenderError
from dynamic_pdf.schema.blocks import ImageBlock
from conftest import open_docx, docx_text, fixture_text


def _xml(data: bytes, part="word/document.xml") -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return z.read(part).decode("utf-8")


def test_headings_use_real_word_styles_and_bookmarks():
    data = DocumentBuilder().heading("Intro").paragraph("Body").heading("Sub", level=2).render_docx()
    d = open_docx(data)
    styles = [(p.style.name, p.text) for p in d.paragraphs if p.text]
    assert ("Heading 1", "Intro") in styles
    assert ("Heading 2", "Sub") in styles
    assert ("Body Text", "Body") in styles
    xml = _xml(data)
    assert 'w:bookmarkStart' in xml and 'w:name="_intro"' in xml


def test_inline_runs_are_native_formatting_and_hyperlinks():
    data = DocumentBuilder().paragraph(
        "Plain **bold** *it* `code` ~~gone~~ x^2^ [site](https://example.com) [j](javascript:x)").render_docx()
    d = open_docx(data)
    p = [p for p in d.paragraphs if "Plain" in p.text][0]
    runs = {r.text: r for r in p.runs}
    assert runs["bold"].bold and runs["it"].italic and runs["gone"].font.strike
    assert runs["2"].font.superscript
    xml = _xml(data)
    assert "<w:hyperlink" in xml
    rels = _xml(data, "word/_rels/document.xml.rels")
    assert "https://example.com" in rels and "javascript" not in rels


def test_nested_lists_use_numbering_and_restart():
    md = "1. one\n2. two\n   - sub\n\ntext\n\n5. five\n6. six\n"
    data = DocumentBuilder.from_markdown(md).render_docx()
    xml = _xml(data)
    num = _xml(data, "word/numbering.xml")
    assert xml.count("<w:numPr>") == 5
    assert '<w:ilvl w:val="1"/>' in xml                       # nested level
    assert 'w:startOverride w:val="5"' in num                # second list starts at 5
    assert 'w:startOverride w:val="1"' in num
    text = docx_text(data)
    for w in ("one", "two", "sub", "five", "six"):
        assert w in text


def test_tables_have_repeating_header_and_numeric_alignment():
    data = DocumentBuilder().table(["Name", "Amount"], [["a", "1,200"], ["b", "3"]],
                                   caption="Totals").render_docx()
    d = open_docx(data)
    t = d.tables[0]
    assert [c.text for c in t.rows[0].cells] == ["Name", "Amount"]
    assert t.rows[0]._tr.trPr.find(qn("w:tblHeader")) is not None
    assert t.rows[1].cells[1].paragraphs[0].alignment == 2      # RIGHT
    assert any(p.style.name == "Caption" and "Totals" in p.text for p in d.paragraphs)


def test_header_footer_page_fields_and_metadata():
    data = (DocumentBuilder().meta(title="Report T", author="Ops", keywords=["k1"])
            .design("executive_report").heading("A").paragraph("b").render_docx())
    d = open_docx(data)
    assert d.core_properties.title == "Report T" and d.core_properties.author == "Ops"
    footer = _xml(data, "word/footer1.xml") if "word/footer1.xml" in zipfile.ZipFile(io.BytesIO(data)).namelist() else ""
    allxml = "".join(zipfile.ZipFile(io.BytesIO(data)).read(n).decode("utf-8", "ignore")
                     for n in zipfile.ZipFile(io.BytesIO(data)).namelist() if n.startswith("word/footer"))
    assert " PAGE " in allxml and " NUMPAGES " in allxml


def test_toc_is_a_real_field_with_links():
    b = DocumentBuilder().table_of_contents()
    for i in range(3):
        b.heading(f"Part {i}").paragraph("x")
    data = b.render_docx()
    xml = _xml(data)
    assert 'TOC \\o "1-3" \\h \\z \\u' in xml
    assert xml.count('w:anchor="_part-') == 0 and xml.count('w:anchor="_part_') == 3
    assert "w:updateFields" in _xml(data, "word/settings.xml")


def test_visual_blocks_embed_images_with_alt_text(png_path):
    data = (DocumentBuilder().chart("bar", data={"Q1": 1, "Q2": 2}, title="Sales")
            .math("E = mc^2").image(png_path, caption="Cap", alt_text="red box").render_docx())
    xml = _xml(data)
    assert xml.count("<pic:pic") == 3
    assert 'descr="bar chart: Sales. Data: Q1: 1; Q2: 2"' in xml
    assert 'descr="Equation: E = mc^2"' in xml
    assert 'descr="red box"' in xml


def test_docx_error_policy_matches_pdf():
    b = DocumentBuilder().paragraph("ok").add_block(ImageBlock(src="/missing.png"))
    with pytest.raises((AssetError, BlockRenderError)):
        b.render_docx()
    b = DocumentBuilder().quality("permissive").paragraph("ok").add_block(ImageBlock(src="/missing.png"))
    data = b.render_docx()
    assert "Block Error (image)" in docx_text(data)
    assert b.last_docx_diagnostics.status == "degraded"


def test_export_both(tmp_path):
    res = DocumentBuilder.from_markdown(fixture_text("proposal.md")).design().export_both(str(tmp_path))
    assert res.pdf_path.endswith(".pdf") and res.docx_path.endswith(".docx")
    assert open(res.pdf_path, "rb").read(4) == b"%PDF"
    assert zipfile.is_zipfile(res.docx_path)
    # exported without QA: neither format was inspected, so nothing is reported "ok"
    assert res.profile == "proposal" and res.status == "unverified"
    assert any(x.startswith("docx not verified") for x in res.status_reasons)


def test_export_rejects_unknown_format(tmp_path):
    with pytest.raises(ValueError):
        DocumentBuilder().paragraph("x").export(str(tmp_path / "x.odt"))


def test_cli_docx_and_both(tmp_path):
    import subprocess, sys
    src = tmp_path / "in.md"
    src.write_text(fixture_text("executive.md"), encoding="utf-8")
    r = subprocess.run([sys.executable, "-m", "dynamic_pdf.cli", "render", str(src),
                        "-o", str(tmp_path / "o.docx"), "--design", "auto"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert zipfile.is_zipfile(tmp_path / "o.docx")
    r = subprocess.run([sys.executable, "-m", "dynamic_pdf.cli", "render", str(src), "-f", "both"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "in.pdf").exists() and (tmp_path / "in.docx").exists()
