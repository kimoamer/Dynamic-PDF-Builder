"""The committed AI art-direction records: complete, transparent, and never human decisions."""
import copy
import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from tools.reference_analyzer import ai_curation, curation  # noqa: E402

FOLDER = os.path.join(ROOT, "tools", "reference_analyzer")


@pytest.fixture(scope="module")
def records():
    return ai_curation.load(FOLDER)


def test_committed_records_are_valid(records):
    assert ai_curation.validate(records["curation"], records["archetypes"]) == []


def test_every_corpus_page_is_accounted_for(records):
    cov = records["curation"]["review_coverage"]
    assert cov["pages_viewed"] + cov["unreviewed_count"] == records["curation"]["corpus"]["pages"] == 1064
    assert sum(d["pages"] for d in cov["by_document"]) == 1064
    assert cov["full_size"] <= cov["enlarged_or_better"]
    assert cov["enlarged_or_better"] + cov["contact_sheet_only"] == cov["pages_viewed"]


def test_both_unilever_reports_were_reviewed_independently(records):
    docs = {d["document"]: d for d in records["curation"]["review_coverage"]["by_document"]}
    assert {"EN-01", "EN-01-1"} <= set(docs)
    assert docs["EN-01"]["document_sha256"] != docs["EN-01-1"]["document_sha256"]


def test_selection_spans_the_requested_kinds_of_page(records):
    kinds = {p["visual_category"] for p in records["curation"]["selected"]}
    assert {"cover_title", "section_opener", "editorial_spread", "financial_table", "infographic", "kpi_page"} <= kinds
    assert any(k.startswith("bilingual") for k in kinds)


def test_archetypes_cite_selected_pages_and_keep_a_fallback(records):
    for a in records["archetypes"]["archetypes"]:
        assert a["reference_pages"], a["id"]
        assert a["constraints_fallback"], a["id"]
        assert a["rtl_bilingual"], a["id"]


@pytest.mark.parametrize("change, expected", [
    (lambda c, a: c["status"].update(human_approved=True), "human-approved"),
    (lambda c, a: a["status"].update(human_review="approved"), "human-approved"),
    (lambda c, a: c["reviewer"].update(kind="human"), "AI model"),
    (lambda c, a: c.update(selected=c["selected"][:29]), "pages selected"),
    (lambda c, a: c["selected"][0]["scores"]["reusability"].update(score=6), "score from 1 to 5"),
    (lambda c, a: c["selected"][0]["scores"]["composition_grid"].update(justification=""), "justification"),
    (lambda c, a: c["selected"][0].update(limitations=""), "missing limitations"),
    (lambda c, a: c["selected"][0].update(mean_score=1.0), "mean_score"),
    (lambda c, a: c["review_coverage"].update(pages_viewed=10), "add up"),
    (lambda c, a: c["selected"][0].update(selection_rationale="see preview/AR01_p5.jpg"), "page images"),
    (lambda c, a: a["archetypes"][0]["reference_pages"].append({"label": "X", "page_id": "000000000000:p0001"}),
     "not a selected page"),
    (lambda c, a: a["archetypes"][0].pop("implementation"), "name its block"),
    (lambda c, a: a["archetypes"][0].update(constraints_fallback=None), "missing constraints_fallback"),
    (lambda c, a: a["archetypes"][3].update(implemented=True), "implemented"),
])
def test_validator_rejects(records, change, expected):
    c, a = copy.deepcopy(records["curation"]), copy.deepcopy(records["archetypes"])
    change(c, a)
    assert any(expected in e for e in ai_curation.validate(c, a))


def test_ai_records_are_not_human_curation(records, tmp_path):
    """The human mechanism is intact: it reads only its own file, and neither AI record passes as one."""
    assert not os.path.exists(os.path.join(FOLDER, "human-curation.json"))
    for record in records.values():
        path = tmp_path / "human-curation.json"
        path.write_text(json.dumps(record), encoding="utf-8")
        with pytest.raises(ValueError):
            curation.load(str(path))


def test_no_reference_material_is_tracked():
    tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.splitlines()
    assert not [f for f in tracked if "Dynamic-PDF-Design-References" in f or f.startswith("visual-atlas/")]
