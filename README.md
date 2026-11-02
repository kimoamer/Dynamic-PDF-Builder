# Dynamic PDF Builder

> Generate beautiful, professional PDF reports from **Markdown**, **JSON**, or a **fluent Python API** — pure Python, no system dependencies required.

[![Version](https://img.shields.io/badge/version-0.3.0-blue.svg)](https://pypi.org/project/dynamic-pdf-builder/)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![CI](https://github.com/kimoamer/Dynamic-PDF-Builder/actions/workflows/ci.yml/badge.svg)](https://github.com/kimoamer/Dynamic-PDF-Builder/actions/workflows/ci.yml)
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

The TOC lists **every** heading in the document (before or after it) with its final page number, and each entry is a clickable link. Headings are also exported as PDF bookmarks (outline). Place it wherever it belongs — typically right after the cover:

```python
builder.table_of_contents(depth=3)  # include H1–H3 only
builder.heading("Introduction")
builder.paragraph("...")
builder.heading("Methods", level=2)
builder.paragraph("...")
builder.heading("Results", level=2)
builder.paragraph("...")
# builder.toc() is an alias of table_of_contents()
```

Combine with section numbering for numbered TOC entries:

```python
builder.section_numbering(True)
builder.toc()  # renders: "1  Introduction ..... 2", "2  Methods ..... 3"
builder.heading("Introduction")
builder.heading("Methods")
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

If `pikepdf` is not installed (or no password is given), `EncryptionError` is raised and **no file is written** — encryption never silently degrades.

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
│   ├── manager.py          #  Thread-safe register + deterministic fallback (no network)
│   └── bundled/            #  JetBrains Mono + Amiri (shipped, OFL licences in LICENSES/)
├── markdown/
│   ├── parser.py           #  CommonMark + GFM → Block tree
│   └── preprocessors.py    #  Math/Mermaid fence extraction
└── rtl/
    └── processor.py        #  Arabic BiDi reshaping

tests/                      #  pytest suite run by GitHub Actions (see Testing)
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
pip install -e ".[dev]"
python -m pytest -q
```

CI (`.github/workflows/ci.yml`) runs the suite on Python 3.9–3.13 for every push
and pull request; the CI badge above reflects the actual latest result. Tests
inspect the generated PDFs (text, outline, links, page totals via PyMuPDF), not
just that a file was produced:

| File | What's verified |
|------|-----------------|
| `test_pagination.py` | `Page n of N` totals on 1/2/10+ page docs, linked TOC with final page numbers, heading keep-with-next, PDF outline |
| `test_markdown_nested.py` | Nested/mixed lists, start numbers, task lists, footnotes, callouts, indented code, front matter, inline-markup escaping |
| `test_encryption.py` | Fail-closed encryption (missing pikepdf / missing password), AES-256 positive case |
| `test_error_policy.py` | Strict vs permissive error semantics, diagnostics, resource limits |
| `test_safe_assets.py` | No network by default, host allowlist, private-IP/scheme blocking, base_dir confinement, size/pixel caps |
| `test_mermaid_security.py` | Diagram passed as data, no CDN, network aborted, fallback warning, size limit |
| `test_regression_blocks.py` | Every fluent block × every theme in strict mode, all header/footer styles, v0.3 helpers |
| `test_cli.py` | CLI exit codes, no output on strict failure |
| `test_ast_contract.py` | Markdown → semantic AST is lossless, typed inline runs, IDs, provenance |
| `test_profiles.py` | Deterministic profile selection on the fixture corpus, recipes, brand kits |
| `test_docx_semantics.py` | Word styles, numbering restarts, tables, fields, TOC, links, alt text, export API/CLI |
| `test_docx_rtl.py` | Arabic bidi paragraphs/runs, complex-script fonts, bilingual tables |
| `test_adaptive_layout.py` | Landscape for wide tables (PDF + DOCX), column widths, min type size, numeric alignment, lead, cover, no stranded headings, word preservation |
| `test_visual_qa.py` | QA on every fixture, synthetic defect detection, auto-fix loop, glyph coverage, DOCX integrity, golden fingerprints |
| `test_pdf_docx_parity.py` | Same words and heading structure in AST, PDF and DOCX; LibreOffice conversion |

## Editable Word (DOCX) export & intelligent design

PDF and DOCX are produced from the **same semantic document** (`builder.semantic()`)
and the same design tokens, so content and structure match across formats.

```python
from dynamic_pdf import DocumentBuilder, BrandKit  # BrandKit: dynamic_pdf.design.BrandKit

b = (DocumentBuilder.from_markdown(md)
     .design("auto", brand={"name": "Acme", "primary": "#0B5FFF", "logo": "logo.png"})
     .quality("strict"))
b.design_explain()        # {'profile': 'executive_report', 'reasons': [...], ...}
b.export("report.docx")   # editable Word
b.export("report.pdf")
res = b.export_both("./out")   # res.pdf_path, res.docx_path, res.profile, res.diagnostics
```

```bash
dynamic-pdf render report.md -o report.docx --design auto
dynamic-pdf render report.md --format both
```

The DOCX uses real Word structures: named styles (Normal, Body Text, Title, Heading 1–6,
Caption, Quote, Code, TOC n), multi-level list numbering that restarts per list, tables with
repeating header rows and right-aligned numeric columns, hyperlinks and bookmarks, a TOC
field (refreshed when Word opens the file), header/footer with `PAGE`/`NUMPAGES` fields,
core properties, Arabic bidi paragraphs/runs with complex-script fonts, and per-table
column order for bilingual documents. Charts, diagrams, math and QR codes are embedded as
images with alt text (Word has no native equivalent). Known differences: page breaks are
computed by Word, so page counts can differ from the PDF; footnotes are rendered as notes
paragraphs; text watermarks use VML (shown by Word, not by every viewer).

`design("auto")` selects a profile deterministically from metadata and content signals
(`executive_report`, `proposal`, `corporate_memo`, `academic_report`, `technical_manual`,
`data_report`, `financial_report`, `letter`, `invoice`, `general`) and applies its recipe —
type ramp, measure, rhythm, numbering, header/footer and navigation. Content is never altered.

The layout planner then measures the content with real font metrics and records every
decision in `design_explain()["layout"]`: content-measured table column widths, tighter
padding and smaller (never below 7.5 pt) type for dense tables, right-aligned numeric
columns, landscape pages/sections for tables that cannot be read in portrait, short tables
and captions kept on one page, comfortable line length for prose, heading ramps tuned to
outline depth, a lead paragraph for reports and proposals, and a metadata-only cover for long
titled reports. Headings are kept with their content and widows/orphans are suppressed.

## Visual quality assurance

`export(..., qa=True)` (or `builder.qa("pdf"|"docx")`, CLI `--qa`) renders the document,
inspects every page and fixes measurable layout defects with bounded retries (3 attempts):

| Check | Source | Automatic fix |
|-------|--------|---------------|
| Text/images clipped off the page, overflow into margins | PDF geometry (PyMuPDF); DOCX via LibreOffice | landscape page / smaller type for the table (≥ 7.5 pt), smaller code type, image rescale |
| Overlapping text lines | same | — (reported) |
| Heading stranded at a page bottom | PDF outline + geometry | page break moved before the heading |
| Accidental blank pages | PDF | redundant page breaks collapsed |
| Missing glyphs | font coverage of every character | bundled fallback face for symbols; otherwise reported |
| Broken links, numbering, bookmarks, tables, XML, alt text | PDF links; DOCX package/XML | — (reported) |

Strict mode raises `QualityError` if errors remain; permissive mode returns the report.
`python -m dynamic_pdf.qa.golden tests/fixtures tests/golden [--update] [--sheets]` verifies
structural fingerprints of the fixture corpus and writes page contact sheets for review; CI
uploads them as the `page-contact-sheets` artifact. QA needs `pip install "dynamic-pdf-builder[qa]"`
(PyMuPDF, AGPL) and LibreOffice for DOCX visual checks.

## Error handling, security & limits

Rendering is **strict by default**: a block, asset or encryption failure raises a
typed `DynamicPDFError` subclass (`BlockRenderError`, `AssetError`,
`EncryptionError`, `ResourceLimitError`) and **no output file is written**.

```python
from dynamic_pdf import DocumentBuilder, RenderPolicy, AssetPolicy

b = DocumentBuilder.from_markdown(md).quality("permissive")   # visible markers instead of raising
b.render("out.pdf")
b.diagnostics            # [{'level': 'error', 'code': 'block_render_failed', ...}]
b.last_render.diagnostics.status   # "ok" | "degraded"

# Images/logos: local files and data: URIs by default, no network.
b.asset_policy(allow_remote=True, allowed_hosts=("cdn.example.com",), max_bytes=5_000_000)
b.asset_policy(base_dir="/srv/assets")       # confine local paths
```

- **Encryption fails closed**: if `pikepdf` is missing or no password is set, `EncryptionError` is raised and nothing is written.
- **Untrusted input**: inline text is escaped before ReportLab markup is applied (no `<img>`/`<a>` injection, links limited to http(s)/mailto/#anchors); remote fetches are limited to public IPs, re-validated on redirect, time- and size-bounded.
- **Mermaid** renders offline only: set `DYNAMIC_PDF_MERMAID_JS=/path/to/mermaid.min.js`; the diagram is passed as data (never HTML), all page network requests are aborted. Without Playwright or the bundle the source is shown as code and a `mermaid_fallback` warning is recorded.
- **Limits** (`ResourceLimits`): input characters, block count, table cells, Mermaid source size, renderer timeout.
- **Fonts** are never downloaded during rendering.

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
