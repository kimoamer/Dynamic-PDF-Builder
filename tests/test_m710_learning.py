"""M7.10: measured layout facts, the blind pairing, and the readiness report. Nothing here trains."""
import importlib.util
import json
import random

import pytest

from dynamic_pdf import DocumentBuilder
from tools.design_learning import preferences as P
from tools.design_learning.layout_facts import measure
from tools.design_learning.readiness import report, usable

AR = "أُعيد افتتاح الرصيف الشمالي في مارس بعد عامين من العمل على بوابات الفيضان."


def row(n, preferred="A", confidence="medium", repeat=False, document="doc_a", a="x", b="x@plain", model="claude-opus-5-5"):
    return {"format": P.FORMAT, "comparison": f"cmp-{n}", "batch": "t", "document": document, "document_hash": document,
            "a": {"candidate": a, "pdf_sha256": a, "docx_sha256": a}, "b": {"candidate": b, "pdf_sha256": b, "docx_sha256": b},
            "preferred": preferred, "confidence": confidence, "reversed_repeat": repeat, "reviewer_type": "ai", "model": model,
            "review_date": "2026-11-05", "evaluation_method": "blind", "formats_inspected": ["pdf"], "pages_shown": [2, 2],
            "pages_total": [2, 2], "shown_px": 240}


def test_facts_are_measurements_of_the_pdf():
    b = DocumentBuilder()
    b.heading("A heading", 1)
    b.paragraph("Plain text. " * 40)
    facts = measure(b.render(), plain_pages=1)
    assert facts["pages"] == 1 and facts["page_growth"] == 1.0
    assert facts["body_size"] > 0 and facts["arabic_line_share"] == 0
    assert all(isinstance(v, (int, float)) for v in facts.values())


def test_facts_see_arabic_at_the_right_edge():
    b = DocumentBuilder()
    for _ in range(4):
        b.paragraph(AR)
    facts = measure(b.render())
    assert facts["arabic_line_share"] > 0.5 and facts["arabic_right_edge_share"] > 0.5


def test_facts_see_two_languages_on_one_line():
    b = DocumentBuilder().paired_row_columns([{"first": "The north quay reopened in March.", "second": AR}] * 3)
    assert measure(b.render())["both_scripts_side_by_side"] > 0


def test_a_design_meets_its_own_baseline_first():
    rows = [{"candidate": c, "design": c.split("@")[0]} for c in ("x", "x@plain", "y", "y@plain")]
    chosen = P._choose(rows, 2, random.Random(1))
    assert chosen[0][0]["design"] == chosen[0][1]["design"]
    assert chosen[1][0]["design"] != chosen[1][1]["design"]


def test_usable_drops_ties_low_confidence_repeats_and_contradictions():
    rows = [row(1), row(2, "tie", a="p", b="q"), row(3, confidence="low", a="r", b="s"), row(4, repeat=True),
            row(5, "A", a="u", b="v"), row(6, "B", a="v", b="u", repeat=True), row(7, "A", a="k", b="m"), row(8, "A", a="m", b="k", repeat=True)]
    assert [r["comparison"] for r in usable(rows, set())] == ["cmp-1", "cmp-5"]


def test_usable_keeps_a_design_out_when_it_was_found_defective():
    assert usable([row(1)], {("t", "doc_a", "x")}) == []


@pytest.fixture
def world(tmp_path):
    batch = tmp_path / "batches" / "t"
    batch.mkdir(parents=True)
    with open(batch / "candidates.jsonl", "w", encoding="utf-8") as f:
        for doc in ("doc_a", "doc_b"):
            for c in ("x", "x@plain"):
                f.write(json.dumps({"document": doc, "candidate": c, "pdf_sha256": c, "layout_facts": {"pages": 2}}) + "\n")
    split = tmp_path / "split.json"
    split.write_text(json.dumps({"families": {"f": ["doc_a"], "g": ["doc_b"]}, "evaluation_families": ["g"]}), encoding="utf-8")
    data = tmp_path / "data.jsonl"
    data.write_text("\n".join(json.dumps(r) for r in (row(1), row(2, "B", document="doc_b"))) + "\n", encoding="utf-8")
    return str(data), str(tmp_path / "batches"), str(split)


def test_readiness_refuses_below_the_gate_and_says_why(world, tmp_path):
    out = tmp_path / "out"
    r = report(*world, str(out))
    assert r["verdict"] == "not ready" and r["usable"] == 2
    assert r["train_usable"] == 1 and r["held_out_usable"] == 1
    assert any("gate of 200" in w for w in r["weaknesses"])
    assert (out / "dataset-readiness.md").exists()


def test_readiness_counts_the_grammar_against_its_own_baseline(world):
    base = report(*world)["signals"]["grammar_against_own_baseline"]
    assert base == {"comparisons": 2, "grammar_won": 1}


def test_readiness_flags_a_row_with_no_matching_render(world):
    data, batches, split = world
    with open(data, "a", encoding="utf-8") as f:
        f.write(json.dumps(row(3, a="ghost", b="x")) + "\n")
    assert "cmp-3" in report(data, batches, split)["provenance"]["rows_not_matching_a_render"]


def test_readiness_finds_no_leak_across_families(world):
    assert report(*world)["leakage"]["documents_in_both"] == []


def test_the_trainer_and_the_report_count_the_same_rows():
    spec = importlib.util.spec_from_file_location("trainer", "scripts/train_variant_ranker.py")
    trainer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(trainer)
    first, second = row(1, "A", a="p", b="q"), dict(row(2, "B", a="p", b="q"), batch="u")     # two batches may disagree
    assert trainer.usable([first, second]) == usable([first, second], set()) == [first, second]
