"""M6: intelligent page composer — constraints, selection, budgets, API, CLI."""
import io
import re
import socket
import subprocess
import sys
import threading
import pytest
import pymupdf
from dynamic_pdf import DocumentBuilder
from dynamic_pdf.intelligence import Geometry, Region, score_layout
from dynamic_pdf.intelligence.analysis import measure_blocks, simulate
from dynamic_pdf.intelligence.geometry import PageInfo
from dynamic_pdf.layout.engine import LayoutEngine
from dynamic_pdf.schema.document import Document
from dynamic_pdf.schema.blocks import HeadingBlock, ParagraphBlock, TableBlock
from conftest import fixture_text, docx_text
from stress_docs import STRESS, technical_manual

A = None


def _smart(b, **kw):
    return b.design().compose("smart", **kw)


# ── geometry & prediction ────────────────────────────────────────────────

def test_engine_records_regions_for_every_block():
    b = DocumentBuilder.from_markdown(fixture_text("financial.md")).design()
    doc, theme = b._prepared()
    geo = Geometry()
    LayoutEngine(doc, theme=theme, geometry=geo).render(io.BytesIO())
    placed = {r.block for r in geo.regions}
    assert placed == set(range(len(doc.blocks)))
    table = [r for r in geo.regions if r.role == "table"]
    assert len(table) >= 2 and len({r.page for r in table}) >= 2      # split across pages
    assert all(geo.pages[r.page].frame_bottom - 1 <= r.bottom <= r.top <= geo.pages[r.page].frame_top + 1
               for r in geo.regions)


@pytest.mark.parametrize("name", ["financial_complex", "academic_paper", "bilingual_corporate"])
def test_simulation_predicts_page_count(name, tmp_path):
    b = STRESS[name](str(tmp_path)).design()
    doc, theme = b._prepared()
    ms, fg = measure_blocks(doc, theme)
    pred = len(simulate(ms, fg).pages)
    geo = Geometry()
    eng = LayoutEngine(doc, theme=theme, geometry=geo)
    eng.render(io.BytesIO())
    assert abs(pred - eng.page_count) <= 1


# ── hard constraints in the scorer ───────────────────────────────────────

def _geo(regions, pages=2):
    g = Geometry()
    for p in range(1, pages + 1):
        g.pages[p] = PageInfo(p, "main", 780, 60, 72, 450)
    g.regions = regions
    return g


def _doc(*blocks):
    return Document(blocks=list(blocks))


def test_scorer_rejects_lost_content_and_reordering():
    from dynamic_pdf.themes import get_theme
    t = get_theme("claude")
    d = _doc(ParagraphBlock(text="a"), ParagraphBlock(text="b"))
    lost = _geo([Region(1, "main", 780, 700, 72, 522, 0, "body")], 1)
    assert "not placed" in " ".join(score_layout(lost, d, t).hard_errors)
    swapped = _geo([Region(1, "main", 780, 700, 72, 522, 1, "body"),
                    Region(1, "main", 690, 600, 72, 522, 0, "body")], 1)
    s = score_layout(swapped, d, t)
    assert not s.valid and "reading order" in " ".join(s.hard_errors)


def test_scorer_rejects_stranded_heading_detached_caption_and_clipping():
    from dynamic_pdf.themes import get_theme
    t = get_theme("claude")
    d = _doc(HeadingBlock(text="H"), ParagraphBlock(text="p"),
             TableBlock(headers=["a"], rows=[["1"]], caption="c"))
    g = _geo([Region(1, "main", 780, 100, 72, 522, 1, "body"),
              Region(1, "main", 95, 70, 72, 522, 0, "heading", 1),        # heading last on page 1 …
              Region(2, "main", 780, 700, 72, 522, 1, "body")])
    # (reading order deliberately broken too; we only look for the heading rule here)
    assert any("stranded" in e for e in score_layout(g, d, t).hard_errors)
    g2 = _geo([Region(1, "main", 780, 100, 72, 522, 0, "heading", 1), Region(1, "main", 99, 98, 72, 522, 1, "body"),
               Region(1, "main", 90, 70, 72, 522, 2, "caption"), Region(2, "main", 780, 700, 72, 522, 2, "table")])
    assert any("detached" in e for e in score_layout(g2, d, t).hard_errors)
    g3 = _geo([Region(1, "main", 780, 40, 72, 522, 0, "heading", 1), Region(1, "main", 40, 30, 72, 522, 1, "body"),
               Region(1, "main", 30, 20, 72, 522, 2, "table")], 1)
    assert any("clipped" in e for e in score_layout(g3, d, t).hard_errors)


def test_layout_added_breaks_are_not_free_whitespace():
    """A candidate cannot buy a better score by inserting its own page breaks."""
    from dynamic_pdf.intelligence.scoring import forced_starts
    d = _doc(HeadingBlock(text="A"), ParagraphBlock(text="x"),
             HeadingBlock(text="B", hints={"break_before": True}), ParagraphBlock(text="y"))
    assert forced_starts(d) == set()


# ── composer behaviour ───────────────────────────────────────────────────

@pytest.mark.parametrize("name", list(STRESS))
def test_selected_layout_is_valid_bounded_and_never_worse(name, tmp_path):
    b = _smart(STRESS[name](str(tmp_path)))
    pdf = b.render()
    r = b.last_composition
    assert r.render_attempts <= 3 and r.repair_renders <= 2
    assert r.simulations <= 5
    base = r.candidates[0]
    chosen = next(c for c in r.candidates if c.name == r.strategy)
    assert chosen.valid
    assert chosen.score >= base.score
    assert r.page_count == pymupdf.open(stream=pdf, filetype="pdf").page_count
    if chosen is not base:
        assert r.reasons and chosen.pages <= base.pages + 1


def test_baseline_kept_when_no_candidate_is_better():
    b = _smart(DocumentBuilder.from_markdown(fixture_text("letter.md")))
    b.render()
    assert b.last_composition.strategy == "baseline"
    assert "kept the designed layout" in b.last_composition.reasons[0]


def test_manual_wasted_space_removed(tmp_path):
    b = _smart(technical_manual(str(tmp_path)))
    b.render()
    r = b.last_composition
    base = r.candidates[0]
    chosen = next(c for c in r.candidates if c.name == r.strategy)
    assert r.strategy != "baseline"
    assert chosen.metrics["wasted"] < base.metrics["wasted"]
    assert chosen.metrics["utilization"] > base.metrics["utilization"]


def test_deterministic(tmp_path):
    runs = []
    for _ in range(2):
        b = _smart(STRESS["chart_report"](str(tmp_path)))
        b.render()
        r = b.last_composition
        runs.append((r.strategy, r.page_count, [(c.name, c.score, c.predicted_score) for c in r.candidates]))
    assert runs[0] == runs[1]


def test_time_budget_falls_back_to_baseline(tmp_path):
    # a document with predicted issues, so candidates are tried and the budget is consulted
    b = _smart(STRESS["chart_report"](str(tmp_path)), time_budget_s=0.0)
    pdf = b.render()
    r = b.last_composition
    assert not r.preflight.startswith("clean")
    assert r.strategy == "baseline" and r.render_attempts == 1
    assert any("time budget" in f for f in r.fallbacks)
    assert pdf.startswith(b"%PDF")


def test_compose_off_is_classic_rendering():
    md = fixture_text("executive.md")
    a = DocumentBuilder.from_markdown(md).design().compose("off")
    a.render()
    assert a.last_composition is None
    with pytest.raises(ValueError):
        DocumentBuilder().compose("turbo")


def test_no_network_during_composition(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise AssertionError("network access attempted")
    monkeypatch.setattr(socket, "create_connection", boom)
    monkeypatch.setattr(socket, "getaddrinfo", boom)
    _smart(STRESS["chart_report"](str(tmp_path))).render()


def test_thread_local_state(tmp_path):
    names = ["financial_complex", "academic_paper", "bilingual_corporate"]
    seq = {}
    for n in names:
        b = _smart(STRESS[n](str(tmp_path)))
        b.render()
        seq[n] = (b.last_composition.strategy, b.last_composition.page_count)
    par, errors = {}, []

    def work(n):
        try:
            b = _smart(STRESS[n](str(tmp_path)))
            b.render()
            par[n] = (b.last_composition.strategy, b.last_composition.page_count)
        except Exception as e:      # pragma: no cover
            errors.append(e)
    th = [threading.Thread(target=work, args=(n,)) for n in names]
    [t.start() for t in th]
    [t.join() for t in th]
    assert not errors and par == seq


# ── composition hints render faithfully ──────────────────────────────────

def test_two_column_list_keeps_order_and_numbering():
    items = [f"Item {i:02d}" for i in range(1, 13)]
    b = DocumentBuilder().numbered_list(items).design()
    b._blocks[0].hints = {"columns": 2}
    text = pymupdf.open(stream=b.render(), filetype="pdf")[0].get_text()
    assert [int(n) for n in re.findall(r"Item (\d\d)", text)] == list(range(1, 13))
    assert "7." in text                         # right column continues numbering
    dx = docx_text(b.render_docx())
    assert [int(n) for n in re.findall(r"Item (\d\d)", dx)] == list(range(1, 13))


def test_fit_figure_shrinks_within_bounds(tmp_path):
    from dynamic_pdf.layout.factory import FitFigure
    from reportlab.platypus import Spacer
    f = FitFigure(Spacer(100, 200), min_scale=0.8)
    assert f.wrap(400, 300) == (100, 200)                      # fits: natural size
    w, h = f.wrap(400, 175)
    assert 160 <= h <= 175                                     # shrinks into the space
    assert f.wrap(400, 100)[1] == 200                          # below 80%: no shrink (moves)


# ── API / export / CLI ───────────────────────────────────────────────────

def test_export_both_with_compose_returns_report(tmp_path):
    res = (DocumentBuilder.from_markdown(fixture_text("manual.md")).design().compose("smart")
           .export_both(str(tmp_path / "out"), qa=True))
    c = res.composition
    for key in ("strategy", "candidates", "reasons", "pages", "render_attempts", "time_s", "cpu_s",
                "corrections", "qa", "fallbacks", "unverified"):
        assert key in c
    assert "pdf" in res.qa and "docx" in res.qa
    assert c["qa"].get("pdf", "").startswith("PDF QA")
    assert res.pdf_path.endswith(".pdf") and res.docx_path.endswith(".docx")


def test_composed_pdf_and_docx_share_decisions(tmp_path):
    b = _smart(STRESS["chart_report"](str(tmp_path)))
    b.render()
    d, _ = b._prepared()
    hinted = [i for i, blk in enumerate(d.blocks) if (blk.hints or {}).get("columns")]
    if hinted:
        import docx as _docx
        doc = _docx.Document(io.BytesIO(b.render_docx()))
        assert len(doc.tables) >= 2


def test_cli_compose_and_report(tmp_path):
    src = tmp_path / "in.md"
    src.write_text(fixture_text("manual.md"), encoding="utf-8")
    rep = tmp_path / "report.json"
    r = subprocess.run([sys.executable, "-m", "dynamic_pdf.cli", "render", str(src), "-o",
                        str(tmp_path / "o.pdf"), "--compose", "smart", "--report", str(rep)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "composition:" in r.stdout
    import json
    assert json.loads(rep.read_text())["render_attempts"] >= 1


# ── optional ranker ──────────────────────────────────────────────────────

def test_ranker_falls_back_without_a_usable_model(tmp_path):
    from dynamic_pdf.intelligence.variant_ranker import RankerRefused, load_model
    bad = tmp_path / "model.pkl"
    bad.write_bytes(b"\x80\x04pickle")
    with pytest.raises(RankerRefused):                  # only a JSON training record loads, never a pickle
        load_model(str(bad))
    b = _smart(DocumentBuilder.from_markdown(fixture_text("manual.md")), ranker_model=str(bad))
    b.render()
    assert any("ranker unavailable" in f for f in b.last_composition.fallbacks)


def test_figure_caption_at_page_end_is_not_detached(tmp_path):
    """Regression: figure captions sit below the image, so a caption ending a page
    together with its figure is not a detached caption (only table captions precede)."""
    from dynamic_pdf.qa import check_pdf
    from dynamic_pdf.qa.loop import qa_context
    b = _smart(technical_manual(str(tmp_path)))
    pdf = b.render()
    doc, theme = b._prepared()
    ctx = qa_context(doc, theme)
    assert "The operations dashboard" not in " ".join(ctx["captions"])
    rep = check_pdf(pdf, heading_texts=[o.text for o in b.semantic().outline], **ctx)
    assert not rep.errors, [f.message for f in rep.errors]
    assert b.last_composition.qa["pdf"].startswith("PDF QA PASS")


def test_candidates_refit_tables_to_their_own_width():
    """Regression: a narrower candidate reused column fractions planned for the
    baseline width and broke the 'Week' header mid-word."""
    from dynamic_pdf.intelligence.analysis import measure_blocks
    from dynamic_pdf.intelligence.candidates import apply
    b = DocumentBuilder.from_markdown(fixture_text("wide_data.md")).design()
    doc, theme = b._prepared()
    ms, fg = measure_blocks(doc, theme)
    page_w = fg.width + theme.spacing.page_margin_left + theme.spacing.page_margin_right
    d, t, changes = apply("compact", doc, theme, page_w, ms)
    if (t.spacing.page_margin_left, t.spacing.page_margin_right) != (
            theme.spacing.page_margin_left, theme.spacing.page_margin_right):
        assert any("re-fitted" in c for c in changes)
    smart = DocumentBuilder.from_markdown(fixture_text("wide_data.md")).design().compose("smart")
    words = re.findall(r"[A-Za-z]+", "\n".join(p.get_text() for p in
                                               pymupdf.open(stream=smart.render(), filetype="pdf")))
    assert "Week" in words and "Wee" not in words
