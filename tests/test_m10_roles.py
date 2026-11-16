"""M10 roles and proportion: keyword data, calibrated document type, meta.audience, contents pages."""
import json
from functools import lru_cache
from pathlib import Path

import pytest

from dynamic_pdf import DocumentBuilder
from dynamic_pdf.core.keywords import keywords, pattern
from dynamic_pdf.design.profile import UNCERTAIN_BELOW, select_profile

DOCS = json.loads((Path(__file__).parent / "data" / "document_types.json").read_text(encoding="utf-8"))["documents"]
FIXTURES = Path(__file__).parent / "fixtures"


@lru_cache(maxsize=None)
def decision(i):
    return select_profile(DocumentBuilder.from_markdown(DOCS[i]["markdown"]).semantic())


def _lead(dec):
    sc = sorted(dec.scores.values(), reverse=True) + [0.0, 0.0]
    return sc[0], sc[0] - sc[1]


def calibrate():
    """The confidence table as the calibration split gives it: per bucket of lead, the share
    of documents whose top-scoring type was right, Laplace-smoothed (an empty bucket is 0.5),
    never falling as the lead grows."""
    table = keywords()["profile_confidence"]
    edges = table["lead_edges"]
    hits = [[0, 0] for _ in range(len(edges) + 1)]
    signal = [0, 0]
    for i, d in enumerate(DOCS):
        if d["split"] != "calibration":
            continue
        dec = decision(i)
        best, lead = _lead(dec)
        top = dec.alternatives[0] if dec.uncertain else dec.profile.value
        if best < table["no_signal_below"]:
            signal[0] += top == d["label"]
            signal[1] += 1
            continue
        k = next((j for j, e in enumerate(edges) if lead < e), len(edges))
        hits[k][0] += top == d["label"]
        hits[k][1] += 1
    values, last = [], 0.0
    for right, n in hits:
        last = max(last, round((right + 1) / (n + 2), 2))
        values.append(last)
    return {"values": values, "no_signal": round((signal[0] + 1) / (signal[1] + 2), 2)}


def test_labelled_set_has_100_documents_in_both_languages():
    assert len(DOCS) >= 100
    assert sum(d["lang"] == "ar" for d in DOCS) >= 30
    assert len({d["label"] for d in DOCS}) == 10
    assert {d["split"] for d in DOCS} == {"calibration", "heldout"}


def test_confidence_table_is_the_one_the_calibration_split_gives():
    table = keywords()["profile_confidence"]
    assert calibrate() == {"values": table["values"], "no_signal": table["no_signal"]}


@pytest.mark.parametrize("split", ["calibration", "heldout", None])
def test_document_type_is_90_percent_right_with_abstentions_counted_wrong(split):
    picked = [i for i, d in enumerate(DOCS) if split is None or d["split"] == split]
    right = sum(decision(i).profile.value == DOCS[i]["label"] and not decision(i).uncertain for i in picked)
    assert right / len(picked) >= 0.90, (split, right, len(picked))


def test_confidence_is_calibrated_on_held_out_documents():
    """Expected calibration error on the held-out half: mean confidence against accuracy, by bucket."""
    buckets = {}
    held = [i for i, d in enumerate(DOCS) if d["split"] == "heldout"]
    for i in held:
        dec = decision(i)
        right = dec.profile.value == DOCS[i]["label"] and not dec.uncertain
        buckets.setdefault(dec.confidence, []).append(right)
    ece = sum(len(v) * abs(c - sum(v) / len(v)) for c, v in buckets.items()) / len(held)
    assert ece <= 0.10, ece


def test_a_tie_is_reported_as_uncertain_and_uses_the_general_layout():
    md = "# Proposal\n\nText.\n\n# Abstract\n\nText.\n"        # one proposal heading, one academic heading
    dec = select_profile(DocumentBuilder.from_markdown(md).semantic())
    assert dec.uncertain and dec.confidence < UNCERTAIN_BELOW
    assert dec.profile.value == "general" and set(dec.alternatives) == {"proposal", "academic_report"}
    assert dec.reasons[0].startswith("uncertain")


def test_keyword_lists_are_data_with_arabic_coverage():
    k = keywords()
    for name, entry in k["profiles"].items():
        assert entry.get("en") and entry.get("ar"), name
    for name in ("summary", "appendix"):
        assert k["sections"][name]["en"] and k["sections"][name]["ar"]
    assert pattern("sections", "appendix").search("الملاحق")
    # an executive summary in Arabic is not an academic abstract
    assert not pattern("profiles", "academic_report").search("الملخص التنفيذي")
    assert pattern("profiles", "academic_report").search("الملخص")


def test_keywords_ship_with_the_package():
    import tomllib
    data = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
    assert "data/*.json" in data["tool"]["setuptools"]["package-data"]["dynamic_pdf"]


AUDIENCE_DOC = "---\ntitle: Platform Update\naudience: {}\n---\n# Changes\n\nWe moved the service to the new cluster.\n"


def test_meta_audience_is_read_and_explained():
    b = DocumentBuilder.from_markdown(AUDIENCE_DOC.format("site reliability engineers")).design()
    ex = b.design_explain()
    assert ex["profile"] == "technical_manual"
    assert "engineers" in ex["audience"] and any("meta.audience" in r for r in ex["reasons"])
    plain = DocumentBuilder.from_markdown(AUDIENCE_DOC.format("")).design().design_explain()
    assert plain["audience"] is None and plain["profile"] != "technical_manual"


def test_meta_audience_names_the_readers_of_an_art_direction():
    from dynamic_pdf.design.art_direction import read_brief
    sem = DocumentBuilder.from_markdown(AUDIENCE_DOC.format("the board of directors")).semantic()
    brief = read_brief(sem, "executive_report", 2)
    assert brief.audience == "the board of directors" and brief.audience_source == "meta.audience"
    assert brief.purpose == "board_paper"
    unmatched = DocumentBuilder().meta(title="Update", audience="Friends of the museum").heading("A").paragraph("B")
    assert read_brief(unmatched.semantic(), "general", 1).audience == "Friends of the museum"


def test_no_contents_page_under_four_pages_in_the_default_design():
    md = (FIXTURES / "manual.md").read_text(encoding="utf-8")
    b = DocumentBuilder.from_markdown(md).design()
    doc, _ = b._prepared()
    assert not any(x.type == "table_of_contents" for x in doc.blocks)
    assert any(line.startswith("contents:") for line in b.design_explain()["layout"])
    import io, docx
    d = docx.Document(io.BytesIO(b.render_docx()))
    assert not any(p.style.name.startswith("TOC") for p in d.paragraphs)


def test_a_long_manual_keeps_its_contents_page():
    md = "---\ntitle: Long Manual\n---\n" + "".join(
        f"# Chapter {i}\n\n" + ("Install the service and configure it with care. " * 60 + "\n\n") * 3
        for i in range(1, 7))
    b = DocumentBuilder.from_markdown(md).design()
    doc, _ = b._prepared()
    assert b.last_design.decision.profile.value == "technical_manual"
    assert any(x.type == "table_of_contents" for x in doc.blocks)


def test_an_author_contents_page_stays_in_a_short_document():
    b = DocumentBuilder().meta(title="Short").table_of_contents().heading("Installation").paragraph(
        "Install it.").heading("Usage").paragraph("Use it.").heading("Troubleshooting").paragraph("Fix it.")
    b.design()
    doc, _ = b._prepared()
    assert any(x.type == "table_of_contents" for x in doc.blocks)


def test_no_contents_page_under_four_pages_in_art_directions():
    from dynamic_pdf.design.art_direction import direct
    from dynamic_pdf.design.directions import DIRECTIONS
    md = (FIXTURES / "manual.md").read_text(encoding="utf-8")
    sem = DocumentBuilder.from_markdown(md).semantic()
    for d in DIRECTIONS.values():
        out = direct(sem, d)
        assert not any(x.type == "table_of_contents" for x in out.document.blocks), d.id
