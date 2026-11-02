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


class DocumentBuilder:
    """Fluent API for building PDF documents.

    Example::

        (DocumentBuilder(theme="claude")
            .meta(title="My Report")
            .heading("Introduction")
            .paragraph("Hello world.")
            .render("report.pdf"))
    """

    def __init__(self, theme: str = "claude", policy: Optional[RenderPolicy] = None):
        self._theme = theme
        self._meta = Meta()
        self._blocks: list = []
        self._policy = policy or RenderPolicy()
        self.last_render = None   # LayoutEngine of the most recent render (diagnostics, page_count)

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
        self.last_render = LayoutEngine(self.build(), policy=self._policy)
        return self.last_render

    def render(self, output=None) -> Optional[bytes]:
        """Render to a file path (str), file-like object, or return bytes (if output is None).

        Nothing is written to ``output`` unless rendering (and encryption, if
        requested) succeeded.
        """
        engine = self._engine()
        if output is None:
            buffer = io.BytesIO()
            engine.render(buffer)
            return buffer.getvalue()
        engine.render(output)
        return None

    def render_bytes(self) -> bytes:
        """Render and return raw PDF bytes."""
        buffer = io.BytesIO()
        self._engine().render(buffer)
        return buffer.getvalue()

    def render_base64(self) -> str:
        """Render and return base64-encoded PDF string."""
        return base64.b64encode(self.render_bytes()).decode("utf-8")

    @classmethod
    def from_markdown(cls, markdown: str, theme: str = "claude",
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
        if isinstance(fm.get("theme"), str) and theme == "claude":
            builder._theme = fm["theme"]
        builder.front_matter = fm
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
