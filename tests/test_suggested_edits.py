"""Suggested edits and comments (CriticMarkup): Word tracked changes and comments, a review copy in the PDF."""
import io
import zipfile

import pytest
from lxml import etree

from dynamic_pdf import DocumentBuilder
from dynamic_pdf.core.content_ledger import build_content_ledger
from dynamic_pdf.core.inline import parse_inline, plain_text
from dynamic_pdf.qa.content_preservation import VERIFIED, check_preservation

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
TEXT = ("Revenue {~~fell~>rose~~} by **12%**{>>source: Q3 ledger<<}. The board {--may--} {++will++} approve "
        "the {==capital budget==}{>>confirm with finance<<} in December.")
MD = f"---\ntitle: Note\nreviewer: Policy AI\n---\n# Summary\n\n{TEXT}\n"


def test_the_markup_marks_runs_and_a_comment_is_not_part_of_the_text():
    runs = {r.text: r for r in parse_inline(TEXT)}
    assert runs["fell"].deleted and runs["rose"].inserted and runs["may"].deleted and runs["will"].inserted
    assert runs["capital budget"].comment == "confirm with finance"
    assert runs["12%"].comment == "source: Q3 ledger" and runs["12%"].bold          # a lone comment takes the word before it
    assert "finance" not in plain_text(TEXT) and "fellrose" in plain_text(TEXT)
    assert [r.text for r in parse_inline("a {b} c, {ref:x} and ~~gone~~")] == ["a {b} c, {ref:x} and ", "gone"]


def word(b):
    with zipfile.ZipFile(io.BytesIO(b.render_docx())) as z:
        return etree.fromstring(z.read("word/document.xml")), etree.fromstring(z.read("word/comments.xml"))


def test_word_gets_tracked_changes_and_comments_by_the_reviewer():
    body, comments = word(DocumentBuilder.from_markdown(MD))
    ins = ["".join(e.itertext()) for e in body.iter(W + "ins")]
    dele = ["".join(t.text for t in e.iter(W + "delText")) for e in body.iter(W + "del")]
    assert ins == ["rose", "will"] and dele == ["fell", "may"]
    assert {e.get(W + "author") for e in body.iter(W + "ins", W + "del")} == {"Policy AI"}
    notes = {c.get(W + "id"): "".join(c.itertext()) for c in comments.iter(W + "comment")}
    assert sorted(notes.values()) == ["confirm with finance", "source: Q3 ledger"]
    assert {c.get(W + "author") for c in comments.iter(W + "comment")} == {"Policy AI"}
    anchored, inside = {}, None                 # the text each comment is anchored on
    for e in body.iter(W + "commentRangeStart", W + "commentRangeEnd", W + "t"):
        if e.tag == W + "commentRangeStart":
            inside = e.get(W + "id")
            anchored[inside] = ""
        elif e.tag == W + "commentRangeEnd":
            inside = None
        elif inside:
            anchored[inside] += e.text or ""
    assert {notes[k]: v for k, v in anchored.items()} == {"source: Q3 ledger": "12%", "confirm with finance": "capital budget"}


def body_of(b):
    with zipfile.ZipFile(io.BytesIO(b.render_docx())) as z:
        return etree.fromstring(z.read("word/document.xml"))


def test_without_a_reviewer_the_changes_are_signed_reviewer():
    body = body_of(DocumentBuilder().paragraph("A {++new++} word."))
    assert [e.get(W + "author") for e in body.iter(W + "ins")] == ["Reviewer"]
    assert DocumentBuilder().meta(reviewer="Ada").paragraph("x {--y--}").build().meta.reviewer == "Ada"


def test_the_pdf_is_a_review_copy_and_nothing_is_lost_in_either_format():
    pymupdf = pytest.importorskip("pymupdf")
    b = DocumentBuilder.from_markdown(MD)
    pdf, docx = b.render(), b.render_docx()
    text = " ".join(pymupdf.open(stream=pdf, filetype="pdf")[0].get_text().split())
    assert "fellrose" in text and "may will" in text and "[confirm with finance]" in text
    designed, _ = b._prepared()
    report = check_preservation(build_content_ledger(designed), pdf=pdf, docx=docx)
    assert report.status == VERIFIED, report.to_dict()


def test_text_without_markup_is_written_as_before():
    body = body_of(DocumentBuilder().paragraph("Revenue rose by 12% {not markup}."))
    assert not list(body.iter(W + "ins", W + "del", W + "commentRangeStart"))
