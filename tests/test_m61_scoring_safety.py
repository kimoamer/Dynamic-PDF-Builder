"""M6.1: trustworthy scoring, ranking safety, efficiency and chart composition."""
import io
import pytest
import pymupdf
from dynamic_pdf import DocumentBuilder, BlockRenderError, AssetError
from dynamic_pdf.intelligence import Composer, Geometry, Region, score_layout
from dynamic_pdf.intelligence.geometry import PageInfo, union_area, union_length
from dynamic_pdf.intelligence.scoring import DENSE_CAP
from dynamic_pdf.layout.engine import LayoutEngine
from dynamic_pdf.schema.blocks import (CoverPageBlock, ImageBlock, ParagraphBlock,
                                       TOCBlock)
from dynamic_pdf.schema.document import Document
from dynamic_pdf.themes import get_theme
from conftest import fixture_text
from stress_docs import STRESS

T = get_theme("claude")


def _rendered_score(b):
    doc, theme = b._prepared()
    g = Geometry()
    LayoutEngine(doc, theme=theme, geometry=g).render(io.BytesIO())
    return score_layout(g, doc, theme)


def _geo(pages, regions):
    g = Geometry()
    for p in range(1, pages + 1):
        g.pages[p] = PageInfo(p, "main", 780, 60, 72, 450)
    g.regions = regions
    return g


# ── scoring correctness ─────────────────────────────────────────────────

def test_nearly_empty_single_page_is_not_perfectly_utilized():
    s = _rendered_score(DocumentBuilder().heading("Quarterly note").paragraph("Revenue grew.").design())
    assert s.pages[0].role == "final"
    assert s.metrics["utilization"] < 0.1           # previously a free 1.0
    full = _rendered_score(DocumentBuilder().heading("Report")
                           .paragraph("Revenue grew strongly in every region. " * 40).design())
    assert full.metrics["utilization"] > s.metrics["utilization"] + 0.3


def test_no_body_pages_never_defaults_to_full_utilization():
    d = Document(blocks=[CoverPageBlock(title="T"), TOCBlock()])
    g = _geo(2, [Region(1, "main", 600, 560, 72, 300, 0, "structure"),
                 Region(2, "main", 780, 700, 72, 522, 1, "structure")])
    assert score_layout(g, d, T).metrics["utilization"] < 1.0


def test_sparse_cover_is_legitimate():
    b = DocumentBuilder().cover_page("Annual Report", subtitle="2026").heading("Intro")
    for _ in range(3):
        b.paragraph("Body text continues across the page. " * 90)
    s = _rendered_score(b.design("executive_report"))
    cover = s.pages[0]
    assert cover.role == "cover" and cover.fill < 0.2 and cover.wasted == 0
    assert s.metrics["wasted"] == 0


def test_partially_filled_last_page_is_not_counted_or_penalized():
    b = DocumentBuilder().heading("Long")
    for _ in range(5):
        b.paragraph("Body text continues across the page. " * 60)
    s = _rendered_score(b.design())
    last = s.pages[-1]
    assert last.role == "final" and last.wasted == 0
    body = [p.occupancy for p in s.pages if p.role == "body"]
    assert s.metrics["utilization"] == pytest.approx(
        sum(min(o, DENSE_CAP) for o in body) / len(body) / DENSE_CAP, abs=1e-3)


def test_tiny_spill_final_page_counts_as_waste():
    d = Document(blocks=[ParagraphBlock(text="a"), ParagraphBlock(text="b")])
    g = _geo(2, [Region(1, "main", 780, 70, 72, 522, 0, "body"),
                 Region(2, "main", 780, 760, 72, 522, 1, "body")])
    s = score_layout(g, d, T)
    assert s.pages[1].role == "final" and s.pages[1].wasted > 0


def test_overlapping_regions_are_not_double_counted():
    assert union_area([(0, 10, 0, 10), (5, 15, 0, 10)]) == 150
    assert union_area([(0, 10, 0, 10), (0, 10, 0, 10)]) == 100
    assert union_length([(0, 5), (3, 8), (10, 12)]) == 10
    d = Document(blocks=[ParagraphBlock(text="a"), ParagraphBlock(text="b"), ParagraphBlock(text="c")])
    one = _geo(2, [Region(1, "main", 780, 400, 72, 522, 0, "body"),
                   Region(1, "main", 780, 400, 72, 522, 1, "body"),
                   Region(2, "main", 780, 700, 72, 522, 2, "body")])
    assert one.pages and score_layout(one, d, T).pages[0].fill == pytest.approx(380 / 720, abs=1e-3)


def test_dense_pages_earn_no_extra_utilization():
    d = Document(blocks=[ParagraphBlock(text=str(i)) for i in range(4)])
    def util(width):
        g = _geo(3, [Region(1, "main", 780, 60, 72, 72 + width, 0, "body"),
                     Region(2, "main", 780, 60, 72, 72 + width, 1, "body"),
                     Region(3, "main", 780, 700, 72, 522, 2, "body"),
                     Region(3, "main", 690, 600, 72, 522, 3, "body")])
        return score_layout(g, d, T).metrics["utilization"]
    assert util(450) == util(0.9 * 450) == 1.0        # 90 % vs 100 % area: both capped


def test_spacers_are_not_content_density():
    b = DocumentBuilder().heading("Gap").spacer(400).paragraph("after").design()
    s = _rendered_score(b)
    assert s.pages[0].fill < 0.2


# ── ranking safety & fallbacks ──────────────────────────────────────────

class _FakeRanker:
    def __init__(self, prefer):
        self.prefer = prefer

    def rank(self, metrics):
        return [1.0 if m.get("pages") == self.prefer else 0.0 for m in metrics]


def test_ranker_cannot_pick_a_candidate_below_the_baseline_policy(monkeypatch, tmp_path):
    import dynamic_pdf.intelligence.ranker as R
    b0 = STRESS["financial_complex"](str(tmp_path)).design().compose("smart")
    b0.render()
    rendered = [c for c in b0.last_composition.candidates if c.rendered]
    # demand an impossible gain: no candidate is eligible, ranker must not override
    monkeypatch.setattr(R, "load_optional", lambda p: _FakeRanker(prefer=rendered[-1].pages))
    b = STRESS["financial_complex"](str(tmp_path)).design().compose("smart", ranker_model="x.txt",
                                                                    min_gain=1000)
    b.render()
    r = b.last_composition
    assert r.strategy == "baseline"
    assert all(c.rejected for c in r.candidates if c.rendered and c.name != "baseline")


def test_ranker_may_choose_among_eligible_layouts_only(monkeypatch, tmp_path):
    import dynamic_pdf.intelligence.ranker as R
    monkeypatch.setattr(R, "load_optional", lambda p: _FakeRanker(prefer=-1))   # prefers nobody
    b = STRESS["chart_report"](str(tmp_path)).design().compose("smart", ranker_model="x.txt")
    b.render()
    r = b.last_composition
    chosen = next(c for c in r.candidates if c.name == r.strategy)
    base = r.candidates[0]
    assert chosen is base or chosen.metrics["adjusted"] >= base.score + 1.0
    assert any("learned ranker among eligible" in x for x in r.reasons)


def test_final_output_is_validated_after_repair(monkeypatch, tmp_path):
    from dynamic_pdf.intelligence import composer as C
    from dynamic_pdf.intelligence.scoring import LayoutScore
    orig = C.Composer._repair

    def broken_repair(self, lay, budget):
        out = orig(self, lay, budget)
        if self.report.strategy != "baseline" and not getattr(self, "_broke", False):
            self._broke = True
            out.score = LayoutScore(valid=False, score=0.0, hard_errors=["synthetic regression"])
        return out
    monkeypatch.setattr(C.Composer, "_repair", broken_repair)
    b = STRESS["chart_report"](str(tmp_path)).design().compose("smart")
    pdf = b.render()
    r = b.last_composition
    assert r.strategy == "baseline" and r.status == "fallback"
    assert any("failed final validation" in f for f in r.fallbacks)
    assert pdf.startswith(b"%PDF")


def test_prediction_failure_keeps_the_designed_render(monkeypatch, tmp_path):
    from dynamic_pdf.intelligence import composer as C
    def boom(*a, **k):
        raise RuntimeError("measurement exploded")
    monkeypatch.setattr(C, "measure_blocks", boom)
    b = STRESS["technical_manual"](str(tmp_path)).design().compose("smart")
    pdf = b.render()
    r = b.last_composition
    assert r.strategy == "baseline" and r.status == "fallback" and r.render_attempts == 1
    assert any("analysis failed" in f for f in r.fallbacks)
    assert pymupdf.open(stream=pdf, filetype="pdf").page_count >= 1


def test_composer_crash_falls_back_to_designed_render(monkeypatch):
    from dynamic_pdf.intelligence import composer as C
    monkeypatch.setattr(C.Composer, "_compose", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("bug")))
    b = DocumentBuilder.from_markdown(fixture_text("manual.md")).design().compose("smart")
    pdf = b.render()
    assert pdf.startswith(b"%PDF")
    r = b.last_composition
    assert r.status == "fallback" and any("composition failed" in f for f in r.fallbacks)


def test_document_errors_still_raise_with_compose():
    b = DocumentBuilder().paragraph("x").add_block(ImageBlock(src="/missing.png")).compose("smart")
    with pytest.raises((BlockRenderError, AssetError)):
        b.render()


# ── efficiency ──────────────────────────────────────────────────────────

def test_preflight_skips_candidates_for_clean_documents():
    b = DocumentBuilder.from_markdown(fixture_text("letter.md")).design().compose("smart")
    b.render()
    r = b.last_composition
    assert r.preflight.startswith("clean") and r.render_attempts == 1
    assert [c.name for c in r.candidates] == ["baseline"]
    assert r.design_trial_renders >= 1                  # M5 page-fit renders are accounted for


def test_no_render_without_plausible_predicted_gain(tmp_path):
    b = STRESS["arabic_long_report"](str(tmp_path)).design().compose("smart")
    b.render()
    r = b.last_composition
    for c in r.candidates[1:]:
        assert c.rendered or c.rejected
        if c.rendered:
            assert c.predicted_score >= r.candidates[0].predicted_score + Composer.PRED_MARGIN


# ── chart-heavy composition ────────────────────────────────────────────

def test_chart_report_packs_two_charts_per_page_legibly(tmp_path):
    base = STRESS["chart_report"](str(tmp_path)).design()
    base_pages = pymupdf.open(stream=base.render(), filetype="pdf").page_count
    b = STRESS["chart_report"](str(tmp_path)).design().compose("smart")
    doc = pymupdf.open(stream=b.render(), filetype="pdf")
    r = b.last_composition
    assert doc.page_count < base_pages
    assert r.candidates[0].metrics["separated_figures"] == 0   # design() already keeps intros with exhibits
    chosen = next(c for c in r.candidates if c.name == r.strategy)
    assert chosen.metrics["separated_figures"] == 0
    # at the reviewed 11.5pt body one page ends at 58% (threshold 62%); the baseline wastes 0.44
    assert chosen.metrics["wasted"] <= 0.06 < r.candidates[0].metrics["wasted"]
    sizes = [s["size"] for p in doc for bl in p.get_text("dict")["blocks"] for ln in bl.get("lines", [])
             for s in ln["spans"] if s["text"].strip()]
    assert min(sizes) >= 6.0                            # chart text redrawn natively, not shrunk
    # chart titles are vector paths; each chart's intro ("Figure N shows …") is kept
    # with its chart (separated_figures == 0), so intros per page = charts per page
    figs_per_page = [sum(1 for t in p.get_text().split("\n") if t.startswith("Figure ") and " shows " in t)
                     for p in doc]
    assert max(figs_per_page) >= 2
    d, _ = b._prepared()
    sized = [blk for blk in d.blocks if (blk.hints or {}).get("figure_size")]
    assert sized and all(blk.hints["figure_size"][1] >= 2.6 for blk in sized)
    import docx as _docx
    dx = _docx.Document(io.BytesIO(b.render_docx()))
    assert len(dx.inline_shapes) == 6                   # same charts, native Word pictures
