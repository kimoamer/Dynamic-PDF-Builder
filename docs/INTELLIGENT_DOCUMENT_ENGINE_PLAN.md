# Intelligent Document Engine — Deep Repository Review & Implementation Plan

**Repository:** `kimoamer/Dynamic-PDF-Builder`  
**Reviewed revision:** `62ab986f64d230000b7f78c07e54fa18d3741f6f` (`main`, v0.3.0)  
**Review date:** 2026-11-02  
**Status:** Design/review only. No runtime changes in this PR.  
**Goal:** Produce publication-quality, editable DOCX and print-ready PDF from the same semantic document; choose purposeful layouts dynamically based on document content and audience, like a competent human designer would.

## 1. Evidence-based baseline

### Existing strengths

- Fluent API, Markdown and typed JSON entry points in `dynamic_pdf/builder.py`.
- Pydantic discriminated block catalog, including charts, tables, figures, callouts, math and diagrams in `dynamic_pdf/schema/blocks.py`.
- ReportLab pagination and flowables, theme registry and several visual presets.
- Existing Arabic/RTL effort, bundled Arabic font, and structured header/footer configuration.

### Verified shortcomings / priority

| ID | Priority | File(s) / code evidence | Finding | Expected corrective behavior |
|---|---|---|---|---|
| P0-01 | Critical correctness | `dynamic_pdf/layout/engine.py:29-51,576-581,720-725` | `NumberedCanvas` sets `_total_pages` only in `save()`; the already-painted footer is not repainted. An isolated reproduction of the source logic generated `Page 1 of ?`. | Render real `Page n of N` in final output; exercise 1/2/10-page fixtures. |
| P0-02 | Critical confidentiality | `dynamic_pdf/layout/engine.py:731-764` | Missing optional `pikepdf` warns and writes the unencrypted document, although encryption was requested. | Fail closed with a typed error and no output artifact when encryption cannot be honored. |
| P0-03 | Critical for untrusted inputs | `dynamic_pdf/renderers/mermaid.py:13-32` | Diagram string is embedded raw inside HTML interpreted by Playwright, and a remote CDN module is loaded during rendering. | Treat diagram as data; escape or use isolated renderer, pin/bundle assets and disable unexpected network/JS access, with resource limits. |
| P0-04 | High for service use | `dynamic_pdf/layout/engine.py:88-122` | Logo URLs can be fetched without explicit host allowlist, size, or time controls. | Restrict to approved local assets or a bounded, validated asset resolver. |
| P1-01 | Correctness | `dynamic_pdf/layout/factory.py:1762-1849` | TOC is a list of prior headings plus dot placeholders; page numbers, destinations, and headings after the TOC are unavailable. | Real two/multi-pass page-aware, linked TOC; TOC may be placed near document start. |
| P1-02 | Correctness | `dynamic_pdf/markdown/parser.py:148-174` | Nested-list walker terminates on the first nested closing token. Reproduction with `- Parent / - Child / - Sibling` lost `Sibling`. | Preserve hierarchy, all sibling items and numbering, including nested task lists. |
| P1-03 | Reliability | `dynamic_pdf/layout/factory.py:606-614`; `dynamic_pdf/layout/engine.py:705-716` | Block failures are transformed into visible `[Block Error]` text while output can still report success. | Strict mode raises typed exceptions; permissive mode emits diagnostics and an explicitly degraded status. |
| P1-04 | Missing requested capability | `dynamic_pdf/builder.py:440-500`, `dynamic_pdf/cli.py` | Only PDF export is implemented; no editable Word renderer or `.docx` output mode. | `format='docx' | 'pdf' | 'both'` from same semantic source. |
| P1-05 | No verifiable tests | repository tree, `README.md:1095,1129-1175` | README claims ~120 tests and 100% pass, but HEAD contains no tracked `tests/` directory or CI workflow. | Restore/add executable tests, CI, reproducible report and remove unsupported badge. |
| P1-06 | Document semantics | `dynamic_pdf/markdown/parser.py:20-31,142-145` | Front matter is parsed but not carried to document metadata; inline token content is passed through as strings, losing rich semantic runs. | Parse structured metadata and inline spans, hyperlinks, image alt/caption, nested nodes. |
| P1-07 | Security/encoding | `dynamic_pdf/layout/factory.py:52-88`; `dynamic_pdf/markdown/sanitizer.py` | Ad hoc Markdown-to-ReportLab markup transformations and separate regex sanitizer are not applied consistently in the public entry points. | Parse once into safe typed runs; validate URLs/assets and escape only at render boundary. |
| P1-08 | Layout quality | `dynamic_pdf/layout/factory.py:987-1050,1403-1426,1687-1718` | Width and column decisions are mostly direct fixed constructions and nested Tables; no explicit adaptive measurement or overflow/typography scoring. | Measure before paginate, fit within frames, split long tables safely, preserve caption/image cohesion. |
| P2-01 | RTL/bilingual | `dynamic_pdf/schema/document.py:15-16`, `dynamic_pdf/layout/factory.py:28-50,639-651` | RTL detection is heuristic per string; document-level `meta.rtl` and block-level `lang` are not wired into the primary rendering pipeline. | Reliable Arabic English mixed runs, direction by paragraph and inline run, explicit locale, test Arabic digits/URLs/tables. |
| P2-02 | Theme precision | `dynamic_pdf/schema/theme.py:67-79`, `dynamic_pdf/layout/factory.py:666-673` | Per-heading size tokens exist, but headings use the `base_size * heading_scale` path. Theme says more than its current renderer applies. | Resolve every token through a single style compiler with graceful defaults and validation. |
| P2-03 | Typography/assets | `dynamic_pdf/fonts/manager.py:17-40,102-175` | `Inter` is the default for body/heading but is not bundled; fallback to Helvetica silently changes intended look. Font downloads during render are nondeterministic when files are absent. | Ship permitted fonts/license texts or require configured font packs; verify glyph coverage before rendering. |

**Scope note:** The high-priority security issues are especially relevant when this library is exposed as a multi-tenant service or accepts user-provided JSON/Markdown. A closed trusted local CLI has a smaller threat model.

### Verification limitations

The repository is private. The GitHub connector provided source inspection, but the sandbox could not resolve github.com to clone the private repository. Therefore **the full repository test suite was NOT run**. Two tiny reproductions copied the relevant source algorithm into an isolated local harness:
- footer `Page 1 of ?` extracted from a generated PDF using PyMuPDF;
- Markdown nested-list walker omitted the sibling after a nested list.
Treat all other defects as static-code findings until covered by regression tests.

## 2. Product contract: design intelligently, not randomly

The system must **never rewrite the author's facts to fit a page**. A dynamic layout planner may select structure, type scale, whitespace, table orientation, safe chart variants and page breaks without changing meaning. Optional copy improvement or summarization belongs to a separate, explicitly enabled content transformation step with traceable source provenance.

Minimum profiles:
- `executive_report`: evidence-led cover, summary, KPIs, charts, numbered sections, appendix;
- `proposal`: human editorial hero, outcomes, scope, workplan, investment, next steps;
- `corporate_memo`: concise document header, minimal ornament, dense but legible hierarchy;
- `academic_report`: citations, footnotes, bibliography, stable heading numbering and TOC;
- `technical_manual`: structured procedures, consistent code style, warnings and figure references;
- `data_report`: landscape option, long tables, repeated headers, chart/table continuity;
- `letter` and `invoice`: formal, restrained formats without gratuitous covers;
- `rtl_report`: right-first rhythm, Arabic typography and mixed English/Arabic support.

Quality principles:
1. Visual character must fit the user's purpose; do not decorate every block as a card.
2. Typography hierarchy, white space, alignment and long-form reading comfort outrank effects.
3. Respect local conventions (A4, locale, date/number formats, direction, page numbering).
4. Keep headings with their following body, figures with captions, and table headers with rows.
5. Prevent orphan headings, clipped charts, tiny fonts, wide code, and empty filler pages.
6. Accessible, selectable text in PDF; editable semantic headings/tables/images in DOCX.
7. Deterministic output for the same input, theme, assets and rendering environment.

## 3. Recommended architecture

```text
Markdown / JSON / Fluent API
    -> Parse & normalize
    -> Canonical semantic Document AST (content + metadata + provenance)
    -> Safety / schema / asset preflight
    -> Document Profile Selection (deterministic default; optional bounded AI planner)
    -> Design Recipe & Theme Token Compiler
    -> Layout Planning (measurement, page/column/asset constraints)
    -> shared RenderPlan
        +-> PDF adapter (retain ReportLab first; experimental WeasyPrint later)
        +-> DOCX adapter (python-docx, real styles and editability)
    -> QA validators + visual page renderer
    -> ArtifactManifest(pdf, docx, warnings, score, checksums)
```

### Canonical semantic AST

Implement `DocumentSpec` and typed nodes for:
- Paragraph with rich inline `TextRun` spans (bold/italic/code/links/RTL/language).
- Heading with stable ID and level.
- Nested ordered/unordered/task lists with starts and hierarchy.
- Table with typed cells, optional `colspan`/`rowspan`, header/footer rows, alignment, units and split policy.
- Figure/Image with alt text, captions, source policy, intrinsic ratio and crop/contain intent.
- Chart/Diagram with accessible alternate description and data provenance.
- Quote, callout, footnote, citation, bibliography, code, formula and page/section break.
- Explicit `document_type`, `audience`, `locale`, `direction`, `brand`, `page_size`, `output_formats`.

A stable JSON Schema is the external contract. Each input path compiles into it. No format adapter reparses Markdown or guesses content structure.

### Separate semantics, design, pagination and rendering

- `StyleTokens` / `DesignRecipe`: font families and fallbacks, type ramp, colors, grid, margins, spacing, variants for headings/tables/covers/figures; all tokens checked for contrast and font availability.
- `DocumentProfileSelector`: rules based on document type, headings, table/figure density, length, language and branding. Optional AI may propose a constrained `DesignPlan`, but is not necessary for default operation.
- `LayoutPlanner`: calculate available content areas, estimate flowable sizes, decide page/section breaks, choose table splitting and landscape sections where supported, and document layout decisions.
- `PDFRenderer`: migrate current flowables gradually; expose a single error/diagnostic contract. Use built-in ReportLab `TableOfContents` and `afterFlowable`/multi-pass support for page-aware TOC.
- `DOCXRenderer`: use real Word styles (`Normal`, `Title`, `Heading 1-6`, `Caption`, `List Bullet/Number`), sections, fields, table repeated headers, bidi paragraph/run properties, inline hyperlinks, actual editable elements where possible. Use image snapshots only where Word lacks a native analog (complex vector charts/diagrams), still retain alt text.
- `AssetResolver`: local-first and explicit paths, optional outbound fetch policy with allowlist, DNS/IP checks, content type, byte/pixel limits, timeouts and cache; no downloads during core rendering without authorization.
- `QualityGate`: real PDF text extraction + bounding boxes + rasterization; DOCX unzip/XML checks + office rendering + visual comparison; deterministic thresholds. Report warnings separately; failures are never silently marked successful.

### Renderer strategy

**Recommended:** keep ReportLab for the PDF baseline and introduce python-docx for editable Word. Both consume the same semantic AST and style recipes; layout implementation differs by renderer. Judge **structural parity** (all paragraphs, headings, assets and tables present) and designed visual consistency, **not identical page counts/pixel coordinates**.

**Optional later:** a WeasyPrint/CSS Paged Media PDF adapter for highly editorial magazine/report layouts, only after representative RTL and long-table tests pass. Do not replace the working PDF backend in the first milestone.

## 4. Milestones in dependency order

### M0 — Stabilize, secure, make outputs testable (first coding PR)

**Modify:** `dynamic_pdf/layout/engine.py`, `dynamic_pdf/layout/factory.py`, `dynamic_pdf/markdown/parser.py`, `dynamic_pdf/markdown/sanitizer.py`, `dynamic_pdf/renderers/mermaid.py`, `dynamic_pdf/fonts/manager.py`, `dynamic_pdf/builder.py`, `pyproject.toml`, `README.md`.

**Add:** `tests/test_pagination.py`, `tests/test_markdown_nested.py`, `tests/test_encryption.py`, `tests/test_safe_assets.py`, `tests/test_mermaid_security.py`, `tests/test_error_policy.py`, `.github/workflows/ci.yml`, `tests/fixtures/`.

- Fail-closed encryption and default strict error semantics for API use.
- Fix `Page n of N`, heading continuity, nested Markdown lists, and true linkable page-number TOC.
- Remove surprise outbound network for assets, pin dependency and render contexts; enforce configurable caps.
- Record actual test outcomes; remove/replace unsupported `100% passing` badge and test-count claims.
- Include license text for redistributed fonts; make permitted packaged-font usage deterministic.

**Acceptance:**
- 1/2/10 page fixtures show final total correctly; no `?` in page numbering.
- Missing encryption backend raises before delivering an unencrypted file.
- `Parent -> Child` and `Sibling` survive Markdown -> AST -> PDF.
- Failing asset/block produces a typed error in strict mode, not an apparently successful report.
- TOC at front has real destinations and final page numbers.
- No unapproved network fetch or diagram HTML execution from untrusted input.
- CI runs all tests on a documented Python matrix.

### M1 — Canonical AST + styles/brand design contract

**Add:** `dynamic_pdf/core/document_spec.py`, `dynamic_pdf/core/inline.py`, `dynamic_pdf/core/normalize.py`, `dynamic_pdf/design/profile.py`, `dynamic_pdf/design/recipes.py`, `dynamic_pdf/design/tokens.py`, `tests/test_ast_contract.py`, `tests/test_profiles.py`.

**Modify:** `dynamic_pdf/schema/blocks.py`, `dynamic_pdf/schema/document.py`, `dynamic_pdf/markdown/parser.py`, `dynamic_pdf/builder.py`, `dynamic_pdf/schema/theme.py`, `dynamic_pdf/layout/factory.py`.

- Provide adapters from all v0.3 fluent and JSON blocks, preserving backward compatibility.
- Preserve inline links/marks, nested lists, metadata/front matter, image accessibility metadata.
- Compile theme tokens consistently; select profile explicitly or by deterministic auto detection.
- Add a `design_explain()` method describing why style/layout decisions were chosen.

**Acceptance:** published fixture corpus round trips source -> AST without losing content or link/citation semantics; unchanged v0.3 public calls still work.

### M2 — Editable DOCX renderer

**Add:** `dynamic_pdf/renderers/docx_renderer.py`, `dynamic_pdf/renderers/docx_styles.py`, `dynamic_pdf/renderers/docx_fields.py`, `tests/test_docx_semantics.py`, `tests/test_docx_rtl.py`, `tests/test_pdf_docx_parity.py`.

**Modify:** `pyproject.toml`, `dynamic_pdf/__init__.py`, `dynamic_pdf/builder.py`, `dynamic_pdf/cli.py`, `README.md`.

- Public API: `builder.export(path, format='pdf'|'docx')`, `builder.export_both(directory)`, and `dynamic-pdf render in.md -o out.docx`; keep `render()` as backward-compatible PDF.
- Real Word paragraphs, headings, tables, section breaks, headers, footers, page-number fields, TOC field and styles.
- Arabic/bilingual style fonts and paragraph direction; test Office/LibreOffice round trips.
- Chart/diagram fallback uses embedded images only when native Word structures are impractical, preserving alt text and caption.

**Acceptance:** generated `.docx` opens without repair, is editable, has accurate structured headings, and survives office PDF conversion without clipped or overlapping content; AST semantic parity across both formats.

### M3 — Adaptive layout designer

**Add:** `dynamic_pdf/design/planner.py`, `dynamic_pdf/design/measure.py`, `dynamic_pdf/design/quality.py`, `dynamic_pdf/design/brand.py`, `tests/test_adaptive_layout.py`.

- Different per-content layouts: executive summary/metrics, proposal sections, academic, manuals, dense reports.
- Adaptive tables with content-aware widths, long-table splitting, caption pairing and controlled landscape pages.
- Orphan/widow and `keep_with_next` policies; preserve natural reading rhythm.
- Design recipe gallery; no random colors, accidental card overload, or font shrinking below declared limits.
- Optional AI planner only outputs validated style/structure choices; it never fabricates, drops, or rephrases factual content unless asked.

**Acceptance:** 12+ real-world fixtures (Arabic RTL, bilingual, academic, financial, proposal, legal/memo, technical, data-heavy) pass content preservation and visual inspection.

### M4 — Automated visual QA, performance and release hardening

**Add:** `dynamic_pdf/qa/pdf_checks.py`, `dynamic_pdf/qa/docx_checks.py`, `dynamic_pdf/qa/rasterize.py`, `dynamic_pdf/qa/report.py`, `tests/golden/`, benchmark harness and image-diff review workflow.

- Render every output page for structural and visual quality assessment.
- Verify no out-of-bound text/images, blank accidental pages, overlapping text, wrong margins, missing glyphs, corrupt links, detached table captions or broken RTL.
- Strict and permissive validation modes; structured manifest with diagnostics, version, profile and source hash.
- Security fuzzing, large-input limits, offline tests, font reproducibility and dependency checks.
- Document known Word vs PDF layout differences; publish a sample gallery per recipe.

**Acceptance:** CI exports both formats for all golden fixtures, checks content parity, and attaches reproducible page images / failures; human reviewer signs off on the style gallery.

## 5. Design QA fixture matrix

Each fixture produces PDF, DOCX and a rendered-page contact sheet:
1. One-page English formal letter.
2. One-page Arabic formal letter with numbers/dates.
3. Ten-page bilingual corporate report (mixed runs, tables, header/footer).
4. Thirty-page English technical manual (code, admonitions, nested lists).
5. Academic paper (footnotes, citations, bibliography, linked TOC).
6. Financial report with 100+ table rows and repeating headers.
7. Proposal with cover, hero, scope and milestones.
8. Data report with chart + table + captions and long numerical labels.
9. Asset stress (huge image, broken image, attempted remote URL).
10. Security stress (malformed markup, malicious Mermaid payload, huge Markdown).
11. Encryption positive and missing-dependency negative cases.
12. Multi-column layout with pagination and long-content fallback.

Every test should record: parser counts, output content hash, page counts, fonts, headings, table row counts, warnings, and visual check outcome. A test that creates a file is **not** equivalent to a test that confirms its layout.

## 6. Proposed public API

```python
from dynamic_pdf import DocumentBuilder

doc = (DocumentBuilder.from_markdown(source_md)
       .meta(title="Annual Review", language="ar")
       .document_type("executive_report")
       .design("auto", brand=brand_kit)
       .quality("strict"))

result = doc.export_both("./out")
# result.pdf_path, result.docx_path, result.profile, result.diagnostics
```

This is a **target API**, not code that exists in v0.3.0.

## 7. Engineering discipline and rollout

- Use separate reviewed PRs for M0/M1/M2/M3/M4; don't merge all refactors at once.
- Each PR: failing regression first (RED) -> smallest fix (GREEN) -> refactor -> actual test output and rasterized samples.
- Preserve original `DocumentBuilder` fluent API and JSON compatibility via adapters, with deprecation notices only where strictly necessary.
- Benchmark before switching PDF backends. Record test counts from CI rather than claims in README.
- Stable, versioned schema and deterministic fixtures allow rollback to the current PDF renderer.
- Review all theme assets/licenses and deployment resource limits prior to providing public API access.

## 8. Design decision and references

- **PDF**: ReportLab remains primary for M0/M1; its official `TableOfContents` with `afterFlowable` and `multiBuild` supplies the missing real page index.
- **Editable DOCX**: python-docx supports real paragraph styles, sections, headers/footers and pagination properties (keep-with-next, widow-control). More complex XML fields/bidi use narrowly tested OOXML helpers.
- **Alternative editorial PDF**: WeasyPrint supports CSS paged media and can be piloted after parity checks.
- **Visual QA**: PyMuPDF exposes page text block bounding boxes and high-DPI rendering for layout inspection.

References:
- https://docs.reportlab.com/reportlab/userguide/ch9_other_useful_flowables/
- https://python-docx.readthedocs.io/en/latest/api/text.html
- https://python-docx.readthedocs.io/en/latest/user/styles-understanding.html
- https://github.com/python-openxml/python-docx/blob/master/docs/user/sections.rst
- https://github.com/Kozea/WeasyPrint/blob/main/docs/api_reference.rst
- https://pymupdf.readthedocs.io/en/latest/page.html

---

**Suggested next execution:** M0 in an isolated implementation branch, with a failing regression test for the two locally reproduced bugs as the first commit. Do not treat this planning PR as a code fix.
