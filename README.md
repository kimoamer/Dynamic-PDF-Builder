# Dynamic PDF Builder

> Generate beautiful, professional PDF reports from **Markdown**, **JSON**, or a **fluent Python API** — pure Python, no system dependencies required.

[![Version](https://img.shields.io/badge/version-0.3.0-blue.svg)](https://pypi.org/project/dynamic-pdf-builder/)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-100%25_passing-brightgreen.svg)](#testing)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

---

## Table of Contents

- [Installation](#installation)
- [Quick Start](#quick-start)
- [Input Modes](#input-modes)
- [CLI Usage](#cli-usage)
- [Themes](#themes)
- [Header & Footer Styles](#header--footer-styles)
- [Block Reference](#block-reference)
- [Section Numbering](#section-numbering)
- [Table of Contents](#table-of-contents-toc)
- [Introduction Page](#introduction-page)
- [Drop Cap](#drop-cap)
- [Arabic & RTL Support](#arabic--rtl-support)
- [PDF Encryption](#pdf-encryption)
- [Custom Fonts](#custom-fonts)
- [Typography Standards](#typography-standards)
- [Project Structure](#project-structure)
- [Dependencies](#dependencies)
- [Testing](#testing)
- [Changelog](#changelog)

---

## Installation

```bash
pip install -e .
```

Core dependencies install automatically. Optional feature sets:

```bash
pip install -e ".[diagrams]"   # Mermaid diagrams via Playwright
pip install -e ".[plotly]"     # Plotly charts
pip install -e ".[pdf]"        # PDF merge / encrypt via pikepdf
pip install -e ".[qrcode]"     # QR code blocks
pip install -e ".[rtl]"        # Arabic & Hebrew RTL support
pip install -e ".[all]"        # Everything
pip install -e ".[dev]"        # Testing + linting tools
```

---

## Quick Start

```python
from dynamic_pdf import DocumentBuilder

(DocumentBuilder(theme="claude")
    .meta(title="Q1 Report", author="Finance Team")
    .cover_page(title="Q1 Report 2026", subtitle="Confidential")
    .heading("Executive Summary")
    .paragraph("Revenue grew **23%** year-over-year, driven by product expansion.")
    .metric_row([
        {"label": "Revenue", "value": "$4.2M",  "delta": "+23%"},
        {"label": "Users",   "value": "18,400", "delta": "+11%"},
        {"label": "NPS",     "value": "72"},
    ])
    .chart("bar", data={"Q1": 3.1, "Q2": 3.4, "Q3": 3.8, "Q4": 4.2},
           title="Quarterly Revenue ($M)")
    .heading("Key Findings", level=2)
    .bullet_list(["Expansion into APAC drove top-line growth.",
                  "Churn reduced from 4.2% to 2.1%.",
                  "New product lines contributed 38% of revenue."])
    .render("report.pdf"))
```

---

## Input Modes

### 1. Fluent Python API

```python
from dynamic_pdf import DocumentBuilder

builder = DocumentBuilder(theme="corporate_dark")
builder.meta(title="Quarterly Review", author="Finance Team")
builder.heading("Revenue Analysis")
builder.paragraph("Our **Q1 revenue** grew by *12%* quarter-over-quarter.")
builder.table(
    headers=["Quarter", "Revenue", "Growth"],
    rows=[["Q4 2025", "$2.1M", "—"], ["Q1 2026", "$2.35M", "+12%"]],
    footer_row=["Total", "$4.45M", ""],
)
builder.render("revenue.pdf")
```

### 2. Markdown → PDF

```python
from dynamic_pdf import markdown_to_pdf

markdown_to_pdf("""
# Quarterly Report

Revenue grew **12%** this quarter.

| Quarter | Revenue |
|---------|---------|
| Q4 2025 | $2.1M   |
| Q1 2026 | $2.35M  |

```python
growth = ((2.35 - 2.1) / 2.1) * 100
```

> "Execution is everything." — Management
""", "report.pdf", theme="claude")
```

### 3. JSON / dict API

```python
from dynamic_pdf import render_from_json
import base64

result = render_from_json({
    "theme": "corporate_dark",
    "meta": {"title": "Report", "author": "Agent"},
    "blocks": [
        {"type": "heading",   "text": "Summary", "level": 1},
        {"type": "paragraph", "text": "Built from JSON."},
        {"type": "callout",   "text": "Validated by Pydantic v2.", "variant": "info"},
        {"type": "chart",     "chart_type": "bar",
         "data": {"Q1": 3.1, "Q2": 3.4}, "title": "Revenue"},
    ]
})

with open("output.pdf", "wb") as f:
    f.write(base64.b64decode(result["pdf_base64"]))
```

### 4. Render to bytes / base64

```python
from dynamic_pdf import render_to_bytes, render_to_base64
from dynamic_pdf.schema.blocks import HeadingBlock, ParagraphBlock

blocks = [HeadingBlock(text="H"), ParagraphBlock(text="Body.")]

pdf_bytes = render_to_bytes(blocks, theme="claude")
b64_str   = render_to_base64(blocks, theme="claude")

# Return None to get bytes directly from DocumentBuilder
data = DocumentBuilder().heading("Report").render()  # returns bytes
```

### 5. Streaming API (for LLM incremental output)

```python
from dynamic_pdf import stream

with stream("output.pdf", theme="claude") as s:
    for chunk in llm_stream:   # any iterable of Markdown strings
        s.write(chunk)
# PDF is rendered automatically on context exit
```

---

## CLI Usage

After installation, a `dynamic-pdf` command is available:

```bash
# Render a Markdown file to PDF
dynamic-pdf render report.md -o report.pdf --theme claude

# Enable automatic section numbering
dynamic-pdf render report.md --section-numbers

# Render a JSON document
dynamic-pdf render payload.json -o output.pdf

# List all available themes
dynamic-pdf themes

# Show version
dynamic-pdf version
```

---

## Themes

| Theme | Style | Drop Cap | Best For |
|-------|-------|----------|----------|
| `claude` | Warm terracotta accent, white background | ✅ | General reports, AI summaries |
| `chatgpt` | Green accent, clean web-style spacing | ❌ | Technical docs, API outputs |
| `corporate_dark` | Dark navy header, teal accent | ✅ | Board decks, executive reports |
| `academic` | Serif-style, APA-ready | ✅ | Research papers, theses |
| `modern_minimal` | Light grey, hairline rules | ❌ | Product briefs, pitch decks |
| `data_report` | Dashboard-style, colourful metrics | ❌ | Analytics, KPI dashboards |
| `government` | Formal, high-contrast, no decorations | ❌ | Public-sector documents |

```python
from dynamic_pdf import list_themes, get_theme
print(list_themes())   # ['claude', 'chatgpt', ...]
```

### Custom Theme

```python
from dynamic_pdf.schema.theme import (
    Theme, ColorPalette, Typography, SpacingScale,
    HeaderFooterConfig, DecorationConfig,
)
from dynamic_pdf.themes import register_theme

my_theme = Theme(
    name="my_brand",
    colors=ColorPalette(
        primary="#2D3748",
        accent="#E53E3E",
        header_bg="#2D3748",
        footer_bg="#2D3748",
        drop_cap="#E53E3E",
    ),
    typography=Typography(
        heading_family="Inter",
        body_family="Inter",
        mono_family="JetBrains Mono",
        arabic_family="Amiri",        # RTL / Arabic text
        base_size=11.0,               # 11 pt body
        line_height=1.5,
        heading_scale=[1.45, 1.27, 1.18, 1.09, 1.0, 0.91],
        caption_size_ratio=0.73,
    ),
    spacing=SpacingScale(
        page_margin_top=72.0,         # 1 inch
        page_margin_bottom=72.0,
        page_margin_left=72.0,
        page_margin_right=72.0,
        block_gap=8.0,
        first_line_indent=36.0,       # 0.5 inch paragraph indent
    ),
    header_footer=HeaderFooterConfig(
        enabled=True,
        header_style="bar",
        footer_style="three_column",
        title="My Company Report",
        copyright_text="© 2026 My Company. All rights reserved.",
        company_name="My Company",
        show_page_number=True,
        page_number_format="Page {n} of {total}",
    ),
    decorations=DecorationConfig(
        drop_cap_enabled=True,
        drop_cap_lines=3,
        drop_cap_font_size_ratio=3.2,
        drop_cap_color="#E53E3E",
        heading_accent_bar=True,
        heading_accent_bar_width=4.0,
        table_row_alternating=True,
    ),
)
register_theme(my_theme)

DocumentBuilder(theme="my_brand").heading("Hello").render("out.pdf")
```

---

## Header & Footer Styles

Over **100+ visual combinations** by mixing styles, colors, and layout slots.

### Header Styles (`header_style`)

| Style | Description |
|-------|-------------|
| `bar` | Full-width solid color bar (default) |
| `gradient` | Horizontal / vertical / diagonal gradient bar |
| `line` | Thin rule at the bottom of the header area |
| `double_line` | Two parallel thin rules |
| `minimal` | Text only, no background or lines |
| `banner` | Large full-bleed colour band |
| `accent_top` | Thin accent stripe at top + text below |
| `underline` | Title with decorative underline |
| `boxed` | Text inside a bordered rectangle |
| `split` | Two-tone left/right halves |
| `sidebar` | Vertical colour bar on left or right edge |
| `academic` | Centred italic title, rule below |
| `modern` | Full bar + bold sans-serif title |
| `logo_left` | Logo left + title right |
| `logo_right` | Logo right + title left |
| `logo_centered` | Centred logo with title underneath |

### Footer Styles (`footer_style`)

| Style | Description |
|-------|-------------|
| `bar` | Full-width solid colour bar (default) |
| `gradient` | Gradient bar |
| `line` | Thin rule above text |
| `minimal` | Just text, no decoration |
| `centered` | All content centred |
| `three_column` | Left \| Centre \| Right |
| `two_column` | Left \| Right only |
| `page_only` | Just page number |
| `copyright_line` | Thin line + copyright centred + page right |
| `academic` | Italic centred text + page number |
| `logo_left` | Logo left-aligned in footer |
| `logo_right` | Logo right-aligned in footer |
| `sidebar` | Vertical bar (mirrors header sidebar) |

### Full HeaderFooterConfig Reference

```python
from dynamic_pdf.schema.theme import HeaderFooterConfig

HeaderFooterConfig(
    enabled=True,
    height=55.0,                        # header height in pts
    footer_height=44.0,

    # ── Style selection ──
    header_style="bar",
    footer_style="three_column",

    # ── Header content ──
    logo="logo.png",                    # path to logo image
    logo_max_height=30.0,
    title="Annual Report 2026",
    subtitle="Confidential • Draft",

    # ── Header colours ──
    header_bg="#0B1D3A",
    header_text_color="#FFFFFF",
    header_bg_gradient_end="#1A3A6A",   # for gradient style
    header_bg_gradient_direction="horizontal",  # horizontal | vertical | diagonal
    header_border_color="#E2E8F0",
    header_border_width=1.0,
    header_accent_color="#E53E3E",

    # ── Header layout slots ──
    header_left="logo",                 # logo | title | subtitle | page | date | "text:Custom"
    header_center="title",
    header_right="date",

    # ── Footer content ──
    show_page_number=True,
    page_number_format="Page {n} of {total}",  # {n} current, {total} page count
    show_date=True,
    date_format="%d %B %Y",
    copyright_text="© 2026 Company Ltd.",
    company_name="Company Ltd",
    address="123 Business St, London, UK",
    phone="+44 20 1234 5678",
    email="info@company.com",
    website="www.company.com",
    footer_text="Prepared by Finance Team",
    footer_logo="footer_logo.png",
    footer_logo_max_height=20.0,

    # ── Footer colours ──
    footer_bg="#0B1D3A",
    footer_text_color="#FFFFFF",
    footer_bg_gradient_end="#1A3A6A",

    # ── Footer layout slots ──
    footer_left="date",
    footer_center="copyright",
    footer_right="page",

    # ── Sidebar (for sidebar style) ──
    sidebar_width=6.0,
    sidebar_color="#E53E3E",
    sidebar_position="left",            # left | right

    # ── Separators ──
    header_separator=True,
    footer_separator=True,

    # ── Skip on first page (for cover pages) ──
    skip_first_page_header=True,
    skip_first_page_footer=True,
)
```

---

## Block Reference

### Text Blocks

| Method | Description |
|--------|-------------|
| `.heading(text, level=1, color=None)` | H1–H6 with optional accent bar on H1–H3 |
| `.paragraph(text)` | Body text with first-line indent + inline Markdown |
| `.rich_text(text, font_size, color, bold, italic, alignment)` | Explicit style overrides |
| `.note(text)` | Smaller muted footnote-style text |

**Inline Markdown** supported inside `.paragraph()` and `.rich_text()`:

```
**bold**        *italic*         `code`          ~~strikethrough~~
[link](url)     ==highlight==    ^superscript^   <sub>subscript</sub>
[^1]            → footnote ref
---             → em-dash (—)
...             → ellipsis (…)
```

### Lists

```python
builder.bullet_list(["Item one", "Item two", "Item three"])
builder.numbered_list(["First", "Second", "Third"], start=1)

builder.checklist([
    {"text": "Review draft",      "checked": True},
    {"text": "Send for approval", "checked": False},
])

builder.definition_list([
    {"term": "API",  "definition": "Application Programming Interface"},
    {"term": "REST", "definition": "Representational State Transfer"},
])
```

### Table

```python
builder.table(
    headers=["Name", "Score", "Status"],
    rows=[["Alice", "95", "Pass"], ["Bob", "72", "Pass"]],
    style="striped",              # striped | bordered | minimal | grid | clean
    header_bg="#0B1D3A",
    header_text_color="#FFFFFF",
    caption="Participant results",
    table_number=1,               # auto-label: "Table 1: ..."
    footer_row=["Average", "83.5", ""],
    column_widths=[200, 80, 80],  # pts; None = auto-distributed
)
```

### Code Block

```python
builder.code(
    "python",
    'def hello():\n    return "world"',
    filename="main.py",          # VS Code-style filename header bar
    caption="Example function",  # alternative to filename
    line_numbers=True,           # show gutter with line numbers
    highlight_lines=[2, 5],      # highlight specific lines
)
```

Syntax highlighting via **Pygments** — 500+ languages. Monokai style on dark themes, default style on light themes.

### Image

```python
builder.image(
    "chart.png",
    width=400,                   # pts; None = fit to page
    height=300,
    caption="Revenue trend Q1–Q4",
    figure_number=1,             # auto-label: "Figure 1: ..."
    alt_text="Bar chart showing quarterly revenue",
    alignment="center",          # left | center | right
    border=False,
    shadow=False,
)
```

### Charts (17 types)

All rendered as vector SVG via matplotlib:

```python
builder.chart(
    chart_type="bar",
    data={"Q1": 100, "Q2": 150, "Q3": 200},
    title="Quarterly Revenue",
    colors=["#3182CE", "#38A169", "#E53E3E"],
    x_label="Quarter",
    y_label="Revenue ($k)",
    width=6.0,   # inches
    height=4.0,
    legend=True,
)
```

| Type | Data Format | Description |
|------|-------------|-------------|
| `bar` | `{label: value}` | Vertical bar chart |
| `horizontal_bar` | `{label: value}` | Horizontal bar chart |
| `grouped_bar` | `{series: {cat: val}}` | Side-by-side groups |
| `stacked_bar` | `{series: {cat: val}}` | Stacked bars |
| `line` | `{label: value}` | Line chart with markers |
| `area` | `{label: value}` | Filled area chart |
| `pie` | `{label: value}` | Pie chart |
| `donut` | `{label: value}` | Donut chart |
| `scatter` | `[{x, y}]` | Scatter plot |
| `bubble` | `[{x, y, size}]` | Bubble chart |
| `histogram` | `[values]` | Distribution histogram |
| `heatmap` | `{rows, cols, values}` | 2D colour matrix |
| `waterfall` | `{label: value}` | Financial bridge chart |
| `funnel` | `{label: value}` | Conversion funnel |
| `gauge` | `float` or `{value, min, max}` | Semicircular gauge |
| `sparkline` | `{label: value}` | Minimal inline chart |
| `treemap` | `{label: value}` | Hierarchical rectangles |

**Multi-series example:**
```python
builder.chart("grouped_bar", data={
    "categories": ["Q1", "Q2", "Q3"],
    "series": {"Product A": [10, 20, 15], "Product B": [5, 10, 20]},
}, title="Sales by Product")
```

### Diagrams (5 types)

Custom vector diagrams rendered via matplotlib:

```python
builder.diagram(
    diagram_type="flowchart",
    title="Build Pipeline",
    nodes=[
        {"id": "src",    "label": "Source", "color": "#2C3E50"},
        {"id": "build",  "label": "Build",  "color": "#2980B9"},
        {"id": "test",   "label": "Test",   "color": "#27AE60"},
        {"id": "deploy", "label": "Deploy", "color": "#E67E22"},
    ],
    edges=[
        ("src", "build"), ("build", "test"),
        {"from": "test", "to": "deploy", "label": "pass"},
    ],
    direction="LR",       # TB (top-bottom) or LR (left-right)
    width=6.0, height=3.0,
)
```

| Type | Description |
|------|-------------|
| `flowchart` | Directed graph with layered layout |
| `tree` | Hierarchical tree (org chart, AST) |
| `network` | Force-directed graph |
| `state` | State machine with transitions |
| `sequence` | Vertical sequence / swim-lane |

### Math (LaTeX)

```python
builder.math(r"E = mc^2")
builder.math(r"\sum_{i=0}^{n} i^2 = \frac{(n^2+n)(2n+1)}{6}")
```

Rendered via `matplotlib.mathtext` — **no LaTeX installation required**.

### Mermaid Diagrams

```python
builder.mermaid("graph TD\n    A[Input] --> B{Process}\n    B --> C[Output]")
```

Requires `pip install "dynamic-pdf-builder[diagrams]"`. Falls back to a styled code block if unavailable.

### Callout

```python
builder.callout(
    text="Your API key has been rotated. Please update your config.",
    title="SECURITY NOTICE",
    variant="warning",     # info | warning | error | success | tip
)
```

### Quote

```python
builder.quote(
    text="The only way to do great work is to love what you do.",
    attribution="Steve Jobs",
)
```

### Metrics & Scores

```python
builder.metric_row([
    {"label": "Revenue", "value": "$2.35M", "delta": "+12%"},
    {"label": "Users",   "value": "14,200", "delta": "+8%"},
    {"label": "NPS",     "value": "72"},
])

builder.score_display(
    score=57, max_score=100,
    label="AI Maturity Score",
    sublabel="Defined",
    score_color="#00897B",
)

builder.progress_bar(
    title="Pillar Breakdown",
    items=[
        {"label": "Strategy",   "value": 20, "color": "#E53E3E",
         "benchmark": 42, "delta": "-22"},
        {"label": "Technology", "value": 75, "color": "#38A169",
         "benchmark": 48, "delta": "+27"},
    ],
)
```

### Badge & Legend

```python
builder.badge("Defined", bg_color="#ECC94B", color="#1A1A2E")

builder.legend(
    title="Maturity Levels",
    items=[
        {"label": "Low",    "color": "#E53E3E", "description": "0–39"},
        {"label": "Medium", "color": "#ECC94B", "description": "40–69"},
        {"label": "High",   "color": "#38A169", "description": "70–100"},
    ],
    layout="horizontal",    # horizontal | vertical
)
```

### Academic Blocks

```python
# Structured abstract (IMRAD format)
builder.abstract(
    fields=[
        {"label": "Background", "text": "This study examines..."},
        {"label": "Methods",    "text": "We analyzed 500 samples..."},
        {"label": "Results",    "text": "Accuracy improved by 18%..."},
        {"label": "Conclusion", "text": "The proposed method outperforms..."},
    ],
    keywords=["machine learning", "NLP", "benchmarking"],
)

# Footnote
builder.footnote(marker="1", text="Source: World Bank Open Data, 2025.")

# Inline citation reference [1]
builder.citation(key="1", style="numeric")

# Reference list
builder.bibliography(
    style="apa",            # apa | ieee | chicago
    entries=[
        {"authors": "Smith, J.", "year": "2024",
         "title": "Deep Learning Survey",
         "source": "Journal of AI Research", "doi": "10.1234/jair.2024"},
    ],
)
```

### Signature

```python
builder.signature(
    name="Jane Smith",
    title="Chief Financial Officer",
    date="March 2026",
    show_line=True,          # print a horizontal line above the name
)
```

### Timeline

```python
builder.timeline([
    {"date": "Jan 2025", "title": "Project kickoff",
     "description": "Team assembled and scope defined."},
    {"date": "Mar 2025", "title": "Beta launch",
     "description": "1,000 early users.", "color": "#38A169"},
    {"date": "Jun 2025", "title": "General availability"},
])
```

### Shapes (Vector Graphics)

```python
# Filled rectangle with label
builder.shape("rect", width=300, height=40, fill_color="#3182CE",
              label="Status: Active", label_color="#fff")

# Rounded card
builder.shape("rounded_rect", width=250, height=80, fill_color="#F7FAFC",
              stroke_color="#CBD5E0", corner_radius=12)

# Circle
builder.shape("circle", width=60, height=60, fill_color="#E53E3E")

# Dashed ellipse
builder.shape("ellipse", stroke_color="#805AD5", stroke_dash=[6, 3])

# Arrow
builder.shape("arrow", width=200, stroke_color="#2D3748", stroke_width=2)

# Custom polygon (triangle)
builder.shape("polygon", width=100, height=100,
              points=[[50, 0], [100, 100], [0, 100]], fill_color="#ECC94B")

# Pie wedge
builder.shape("wedge", width=120, height=120,
              start_angle=0, end_angle=120, fill_color="#48BB78")
```

| `shape_type` | Description |
|--------------|-------------|
| `rect` | Rectangle |
| `rounded_rect` | Rectangle with rounded corners |
| `circle` | Circle |
| `ellipse` | Ellipse |
| `line` | Horizontal line |
| `arrow` | Horizontal arrow with filled head |
| `polygon` | Custom polygon from `points` list |
| `arc` | Arc segment |
| `wedge` | Filled pie wedge |

### QR Code

```python
builder.qrcode(
    data="https://example.com/report/2026-q1",
    size=100,                 # pts (width = height)
    caption="Scan to view online",
    alignment="center",
    error_correction="M",     # L | M | Q | H
)
```

Requires `pip install "dynamic-pdf-builder[qrcode]"`.

### Watermark

```python
builder.watermark(text="DRAFT", opacity=0.08, color="#cccccc")
builder.watermark(text="CONFIDENTIAL", opacity=0.12, color="#FF0000")
```

### Layout Utilities

```python
builder.divider(color="#CBD5E0", thickness=1.0)         # solid line
builder.divider(color="#CBD5E0", style="dashed")         # dashed line
builder.divider(color="#CBD5E0", style="dotted")         # dotted line
builder.spacer(height=20)                                # vertical gap
builder.page_break()                                     # force new page
```

### Multi-Column Layouts

```python
from dynamic_pdf.schema.blocks import (
    TwoColumnBlock, ThreeColumnBlock, SidebarBlock,
    HeadingBlock, ParagraphBlock, CalloutBlock,
)

# Two-column layout with custom ratio
builder.add_block(TwoColumnBlock(
    left=[HeadingBlock(text="Left Column", level=2),
          ParagraphBlock(text="Left body text.")],
    right=[ParagraphBlock(text="Right column content.")],
    ratio=0.4,              # left column Width fraction
))

# Three equal columns
builder.add_block(ThreeColumnBlock(columns=[
    [ParagraphBlock(text="Column 1.")],
    [ParagraphBlock(text="Column 2.")],
    [ParagraphBlock(text="Column 3.")],
]))

# Sidebar layout
builder.add_block(SidebarBlock(
    main_content=[ParagraphBlock(text="Main body text here...")],
    sidebar_content=[CalloutBlock(text="Key insight.", variant="tip")],
    sidebar_position="right",   # left | right
    sidebar_ratio=0.3,
))
```

---

## Section Numbering

Automatically number all headings in the document:

```python
# Enable via builder
builder.section_numbering(True)
builder.heading("Introduction")       # renders: "1  Introduction"
builder.heading("Background", level=2) # renders: "1.1  Background"
builder.heading("Methods")            # renders: "2  Methods"
builder.heading("Design", level=2)    # renders: "2.1  Design"
builder.heading("Implementation", level=3)  # "2.1.1  Implementation"

# Enable via CLI
dynamic-pdf render report.md --section-numbers
```

---

## Table of Contents (TOC)

The TOC auto-populates from all headings in the document. Place it **after** your headings for full population, or anywhere as a structural placeholder:

```python
builder.heading("Introduction")
builder.paragraph("...")
builder.heading("Methods", level=2)
builder.paragraph("...")
builder.heading("Results", level=2)
builder.paragraph("...")

# TOC auto-collects all headings defined before this call
builder.table_of_contents(depth=3)  # include H1–H3 only
# or use the alias:
builder.toc()
```

Combine with section numbering for numbered TOC entries:

```python
builder.section_numbering(True)
builder.heading("Introduction")
builder.heading("Methods")
builder.toc()  # renders: "1  Introduction", "2  Methods", ...
```

---

## Introduction Page

Add a styled preface or introduction page before the main content:

```python
builder.introduction_page(
    title="Executive Preface",
    subtitle="A note from the CEO",
    content="""
This report represents the culmination of a year's work across our global teams.

The insights contained within reflect both our achievements and the challenges ahead.
We remain committed to transparency and excellence in all we do.
    """,
    accent_color="#E53E3E",   # overrides theme accent for the page divider
)
```

The introduction page always ends with a page break.

---

## Cover Page

```python
builder.cover_page(
    title="Annual Report 2026",
    subtitle="Confidential — For Board Use Only",
    author="Finance Team",
    date="March 2026",
    logo="logo.png",            # optional logo above the title
    background_color="#0B1D3A", # optional full-page background
)
```

---

## Drop Cap

Automatically enlarges the first letter of the first paragraph after every heading. Arabic/RTL paragraphs are silently skipped.

```python
from dynamic_pdf.schema.theme import DecorationConfig

theme.decorations = DecorationConfig(
    drop_cap_enabled=True,
    drop_cap_lines=3,               # body lines the cap spans vertically
    drop_cap_font_size_ratio=3.2,   # cap_size = base_size × ratio
    drop_cap_color="#E53E3E",       # None → uses colors.drop_cap
)
```

**How it works:**
1. Every `heading()` sets an internal per-render flag.
2. The next LTR `paragraph()` consumes the flag and renders a `DropCapParagraph` flowable.
3. Any non-paragraph block (table, callout, list…) between heading and paragraph **clears the flag** — so it only fires when text directly follows a heading.
4. The flag is stored in a **thread-safe `RenderContext`** — concurrent renders never leak state.

Enabled by default in `claude` and `corporate_dark` themes.

---

## Arabic & RTL Support

Arabic (and Hebrew) text is detected automatically:

```python
# Arabic paragraph — detected, rendered RTL with Amiri, drop cap skipped
builder.paragraph(
    "يُعدّ الذكاء الاصطناعي من أبرز التحولات التقنية في القرن الحادي والعشرين."
)

# Mixed content — heading detected as RTL, aligned right
builder.heading("التقرير السنوي — Annual Report")

# English follows — LTR, drop cap fires normally
builder.heading("Executive Summary")
builder.paragraph("Artificial intelligence is reshaping every industry.")
```

### How it works

| Step | Detail |
|------|--------|
| Detection | Unicode bidi scan — RTL if >30% of alphabetic characters are Arabic/Hebrew |
| Reshaping | `arabic-reshaper` joins isolated letter forms into proper connected glyphs |
| Visual order | `python-bidi` applies the Unicode BiDi algorithm |
| Font | `Amiri` (auto-downloaded to `dynamic_pdf/fonts/bundled/` on first run) |
| Alignment | RTL paragraphs are right-aligned automatically |
| Tables | Column order is reversed; markers appear on the right |
| Callouts | Left accent bar moves to the right side |

```bash
pip install "dynamic-pdf-builder[rtl]"
# or: pip install arabic-reshaper python-bidi
```

---

## PDF Encryption

Password-protect PDFs with AES-256 (requires `pikepdf`):

```python
(DocumentBuilder(theme="claude")
    .meta(title="Confidential")
    .encrypt(owner_password="owner_secret", user_password="user_pass")
    .heading("Confidential Report")
    .paragraph("This document is protected.")
    .render("secure.pdf"))
```

```bash
pip install "dynamic-pdf-builder[pdf]"
```

If `pikepdf` is not installed, a warning is issued and an unencrypted PDF is saved.

---

## Custom Fonts

```python
from dynamic_pdf import register_custom_font, list_available_fonts

# Register a TTF font
register_custom_font("MyBrand", "/path/to/MyBrand-Regular.ttf")
register_custom_font("MyBrand-Bold", "/path/to/MyBrand-Bold.ttf")

# Use in a theme
theme.typography.heading_family = "MyBrand"
theme.typography.body_family = "MyBrand"

# List all registered fonts
print(list_available_fonts())
```

Built-in fonts auto-downloaded on first run:
- **JetBrains Mono** — code blocks
- **Amiri** — Arabic / RTL text

Fallback to `Helvetica` / `Courier` if download fails.

---

## Typography Standards

### Comparison by Major Style Guide

| Element | APA 7 | MLA 9 | Chicago (CMS) | Dynamic PDF Default |
|---------|-------|-------|---------------|---------------------|
| Font | Arial/Calibri 11 pt | TNR 12 pt | TNR 12 pt | Inter 11 pt |
| Line Spacing | 2.0× | 2.0× | 2.0× | 1.5× (configurable) |
| Margins | 1 inch all sides | 1 inch all sides | 1 inch all sides | 1 inch all sides |
| First-Line Indent | 0.5 inch | 0.5 inch | 0.5 inch | 0.5 inch |
| Citations | Author-Date | Works Cited | Bibliography | `.bibliography(style=...)` |

### Style Guide Presets

```python
from dynamic_pdf.themes import get_theme, register_theme
from dynamic_pdf.schema.theme import Typography, HeaderFooterConfig, DecorationConfig

# ── APA 7 ──
theme = get_theme("academic")
theme.name = "apa7"
theme.typography.base_size = 12.0
theme.typography.line_height = 2.0
theme.header_footer = HeaderFooterConfig(
    enabled=True, header_style="minimal", footer_style="page_only",
    show_page_number=True, page_number_format="{n}",
)
theme.decorations = DecorationConfig(
    heading_accent_bar=False, drop_cap_enabled=False, table_row_alternating=False,
)
register_theme(theme)

# ── IEEE ──
theme = get_theme("academic")
theme.name = "ieee"
theme.typography.base_size = 10.0
theme.typography.line_height = 1.0     # single-spaced
theme.spacing.first_line_indent = 0.0  # IEEE uses block paragraphs
register_theme(theme)
```

### Default Typographic Settings

| Setting | Value | Standard |
|---------|-------|----------|
| Body font size | 11 pt | APA 7 |
| H1 heading | 16 pt (×1.45) | |
| H2 heading | 14 pt (×1.27) | |
| H3 heading | 13 pt (×1.18) | |
| Caption / Footnote | 8 pt (×0.73) | |
| Code block | 9 pt | |
| Line height | 1.5× | |
| First-line indent | 36 pt (0.5 in) | APA / MLA |
| Page margins | 72 pt (1 in) all sides | Universal |
| Color contrast | ≥ 4.5:1 body | WCAG 2.2 AA |

---

## Project Structure

```
dynamic_pdf/
├── __init__.py             # Public API, __version__, __all__
├── builder.py              # DocumentBuilder fluent API + standalone helpers
├── cli.py                  # dynamic-pdf CLI entry point
├── streaming.py            # Context manager for LLM streaming output
├── utils/
│   └── errors.py           # DynamicPDFError hierarchy
├── schema/
│   ├── blocks.py           # 40+ block types (Pydantic v2 discriminated union)
│   ├── theme.py            # Theme, ColorPalette, Typography, SpacingScale, etc.
│   ├── document.py         # Document + Meta + RenderResult models
│   └── enums.py            # PageSize (case-insensitive), Orientation enums
├── themes/
│   ├── claude.py           #  Warm terracotta
│   ├── chatgpt.py          #  Green + clean
│   ├── corporate_dark.py   #  Dark navy
│   ├── academic.py         #  Serif / APA-ready
│   ├── modern_minimal.py   #  Light grey minimal
│   ├── data_report.py      #  Dashboard-style
│   ├── government.py       #  Formal / high-contrast
│   └── registry.py         #  register_theme(), get_theme(), list_themes()
├── layout/
│   ├── engine.py           #  LayoutEngine — orchestrates ReportLab doc build
│   ├── factory.py          #  Block → ReportLab Flowable; RenderContext
│   ├── page_template.py    #  Header/footer drawing (15+ styles)
│   └── toc.py              #  Table of contents
├── renderers/
│   ├── chart.py            #  17 chart types → SVG via matplotlib
│   ├── diagram.py          #  5 diagram types
│   ├── callout.py
│   ├── code_block.py
│   ├── math.py
│   ├── mermaid.py
│   ├── metric.py
│   └── dividers.py
├── fonts/
│   ├── manager.py          #  Thread-safe download, register, fallback
│   └── bundled/            #  JetBrains Mono + Amiri (auto-downloaded)
├── markdown/
│   ├── parser.py           #  CommonMark + GFM → Block tree
│   └── preprocessors.py    #  Math/Mermaid fence extraction
└── rtl/
    └── processor.py        #  Arabic BiDi reshaping

tests/
└── test_basic.py           #  ~120 test cases, 30 classes, 100% passing
```

---

## Dependencies

### Core (always installed)

| Package | Purpose |
|---------|---------|
| `reportlab ≥ 4.0` | PDF rendering engine (Platypus layout system) |
| `pydantic ≥ 2.0` | Schema validation + JSON serialization |
| `markdown-it-py ≥ 3.0` | CommonMark + GFM Markdown parser |
| `pygments ≥ 2.17` | Code syntax highlighting (500+ languages) |
| `matplotlib ≥ 3.8` | Charts (17 types) + LaTeX math rendering |
| `Pillow ≥ 10.0` | Image processing |
| `svglib ≥ 1.5` | SVG → ReportLab Drawing conversion |
| `latex2mathml ≥ 3.76` | LaTeX → MathML conversion |
| `pyphen ≥ 0.14` | Text hyphenation |

### Optional

| Extra | Package | Feature |
|-------|---------|---------|
| `rtl` | `arabic-reshaper`, `python-bidi` | Arabic / Hebrew RTL rendering |
| `diagrams` | `playwright ≥ 1.40` | Mermaid diagram rendering |
| `plotly` | `plotly ≥ 5.0`, `kaleido ≥ 0.2` | Plotly interactive chart export |
| `pdf` | `pikepdf ≥ 8.0` | PDF merge, AES-256 encryption |
| `qrcode` | `qrcode[pil] ≥ 7.4` | QR code block generation |

---

## Testing

```bash
# Run all tests
py -m pytest tests/test_basic.py -v

# Run a specific class
py -m pytest tests/test_basic.py::TestBlockTypes -v

# Run with short traceback
py -m pytest tests/test_basic.py --tb=short
```

The test suite covers:

| Class | What's tested |
|-------|---------------|
| `TestPackage` | Version, public exports |
| `TestBuilderCore` | All render modes, chaining, file/bytes/base64 output |
| `TestMeta` | Page size (case-insensitive), orientation, section numbering, encryption flag |
| `TestTextBlocks` | All heading levels, paragraph, rich_text, note |
| `TestListBlocks` | Bullet, numbered, checklist, definition list |
| `TestTableBlock` | All table options, empty rows |
| `TestCodeBlock` | Languages, filename/caption, line numbers, highlight lines |
| `TestCalloutsQuotes` | All 5 callout variants, quote with/without attribution |
| `TestMetrics` | Metric rows, scores, progress bars, legends, badges |
| `TestAcademicBlocks` | Abstract, footnote, citation, bibliography (3 styles), signature |
| `TestLayout` | All divider styles, spacer, page break, cover page, watermark, TOC, intro page |
| `TestShapes` | All 8 shape types |
| `TestTimeline` | Basic + full with descriptions & colors |
| `TestCharts` | Bar, line, pie + label options |
| `TestThemes` | All 7 built-in themes, custom theme, invalid theme |
| `TestHeaderFooterStyles` | Every header style + every footer style (parametrized) |
| `TestMarkdown` | All parsed block types, inline formatting, full document |
| `TestJsonAPI` | Basic, with meta, multiple block types |
| `TestStandaloneHelpers` | render_to_bytes, render_to_base64, render shortcut |
| `TestStreaming` | Context manager stream |
| `TestInlineMarkdown` | Every inline syntax token |
| `TestRTL` | Arabic detection, paragraph & heading render |
| `TestSectionNumbering` | Counter logic, reset, full render |
| `TestTableOfContents` | Entry collection, depth filtering |
| `TestDropCap` | Enabled, RTL skip |
| `TestRenderContext` | Thread isolation, independent state |
| `TestExceptions` | Exception hierarchy, attributes |
| `TestFonts` | Available list, thread-safe registration |
| `TestEdgeCases` | Long paragraphs, Unicode, empty/huge tables, full mixed-content doc |
| `TestEnums` | Case-insensitive page sizes, invalid value |

---

## Changelog

### v0.3.0 (2026-04-04)

**New Features**
- `introduction_page()` — styled preface/introduction page block
- `section_numbering()` — automatic heading numbering (1, 1.1, 1.1.2, …)
- `table_of_contents()` / `toc()` — auto-populated from document headings
- `encrypt()` — AES-256 PDF password protection via `pikepdf`
- `register_custom_font()` / `list_available_fonts()` — public font management API
- `dynamic-pdf` CLI — render Markdown/JSON from the terminal
- Code block `line_numbers` and `highlight_lines` now fully implemented
- `divider(style=)` — `solid` / `dashed` / `dotted` fully threaded through builder

**Bug Fixes**
- **Global mutable state** — `_ParagraphContext` singleton replaced with per-render `RenderContext` (thread-safe concurrent renders)
- **Hardcoded `460px` width** — all renderers (metrics, columns, sidebar, images) now use actual frame width computed from page size and margins
- **Letter / Legal page sizes** — `PageSize` enum now case-insensitive (`"letter"`, `"LETTER"`, `"Letter"` all work)

**Improvements**
- Font manager is now thread-safe (uses `threading.Lock`)
- Engine computes actual frame width and passes it to factory via `RenderContext`
- PDF encryption post-processing via `pikepdf` with AES-256
- Custom exception hierarchy: `DynamicPDFError`, `ThemeError`, `FontError`, `BlockRenderError`, `ValidationError`
- `render()` returns `bytes` when called with no arguments
- 120+ test cases, 30 test classes, 100% pass rate

### v0.2.0

- Initial public release with 39 block types, 7 themes, RTL support, drop cap

---

## License

MIT
