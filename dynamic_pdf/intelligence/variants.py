"""
Generate → render → evaluate → refine → select, for several designs of one document.

Each direction yields a complete design. Rendered pages are measured, weak ones get a
focused change and one more render while the budget lasts, and every design then passes
the hard gates or is rejected with its reasons. The recommendation is the valid design
that best fits the document and measures best, with both numbers shown. It is a
recommendation from heuristics, not a verdict on beauty.
"""
from __future__ import annotations

import io
import json
import os
import re
import time
import warnings
from dataclasses import dataclass, field, replace
from typing import Dict, List, Optional, Sequence

from pydantic import BaseModel, Field

from ..core.normalize import normalize
from ..design import BrandKit
from ..design.art_direction import Adjust, ArtDirectionPlan, content_changes, direct, read_brief, select_directions
from ..design.directions import DIRECTIONS, Direction
from ..i18n import LABELS
from ..qa.content_preservation import _fold
from .geometry import Geometry
from .scoring import score_layout


class VariantBudget(BaseModel):
    """Limits for one ``design_variants`` call. ReportLab cannot be stopped mid-render, so
    time is checked between renders; a design that starts in time may finish after it."""

    max_renders: int = Field(30, ge=1)
    max_refinements: int = Field(5, ge=0)        # per design
    max_seconds: float = Field(120.0, gt=0)
    max_output_mb: float = Field(160.0, gt=0)    # PDF and DOCX bytes held at once


class VariantReport(BaseModel):
    status: str                                  # valid | rejected | not_rendered
    pages: int = 0
    renders: int = 0
    seconds: float = 0.0
    fit: float = 0.0
    index: float = 0.0                           # heuristic ordering number, not a quality grade
    hard_failures: List[str] = Field(default_factory=list)
    heuristics: Dict[str, float] = Field(default_factory=dict)
    heuristic_label: str = ""
    observations: List[str] = Field(default_factory=list)
    refinements: List[str] = Field(default_factory=list)
    office: Optional[Dict] = None
    unverified: List[str] = Field(default_factory=list)
    grammar_rules: List[str] = Field(default_factory=list)   # approved rules this design used
    grammar_version: Optional[str] = None


@dataclass
class Variant:
    id: str
    name: str
    plan: Optional[ArtDirectionPlan]
    report: VariantReport
    pdf: Optional[bytes] = None
    docx: Optional[bytes] = None
    document: object = None
    theme: object = None

    @property
    def valid(self) -> bool:
        return self.report.status == "valid"


@dataclass
class VariantSet:
    variants: List[Variant]
    recommended: Optional[Variant]
    reasons: List[str]
    fallback: bool = False                       # no design passed: use the stable designed output
    stats: Dict = field(default_factory=dict)

    def __iter__(self):
        return iter(self.variants)

    def __len__(self):
        return len(self.variants)

    def to_dict(self) -> dict:
        return {"recommended": self.recommended.id if self.recommended else None, "reasons": self.reasons,
                "fallback": self.fallback, "stats": self.stats,
                "note": "the recommendation comes from fit rules and page measurements; no person has judged it",
                "variants": [{"id": v.id, "name": v.name, "report": v.report.model_dump(),
                              "plan": v.plan.explain() if v.plan else None} for v in self.variants]}

    def export(self, directory: str) -> Dict[str, Dict[str, str]]:
        """Write each valid design and ``decisions.json``. Returns the paths by design."""
        os.makedirs(directory, exist_ok=True)
        out: Dict[str, Dict[str, str]] = {}
        for v in self.variants:
            paths: Dict[str, str] = {}
            for ext, data in (("pdf", v.pdf), ("docx", v.docx)):
                if data and v.valid:
                    paths[ext] = os.path.join(directory, f"{v.id}.{ext}")
                    with open(paths[ext], "wb") as f:
                        f.write(data)
            out[v.id] = paths
        with open(os.path.join(directory, "decisions.json"), "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
        return out


def _words(text: str) -> frozenset:
    """Words of a line up to reversal: extraction may turn Arabic words and lines around."""
    clean = re.sub(r"[^\w\s]", " ", _fold(text))     # a title's colon may extract as its own span
    return frozenset(min(w, w[::-1]) for w in clean.split())


def _initials(doc, theme) -> List[str]:
    """First words of the paragraphs that may take a drop cap."""
    if not theme.decorations.drop_cap_enabled:
        return []
    out, armed = [], False
    for b in doc.blocks:
        word = re.match(r"\W*([^\W\d_]+)", b.text) if b.type == "paragraph" and armed else None
        if word:
            out.append(word.group(1))
        armed = b.type == "heading"
    return out


def _intended(plan: ArtDirectionPlan, pdf_pages, opener_titles: Sequence[str]) -> List[int]:
    """Pages planned to be quiet: the cover, contents, opening pages and statement pages."""
    pages = {1} if plan.cover not in ("masthead", "none") else set()
    titles = {_words(t) for t in opener_titles}
    for p in pdf_pages:
        if _words(p.first_line) in titles or (p.words <= 60 and p.largest_type >= 18 and p.page > 1):
            pages.add(p.page)
    return sorted(pages)


SHORT_LAST_WORDS = 70
SHORT_TAIL = 0.6                      # blank share under the last content of the last page


def _title_on(line: str, titles: Sequence[str]) -> Optional[str]:
    """The title a page opens with. Arabic display type can extract one word per line,
    so a line may hold only part of its title."""
    seen = _words(line)
    return next((t for t in titles if seen and (_words(t) <= seen or seen <= _words(t))), None)


def _next_refinement(critique, adjust: Adjust, plan: ArtDirectionPlan, titles: Sequence[str],
                     base_pages: int) -> Optional[tuple]:
    """One focused change for the worst thing measured, or nothing."""
    pages = critique.pages
    by_number = {p.page: p for p in pages}
    for o in critique.observations:
        if o.code != "sparse_page":
            continue
        nxt = by_number.get(o.page + 1)
        if nxt is None:
            continue
        title = _title_on(nxt.first_line, titles)
        if title and title not in adjust.no_break:
            return (replace(adjust, no_break=adjust.no_break | {title}),
                    f"page {o.page} ended early: let {title!r} follow on instead of opening a page")
    n = len(pages)
    last = pages[-1] if pages else None
    if last and n > 1 and last.words <= SHORT_LAST_WORDS:     # a short closing section need not open a page
        title = _title_on(last.first_line, titles)
        if title and title not in adjust.no_break:
            return (replace(adjust, no_break=adjust.no_break | {title}),
                    f"last page holds {last.words} words: let {title!r} follow on")
    if n >= max(4, base_pages * 1.75) and adjust.openers:
        return (replace(adjust, openers=False),
                f"{n} pages against about {base_pages} in plain setting: dropped the opening pages")
    if n >= max(4, base_pages * 1.5) and adjust.major_breaks:
        return (replace(adjust, major_breaks=False),
                f"{n} pages against about {base_pages} in plain setting: sections now follow on")
    if not _faults(critique, base_pages):
        return None
    if n >= max(3, base_pages * 1.5) and adjust.hero_page:
        return (replace(adjust, hero_page=False),
                f"{n} pages against about {base_pages} in plain setting: figures join their section")
    why = f"{n} pages, the last with {last.words} words"
    if adjust.exhibits > 0.76:
        return (replace(adjust, exhibits=round(adjust.exhibits * 0.87, 3)),
                f"{why}: made image bands and charts smaller to pull it back")
    if adjust.density > 0.8:
        return (replace(adjust, density=round(adjust.density * 0.9, 3)),
                f"{why}: tightened spacing to pull it back")
    return None


def _faults(critique, base_pages: int) -> int:
    """Measured page problems a design should not keep: a last page with little on it, and a
    document that grew by half. Each is a fact about the pages, not a quality grade."""
    pages = critique.pages
    n = len(pages)
    short = n > 1 and pages[-1].tail >= SHORT_TAIL
    return int(short) + int(n >= max(3, base_pages * 1.5))


class _Runner:
    def __init__(self, source, policy, brand, base_theme, budget: VariantBudget, office: bool):
        self.source, self.policy, self.brand, self.base_theme = source, policy, brand, base_theme
        self.budget, self.office = budget, office
        self.sem = normalize(source)
        self.renders = 0
        self.bytes = 0
        self.start = time.monotonic()
        self.base_pages = 1

    def spent(self) -> Optional[str]:
        if self.renders >= self.budget.max_renders:
            return f"render budget of {self.budget.max_renders} used"
        if time.monotonic() - self.start >= self.budget.max_seconds:
            return f"time budget of {self.budget.max_seconds:g} s used"
        if self.bytes >= self.budget.max_output_mb * 1e6:
            return f"output budget of {self.budget.max_output_mb:g} MB used"
        return None

    def _render(self, doc, theme):
        from ..layout.engine import LayoutEngine
        geo = Geometry()
        eng = LayoutEngine(doc, policy=self.policy, theme=theme, geometry=geo)
        buf = io.BytesIO()
        eng.render(buf)
        self.renders += 1
        return buf.getvalue(), geo

    def _attempt(self, direction: Direction, adjust: Adjust, why: List[str]):
        made = direct(self.sem, direction, brand=self.brand, base_theme=self.base_theme, adjust=adjust,
                      fit_reasons=why)
        pdf, geo = self._render(made.document, made.theme)
        return made, pdf, geo

    def run(self, direction: Direction, fit: float, why: List[str]) -> Variant:
        from ..qa.visual_critique import HEURISTIC_LABEL
        began = time.monotonic()
        rep = VariantReport(status="rejected", fit=fit, heuristic_label=HEURISTIC_LABEL)
        stop = self.spent()
        if stop:
            rep.status = "not_rendered"
            rep.hard_failures.append(stop)
            return Variant(direction.id, direction.name, None, rep)
        adjust = Adjust()
        titles = [o.text for o in self.sem.outline if o.level == 1]
        made, pdf, geo = self._attempt(direction, adjust, why)
        rep.renders = 1
        critique = self._look(made, pdf, titles)
        steps: List[str] = []
        for _ in range(self.budget.max_refinements):
            step = _next_refinement(critique, adjust, made.plan, titles, self.base_pages)
            if step is None or self.spent():
                break
            trial = step[0]
            t_made, t_pdf, t_geo = self._attempt(direction, trial, why)
            rep.renders += 1
            t_critique = self._look(t_made, t_pdf, titles)
            adjust = trial                        # a rejected change is not tried again
            before, after = _faults(critique, self.base_pages), _faults(t_critique, self.base_pages)
            if after < before or (after == before and t_critique.index >= critique.index):
                made, pdf, geo, critique = t_made, t_pdf, t_geo, t_critique
                steps.append(f"kept: {step[1]} (index {critique.index})")
            else:
                steps.append(f"undone: {step[1]} (index fell to {t_critique.index})")
        made.plan.refinements = steps
        rep.refinements = steps
        docx = self._docx(made, rep)
        self._gate(made, pdf, geo, docx, critique, rep)
        rep.pages = len(critique.pages) or len(geo.pages)
        rep.heuristics = critique.heuristics
        rep.index = critique.index
        rep.observations = [o.note for o in critique.observations]
        rep.seconds = round(time.monotonic() - began, 2)
        self.bytes += len(pdf) + len(docx or b"")
        return Variant(direction.id, direction.name, made.plan, rep, pdf, docx, made.document, made.theme)

    def _look(self, made, pdf: bytes, titles: Sequence[str]):
        from ..qa.visual_critique import critique_pdf
        first = critique_pdf(pdf)
        contents = [v["toc"] for v in LABELS.values()] if any(
            b.type == "table_of_contents" for b in made.document.blocks) else []
        quiet = _intended(made.plan, first.pages, [*titles, *contents])
        return critique_pdf(pdf, intended=quiet) if quiet else first

    def _docx(self, made, rep: VariantReport) -> Optional[bytes]:
        from ..renderers.docx_renderer import render_docx
        try:
            return render_docx(normalize(made.document), made.theme, self.policy)[0]
        except Exception as e:                    # a failed format rejects the design, not the batch
            rep.hard_failures.append(f"docx: {type(e).__name__}: {e}")
            return None

    def _gate(self, made, pdf, geo, docx, critique, rep: VariantReport) -> None:
        from ..core.content_ledger import build_content_ledger
        from ..policy import AssetPolicy
        from ..qa.content_preservation import UNKNOWN, check_preservation
        from ..qa.docx_checks import check_docx, docx_to_pdf, office_version
        from ..qa.loop import glyph_findings, qa_context
        from ..qa.media_checks import check_docx_media, check_pdf_media
        from ..qa.pdf_checks import check_pdf
        from ..qa.visual_critique import hard_failures
        doc, theme = made.document, made.theme
        brand = [self.brand.logo] if self.brand and self.brand.logo else []
        changes = content_changes(self.source, doc, theme, brand)
        layout = score_layout(geo, doc, theme)
        sem = normalize(doc)
        heads = [o.text for o in sem.outline]
        pdf_rep = docx_rep = preservation = None
        media: List[Dict] = []
        try:
            ctx = qa_context(doc, theme)
            pdf_rep = check_pdf(pdf, heading_texts=heads, **ctx)
            pdf_rep.findings += glyph_findings(sem, theme)
            media += check_pdf_media(pdf)
        except ImportError:
            rep.unverified.append("pdf page checks need PyMuPDF")
        if docx:
            docx_rep = check_docx(docx, heading_texts=heads, visual=False)
            media += check_docx_media(docx)
        try:
            # the source was compared with the design above; the files are compared with the
            # design, whose title block and chapter strips repeat the author's words
            ledger = build_content_ledger(doc, self.policy.assets if self.policy else AssetPolicy(), theme)
            preservation = check_preservation(ledger, pdf=pdf, docx=docx, initials=_initials(doc, theme))
            for layer in preservation.layers:
                if layer.status == UNKNOWN:
                    rep.unverified += [f"preservation {layer.name}: {x}" for x in layer.details]
        except ImportError:
            rep.unverified.append("preservation of the PDF text needs PyMuPDF")
        rep.hard_failures += hard_failures(content=changes, pdf_report=pdf_rep, docx_report=docx_rep,
                                           preservation=preservation, layout_errors=layout.hard_errors, media=media,
                                           smallest_type=theme.typography.base_size, critique=critique)
        if self.office and docx:
            version = office_version()
            converted = docx_to_pdf(docx) if version else None
            if converted:
                import pymupdf
                with pymupdf.open(stream=converted, filetype="pdf") as d:
                    rep.office = {"engine": version, "pages": d.page_count}
            else:
                rep.unverified.append("LibreOffice was not available for this DOCX")
        rep.unverified.append("Microsoft Word not run")
        rep.status = "rejected" if rep.hard_failures else "valid"


def generate_variants(source, *, policy=None, brand: Optional[BrandKit] = None, base_theme=None, n: int = 3,
                      families: Optional[Sequence[str]] = None, budget: Optional[VariantBudget] = None,
                      office: bool = False, grammar=None, grammar_rules: Optional[Sequence[str]] = None,
                      ranker_model: Optional[str] = None) -> VariantSet:
    """Up to ``n`` (3–5) designs of ``source`` and a recommendation.

    ``grammar`` is ``True`` for the packaged approved grammar, a path, or a ``Grammar``.
    A design the grammar breaks falls back to the same direction without it.

    ``ranker_model`` names a trained ranker for the valid designs. It never runs by itself,
    and ``stats["selection"]`` says which selector chose. Any problem keeps the fixed rule."""
    from ..design.grammar import resolve
    grammar = resolve(grammar)
    budget = budget or VariantBudget()
    if not 1 <= n <= len(DIRECTIONS):
        raise ValueError(f"n must be between 1 and {len(DIRECTIONS)}")
    for f in families or ():
        if f not in DIRECTIONS:
            raise ValueError(f"unknown design family {f!r}; choose from {sorted(DIRECTIONS)}")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        run = _Runner(source, policy, brand, base_theme, budget, office)
        base_pages = _plain_pages(run)
        run.base_pages = base_pages
        brief = read_brief(run.sem, _profile(run.sem), base_pages)
        ranked = select_directions(brief, len(DIRECTIONS))
        if families:
            chosen = [r for f in families for r in ranked if r[0].id == f]
            chosen += [(DIRECTIONS[f], 0.0, ["requested by the caller"]) for f in families
                       if f not in {r[0].id for r in ranked}]
        else:
            chosen = ranked[:n]
        variants = [_with_grammar(run, grammar, grammar_rules, brief, d, fit, why) for d, fit, why in chosen]
    valid = [v for v in variants if v.valid]
    best = max(valid, key=lambda v: v.report.fit * 6 + v.report.index, default=None)
    selection = {"selector": "deterministic", "model": None}
    if best is not None and ranker_model:
        from .variant_ranker import choose
        best, selection = choose(valid, best, ranker_model)
    if best is None:
        reasons = ["no design passed the hard gates: keep the stable designed output"]
    else:
        reasons = [f"{best.name}: fit {best.report.fit:g} for this document, measured index {best.report.index:g}",
                   *best.plan.fit_reasons,
                   "chosen from fit rules and page measurements; no person has judged it"]
        for v in valid:
            if v is not best:
                reasons.append(f"not chosen: {v.name} (fit {v.report.fit:g}, index {v.report.index:g})")
    for v in variants:
        if v.report.status == "rejected":
            reasons.append(f"rejected: {v.name}: {'; '.join(v.report.hard_failures[:3])}")
    stats = {"renders": run.renders, "seconds": round(time.monotonic() - run.start, 2),
             "budget": budget.model_dump(), "plain_pages": base_pages, "selection": selection}
    return VariantSet(variants, best, reasons, fallback=best is None, stats=stats)


def _with_grammar(run: _Runner, grammar, only, brief, direction, fit, why) -> Variant:
    """One design, following the grammar when given one."""
    from ..design.grammar import overlay
    if grammar is None:
        return run.run(direction, fit, why)
    changed, rules = overlay(grammar, direction, brief, run.sem.meta.title or "", only)
    if not rules:
        return run.run(direction, fit, why)
    v = run.run(changed, fit, why)
    spilled = any(r.startswith("cover.") for r in rules) and _cover_spilled(v.pdf)
    if v.valid and not spilled:
        v.report.grammar_rules, v.report.grammar_version = rules, grammar.version
        if v.plan:
            v.plan.decisions += [f"grammar {grammar.version}: {r}" for r in rules]
        return v
    fallback = run.run(direction, fit, why)
    fallback.report.observations.append(
        f"grammar {grammar.version}: {', '.join(rules)} failed the hard gates, so this design does without them")
    return fallback


def _cover_spilled(pdf: Optional[bytes]) -> bool:
    """A cover too tall for its page leaves white type on a white second page, which no text check sees."""
    try:
        import pymupdf
    except ImportError:
        return False
    if not pdf:
        return False
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        if doc.page_count < 2:
            return False
        page = doc[1]
        spans = [x for block in page.get_text("dict")["blocks"] for line in block.get("lines", []) for x in line["spans"]]
        for span in spans:
            if span["color"] >= 0xF0F0F0 and span["text"].strip():
                pix = page.get_pixmap(clip=pymupdf.Rect(span["bbox"]), colorspace=pymupdf.csGRAY, alpha=False)
                if min(pix.samples, default=255) > 200:         # nothing behind it: this type cannot be seen
                    return True
    return False


def _profile(sem) -> str:
    from ..design import select_profile
    return select_profile(sem, None).profile.value


def _plain_pages(run: _Runner) -> int:
    """Pages of the document in plain setting: the yardstick for growth."""
    from ..themes import get_theme
    theme = run.base_theme or get_theme(run.source.theme)
    _, geo = run._render(run.source, theme)
    return max(1, len(geo.pages))
