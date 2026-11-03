"""
DocumentBuilder — fluent API for constructing PDFs programmatically.
Every method returns self for chaining.
"""
import io
import base64
from typing import Optional, List, Dict, Any, Union
from .schema.document import Document, Meta
from .schema.enums import PageSize, Orientation
from .schema.blocks import (
    HeadingBlock, ParagraphBlock, RichTextBlock, BulletListBlock, NumberedListBlock,
    TableBlock, CodeBlock, ImageBlock, ChartBlock, MathBlock, MermaidBlock,
    CalloutBlock, QuoteBlock, MetricRowBlock, MetricItem,
    ProgressBarBlock, ProgressBarItem, ScoreDisplayBlock,
    LegendBlock, LegendItem, BadgeBlock, NoteBlock,
    DividerBlock, SpacerBlock, PageBreakBlock, CoverPageBlock,
    ChecklistBlock, ChecklistItem, DefinitionListBlock, DefinitionItem,
    FootnoteBlock, AbstractBlock, AbstractField,
    BibliographyBlock, BibliographyEntry, CitationBlock,
    SignatureBlock, TimelineBlock, TimelineEvent,
    ShapeBlock, QRCodeBlock, WatermarkBlock, TOCBlock,
    IntroductionPageBlock, DiagramBlock,
    TwoColumnBlock, ThreeColumnBlock, SidebarBlock,
)
from .layout.engine import LayoutEngine
from .policy import RenderPolicy, ResourceLimits, STRICT
from .assets import AssetPolicy
from .utils.errors import ResourceLimitError


class ExportResult:
    """Paths and diagnostics produced by ``export`` / ``export_both``."""

    def __init__(self, pdf_path=None, docx_path=None, page_count=None, profile=None,
                 diagnostics=None):
        self.pdf_path = pdf_path
        self.docx_path = docx_path
        self.page_count = page_count
        self.profile = profile
        self.diagnostics = diagnostics or []
        self.qa = {}             # format -> QAReport (when exported with qa=True)
        self.composition = None  # dict (CompositionReport) when compose() is active

    _RANK = {"ok": 0, "fallback": 1, "unverified": 2, "degraded": 3, "failed": 4}

    def _evaluate(self):
        """(status, reasons) from QA reports, diagnostics and the composition."""
        found = []
        for fmt, rep in self.qa.items():
            if rep.status == "fail":
                found.append(("failed", f"{fmt} QA failed: {len(rep.errors)} error(s)"))
            elif rep.status == "unverified":
                found.append(("unverified", f"{fmt} QA unverified: {', '.join(rep.unverified)}"))
        n_err = sum(1 for d in self.diagnostics if d.get("level") == "error")
        if n_err:
            found.append(("degraded", f"{n_err} render error(s)"))
        c = self.composition or {}
        cst = c.get("status")
        if cst == "failed":
            found.append(("failed", "composition: no valid layout ("
                          + "; ".join(c.get("reasons", [])[-1:]) + ")"))
        elif cst == "unverified" and "pdf" not in self.qa and self.pdf_path:
            found.append(("unverified", "composition QA unverified: " + ", ".join(c.get("unverified", []))))
        if cst == "fallback" or any("designed layout" in f for f in c.get("fallbacks", [])):
            found.append(("fallback", "composition fell back to the designed layout: "
                          + "; ".join(c.get("fallbacks", [])[:2])))
        status = max((s for s, _ in found), key=self._RANK.__getitem__, default="ok")
        return status, [why for _, why in found]

    @property
    def status(self) -> str:
        """"failed" (QA errors or no valid composed layout) > "degraded" (render
        errors) > "unverified" (a required check was skipped or could not run) >
        "fallback" (composition used the designed layout) > "ok"."""
        return self._evaluate()[0]

    @property
    def status_reasons(self) -> list:
        """Why ``status`` is not ``"ok"`` (empty when it is)."""
        return self._evaluate()[1]

    def __repr__(self):
        return (f"ExportResult(pdf={self.pdf_path!r}, docx={self.docx_path!r}, "
                f"profile={self.profile!r}, status={self.status!r})")


class DocumentBuilder:
    """Fluent API for building PDF documents.

    Example::

        (DocumentBuilder(theme="claude")
            .meta(title="My Report")
            .heading("Introduction")
            .paragraph("Hello world.")
            .render("report.pdf"))
    """

    def __init__(self, theme: Optional[str] = None, policy: Optional[RenderPolicy] = None):
        self._theme_explicit = theme is not None
        self._theme = theme or "claude"
        self._meta = Meta()
        self._blocks: list = []
        self._policy = policy or RenderPolicy()
        self.last_render = None   # LayoutEngine of the most recent render (diagnostics, page_count)
        self._design_mode: Optional[str] = None   # None = classic theme rendering (v0.3)
        self._design_explicit = False             # export()/CLI default to design("auto")
        self._brand = None
        self._source_kind = "api"
        self._source_text: Optional[str] = None
        self.front_matter: dict = {}
        self.last_design = None
        self._qa_hints: dict = {}        # block index -> layout hints from the QA loop
        self._compose_options = None     # set by compose(); None = classic single render
        self._composition = None
        self.last_composition = None
        self._fit_cache: dict = {}

    # ─── Semantic / design layer ───────────────────────────────────

    def document_type(self, doc_type: str) -> 'DocumentBuilder':
        """Declare the document type (e.g. ``executive_report``, ``proposal``,
        ``academic_report``, ``technical_manual``, ``data_report``, ``letter``)."""
        from .design import resolve_profile_name
        self._meta.document_type = (None if doc_type in (None, "", "auto")
                                    else resolve_profile_name(doc_type).value)
        return self

    def direction(self, direction: str) -> 'DocumentBuilder':
        if direction not in ("ltr", "rtl", "auto"):
            raise ValueError("direction must be 'ltr', 'rtl' or 'auto'")
        self._meta.direction = None if direction == "auto" else direction
        self._meta.rtl = direction == "rtl"
        return self

    def design(self, mode: str = "auto", brand=None) -> 'DocumentBuilder':
        """Enable intelligent design: ``"auto"`` selects a profile from the
        content; a profile name forces it. ``brand`` is a ``BrandKit`` or dict.
        Content is never altered — only typography, layout and navigation."""
        from .design import BrandKit, resolve_profile_name
        self._design_explicit = True
        if mode is None or mode == "none":
            self._design_mode = None       # explicit opt-out: classic theme rendering
            return self
        if mode != "auto":
            resolve_profile_name(mode)   # validate early
        self._design_mode = mode
        if brand is not None:
            self._brand = brand if isinstance(brand, BrandKit) else BrandKit(**brand)
        return self

    def semantic(self):
        """The canonical, renderer-independent ``SemanticDocument``."""
        from .core.normalize import normalize
        return normalize(self.build(), source_kind=self._source_kind,
                         source_text=self._source_text, front_matter=self.front_matter)

    # ─── Intelligent composition ───────────────────────────────────

    def compose(self, mode: str = "smart", **options) -> 'DocumentBuilder':
        """Enable CPU-only intelligent page composition.

        ``mode="smart"`` evaluates up to four layout strategies (balanced,
        compact, editorial, data) against the designed layout, renders at most
        three, and keeps the best *valid* one by a deterministic score; the
        designed layout is kept unless a candidate is objectively better.
        ``mode="off"`` disables it. Options: see ``intelligence.ComposeOptions``
        (max_candidates, max_renders, max_repairs, min_gain, time_budget_s,
        memory_budget_mb, measure_memory, qa). The result is in
        ``last_composition`` (and ``ExportResult.composition``).
        """
        from .intelligence import ComposeOptions
        if mode not in ("smart", "off"):
            raise ValueError("compose mode must be 'smart' or 'off'")
        self._compose_options = None if mode == "off" else ComposeOptions(mode=mode, **options)
        self._composition = None
        return self

    def _compose_active(self) -> bool:
        return getattr(self, "_compose_options", None) is not None

    def _composed(self):
        """(doc, theme, pdf_bytes, engine, composer) of the selected composition (cached)."""
        import hashlib
        from .core.normalize import normalize
        from .intelligence import Composer
        from .themes import get_theme as _gt
        doc, theme = self._prepared_base()
        theme = theme or _gt(doc.theme)
        key = hashlib.sha256((doc.model_dump_json() + theme.model_dump_json()
                              + self._compose_options.model_dump_json()).encode()).hexdigest()
        if self._composition is not None and self._composition[0] == key:
            return self._composition[1]
        sem = normalize(doc)
        profile = self.last_design.decision.profile.value if self.last_design else "general"
        composer = Composer(self._compose_options, self._policy)
        layout = getattr(self.last_design, "layout", None) if self.last_design else None
        composer.report.design_trial_renders = getattr(layout, "trial_renders", 0) or 0
        try:
            d, t, pdf, eng = composer.compose(doc, theme, profile, sem.stats)
        except Exception as e:
            from .utils.errors import DynamicPDFError
            if isinstance(e, DynamicPDFError):
                raise                   # the document's own error, exactly as without compose()
            # optimizer bug: never let it break an otherwise valid designed render
            eng = LayoutEngine(doc, policy=self._policy, theme=theme)
            buf = io.BytesIO()
            eng.render(buf)
            d, t, pdf = doc, theme, buf.getvalue()
            r = composer.report
            r.strategy, r.status = "baseline", "fallback"
            r.fallbacks.append(f"composition failed ({type(e).__name__}: {e}); designed layout rendered")
            r.page_count = eng.page_count
            # QA must describe these bytes, never a candidate inspected before the crash
            r.qa.pop("pdf", None)
            try:
                composer.pdf_qa = composer.inspect(d, t, pdf)
            except Exception as qe:
                composer.pdf_qa = None
                r.unverified.append(f"pdf_visual_qa ({type(qe).__name__})")
            if composer.pdf_qa is not None:
                r.qa["pdf"] = composer.pdf_qa.summary()
                if composer.pdf_qa.errors:
                    r.status = "failed"
            elif r.unverified:
                r.status = "unverified"
        result = (d, t, pdf, eng, composer)
        self._composition = (key, result)
        self.last_composition = composer.report
        return result

    def _composer_pdf_qa(self):
        """QAReport of the delivered composed PDF (unverified when QA could not run)."""
        from .qa.report import QAReport, sha256
        _, _, data, eng, composer = self._composed()
        if composer.pdf_qa is not None:
            return composer.pdf_qa
        why = [u for u in composer.report.unverified if u.startswith("pdf_")] or ["visual (composer QA unavailable)"]
        return QAReport(format="pdf", pages=eng.page_count, sha256=sha256(data), unverified=why)

    def _prepared(self):
        """(Document, Theme | None) for renderers: the composed layout when
        ``compose()`` is active, otherwise the designed layout."""
        if self._compose_active():
            d, t, _, _, _ = self._composed()
            return d, t
        return self._prepared_base()

    def _prepared_base(self):
        """(Document, Theme | None) ready for a renderer, applying the design plan."""
        doc, theme = self._prepared_inner()
        if self._qa_hints:
            doc = doc.model_copy(deep=True)
            for idx, hint in self._qa_hints.items():
                if 0 <= idx < len(doc.blocks):
                    b = doc.blocks[idx]
                    b.hints = {**(b.hints or {}), **hint}
            doc.blocks = [b for b in doc.blocks if not (b.hints or {}).get("skip")]
        return doc, theme

    def _prepared_inner(self):
        if self._design_mode is None and self._brand is None:
            self.last_design = None
            return self.build(), None
        from .design import plan_design, apply_plan
        sem = self.semantic()
        from .themes import get_theme as _gt
        plan = plan_design(sem, None if self._design_mode in (None, "auto") else self._design_mode,
                           self._brand, base_theme=_gt(self._theme) if self._theme_explicit else None)
        sem = apply_plan(sem, plan)
        from .design.planner import plan_layout, fit_pages
        plan.layout = plan_layout(sem, plan)
        key = (sem.provenance.content_sha256, plan.decision.profile.value, plan.theme.model_dump_json())
        cached = self._fit_cache.get(key)
        if cached is None:
            fit_pages(sem, plan, self._policy)
            self._fit_cache = {key: (plan.theme, plan.layout)}
        else:
            plan.theme, plan.layout = cached
            from .design.tokens import compile_tokens
            plan.tokens = compile_tokens(plan.theme)
        self.last_design = plan
        return sem.to_document(), plan.theme

    def design_explain(self) -> dict:
        """Why each style/layout decision was made (profile, reasons, recipe)."""
        if self._design_mode is None and self._brand is None:
            return {"profile": None, "reasons": ["design() not enabled; using theme "
                                                 f"'{self._theme}' as-is"]}
        self._prepared()
        return self.last_design.explain()

    # ─── Render policy (caller-owned; never taken from document payloads) ───

    def quality(self, mode: str = STRICT) -> 'DocumentBuilder':
        """Error semantics: ``"strict"`` (raise typed errors, default) or
        ``"permissive"`` (visible markers + ``error`` diagnostics)."""
        self._policy = RenderPolicy(error_mode=mode, assets=self._policy.assets,
                                    limits=self._policy.limits)
        return self

    def asset_policy(self, policy: Optional[AssetPolicy] = None, **kwargs) -> 'DocumentBuilder':
        """Configure image/logo loading (e.g. ``allow_remote=True,
        allowed_hosts=("cdn.example.com",)`` or ``base_dir="/srv/assets"``)."""
        assets = policy or AssetPolicy(**kwargs)
        self._policy = RenderPolicy(error_mode=self._policy.error_mode, assets=assets,
                                    limits=self._policy.limits)
        return self

    def limits(self, limits: Optional[ResourceLimits] = None, **kwargs) -> 'DocumentBuilder':
        self._policy = RenderPolicy(error_mode=self._policy.error_mode,
                                    assets=self._policy.assets,
                                    limits=limits or ResourceLimits(**kwargs))
        return self

    @property
    def diagnostics(self) -> list:
        """Diagnostics of the most recent render (list of dicts)."""
        if self.last_render is None:
            return []
        return [d.to_dict() for d in self.last_render.diagnostics.items]

    # ─── Meta ───────────────────────────────────────────────────────

    def meta(self, title: Optional[str] = None, author: Optional[str] = None,
             language: str = "en", subject: Optional[str] = None,
             keywords: Optional[List[str]] = None,
             description: Optional[str] = None) -> 'DocumentBuilder':
        if title:
            self._meta.title = title
        if author:
            self._meta.author = author
        if subject:
            self._meta.subject = subject
        if keywords:
            self._meta.keywords = keywords
        if description:
            self._meta.description = description
        self._meta.language = language
        return self

    def theme(self, name: str) -> 'DocumentBuilder':
        self._theme = name
        return self

    def page_size(self, size: str) -> 'DocumentBuilder':
        self._meta.page_size = PageSize(size)
        return self

    def orientation(self, o: str) -> 'DocumentBuilder':
        self._meta.orientation = Orientation(o)
        return self

    def section_numbering(self, enabled: bool = True) -> 'DocumentBuilder':
        """Enable automatic heading numbering (1, 1.1, 1.1.2, ...)."""
        self._meta.section_numbering = enabled
        return self

    def encrypt(self, owner_password: str, user_password: str = "") -> 'DocumentBuilder':
        """Enable PDF password protection (requires pikepdf)."""
        self._meta.encrypt = True
        self._meta.owner_password = owner_password
        self._meta.user_password = user_password
        return self

    # ─── Text Blocks ───────────────────────────────────────────────

    def heading(self, text: str, level: int = 1, numbered: bool = False,
                color: Optional[str] = None) -> 'DocumentBuilder':
        self._blocks.append(HeadingBlock(text=text, level=level, numbered=numbered, color=color))
        return self

    def paragraph(self, text: str) -> 'DocumentBuilder':
        self._blocks.append(ParagraphBlock(text=text))
        return self

    def rich_text(self, text: str, font_size: Optional[float] = None,
                  color: Optional[str] = None, bold: bool = False,
                  italic: bool = False, alignment: str = "left") -> 'DocumentBuilder':
        self._blocks.append(RichTextBlock(text=text, font_size=font_size, color=color,
                                          bold=bold, italic=italic, alignment=alignment))
        return self

    def note(self, text: str) -> 'DocumentBuilder':
        self._blocks.append(NoteBlock(text=text))
        return self

    # ─── Lists ─────────────────────────────────────────────────────

    def bullet_list(self, items, marker_style: str = "disc") -> 'DocumentBuilder':
        """Bullet list. items can be:
        - List[str] — simple
        - List[dict] — with optional children: [{"text": ..., "children": [...]}, ...]
        """
        from .schema.blocks import ListItemModel
        def _parse(item):
            if isinstance(item, str):
                return ListItemModel(text=item)
            if isinstance(item, dict):
                children = [_parse(c) for c in item.pop('children', [])]
                return ListItemModel(children=children, **item)
            return item
        self._blocks.append(BulletListBlock(
            items=[_parse(i) for i in items], marker_style=marker_style))
        return self

    def numbered_list(self, items, start: int = 1,
                      format: str = "decimal") -> 'DocumentBuilder':
        """Numbered list. items can be:
        - List[str] — simple
        - List[dict] — with optional children: [{"text": ..., "children": [...]}, ...]
        """
        from .schema.blocks import ListItemModel
        def _parse(item):
            if isinstance(item, str):
                return ListItemModel(text=item)
            if isinstance(item, dict):
                children = [_parse(c) for c in item.pop('children', [])]
                return ListItemModel(children=children, **item)
            return item
        self._blocks.append(NumberedListBlock(
            items=[_parse(i) for i in items], start=start, format=format))
        return self

    def checklist(self, items: List[Dict[str, Any]]) -> 'DocumentBuilder':
        cl_items = [ChecklistItem(**i) if isinstance(i, dict) else i for i in items]
        self._blocks.append(ChecklistBlock(items=cl_items))
        return self

    def definition_list(self, items: List[Dict[str, str]]) -> 'DocumentBuilder':
        dl_items = [DefinitionItem(**i) if isinstance(i, dict) else i for i in items]
        self._blocks.append(DefinitionListBlock(items=dl_items))
        return self

    # ─── Table ─────────────────────────────────────────────────────

    def table(self, headers: List[str], rows: List[List[str]], style: str = "striped",
              caption: Optional[str] = None, column_widths: Optional[List[float]] = None,
              header_bg: Optional[str] = None, footer_row: Optional[List[str]] = None,
              table_number: Optional[int] = None,
              header_text_color: Optional[str] = None) -> 'DocumentBuilder':
        self._blocks.append(TableBlock(headers=headers, rows=rows, style=style,
                                       caption=caption, column_widths=column_widths,
                                       header_bg=header_bg, footer_row=footer_row,
                                       table_number=table_number,
                                       header_text_color=header_text_color))
        return self

    # ─── Code ──────────────────────────────────────────────────────

    def code(self, language: str, code_str: str, caption: Optional[str] = None,
             filename: Optional[str] = None, line_numbers: bool = False,
             highlight_lines: Optional[List[int]] = None) -> 'DocumentBuilder':
        self._blocks.append(CodeBlock(language=language, code=code_str, caption=caption,
                                      filename=filename, line_numbers=line_numbers,
                                      highlight_lines=highlight_lines or []))
        return self

    # ─── Media ─────────────────────────────────────────────────────

    def image(self, src: str, width: Optional[float] = None,
              height: Optional[float] = None,
              caption: Optional[str] = None,
              figure_number: Optional[int] = None,
              alt_text: Optional[str] = None,
              alignment: str = "center",
              border: bool = False,
              shadow: bool = False) -> 'DocumentBuilder':
        self._blocks.append(ImageBlock(src=src, width=width, height=height,
                                       caption=caption, figure_number=figure_number,
                                       alt_text=alt_text, alignment=alignment,
                                       border=border, shadow=shadow))
        return self

    def chart(self, chart_type: str, data: Any, title: Optional[str] = None,
              colors: Optional[List[str]] = None, width: float = 6.0,
              height: float = 4.0, x_label: Optional[str] = None,
              y_label: Optional[str] = None, legend: bool = True) -> 'DocumentBuilder':
        self._blocks.append(ChartBlock(chart_type=chart_type, data=data, title=title,
                                       colors=colors, width=width, height=height,
                                       x_label=x_label, y_label=y_label, legend=legend))
        return self

    def math(self, latex: str) -> 'DocumentBuilder':
        self._blocks.append(MathBlock(latex=latex))
        return self

    def mermaid(self, diagram: str) -> 'DocumentBuilder':
        self._blocks.append(MermaidBlock(diagram=diagram))
        return self

    def diagram(self, diagram_type: str = "flowchart",
                nodes: Optional[List[Any]] = None,
                edges: Optional[List[Any]] = None,
                title: Optional[str] = None,
                direction: Optional[str] = None,
                directed: Optional[bool] = None,
                colors: Optional[List[str]] = None,
                width: float = 6.0,
                height: float = 4.0) -> 'DocumentBuilder':
        self._blocks.append(DiagramBlock(
            diagram_type=diagram_type,
            nodes=nodes or [], edges=edges or [],
            title=title, direction=direction, directed=directed,
            colors=colors, width=width, height=height,
        ))
        return self

    # ─── Callouts & Quotes ─────────────────────────────────────────

    def callout(self, text: str, variant: str = "info",
                title: Optional[str] = None) -> 'DocumentBuilder':
        self._blocks.append(CalloutBlock(text=text, variant=variant, title=title))  # type: ignore
        return self

    def quote(self, text: str, attribution: Optional[str] = None,
              style: str = "blockquote") -> 'DocumentBuilder':
        self._blocks.append(QuoteBlock(text=text, attribution=attribution, style=style))
        return self

    # ─── Metrics & Scores ──────────────────────────────────────────

    def metric_row(self, metrics: List[Dict[str, str]]) -> 'DocumentBuilder':
        items = [MetricItem(**m) for m in metrics]
        self._blocks.append(MetricRowBlock(metrics=items))
        return self

    def progress_bar(self, items: List[Dict], title: Optional[str] = None,
                     subtitle: Optional[str] = None) -> 'DocumentBuilder':
        pb_items = [ProgressBarItem(**i) for i in items]
        self._blocks.append(ProgressBarBlock(items=pb_items, title=title, subtitle=subtitle))
        return self

    def score_display(self, score: float, max_score: float = 100, label: str = "",
                      sublabel: Optional[str] = None, score_color: Optional[str] = None) -> 'DocumentBuilder':
        self._blocks.append(ScoreDisplayBlock(score=score, max_score=max_score, label=label,
                                              sublabel=sublabel, score_color=score_color))
        return self

    def legend(self, items: List[Dict[str, str]], title: Optional[str] = None,
               layout: str = "horizontal") -> 'DocumentBuilder':
        lg_items = [LegendItem(**i) for i in items]
        self._blocks.append(LegendBlock(items=lg_items, title=title, layout=layout))
        return self

    def badge(self, text: str, bg_color: Optional[str] = None,
              color: Optional[str] = None) -> 'DocumentBuilder':
        self._blocks.append(BadgeBlock(text=text, bg_color=bg_color, color=color))
        return self

    # ─── Academic ──────────────────────────────────────────────────

    def footnote(self, marker: str, text: str) -> 'DocumentBuilder':
        self._blocks.append(FootnoteBlock(marker=marker, text=text))
        return self

    def abstract(self, fields: List[Dict[str, str]],
                 keywords: Optional[List[str]] = None) -> 'DocumentBuilder':
        af = [AbstractField(**f) for f in fields]
        self._blocks.append(AbstractBlock(fields=af, keywords=keywords))
        return self

    def bibliography(self, entries: List[Dict[str, str]],
                     style: str = "apa") -> 'DocumentBuilder':
        be = [BibliographyEntry(**e) for e in entries]
        self._blocks.append(BibliographyBlock(entries=be, style=style))
        return self

    def citation(self, key: str, style: str = "numeric") -> 'DocumentBuilder':
        self._blocks.append(CitationBlock(key=key, style=style))
        return self

    def signature(self, name: str, title: Optional[str] = None,
                  date: Optional[str] = None, show_line: bool = True) -> 'DocumentBuilder':
        self._blocks.append(SignatureBlock(name=name, title=title, date=date, show_line=show_line))
        return self

    def timeline(self, events: List[Dict[str, str]],
                 layout: str = "vertical") -> 'DocumentBuilder':
        te = [TimelineEvent(**e) for e in events]
        self._blocks.append(TimelineBlock(events=te, layout=layout))
        return self

    # ─── Shapes & QR ───────────────────────────────────────────────

    def shape(self, shape_type: str = "rect", width: float = 200.0, height: float = 60.0,
              fill_color: Optional[str] = None, stroke_color: Optional[str] = None,
              stroke_width: float = 1.5, stroke_dash: Optional[List[float]] = None,
              alignment: str = "center", corner_radius: float = 8.0,
              label: Optional[str] = None, label_color: Optional[str] = None,
              points: Optional[List[List[float]]] = None,
              start_angle: float = 0.0, end_angle: float = 90.0) -> 'DocumentBuilder':
        self._blocks.append(ShapeBlock(
            shape_type=shape_type, width=width, height=height,
            fill_color=fill_color, stroke_color=stroke_color,
            stroke_width=stroke_width, stroke_dash=stroke_dash,
            alignment=alignment, corner_radius=corner_radius,
            label=label, label_color=label_color,
            points=points, start_angle=start_angle, end_angle=end_angle,
        ))
        return self

    def qrcode(self, data: str, size: float = 120.0, caption: Optional[str] = None,
               alignment: str = "center", error_correction: str = "M") -> 'DocumentBuilder':
        self._blocks.append(QRCodeBlock(
            data=data, size=size, caption=caption,
            alignment=alignment, error_correction=error_correction,
        ))
        return self

    # ─── Layout ────────────────────────────────────────────────────

    def divider(self, color: Optional[str] = None, thickness: float = 1.0,
                style: str = "solid") -> 'DocumentBuilder':
        """Add a divider line. style: solid, dashed, dotted."""
        self._blocks.append(DividerBlock(color=color, thickness=thickness, style=style))
        return self

    def spacer(self, height: float = 12.0) -> 'DocumentBuilder':
        self._blocks.append(SpacerBlock(height=height))
        return self

    def page_break(self) -> 'DocumentBuilder':
        self._blocks.append(PageBreakBlock())
        return self

    def cover_page(self, title: str, subtitle: Optional[str] = None,
                   logo: Optional[str] = None, date: Optional[str] = None,
                   author: Optional[str] = None,
                   background_color: Optional[str] = None) -> 'DocumentBuilder':
        self._blocks.append(CoverPageBlock(title=title, subtitle=subtitle,
                                           logo=logo, date=date, author=author,
                                           background_color=background_color))
        return self

    def watermark(self, text: str, opacity: float = 0.08,
                  color: str = "#cccccc") -> 'DocumentBuilder':
        """Add a diagonal watermark (e.g., 'DRAFT', 'CONFIDENTIAL')."""
        self._blocks.append(WatermarkBlock(text=text, opacity=opacity, color=color))
        return self

    def table_of_contents(self, depth: int = 3,
                          style: str = "default") -> 'DocumentBuilder':
        """Add an auto-generated table of contents."""
        self._blocks.append(TOCBlock(depth=depth, style=style))
        return self

    # Alias
    toc = table_of_contents

    def introduction_page(self, title: str = "Introduction",
                          content: str = "",
                          subtitle: Optional[str] = None,
                          accent_color: Optional[str] = None) -> 'DocumentBuilder':
        """Add a styled introduction / preface page."""
        self._blocks.append(IntroductionPageBlock(
            title=title, content=content, subtitle=subtitle,
            accent_color=accent_color,
        ))
        return self

    def two_column(self, left: List[Any], right: List[Any],
                   ratio: float = 0.5) -> 'DocumentBuilder':
        """Two-column layout."""
        self._blocks.append(TwoColumnBlock(left=left, right=right, ratio=ratio))
        return self

    def sidebar(self, main_content: List[Any], sidebar_content: List[Any],
                sidebar_position: str = "right",
                sidebar_ratio: float = 0.3) -> 'DocumentBuilder':
        """Main content with a sidebar."""
        self._blocks.append(SidebarBlock(
            main_content=main_content, sidebar_content=sidebar_content,
            sidebar_position=sidebar_position, sidebar_ratio=sidebar_ratio,
        ))
        return self

    # ─── Build & Render ────────────────────────────────────────────

    def add_block(self, block) -> 'DocumentBuilder':
        """Add a raw Block object (for advanced use)."""
        self._blocks.append(block)
        return self

    def add_blocks(self, blocks: list) -> 'DocumentBuilder':
        """Add multiple raw Block objects."""
        self._blocks.extend(blocks)
        return self

    def build(self) -> Document:
        return Document(meta=self._meta, theme=self._theme, blocks=self._blocks)

    def _engine(self) -> LayoutEngine:
        doc, theme = self._prepared()
        self.last_render = LayoutEngine(doc, policy=self._policy, theme=theme)
        return self.last_render

    def render(self, output=None) -> Optional[bytes]:
        """Render to a file path (str), file-like object, or return bytes (if output is None).

        Nothing is written to ``output`` unless rendering (and encryption, if
        requested) succeeded.
        """
        if self._compose_active():
            from .layout.engine import _write_output
            _, _, pdf, eng, _ = self._composed()
            self.last_render = eng
            if output is None:
                return pdf
            _write_output(output, pdf)
            return None
        engine = self._engine()
        if output is None:
            buffer = io.BytesIO()
            engine.render(buffer)
            return buffer.getvalue()
        engine.render(output)
        return None

    # ─── Multi-format export ───────────────────────────────────────

    def render_docx(self, output=None) -> Optional[bytes]:
        """Render an editable Word document (same semantic model and design as PDF)."""
        from .core.normalize import normalize
        from .renderers.docx_renderer import render_docx
        from .themes import get_theme as _get_theme
        doc, theme = self._prepared()
        sem = normalize(doc, source_kind=self._source_kind, source_text=self._source_text,
                        front_matter=self.front_matter)
        data, col = render_docx(sem, theme or _get_theme(doc.theme), self._policy)
        self.last_docx_diagnostics = col
        if output is None:
            return data
        from .layout.engine import _write_output
        _write_output(output, data)
        return None

    def qa(self, fmt: str = "pdf", max_attempts: int = 3, visual: bool = True):
        """Render with visual/structural QA and bounded auto-fix. Returns (bytes, QAReport).

        In strict mode remaining errors raise ``QualityError``; in permissive
        mode the report is returned with ``passed == False``.
        """
        from .qa.loop import render_with_qa
        from .utils.errors import QualityError
        if self._compose_active():
            # the composer already inspected/repaired the PDF within its budget;
            # DOCX is checked once on its own rendered output (no recomposition)
            if fmt == "pdf":
                _, _, data, eng, composer = self._composed()
                self.last_render = eng
                report = self._composer_pdf_qa()
            else:
                data, report = render_with_qa(self, fmt, max_attempts=1, visual_docx=visual)
                self.last_composition.qa["docx"] = report.summary()
                self.last_composition.unverified += [f"docx_{u}" for u in report.unverified]
        else:
            data, report = render_with_qa(self, fmt, max_attempts=max_attempts, visual_docx=visual)
        self.last_qa = report
        if report.errors and self._policy.strict:
            raise QualityError(report.summary() + ": " + "; ".join(
                f.message for f in report.errors[:5]), report)
        return data, report

    def export(self, path: str, format: Optional[str] = None, qa: bool = False) -> 'ExportResult':
        """Export to ``path``; format inferred from the extension (``.pdf``/``.docx``)
        unless given as ``"pdf"`` or ``"docx"``. ``qa=True`` inspects the rendered
        pages, auto-fixes measurable layout defects (bounded retries) and attaches
        the QA report."""
        import os
        fmt = (format or os.path.splitext(path)[1].lstrip(".") or "pdf").lower()
        if fmt not in ("pdf", "docx"):
            raise ValueError(f"Unsupported export format {fmt!r}; use 'pdf' or 'docx'")
        if not self._design_explicit and self._design_mode is None:
            # export() is a new-style API: intelligent design unless opted out
            # with design(None). Legacy render()/render_bytes() are unchanged.
            self._design_mode = "auto"
            try:
                return self.export(path, format=fmt, qa=qa)
            finally:
                self._design_mode = None
        result = ExportResult()
        if qa:
            from .layout.engine import _write_output
            data, report = self.qa(fmt)
            _write_output(path, data)
            result.qa[fmt] = report
            if fmt == "pdf":
                result.pdf_path, result.page_count = path, report.pages
                result.diagnostics = self.diagnostics
            else:
                result.docx_path = path
                result.diagnostics = [d.to_dict() for d in self.last_docx_diagnostics.items]
            result.profile = self.last_design.decision.profile.value if self.last_design else None
            if self._compose_active():
                result.composition = self.last_composition.model_dump()
            return result
        if fmt == "pdf":
            self.render(path)
            result.pdf_path = path
            result.page_count = self.last_render.page_count
            result.diagnostics = self.diagnostics
            if self._compose_active():
                result.qa["pdf"] = self._composer_pdf_qa()
        else:
            self.render_docx(path)
            result.docx_path = path
            result.diagnostics = [d.to_dict() for d in self.last_docx_diagnostics.items]
        result.profile = self.last_design.decision.profile.value if self.last_design else None
        if self._compose_active():
            result.composition = self.last_composition.model_dump()
        return result

    def export_both(self, directory: str, basename: Optional[str] = None,
                    qa: bool = False) -> 'ExportResult':
        """Export PDF and DOCX from the same semantic document into ``directory``."""
        import os
        import re as _re
        os.makedirs(directory, exist_ok=True)
        stem = basename or _re.sub(r"[^\w.-]+", "_", (self._meta.title or "document")).strip("_") or "document"
        pdf = self.export(os.path.join(directory, stem + ".pdf"), qa=qa)
        docx = self.export(os.path.join(directory, stem + ".docx"), qa=qa)
        res = ExportResult(pdf_path=pdf.pdf_path, docx_path=docx.docx_path,
                           page_count=pdf.page_count, profile=pdf.profile,
                           diagnostics=pdf.diagnostics + [dict(d, format="docx") for d in docx.diagnostics])
        res.qa = {**pdf.qa, **docx.qa}
        res.composition = self.last_composition.model_dump() if self._compose_active() else None
        return res

    def render_bytes(self) -> bytes:
        """Render and return raw PDF bytes."""
        buffer = io.BytesIO()
        self._engine().render(buffer)
        return buffer.getvalue()

    def render_base64(self) -> str:
        """Render and return base64-encoded PDF string."""
        return base64.b64encode(self.render_bytes()).decode("utf-8")

    @classmethod
    def from_markdown(cls, markdown: str, theme: Optional[str] = None,
                      policy: Optional[RenderPolicy] = None) -> 'DocumentBuilder':
        """Create a DocumentBuilder pre-populated from a Markdown string.

        Front matter keys ``title``, ``author``, ``subject``, ``description``,
        ``keywords`` and ``language``/``lang`` populate document metadata.
        """
        from .markdown.preprocessors import preprocess_markdown
        from .markdown.parser import parse_markdown
        builder = cls(theme=theme, policy=policy)
        max_chars = builder._policy.limits.max_input_chars
        if len(markdown) > max_chars:
            raise ResourceLimitError(
                f"Markdown input length ({len(markdown)}) exceeds limit ({max_chars})")
        fm, blocks = parse_markdown(preprocess_markdown(markdown))
        kw = {k: fm[k] for k in ("title", "author", "subject", "description") if isinstance(fm.get(k), str)}
        if isinstance(fm.get("keywords"), list):
            kw["keywords"] = fm["keywords"]
        elif isinstance(fm.get("keywords"), str) and fm["keywords"]:
            kw["keywords"] = [k.strip() for k in fm["keywords"].split(",") if k.strip()]
        lang = fm.get("language") or fm.get("lang")
        builder.meta(language=lang if isinstance(lang, str) and lang else "en", **kw)
        if isinstance(fm.get("theme"), str) and theme is None:
            builder._theme = fm["theme"]
            builder._theme_explicit = True
        if isinstance(fm.get("document_type"), str) and fm["document_type"]:
            builder.document_type(fm["document_type"])
        if fm.get("direction") in ("ltr", "rtl"):
            builder.direction(fm["direction"])
        builder.front_matter = fm
        builder._source_kind = "markdown"
        builder._source_text = markdown
        builder._blocks.extend(blocks)
        return builder


# ─── Standalone helpers ───────────────────────────────────────────────────────

def render_from_json(payload: dict, policy: Optional[RenderPolicy] = None) -> dict:
    """Render a PDF from a Document dict.

    Returns ``{success, status, pdf_base64, metadata, diagnostics}``. In strict
    mode (default) failures raise typed ``DynamicPDFError`` subclasses; in
    permissive mode ``status`` is ``"degraded"`` when any block failed.
    """
    from .schema.document import Document
    doc = Document.model_validate(payload)
    buffer = io.BytesIO()
    engine = LayoutEngine(doc, policy=policy)
    engine.render(buffer)
    pdf_bytes = buffer.getvalue()
    return {
        "success": True,
        "status": engine.diagnostics.status,
        "pdf_base64": base64.b64encode(pdf_bytes).decode("utf-8"),
        "metadata": {"file_size_bytes": len(pdf_bytes), "page_count": engine.page_count},
        "diagnostics": [d.to_dict() for d in engine.diagnostics.items],
    }


def markdown_to_pdf(markdown: str, output_path: str, theme: str = "claude") -> None:
    """Convert a Markdown string to a PDF file."""
    DocumentBuilder.from_markdown(markdown, theme=theme).render(output_path)


def render_to_bytes(blocks: list, theme: str = "claude") -> bytes:
    """Render a list of Block objects to PDF bytes."""
    builder = DocumentBuilder(theme=theme)
    builder._blocks.extend(blocks)
    return builder.render_bytes()


def render_to_base64(blocks: list, theme: str = "claude") -> str:
    """Render a list of Block objects to a base64-encoded PDF string."""
    return base64.b64encode(render_to_bytes(blocks, theme)).decode("utf-8")
