# Dynamic PDF Builder: guide for people and AI agents

Read with `dynamic_pdf.guide()` (Python), `dynamic-pdf guide` (terminal) or the `guide` tool of the MCP
server. Each section is a topic: `dynamic-pdf guide tables` prints one.

## Overview

Dynamic PDF Builder turns content into a finished, designed document:

- **In:** Markdown (the easiest, and what this guide recommends), a JSON document, or a fluent Python API.
- **Out:** a PDF to read and print, a DOCX to edit in Word, and the tables as an Excel workbook.
- **Design is the library's job:** it reads what the content is (a report, an invoice, a paper, a
  letter ...) and chooses fonts, colours, page layout, table styles and page breaks. You write the content.
- **Arabic and right-to-left text are first class**, as are documents that mix Arabic and English.
- **Quality is checked:** every design is rendered and inspected (text off the page, overlaps, headings
  stranded at the foot of a page, missing characters, missing words) before it is delivered.

What it does not do: write the content for you (an optional AI layer can draft summaries and alt
text), edit existing PDF or DOCX files, or lay out freehand pages like a design tool.

## Quickstart

Python:

```python
from dynamic_pdf import DocumentBuilder

b = DocumentBuilder.from_markdown(open("report.md", encoding="utf-8").read())
b.export("report.pdf")       # designed PDF
b.export("report.docx")      # the same document, editable in Word
b.export("tables.xlsx")      # its tables as a workbook (needs the xlsx extra)
result = b.review("pages/")  # what a reader would notice, with page images in pages/
```

`export()` picks the format by the extension; `render()` writes the PDF (or returns its bytes). Both design
the document; `b.design(None)` asks for the plain classic look instead.

Terminal:

```bash
dynamic-pdf render report.md -o report.pdf     # .docx or .xlsx by the extension
dynamic-pdf review report.md -o pages/         # issues, each with what to change
dynamic-pdf variants report.md -o designs/ -n 3
dynamic-pdf compare old.md new.md -o changes.docx
dynamic-pdf lint report.md
```

AI agents over MCP (`pip install "dynamic-pdf-builder[mcp]"`, then
`python -m dynamic_pdf.ai.mcp_server --out-dir ./out`): tools `guide`, `render`, `review`, `variants`,
`explain`, `lint`, `kit` and `schema`. `render`, `review`, `variants`, `explain` and `lint` take `markdown` (a
string) or `document` (JSON). The loop that works: write Markdown, `render`, `review`, fix what it lists,
`review` again.

## Markdown

Front matter (optional, at the very top):

```markdown
---
title: Quarterly report            # shown on the cover or at the head of page one
author: Finance team
subject: Q3 2026                   # subtitle
language: ar                       # en (default) or ar; Arabic text is detected anyway
document_type: financial_report    # optional: executive_report, proposal, academic_report, invoice, letter ...
audience: board                    # who reads it, in words; the design takes it into account
numbering: true                    # number captioned tables and figures
bibliography: refs.bib             # BibTeX for [@key] citations
citation-style: apa                # apa (author and year) or ieee (numbers)
reviewer: Policy AI                # name on suggested edits and comments
header: modern                     # header and footer: letterhead, modern, banner, report, minimal
logo: logo.png                     # the logo; without header, a letterhead (letters, invoices) or modern
company: Nile Co.                  # for the header: also address, website, email, phone, confidentiality ...
---
```

Text: `**bold**`, `*italic*`, `~~struck~~`, `` `code` ``, `==highlight==`, `x^2^`, `H<sub>2</sub>O`,
`[link](https://example.com)`, footnotes `text[^1]` with `[^1]: the note` anywhere below.

Blocks:

| Write | Get |
| --- | --- |
| `# Heading` to `###### Heading`; `# Results {#results}` gives it an id | headings (numbered when the design numbers them) |
| `- item`, `1. item`, nested by indenting | lists |
| `- [x] done` / `- [ ] to do` | a checklist |
| `Term` then `: definition` on the next line | a definition list |
| a GFM table, then `Table: caption {#id}` on its own line under it | a table with a caption and an id |
| `![alt text](photo.jpg "caption"){#fig-id}` alone in a paragraph | a figure |
| `> quoted text`, then `> — Name` as its last line | a quote with its attribution, a bar along its start edge |
| `> [!pullquote]` or `> [!epigraph]` as the quote's first line | a statement set large, or a short epigraph toward the end edge |
| ```` ```signature ```` with `{"name": ..., "title": ..., "image": "sig.png"}`, or a list of them | a signature, or up to four side by side |
| `:::warning` ... `:::` (also info, tip, success, danger, caution, important, example) | a callout box |
| ```` ```python ```` ... ```` ``` ```` | code, highlighted |
| `$$ E = mc^2 $$ {#eq-energy}` or ```` ```math ```` | an equation (numbered when it has an id) |
| ```` ```chart ```` with a JSON object | a chart (see Charts) |
| ```` ```mermaid ```` | a diagram (needs the diagrams extra or a local mermaid.js) |
| `---` | a divider |
| `[TOC]`, `[LOF]`, `[LOT]`, `[REFERENCES]` alone in a paragraph | contents, list of figures, list of tables, the works cited |

References inside text: `{ref:results}` reads "Section 2", `{ref:fig-id}` "Figure 3", `{ref:tab-id}`
"Table 1", `{ref:eq-energy}` "Equation (1)". `{=tab-id!D5}` shows what cell D5 of that table shows.
`[@smith2024]` is a citation (see Academic).

## Charts

In Markdown:

````markdown
```chart {#fig-revenue}
{"type": "bar", "title": "Revenue by region, SAR m", "data": {"North": 14.3, "South": 12.5, "East": 7.8}}
```
````

In Python: `b.chart("bar", {"North": 14.3, "South": 12.5}, title="Revenue")`.

Types: bar, vertical_bar, horizontal_bar, grouped_bar, stacked_bar, line, area, pie, donut, scatter,
bubble, histogram, heatmap, waterfall, funnel, gauge, sparkline, treemap.

Data: one series is `{"label": value}`. Several series (grouped_bar, stacked_bar, line, area) are
`{"categories": ["Q1", "Q2"], "series": {"2025": [3, 4], "2026": [4, 6]}}`. Optional keys: `x_label`,
`y_label`, `colors` (a list of hex colours), `legend` (true or false). Shares in a pie must be parts of
a whole: no negative values. Data a chart cannot draw truthfully is refused with the reason.

In Word, bar, line, area, pie and doughnut charts are native Word charts whose data can be edited; the
other types are pictures.

## Tables

A GFM table. Columns of figures are right-aligned; rows labelled Total or Subtotal are set in bold with
a rule above; a total row's label runs over the empty cells before its figure.

Computed cells: a cell that starts with `=` is a formula, written as in a spreadsheet. Columns are A, B,
C ... and rows count from 1, the header row.

```markdown
| Item  | Qty | Price        | Amount         |
|-------|-----|--------------|----------------|
| Paper | 3   | SAR 12.50    | =B2*C2         |
| Toner | 2   | SAR 1,310.00 | =B3*C3         |
| VAT   |     | 15%          | =SUM(D2:D3)*C4 |
| Total |     |              | =SUM(ABOVE)    |
| In words |  |              | =WORDS(D5)     |

Table: Invoice lines {#invoice}
```

- Functions: SUM, AVERAGE, MIN, MAX, COUNT, ROUND, ABS, NPV and IRR (as a spreadsheet has them:
  `=B2+NPV(10%, B3:B7)` for a project's value, `=IRR(B2:B7)` written as a percent); `ABOVE` and `LEFT` (the numbers above in the
  column, or to the left in the row); `15%` is 0.15. Arithmetic is decimal and exact.
- A result is written like its column: currency, decimals, thousands separators, percent, negatives in
  parentheses, Arabic-Indic digits.
- `=WORDS(D5)` writes the amount in words in the document's language ("فقط ثلاثة آلاف ... لا غير",
  "Three thousand ... only"); a currency code may follow: `=WORDS(D5, "EGP")`, `=WORDS(D5, "en", "USD")`.
  Codes: SAR, EGP, AED, KWD, QAR, OMR, BHD, JOD, USD, EUR, and GBP in English.
- Text can quote a cell: `The total due is {=invoice!D5}.`
- A formula that cannot be computed stops the render with the table, the cell and the reason.
- `export("tables.xlsx")` writes every table as a sheet with working formulas.

## Academic

- Citations: `[@abara2023]`, `[@abara2023, p. 50]`, `[@kim2021; @lund2022]`, with `bibliography: refs.bib`
  in the front matter (or `b.bibtex("refs.bib")`). APA writes "(Abara & Halvorsen, 2023, p. 50)", IEEE
  "[1, p. 50]". The list holds only the works cited, where `[REFERENCES]` stands or at the end.
- Numbered equations: `$$ ... $$ {#eq-name}`, referred to with `{ref:eq-name}`.
- Numbered tables and figures: give a caption and an id; `{ref:id}` reads "Table 2".
- An academic document (`document_type: academic_report`, or content that reads as a paper) is set as a
  paper: title block, abstract, booktabs tables, numbered sections, figures in greys.
- In Python: `b.abstract(fields=[...], keywords=[...])`, `b.footnote(...)`, `b.bibliography(entries=[...])`.

## Review and changes

- `b.review("pages/")` (CLI `review`, MCP `review`): each issue with its page, severity, code, message
  and `fix`, what to change in words; one PNG a page. Nothing is changed. Fix the source and review again.
- `b.lint()` (CLI `lint`): content warnings: totals that do not add up, shares that do not make 100,
  references and citations to nothing, mixed digits or date formats, images without alt text, empty
  sections, formulas that cannot be computed.
  Each warning names its rule: `total_mismatch`, `percent_sum`, `repeated_heading`, `unresolved_ref`,
  `mixed_digits`, `number_format`, `date_format`, `missing_alt_text`, `empty_section`, `formula_error`,
  `unresolved_citation`; `lint(rules=[...])` runs only some.
- Suggested edits and comments in any text (CriticMarkup): `{++added++}`, `{--removed--}`,
  `{~~old~>new~~}`, `{==text==}{>>comment<<}`, `{>>comment<<}`. Word gets tracked changes and comments
  signed by `reviewer`; the PDF is a review copy.
- `new.compared_with(old)` (CLI `compare old.md new.md -o changes.docx`) marks every difference between
  two versions as tracked changes.

## Design

- Every output is designed by default (`export()`, `render()` and the CLI). `b.design(None)` asks for the
  classic look of the chosen theme instead.
- `b.design(direction="editorial_modern")` picks an art direction: corporate_conservative,
  editorial_modern, executive_premium, financial_data, arabic_institutional, academic_paper.
- `b.design_variants(n=3)` (CLI `variants`) renders several directions, checks each, and recommends one.
- `b.design_explain()` (MCP `explain`) says why each decision was made.
- Themes (the design starts from the one you choose; with `design(None)` it is the whole look): claude, chatgpt, corporate_dark, academic, modern_minimal,
  government, data_report. A brand kit (colours, fonts, logo) goes in `b.design(brand=BrandKit(...))`.

## Headers, footers, logos and signatures

A preset places the logo, title, section, company and page number by reading edge, so it mirrors in
Arabic, lines up with the text column, and takes its colours from the design. Page one opens with the
document's own title, so its header shows the subtitle or company instead of repeating it. A logo is
any PNG, JPEG or SVG; give it with transparent background:

```python
b.page_system("modern", logo="logo.png", company="Nile Co.", confidentiality="Internal")
```

- `letterhead`: a large logo and the company at the head of page one, the website, email and phone over
  a rule of the accent colour; later pages carry a small logo and the title, and get their room back.
- `modern`: the logo over a rule of the accent colour, the title and running section at the end;
  confidentiality, company and "3 / 12" under a hairline.
- `banner`: the logo, on a light plate so its own colours show, and the title on a band of the primary colour.
- `report`: the title and running section over a hairline; company, confidentiality and the page below.
- `minimal`: the page number only.

Any arrangement can be built with `b.page_system({...})`: each band has rows, and each row has `start`,
`center` and `end` slots (or `left` and `right`, which do not mirror) holding text and logos. Text may
carry fields: `{title}`, `{section}` (the current heading), `{page}`, `{pages}`, `{date}`, `{company}`,
`{website}`, `{email}`, `{phone}`, `{department}`, `{confidentiality}`, `{code}`, `{period}`. A field
with no value is left out with its separator. Colours may be hex or a theme colour by name
(`primary`, `accent`, `text_muted` ...). Page numbers and sections stay live fields in Word.

Signatures: `b.signature("Omar Hassan", title="Director", date="17 November 2026", image="sig.png",
alignment="start")` (start, center or end) and `b.signatures([{...}, {...}])` for up to four side by side,
standing on one line. The image goes through the asset policy like any picture.

Quotes: `b.quote(text, attribution="Name", style="blockquote" | "pullquote" | "epigraph")`.

## Kits

Ready-made documents: give the data, get the whole document with every part it needs, designed and checked.

```python
from dynamic_pdf import kit, kit_example
data = kit_example("invoice")          # example data to change
kit("invoice", data).export("invoice.pdf")   # or .docx, or .xlsx for the lines with their formulas
```

Terminal: `dynamic-pdf kit invoice --example > invoice.json`, then `dynamic-pdf kit invoice invoice.json -o
invoice.pdf`. MCP: the `kit` tool (without `data` it returns the example).

Every kit reads `language`: `en` or `ar`, and `logo` (a PNG, JPEG or SVG path): the letter gets a
letterhead with the sender's name, address and contacts; the invoice and quotation a logo header; the
feasibility study and statements a report header; the certificate the logo over its title. A CV takes
none, for applicant tracking systems. A missing or malformed field is refused with its name and the fix.

- `invoice` reads `number`, `date`, `due`, `currency` (SAR, EGP, USD ... for the amount in words), `seller`
  and `buyer` (each `name`, `address`, `tax_id`, `email`, `phone`), `items` (each `description`,
  `quantity`, `price`), `discount` (an amount, or a percent as `"10%"`), `tax_rate` (percent), `payment`
  (label: value pairs) and `notes`. It writes the seller and buyer side by side, then the lines, subtotal,
  discount, VAT, total and the amount in words as formulas, each rounded to cents where it is computed, so
  the printed figures add up to the printed total. A unit price keeps its own decimals.
- `quote`: a quotation, with the same fields as `invoice`; `due` reads "Valid until" and `payment` "Terms".
- `letter`: a formal letter. `sender` (the letterhead: `name`, `address`, `email`, `phone`), `date`,
  `reference`, `recipient` (`name`, `title`, `organisation`, `address`), `subject`, `body` (Markdown, or a
  list of paragraphs), `salutation` and `closing` (defaults in the letter's language), `signature`
  (`name`, `title`), `enclosures` and `cc`.
- `cv`: a CV. `name`, `headline`, `contact` (`email`, `phone`, `location`, `links`), `summary` (Markdown),
  `experience` (each `role`, `organisation`, `location`, `start`, `end` (none: to the present), `points`),
  `education` (each `degree`, `institution`, `start`, `end`, `note`), `skills` (a list, or groups:
  `{"Tools": ["Excel", "SQL"]}`), `languages` and `certifications`. It is set for applicant tracking
  systems: standard section names, the job title on its own line with "organisation | location |
  dates" under it, no running header or footer, text flush to the start edge and never hyphenated, a
  tagged PDF, and in Word real heading styles with no tables or text boxes.
- `feasibility`: a feasibility study. `title`, `prepared_by`, `date`, `currency`, `summary` (Markdown),
  `discount_rate` ("12%"), `years` (each `year`, `investment`, `revenue`, `costs`; the first year carries
  the investment), `assumptions`, `risks` and `conclusion`. It writes the cash flows by year with net and
  cumulative flows, NPV and IRR as formulas, the payback period, and a chart of the net flow by year.
- `statements`: financial statements. `company`, `title`, `period`, `currency`, `periods` (column titles,
  e.g. `["2026", "2025"]` for a comparative year), `income` (`revenue`, `cost_of_sales`,
  `operating_expenses`, `other`, `tax`) and `position` (`non_current_assets`, `current_assets`, `equity`,
  `non_current_liabilities`, `current_liabilities`), each a list of `{"label", "values"}` with one amount a
  period; costs are entered as positive amounts and shown in brackets, `other` keeps its sign. Gross,
  operating and net profit and every total are formulas. Statements that do not balance are refused with
  the difference.
- `certificate`: a landscape certificate. `organisation`, `title` (default "Certificate of Completion"),
  `recipient`, `gender` (`f` for the Arabic feminine), `achievement`, `details`, `date`, `number` and
  `signatures` (one or two, each `name` and `title`).

## Output

| Format | How | Notes |
| --- | --- | --- |
| PDF | `export("x.pdf")` | designed, checked; `meta(tagged=True)` for a tagged, accessible PDF |
| DOCX | `export("x.docx")` | real Word styles, contents and number fields, native equations, native charts, footnotes, tracked changes |
| XLSX | `export("x.xlsx")` | the tables only, with formulas (the xlsx extra) |

`export()` returns an `ExportResult` with `status` (ok, unverified, degraded, failed) and the reasons.
`export(..., qa=True)` also inspects the pages and repairs what it can measure.

## Python API

Every Markdown feature has a builder method, and more: `heading`, `paragraph`, `bullet_list`,
`numbered_list`, `checklist`, `definition_list`, `table`, `image`, `chart`, `math`, `mermaid`,
`diagram`, `callout`, `quote`, `code`, `metric_row` (KPI figures), `progress_bar`, `score_display`,
`timeline`, `signature`, `qrcode`, `cover_page`, `table_of_contents`, `abstract`, `footnote`,
`bibliography`, `two_column`, `sidebar`, `section_opener`, `page_break`, `watermark`. Each returns the
builder, so calls chain. `DocumentBuilder.from_markdown(text)` starts from Markdown and more blocks can
be added after.

JSON: `{"meta": {...}, "blocks": [{"type": "heading", "text": "..."}, ...]}`; `dynamic-pdf schema` (or the
MCP `schema` tool) prints the JSON Schema with a description of every field.

## Arabic

Write Arabic as it is; direction is detected per paragraph, and `language: ar` (or `direction: rtl`)
makes the whole document right-to-left. Tables, lists, captions, page numbers, charts and the Word file
follow. Arabic-Indic digits stay as written, and computed cells keep them. Amounts in words and
references ("المعادلة (1)", "جدول 2") are written in Arabic in an Arabic document.

## Safety and settings

- Remote images are refused unless `AssetPolicy(allow_remote=True)`; local files can be confined to a
  folder with `AssetPolicy(base_dir=...)`. The same policy reads `.bib` files.
- `RenderPolicy(error_mode="permissive")` draws a visible marker where a block fails instead of raising.
- `ResourceLimits` caps input size, blocks, table cells, pages, time and memory; for untrusted input use
  `python -m dynamic_pdf.service`, which renders each request in a subprocess.
- Environment variables (`DYNAMIC_PDF_*`) and what the library does to its host: `docs/CONFIGURATION.md`.

## Limits

- Bar, line, area, pie and doughnut charts are native in Word; other chart types, diagrams and QR codes
  are pictures there.
- Formulas work in tables at the top level of the document, not inside columns or sidebars.
- Emphasis inside a suggested edit should open and close inside it.
- Word lays out its own pages, so its page count can differ from the PDF's.
- A long unbreakable word (an e-mail address, a long URL) can leave the justified line before it widely spaced.
