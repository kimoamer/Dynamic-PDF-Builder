"""
Intelligent page composer — bounded, deterministic, CPU-only.

Pipeline (one call, no nested loops):

1. Analyze the designed document once (block measurements, frame geometry).
2. Choose ≤ ``max_candidates`` layout strategies from structure and purpose.
3. Predict each candidate by simulated pagination; drop invalid ones
   (hard constraints) before rendering.
4. Render the baseline plus the best predicted candidates — at most
   ``max_renders`` PDF renders — recording real occupied regions.
5. Score real geometry; select the best *valid* layout. The baseline is kept
   unless a candidate beats it by ``min_gain`` points.
6. Inspect the selected PDF (QA) and apply at most ``max_repairs`` repair renders.

Time and memory budgets are checked between steps; when exceeded, the best
layout found so far (or the baseline) is used and the fallback is reported.
All state is local to one ``Composer`` instance (thread-safe per request).
"""
from __future__ import annotations

import io
import time
import warnings
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from .analysis import measure_blocks, simulate
from .candidates import CandidateInvalid, apply as apply_candidate, choose
from .geometry import Geometry
from .scoring import LayoutScore, PageMetric, hard_typography_errors, score_layout


class ComposeOptions(BaseModel):
    mode: str = "smart"                 # "smart" | "off"
    max_candidates: int = 4
    max_renders: int = 3                # PDF renders for candidate selection (incl. baseline)
    max_repairs: int = 2                # extra PDF renders to repair QA findings
    min_gain: float = 1.0               # score points a candidate must win by
    time_budget_s: float = 60.0
    memory_budget_mb: float = 1024.0
    measure_memory: bool = False        # tracemalloc peak (process-global: benchmarks only)
    qa: bool = True                     # inspect the selected PDF (needs PyMuPDF)
    ranker_model: Optional[str] = None  # optional LightGBM text model (valid candidates only)


class CandidateResult(BaseModel):
    name: str
    reason: str = ""
    changes: List[str] = Field(default_factory=list)
    predicted_score: Optional[float] = None
    predicted_pages: Optional[int] = None
    rendered: bool = False
    score: Optional[float] = None
    pages: Optional[int] = None
    valid: Optional[bool] = None
    hard_errors: List[str] = Field(default_factory=list)
    metrics: Dict[str, float] = Field(default_factory=dict)
    rejected: Optional[str] = None


class CompositionReport(BaseModel):
    mode: str = "smart"
    strategy: str = "baseline"
    reasons: List[str] = Field(default_factory=list)
    candidates: List[CandidateResult] = Field(default_factory=list)
    pages: List[PageMetric] = Field(default_factory=list)
    page_count: int = 0
    simulations: int = 0
    render_attempts: int = 0
    repair_renders: int = 0
    time_s: float = 0.0
    cpu_s: float = 0.0
    peak_memory_mb: Optional[float] = None
    rss_peak_mb: Optional[float] = None
    corrections: List[str] = Field(default_factory=list)
    qa: Dict[str, str] = Field(default_factory=dict)
    fallbacks: List[str] = Field(default_factory=list)
    unverified: List[str] = Field(default_factory=list)
    status: str = "ok"                  # ok | fallback (designed layout used) | failed
    preflight: str = ""                 # predicted issues, or "clean: …" (no candidates tried)
    final_score: Optional[float] = None
    design_trial_renders: int = 0       # renders spent by design page-fitting before composition


def _rss_mb() -> Optional[float]:
    try:
        import resource
        import sys
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return peak / (1024 * 1024) if sys.platform == "darwin" else peak / 1024
    except Exception:
        return None


class Composer:
    def __init__(self, options: Optional[ComposeOptions] = None, policy=None):
        self.o = options or ComposeOptions()
        self.policy = policy
        self.cache: dict = {}             # request-local figure cache shared by all renders
        self.report = CompositionReport(mode=self.o.mode)
        self.pdf_qa = None                # QAReport of the selected PDF
        self._t0 = self._c0 = 0.0
        self._rss0: Optional[float] = None

    # ── budgets ──
    def _over_budget(self) -> Optional[str]:
        if time.perf_counter() - self._t0 > self.o.time_budget_s:
            return f"time budget {self.o.time_budget_s:g}s exceeded"
        if self.o.measure_memory:
            import tracemalloc
            if tracemalloc.is_tracing():
                cur, _ = tracemalloc.get_traced_memory()
                if cur / 2 ** 20 > self.o.memory_budget_mb:
                    return f"memory budget {self.o.memory_budget_mb:g}MB exceeded"
        rss = _rss_mb()
        if rss is not None and self._rss0 is not None and rss - self._rss0 > self.o.memory_budget_mb:
            return f"memory budget {self.o.memory_budget_mb:g}MB exceeded"
        return None

    # ── rendering ──
    def _render(self, doc, theme) -> Tuple[bytes, Geometry, object]:
        from ..layout.engine import LayoutEngine
        geo = Geometry()
        eng = LayoutEngine(doc, policy=self.policy, theme=theme, geometry=geo, cache=self.cache)
        buf = io.BytesIO()
        eng.render(buf)
        self.report.render_attempts += 1
        return buf.getvalue(), geo, eng

    def _predict(self, doc, theme) -> Tuple[LayoutScore, int, list]:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ms, fg = measure_blocks(doc, theme, self.policy, self.cache)
        geo = simulate(ms, fg)
        self.report.simulations += 1
        return score_layout(geo, doc, theme), len(geo.pages), ms

    # ── main entry ──
    def compose(self, doc, theme, profile: str, stats) -> Tuple[object, object, bytes, object]:
        """Returns (doc, theme, pdf_bytes, LayoutEngine) of the selected layout."""
        import tracemalloc
        started_tracing = False
        if self.o.measure_memory and not tracemalloc.is_tracing():
            tracemalloc.start()
            started_tracing = True
        self._t0, self._c0, self._rss0 = time.perf_counter(), time.process_time(), _rss_mb()
        try:
            return self._compose(doc, theme, profile, stats)
        finally:
            r = self.report
            r.time_s = round(time.perf_counter() - self._t0, 3)
            r.cpu_s = round(time.process_time() - self._c0, 3)
            r.rss_peak_mb = round(_rss_mb(), 1) if _rss_mb() is not None else None
            if self.o.measure_memory and tracemalloc.is_tracing():
                r.peak_memory_mb = round(tracemalloc.get_traced_memory()[1] / 2 ** 20, 1)
                if started_tracing:
                    tracemalloc.stop()

    # ── selection policy ──
    PAGE_PENALTY = 1.5          # score points per page added vs the baseline
    PRED_MARGIN = 0.25          # predicted gain needed before a candidate is rendered

    def _adjusted(self, s: LayoutScore, pages: int, base_pages: int) -> float:
        return s.score - self.PAGE_PENALTY * max(0, pages - base_pages)

    def _eligible(self, s: LayoutScore, pages: int, base: LayoutScore, base_pages: int) -> bool:
        """Baseline non-regression policy — the *only* way a candidate can be selected
        (deterministically or by the optional ranker)."""
        if not s.valid:
            return False
        if not base.valid:
            return True
        return self._adjusted(s, pages, base_pages) >= base.score + self.o.min_gain

    @staticmethod
    def preflight(pred: LayoutScore) -> Optional[str]:
        """None when the predicted designed layout has no measurable layout issue."""
        m = pred.metrics
        issues = []
        if not pred.valid:
            issues.append("predicted hard violations")
        if m.get("wasted", 0) > 0.02:
            issues.append(f"wasted space {m['wasted']}")
        if m.get("separated_figures", 0):
            issues.append(f"{int(m['separated_figures'])} figure(s) separated from their intro")
        if m.get("efficiency", 1) < 1.0:
            issues.append(f"pagination efficiency {m['efficiency']}")
        if m.get("tables", 1) < 1.0:
            issues.append("table orphan pieces")
        if m.get("placement", 1) < 1.0:
            issues.append("figure placement")
        if m.get("readability", 1) < 0.97:
            issues.append(f"readability {m['readability']}")
        return "; ".join(issues) or None

    def _plan(self, doc, theme, profile, stats):
        """Predict the baseline and the candidates (no rendering)."""
        r = self.report
        base_pred, base_pages, measures = self._predict(doc, theme)
        issues = self.preflight(base_pred)
        r.preflight = issues or "clean: no measurable layout issue predicted"
        if not issues:
            return base_pred, base_pages, []
        from .analysis import frame_geometry
        fg = frame_geometry(doc, theme)
        page_w = fg.width + theme.spacing.page_margin_left + theme.spacing.page_margin_right
        shortlist = []
        for cand in choose(stats, profile, base_pages, self.o.max_candidates):
            res = CandidateResult(name=cand.name, reason=cand.reason)
            r.candidates.append(res)
            reason = self._over_budget()
            if reason:
                res.rejected = f"not evaluated: {reason}"
                r.fallbacks.append(reason)
                break
            try:
                d, t, changes = apply_candidate(cand.name, doc, theme, page_w, measures)
            except CandidateInvalid as e:
                res.rejected = f"invalid: {e}"
                continue
            except Exception as e:  # a candidate must never break composition
                res.rejected = f"construction failed: {type(e).__name__}: {e}"
                continue
            res.changes = changes
            typo = hard_typography_errors(t, d)
            if typo:
                res.rejected = "; ".join(typo)
                continue
            try:
                pred, pages, _ = self._predict(d, t)
            except Exception as e:
                res.rejected = f"prediction failed: {type(e).__name__}: {e}"
                continue
            res.predicted_score, res.predicted_pages = pred.score, pages
            if not pred.valid:
                res.rejected = "predicted: " + "; ".join(pred.hard_errors[:3])
                continue
            if pred.score < base_pred.score + self.PRED_MARGIN:
                res.rejected = "no plausible improvement predicted"
                continue
            shortlist.append((res, d, t))
        shortlist.sort(key=lambda x: -x[0].predicted_score)
        return base_pred, base_pages, shortlist

    def _compose(self, doc, theme, profile, stats):
        r = self.report
        baseline = CandidateResult(name="baseline", reason="designed layout (M5 engine)")
        r.candidates.append(baseline)
        # 1–3. analysis + prediction; a failure here must not affect the baseline
        try:
            base_pred, _, shortlist = self._plan(doc, theme, profile, stats)
            baseline.predicted_score = base_pred.score
        except Exception as e:
            r.fallbacks.append(f"analysis failed ({type(e).__name__}: {e}); designed layout used")
            r.status = "fallback"
            shortlist = []

        # 4. baseline render (errors here are the document's own, as without compose())
        pdf, geo, eng = self._render(doc, theme)
        base_score = score_layout(geo, doc, theme)
        base_pages = len(geo.pages)
        self._fill(baseline, base_score, base_pages)
        base_entry = (baseline, doc, theme, pdf, eng, base_score, geo)
        eligible = []
        for res, d, t in shortlist:
            if r.render_attempts >= self.o.max_renders:
                res.rejected = res.rejected or "not rendered (render budget)"
                continue
            reason = self._over_budget()
            if reason:
                res.rejected = f"not rendered: {reason}"
                r.fallbacks.append(reason)
                break
            try:
                cpdf, cgeo, ceng = self._render(d, t)
                cs = score_layout(cgeo, d, t)
            except Exception as e:
                res.rejected = f"render failed: {type(e).__name__}: {e}"
                r.fallbacks.append(f"candidate {res.name} failed to render; ignored")
                continue
            self._fill(res, cs, len(cgeo.pages))
            res.metrics["adjusted"] = round(self._adjusted(cs, len(cgeo.pages), base_pages), 2)
            if self._eligible(cs, len(cgeo.pages), base_score, base_pages):
                eligible.append((res, d, t, cpdf, ceng, cs, cgeo))
            elif cs.valid:
                res.rejected = "below the baseline non-regression threshold"

        # 5. selection: deterministic, optionally re-ranked — both only among
        #    candidates that passed the non-regression policy (plus the baseline)
        best = max(eligible, key=lambda e: e[0].metrics["adjusted"], default=base_entry)
        best = self._apply_ranker(best, eligible, base_entry)
        chosen, d, t, pdf, eng, s, geo = best
        r.strategy = chosen.name
        self._explain(chosen, baseline, base_score, s)

        # 6. QA + bounded repairs, then validate what will actually be delivered
        repairs_left = self.o.max_repairs
        d2, t2, pdf2, eng2, s2, used = self._repair(d, t, pdf, eng, s, repairs_left)
        if chosen is not baseline and (not s2.valid or s2.score < base_score.score):
            r.fallbacks.append(f"{chosen.name} failed final validation after repair "
                               f"({'; '.join(s2.hard_errors[:2]) or f'score {s2.score} < {base_score.score}'}); "
                               "designed layout used")
            r.strategy = "baseline"
            r.status = "fallback"
            d2, t2, pdf2, eng2, s2, _ = self._repair(doc, theme, base_entry[3], base_entry[4],
                                                    base_score, repairs_left - used)
        elif s.valid and not s2.valid:
            r.fallbacks.append("repair produced an invalid layout; pre-repair layout kept")
            d2, t2, pdf2, eng2, s2 = d, t, pdf, eng, s
        if not s2.valid:
            r.status = "failed"
            r.reasons.append("delivered layout still violates: " + "; ".join(s2.hard_errors[:3]))
        r.final_score = s2.score
        r.pages = s2.pages
        r.page_count = len(s2.pages)
        return d2, t2, pdf2, eng2

    def _explain(self, chosen, baseline, base_score, s):
        r = self.report
        if chosen is baseline:
            beaten = [c for c in r.candidates if c.rendered and c is not baseline]
            r.reasons.append("kept the designed layout: no candidate was objectively better"
                             + (f" (best alternative {max(beaten, key=lambda c: c.score or 0).name} "
                                f"{max(c.score or 0 for c in beaten):.1f} vs {base_score.score:.1f})" if beaten else ""))
            if not base_score.valid:
                r.reasons.append("baseline has hard violations; repairs follow")
            return
        m0, m1 = base_score.metrics, s.metrics
        r.reasons.append(f"{chosen.name}: score {s.score:.1f} vs baseline {base_score.score:.1f}")
        for k in ("pages", "wasted", "utilization", "readability", "separated_figures"):
            if m0.get(k) != m1.get(k):
                r.reasons.append(f"{k} {m0.get(k)} → {m1.get(k)}")
        r.reasons += chosen.changes

    def _apply_ranker(self, best, eligible, base_entry):
        """Optional learned re-ranking among the baseline and *eligible* candidates."""
        if not self.o.ranker_model:
            return best
        from .ranker import load_optional
        ranker = load_optional(self.o.ranker_model)
        if ranker is None:
            self.report.fallbacks.append("ranker unavailable (lightgbm or model missing); "
                                         "deterministic selection used")
            return best
        pool = ([base_entry] if base_entry[5].valid else []) + list(eligible)
        if len(pool) < 2:
            return best
        try:
            scores = ranker.rank([e[5].metrics for e in pool])
        except Exception as e:
            self.report.fallbacks.append(f"ranker failed ({type(e).__name__}); deterministic selection used")
            return best
        top = max(range(len(pool)), key=lambda k: scores[k])
        self.report.reasons.append("learned ranker among eligible layouts: " + ", ".join(
            f"{e[0].name}={sc:.2f}" for e, sc in zip(pool, scores)))
        return pool[top]

    def _fill(self, res: CandidateResult, s: LayoutScore, pages: int):
        res.rendered = True
        res.score, res.valid, res.pages = s.score, s.valid, pages
        res.hard_errors, res.metrics = s.hard_errors, s.metrics

    def _repair(self, d, t, pdf, eng, s, budget: int):
        """QA the PDF; at most ``budget`` repair renders. Returns (d, t, pdf, eng, score, used)."""
        r = self.report
        used = 0
        if not self.o.qa:
            r.unverified.append("pdf_visual_qa (disabled)")
            return d, t, pdf, eng, s, used
        try:
            from ..qa.pdf_checks import check_pdf
        except Exception:
            r.unverified.append("pdf_visual_qa (PyMuPDF not installed)")
            return d, t, pdf, eng, s, used
        from ..core.normalize import normalize
        from ..qa.loop import _propose_fixes, glyph_findings, qa_context
        while True:
            sp = t.spacing
            try:
                rep = check_pdf(pdf, margins={"left": sp.page_margin_left, "right": sp.page_margin_right},
                                heading_texts=[o.text for o in normalize(d).outline], **qa_context(d, t))
            except Exception as e:
                r.unverified.append(f"pdf_visual_qa ({type(e).__name__})")
                break
            rep.findings += glyph_findings(normalize(d), t)
            rep.attempts = used + 1
            rep.fixes_applied = list(r.corrections)
            r.qa["pdf"] = rep.summary()
            self.pdf_qa = rep
            if not rep.errors or used >= budget:
                break
            fixes = _propose_fixes(d.blocks, rep, {})
            if not fixes or self._over_budget():
                break
            d = d.model_copy(deep=True)
            for idx, hint, why in fixes:
                b = d.blocks[idx]
                b.hints = {**(b.hints or {}), **hint}
                r.corrections.append(why)
            d.blocks = [b for b in d.blocks if not (b.hints or {}).get("skip")]
            pdf, geo, eng = self._render(d, t)
            used += 1
            r.repair_renders += 1
            r.render_attempts -= 1          # counted separately
            s = score_layout(geo, d, t)
        return d, t, pdf, eng, s, used
