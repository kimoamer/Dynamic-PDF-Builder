"""M7 benchmark harness: corpus, content checks, verdict rules, preference format."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "benchmarks", "m7"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import corpus  # noqa: E402
import preferences  # noqa: E402
import report  # noqa: E402
import run  # noqa: E402


def test_corpus_covers_required_document_kinds():
    assert 12 <= len(corpus.CORPUS) <= 18
    cats = " ".join(c for c, _, _ in corpus.CORPUS.values()).lower()
    for kind in ("arabic", "bilingual", "proposal", "academic", "technical", "financial", "chart",
                 "letter", "invoice", "long"):
        assert kind in cats, kind
    assert {s for _, s, _ in corpus.CORPUS.values()} == {"small", "medium", "long"}


@pytest.mark.parametrize("name", sorted(corpus.CORPUS))
def test_corpus_documents_build(name):
    doc = corpus.CORPUS[name][2]().build()
    assert len(doc.blocks) >= 5
    if name.startswith("ar_"):
        assert doc.meta.direction == "rtl" or doc.meta.rtl


def test_sequence_check_finds_missing_duplicated_and_reordered():
    fps = [(0, ("alpha", "beta", "gamma", "delta", "epsilon", "zeta"), False),
           (1, ("one", "two", "three", "four", "five", "six"), False),
           (2, ("red", "green", "blue", "cyan", "magenta", "yellow"), False)]
    ok = run._sequence_check(fps, "alpha beta gamma delta epsilon zeta x one two three four five six "
                                  "red green blue cyan magenta yellow", ltr_only=False)
    assert ok == {"checked": 3, "missing": [], "duplicated": [], "reordered": []}
    bad = run._sequence_check(fps, "one two three four five six alpha beta gamma delta epsilon zeta "
                                   "one two three four five six", ltr_only=False)
    assert bad["missing"] == [2] and bad["duplicated"] == [1] and bad["reordered"] == []
    swapped = run._sequence_check(fps[:2], "one two three four five six . alpha beta gamma delta epsilon zeta",
                                  ltr_only=False)
    assert swapped["reordered"] == [1] and swapped["missing"] == []
    swapped3 = run._sequence_check(fps, "red green blue cyan magenta yellow alpha beta gamma delta epsilon "
                                        "zeta", ltr_only=False)
    assert swapped3["missing"] == [1] and swapped3["reordered"] == [2]


def _rec(pages=3, under=(), sep=0, qa=(), strategy="balanced", score=80.0, cpl=80):
    return {"pages": pages, "composition": {"strategy": strategy},
            "layout": {"underfilled_body_pages": list(under), "figures_after_gap": [], "oversize_figures": [],
                       "geometry_duplicates": [], "rtl_right_aligned_share": None},
            "score": {"value": score, "separated_figures": sep, "hard_errors": [], "cpl": cpl},
            "pdf_qa": {"errors": list(qa)}, "docx_qa": {"errors": []},
            "content": {"pdf_missing_words": [], "docx_missing_words": [],
                        "pdf_sequence": {"missing": [], "duplicated": [], "reordered": []},
                        "docx_sequence": {"missing": [], "duplicated": [], "reordered": []}}}


def test_verdict_never_counts_a_score_only_gain():
    v, notes = report.verdict(_rec(score=80), _rec(score=90))
    assert v.startswith("no measurable change") and "score-only" in v and notes == []
    assert report.verdict(_rec(sep=2), _rec(sep=0))[0] == "improved"
    assert report.verdict(_rec(pages=3), _rec(pages=4))[0] == "regressed"
    assert report.verdict(_rec(pages=3, sep=2), _rec(pages=4, sep=0))[0] == "mixed"
    assert report.verdict(_rec(), _rec(strategy="baseline", pages=9))[0].startswith("unchanged")


def _pref(choice="A", preferred="smart"):
    return {"format": preferences.FORMAT, "version": 1, "reviewer": "t",
            "judgments": [{"document": "proposal", "shown_as": {"A": "smart", "B": "baseline"},
                           "choice": choice, "preferred_variant": preferred, "reasons": ["whitespace"],
                           "layout_id": {"baseline": "b1", "smart": "s1"}}]}


def test_preference_file_validation():
    assert preferences.validate(_pref()) == []
    assert preferences.validate(_pref("B", "baseline")) == []
    assert preferences.validate(_pref("tie", "tie")) == []
    assert any("unlabelled" in e for e in preferences.validate(_pref(None, None)))
    assert any("contradicts" in e for e in preferences.validate(_pref("A", "baseline")))
    assert preferences.validate({"format": "x", "version": 1, "judgments": []})


def test_preference_summary_ignores_stale_layouts():
    results = {"documents": {"proposal": {"baseline": {"layout_id": "b1"}, "smart": {"layout_id": "s1"}}}}
    assert preferences.summary(results, [_pref()]) == {"proposal": {"smart": 1, "baseline": 0, "tie": 0}}
    results["documents"]["proposal"]["smart"]["layout_id"] = "s2"     # re-rendered differently
    assert preferences.summary(results, [_pref()]) == {}


def test_template_preferences_file_has_no_judgments():
    import json
    path = os.path.join(os.path.dirname(__file__), "..", "benchmarks", "m7", "human_preferences.template.json")
    data = json.load(open(path, encoding="utf-8"))
    assert data["judgments"] == [] and preferences.validate(data) == []
