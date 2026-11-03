"""M6.2: unified quality status, final layout validation, Arabic table grouping."""
import hashlib
import io
import time
import unicodedata

import pymupdf

from dynamic_pdf import DocumentBuilder, ExportResult
from dynamic_pdf.intelligence import Composer, Geometry, score_layout
from dynamic_pdf.intelligence.analysis import measure_blocks, simulate
from dynamic_pdf.intelligence.composer import ComposeOptions, _Layout
from dynamic_pdf.intelligence.scoring import LayoutScore
from dynamic_pdf.layout.engine import LayoutEngine
from dynamic_pdf.qa.report import ERROR, Finding, QAReport
from conftest import docx_text, open_docx
from stress_docs import STRESS


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _qa(status: str) -> QAReport:
    rep = QAReport(format="pdf", pages=1)
    if status == "fail":
        rep.findings.append(Finding(severity=ERROR, code="overflow", message="text past the margin"))
    elif status == "unverified":
        rep.unverified.append("visual (PyMuPDF not installed)")
    return rep


def _bad_qa(pdf: bytes) -> QAReport:
    rep = QAReport(format="pdf", pages=1, sha256=_sha(pdf))
    rep.findings.append(Finding(severity=ERROR, code="clipped", message="synthetic clipped text"))
    return rep


def _small_doc():
    return (DocumentBuilder().meta(title="Gate")
            .heading("Summary").paragraph("Revenue grew in every region this quarter. " * 6)
            .table(["Region", "Revenue"], [["North", "1,200"], ["South", "980"]], caption="Revenue")
            .design())


# ── 1. unified status ───────────────────────────────────────────────────

def test_status_precedence_and_reasons():
    r = ExportResult(pdf_path="x.pdf")
    assert r.status == "ok" and r.status_reasons == []
    r.composition = {"status": "fallback", "strategy": "baseline",
                     "fallbacks": ["balanced failed final validation; designed layout restored"]}
    assert r.status == "fallback" and "fell back" in r.status_reasons[0]
    r.qa["pdf"] = _qa("unverified")
    assert r.status == "unverified"                       # a skipped check outranks fallback
    r.diagnostics = [{"level": "error", "message": "chart failed"}]
    assert r.status == "degraded"
    r.qa["docx"] = _qa("fail")
    assert r.status == "failed"
    assert any("docx QA failed" in x for x in r.status_reasons)


def test_failed_composition_is_never_reported_as_success():
    r = ExportResult(pdf_path="x.pdf")
    r.qa["pdf"] = _qa("pass")
    r.composition = {"status": "failed", "strategy": "baseline", "fallbacks": [],
                     "reasons": ["no valid layout: block 3 not placed"]}
    assert r.status == "failed" and "no valid layout" in r.status_reasons[0]


def test_export_reports_qa_of_the_delivered_bytes(tmp_path):
    path = tmp_path / "out.pdf"
    res = _small_doc().compose("smart").export(str(path))
    assert res.status == "ok", res.status_reasons
    assert res.qa["pdf"].sha256 == _sha(path.read_bytes())
    assert res.composition["status"] == "ok"


def test_skipped_qa_is_unverified_not_ok(tmp_path):
    res = _small_doc().compose("smart", qa=False).export(str(tmp_path / "out.pdf"))
    assert res.status == "unverified"
    assert res.composition["status"] == "unverified"
    assert any("disabled" in x for x in res.status_reasons)


def test_failed_qa_propagates_to_composition_and_export(monkeypatch, tmp_path):
    monkeypatch.setattr(Composer, "inspect", lambda self, d, t, pdf: _bad_qa(pdf))
    b = _small_doc().compose("smart", max_repairs=0)
    res = b.export(str(tmp_path / "out.pdf"))
    assert res.composition["status"] == "failed"
    assert res.status == "failed"
    assert any("QA clipped" in x for x in b.last_composition.reasons)


# ── 2. final layout validation ──────────────────────────────────────────

def test_repair_that_regresses_keeps_the_better_attempt(monkeypatch):
    import dynamic_pdf.qa.loop as loop
    doc, theme = _small_doc()._prepared_base()
    c = Composer(ComposeOptions(), None)
    c._t0 = time.perf_counter()              # budgets start when compose() starts
    pdf, geo, eng = c._render(doc, theme)
    good = _Layout(doc, theme, pdf, eng, score_layout(geo, doc, theme))
    calls = []

    def inspect(self, d, t, data):
        calls.append(data)
        return _bad_qa(data)                  # every attempt has one QA error
    monkeypatch.setattr(Composer, "inspect", inspect)
    monkeypatch.setattr(loop, "_propose_fixes", lambda blocks, rep, h: [(0, {"break_before": True}, "x")])
    real_render = Composer._render

    def render(self, d, t):
        out = real_render(self, d, t)
        return out[0], Geometry(), out[2]     # repaired layout loses all content
    monkeypatch.setattr(Composer, "_render", render)
    out = c._repair(good, 1)
    assert out is good and out.used == 1 and len(calls) == 2
    assert out.qa.sha256 == _sha(good.pdf)
    assert any("regressed" in f for f in c.report.fallbacks)


def test_candidate_below_min_gain_after_repair_restores_baseline(monkeypatch, tmp_path):
    orig = Composer._repair

    def degrade(self, lay, budget):
        out = orig(self, lay, budget)
        if self.report.strategy != "baseline" and not getattr(self, "_hit", False):
            self._hit = True
            s = out.score
            # still above the baseline, but no longer by min_gain
            out.score = LayoutScore(valid=True, score=self.report.candidates[0].score + 0.5,
                                    metrics=s.metrics, pages=s.pages)
        return out
    monkeypatch.setattr(Composer, "_repair", degrade)
    b = STRESS["chart_report"](str(tmp_path)).design().compose("smart")
    pdf = b.render()
    r = b.last_composition
    assert r.strategy == "baseline" and r.status == "fallback"
    assert any("min_gain" in f for f in r.fallbacks)
    _, _, _, _, composer = b._composed()
    assert composer.pdf_qa.sha256 == _sha(pdf)            # QA of the restored bytes
    assert r.page_count == pymupdf.open(stream=pdf, filetype="pdf").page_count


def test_crash_fallback_qa_describes_delivered_bytes(monkeypatch):
    monkeypatch.setattr(Composer, "_compose", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("bug")))
    b = _small_doc().compose("smart")
    pdf = b.render()
    _, _, _, _, composer = b._composed()
    assert composer.pdf_qa is not None and composer.pdf_qa.sha256 == _sha(pdf)
    assert b.last_composition.status == "fallback"


def test_candidates_never_add_more_than_one_page_or_lose_readability(tmp_path):
    for name in ("arabic_long_report", "chart_report"):
        b = STRESS[name](str(tmp_path)).design().compose("smart")
        b.render()
        r = b.last_composition
        base = r.candidates[0]
        chosen = next(c for c in r.candidates if c.name == r.strategy)
        assert chosen.pages <= base.pages + 1
        assert chosen.metrics["readability"] >= base.metrics["readability"] - 0.01


# ── 3. Arabic table grouping ────────────────────────────────────────────

def _first_last_pages(doc, theme):
    g = Geometry()
    LayoutEngine(doc, theme=theme, geometry=g, cache={}).render(io.BytesIO())
    first, last = {}, {}
    for reg in sorted(g.regions, key=lambda x: (x.page, -x.top)):
        first.setdefault(reg.block, reg.page)
        last[reg.block] = reg.page
    return first, last


def test_arabic_report_tables_stay_with_their_lead_in_text():
    b = STRESS["arabic_long_report"](None).design("auto").compose("smart")
    pdf = b.render()
    r = b.last_composition
    base = r.candidates[0]
    assert base.metrics["separated_figures"] == 3          # the M6.1 defect
    assert r.status == "ok" and r.strategy == "grouped"
    chosen = next(c for c in r.candidates if c.name == r.strategy)
    assert chosen.metrics["separated_figures"] == 0 and chosen.valid
    assert chosen.pages <= base.pages + 1
    d, t, _, _, _ = b._composed()
    first, last = _first_last_pages(d, t)
    for i, blk in enumerate(d.blocks):
        if blk.type == "table":
            assert last[i - 1] == first[i], f"table {i} opens a page without its lead-in text"
    # content, order and direction intact
    text = unicodedata.normalize("NFKC", "".join(pg.get_text() for pg in pymupdf.open(stream=pdf)))
    assert text.count("مؤشرات") >= 12                     # every table caption rendered
    assert d.meta.direction == "rtl" or d.meta.rtl
    assert [x.type for x in d.blocks] == [x.type for x in b._prepared_base()[0].blocks]


def test_keep_tail_splits_the_intro_instead_of_moving_it_whole():
    para = "Line of a long lead-in paragraph that wraps across several lines of text. " * 6
    b = DocumentBuilder().meta(title="Tail")
    b.paragraph("Filler paragraph. " * 110)
    b.paragraph(para)
    b.table(["Item", "Value"], [[f"Item {i}", str(i)] for i in range(8)], caption="Values")
    doc = b.build()
    doc.blocks[2].hints = {"keep_together": True}
    theme = b._prepared_base()[1] or __import__("dynamic_pdf.themes", fromlist=["x"]).get_theme("claude")
    first0, last0 = _first_last_pages(doc, theme)
    assert last0[1] < first0[2]                            # separated without the hint
    doc.blocks[1].hints = {"keep_tail_with_next": 2}
    first, last = _first_last_pages(doc, theme)
    assert first[1] < last[1] == first[2]                  # split: tail travels with the table
    assert first[2] == first0[2]                           # no page added
    ms, fg = measure_blocks(doc, theme)
    sim = simulate(ms, fg)
    sim_pages = {}
    for reg in sim.regions:
        sim_pages.setdefault(reg.block, set()).add(reg.page)
    assert max(sim_pages[1]) == min(sim_pages[2])          # the simulator predicts the same
    assert score_layout(sim, doc, theme).metrics["separated_figures"] == 0


def test_docx_keeps_lead_in_with_table_and_stays_editable(tmp_path):
    b = STRESS["arabic_long_report"](None).design("auto").compose("smart")
    data = b.render_docx()
    docx = open_docx(data)
    kept = [p for p in docx.paragraphs if p.paragraph_format.keep_with_next]
    assert len(docx.tables) == 12 and kept
    assert "مؤشرات" in docx_text(data)
