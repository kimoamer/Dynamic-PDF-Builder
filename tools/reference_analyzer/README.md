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
  and count once when patterns compute support.
* Reviewed metadata (licence, provenance) is read from `05-Reviewed/` inside the input folder or next to
  it. Supported: `*.json` (object, list, or `{"documents": [...]}`), `*.csv` (header row), `*.md`/`*.yaml`/
  `*.txt` (flat `key: value` lines). A record matches a PDF by `sha256`, then `file`/`filename`/`path`, then
  a sidecar named after the PDF stem. Recognised keys: licence — `license`, `licence`, `license_status`,
  `reuse`, `reuse_status`, `rights`, `usage`; provenance — `source`, `provenance`, `url`, `publisher`,
  `origin`, `downloaded_from`, `obtained`. Missing values are reported as `unknown`, never guessed.

## Outputs

| file | content |
|---|---|
| `reference-catalog.json` | per file: path (relative), SHA-256, bytes, status, page count, page sizes, PDF metadata, `/PageLayout`, licence/reuse, provenance, duplicates; tool versions and dependency licences |
| `design-features.json` | per document: summary (body size, heading hierarchy, leading, margins, running headers/footers, facing pages, spreads, columns, alignment, scripts, accent colours, rules, tables, images, vector graphics), a recipe candidate mapped to `DesignRecipe` fields with the nearest existing recipe, and per-page measurements |
| `design-patterns.json` | recurring patterns (≥ `--min-support` distinct documents) and single-document observations, each with evidence pages — all `inferred`, `proposal — needs human review` |
| `warnings.json` | unreadable/encrypted/empty files, scans, broken text extraction, Arabic presentation forms, spreads, ambiguous alignment, duplicates, missing licence/metadata, sampled previews (page-level warnings grouped per code with their pages) |
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
| image placement, size, aspect, effective DPI | measured | high | |
| text margins (all text) | measured | high | union of extracted line boxes |
| body margins | measured + inferred | high/medium | excludes detected running headers/footers |
| line spacing at body size | measured | high with ≥3 samples | consecutive same-size baselines in a block |
| body size | inferred | high | character-weighted most common size |
| heading hierarchy | inferred | medium | size ≥1.15× body, ≤3 lines, ≥2 occurrences |
| columns, alignment | inferred | per value | 2-line blocks only report the flush edge |
| running headers/footers | inferred | medium | short lines in top/bottom 12 % repeated on ≥50 % of pages |
| facing pages (mirrored margins), spreads | inferred | medium | spreads: landscape ~2 pages wide, no text across the centre |
| tables | inferred | medium/low | ruled tables only (`find_tables(strategy="lines")`); padding = cell edge to text |
| vector graphics (possible charts) | inferred | low | clusters of ≥12 drawing paths |
| captions | inferred | medium | smaller-than-body text within 24 pt above/below an image |
| extracted *text content* of Arabic | — | low | often presentation forms in visual order; geometry and fonts are still measured |
| scanned pages | — | none | flagged; typography not measurable without OCR (not performed) |

Nothing in the output is a judgement of aesthetic quality.

## Verification

* **Ground truth by construction** (`sample_corpus.py`, tests in `tests/test_reference_analyzer.py`): A4 size,
  72 pt side margins, 10/14 pt body (1.4×), 18 pt H1, accent colour, three accent rules, a 7×4 ruled table
  (columns 150/100/100/101.3 pt, header fill, banded rows, 6 pt padding) and a 300×150 pt image are all
  recovered exactly; mirrored facing margins (90/50 pt), two spreads, a scanned page, Arabic RTL and bilingual
  pages, corrupt/zero-byte files, exact duplicates, and a 12-page/4-page related pair are detected as such.
* **Manual inspection** of the overlay previews (table, image, Arabic and spread pages) confirmed that the
  drawn boxes coincide with the visible content.
* **Scale**: a 228-page mixed document (tables, charts, Arabic) analyses in ~54 s with ~380 MB peak RSS on
  one CPU; `design-features.json` ≈ 3.6 MB.

`examples/sample-output/` is a full run on the synthetic sample corpus
(`python -m tools.reference_analyzer.sample_corpus OUT` regenerates it).

## Limits

Unruled tables are not detected; charts are only flagged as vector regions; OCR is not performed; text
inside images is not measured; leading needs ≥3 consecutive same-size lines; Arabic text content (not
geometry) can be in visual order. Spreads stored as two separate portrait pages are reported through
mirrored margins, not as spreads.

## Licences and reuse

PyMuPDF — AGPL-3.0 or Artifex commercial (optional, local tooling; not a runtime dependency). Pillow — MIT-CMU
(already a core dependency). Reference PDFs, previews and extracted content stay on the machine running the
tool. Patterns describe roles and ranges; do not copy commercial branding, artwork or layouts into
distributed runtime assets. Do not commit third-party reference PDFs or their previews unless their licence
allows it.

## Human review

Open `analysis-report.html`, check each recurring pattern against its evidence pages, and record decisions
(accept / reject / needs more evidence) before any value is used in `dynamic_pdf/design/recipes.py`.
