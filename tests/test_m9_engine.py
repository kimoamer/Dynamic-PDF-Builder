"""M9: one set of measured facts, one objective, variants reachable from export() and the CLI,
less repeated work, a calibrated page forecast and one scoreboard."""
import io
import json
import os
import subprocess
import sys

import pytest

from conftest import fixture_text
from dynamic_pdf import DocumentBuilder
from dynamic_pdf.intelligence import facts as F
from dynamic_pdf.intelligence import objective, scoring, variants as vmod
from dynamic_pdf.intelligence.analysis import measure_blocks, simulate
from dynamic_pdf.intelligence.geometry import Geometry
from dynamic_pdf.intelligence.variant_ranker import variant_features
from dynamic_pdf.layout.engine import LayoutEngine
from dynamic_pdf.qa.visual_critique import critique_facts, critique_pdf
from dynamic_pdf.themes import get_theme

pymupdf = pytest.importorskip("pymupdf")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PARA = ("The harbour moved more freight this year than in any year since records began, and the new "
        "quay opened on time and within its approved budget of forty million. ")


def report(sections=4):
    b = DocumentBuilder().meta(title="Harbour annual report", author="Port Authority")
    for i in range(sections):
        b.heading(f"Section {i + 1}").paragraph(PARA * 4).paragraph(PARA * 3)
    return b


def long_table(rows=90):
    b = DocumentBuilder().meta(title="Ledger")
    b.heading("Ledger").paragraph(PARA)
    b.table(["Item", "Region", "Amount", "Note"],
            [[f"Item {i}", "North" if i % 2 else "South", f"{i * 137:,}", "checked " * (1 + i % 4)]
             for i in range(rows)])
    return b.heading("After").paragraph(PARA)


# ── PageFacts ──────────────────────────────────────────────────────────────────────────

def test_page_facts_are_one_versioned_reading_of_the_pdf():
    pdf = report().render()
    facts = F.read_pdf(pdf, plain_pages=1)
    assert facts.version == F.FACTS_VERSION == 2 and facts.available
    assert facts.page_count == len(facts.pages) == facts.document["pages"] == len(facts.thumbs)
    assert facts.document["facts_version"] == F.FACTS_VERSION
    # the critique and the dataset facts are views of the same reading
    assert critique_pdf(pdf).model_dump() == critique_facts(facts).model_dump()
    from tools.design_learning.layout_facts import measure
    assert measure(pdf, plain_pages=1) == F.read_pdf(pdf, plain_pages=1, image=False).document
    assert "thumbs" not in facts.model_dump()


def test_page_facts_measure_the_type_on_the_page():
    b = report()
    theme = get_theme("claude")
    facts = F.read_pdf(b.render())
    assert facts.document["body_size"] == pytest.approx(theme.typography.base_size, abs=0.1)
    assert facts.document["body_leading"] == pytest.approx(theme.typography.line_height, abs=0.06)


def test_layout_facts_join_the_page_facts():
    b = report()
    doc = b.build()
    theme = get_theme(doc.theme)
    geo = Geometry()
    buf = io.BytesIO()
    LayoutEngine(doc, theme=theme, geometry=geo).render(buf)
    facts = F.measure_render(buf.getvalue(), geo, doc, theme)
    score = scoring.score_layout(geo, doc, theme)
    assert facts.layout["score"] == score.score and facts.layout["utilization"] == score.metrics["utilization"]
    assert len(facts.layout_pages) == facts.page_count and facts.layout_errors == score.hard_errors


# ── one objective ──────────────────────────────────────────────────────────────────────

def test_one_weights_table_drives_every_score():
    assert scoring.WEIGHTS is objective.WEIGHTS["layout"]
    h = {"page_variety": 0.5, "type_contrast": 2.0, "image_share": 0.05, "sparse_share": 0.1,
         "alike_share": 0.2, "last_page_ink": 0.05}
    from dynamic_pdf.qa.visual_critique import VisualCritique
    assert VisualCritique(heuristics=h).index == objective.visual_index(h)
    old = 60 + 14 * 0.5 + 10 * 2.0 / 3.5 + 8 * 0.05 / 0.15 - 22 * 0.1 - 18 * 0.2 - 10 * 0.15
    assert objective.visual_index(h) == round(old, 2)
    assert objective.design_score(2, 70.0) == 82.0


@pytest.fixture(scope="module")
def proposal_variants():
    return DocumentBuilder.from_markdown(fixture_text("proposal.md")).design_variants(n=3)


def test_variants_carry_facts_and_the_recommendation_follows_the_objective(proposal_variants):
    vs = proposal_variants
    valid = [v for v in vs if v.valid]
    assert valid and vs.recommended is max(valid, key=lambda v: v.report.score)
    for v in valid:
        assert v.facts.version == F.FACTS_VERSION
        assert v.report.score == objective.design_score(v.report.fit, v.report.index)
        assert v.report.facts["body_size"] > 0 and "layout_score" in v.report.facts
    choice = vs.choice()
    assert choice.recommended == vs.recommended.id and set(choice.variants) == {v.id for v in vs}


def test_ranker_reads_measured_type_not_the_plan_text(proposal_variants):
    for v in proposal_variants:
        before = variant_features(v)
        v.plan.typography = "Nothing 99/9"
        f = variant_features(v)
        assert f == before
        # the leading as measured, or the compiled theme's where no body line wraps to show it
        measured = v.facts.document["body_leading"] or v.theme.typography.line_height
        assert (f["base_size"], f["line_height"]) == (v.facts.document["body_size"], measured)
    plain = next(v for v in proposal_variants if v.id == "corporate_conservative")    # no lead paragraphs
    assert variant_features(plain)["base_size"] == plain.theme.typography.base_size


def test_leading_is_measured_where_lines_wrap_and_unknown_where_none_do():
    theme = get_theme("claude")
    assert F.read_pdf(report().render()).document["body_leading"] == pytest.approx(theme.typography.line_height,
                                                                                    abs=0.06)
    short = DocumentBuilder().heading("A").paragraph("One line.").paragraph("Another line.").render()
    assert F.read_pdf(short).document["body_leading"] == 0.0


# ── less repeated work (F13) ───────────────────────────────────────────────────────────

def test_each_render_is_read_once_and_an_unchanged_design_is_not_rendered_again(monkeypatch):
    reads, renders, caches = [], [], []
    real_read, real_render = vmod.read_pdf, vmod._Runner._render

    def read(pdf, **kw):
        reads.append(pdf)
        return real_read(pdf, **kw)

    def render(self, doc, theme, cache=None):
        renders.append(doc.model_dump_json() + theme.model_dump_json())
        caches.append(cache)
        return real_render(self, doc, theme, cache)

    monkeypatch.setattr(vmod, "read_pdf", read)
    monkeypatch.setattr(vmod._Runner, "_render", render)
    vs = DocumentBuilder.from_markdown(fixture_text("proposal.md")).design_variants(
        n=1, families=["editorial_modern"])
    v = vs.variants[0]
    designed = renders[1:]                         # the first render is the plain yardstick
    assert len(designed) == len(set(designed)) == v.report.renders == len(reads)
    assert len(v.report.refinements) >= v.report.renders      # some steps changed nothing
    assert caches[0] is None and all(c is caches[1] for c in caches[1:]) and isinstance(caches[1], dict)


def test_a_shared_figure_cache_does_not_carry_one_render_into_the_next():
    def chart_doc(keep):
        b = DocumentBuilder().meta(title="Charts").heading("Results")
        b.chart("bar", data={"North": 3.0, "South": 5.0, "East": 2.0}, title="Sales")
        doc = b.paragraph(PARA * 2).build()
        if keep:
            doc.blocks[1].hints = {"keep_with_next": True}
        return doc
    cache = {}
    for keep in (True, False, True):
        LayoutEngine(chart_doc(keep), cache=cache).render(io.BytesIO())
    cached = [f for k, v in cache.items() if k[0] == "fig" for f in v]
    assert cached and not any(getattr(f, "keepWithNext", 0) for f in cached)


# ── the page forecast (F6) ─────────────────────────────────────────────────────────────

def _forecast(b):
    doc = b.build()
    theme = get_theme(doc.theme)
    ms, fg = measure_blocks(doc, theme, None, {})
    pred = simulate(ms, fg)
    geo = Geometry()
    LayoutEngine(doc, theme=theme, geometry=geo).render(io.BytesIO())
    return pred, geo, fg


def test_the_forecast_breaks_tables_between_rows_inside_the_frame_padding():
    pred, geo, fg = _forecast(long_table())
    assert len(pred.pages) == len(geo.pages) > 2
    real = scoring.score_layout(geo, long_table().build(), get_theme("claude"))
    guess = scoring.score_layout(pred, long_table().build(), get_theme("claude"))
    assert abs(guess.score - real.score) < 1.5
    for r in pred.regions:          # inside the padded frame, as the renderer places content
        info = pred.pages[r.page]
        assert info.frame_bottom + 6 - 0.01 <= r.bottom and r.top <= info.frame_top - 6 + 0.01
        assert fg.left + 6 - 0.01 <= r.x0 < r.x1 <= fg.left + fg.width - 6 + 0.01


def test_the_forecast_takes_real_content_widths(tmp_path):
    from PIL import Image
    Image.new("RGB", (400, 300), (40, 80, 110)).save(tmp_path / "small.png")
    b = DocumentBuilder().meta(title="Narrow").heading("A small figure").image(str(tmp_path / "small.png"), width=120)
    pred, geo, fg = _forecast(b)
    sim = [r for r in pred.regions if r.block == 1]
    real = [r for r in geo.regions if r.role == "figure"]
    assert sim and real and sim[0].x1 - sim[0].x0 == pytest.approx(real[0].x1 - real[0].x0, abs=1)
    assert sim[0].x1 - sim[0].x0 < fg.width - 12


# ── reach: design(direction=, variants=, grammar=) and the CLI ─────────────────────────

def test_export_delivers_the_recommended_design(tmp_path, monkeypatch):
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1700000000")
    b = DocumentBuilder.from_markdown(fixture_text("proposal.md")).design(direction="auto", variants=2)
    res = b.export_both(str(tmp_path), qa=True)
    chosen = b.last_variants.recommended
    assert res.design.recommended == chosen.id and not res.design.fallback and res.design.reasons
    assert res.status == "ok", res.status_reasons
    with open(res.pdf_path, "rb") as f:
        assert f.read() == chosen.pdf
    assert res.profile == chosen.plan.brief.profile
    assert b.design_explain()["direction"] == chosen.id


def test_a_named_direction_is_the_only_one_tried():
    b = DocumentBuilder.from_markdown(fixture_text("proposal.md")).design(direction="financial_data")
    b.render()
    assert [v.id for v in b.last_variants] == ["financial_data"]


def test_without_the_new_arguments_nothing_changes(tmp_path, monkeypatch):
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1700000000")
    md = fixture_text("memo.md")
    plain = DocumentBuilder.from_markdown(md)
    assert plain.render() == DocumentBuilder.from_markdown(md).render()
    res = DocumentBuilder.from_markdown(md).design("auto").export(str(tmp_path / "m.pdf"))
    assert res.design is None
    with pytest.raises(ValueError):
        DocumentBuilder().design(direction="nonsense")
    with pytest.raises(ValueError):
        DocumentBuilder().design(variants=9)
    with pytest.raises(ValueError):
        DocumentBuilder.from_markdown(md).design(variants=1).compose("smart").render()


def test_no_valid_variant_falls_back_to_the_stable_design(tmp_path, monkeypatch):
    empty = vmod.VariantSet([], None, ["no design passed the hard gates"], fallback=True)
    monkeypatch.setattr(DocumentBuilder, "design_variants", lambda self, **kw: empty)
    md = fixture_text("memo.md")
    res = DocumentBuilder.from_markdown(md).design(variants=2).export(str(tmp_path / "m.pdf"), qa=True)
    assert res.design.fallback and res.design.recommended is None and res.status == "fallback"
    assert any("no design variant passed" in r for r in res.status_reasons)
    stable = DocumentBuilder.from_markdown(md).design("auto")
    assert res.page_count == stable.export(str(tmp_path / "s.pdf")).page_count


def _cli(*args):
    env = dict(os.environ, PYTHONPATH=ROOT + os.pathsep + os.environ.get("PYTHONPATH", ""))
    return subprocess.run([sys.executable, "-m", "dynamic_pdf.cli", *args], capture_output=True, text=True, env=env)


def test_cli_variants_writes_and_explains_the_designs(tmp_path):
    src = tmp_path / "proposal.md"
    src.write_text(fixture_text("proposal.md"), encoding="utf-8")
    brand = tmp_path / "brand.json"
    brand.write_text(json.dumps({"primary": "#0B5394"}), encoding="utf-8")
    r = _cli("variants", str(src), "-o", str(tmp_path / "out"), "-n", "2", "--brand", str(brand))
    assert r.returncode == 0, r.stderr
    decisions = json.loads((tmp_path / "out" / "decisions.json").read_text(encoding="utf-8"))
    assert decisions["recommended"] and f"recommended: {decisions['recommended']}" in r.stdout
    assert (tmp_path / "out" / f"{decisions['recommended']}.pdf").exists()
    r = _cli("render", str(src), "-o", str(tmp_path / "p.pdf"), "--direction", "auto", "--grammar",
             "--brand", str(brand))
    assert r.returncode == 0, r.stderr
    assert "design: " in r.stdout and (tmp_path / "p.pdf").exists()


# ── the scoreboard ─────────────────────────────────────────────────────────────────────

def _scoreboard():
    sys.path.insert(0, os.path.join(ROOT, "benchmarks"))
    import scoreboard
    return scoreboard


def test_scoreboard_budgets_catch_a_regression():
    sb = _scoreboard()
    summary = {"forecast_page_exact": 0.9, "forecast_score_mae": 1.0, "variants3_median_s": 1.0}
    budgets = sb.budgets_from(summary)
    assert budgets["forecast_page_exact"] == {"min": 0.9} and budgets["variants3_median_s"] == {"max": 2.0}
    assert sb.compare(summary, budgets) == []
    worse = dict(summary, forecast_page_exact=0.8, variants3_median_s=2.5)
    assert len(sb.compare(worse, budgets)) == 2


def test_scoreboard_runs_and_the_committed_baseline_has_budgets(tmp_path):
    sb = _scoreboard()
    with open(os.path.join(ROOT, "benchmarks", "scoreboard_baseline.json"), encoding="utf-8") as f:
        base = json.load(f)
    assert set(base["budgets"]) <= set(sb.METRICS) and base["summary"]["docs"] >= 15
    strict = tmp_path / "budgets.json"
    strict.write_text(json.dumps({"budgets": {"forecast_page_exact": {"min": 1.01}}}), encoding="utf-8")
    code = sb.main([str(tmp_path / "run"), "--docs", "memo", "--quick", "--no-office", "--budgets", str(strict)])
    out = json.loads((tmp_path / "run" / "scoreboard.json").read_text(encoding="utf-8"))
    assert code == 1 and out["summary"]["docs"] == 1 and (tmp_path / "run" / "scoreboard.md").exists()


def test_each_refinement_is_chosen_from_the_last_kept_render(monkeypatch):
    # an integration slip once chose every step from the first render, so a design lost
    # the page its later steps would have pulled back
    import stress_docs
    seen, kept = [], []
    real_ranked, real_trial = vmod._Runner._ranked, vmod._Runner._trial

    def ranked(self, direction, why, critique, *a):
        seen.append(critique)
        return real_ranked(self, direction, why, critique, *a)

    def trial(self, *a, **k):
        state = real_trial(self, *a, **k)
        kept.append(state[3])
        return state

    monkeypatch.setattr(vmod._Runner, "_ranked", ranked)
    monkeypatch.setattr(vmod._Runner, "_trial", trial)
    stress_docs.academic_paper().design_variants(families=["executive_premium"])
    assert len(seen) >= 2 and all(s is k for s, k in zip(seen[1:], kept))
