# M14: typography, Arabic and accessibility

- **Branch:** M14 worktree, on `main` at `4890d03`
- **Environment:** Linux, Python 3.13, ReportLab 5.0.1, PyMuPDF 2.1, pypdfium2 5.x (PDFium 153), uharfbuzz 0.57, pikepdf 10.18, LibreOffice
- **Owner decisions applied:** PDF/UA is a goal to spike, not a requirement (decision 3). AGPL PyMuPDF stays optional, behind an interface, with a permissive alternative (decision 4).

## Status against "Done when"

| Criterion | Status | Evidence |
| --- | --- | --- |
| A verbatim search finds Arabic source text in the PDF | **Done** | `test_verbatim_search_finds_arabic_source_text`: the whole 30-word paragraph and its heading are found verbatim in `page.get_text()`, with no NFKC step, including the lam-alef words. No presentation forms are left in the extracted text. Classic and designed output. |
| A justified probe paragraph hyphenates, and loose lines fall on the corpus | **Done** | `test_justified_probe_paragraph_hyphenates_and_keeps_every_word`. On the corpus (11 fixtures, classic and `design()`, plus 7 stress documents, both modes): loose justified lines went from **65 of 305 (21.3%)** to **5 of 308 (1.6%)**. A loose line here is one whose word gaps are more than twice a normal space. |
| A sample passes a PDF/UA validator | **Not done** | veraPDF is a Java application that is not on PyPI, and installs from other sources were outside this task. The tagged output was checked structurally with pikepdf instead (below). It would not pass yet: see "What keeps it from PDF/UA". |
| QA and variants run without PyMuPDF installed | **Done** | `test_qa_runs_without_pymupdf` and `test_variants_run_without_pymupdf` make `import pymupdf` and `import fitz` fail and run QA (`qa("pdf")`, a planted clipping and missing-glyph defect, the critique) and `design_variants(n=3)` on PDFium. No check reports itself as unverified. |

## 1. Arabic shaping and extraction (F10)

### Spike: ReportLab's HarfBuzz path, not adopted

`uharfbuzz` 0.57 was installed and `ParagraphStyle(shaping=1)` used with Amiri, on logical, unreshaped text.

- **ReportLab's own bidi needs `rlbidi`, which is not on PyPI** (ReportLab ships it from its own index). Without it, `wordWrap="RTL"` does nothing and `rtlSupport` is False. So shaping would be ReportLab's job and line order ours.
- **With our line reordering, the shaped output is garbled.** `Paragraph` lays lines out in logical order and reorders each line's characters for display (`_visual_line`). HarfBuzz shapes each word into glyphs in visual order. Reordering already-shaped glyph runs reversed the letters inside words (rendered sample: "ةرادإ درالموا" for "إدارة الموارد").
- **Extraction got worse, not better.** With shaping on, the extracted text held 0 presentation forms but also lost most letters: ligature glyphs had no usable ToUnicode entry, and a verbatim search failed.
- **Speed:** 0.013 s against 0.007 s for the same paragraph, so about 2x slower before any of the bidi work it would need.

Adopting it means replacing our bidi line reordering with `rlbidi`, a package outside PyPI, and re-proving every Arabic test (line order, split paragraphs, justified right-to-left text, diacritics, mixed runs). That is not a one-week change, and the reshaper already draws correctly. **Decision: keep the reshaper and add a text mapping.**

### What was done: ToUnicode maps presentation forms to the base letters

Every font subset ReportLab writes gets its `/ToUnicode` CMap from one module function, `reportlab.pdfbase.ttfonts.makeToUnicodeCMap`. `dynamic_pdf/fonts/manager.py` wraps it. A code that maps to an Arabic presentation form (U+FB50 to U+FDFF, U+FE70 to U+FEFF) now maps to its NFKC base letters instead. Every other code keeps ReportLab's own mapping, byte for byte. That is tested.

A ligature's letters are written in **visual order**, the order its glyph is drawn in. Lam-alef U+FEFB maps to U+0627 U+0644. Measured on three extractors:

| Extractor | Plain order | Visual order (adopted) |
| --- | --- | --- |
| PyMuPDF `get_text()` (reorders RTL lines) | "إبالغكم", "األول": wrong | source found verbatim |
| PDFium `get_text_range()` (reorders within words) | wrong inside lam-alef words | every word correct |
| pdfminer (no reordering) | not the mirror | the exact mirror of the source |

Nothing is drawn differently: the glyphs, pixels and goldens are unchanged. Only text extraction changes. ActualText marked content would also work, but it would have meant wrapping every Arabic run in the paragraph and canvas code. The CMap is one seam that covers paragraphs, canvas strings, tables, bands and charts.

## 2. Hyphenation (F11)

- **PDF:** body paragraphs and lead paragraphs that are justified and left-to-right get `hyphenationLang` from the document language through `pyphen.language_fallback` (`en`, `de`, `fr` and so on), with a minimum word length of 8. Headings, tables, lists, code, captions, notes and right-to-left text never hyphenate, because only those two paragraph branches call `_hyphenated()`. A language with no dictionary (Arabic) gets none. A right-to-left document uses `ar`, as the PDF engine does, so it gets none either.
- **Minimum word length 8, not ReportLab's 5:** the same loose-line result (5 lines) with fewer breaks (60 against 77 hyphenation breaks on the corpus). The academic stress paper ends 16 of 136 lines with a hyphen, never two lines in a row.
- **Word:** `w:autoHyphenation` in `settings.xml`, `w:suppressAutoHyphens` on Normal (so headings, tables, lists, captions and code inherit it), and the suppression switched off in Body Text. Same language rule as the PDF.
- **Content ledger:** a line-end hyphen is read both ways in `check_pdf_content`, as a break and as the author's own hyphen. A hyphenation point is then not a missing word. `same_extracted_words` rejoins such breaks. PDFium's own join marker, U+FFFE, is given back in MuPDF's form.
- **Goldens:** unchanged. `python -m dynamic_pdf.qa.golden tests/fixtures tests/golden` passes on all 11 fixtures: the page counts and structure did not move.

## 3. Accessibility

### Contrast check (`dynamic_pdf/qa/contrast.py`)

Each text span's fill colour is compared with the colour actually painted behind it. That colour is the commonest pixel colour in the span's box, padded, that is not the text's own colour. The page is rendered once at 72 dpi. WCAG 2.x AA applies: 4.5:1 for body text, 3:1 for large text (18 pt, or 14 pt bold). Findings are `low_contrast` **warnings**, one per colour pair per page, never gate failures. Both backends agree on the corpus.

It found real issues: the metric-delta greens in three stress documents (`#10b981` on white is 2.54:1, `#00c853` is 2.24:1, `#48bb78` is 2.43:1). The fixtures are clean.

### Tagging spike: tag the ReportLab output (opt-in)

`DocumentBuilder().meta(tagged=True)`, or `meta.tagged` in JSON. Implementation in `dynamic_pdf/layout/tagging.py`:

1. While pages are drawn, each tagged flowable is wrapped in `/Tag <</MCID n>> BDC ... EMC`. Paragraphs tag themselves in `Paragraph.drawOn`. Other leaves (designed headings, images, charts, drop caps) are wrapped where `GeoFrame.add` places them, and taken back if nothing was placed. Running heads, feet and page layers are `/Artifact`. The roles come from the existing geometry tags (`_role_for`). Table cells carry their table, row and logical column, so right-to-left tables keep reading order.
2. After ReportLab writes the file, pikepdf adds `/MarkInfo <</Marked true>>`, `/StructTreeRoot` with a ParentTree, `/Lang`, `/ViewerPreferences /DisplayDocTitle`, and on each page `/StructParents` and `/Tabs /S`. The tree is Document > H1 to H6, P, Figure (with `/Alt` from alt text or caption), Caption, L > LI > LBody, and Table > TR > TH/TD.
3. A paragraph split across pages, a drop-capped paragraph included, is one element with one MCR per page. A header row repeated on the next page of a split table is an artifact. Tagging is combined with encryption (tagged first) and stays reproducible under `SOURCE_DATE_EPOCH`.

Checked with pikepdf on all 11 fixtures and 7 stress documents, designed. Pixels at 40 dpi and extracted text are identical to the untagged file. Every MCID in every content stream is in the ParentTree and nothing else is. `check_pdf_syntax()` finds nothing. Rendering takes about 10 to 15% longer. Untagged output carries no structure tree.

**What keeps it from PDF/UA** (measured on the same corpus): 94% of text-showing operators are tagged or artifacts. The other 270 of 4,589 are list bullets and numbers, contents entries, cover text, metric tiles, timeline and badge labels. 1,042 path and image paints are outside both: table rules and fills, dividers, callout boxes and chart frames. Also missing: figure `/BBox`, `/Lbl` for list markers, link `/Link` elements with `/OBJR`, `/Scope` on TH, XMP `pdfuaid`, and a validator run.

**Decision: keep tagging the ReportLab output; no second backend.** Every gap above is drawn by code we own, and the seam (marked content at draw time plus a pikepdf post-pass) already carries headings, paragraphs, lists, tables and figures without changing a pixel. Each remaining item is a local change: wrap the decoration draws in `/Artifact`, tag the list labels and the contents flowable. A second backend would duplicate the whole layout engine to get the same tree. Next step: mark decoration as artifacts, then run veraPDF in CI (a Java job) and fix what it reports, until a sample passes.

## 4. DOCX editability: real Word footnotes

`dynamic_pdf/renderers/docx_footnotes.py` creates a `word/footnotes.xml` part (separator and continuation separator, the relationship, the content type) and the `Footnote Text` and `Footnote Reference` styles. At a footnote's first reference it writes `w:footnoteReference` and the note's paragraph (with `w:footnoteRef`, links included, bidi when the note is Arabic). Word then sets the note at the foot of the page and renumbers it while the document is edited.

- A marker that is not the next automatic number ("*", "†", "dagger") keeps the author's mark (`w:customMarkFollows`).
- Kept as before, so text is never dropped or doubled: a definition nobody refers to, a definition reached before its first reference, and a repeated reference (a superscript marker).
- The DOCX content ledger reads an automatic reference as its number, so "recall.1" still matches the source. The tests' DOCX text helper also reads the footnotes part.
- LibreOffice opens it and sets the notes at the foot of the page (tested). LibreOffice shows a custom mark twice in the note area ("xx"), because it adds the mark and also keeps the mark text Word writes there. The file follows Word's own form. Microsoft Word itself was not available.
- **OMML math was not started.**

## 5. QA backend without AGPL (F16)

`dynamic_pdf/qa/pdf_backend.py` is one small interface: page count, text, `text_dict()` and `rawdict()` in PyMuPDF's shapes, images, vector shapes, paint order, internal link targets, greyscale and RGB rasters, PNG. It is used by `qa/pdf_checks`, `content_preservation`, `visual_critique`, `media_checks`, `rasterize`, `contrast`, `intelligence/variants` and `intelligence/media_gate`.

- **PyMuPDF stays preferred when installed**, so results do not change. Its adapter returns PyMuPDF's own structures.
- **PDFium through `pypdfium2`** (BSD-3 and Apache-2.0, new extra `qa-permissive`) is used otherwise. Lines come from PDFium's character boxes, grouped at its line ends, at vertical breaks, at wide jumps such as the next table cell, and never at a combining mark. Fonts, sizes and colours come per character.
- `DYNAMIC_PDF_QA_BACKEND=pymupdf|pdfium` pins one.
- **Parity:** forced to PDFium, the QA, critique, media, composer, variants, art-direction, grammar, compositions and M14 suites pass (403 tests). `check_pdf` gives the same findings on all 11 fixtures. Page fill and the critique's ink grid differ by about 0.01 (anti-aliasing).
- **Speed:** QA, critique and media checks over the 11 fixtures take 0.68 s on PDFium and 0.37 s on PyMuPDF.
- **One known difference:** PyMuPDF joins neighbouring table cells into one line, and PDFium splits them. So `arabic_percent_position` warnings that came from a Latin "14.2%" cell next to an Arabic cell (152 on the Arabic stress report) do not appear on PDFium. They are warnings either way.
- **Left on PyMuPDF:** `qa/golden.py` (the maintainers' fingerprint CLI, whose fonts and outline must stay comparable with the stored goldens) and `tools/reference_analyzer` (a local development tool with its own extra). `tests/conftest.py` still requires PyMuPDF, so the suite itself needs it.

## Files

- New: `dynamic_pdf/qa/pdf_backend.py`, `dynamic_pdf/qa/contrast.py`, `dynamic_pdf/layout/tagging.py`, `dynamic_pdf/renderers/docx_footnotes.py`, `tests/test_m14_typography_a11y.py`.
- Changed: `fonts/manager.py` (CMap), `layout/factory.py` (hyphenation, tag propagation, table cells), `layout/engine.py` (tagging hooks), `intelligence/geometry.py` (leaf tagging), `qa/*` and `intelligence/{variants,media_gate}.py` (backend), `renderers/docx_{renderer,styles}.py` (footnotes, hyphenation), `schema/document.py` (`Meta.tagged`), `builder.py` (`meta(tagged=...)`), `pyproject.toml` (`qa-permissive` extra), `tests/conftest.py` (footnotes in the DOCX text).
