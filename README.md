# Dynamic PDF Builder

> Generate beautiful, professional PDF reports from **Markdown**, **JSON**, or a **fluent Python API** — pure Python, no system dependencies required.

[![Version](https://img.shields.io/badge/version-0.3.0-blue.svg)](https://pypi.org/project/dynamic-pdf-builder/)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![CI](https://github.com/kimoamer/Dynamic-PDF-Builder/actions/workflows/ci.yml/badge.svg)](https://github.com/kimoamer/Dynamic-PDF-Builder/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

---

## Table of Contents

- [Installation](#installation)
- [Quick Start](#quick-start)
- [Input Modes](#input-modes)
- [CLI Usage](#cli-usage)
- [Using with AI agents](#using-with-ai-agents)
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
pip install dynamic-pdf-builder        # from PyPI, once a release is published
pip install -e .                        # from a clone of this repository
```

Python 3.10 or newer. Core dependencies install automatically, including the fonts (45 families
under the SIL Open Font License) and a PDF reader (PDFium) that design variants and QA use to
check the rendered pages. No system fonts, browser or LibreOffice are needed for PDF and DOCX.
Optional feature sets:

```bash
pip install "dynamic-pdf-builder[diagrams]"   # Mermaid diagrams via Playwright
pip install "dynamic-pdf-builder[plotly]"     # Plotly charts
pip install "dynamic-pdf-builder[pdf]"        # PDF merge / encrypt via pikepdf
pip install "dynamic-pdf-builder[qrcode]"     # QR code blocks
pip install "dynamic-pdf-builder[xlsx]"       # XLSX data sources, workbook export, editable Word chart data
pip install "dynamic-pdf-builder[qa]"         # PyMuPDF for QA (AGPL): faster and used when installed
pip install "dynamic-pdf-builder[ai]"         # optional AI layer (needs an API key, only when asked)
pip install "dynamic-pdf-builder[mcp]"        # MCP server for agents
pip install "dynamic-pdf-builder[all]"        # every extra above except qa (AGPL), ai and mcp
pip install -e ".[dev]"                       # from a clone: testing and linting tools
```

The code is MIT; the bundled fonts are OFL-1.1 (`License-Expression: MIT AND OFL-1.1`), with each
font's licence shipped in the package.

---

Settings, environment variables and what the library does (and does not do) inside a host
application are in [docs/CONFIGURATION.md](docs/CONFIGURATION.md).

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

# What a reader would notice, each with what to change; page images in pages/
dynamic-pdf review report.md -o pages/

# List all available themes
dynamic-pdf themes

# Show version
dynamic-pdf version
```

---

## Using with AI agents

The library explains itself, so an agent needs no outside notes:

- **The guide ships with the package**: `dynamic_pdf.guide()` returns it, `dynamic_pdf.guide("tables")`
  one topic, and `dynamic-pdf guide [topic]` prints it. It covers the Markdown the library reads, with
  an example for every feature, the output formats, the Python API, Arabic, and what it cannot do.
- **MCP server** (`pip install "dynamic-pdf-builder[mcp]"`):

  ```bash
  python -m dynamic_pdf.ai.mcp_server --out-dir ./out
  ```

  It tells the agent what the library is and how to work with it when it connects. Tools: `guide`,
  `render` (.pdf, .docx or .xlsx), `review`, `variants`, `explain`, `lint` and `schema`. Each document
  tool takes the document as `markdown` (a string, the easiest) or as `document` (JSON); files are
  written only inside the output folder, remote images stay off, and an invalid document is refused
  with each failing field and how to fix it.
- **The JSON Schema describes its fields** (`dynamic-pdf schema`, or the `schema` tool), for agents
  that send JSON.
- **`llms.txt`** at the repository root points to all of the above.

The loop that works: write Markdown, `render`, `review` (each issue with its page and the fix, and
one image a page), fix, `review` again.

## Themes

Every document is designed by default and the design starts from the theme you choose. For a theme's
classic look exactly as below, call `design(None)` before rendering.

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

In the PDF the formula is drawn with `matplotlib.mathtext` — **no LaTeX installation required**.
In the DOCX it is a native Word equation (Office Math), so it can be edited in Word and is read
by screen readers; a formula Office Math cannot hold falls back to the picture.

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

#### Citations from BibTeX

Cite works in the text as Pandoc does and give the library as BibTeX; the reference list is built
from what is cited:

```markdown
---
bibliography: refs.bib        # or several: [refs.bib, more.bib]
citation-style: ieee          # apa (author and year, the default) or ieee (numbers)
---
Relocation works when communities move together [@abara2023, p. 50].
Markets respond to floods [@kim2021; @lund2022].

# References

[REFERENCES]
```

APA writes "(Abara & Halvorsen, 2023, p. 50)" and "(Kim et al., 2021; Lund, 2022)" and lists by
author; IEEE writes "[1, p. 50]" and "[2], [3]" and lists in order of first citation. Only works cited
are listed, where `[REFERENCES]` stands or else at the end. In Python: `builder.bibtex("refs.bib",
style="apa")` (a path, read under the asset policy as images are, or BibTeX text). A key the library
does not have stays as written and `lint()` reports it (`unresolved_citation`).

#### Numbered equations

A displayed equation with an id is numbered, as captioned tables and figures are, and `{ref:id}`
reads "Equation (2)" (المعادلة (2) in Arabic). The number sits at the far edge in the PDF and in Word.

```markdown
The energy follows {ref:eq-energy}.

$$ E = mc^2 $$ {#eq-energy}
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

### Compositions

Three blocks draw a whole composition, with live text in both the PDF and the Word file. With
`design_variants(grammar=True)` the engine uses them by itself where a document already has the
structure: a photograph followed by short text, a run of charts of one kind, or paragraphs paired
in two languages.

```python
# A picture with a text panel beside it, or laid over it with layout="overlay"
builder.image_text_panel({"src": "quay.jpg", "alt_text": "The quay", "caption": "North quay"},
                         ["The north quay reopened in March."],
                         title="A quay rebuilt", layout="split", side="start", tone="dark")

# Equal cells of charts or figures; cells run from the right in Arabic
builder.figure_matrix([{"title": "Tram", "chart": {"chart_type": "bar", "data": {"2024": 44, "2025": 52}}},
                       {"title": "Satisfaction", "value": "92%", "label": "of riders"}],
                      title="The year in figures", columns=2)

# Two languages, row by row; Arabic takes the right column
builder.paired_row_columns([{"first": "Water", "second": "المياه", "heading": True},
                            {"first": "English text", "second": "النص العربي"}],
                           header_first="English", header_second="العربية")
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
| Font | `Amiri` by default, or any bundled Arabic family (shipped with the package) |
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

Fonts are shipped with the package and never downloaded. **JetBrains Mono** sets code and
**Amiri** is the default Arabic face; the bundled families are listed below. A family that is
not available falls back to `Helvetica` / `Courier`, and `design_explain()` says so.

---

### Bundled families

The package carries 23 Arabic and 22 Latin families, all under the SIL Open Font License, so a
design looks the same on a machine with none of them installed. Word files embed the family
they use. Licences sit in `dynamic_pdf/fonts/bundled/LICENSES/`, and `catalog.json` records the
source of each family and whether it was changed.

```python
from dynamic_pdf.fonts import list_font_families

list_font_families("arabic")     # Cairo, Tajawal, Noto Naskh Arabic, El Messiri, ...
list_font_families("latin")      # Open Sans, Montserrat, EB Garamond, Barlow, ...

builder.fonts(heading="Montserrat", body="Spectral", arabic="Markazi Text")
```

Bundled families load when first used. An unchanged document keeps its current fonts.

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
│   └── bundled/            #  45 families, OFL licences in LICENSES/, sources in catalog.json
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
| `latex2mathml ≥ 3.76` | LaTeX → MathML, for native Word equations |
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

CI (`.github/workflows/ci.yml`) runs the suite on Python 3.10–3.13 for every push
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
| `test_m5_quality.py` | Regression tests for confirmed layout/typography/QA defects (whitespace, kept groups, RTL/bilingual, QA states, defaults) |
| `test_stress_documents.py` | 20–50 page Arabic report, bilingual report, proposal, multi-page financial tables, academic paper, manual: page QA + word preservation in PDF and DOCX |
| `test_m6_composer.py` | Geometry capture, simulation accuracy, hard constraints, selection, budgets, determinism, thread isolation, no network, hints, API/CLI, ranker fallback |
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
column order for bilingual documents. Equations are native Word equations (Office Math).
Numbered captions ("Table 2", "Figure 3") hold their number in a `SEQ` field, references to them
(`{ref:id}`) are `REF` fields, and lists of tables and figures are `TOC \c` fields, so inserting a
table in Word and updating fields (F9) renumbers captions, references and lists together.
Bar, column, grouped and stacked bar, line, area, pie and doughnut charts are native Word
charts in the library's colours: their data and formatting can be edited in Word, and with the
`xlsx` extra (openpyxl) a workbook is embedded so Word's "Edit Data" opens it. Other chart types,
diagrams and QR codes are embedded as images with alt text. Known differences: page breaks are
computed by Word, so page counts can differ from the PDF; text watermarks use VML (shown by
Word, not by every viewer); LibreOffice shows equations only with its Math module installed.
Footnotes are real Word footnotes.

Every output applies intelligent design by default: `export()`, `export_both()`, `render()`,
`render_bytes()`, `render_from_json()` and the CLI (opt out with `design(None)` or `--design none`
for the classic theme look); an explicitly chosen theme becomes the design's base.

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

### Computed tables, amounts in words and workbooks

A table cell that starts with `=` is a formula, written as in a spreadsheet. Cells are named as a
spreadsheet names them (columns A, B, C ... and rows from 1, the header row), so a formula means
the same in the document, in Word and in an exported workbook:

```markdown
| Item  | Qty | Price        | Amount             |
|-------|-----|--------------|--------------------|
| Paper | 3   | SAR 12.50    | =B2*C2             |
| Toner | 2   | SAR 1,310.00 | =B3*C3             |
| VAT   |     | 15%          | =SUM(D2:D3)*C4     |
| Total |     |              | =SUM(ABOVE)        |
| In words |  |              | =WORDS(D5)         |
```

Functions: `SUM`, `AVERAGE`, `MIN`, `MAX`, `COUNT`, `ROUND`, `ABS`, and Word's `ABOVE` and `LEFT`
(the numbers above in the column, or to the left in the row). `15%` is 0.15. Arithmetic is decimal,
so 0.1 + 0.2 is 0.3, and `ROUND` rounds half away from zero. A result is written as its column
writes numbers: decimals, thousands separators, currency, percent sign, negatives in parentheses
and Arabic-Indic digits. The document keeps the formulas; the PDF and the DOCX show the results.
A formula that cannot be computed raises a `FormulaError` naming the table, the cell and why (in
permissive mode the cell reads `#ERROR`), and `lint()` reports it in either mode.

`WORDS(D5)` writes the amount in words, in the document's language: "فقط ثلاثة آلاف وستة وخمسون
ريالاً وثلاث عشرة هللةً لا غير", or "Three thousand fifty-six riyals and thirteen halalas only". It
takes the currency of the cells it reads, or a code: `=WORDS(D5, "EGP")`, `=WORDS(D5, "en", "USD")`.
Arabic counts the noun as invoices do (ريالان، ثلاثة ريالات، أحد عشر ريالاً، مئتا ريال، ألفا ريال).
Currencies: SAR, EGP, AED, KWD, QAR, OMR, BHD, JOD, USD, EUR, GBP (English). The same words are
`dynamic_pdf.core.words.amount_in_words(1250.5, "ar", "SAR")` and the template filter
`{{ total | words("SAR") }}`.

Text can quote a cell of a table that has an id, so a figure in the prose cannot drift from its
table: "The total due is `{=invoice!D5}`" shows what D5 shows (Markdown gives the id with
`Table: Invoice lines {#invoice}` under the table). An unknown table or cell stays as written and
`lint()` reports it.

`export("tables.xlsx")` (or `render_xlsx()`, CLI `render -o tables.xlsx`) writes every table as a
sheet of a workbook, with the `xlsx` extra: numbers as numbers in the formats the document uses,
and formulas as working spreadsheet formulas (`ABOVE` becomes the range it covers; `WORDS`, which
no spreadsheet has, its text). Sheets read right to left in an Arabic document.

### Comparing two versions

`new.compared_with(old)` returns this document with every difference from the earlier one marked
as a suggested edit; export it to DOCX for tracked changes to accept or reject, or to PDF for a
review copy. Changed words in paragraphs, headings, quotes and list items, changed table cells and
added or removed rows, and added or removed blocks are marked; formulas are compared by what they
show. CLI: `dynamic-pdf compare old.md new.md -o changes.docx [--reviewer Finance]`.

### Suggested edits and comments

Text can carry suggested edits and comments in [CriticMarkup](https://github.com/CriticMarkup/CriticMarkup-toolkit),
the plain-text form people and language models use for suggestions:

```markdown
---
reviewer: Policy AI
---
Revenue {~~fell~>rose~~} by 12%{>>source: Q3 ledger<<}. The board {--may--} {++will++} approve
the {==capital budget==}{>>confirm with finance<<} in December.
```

| Markup | Word | PDF (a review copy) |
| --- | --- | --- |
| `{++added++}` | tracked insertion | underlined in green |
| `{--removed--}` | tracked deletion | struck through in red |
| `{~~old~>new~~}` | deletion then insertion | both |
| `{==text==}{>>comment<<}` | comment on the text | text highlighted, comment after it in small type |
| `{>>comment<<}` | comment on the word before it | comment after the word |

In Word each change can be accepted or rejected, and changes and comments carry the
`reviewer` (front matter, or `meta(reviewer=...)`; "Reviewer" when none is named). Text
without markup is written as before. A suggestion is parsed on its own, so emphasis should
open and close inside it.

## Intelligent page composition (CPU-only)

`compose("smart")` adds a deterministic layout optimizer on top of `design()`. It needs
no AI service, model, GPU or network:

```python
result = (DocumentBuilder.from_markdown(content)
          .design("auto")
          .compose(mode="smart")            # optional; "off" = single classic render
          .export_both(directory="output", qa=True))
result.composition["strategy"]               # e.g. "balanced"
```

```bash
dynamic-pdf render report.md --format both --compose smart --report composition.json
```

How it works (bounded — no nested loops):

1. **Analyze once** — every block is measured with real font metrics at the frame width;
   pagination is *simulated* (keep-with-next groups, split points, landscape runs).
2. **Choose ≤ 4 candidates** from structure and purpose — `balanced`, `compact`,
   `editorial`, `data` — each a bounded change of rhythm, measure, break policy, list
   columns or figure scaling. Content and reading order are never changed.
3. **Prune before rendering** — hard constraints (readable type, table text ≥ 7.5 pt,
   predicted stranded headings / detached captions / lost or reordered content).
4. **Render ≤ 3** (baseline + 2 best predicted) and record the region every flowable
   actually occupies; **score** utilization, whitespace balance, pagination efficiency,
   readability, typography, figure/table placement and accidental waste. Layout-added
   breaks never count as intentional whitespace; adding pages costs 1.5 points each.
5. **Select** the best *valid* layout; the designed layout is kept unless a candidate
   wins by `min_gain`. **Repair** QA findings with ≤ 2 extra renders.

Budgets (`time_budget_s`, `memory_budget_mb`) fall back to the best layout so far. All
state is per call. `ExportResult.composition` reports the strategy, candidate scores,
reasons, per-page occupancy, renders, wall/CPU time, memory, corrections, PDF/DOCX QA,
fallbacks and unverified checks. DOCX uses the same decisions and is checked on its own
LibreOffice rendering when available (`unverified` otherwise).

A learned selector can choose among *valid* results: `ranker="auto"` (the model packaged
with a release) or `ranker="model.json"` on `design_variants()`, `design(variants=...)`,
`compose("smart", ...)` and the CLI (`--ranker`). It is one small JSON file read in plain
Python, so using it needs no LightGBM; it replaces the fixed choice only when it is sure
enough, and the result says which selector chose and why. No model ships yet: the data does
not pass the training gate (`docs/LEARNED_RANKER_PLAN.md`), so `"auto"` keeps the fixed rule.

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

Every report has a `status` of **`pass`**, **`fail`** or **`unverified`**. A check that could not run
(e.g. DOCX layout without LibreOffice) is never reported as a pass, and `ExportResult.status`
reflects it (`failed` > `degraded` > `unverified` > `ok`). Strict mode raises `QualityError` only
for real errors; permissive mode returns the report. Additional page checks flag wasted space
before continuing content, detached captions, oversized headings and low page density.
`python -m dynamic_pdf.qa.golden tests/fixtures tests/golden [--update] [--sheets]` verifies
structural fingerprints of the fixture corpus and writes page contact sheets for review; CI
uploads them as the `page-contact-sheets` artifact. QA reads pages with PDFium, a core
dependency; PyMuPDF (`[qa]`, AGPL) is used instead when installed. DOCX visual checks need
LibreOffice.

### Review: render, look, fix

`review()` renders once and lists what a reader would notice, without changing anything, so you
or an agent can fix the document and review again:

```python
r = DocumentBuilder.from_markdown(text).review("pages/")      # one PNG a page in pages/
for issue in r["issues"]:
    print(issue["page"], issue["severity"], issue["code"], issue["message"])
    print("   fix:", issue["fix"])                              # what to change, in words
r["passed"]                                                    # False when any issue is an error
```

Issues come from the page checks above, the page critique (mostly empty or repeated pages; a
cover or an opening page is not reported), render diagnostics (a missing image, a formula shown
as source) and `lint()`. A failing block is reported, not raised. The same review is the CLI's
`dynamic-pdf review report.md -o pages/` (exit code 1 on errors) and the MCP server's `review` tool.

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

### Reproducible output

Documents are stamped with the time they were rendered. Set `SOURCE_DATE_EPOCH` (seconds since
1970, the reproducible-builds convention) to stamp them with a fixed time instead; the same input,
version and fonts then give the same PDF and DOCX bytes.

```bash
SOURCE_DATE_EPOCH=1700000000 dynamic-pdf render report.md --format both
```

---

## Changelog

### Unreleased

Work since v0.3.0, in brief. Design records for each step are under `docs/`.

**Changes that can affect existing users**
- `render()`, `render_bytes()` and `render_from_json()` design the document, as `export()` always has.
  For the classic theme look of v0.3, call `design(None)` first. `theme()` now counts as choosing a
  theme, so the design starts from it, as `DocumentBuilder(theme=...)` does.
- `pypdfium2` (BSD-3/Apache-2.0) is a core dependency: design variants and QA read the rendered
  pages, and a plain install could not. `[qa-permissive]` stays, empty in effect.
- `[all]` no longer installs PyMuPDF (AGPL); ask for it with `[qa]`.
- `VariantSet.accept()` writes only where it is told: `root=` or `DYNAMIC_PDF_PREFERENCES_DIR`.
- DOCX: equations are Office Math and common charts are Word charts, not pictures; caption numbers,
  references and lists of figures and tables are Word fields.

**New**
- Ready-made documents: `kit(name, data)` (CLI `kit`, MCP `kit`) in English or Arabic. `invoice` and
  `quote`: seller and buyer, dates, the lines with computed amounts, discount, VAT, total and the amount
  in words, each figure rounded where computed so the printed figures add up. `letter`: a formal letter
  with letterhead, reference, recipient, subject, body and signature. `cv`: a CV with experience,
  education, skills and languages, set for applicant tracking systems (no running header or footer,
  no hyphenation, standard sections, tagged PDF, plain Word structure).
- The library explains itself to agents and people: a guide in the package (`guide()`, CLI `guide`,
  MCP `guide`), MCP instructions sent on connect, Markdown input for every MCP tool, field
  descriptions in the JSON Schema, ```` ```chart ```` blocks holding JSON in Markdown, and `llms.txt`.
- Linked values (`{=table-id!D5}` in text shows the cell) and version comparison
  (`compared_with()`, CLI `compare`) as tracked changes in Word and a review copy in PDF.
- Citations from BibTeX (`[@key]`, `bibliography: refs.bib`, `builder.bibtex()`), written in APA or
  IEEE with the list of works cited; numbered equations with `{ref:id}` references, in PDF and Word.
- Computed tables: spreadsheet formulas in cells (`=B2*C2`, `=SUM(ABOVE)`), computed in decimals and
  written as their column writes numbers; amounts in words in Arabic and English (`=WORDS(D5)`,
  `amount_in_words`, the template filter `words`); every table as a workbook with working formulas
  (`export("x.xlsx")`, `render_xlsx()`).
- Word: native equations (Office Math), native bar/line/area/pie/doughnut charts with an embedded
  workbook when openpyxl is installed, `SEQ`/`REF`/`TOC \c` fields that renumber in Word, and
  suggested edits and comments in CriticMarkup as tracked changes and Word comments (a review copy
  in the PDF), signed by `meta(reviewer=...)`.
- `review()`, CLI `review` and an MCP `review` tool: every issue with its page and what to change,
  and one PNG a page.
- `dynamic_pdf.settings`: every `DYNAMIC_PDF_*` variable in one place, read when needed; what the
  caller passes wins. `docs/CONFIGURATION.md` lists them and what the library does to its host.
- An academic document is set as a paper (title block, abstract, booktabs tables, numbered
  references, greys for figures), in PDF and DOCX.
- A learned selector slot (`ranker=`): a model file whose training gate passed may reorder the valid
  designs; none is packaged. Training data and tools for it are under `training/` and `tools/`.
- License expression `MIT AND OFL-1.1` with every font licence in the package; `py.typed`.

**Fixed**
- A justified line before a long e-mail address or URL no longer stretches its words far apart: such a
  line keeps its natural spacing, and the address stays whole, so it copies intact.
- Right-to-left text: lines ending in a line break (an address, Label: value lines) sat on the left in
  justified paragraphs; two columns now read from the right, as in Word.
- A column of amounts with an "in words" row under it was read as text and lost its right alignment.
- Word: `rich_text` with `alignment="left"` was set by its style (possibly justified); it is left-aligned.
- Word: a phone number in Arabic text ("+966 11 000 0000") read with its groups reversed; it is now
  embedded left to right. Numbers that are not phone-shaped ("2024 2025") are left as written.
- Signatures: Arabic names are shaped and set from the right; a name is literal text (`&` or `<` no
  longer break the PDF), and `line_width` is honoured. A letter no longer gets a title block above it.
- Line and area charts in the PDF read `{"categories": [...], "series": {...}}` as the bar charts do.
- The `logo_left` and `logo_right` headers drew the logo twice. A logo in the chosen theme stays in the
  designed header, from page one, as a letterhead.
- Arabic in charts read backwards with Matplotlib 3.11, which shapes Arabic itself.
- A compound word lost its hyphen when its paragraph ran onto the next page.
- Crossed emphasis (`**a *b** c*`) stopped the whole PDF; a JPEG without a JFIF or Exif header
  stopped the DOCX; a quote wrapped over source lines split into several Word paragraphs.
- A reference list under the author's own "References" heading printed a second title; a long
  doughnut title ran over the ring.
- False alarms that rejected good designs: a chapter's opening page read as a stranded heading,
  contents leader dots counted as words, a Western and an Arabic-Indic number in one table read
  as one number.
- ReportLab's hyphen correction and Matplotlib's backend no longer change the host process.

**Earlier in this cycle**

- Editable DOCX from the same semantic document as the PDF; `export()`, `export_both()`, CLI `--format`.
- Intelligent design: `design("auto")` profiles, recipes, a layout planner, `design_explain()`.
- `compose("smart")`: CPU-only layout candidates, scored on rendered geometry, with repairs.
- Visual QA for PDF and LibreOffice-rendered DOCX, with bounded automatic fixes.
- Five art directions and `design_variants()`; an opt-in approved design grammar.
- Media placement, page systems, section openers, performance pages, ledgers and other compositions.
- 45 bundled font families; a human-reviewed typography, margin and palette standard for designed output.
- Fixed: justified Arabic paragraphs set their last line and first-line indent on the left; Arabic
  classic covers were flush left and their title ran into the author line; consecutive Markdown
  footnotes merged; DOCX files said they were created in 2013.
- Margin overflow is judged by rendered ink, not by font boxes.
- `SOURCE_DATE_EPOCH` makes PDF and DOCX output byte-for-byte reproducible.
- One engine (M9): `PageFacts`, one measured description of a rendered PDF, feeds scoring, critique,
  ranking and benchmarks; one weights table; `design(direction=, variants=, grammar=)` makes
  `export()` deliver the recommended valid design (`ExportResult.design`); CLI `variants`,
  `--direction`, `--grammar`, `--brand`; one scoreboard (`benchmarks/scoreboard.py`) with budgets.
- Content (M10): typed table columns (period, measure, currency ...), `lint()` and CLI `lint`,
  document type with a confidence and an "uncertain" outcome, `meta.audience`, figure and table
  numbers with `{ref:id}` references and lists of figures and tables, stricter chart data.
- Page breaks (M11) are chosen by search over measured heights and kept only when a render confirms
  them; Word gets native keep and row-split properties.
- Learning (M12): scripted blind AI review with two judges, `VariantSet.accept()`, a local A/B page,
  calibrated monotone weights behind the existing training gate. No model is trained yet.
- Optional AI (M13, `pip install dynamic-pdf-builder[ai]`): a Director and a Critic that only choose
  among designs the gates accept, content assistance labelled as AI-written, CLI `schema` and an MCP
  server (`[mcp]`). Nothing loads it unless the caller passes it.
- Typography and accessibility (M14): Arabic text extracts as written, justified English text
  hyphenates, QA reads PDFs through PyMuPDF or the permissively licensed PDFium (`[qa-permissive]`),
  a contrast check, real Word footnotes, and opt-in tagged PDF (`meta(tagged=True)`).
- Product (M15): streaming that parses as text arrives, templates over CSV, JSON or XLSX data
  (`render --data`, `batch`), a `charts` extra, and `python -m dynamic_pdf.service`.

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

### v0.2.0

- Initial public release with 39 block types, 7 themes, RTL support, drop cap

---

## License

MIT
