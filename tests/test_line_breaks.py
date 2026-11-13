"""Newlines mean what Markdown says, the same in PDF and DOCX.

A single newline inside a paragraph is a soft break (an editor wrapped the text): a space.
Two trailing spaces or a backslash make a hard break, and a blank line inside one block
separates its paragraphs: both start a new line. A paragraph of ``Label: value`` lines keeps
its lines."""
import io
import zipfile

import pymupdf
import pytest

from dynamic_pdf import DocumentBuilder
from dynamic_pdf.core.inline import parse_inline
from dynamic_pdf.markdown.parser import markdown_to_blocks

WRAPPED = ("This paragraph was written in an editor that wraps\nlines at about fifty characters, as many "
           "Markdown\nfiles are, and each newline is only a soft break.")
MEMO = "To: All staff\nFrom: Operations\nSubject: Office relocation on 1 December"


def _xml(data: bytes, part: str = "word/document.xml") -> str:
    return zipfile.ZipFile(io.BytesIO(data)).read(part).decode()


def _pdf_lines(data: bytes, needle: str):
    page = pymupdf.open(stream=data, filetype="pdf")[0]
    return ["".join(s["text"] for s in ln["spans"]) for b in page.get_text("dict")["blocks"]
            for ln in b.get("lines", []) if needle in "".join(s["text"] for s in ln["spans"])]


@pytest.mark.parametrize("text, runs", [
    ("wrapped\nlines", [("wrapped lines", False)]),
    ("hard  \nbreak", [("hard", False), ("\n", True), ("break", False)]),
    ("back\\\nslash", [("back", False), ("\n", True), ("slash", False)]),
    ("one\n\ntwo", [("one", False), ("\n", True), ("two", False)]),
])
def test_inline_runs_follow_markdown_breaks(text, runs):
    assert [(r.text, r.line_break) for r in parse_inline(text)] == runs


def test_emphasis_may_cross_a_wrapped_line():
    assert [(r.text, r.bold) for r in parse_inline("**bold\nacross** line") if r.text.strip()] == [
        ("bold", True), ("across", True), (" line", False)]


def test_wrapped_markdown_is_one_flowing_paragraph_in_both_formats():
    b = DocumentBuilder.from_markdown("# Notes\n\n" + WRAPPED + "\n").design()
    assert "<w:br/>" not in _xml(b.render_docx())
    lines = _pdf_lines(b.render(), "")
    assert any("wraps lines" in ln for ln in lines)          # the soft break joined the words


def test_hard_break_starts_a_new_line_in_both_formats():
    b = DocumentBuilder.from_markdown("# Notes\n\nA hard break ends here  \nand this starts a new line.\n").design()
    assert _xml(b.render_docx()).count("<w:br/>") == 1
    pdf = b.render()
    assert _pdf_lines(pdf, "ends here") == ["A hard break ends here"]
    assert _pdf_lines(pdf, "starts a new") == ["and this starts a new line."]


def test_field_lines_keep_one_pair_per_line():
    para = markdown_to_blocks(MEMO + "\n\nBody text.\n")[0]
    assert para.type == "paragraph" and para.text.count("\\\n") == 2
    b = DocumentBuilder.from_markdown("---\ntitle: Memo\n---\n" + MEMO + "\n\nBody text.\n").design()
    assert b.design_explain()["profile"] == "corporate_memo"
    assert _xml(b.render_docx()).count("<w:br/>") == 2
    pdf = b.render()
    for line in MEMO.split("\n"):
        assert _pdf_lines(pdf, line.split(":")[0] + ":") == [line]


def test_ordinary_lines_with_a_colon_stay_prose():
    para = markdown_to_blocks("Note: this sentence wraps\nonto a second line without a label.\n")[0]
    assert "\\\n" not in para.text


def test_quote_paragraphs_stay_separate():
    quote = markdown_to_blocks("> First paragraph\n> wraps here.\n>\n> Second paragraph.\n")[0]
    runs = [(r.text, r.line_break) for r in parse_inline(quote.text)]
    assert runs == [("First paragraph wraps here.", False), ("\n", True), ("Second paragraph.", False)]


def test_word_does_not_stretch_lines_that_end_in_a_manual_break():
    settings = _xml(DocumentBuilder().paragraph("x").render_docx(), "word/settings.xml")
    assert "<w:doNotExpandShiftReturn/>" in settings
