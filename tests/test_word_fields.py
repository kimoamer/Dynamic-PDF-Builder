"""Caption numbers, references and lists of tables and figures are Word fields, so they update in Word."""
import io
import re
import zipfile

import pytest
from lxml import etree

from dynamic_pdf import DocumentBuilder
from dynamic_pdf.schema.blocks import TableBlock

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


@pytest.fixture
def photo(tmp_path):
    from PIL import Image
    path = tmp_path / "map.png"
    Image.new("RGB", (400, 240), (40, 90, 160)).save(path)
    return str(path)


def body(data):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return etree.fromstring(z.read("word/document.xml"))


def fields(root):
    """(instruction, shown text) of every complex field, in document order."""
    out, instr, shown, state = [], "", "", None
    for e in root.iter(W + "fldChar", W + "instrText", W + "t"):
        if e.tag == W + "fldChar":
            kind = e.get(W + "fldCharType")
            if kind == "begin":
                instr, shown, state = "", "", "instr"
            elif kind == "separate":
                state = "shown"
            elif kind == "end" and state:
                out.append((instr.strip(), shown))
                state = None
        elif e.tag == W + "instrText" and state == "instr":
            instr += e.text or ""
        elif e.tag == W + "t" and state == "shown":
            shown += e.text or ""
    return out


def bookmarked(root, name):
    """The text a bookmark holds: what a REF field to it shows."""
    start = next(e for e in root.iter(W + "bookmarkStart") if e.get(W + "name") == name)
    inside, text = False, ""
    for e in root.iter():
        if e is start:
            inside = True
        elif inside and e.tag == W + "bookmarkEnd" and e.get(W + "id") == start.get(W + "id"):
            return text
        elif inside and e.tag == W + "t":
            text += e.text or ""


def test_captions_references_and_lists_are_fields_that_show_the_right_text(photo):
    from test_m10_references import doc_md
    root = body(DocumentBuilder.from_markdown(doc_md(photo)).design().render_docx())
    found = fields(root)
    assert ("SEQ Table \\* ARABIC", "1") in found and ("SEQ Table \\* ARABIC", "2") in found
    assert ("SEQ Figure \\* ARABIC", "1") in found
    assert ("REF _tab_sales \\h", "Table 1") in found and ("REF _fig_map \\h", "Figure 1") in found
    assert bookmarked(root, "_tab_sales") == "Table 1" and bookmarked(root, "_fig_map") == "Figure 1"
    assert {i for i, _ in found if i.startswith("TOC")} == {'TOC \\h \\z \\c "Table"', 'TOC \\h \\z \\c "Figure"'}


def test_when_word_recounts_the_fields_it_gets_the_numbers_already_written():
    b = DocumentBuilder()
    b.add_block(TableBlock(headers=["A"], rows=[["1"]], caption="Set by the author", table_number=4))
    b.add_block(TableBlock(headers=["A"], rows=[["1"]], caption="Numbered by the library", id="second"))
    b.paragraph("See {ref:second}.")                 # a reference turns numbering on
    root = body(b.render_docx())
    count = 0
    for instr, shown in fields(root):
        if instr.startswith("SEQ Table"):
            restart = re.search(r"\\r (\d+)", instr)
            count = int(restart.group(1)) if restart else count + 1
            assert str(count) == shown, (instr, shown)
    assert count, "no SEQ field was written"


def test_a_document_without_numbering_has_no_number_fields():
    data = DocumentBuilder().add_block(TableBlock(headers=["A"], rows=[["1"]], caption="Plain")).render_docx()
    assert not [i for i, _ in fields(body(data)) if i.startswith(("SEQ", "REF"))]
