"""Two versions of a document compared, as suggested edits: tracked changes in Word, a review copy in PDF."""
import io
import sys
import zipfile

import pytest

from dynamic_pdf import DocumentBuilder
from dynamic_pdf.core.compare import words

OLD = """# Summary

Revenue fell by 12% in the third quarter.

- Hire two engineers
- Open the Riyadh office

| Item | Amount |
|---|---|
| Rent | 1,200 |
| Staff | 3,400 |
| Total | =SUM(ABOVE) |

A paragraph that was removed.
"""
NEW = """# Summary

Revenue rose by 14% in the third quarter of 2025.

- Hire three engineers
- Open the Riyadh office
- Close the old warehouse

| Item | Amount |
|---|---|
| Rent | 1,200 |
| Staff | 3,900 |
| Travel | 300 |
| Total | =SUM(ABOVE) |
"""


def test_words_marks_what_differs_and_keeps_the_rest():
    assert words("Revenue fell by 12% in Q3.", "Revenue rose by 14% in Q3 of 2025.") == \
        "Revenue {~~fell~>rose~~} by {~~12%~>14%~~} in Q3 {++of 2025++}."
    assert words("same text", "same text") == "same text"
    assert words("a b c", "a c") == "a {--b--} c"


def test_paragraphs_lists_tables_and_removed_blocks_are_marked():
    blocks = DocumentBuilder.from_markdown(NEW).compared_with(OLD).build().blocks
    texts = {b.type: b for b in reversed(blocks)}                     # the first block of each kind
    assert texts["paragraph"].text == "Revenue {~~fell~>rose~~} by {~~12%~>14%~~} in the third quarter {++of 2025++}."
    items = [i if isinstance(i, str) else i.text for i in texts["bullet_list"].items]
    assert items == ["Hire {~~two~>three~~} engineers", "Open the Riyadh office", "{++Close the old warehouse++}"]
    rows = texts["table"].rows
    assert rows[1] == ["Staff", "{~~3,400~>3,900~~}"] and rows[2] == ["{++Travel++}", "{++300++}"]
    assert rows[3] == ["Total", "{~~4,600~>5,400~~}"]                 # formulas are compared by what they show
    assert blocks[-1].type == "paragraph" and blocks[-1].text == "{--A paragraph that was removed.--}"


def test_word_gets_tracked_changes_signed_by_the_reviewer(tmp_path):
    out = DocumentBuilder.from_markdown(NEW).compared_with(OLD, reviewer="Finance").export(str(tmp_path / "c.docx"))
    xml = zipfile.ZipFile(out.docx_path).read("word/document.xml").decode()
    assert xml.count("<w:ins ") >= 6 and xml.count("<w:del ") >= 4 and 'w:author="Finance"' in xml


def test_identical_versions_have_nothing_marked():
    blocks = DocumentBuilder.from_markdown(NEW).compared_with(NEW).build().blocks
    assert "{++" not in repr([b.model_dump() for b in blocks]) and "{--" not in repr([b.model_dump() for b in blocks])


def test_the_cli_compares_two_files(tmp_path, monkeypatch, capsys):
    from dynamic_pdf import cli
    (tmp_path / "old.md").write_text(OLD, encoding="utf-8")
    (tmp_path / "new.md").write_text(NEW, encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["dynamic-pdf", "compare", str(tmp_path / "old.md"), str(tmp_path / "new.md"),
                                      "-o", str(tmp_path / "changes.docx")])
    cli.main()
    assert "changes:" in capsys.readouterr().out and (tmp_path / "changes.docx").is_file()
