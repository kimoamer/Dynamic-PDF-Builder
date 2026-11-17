"""Computed table cells, amounts in words, and the tables as a workbook."""
import io
import sys

import pytest

from dynamic_pdf import DocumentBuilder
from dynamic_pdf.core.formulas import FormulaError, compute_table
from dynamic_pdf.core.words import amount_in_words
from dynamic_pdf.schema.blocks import TableBlock


@pytest.mark.parametrize("amount, words", [
    (1, "فقط ريال واحد لا غير"), (2, "فقط ريالان لا غير"), (3, "فقط ثلاثة ريالات لا غير"),
    (11, "فقط أحد عشر ريالاً لا غير"), (21, "فقط واحد وعشرون ريالاً لا غير"), (100, "فقط مائة ريال لا غير"),
    (200, "فقط مئتا ريال لا غير"), (2000, "فقط ألفا ريال لا غير"), (3000, "فقط ثلاثة آلاف ريال لا غير"),
    (11000, "فقط أحد عشر ألف ريال لا غير"), (200000, "فقط مئتا ألف ريال لا غير"),
    (0.01, "فقط هللة واحدة لا غير"), (0.13, "فقط ثلاث عشرة هللةً لا غير"),     # a feminine minor unit
    (1250.5, "فقط ألف ومئتان وخمسون ريالاً وخمسون هللةً لا غير"),
])
def test_arabic_amounts_count_their_noun_as_invoices_do(amount, words):
    assert amount_in_words(amount, "ar", "SAR") == words


def test_other_currencies_languages_and_plain_numbers():
    assert amount_in_words(12.345, "ar", "KWD") == "فقط اثنا عشر ديناراً وثلاثمائة وخمسة وأربعون فلساً لا غير"
    assert amount_in_words(1250.5, "en", "SAR") == "One thousand two hundred fifty riyals and fifty halalas only"
    assert amount_in_words(0.05, "en", "USD") == "Five cents only"
    assert amount_in_words(1.005, "en", "USD") == "One dollar and one cent only"     # half away from zero
    assert amount_in_words(15.75, "ar") == "خمسة عشر فاصلة خمسة وسبعون"
    with pytest.raises(ValueError, match="XYZ"):
        amount_in_words(1, "ar", "XYZ")


INVOICE = TableBlock(headers=["Item", "Qty", "Price", "Amount"], rows=[
    ["Paper", "3", "SAR 12.50", "=B2*C2"], ["Toner", "2", "SAR 1,310.00", "=B3*C3"],
    ["VAT", "", "15%", "=SUM(D2:D3)*C4"], ["Total", "", "", "=SUM(ABOVE)"], ["In words", "", "", "=WORDS(D5)"]])


def test_formulas_compute_in_decimals_and_write_as_the_column_does():
    rows = compute_table(INVOICE, "en").rows
    assert [r[3] for r in rows] == ["SAR 37.50", "SAR 2,620.00", "SAR 398.63", "SAR 3,056.13",
                                    "Three thousand fifty-six riyals and thirteen halalas only"]
    assert compute_table(TableBlock(headers=["x", "y"], rows=[["0.1", "0.2"], ["=A2+B2", ""]])).rows[1][0] == "0.3"


def test_arabic_digits_parentheses_percent_and_ratios_keep_their_look():
    ar = TableBlock(headers=["البند", "المبلغ"], rows=[["أ", "١٬٢٠٠٫٥٠"], ["ب", "٣٠٠٫٢٥"], ["المجموع", "=SUM(ABOVE)"]])
    assert compute_table(ar, "ar").rows[-1][1] == "١٬٥٠٠٫٧٥"
    neg = TableBlock(headers=["", "2024", "2025", "Change"], rows=[["Profit", "1,500", "(200)", "=C2-B2"], ["Cost", "(300)", "100", "=C3-B3"]])
    assert [r[3] for r in compute_table(neg).rows] == ["(1,700)", "400"]
    share = TableBlock(headers=["Region", "Sales", "Share"], rows=[["N", "400", "40.0%"], ["S", "600", "=B3/B4"]],
                       footer_row=["Total", "=SUM(ABOVE)", "=SUM(ABOVE)"])
    done = compute_table(share)
    assert done.rows[1][2] == "60.0%" and done.footer_row == ["Total", "1,000", "100.0%"]
    ratio = TableBlock(headers=["R", "Sales", "Share"], rows=[["N", "400", "=B2/B4"], ["S", "600", "=B3/B4"], ["T", "=SUM(B2:B3)", "=SUM(C2:C3)"]])
    assert [r[2] for r in compute_table(ratio).rows] == ["0.40", "0.60", "1.00"]


@pytest.mark.parametrize("formula, why", [("=B2+1", "refers back to itself"), ("=A2*2", "holds text"),
                                          ("=Z9", "outside the table"), ("=1/0", "division by zero"),
                                          ("=FOO(1)", "unknown function"), ("=WORDS(1)+1", "WORDS")])
def test_a_formula_that_cannot_be_computed_says_which_cell_and_why(formula, why):
    t = TableBlock(headers=["A", "B"], rows=[["label", formula]], caption="Costs")
    with pytest.raises(FormulaError, match=f"Costs.*B2.*{why}"):
        compute_table(t, strict=True)
    assert compute_table(t, strict=False).rows[0][1] == "#ERROR"


def test_the_document_shows_results_keeps_formulas_and_lint_reports_errors():
    b = DocumentBuilder().add_block(INVOICE)
    assert b.build().blocks[0].rows[0][3] == "SAR 37.50" and b._blocks[0].rows[0][3] == "=B2*C2"
    assert b.build().meta is b._meta
    pymupdf = pytest.importorskip("pymupdf")
    text = " ".join(pymupdf.open(stream=b.render(), filetype="pdf")[0].get_text().split())
    assert "SAR 3,056.13" in text and "=SUM" not in text
    for mode in ("permissive", "strict"):                   # lint reports it whatever the mode
        bad = DocumentBuilder().quality(mode).table(["A", "B"], [["x", "=A2*2"]])
        assert [w.rule for w in bad.lint()] == ["formula_error"]
    with pytest.raises(FormulaError):
        DocumentBuilder().table(["A", "B"], [["x", "=A2*2"]]).render()


def test_an_arabic_document_writes_amounts_in_arabic_words():
    b = DocumentBuilder().meta(language="ar").table(["البند", "المبلغ"], [["أ", "SAR 10.00"], ["كتابة", "=WORDS(B2)"]])
    assert b.build().blocks[0].rows[1][1] == "فقط عشرة ريالات لا غير"


def test_the_workbook_keeps_numbers_formats_and_working_formulas(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    b = DocumentBuilder().add_block(INVOICE)
    res = b.export(str(tmp_path / "t.xlsx"))
    ws = openpyxl.load_workbook(res.xlsx_path).active
    assert ws["C2"].value == 12.5 and ws["C2"].number_format == '"SAR "#,##0.00'
    assert ws["C4"].value == 0.15 and ws["C4"].number_format.endswith("%")
    assert ws["D2"].value == "=B2*C2" and ws["D5"].value == "=SUM(D2:D4)"      # ABOVE as the range it covers
    assert ws["D6"].value.startswith("Three thousand")                           # WORDS has no spreadsheet twin
    assert ws["A1"].font.bold and ws.freeze_panes == "A2"
    with pytest.raises(ValueError, match="no tables"):
        DocumentBuilder().paragraph("x").render_xlsx()


def test_the_cli_writes_a_workbook(tmp_path, monkeypatch):
    pytest.importorskip("openpyxl")
    from dynamic_pdf import cli
    src = tmp_path / "in.md"
    src.write_text("# Costs\n\n| Item | Cost |\n|---|---|\n| A | 10 |\n| B | 15 |\n| Total | =SUM(ABOVE) |\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["dynamic-pdf", "render", str(src), "-o", str(tmp_path / "out.xlsx")])
    cli.main()
    import openpyxl
    assert openpyxl.load_workbook(tmp_path / "out.xlsx").active["B4"].value == "=SUM(B2:B3)"


def test_templates_write_amounts_in_words():
    from dynamic_pdf.templates.engine import render_template
    out = render_template('{{ t | words("SAR") }} / {{ t | words("en", "USD") }}', {"t": 3})
    assert out == "فقط ثلاثة ريالات لا غير / Three dollars only"


def test_text_quotes_a_table_cell_and_follows_it():
    md = ("# Invoice\n\nThe total due is {=inv!B4}, in words {=inv!B5}. Unknown {=nope!A1}.\n\n"
          "| Item | Amount |\n|---|---|\n| Paper | SAR 37.50 |\n| Toner | SAR 2,620.00 |\n| Total | =SUM(ABOVE) |\n"
          "| In words | =WORDS(B4) |\n\nTable: Lines {#inv}\n")
    b = DocumentBuilder.from_markdown(md)
    assert b.build().blocks[1].text == ("The total due is SAR 2,657.50, in words Two thousand six hundred fifty-seven "
                                        "riyals and fifty halalas only. Unknown {=nope!A1}.")
    assert [w.rule for w in b.lint()] == ["unresolved_ref"]
