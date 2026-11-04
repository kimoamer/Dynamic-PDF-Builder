# Reference analyzer

Offline, CPU-only measurement of professional PDF design references. It lives outside the `dynamic_pdf`
runtime: the library never imports it, the wheel does not include it (`packages.find` → `dynamic_pdf*`), and
rendering cost, import time and core dependencies are unchanged.

```bash
pip install pymupdf            # or: pip install -e ".[analyzer]"  (PyMuPDF is AGPL-3.0 — local tool only)
python -m tools.reference_analyzer analyze --input "PATH_TO_REFERENCES" --output "PATH_TO_RESULTS"
```

Options: `--reviewed DIR` (metadata folder, repeatable), `--max-previews N` (preview pages per document;
every page is measured), `--min-support N` (distinct documents needed for a recurring pattern, default 2),
`--no-previews`. No network access is used; nothing is uploaded. Output is byte-identical for identical input.

## Input

* Every `*.pdf` under the input folder (recursive). **Each file is its own record** keyed by
  `doc_id = ref-<first 12 hex of SHA-256>` — related editions (e.g. a 224-page report and its 32-page
  summary) are never merged. Byte-identical copies stay separate records, are flagged `duplicate_exact`,
  and count once when patterns compute support. So do refills of one template (same page count and formats,
  body size, fonts, top and side margins: `possible_template_family`). A compilation (3 or more page formats
  each on ≥10 % of the pages: `mixed_design_system`) stays in the evidence but supports no pattern.
* Reviewed metadata (rights notes, licence, provenance) is read from `05-Reviewed/` inside the input folder or next to
  it. Supported: `*.json` (object, list, or `{"documents": [...]}`), `*.csv` (header row), `*.md`/`*.yaml`/
  `*.txt` (flat `key: value` lines). A record matches a PDF by `sha256`, by `file`/`filename`/`path`/
  `original_relative_path` (a path must equal the relative path, a bare name the file name), or as a sidecar
  named after the PDF stem. All records matching a PDF are merged, first non-empty value wins; per-page dumps
  are left out of the catalogue. A record naming the file with another SHA-256 is ignored
  (`reviewed_sha256_mismatch`); a page count that disagrees with the PDF is reported
  (`reviewed_page_count_mismatch`). Recognised keys: rights note — `rights_status`, `reuse`, `reuse_status`,
  `rights`, `usage` (`rights_evidence` is kept beside it); legal licence — `license`, `licence`,
  `license_status`; provenance — `source`, `provenance`, `url`, `publisher`, `origin`, `downloaded_from`,
  `obtained`. These stay three separate facts: a reviewer's rights note never becomes a licence, and a licence
  or provenance counts as verified only when the record says `license_verified` or `provenance_verified`.
  Missing values are reported as `unknown`, never guessed.

## Outputs

| file | content |
|---|---|
| `reference-catalog.json` | per file: path (relative), SHA-256, bytes, status, page count, page sizes, PDF metadata, `/PageLayout`, rights status, licence, provenance, duplicates; tool versions and dependency licences |
| `design-features.json` | per document: summary (body size and its share, design uniformity, heading hierarchy, display sizes, leading, margins, running headers/footers, facing pages, spreads, columns, alignment, scripts, accent colours, rules, tables, images, vector graphics), a recipe candidate mapped to `DesignRecipe` fields with the nearest existing recipe, and per-page measurements |
| `design-patterns.json` | recurring patterns (≥ `--min-support` distinct documents) and single-document observations, each with evidence pages — all `inferred`, `proposal — needs human review` |
| `warnings.json` | unreadable/encrypted/empty files, scans, image-only pages, fragmented images, broken text extraction, Arabic presentation forms, spreads, ambiguous alignment, duplicates, template families, compilations, missing or conflicting licence/metadata, sampled previews (page-level warnings grouped per code with their pages) |
| `analysis-report.html` | offline report: catalogue, measured values with method/confidence, page previews with overlays, patterns with links to evidence pages, warnings |

Every value is `{"value", "unit", "method", "confidence", "basis"}`. Units are PDF points (1/72 in; mm
where stated); coordinates use a top-left origin.

## What can be trusted

| measurement | basis | confidence | notes |
|---|---|---|---|
| page size, orientation, rotation, page count, SHA-256, PDF metadata, `/PageLayout` | measured | high | read from the file |
| font names and sizes per span, character counts | measured | high | names are as embedded (subset prefix removed) |
| weight | measured / inferred | medium | from the font name; the span *bold flag* is used only when the name has no weight |
| text colours, filled-shape colours, accent colours | measured | high | accent = saturated colour on ≥2 pages (≥20 %) |
| image placement, size, aspect, effective DPI | measured | high | touching images are one placement (`fragments` = stored pieces; merged placements have no DPI) |
| text margins (all text) | measured | high | union of extracted horizontal line boxes; rotated text sets no margin; never negative |
| body margins | measured + inferred | high/medium | excludes detected running headers/footers. The median says where text stops on a typical page; `margins_body_frame` (10th percentile per side) is the frame nearly-full pages reach and feeds the recipe candidate |
| line spacing at body size | measured | high with ≥3 pages | consecutive same-size baselines in a block, sizes within 0.25 pt of the body bin |
| body size | inferred | by share of characters | character-weighted most common size; high ≥50 %, medium ≥25 %, low below or on a compilation |
| heading hierarchy | inferred | medium | size ≥1.15× body, ≤3 lines, ≥2 occurrences, on text pages (≥200 characters); covers, openers, numerals and type over 5× body go to `display_sizes` |
| columns, alignment | inferred | per value | columns: most side-by-side multi-line body blocks over ≥25 % of the text height, tables and running elements excluded. 2-line blocks only report the flush edge. The multi-column pattern's share is of every text page, so pages that could not be classified count against it |
| running headers/footers | inferred | medium | lines in top/bottom 12 % repeated on ≥50 % of all, odd or even pages, by text or by position and size; lines with text at line distance towards the page centre belong to the body flow |
| facing pages (mirrored margins), spreads | inferred | medium | spreads: sheets ≥900 pt wide, ~2 pages, text on both halves, ≤5 % of lines across the centre, plus sheets of that size when half of them qualify; margins and columns are then measured per half (right half = odd, left half = even) |
| tables | inferred | medium/low | ruled tables of ≥2×2 cells (`find_tables(strategy="lines")`, layout model off); 1-row or 1-column grids are `ruled_boxes`; padding = nearer of the left/right cell edge to text; fills read at mid-row, whole-row or cell by cell, near-white ignored |
| vector graphics (possible charts) | inferred | low | clusters of ≥12 drawing paths |
| captions | inferred | low in practice | smaller-than-body text within 24 pt above/below a picture ≥40 pt tall; bleeds, bands and running elements excluded. The rule has no idea what the text says: table source notes above a picture, side boxes and text beside a stamp also match, so check the cited pages |
| extracted *text content* of Arabic | — | low | often presentation forms in visual order; geometry and fonts are still measured |
| garbled text layers | — | low | ≥30 % accented Latin letters, or >0.5 % U+FFFD: `broken_text_extraction`, script `undetermined` (`font_hint` from font names); sizes and geometry are still measured |
| scanned pages | — | none | flagged when most of a document is full-page images without text, otherwise `image_only_page`; typography not measurable without OCR (not performed) |

Nothing in the output is a judgement of aesthetic quality.

## Verification

* **Ground truth by construction** (`sample_corpus.py`, tests in `tests/test_reference_analyzer.py`): A4 size,
  72 pt side margins, 10/14 pt body (1.4×), 18 pt H1, accent colour, three accent rules, a 7×4 ruled table
  (columns 150/100/100/101.3 pt, header fill, banded rows, 6 pt padding) and a 300×150 pt image are all
  recovered exactly; mirrored facing margins (90/50 pt), two spreads, a scanned page, Arabic RTL and bilingual
  pages, corrupt/zero-byte files, exact duplicates, and a 12-page/4-page related pair are detected as such.
  Defects found on real references are reproduced by synthetic fixtures: section-dependent heads, three-piece
  footers, spread sheets, A4 landscape, garbled text layers, tiled images, photo openers, thin filled rules,
  cell-by-cell fills, template refills, compilations, and split reviewed metadata.
* **Manual inspection** of the overlay previews (table, image, Arabic and spread pages) confirmed that the
  drawn boxes coincide with the visible content.
* **Real corpus**: 13 reference PDFs (1,064 pages) reviewed against rendered pages, see
  [`REAL_CORPUS_REVIEW.md`](REAL_CORPUS_REVIEW.md).
* **Scale**: a 228-page mixed document (tables, charts, Arabic) analyses in ~54 s with ~380 MB peak RSS on
  one CPU; `design-features.json` ≈ 3.6 MB.

`examples/sample-output/` is a full run on the synthetic sample corpus
(`python -m tools.reference_analyzer.sample_corpus OUT` regenerates it).

## Limits

Ruled diagrams can read as tables (an organisation chart, the gridlines and bars of a chart).
Unruled tables, including tables ruled with horizontal lines only, are not detected: PyMuPDF ≥2.1 can find
some with its bundled ONNX layout model, but that model also drops ruled tables, costs seconds per page and
is switched off here. Same-size bold headings are not detected (heading levels come from size). Charts are
only flagged as vector regions; OCR is not performed; text inside images is not measured. Arabic text
content (not geometry) can be in visual order. Spreads stored as two separate portrait pages are reported
through mirrored margins, not as spreads, and a spread of two A5 pages is indistinguishable from an A4
landscape page, so it stays a single page. Template families are recognised only when their page counts
match.

## Licences and reuse

PyMuPDF — AGPL-3.0 or Artifex commercial (optional, local tooling; not a runtime dependency). Pillow — MIT-CMU
(already a core dependency). Reference PDFs, previews and extracted content stay on the machine running the
tool. Patterns describe roles and ranges; do not copy commercial branding, artwork or layouts into
distributed runtime assets. Do not commit third-party reference PDFs or their previews unless their licence
allows it.

## Human review

Open `analysis-report.html`, check each recurring pattern against its evidence pages, and record decisions
(accept / reject / needs more evidence) before any value is used in `dynamic_pdf/design/recipes.py`.

Decisions live in [`pattern_review.json`](pattern_review.json), linked to documents by doc id and SHA-256 and
to pages by role (`supports`, `contradicts`, `unchecked`). An accepted pattern must say where it applies
(`applies_to`); frequency alone is not accepted as a reason. `REAL_CORPUS_REVIEW.md` is the readable form.

```bash
python -m tools.reference_analyzer review
python -m tools.reference_analyzer review --patterns RESULTS/design-patterns.json
```

The first checks the file against itself and `REAL_CORPUS_REVIEW.md`, the second also against a run. Only ids
accepted here may be cited by `EVIDENCE_RECIPES` in `dynamic_pdf/design/recipes.py`; a test enforces it.

## Visual atlas

`analyze` measures geometry and previews a few pages per document. The atlas shows
every page, finds the visually distinct ones, and records what a human thinks of them.

```bash
python -m tools.reference_analyzer atlas --input REFS --output OUT
python -m tools.reference_analyzer atlas-serve --output OUT      # http://127.0.0.1:8765/
python -m tools.reference_analyzer curation OUT/human-curation.json
```

`OUT` must be outside any git repository: the command refuses a folder inside one,
because the atlas holds images of the references.

| File | Holds | Written by |
|---|---|---|
| `visual-atlas/index.html` | Gallery of all pages; also opens straight from disk | tool |
| `visual-page-index.json` | Page descriptors and provenance, no extracted text | tool |
| `visual-shortlist.json` | Diverse candidates, each with its reasons | tool |
| `human-curation.json` | Decisions, pins, ratings and notes | reviewers only |

**Labels describe composition.** Each carries its measurement and a confidence, and
some are weak by design (`callout`, `data_story`, a `pull_quote` without quotation
marks). Labels help you browse; they are not findings.

**Distinctiveness is not quality.** It ranks how far a page sits from its nearest
neighbours, in the corpus and in its document. A strange page ranks high.

**Reviewing.** Run `atlas-serve` so decisions save straight to `human-curation.json`.
Enter your name, then open any page: `a` accept, `r` reject, `n` needs review, `p` pin,
`s` spread, `o` measurements, arrow keys to move. Opened from disk, decisions stay in
that browser until you use Export; copy the exported file over `human-curation.json`.

Decisions are keyed by document SHA-256 and page number. Accepted and pinned pages
stay in the shortlist on every rerun, rejected pages are not proposed again but stay
in the atlas, and decisions for pages that left the corpus are reported and kept.

**Rerunning is cheap.** Pixels and measurements are cached per document SHA-256, and
labels, relations and the shortlist are recomputed from the cache. Bump `VERSION` in
`atlas.py` only when a measurement changes.

[`VISUAL_ATLAS_REVIEW.md`](VISUAL_ATLAS_REVIEW.md) records what the atlas found in the real corpus, which labels
are weak, and what remains unverified.

## AI art direction

| File | Holds | Written by |
|---|---|---|
| `ai-design-curation.json` | 39 selected pages with scores and reasons, rejected candidates, what was viewed and how closely | AI reviewer |
| `layout-archetypes.json` | 7 archetypes and 8 design principles drawn from the selected pages | AI reviewer |

**These are AI judgements, not human decisions.** Both name their reviewer and set `human_approved: false`.
`ai_curation.validate` refuses a record that claims otherwise, and `curation.py` refuses to load either one as
`human-curation.json`. Nothing in the atlas or the runtime reads them.

The records hold page IDs, hashes and written notes only: no page images, no extracted text. Scores are opinions about
visual quality and are not measurements. Each page records how it was seen: `full_size`, `enlarged` or
`contact_sheet`.
