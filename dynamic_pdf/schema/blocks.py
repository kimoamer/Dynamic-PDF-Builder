"""
Block models — complete catalog of content primitives.
Every block is a Pydantic v2 model with Literal discriminator.
"""
from typing import List, Optional, Union, Dict, Any, Literal, Annotated
from pydantic import BaseModel, Field
from .media import ImageTreatment, MediaPlacement, RepeatScope
from .media_intent import MediaIntent

# ─────────────────────── Base ───────────────────────

class BaseBlock(BaseModel):
    id: Optional[str] = None          # Anchor ID for cross-references
    lang: Optional[str] = None        # Per-block language override (PDF/UA)
    # Layout hints set by the design planner (renderer-agnostic, never content)
    hints: Optional[Dict[str, Any]] = None

# ─────────────────────── Text Primitives ───────────────────────

class HeadingBlock(BaseBlock):
    type: Literal["heading"] = "heading"
    text: str
    level: int = Field(ge=1, le=6, default=1)
    numbered: bool = False
    color: Optional[str] = None

class ParagraphBlock(BaseBlock):
    type: Literal["paragraph"] = "paragraph"
    text: str

class RichTextBlock(BaseBlock):
    type: Literal["rich_text"] = "rich_text"
    text: str
    font_size: Optional[float] = None
    color: Optional[str] = None
    bold: bool = False
    italic: bool = False
    alignment: str = "left"

class NoteBlock(BaseBlock):
    type: Literal["note"] = "note"
    text: str

# ─────────────────────── Lists ───────────────────────

class ListItemModel(BaseModel):
    """A single list item that may itself contain nested sub-items."""
    text: str
    children: List["ListItemModel"] = Field(default_factory=list)
    checked: Optional[bool] = None        # for mixed checklist/bullet
    children_ordered: Optional[bool] = None  # children form an ordered list (None = inherit)

ListItemModel.model_rebuild()  # resolve forward reference

# Accept both plain strings and ListItemModels so old API still works
ListItemInput = Union[str, ListItemModel]

class BulletListBlock(BaseBlock):
    type: Literal["bullet_list"] = "bullet_list"
    items: List[ListItemInput]
    nested: bool = False
    marker_style: str = "disc"        # disc, circle, square, dash, arrow, check

    @classmethod
    def from_strings(cls, items: List[str], **kw) -> "BulletListBlock":
        return cls(items=[ListItemModel(text=i) for i in items], **kw)

class NumberedListBlock(BaseBlock):
    type: Literal["numbered_list"] = "numbered_list"
    items: List[ListItemInput]
    start: int = 1
    format: str = "decimal"           # decimal, lower_alpha, upper_alpha, lower_roman, upper_roman

class ChecklistItem(BaseModel):
    text: str
    checked: bool = False

class ChecklistBlock(BaseBlock):
    """GFM task list: - [ ] / - [x]"""
    type: Literal["checklist"] = "checklist"
    items: List[ChecklistItem]

class DefinitionItem(BaseModel):
    term: str
    definition: str

class DefinitionListBlock(BaseBlock):
    """HTML <dl>/<dt>/<dd> equivalent for glossaries and specs."""
    type: Literal["definition_list"] = "definition_list"
    items: List[DefinitionItem]

# ─────────────────────── Tables ───────────────────────

class TableBlock(BaseBlock):
    type: Literal["table"] = "table"
    headers: List[str]
    rows: List[List[str]]
    column_widths: Optional[List[float]] = None
    style: str = "striped"
    caption: Optional[str] = None
    header_bg: Optional[str] = None
    header_text_color: Optional[str] = None
    footer_row: Optional[List[str]] = None          # Summary/total row
    table_number: Optional[int] = None              # Auto-numbering: "Table 1"

# ─────────────────────── Code ───────────────────────

class CodeBlock(BaseBlock):
    type: Literal["code"] = "code"
    language: str = "text"
    code: str
    line_numbers: bool = False
    highlight_lines: List[int] = Field(default_factory=list)
    caption: Optional[str] = None
    filename: Optional[str] = None                  # VS Code-style filename header

# ─────────────────────── Media ───────────────────────

class ImageBlock(BaseBlock):
    type: Literal["image"] = "image"
    src: str
    caption: Optional[str] = None
    alt_text: Optional[str] = None                  # WCAG 1.1.1
    alignment: str = "center"
    width: Optional[float] = None                   # points; the picture keeps its proportions
    height: Optional[float] = None                  # points
    figure_number: Optional[int] = None             # "Figure 1"
    border: bool = False
    shadow: bool = False
    placement: Optional[MediaPlacement] = None
    treatment: Optional[ImageTreatment] = None
    source: Optional[str] = None                    # attribution, set under the caption
    intent: Optional[MediaIntent] = None

class ChartBlock(BaseBlock):
    type: Literal["chart"] = "chart"
    chart_type: str                                 # bar, vertical_bar, horizontal_bar, grouped_bar, stacked_bar, line, area, pie, donut, scatter, bubble, histogram, heatmap, waterfall, funnel, gauge, sparkline, treemap
    data: Any
    title: Optional[str] = None
    colors: Optional[List[str]] = None
    x_label: Optional[str] = None
    y_label: Optional[str] = None
    legend: bool = True
    width: float = 6.0                              # inches
    height: float = 4.0                             # inches

# ─────────────────────── Math & Diagrams ───────────────────────

class MathBlock(BaseBlock):
    type: Literal["math"] = "math"
    latex: str
    inline: bool = False                            # inline vs display mode
    equation_number: Optional[int] = None           # "(1)"

class MermaidBlock(BaseBlock):
    type: Literal["mermaid"] = "mermaid"
    diagram: str

class DiagramBlock(BaseBlock):
    """
    Structured diagram: flowchart, tree, network, state, sequence.

    nodes: list of dicts with id, label, shape, color, text_color, border_style
    edges: list of dicts with from, to, label, color, style, curve
           or tuples: (from, to) or (from, to, label)
    """
    type: Literal["diagram"] = "diagram"
    diagram_type: str = "flowchart"             # flowchart, tree, network, state, sequence
    nodes: List[Any] = Field(default_factory=list)
    edges: List[Any] = Field(default_factory=list)
    title: Optional[str] = None
    direction: Optional[str] = None             # TB (top-bottom), LR (left-right)
    directed: Optional[bool] = None             # arrows on edges (auto per type)
    colors: Optional[List[str]] = None
    width: float = 6.0
    height: float = 4.0

# ─────────────────────── Callouts & Quotes ───────────────────────

class CalloutBlock(BaseBlock):
    type: Literal["callout"] = "callout"
    text: str
    title: Optional[str] = None
    variant: str = "info"                           # info, warning, error, success, tip, danger, caution, important, abstract, example
    icon: Optional[str] = None

class QuoteBlock(BaseBlock):
    type: Literal["quote"] = "quote"
    text: str
    attribution: Optional[str] = None
    style: str = "blockquote"                       # blockquote, pullquote, epigraph

# ─────────────────────── Metrics & Scores ───────────────────────

class MetricItem(BaseModel):
    label: str
    value: str
    delta: Optional[str] = None
    icon: Optional[str] = None

class MetricRowBlock(BaseBlock):
    type: Literal["metric_row"] = "metric_row"
    metrics: List[MetricItem]

class ProgressBarItem(BaseModel):
    label: str
    value: float
    max_value: float = 100.0
    color: Optional[str] = None
    benchmark: Optional[float] = None
    delta: Optional[str] = None

class ProgressBarBlock(BaseBlock):
    type: Literal["progress_bar"] = "progress_bar"
    items: List[ProgressBarItem]
    title: Optional[str] = None
    subtitle: Optional[str] = None
    show_value: bool = True
    show_delta: bool = True

class ScoreDisplayBlock(BaseBlock):
    type: Literal["score_display"] = "score_display"
    score: float
    max_score: float = 100.0
    label: str = ""
    sublabel: Optional[str] = None
    score_color: Optional[str] = None
    label_color: Optional[str] = None

class LegendItem(BaseModel):
    label: str
    color: str
    description: Optional[str] = None

class LegendBlock(BaseBlock):
    type: Literal["legend"] = "legend"
    title: Optional[str] = None
    items: List[LegendItem]
    layout: str = "horizontal"

# ─────────────────────── Academic / Professional ───────────────────────

class FootnoteBlock(BaseBlock):
    """Footnote marker + content. Rendered at page bottom."""
    type: Literal["footnote"] = "footnote"
    marker: str                                     # "1", "†", "*"
    text: str

class AbstractField(BaseModel):
    label: str                                      # "Background", "Methods", etc.
    text: str

class AbstractBlock(BaseBlock):
    """IMRAD structured abstract."""
    type: Literal["abstract"] = "abstract"
    fields: List[AbstractField]
    keywords: Optional[List[str]] = None

class BibliographyEntry(BaseModel):
    key: str                                        # "smith2024"
    authors: str
    title: str
    source: str                                     # journal/book/URL
    year: str
    doi: Optional[str] = None

class BibliographyBlock(BaseBlock):
    """Reference list with entries."""
    type: Literal["bibliography"] = "bibliography"
    entries: List[BibliographyEntry]
    style: str = "apa"                              # apa, ieee, chicago

class CitationBlock(BaseBlock):
    """Inline citation marker: [1] or (Smith, 2024)."""
    type: Literal["citation"] = "citation"
    key: str
    style: str = "numeric"                          # numeric, author_year

class SignatureBlock(BaseBlock):
    """Signature line with name, title, date underline."""
    type: Literal["signature"] = "signature"
    name: str
    title: Optional[str] = None
    date: Optional[str] = None
    show_line: bool = True
    line_width: float = 200.0                       # points
    image: Optional[str] = None                     # the signature itself, drawn over the line: a path or data: URI
    alignment: str = "start"                        # start, center or end (left and right also work)

def signature_row(signers):
    """Signatures side by side: one column each, read from the start edge."""
    sigs = [s if isinstance(s, SignatureBlock) else SignatureBlock(**{"line_width": 170.0, **s}) for s in signers]
    if not 1 <= len(sigs) <= 4:
        raise ValueError(f"a row holds 1 to 4 signatures, not {len(sigs)}")
    if len(sigs) == 1:
        return sigs[0]
    if len(sigs) == 2:
        return TwoColumnBlock(left=[sigs[0]], right=[sigs[1]])
    return ThreeColumnBlock(columns=[[x] for x in sigs])

# ─────────────────────── Timeline ───────────────────────

class TimelineEvent(BaseModel):
    date: str
    title: str
    description: Optional[str] = None
    color: Optional[str] = None

class TimelineBlock(BaseBlock):
    """Vertical or horizontal timeline."""
    type: Literal["timeline"] = "timeline"
    events: List[TimelineEvent]
    layout: str = "vertical"                        # vertical, horizontal

# ─────────────────────── Layout ───────────────────────

class DividerBlock(BaseBlock):
    type: Literal["divider"] = "divider"
    style: str = "solid"                            # solid, dashed, dotted
    color: Optional[str] = None
    thickness: float = 1.0

class SpacerBlock(BaseBlock):
    type: Literal["spacer"] = "spacer"
    height: float = 12.0

class PageBreakBlock(BaseBlock):
    type: Literal["page_break"] = "page_break"

class CoverPageBlock(BaseBlock):
    type: Literal["cover_page"] = "cover_page"
    title: str
    subtitle: Optional[str] = None
    logo: Optional[str] = None
    date: Optional[str] = None
    author: Optional[str] = None
    background_color: Optional[str] = None
    layout: Optional[str] = None                    # centered, left_aligned, split
    background_image: Optional[str] = None
    background_treatment: Optional[ImageTreatment] = None
    overlay_color: Optional[str] = None             # laid over the image so the text reads
    overlay_opacity: float = 0.0
    text_color: Optional[str] = None

class TOCBlock(BaseBlock):
    type: Literal["table_of_contents"] = "table_of_contents"
    depth: int = 3
    style: str = "default"
    kind: Literal["contents", "figures", "tables"] = "contents"   # contents, or a list of figures or tables

class WatermarkBlock(BaseBlock):
    type: Literal["watermark"] = "watermark"
    text: str
    opacity: float = 0.1
    color: str = "#cccccc"

class PageMediaBlock(BaseBlock):
    """An image on the page itself, behind or over the text: a background, an image
    watermark or a recurring brand mark. It takes no space in the text flow."""
    type: Literal["page_media"] = "page_media"
    src: str
    scope: RepeatScope = "every_page"
    sections: List[str] = Field(default_factory=list)   # for scope="sections"
    layer: Literal["behind", "front"] = "behind"
    placement: MediaPlacement = Field(default_factory=lambda: MediaPlacement(
        mode="behind_text", relative_to="page"))
    treatment: ImageTreatment = Field(default_factory=lambda: ImageTreatment(fit="cover"))
    alt_text: Optional[str] = None

class PageSectionBlock(BaseBlock):
    """Starts a named run of pages, which can have its own bands and backgrounds."""
    type: Literal["page_section"] = "page_section"
    name: str
    new_page: bool = True

class TwoColumnBlock(BaseBlock):
    type: Literal["two_column"] = "two_column"
    left: List[Any] = Field(default_factory=list)
    right: List[Any] = Field(default_factory=list)
    ratio: float = 0.5

class ThreeColumnBlock(BaseBlock):
    type: Literal["three_column"] = "three_column"
    columns: List[List[Any]] = Field(default_factory=list)

class SidebarBlock(BaseBlock):
    """Floating sidebar next to main text."""
    type: Literal["sidebar"] = "sidebar"
    main_content: List[Any] = Field(default_factory=list)
    sidebar_content: List[Any] = Field(default_factory=list)
    sidebar_position: str = "right"                 # left, right
    sidebar_ratio: float = 0.3

class BadgeBlock(BaseBlock):
    type: Literal["badge"] = "badge"
    text: str
    color: Optional[str] = None
    bg_color: Optional[str] = None
    font_size: float = 10.0

# ─────────────────────── Vector Shapes ───────────────────────

class ShapeBlock(BaseBlock):
    """
    Vector shape drawn directly on canvas via ReportLab primitives.

    shape_type options:
        rect, rounded_rect, circle, ellipse,
        line, arrow,
        polygon  (requires points: [[x,y], ...]),
        arc, wedge  (use start_angle / end_angle in degrees)
    """
    type: Literal["shape"] = "shape"
    shape_type: str = "rect"
    width: float = 200.0                            # pts
    height: float = 60.0                            # pts
    alignment: str = "center"                       # left | center | right
    # Geometry extras
    points: Optional[List[List[float]]] = None      # polygon vertices [[x,y],...]
    start_angle: float = 0.0                        # arc / wedge
    end_angle: float = 90.0
    corner_radius: float = 8.0                      # rounded_rect
    # Style
    fill_color: Optional[str] = None
    stroke_color: Optional[str] = None
    stroke_width: float = 1.5
    stroke_dash: Optional[List[float]] = None       # e.g. [6, 3]
    opacity: float = 1.0
    # Optional label inside the shape
    label: Optional[str] = None
    label_color: Optional[str] = None

# ─────────────────────── QR Code ───────────────────────

class QRCodeBlock(BaseBlock):
    """QR code generated from text or URL (requires qrcode[pil] optional dep)."""
    type: Literal["qrcode"] = "qrcode"
    data: str                                       # URL or text to encode
    size: float = 120.0                             # pts (width = height)
    alignment: str = "center"
    caption: Optional[str] = None
    error_correction: str = "M"                     # L | M | Q | H

# ─────────────────────── Introduction Page ───────────────────────

class IntroductionPageBlock(BaseBlock):
    """Styled introduction / preface page with title, optional subtitle, and body text."""
    type: Literal["introduction_page"] = "introduction_page"
    title: str = "Introduction"
    subtitle: Optional[str] = None
    content: str = ""                               # Markdown; a blank line parts paragraphs
    background_color: Optional[str] = None
    accent_color: Optional[str] = None
    position: Literal["front", "back"] = "front"    # front: a preface, the text starts on the next page; back: a conclusion, on a new page

# ─────────────────────── Layout Archetypes ───────────────────────
# Opt-in page compositions. Each one fits itself to its content and, when it
# cannot, falls back to plain blocks (design/archetypes.py): nothing is dropped.

class SectionOpenerBlock(BaseBlock):
    """Opens a chapter on its own page: a strip on the reading-start edge, text hung from it."""
    type: Literal["section_opener"] = "section_opener"
    title: str
    title_alt: Optional[str] = None           # second-language title
    label: Optional[str] = None               # chapter number or short label
    standfirst: Optional[str] = None
    standfirst_alt: Optional[str] = None
    points: List[str] = Field(default_factory=list)
    chapters: List[str] = Field(default_factory=list)   # the strip shows where this chapter sits
    current: int = 0                          # index into ``chapters``


class PerformanceFigure(BaseModel):
    value: str
    label: str
    delta: Optional[str] = None
    note: Optional[str] = None


class TrendSeries(BaseModel):
    label: str
    periods: List[str]
    values: List[float]                       # the last period is the current one
    display: Optional[List[str]] = None       # formatted values; defaults to the numbers


class PerformancePageBlock(BaseBlock):
    """One page of results in horizontal strata: title, hero figure, tiles, trends, highlights."""
    type: Literal["performance_page"] = "performance_page"
    title: str
    eyebrow: Optional[str] = None
    standfirst: Optional[str] = None
    hero: PerformanceFigure
    tiles: List[PerformanceFigure] = Field(default_factory=list)
    trends: List[TrendSeries] = Field(default_factory=list)
    highlights: List[str] = Field(default_factory=list)


class LedgerRow(BaseModel):
    label: str
    label_alt: Optional[str] = None
    values: List[str]
    total: bool = False


class LedgerSection(BaseModel):
    title: str
    title_alt: Optional[str] = None
    rows: List[LedgerRow]
    note: Optional[str] = None


class ParallelLedgerBlock(BaseBlock):
    """Comparative figures stated once, labelled from each language's own edge."""
    type: Literal["parallel_ledger"] = "parallel_ledger"
    periods: List[str]
    sections: List[LedgerSection]
    emphasis: int = 0                         # index of the emphasised period
    label_header: Optional[str] = None
    label_header_alt: Optional[str] = None
    title_first: bool = False                 # one section: its title stands above the column heads


class ImageTextPanelBlock(BaseBlock):
    """A picture with a live text panel beside it (``split``) or laid over it (``overlay``)."""
    type: Literal["image_text_panel"] = "image_text_panel"
    image: ImageBlock
    paragraphs: List[str] = Field(default_factory=list)
    title: Optional[str] = None
    eyebrow: Optional[str] = None
    layout: Literal["split", "overlay"] = "split"
    side: Literal["start", "end"] = "start"   # where the panel sits, in reading direction
    image_share: float = Field(0.6, ge=0.3, le=0.75)
    height: Optional[float] = Field(None, gt=0)
    panel_color: Optional[str] = None
    tone: Literal["dark", "tint"] = "dark"


class FigureCell(BaseModel):
    """One cell of a matrix: a chart, or a figure with its label."""
    title: Optional[str] = None
    chart: Optional[ChartBlock] = None
    value: Optional[str] = None
    label: Optional[str] = None
    note: Optional[str] = None


class FigureMatrixBlock(BaseBlock):
    """Equal cells under one title; cells run from the reading edge."""
    type: Literal["figure_matrix"] = "figure_matrix"
    figures: List[FigureCell]
    title: Optional[str] = None
    note: Optional[str] = None
    columns: int = Field(2, ge=2, le=4)
    cell_height: float = Field(120.0, gt=0)


class PairedRow(BaseModel):
    first: str
    second: str
    heading: bool = False


class PairedRowColumnsBlock(BaseBlock):
    """Text in two languages, row by row; Arabic takes the right column."""
    type: Literal["paired_row_columns"] = "paired_row_columns"
    rows: List[PairedRow]
    header_first: Optional[str] = None
    header_second: Optional[str] = None


# ─────────────────────── Discriminated Union ───────────────────────

Block = Annotated[
    Union[
        HeadingBlock, ParagraphBlock, RichTextBlock, NoteBlock,
        BulletListBlock, NumberedListBlock, ChecklistBlock, DefinitionListBlock,
        TableBlock, CodeBlock,
        ImageBlock, ChartBlock,
        MathBlock, MermaidBlock, DiagramBlock,
        CalloutBlock, QuoteBlock,
        MetricRowBlock, ProgressBarBlock, ScoreDisplayBlock, LegendBlock,
        FootnoteBlock, AbstractBlock, BibliographyBlock, CitationBlock, SignatureBlock,
        TimelineBlock,
        DividerBlock, SpacerBlock, PageBreakBlock,
        CoverPageBlock, TOCBlock, WatermarkBlock,
        TwoColumnBlock, ThreeColumnBlock, SidebarBlock,
        BadgeBlock, ShapeBlock, QRCodeBlock, IntroductionPageBlock,
        SectionOpenerBlock, PerformancePageBlock, ParallelLedgerBlock,
        ImageTextPanelBlock, FigureMatrixBlock, PairedRowColumnsBlock,
        PageMediaBlock, PageSectionBlock,
    ],
    Field(discriminator="type")
]
