"""M7.4: evidence recipes are opt-in, cite only accepted patterns, and fall back when unsafe."""
import importlib.util
import io
import json
import os

import docx
import pymupdf
import pytest

from dynamic_pdf import DocumentBuilder
from dynamic_pdf.design import EVIDENCE_RECIPES
from dynamic_pdf.design import evidence_gate as gate
from dynamic_pdf.design.planner import MIN_RUN_CHARS, _tighten
from dynamic_pdf.design.recipes import RECIPES
from dynamic_pdf.intelligence.geometry import Geometry
from dynamic_pdf.intelligence.scoring import MIN_LEADING, score_layout
from dynamic_pdf.layout.column_flow import ColumnFlow
from dynamic_pdf.layout.engine import LayoutEngine
from dynamic_pdf.qa import check_docx

ROOT = os.path.join(os.path.dirname(__file__), "..")
SENTENCE = ("The harbour authority reviewed the quarterly results and agreed the next steps for the "
            "programme, noting that the forecast depends on work that has not yet been signed. ")


def _paras(n=4, tag="para", repeat=3):
    return "\n\n".join(f"{tag}{i} " + SENTENCE * repeat for i in range(n))


def _report(sections=3, n=4, repeat=3):
    body = "\n\n".join(f"## Section {s}\n\n{_paras(n, f's{s}p', repeat)}" for s in range(sections))
    table = "| Year | Revenue | Profit |\n|---|---:|---:|\n| 2024 | 120 | 12 |\n| 2025 | 140 | 19 |\n"
    return f"# Quarterly results\n\n{body}\n\n## Figures\n\n{table}"


def _editorial(md=None):
    return DocumentBuilder.from_markdown(md or _report()).design(
        "executive_report", recipe="editorial_executive", recipe_gate="preview")


def _text(pdf):
    return "\n".join(p.get_text() for p in pymupdf.open(stream=pdf, filetype="pdf"))


def _review():
    with open(os.path.join(ROOT, "tools", "reference_analyzer", "pattern_review.json"), encoding="utf-8") as f:
        return {p["pattern_id"]: p for p in json.load(f)["patterns"]}


# ─────────────────────────── existing behaviour ───────────────────────────

def test_default_design_is_untouched():
    b = DocumentBuilder.from_markdown(_report()).design()
    b.render()
    explain = b.design_explain()
    assert "evidence_recipe" not in explain and b.last_design.recipe_outcome is None
    assert not any("flow_run" in (x.hints or {}) for x in b._prepared()[0].blocks)
    for r in RECIPES.values():
        assert r.body_columns == 1 and r.heading_ramp_locked is False


def test_positional_design_arguments_still_mean_mode_and_brand():
    b = DocumentBuilder.from_markdown("# T\n\nx").design("letter", {"name": "Acme"})
    assert b._design_mode == "letter" and b._brand.name == "Acme" and b._evidence_recipe is None


def test_tighten_never_loosens_a_tighter_leading():
    t = EVIDENCE_RECIPES and DocumentBuilder.from_markdown("# T\n\nx").design(
        recipe="financial_corporate", recipe_gate="preview")._prepared()[1].model_copy(deep=True)
    t.typography.line_height = 1.25
    _tighten(t, 0.8, 0.9, 0.05)
    assert t.typography.line_height == 1.25
    t.typography.line_height = 1.4
    _tighten(t, 0.8, 0.9, 0.05)
    assert t.typography.line_height == 1.35


# ─────────────────────────── evidence ───────────────────────────

def test_recipes_cite_only_patterns_accepted_for_them():
    review = _review()
    for r in EVIDENCE_RECIPES.values():
        assert r.evidence
        for ids in r.evidence.values():
            for pid in ids:
                assert review[pid]["decision"] == "accept", pid
                assert r.name in review[pid]["applies_to"]["recipes"], (r.name, pid)


def test_every_recipe_named_in_the_review_exists():
    for p in _review().values():
        for name in (p.get("applies_to") or {}).get("recipes", []):
            assert name in EVIDENCE_RECIPES


def test_recipe_values_sit_inside_the_accepted_bands():
    fin, ed, ar = (EVIDENCE_RECIPES[n] for n in ("financial_corporate", "editorial_executive", "arabic_bilingual"))
    assert 9.5 <= fin.base_size <= 10.4 and 9.5 <= ed.base_size <= 10.4 and 12 <= ar.base_size <= 12.5
    assert fin.line_height == MIN_LEADING                  # the accepted band ends at the safety floor
    assert 1.26 <= ed.line_height <= 1.40 and 1.26 <= ar.line_height <= 1.40
    assert all(r.heading_scale[0] >= 2.74 for r in (fin, ed))
    assert ar.heading_scale is None and "heading ramp" in ar.not_applied    # withdrawn after the comparison


def test_changes_without_accepted_evidence_are_recorded_as_not_applied():
    assert "margins" in EVIDENCE_RECIPES["financial_corporate"].not_applied
    assert "table padding" in EVIDENCE_RECIPES["financial_corporate"].not_applied
    assert "whitespace" in EVIDENCE_RECIPES["editorial_executive"].not_applied
    base = RECIPES[EVIDENCE_RECIPES["financial_corporate"].profiles[0]]
    b = DocumentBuilder.from_markdown(_report()).design("financial_report", recipe="financial_corporate",
                                                        recipe_gate="preview")
    b._prepared()
    assert b.last_design.recipe.margins == base.margins and b.last_design.recipe.density == base.density


# ─────────────────────────── gate ───────────────────────────

def test_unknown_recipe_and_gate_are_refused():
    b = DocumentBuilder.from_markdown("# T\n\nx")
    with pytest.raises(ValueError):
        b.design(recipe="nope")
    with pytest.raises(ValueError):
        b.design(recipe="auto", recipe_gate="nope")


def test_recipe_outside_its_documents_keeps_the_existing_design():
    b = DocumentBuilder.from_markdown("Dear Sir,\n\nThank you.\n\nYours faithfully").design("letter", recipe="auto")
    b.render()
    out = b.design_explain()["evidence_recipe"]
    assert out["status"] == "not_applicable" and out["applied"] is False
    assert b.last_design.recipe.base_size == RECIPES[b.last_design.decision.profile].base_size


def test_auto_picks_the_recipe_for_the_document():
    b = DocumentBuilder.from_markdown(_report()).design("financial_report", recipe="auto")
    b._prepared()
    assert b.last_design.recipe_outcome.recipe == "financial_corporate"


def _make(status, monkeypatch):
    r = EVIDENCE_RECIPES["editorial_executive"].model_copy(update={"status": status, "status_reason": "no proof yet"})
    monkeypatch.setitem(EVIDENCE_RECIPES, "editorial_executive", r)


def test_recipe_without_evidence_stays_off_and_is_labelled_inconclusive(monkeypatch):
    _make("inconclusive", monkeypatch)
    md = _report()
    plain = DocumentBuilder.from_markdown(md).design("executive_report")
    gated = DocumentBuilder.from_markdown(md).design("executive_report", recipe="editorial_executive")
    assert gated._prepared()[1].typography.base_size == plain._prepared()[1].typography.base_size
    out = gated.design_explain()["evidence_recipe"]
    assert (out["status"], out["applied"]) == ("inconclusive", False)
    assert "no proof yet" in out["reasons"] and out["proposed"] is None        # nothing was rendered for it


def test_active_recipe_applies_when_safe(monkeypatch):
    _make("active", monkeypatch)
    b = DocumentBuilder.from_markdown(_report()).design("executive_report", recipe="editorial_executive")
    assert b._prepared()[1].typography.base_size == 10.0
    out = b.design_explain()["evidence_recipe"]
    assert (out["status"], out["applied"]) == ("active", True) and out["proposed"]["valid"]


@pytest.mark.parametrize("bad,word", [
    ({"valid": False, "hard_errors": ["block 3 (table) not placed"]}, "hard layout"),
    ({"split_tables": 2}, "split"),
    ({"pages": 9}, "pages"),
])
def test_unsafe_recipe_falls_back_and_says_why(monkeypatch, bad, word):
    _make("active", monkeypatch)
    real = gate.measure
    calls = []

    def fake(sem, theme, policy=None):
        calls.append(1)
        m = real(sem, theme, policy)
        m["pages"] = 2
        return {**m, **bad} if len(calls) == 2 else m
    monkeypatch.setattr(gate, "measure", fake)
    md = _report()
    b = DocumentBuilder.from_markdown(md).design("executive_report", recipe="editorial_executive")
    plain = DocumentBuilder.from_markdown(md).design("executive_report")
    assert b._prepared()[1].typography.base_size == plain._prepared()[1].typography.base_size
    out = b.design_explain()["evidence_recipe"]
    assert (out["status"], out["applied"]) == ("inconclusive", False)
    assert any(word in r for r in out["reasons"]) and "existing design kept" in out["reasons"]


def test_preview_renders_the_recipe_but_keeps_the_label(monkeypatch):
    monkeypatch.setattr(gate, "safety_failures", lambda a, b: ["forced"])
    b = _editorial()
    assert b._prepared()[1].typography.base_size == 10.0
    assert b.last_design.recipe_outcome.status == "inconclusive"
    assert b.last_design.recipe_outcome.applied is True


def test_gate_runs_once_per_design(monkeypatch):
    calls = []
    real = gate.measure
    monkeypatch.setattr(gate, "measure", lambda *a, **k: calls.append(1) or real(*a, **k))
    b = _editorial()
    b.render()
    b.render_docx()
    assert len(calls) == 2


def test_content_is_identical_under_every_recipe():
    md = _report()
    for name, mode in (("financial_corporate", "financial_report"), ("editorial_executive", "executive_report")):
        words = set(_text(DocumentBuilder.from_markdown(md).design(mode).render()).split())
        got = set(_text(DocumentBuilder.from_markdown(md).design(mode, recipe=name, recipe_gate="preview")
                        .render()).split())
        assert {w for w in words if w.isalpha()} == {w for w in got if w.isalpha()}


# ─────────────────────────── planner ───────────────────────────

def _hints(b):
    return [x.hints.get("flow_run") if x.hints else None for x in b._prepared()[0].blocks]


def test_long_prose_runs_get_columns_and_headings_tables_do_not():
    doc, _ = _editorial()._prepared()
    marked = [x for x in doc.blocks if (x.hints or {}).get("flow_run") is not None]
    assert marked and all(x.type == "paragraph" for x in marked)
    assert len({x.hints["flow_run"] for x in marked}) >= 2


def test_short_runs_stay_single_column():
    assert len(SENTENCE) * 4 < MIN_RUN_CHARS
    assert not any(h is not None for h in _hints(_editorial(_report(n=2, repeat=3))))
    assert not any(h is not None for h in _hints(_editorial(_report(n=4, repeat=1))))


def test_a_lead_paragraph_stays_full_width():
    doc, _ = _editorial()._prepared()
    leads = [x for x in doc.blocks if (x.hints or {}).get("lead")]
    assert leads and all("flow_run" not in x.hints for x in leads)


def test_right_to_left_text_never_gets_columns():
    ar = "هذا نص عربي طويل يصف نتائج الربع الأخير ويشرح الخطوات القادمة للبرنامج كما اتفق عليها المجلس. " * 4
    md = "# تقرير\n\n## القسم\n\n" + "\n\n".join([ar] * 4)
    b = DocumentBuilder.from_markdown(md).design("executive_report", recipe="editorial_executive",
                                                 recipe_gate="preview")
    assert not any(h is not None for h in _hints(b))
    assert b.last_design.recipe_outcome.status == "not_applicable"


def test_heading_ramp_survives_a_deep_outline():
    md = "# A\n\n## B\n\n### C\n\n#### D\n\n" + _paras(2)
    b = DocumentBuilder.from_markdown(md).design("financial_report", recipe="financial_corporate",
                                                 recipe_gate="preview")
    assert b._prepared()[1].typography.heading_scale[0] == 2.75


# ─────────────────────────── columns in PDF ───────────────────────────

def _render(b):
    doc, theme = b._prepared()
    geo = Geometry()
    data = io.BytesIO()
    LayoutEngine(doc, theme=theme, geometry=geo).render(data)
    return doc, theme, geo, data.getvalue()


def test_columns_keep_every_block_and_a_valid_score():
    doc, theme, geo, _ = _render(_editorial())
    score = score_layout(geo, doc, theme)
    assert score.valid, score.hard_errors


def test_columns_sit_side_by_side_and_read_in_order():
    pdf = _editorial().render()
    text = " ".join(_text(pdf).split())
    order = [text.index(f"s0p{i} ") for i in range(1, 4)]
    assert order == sorted(order)
    page = next(p for p in pymupdf.open(stream=pdf, filetype="pdf") if "s0p1 " in p.get_text())
    xs = {round(b[0]) for b in page.get_text("blocks") if len(b[4]) > 120}
    assert len(xs) >= 2


def test_a_run_longer_than_a_page_continues_on_the_next_page():
    md = "# Long\n\n## Part\n\n" + _paras(30, "w", 4) + "\n\n## After\n\nDone."
    b = _editorial(md)
    doc, theme, geo, pdf = _render(b)
    assert score_layout(geo, doc, theme).valid
    text = _text(pdf)
    for i in range(30):
        assert f"w{i} " in text
    assert len(pymupdf.open(stream=pdf, filetype="pdf")) >= 3


def test_columns_balance_at_the_end_of_a_run():
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph
    st = ParagraphStyle("b", fontName="Helvetica", fontSize=10, leading=13, spaceAfter=6)
    flow = ColumnFlow([Paragraph(SENTENCE * 3, st) for _ in range(4)])
    _, h = flow.wrap(460, 700)
    assert 0 < h < 700
    heights = [sum(fh for _, fh in col) for col in flow._cols]
    assert abs(heights[0] - heights[1]) <= 3 * 13


def test_columns_split_keeps_everything():
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph
    st = ParagraphStyle("b", fontName="Helvetica", fontSize=10, leading=13, spaceAfter=6)
    flow = ColumnFlow([Paragraph(f"p{i} " + SENTENCE * 3, st) for i in range(10)])
    assert flow.split(460, 20) == []                          # too little room: start on the next page
    head, tail = flow.split(460, 200)
    assert head.wrap(460, 200)[1] <= 200 and tail.items


def test_column_run_with_a_non_paragraph_is_left_alone():
    from reportlab.platypus import Spacer
    from dynamic_pdf.layout.column_flow import column_flow
    items = [Spacer(1, 1)]
    assert column_flow(items, 2, 18) == items


def test_compose_accepts_a_recipe_design():
    pdf = _editorial().compose("smart").render()
    assert "s0p0" in _text(pdf)


# ─────────────────────────── columns in DOCX ───────────────────────────

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _sections(data):
    d = docx.Document(io.BytesIO(data))
    return d, [(s.find(W + "cols"), s.find(W + "type")) for s in d.element.body.iter(W + "sectPr")]


def test_docx_columns_are_real_word_columns_with_editable_text():
    data = _editorial().render_docx()
    d, secs = _sections(data)
    nums = [int(c.get(W + "num", "1")) if c is not None else 1 for c, _ in secs]
    assert 2 in nums and nums[-1] == 1
    assert all(t.get(W + "val") == "continuous" for c, t in secs[1:] if t is not None)
    text = "\n".join(p.text for p in d.paragraphs)
    for i in range(4):
        assert f"s0p{i} " in text
    assert not any(p.text == "" and p._p.pPr is None for p in d.paragraphs)


def test_docx_columns_render_side_by_side():
    """Needs LibreOffice, which CI installs: the Word columns on a rendered page."""
    qa = check_docx(_editorial().render_docx(), visual=True)
    if qa.unverified:
        pytest.skip("no DOCX renderer")
    assert not qa.errors
    page = pymupdf.open(stream=qa._pdf, filetype="pdf")[0]
    mid = page.rect.width / 2
    lines = [b for b in page.get_text("blocks") if "harbour" in b[4]]
    assert any(b[2] <= mid for b in lines) and any(b[0] >= mid for b in lines)


def test_docx_columns_keep_the_page_furniture():
    d = docx.Document(io.BytesIO(_editorial().render_docx()))
    assert all(s.footer.is_linked_to_previous for s in d.sections[1:])


def test_docx_without_a_recipe_has_one_section():
    d = docx.Document(io.BytesIO(DocumentBuilder.from_markdown(_report()).design().render_docx()))
    assert len(d.sections) == 1


# ─────────────────────────── review mechanism ───────────────────────────

def _m74(name):
    spec = importlib.util.spec_from_file_location(f"m74_{name}", os.path.join(ROOT, "benchmarks", "m74", name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _judgment(choice, preferred, layout="x"):
    return {"format": "dynamic-pdf-builder/m74-human-preferences", "version": 1, "reviewer": "t", "judgments": [{
        "document": "editorial_executive/proposal", "shown_as": {"A": "proposed", "B": "baseline"}, "choice": choice,
        "preferred_variant": preferred, "reasons": [], "layout_id": {"baseline": "b", "proposed": layout}}]}


def test_preference_files_are_validated_and_never_generated():
    prefs = _m74("preferences")
    assert prefs.validate(_judgment("A", "proposed")) == []
    assert prefs.validate(_judgment("tie", "tie")) == []
    assert any("contradicts" in e for e in prefs.validate(_judgment("A", "baseline")))
    assert any("unlabelled" in e for e in prefs.validate(_judgment(None, None)))
    with open(os.path.join(ROOT, "benchmarks", "m74", "human_preferences.template.json"), encoding="utf-8") as f:
        assert json.load(f)["judgments"] == []


def test_stale_judgments_are_dropped_from_the_summary():
    prefs = _m74("preferences")
    results = {"documents": {"editorial_executive/proposal": {"baseline": {"layout_id": "b"},
                                                             "proposed": {"layout_id": "x"}}}}
    assert prefs.summary(results, [_judgment("A", "proposed")]) == {
        "editorial_executive/proposal": {"proposed": 1, "baseline": 0, "tie": 0}}
    assert prefs.summary(results, [_judgment("A", "proposed", layout="changed")]) == {}


def test_no_recipe_is_active_without_human_review():
    # activation needs exported judgments in the results; there are none yet
    assert all(r.status == "inconclusive" and r.status_reason for r in EVIDENCE_RECIPES.values())


def test_no_human_judgment_is_committed_with_the_comparison():
    path = os.path.join(ROOT, "docs", "m74-evidence-recipes", "results.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            res = json.load(f)
        assert all(r["human_review"]["judgments"] == 0 for r in res["recipes"].values())
