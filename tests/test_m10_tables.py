"""M10 typed tables: each column's role, unit and precision, the table's orientation and its total rows."""
import io
import json
from pathlib import Path

import pytest

from dynamic_pdf import DocumentBuilder
from dynamic_pdf.core.table_types import FIGURES, infer_table, read_cell

DATA = json.loads((Path(__file__).parent / "data" / "table_roles.json").read_text(encoding="utf-8"))["tables"]
FIXTURES = Path(__file__).parent / "fixtures"


def test_labelled_set_is_large_and_bilingual():
    assert len(DATA) >= 60
    langs = {t["lang"] for t in DATA}
    assert {"en", "ar", "bilingual"} <= langs
    assert sum(t["source"].startswith("tests/fixtures") for t in DATA) >= 5


def test_column_roles_are_at_least_95_percent_correct():
    right = total = 0
    wrong = []
    for t in DATA:
        got = infer_table(t["headers"], t["rows"]).roles
        for i, (g, want) in enumerate(zip(got, t["roles"])):
            total += 1
            right += g == want
            if g != want:
                wrong.append((t["id"], t["headers"][i], g, want))
    assert right / total >= 0.95, wrong


def test_no_period_column_is_treated_as_a_measure():
    for t in DATA:
        types = infer_table(t["headers"], t["rows"])
        for i, want in enumerate(t["roles"]):
            if want == "period":
                assert types.columns[i].role not in FIGURES, (t["id"], t["headers"][i])
                assert i not in types.numeric_cols


def test_orientation_current_period_and_totals_match_the_labels():
    misses = []
    for t in DATA:
        types = infer_table(t["headers"], t["rows"])
        if (types.orientation, types.current_col, types.total_rows, types.subtotal_rows) != (
                t["orientation"], t["current_col"], t["total_rows"], t["subtotal_rows"]):
            misses.append(t["id"])
    assert len(misses) <= len(DATA) * 0.05, misses


def test_units_and_precision():
    types = infer_table(["Division", "Revenue (£m)", "Margin (%)", "Weight (kg)"],
                        [["A", "412.0", "18.25", "3"], ["B", "268.5", "22.9", "4"]])
    assert [c.role for c in types.columns] == ["category", "currency", "percent", "measure"]
    assert types.columns[1].unit == "£m" and types.columns[1].precision == 1
    assert types.columns[2].precision == 2
    assert types.columns[3].unit == "kg"


def test_arabic_indic_digits_and_arabic_totals():
    types = infer_table(["المنطقة", "المبيعات (ريال)", "النمو"],
                        [["الرياض", "٥٬٤٠٠", "١٢٪"], ["جدة", "٣٬١٠٠", "٨٫٥٪"], ["الإجمالي", "٨٬٥٠٠", "١٠٪"]])
    assert types.roles == ["category", "currency", "percent"]
    assert types.total_rows == [2]
    assert types.columns[2].precision == 1
    cell = read_cell("(٢٬١٠٥)")
    assert cell.kind == "number" and cell.value == -2105


def test_latest_actual_period_is_current_not_the_first_figure_column():
    t = infer_table(["Segment", "2022", "2023", "2024", "2025E"], [["Retail", "1", "2", "3", "4"]])
    assert t.orientation == "periods_in_columns" and t.current_col == 3


def _designed(md):
    b = DocumentBuilder.from_markdown(md).design()
    doc, _ = b._prepared()
    return b, [x for x in doc.blocks if x.type == "table"]


def test_fiscal_year_column_is_not_right_aligned_or_tinted():
    md = (FIXTURES / "financial.md").read_text(encoding="utf-8")
    b, tables = _designed(md)
    hints = tables[0].hints
    assert 0 not in hints["numeric_cols"] and hints["column_roles"][0] == "period"
    assert "current_period_col" not in hints
    # the ledger direction tints the current period only when periods run across the columns
    from dynamic_pdf.design.art_direction import direct
    from dynamic_pdf.design.directions import DIRECTIONS
    d = direct(b.semantic(), DIRECTIONS["financial_data"])
    table = next(x for x in d.document.blocks if x.type == "table")
    assert table.hints.get("design") == "ledger" and table.hints.get("current_col") is None


def test_ledger_tints_the_latest_period_column():
    md = ("---\ntitle: Results\n---\n# Results\n\nFigures for three years.\n\n"
          "| Line item | 2022 | 2023 | 2024 |\n|---|---|---|---|\n| Revenue | 10 | 11 | 12 |\n"
          "| Costs | 6 | 7 | 7 |\n| Total | 16 | 18 | 19 |\n")
    b = DocumentBuilder.from_markdown(md)
    from dynamic_pdf.design.art_direction import direct
    from dynamic_pdf.design.directions import DIRECTIONS
    d = direct(b.semantic(), DIRECTIONS["financial_data"])
    table = next(x for x in d.document.blocks if x.type == "table")
    assert table.hints["current_col"] == 3
    assert table.hints["total_rows"] == [2]


def test_total_rows_are_bold_and_ruled_in_docx():
    import docx
    md = ("# Costs\n\n| Item | Amount |\n|---|---|\n| Rent | 10 |\n| Staff | 20 |\n| Total | 30 |\n")
    b = DocumentBuilder.from_markdown(md).design()
    d = docx.Document(io.BytesIO(b.render_docx()))
    rows = d.tables[0].rows
    assert all(r.bold for r in rows[3].cells[0].paragraphs[0].runs)
    assert not any(r.bold for r in rows[1].cells[0].paragraphs[0].runs)
    assert "w:top" in rows[3].cells[0]._tc.xml
    assert b.render()[:4] == b"%PDF"


def test_prose_tables_wrap_instead_of_turning_the_page():
    long = "a sentence long enough to wrap in a narrow column of a portrait page without trouble " * 2
    md = "# Notes\n\n| A | B | C | D | E |\n|---|---|---|---|---|\n" + "".join(
        f"| {long} | {long} | {long} | {long} | {long} |\n" for _ in range(3))
    _, tables = _designed(md)
    assert not tables[0].hints.get("landscape")


def test_inline_code_is_measured_in_the_monospace_face():
    from dynamic_pdf.design.measure import column_metrics
    plain, _ = column_metrics(["Code"], [["invalid_request_token"]], "Helvetica", 9)
    code, _ = column_metrics(["Code"], [["`invalid_request_token`"]], "Helvetica", 9)
    assert code[0] > plain[0] + 10
