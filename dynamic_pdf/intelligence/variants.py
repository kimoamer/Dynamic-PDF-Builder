"""
Generate → render → evaluate → refine → select, for several designs of one document.

Each direction yields a complete design. Rendered pages are measured, weak ones get a
focused change and one more render while the budget lasts, and every design then passes
the hard gates or is rejected with its reasons. The recommendation is the valid design
that best fits the document and measures best, with both numbers shown. It is a
recommendation from heuristics, not a verdict on beauty.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import time
import warnings
from dataclasses import dataclass, field, replace
from itertools import islice
from typing import Dict, List, Optional, Sequence

from pydantic import BaseModel, Field

from ..core.normalize import normalize
from ..design import BrandKit
from ..design.art_direction import Adjust, ArtDirectionPlan, content_changes, direct, read_brief, select_directions
from ..design.directions import DIRECTIONS, Direction
from ..i18n import LABELS
from ..qa.content_preservation import _fold
from .facts import read_pdf, with_layout
from .geometry import Geometry
from .objective import design_score, gates
from .scoring import score_layout


class VariantBudget(BaseModel):
    """Limits for one ``design_variants`` call. ReportLab cannot be stopped mid-render, so
    time is checked between renders; a design that starts in time may finish after it."""

    max_renders: int = Field(40, ge=1)
    max_refinements: int = Field(5, ge=0)        # per design
    # changes forecast (measured blocks, no render) before each refinement; the best is rendered.
    # 0 renders the ladder's first change. Off by default: on three corpus documents the
    # forecast chose differently twice and the designs ended the same.
    max_forecasts: int = Field(0, ge=0)
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
    ai: List[Dict] = Field(default_factory=list)              # what a model was asked, and whether its answer was used
    facts: Dict[str, float] = Field(default_factory=dict)    # measured document facts (PageFacts)
    score: float = 0.0                                       # the soft score the recommendation ranks by


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
    facts: object = None                         # PageFacts of the delivered render

    @property
    def valid(self) -> bool:
        return self.report.status == "valid"


@dataclass
class DesignChoice:
    """Which design an export delivered and why (``ExportResult.design``)."""

    recommended: Optional[str]                   # direction id, None when no design passed
    reasons: List[str]
    fallback: bool                               # True: the stable designed output was delivered
    variants: Dict[str, str] = field(default_factory=dict)    # direction id -> status
    scores: Dict[str, float] = field(default_factory=dict)    # direction id -> soft score (valid designs)
    selection: Dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"recommended": self.recommended, "reasons": self.reasons, "fallback": self.fallback,
                "variants": self.variants, "scores": self.scores, "selection": self.selection}


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

    def choice(self) -> DesignChoice:
        return DesignChoice(self.recommended.id if self.recommended else None, list(self.reasons), self.fallback,
                            {v.id: v.report.status for v in self.variants},
                            {v.id: v.report.score for v in self.variants if v.valid},
                            dict(self.stats.get("selection") or {}))

    def to_dict(self) -> dict:
        return {"recommended": self.recommended.id if self.recommended else None, "reasons": self.reasons,
                "fallback": self.fallback, "stats": self.stats,
                "note": "the recommendation comes from fit rules and page measurements; no person has judged it",
                "variants": [{"id": v.id, "name": v.name, "report": v.report.model_dump(),
                              "plan": v.plan.explain() if v.plan else None} for v in self.variants]}

    def accept(self, variant_id: str, reviewer: str, *, note: str = "", root: Optional[str] = None,
               date: Optional[str] = None) -> dict:
        """Record that a person kept ``variant_id``: one row in ``<root>/accepted.jsonl``.
        ``root`` is the caller's folder, or ``DYNAMIC_PDF_PREFERENCES_DIR``; the library never
        picks a place to write by itself.

        This is human signal, so it goes only to a ``human_preferences`` folder, never to the AI
        rows. The row names the design kept, the valid designs passed over and the recommendation."""
        import datetime

        from ..settings import get
        root = root or get("PREFERENCES_DIR")
        if not root:
            raise ValueError("say where to record it: root=<a human_preferences folder>, or set DYNAMIC_PDF_PREFERENCES_DIR")
        if os.path.basename(os.path.normpath(root)) != "human_preferences":
            raise ValueError("accepted designs are written only to a human_preferences folder")
        if not reviewer or not reviewer.strip():
            raise ValueError("a person's name is required: an acceptance is a human judgment")
        chosen = next((v for v in self.variants if v.id == variant_id), None)
        if chosen is None or not chosen.valid:
            raise ValueError(f"{variant_id!r} is not a valid design of this set; choose from "
                             f"{[v.id for v in self.variants if v.valid]}")

        def ident(v):
            return {"candidate": v.id, "pdf_sha256": hashlib.sha256(v.pdf or b"").hexdigest(),
                    "docx_sha256": hashlib.sha256(v.docx or b"").hexdigest()}

        row = {"format": "dynamic-pdf-builder/human-acceptance", "reviewer_type": "human", "reviewer": reviewer.strip(),
               "review_date": date or datetime.date.today().isoformat(), "document_hash": self.stats.get("source_sha256"),
               "accepted": ident(chosen), "passed_over": [ident(v) for v in self.variants if v.valid and v is not chosen],
               "recommended": self.recommended.id if self.recommended else None,
               "selector": (self.stats.get("selection") or {}).get("selector"), "note": note}
        os.makedirs(root, exist_ok=True)
        with open(os.path.join(root, "accepted.jsonl"), "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return row

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


def _intended(cover: bool, pdf_pages, opener_titles: Sequence[str]) -> List[int]:
    """Pages planned to be quiet: the cover (when the first page is one), contents, opening
    pages and statement pages."""
    pages = {1} if cover else set()
    titles = {_words(t) for t in opener_titles}
    for p in pdf_pages:
        if _words(p.first_line) in titles or (p.words <= 60 and p.largest_type >= 18 and p.page > 1):
            pages.add(p.page)
    return sorted(pages)


SHORT_LAST_WORDS = 70
SHORT_TAIL = 0.55                     # blank share under the last content of the last page


def _title_on(line: str, titles: Sequence[str]) -> Optional[str]:
    """The title a page opens with. Arabic display type can extract one word per line,
    so a line may hold only part of its title."""
    seen = _words(line)
    return next((t for t in titles if seen and (_words(t) <= seen or seen <= _words(t))), None)


def _next_refinement(critique, adjust: Adjust, plan: ArtDirectionPlan, titles: Sequence[str],
                     base_pages: int) -> Optional[tuple]:
    """One focused change for the worst thing measured, or nothing."""
    return next(_refinements(critique, adjust, plan, titles, base_pages), None)


def _refinements(critique, adjust: Adjust, plan: ArtDirectionPlan, titles: Sequence[str], base_pages: int):
    """Every focused change for what was measured, worst problem first."""
    pages = critique.pages
    by_number = {p.page: p for p in pages}
    seen = set()
    for o in critique.observations:
        if o.code != "sparse_page":
            continue
        nxt = by_number.get(o.page + 1)
        if nxt is None:
            continue
        title = _title_on(nxt.first_line, titles)
        if title and title not in adjust.no_break and title not in seen:
            seen.add(title)
            yield (replace(adjust, no_break=adjust.no_break | {title}),
                   f"page {o.page} ended early: let {title!r} follow on instead of opening a page")
    n = len(pages)
    last = pages[-1] if pages else None
    if last and n > 1 and last.words <= SHORT_LAST_WORDS:     # a short closing section need not open a page
        title = _title_on(last.first_line, titles)
        if title and title not in adjust.no_break and title not in seen:
            yield (replace(adjust, no_break=adjust.no_break | {title}),
                   f"last page holds {last.words} words: let {title!r} follow on")
    if n >= max(4, base_pages * 1.75) and adjust.openers:
        yield (replace(adjust, openers=False),
               f"{n} pages against about {base_pages} in plain setting: dropped the opening pages")
    if n >= max(4, base_pages * 1.5) and adjust.major_breaks:
        yield (replace(adjust, major_breaks=False),
               f"{n} pages against about {base_pages} in plain setting: sections now follow on")
    if not _faults(critique, base_pages):
        return
    if n >= max(3, base_pages * 1.5) and adjust.hero_page:
        yield (replace(adjust, hero_page=False),
               f"{n} pages against about {base_pages} in plain setting: figures join their section")
    why = f"{n} pages, the last with {last.words} words"
    if adjust.exhibits > 0.76:
        yield (replace(adjust, exhibits=round(adjust.exhibits * 0.87, 3)),
               f"{why}: made image bands and charts smaller to pull it back")
    if adjust.density > 0.8:
        yield (replace(adjust, density=round(adjust.density * 0.9, 3)),
               f"{why}: tightened spacing to pull it back")


def _faults(critique, base_pages: int) -> int:
    """Measured page problems a design should not keep: a last page with little on it, and a
    document that grew by half. Each is a fact about the pages, not a quality grade."""
    pages = critique.pages
    n = len(pages)
    short = n > 1 and pages[-1].tail >= SHORT_TAIL
    return int(short) + int(n >= max(3, base_pages * 1.5))


class _Runner:
    def __init__(self, source, policy, brand, base_theme, budget: VariantBudget, office: bool, critic=None):
        self.source, self.policy, self.brand, self.base_theme = source, policy, brand, base_theme
        self.budget, self.office, self.critic = budget, office, critic
        self.start_adjust = Adjust()             # a Director may start every design from its own choice
        self.plain_pdf: Optional[bytes] = None
        self.sem = normalize(source)
        self.renders = 0
        self.bytes = 0
        self.start = time.monotonic()
        self.base_pages = 1
        self.forecast_figures: dict = {}      # figures drawn once for all forecasts

    def spent(self) -> Optional[str]:
        if self.renders >= self.budget.max_renders:
            return f"render budget of {self.budget.max_renders} used"
        if time.monotonic() - self.start >= self.budget.max_seconds:
            return f"time budget of {self.budget.max_seconds:g} s used"
        if self.bytes >= self.budget.max_output_mb * 1e6:
            return f"output budget of {self.budget.max_output_mb:g} MB used"
        return None

    def _render(self, doc, theme, cache=None):
        from ..layout.engine import LayoutEngine
        geo = Geometry()
        eng = LayoutEngine(doc, policy=self.policy, theme=theme, geometry=geo, cache=cache)
        buf = io.BytesIO()
        eng.render(buf)
        self.renders += 1
        return buf.getvalue(), geo

    def _attempt(self, direction: Direction, adjust: Adjust, why: List[str], cache: dict):
        """One design and its render. ``cache`` holds this direction's figures and renders: an
        adjustment that leaves the document and theme as they were is not rendered again."""
        made = direct(self.sem, direction, brand=self.brand, base_theme=self.base_theme, adjust=adjust,
                      fit_reasons=why)
        key = ("render", hashlib.sha256((made.document.model_dump_json()
                                         + made.theme.model_dump_json()).encode()).hexdigest())
        if key in cache:
            return (made, *cache[key], False)
        pdf, geo = self._render(made.document, made.theme, cache)
        cache[key] = (pdf, geo, read_pdf(pdf, plain_pages=self.base_pages))
        return (made, *cache[key], True)

    def run(self, direction: Direction, fit: float, why: List[str]) -> Variant:
        from ..qa.visual_critique import HEURISTIC_LABEL
        began = time.monotonic()
        rep = VariantReport(status="rejected", fit=fit, heuristic_label=HEURISTIC_LABEL)
        stop = self.spent()
        if stop:
            rep.status = "not_rendered"
            rep.hard_failures.append(stop)
            return Variant(direction.id, direction.name, None, rep)
        adjust = self.start_adjust
        renders_before = self.renders
        titles = [o.text for o in self.sem.outline if o.level == 1]
        cache: dict = {}                          # figures drawn once for all of this direction's renders
        made, pdf, geo, facts, _ = self._attempt(direction, adjust, why, cache)
        rep.renders = 1
        critique = self._look(made, facts, titles)
        steps: List[str] = []
        state = (made, pdf, geo, critique, facts)
        for _ in range(self.budget.max_refinements):
            step = self._ranked(direction, why, critique, adjust, made.plan, titles)
            if step is None or self.spent():
                break
            adjust = step[0]                      # a rejected change is not tried again
            state = self._trial(direction, adjust, why, titles, state, step[1], rep, steps, cache, critic=False)
            made, pdf, geo, critique, facts = state
        for _ in range(self.critic.rounds if self.critic else 0):
            if self.spent():
                break
            made, pdf, geo, critique, facts = state
            trial, note, asked = self.critic.review(pdf, critique, adjust, titles, direction.id)
            rep.ai.append(asked)
            if trial is None:
                break
            adjust = trial
            state = self._trial(direction, adjust, why, titles, state, note, rep, steps, cache, critic=True)
        made, pdf, geo, critique, facts = self._paged(*state, titles, steps)
        rep.renders = self.renders - renders_before
        made.plan.refinements = steps
        rep.refinements = steps
        docx = self._docx(made, rep)
        self._gate(made, pdf, geo, docx, facts, rep)
        rep.pages = facts.page_count or len(geo.pages)
        rep.heuristics = critique.heuristics
        rep.index = critique.index
        rep.score = design_score(rep.fit, rep.index)
        rep.facts = {**facts.document, **{f"layout_{k}": v for k, v in facts.layout.items()}}
        rep.observations = [o.note for o in critique.observations]
        rep.seconds = round(time.monotonic() - began, 2)
        self.bytes += len(pdf) + len(docx or b"")
        return Variant(direction.id, direction.name, made.plan, rep, pdf, docx, made.document, made.theme, facts)

    def _trial(self, direction, trial: Adjust, why, titles, state, note: str, rep: VariantReport, steps: List[str],
               cache: dict, critic: bool):
        """Render one change and keep it if it measures no worse. A critic's change needs only to
        add no measured fault: the model is the judge there, the measurements a filter."""
        critique = state[3]
        t_made, t_pdf, t_geo, t_facts, _ = self._attempt(direction, trial, why, cache)
        t_critique = self._look(t_made, t_facts, titles)
        before, after = _faults(critique, self.base_pages), _faults(t_critique, self.base_pages)
        if after < before or (after == before and (critic or t_critique.index >= critique.index)):
            steps.append(f"kept: {note} (index {t_critique.index})")
            return t_made, t_pdf, t_geo, t_critique, t_facts
        steps.append(f"undone: {note} (" + (f"measured faults rose to {after}" if after > before
                                             else f"index fell to {t_critique.index}") + ")")
        return state

    def _ranked(self, direction: Direction, why, critique, adjust: Adjust, plan, titles) -> Optional[tuple]:
        """The change to render next. Of the first ``max_forecasts`` the ladder offers, the one
        whose forecast (measured blocks, no render) has the fewest page faults, then the fewest
        pages; ladder order breaks ties and stands wherever a forecast is missing."""
        options = list(islice(_refinements(critique, adjust, plan, titles, self.base_pages),
                              max(1, self.budget.max_forecasts)))
        if len(options) < 2:
            return options[0] if options else None
        keys = []
        for k, (trial, _) in enumerate(options):
            got = self._forecast(direction, trial, why)
            if got is None:
                return options[0]
            keys.append((got, k))
        return options[min(keys)[1]]

    def _forecast(self, direction: Direction, adjust: Adjust, why) -> Optional[tuple]:
        """(page faults, pages) forecast for a design, or None."""
        from ..layout.breaks import forecast
        made = direct(self.sem, direction, brand=self.brand, base_theme=self.base_theme, adjust=adjust,
                      fit_reasons=why)
        got = forecast(made.document, made.theme, self.policy, self.forecast_figures)
        if got is None:
            return None
        pages, last_fill = got
        return int(pages > 1 and last_fill < 1 - SHORT_TAIL) + int(pages >= max(3, self.base_pages * 1.5)), pages

    def _paged(self, made, pdf, geo, critique, facts, titles, steps: List[str]):
        """Page breaks chosen by search (``layout/breaks.py``) for the refined design: one more
        refinement, kept when a render confirms it and the measured faults do not grow."""
        from ..layout.breaks import optimize_breaks
        unchanged = made, pdf, geo, critique, facts
        if len(steps) >= self.budget.max_refinements or self.spent():
            return unchanged
        doc, br = optimize_breaks(made.document, made.theme, self.policy, natural=geo)
        self.renders += br.renders
        if not br.applied:
            return unchanged
        t_made = replace(made, document=doc)
        t_pdf, t_geo = br.rendered
        t_facts = read_pdf(t_pdf, plain_pages=self.base_pages)
        t_critique = self._look(t_made, t_facts, titles)
        if _faults(t_critique, self.base_pages) <= _faults(critique, self.base_pages):
            steps.append(f"kept: {br.summary()} (index {t_critique.index})")
            return t_made, t_pdf, t_geo, t_critique, t_facts
        steps.append(f"undone: {br.summary()} (more page faults)")
        return unchanged

    def _look(self, made, facts, titles: Sequence[str]):
        """The critique of one render, from its facts: the PDF is read and rasterized once."""
        from ..qa.visual_critique import critique_facts
        first = critique_facts(facts)
        contents = [v["toc"] for v in LABELS.values()] if any(
            b.type == "table_of_contents" for b in made.document.blocks) else []
        quiet = _intended(made.plan.cover not in ("masthead", "title_block", "none"), first.pages, [*titles, *contents])
        return critique_facts(facts, intended=quiet) if quiet else first

    def _docx(self, made, rep: VariantReport) -> Optional[bytes]:
        from ..renderers.docx_renderer import render_docx
        try:
            return render_docx(normalize(made.document), made.theme, self.policy)[0]
        except Exception as e:                    # a failed format rejects the design, not the batch
            rep.hard_failures.append(f"docx: {type(e).__name__}: {e}")
            return None

    def _gate(self, made, pdf, geo, docx, facts, rep: VariantReport) -> None:
        from ..core.content_ledger import build_content_ledger
        from ..policy import AssetPolicy
        from ..qa.content_preservation import UNKNOWN, check_preservation
        from ..qa.docx_checks import check_docx, docx_to_pdf, office_version
        from ..qa.loop import glyph_findings, qa_context
        from ..qa.media_checks import check_docx_media, check_pdf_media
        from ..qa.pdf_checks import check_pdf
        doc, theme = made.document, made.theme
        brand = [self.brand.logo] if self.brand and self.brand.logo else []
        changes = content_changes(self.source, doc, theme, brand)
        with_layout(facts, score_layout(geo, doc, theme))
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
            rep.unverified.append("pdf page checks need a PDF reader (PyMuPDF or pypdfium2)")
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
            rep.unverified.append("preservation of the PDF text needs a PDF reader (PyMuPDF or pypdfium2)")
        rep.hard_failures += gates(facts, content=changes, pdf_report=pdf_rep, docx_report=docx_rep,
                                   preservation=preservation, media=media, smallest_type=theme.typography.base_size)
        if self.office and docx:
            version = office_version()
            converted = docx_to_pdf(docx) if version else None
            if converted:
                from ..qa.pdf_backend import open_pdf
                with open_pdf(converted) as d:
                    rep.office = {"engine": version, "pages": d.page_count}
            else:
                rep.unverified.append("LibreOffice was not available for this DOCX")
        rep.unverified.append("Microsoft Word not run")
        rep.status = "rejected" if rep.hard_failures else "valid"


def generate_variants(source, *, policy=None, brand: Optional[BrandKit] = None, base_theme=None, n: int = 3,
                      families: Optional[Sequence[str]] = None, budget: Optional[VariantBudget] = None,
                      office: bool = False, grammar=None, grammar_rules: Optional[Sequence[str]] = None,
                      ranker_model: Optional[str] = None, ai=None, critic=None,
                      request: Optional[str] = None, ranker: Optional[str] = None) -> VariantSet:
    """Up to ``n`` (3–5) designs of ``source`` and a recommendation.

    ``grammar`` is ``True`` for the packaged approved grammar, a path, or a ``Grammar``.
    A design the grammar breaks falls back to the same direction without it.

    ``ranker`` asks for the learned selector among the valid designs: ``"auto"`` for the model
    packaged with this release, or a model's path (``ranker_model`` is the older name for a
    path). ``None`` or ``"off"`` keeps the fixed rule. The model replaces the fixed choice only
    when it is sure enough (``variant_ranker.choose``), ``stats["selection"]`` says which
    selector chose and what moved it, and any problem with a model keeps the fixed rule.

    ``ai`` is a ``dynamic_pdf.ai.Director``: it ranks the directions, starts each design from its
    section treatments and emphasis, and its first valid design is recommended. ``request`` is a
    caller's brief in words, for the Director. ``critic`` is a ``dynamic_pdf.ai.Critic`` that may
    refine each design for a few more renders. Both are opt-in; every design they shape passes the
    same hard gates, and ``stats["ai"]`` reports what each model was asked and whether it was used.
    A learned selector that was asked for still has the last word among the valid designs."""
    from ..design.grammar import resolve
    if request and ai is None:
        raise ValueError("a brief is read by a model: pass ai=dynamic_pdf.ai.Director(...), or leave the brief out")
    grammar = resolve(grammar)
    budget = budget or VariantBudget()
    if not 1 <= n <= len(DIRECTIONS):
        raise ValueError(f"n must be between 1 and {len(DIRECTIONS)}")
    for f in families or ():
        if not isinstance(f, Direction) and f not in DIRECTIONS:
            raise ValueError(f"unknown design family {f!r}; choose from {sorted(DIRECTIONS)}")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        run = _Runner(source, policy, brand, base_theme, budget, office, critic)
        base_pages = _plain_pages(run)
        run.base_pages = base_pages
        brief = read_brief(run.sem, _profile(run.sem), base_pages)
        ranked = select_directions(brief, len(DIRECTIONS))
        order, director = None, None
        if ai is not None:
            order, run.start_adjust, director = ai.choose(run.sem, brief, ranked, request=request, plain_pdf=run.plain_pdf)
            if order:
                ranked = sorted(ranked, key=lambda r: order.index(r[0].id))
        if families and all(isinstance(f, Direction) for f in families):
            chosen = [(f, 0.0, ["the chosen theme"]) for f in families]       # a theme's own structure, as given
        elif families:
            chosen = [r for f in families for r in ranked if r[0].id == f]
            chosen += [(DIRECTIONS[f], 0.0, ["requested by the caller"]) for f in families
                       if f not in {r[0].id for r in ranked}]
        else:
            chosen = ranked[:n]
        variants = [_with_grammar(run, grammar, grammar_rules, brief, d, fit, why) for d, fit, why in chosen]
    valid = [v for v in variants if v.valid]
    best = max(valid, key=lambda v: v.report.score, default=None)
    selection = {"selector": "deterministic", "model": None}
    if best is not None and order:
        fixed = best
        best = min(valid, key=lambda v: order.index(v.id) if v.id in order else len(order))
        selection = {"selector": "ai", "model": director["model"], "deterministic_choice": fixed.id}
    from .variant_ranker import choose, context_features
    context = context_features(brief)             # the document, the same for each of its designs
    if best is not None and (ranker or ranker_model):
        best, selection = choose(valid, best, ranker or ranker_model, context=context)
    if best is None:
        reasons = ["no design passed the hard gates: keep the stable designed output"]
    else:
        reasons = [f"{best.name}: fit {best.report.fit:g} for this document, measured index {best.report.index:g}",
                   *best.plan.fit_reasons,
                   f"ranked first by {selection['model']} among the valid designs; no person has judged it"
                   if selection["selector"] == "ai" else
                   f"chosen by the learned selector {selection['model']}, a student of AI comparisons; "
                   "no person has judged it" if selection["selector"] == "learned" else
                   "chosen from fit rules and page measurements; no person has judged it"]
        if selection.get("abstained"):
            reasons.append(f"the learned selector preferred {selection['learned_choice']} but was not sure enough "
                           f"({selection['margin']:g} against a threshold of {selection['threshold']:g}): the fixed choice stands")
        reasons += [f"learned selector: {r}" for r in selection.get("reasons", [])]
        for v in valid:
            if v is not best:
                reasons.append(f"not chosen: {v.name} (fit {v.report.fit:g}, index {v.report.index:g})")
    for v in variants:
        if v.report.status == "rejected":
            reasons.append(f"rejected: {v.name}: {'; '.join(v.report.hard_failures[:3])}")
    stats = {"renders": run.renders, "seconds": round(time.monotonic() - run.start, 2),
             "budget": budget.model_dump(), "plain_pages": base_pages, "selection": selection, "context": context,
             "source_sha256": hashlib.sha256(source.model_dump_json().encode("utf-8")).hexdigest()}
    if director is not None or critic is not None:
        stats["ai"] = {"director": director, "critic": {v.id: v.report.ai for v in variants if v.report.ai}}
    return VariantSet(variants, best, reasons, fallback=best is None, stats=stats)


COMPOSITION_MARKS = {"chart.small_multiples": "matrix:", "editorial.overlaid_panel": "panel:",
                     "bilingual.parallel_columns": "paired columns:", "bilingual.parallel_ledger": "ledger:"}


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
        rules = [r for r in rules if _took_effect(r, v.plan)]
        v.report.grammar_rules, v.report.grammar_version = rules, grammar.version
        if v.plan:
            v.plan.decisions += [f"grammar {grammar.version}: {r}" for r in rules]
        return v
    if v.valid and spilled:                       # the cover alone was at fault; keep the other rules
        kept = [r for r in rules if not r.startswith("cover.")]
        if kept:
            changed, rules = overlay(grammar, direction, brief, run.sem.meta.title or "", kept)
            v = run.run(changed, fit, why)
            if v.valid:
                v.report.grammar_rules = [r for r in rules if _took_effect(r, v.plan)]
                v.report.grammar_version = grammar.version
                v.report.observations.append(f"grammar {grammar.version}: cover rule dropped, the title spilled")
                return v
    fallback = run.run(direction, fit, why)
    fallback.report.observations.append(
        f"grammar {grammar.version}: {', '.join(rules)} failed the hard gates, so this design does without them")
    return fallback


def _took_effect(rule: str, plan) -> bool:
    """A composition rule counts only where the document had the structure for it."""
    mark = COMPOSITION_MARKS.get(rule)
    return not mark or not plan or any(d.startswith(mark) for d in plan.decisions)


def _cover_spilled(pdf: Optional[bytes]) -> bool:
    """A cover too tall for its page leaves white type on a white second page, which no text check sees."""
    from ..qa.pdf_backend import open_pdf
    if not pdf:
        return False
    try:
        doc = open_pdf(pdf)
    except ImportError:
        return False
    with doc:
        if doc.page_count < 2:
            return False
        page = doc[1]
        spans = [x for block in page.text_dict()["blocks"] for line in block.get("lines", []) for x in line["spans"]]
        for span in spans:
            if span["color"] >= 0xF0F0F0 and span["text"].strip():
                clip = page.clip(tuple(span["bbox"]))
                if clip and min(page.gray(1.0, clip)[2], default=255) > 200:   # nothing behind it: unseen type
                    return True
    return False


def _profile(sem) -> str:
    from ..design import select_profile
    return select_profile(sem, None).profile.value


def _plain_pages(run: _Runner) -> int:
    """Pages of the document in plain setting: the yardstick for growth."""
    from ..themes import get_theme
    theme = run.base_theme or get_theme(run.source.theme)
    run.plain_pdf, geo = run._render(run.source, theme)
    return max(1, len(geo.pages))
