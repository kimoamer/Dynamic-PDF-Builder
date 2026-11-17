"""M10 content lint: each rule catches a planted defect, the fixture corpus raises nothing false."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from dynamic_pdf import DocumentBuilder
from dynamic_pdf.qa.lint import RULES

FIXTURES = Path(__file__).parent / "fixtures"
# The one warning the corpus raises is true: the Arabic sentence writes the year in
# Arabic-Indic digits (٢٠٢٧) and the amount in Western digits (12.5).
EXPECTED = {("bilingual.md", "mixed_digits")}


def rules_of(md):
    return [w.rule for w in DocumentBuilder.from_markdown(md).lint()]


@pytest.mark.parametrize("name", sorted(p.name for p in FIXTURES.glob("*.md")))
def test_fixture_corpus_raises_no_false_positive(name):
    got = {(name, r) for r in rules_of((FIXTURES / name).read_text(encoding="utf-8"))}
    assert got <= EXPECTED, got - EXPECTED


def test_lint_never_edits():
    md = (FIXTURES / "bilingual.md").read_text(encoding="utf-8")
    b = DocumentBuilder.from_markdown(md)
    before = b.build().model_dump_json()
    b.lint()
    assert b.build().model_dump_json() == before


PLANTED = {
    "total_mismatch": "# Costs\n\nText.\n\n| Item | Amount |\n|---|---|\n| Rent | 1,200 |\n| Staff | 3,400 |\n"
                      "| Total | 4,500 |\n",
    "percent_sum": "# Mix\n\nText.\n\n| Channel | Share of revenue |\n|---|---|\n| Online | 46% |\n| Stores | 38% |\n"
                   "| Partners | 12% |\n",
    "repeated_heading": "# Results\n\nText.\n\n## Sales\n\nText.\n\n## Sales\n\nMore text.\n",
    "unresolved_ref": "# Intro\n\nSee [the method](#method) and note[^9].\n",
    "mixed_digits": "# التقرير\n\nبلغت الإيرادات ١٢٫٥ مليون ريال في عام 2024.\n",
    "number_format": "# Data\n\nText.\n\n| Region | Revenue |\n|---|---|\n| North | 1,250,000 |\n| South | 980000 |\n"
                     "| East | 1500000 |\n",
    "date_format": "# Plan\n\nThe pilot starts on 2025-03-04 and ends on 31/05/2025.\n",
    "missing_alt_text": "# Site\n\nText.\n\n![](photo.png)\n",
    "empty_section": "# Overview\n\n# Details\n\nText.\n",
    "unresolved_citation": "# Method\n\nAs shown [@smith2024].\n",
    "formula_error": "# Costs\n\nText.\n\n| Item | Amount |\n|---|---|\n| Rent | 1,200 |\n| Twice | =A2*2 |\n",
}


@pytest.mark.parametrize("rule", RULES)
def test_each_rule_catches_its_planted_defect(rule):
    assert rule in rules_of(PLANTED[rule])


def test_correct_totals_subtotals_and_rounding_pass():
    md = ("# Budget\n\nText.\n\n| Item | Amount (EUR) | Share of total |\n|---|---|---|\n"
          "| Licences | 12,000 | 29.3% |\n| Support | 3,000 | 7.3% |\n| Subtotal software | 15,000 | 36.6% |\n"
          "| Consulting | 22,000 | 53.7% |\n| Training | 4,000 | 9.8% |\n| Subtotal services | 26,000 | 63.4% |\n"
          "| Grand total | 41,000 | 100% |\n")
    assert rules_of(md) == []


def test_arabic_total_and_arabic_indic_digits():
    md = ("# المبيعات\n\nنص.\n\n| المنطقة | المبيعات (ريال) |\n|---|---|\n| الرياض | ٥٬٤٠٠ |\n| جدة | ٣٬١٠٠ |\n"
          "| الإجمالي | ٩٬٥٠٠ |\n")
    assert rules_of(md) == ["total_mismatch"]
    assert rules_of(md.replace("٩٬٥٠٠", "٨٬٥٠٠")) == []


def test_growth_rates_are_not_shares():
    md = "# Growth\n\nText.\n\n| Region | YoY change |\n|---|---|\n| North | 46% |\n| South | 38% |\n| East | 12% |\n"
    assert "percent_sum" not in rules_of(md)


def test_row_breakdowns_that_miss_100_are_queried():
    md = ("# Survey\n\nText.\n\n| Question | Agree | Neutral | Disagree |\n|---|---|---|---|\n"
          "| Onboarding was clear | 72% | 18% | 10% |\n| I know who to ask | 65% | 20% | 15% |\n"
          "| Tools are adequate | 60% | 25% | 25% |\n")
    warnings = DocumentBuilder.from_markdown(md).lint()
    assert [w.rule for w in warnings] == ["percent_sum"] and "Tools are adequate" in warnings[0].message


def test_resolved_references_pass():
    md = "# Method\n\nText.[^1]\n\n# Intro\n\nSee [the method](#method).\n\n[^1]: A note.\n"
    assert "unresolved_ref" not in rules_of(md)


def test_pie_slices_that_miss_100():
    b = DocumentBuilder().heading("Mix").paragraph("Text.").chart("pie", {"A": 40, "B": 35, "C": 20})
    assert [w.rule for w in b.lint()] == ["percent_sum"]


def test_cli_lint_prints_and_strict_fails(tmp_path):
    src = tmp_path / "doc.md"
    src.write_text(PLANTED["total_mismatch"], encoding="utf-8")
    run = lambda *a: subprocess.run([sys.executable, "-m", "dynamic_pdf.cli", "lint", str(src), *a],
                                    capture_output=True, text=True)
    out = run()
    assert out.returncode == 0 and "[total_mismatch]" in out.stdout
    assert run("--strict").returncode == 1
    data = json.loads(run("--json").stdout)
    assert data[0]["rule"] == "total_mismatch" and data[0]["block"] == 2
