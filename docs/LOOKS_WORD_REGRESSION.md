# Eight looks: Arabic/bilingual Word regression

This check is independent of GitHub Actions and does not edit production code.
Its source baseline is PR #31 (merged on 2026-11-18); run against a local
checkout of the branch under review, not an older main branch.

## Setup

Use Python 3.10-3.13, preferably in an isolated virtual environment.
From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate   # On PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,qrcode]" -c constraints.txt
```

To make the optional rendering phase available, install LibreOffice Writer and
ensure `soffice` is on PATH. For Linux/WSL2, register the repository's bundled
font files with fontconfig before running the visual comparison; do not copy
or publish them with reports:

```bash
mkdir -p ~/.local/share/fonts/dpb-looks
cp dynamic_pdf/fonts/bundled/*.ttf ~/.local/share/fonts/dpb-looks/
fc-cache -f
soffice --version
```

The local font registration is needed to compare LibreOffice output fairly;
DOCX font embedding is separately checked in OOXML. Do not commit or distribute
installed font files as QA attachments.

## Tests

```bash
# Focused regression: eight looks x Arabic/bilingual, plus existing coverage.
python scripts/run_looks_local.py --out local-qa/looks

# Full pytest suite after fixing any focused failures.
python scripts/run_looks_local.py --full --out local-qa/full

# Optional real LibreOffice rendering and PDF vs DOCX contact sheets.
python scripts/run_looks_local.py --visual --out local-qa/visual

# Create the visual artifacts without running pytest again.
python scripts/run_looks_local.py --no-test --visual --out local-qa/visual
```

Exit code 0: the selected automated checks passed and (if requested) automatic
geometry checks found no errors. Exit code 1: tests or automatic geometry checks
failed. Exit code 2: the optional visual phase could not run. This is not a
Microsoft Word pass/fail decision.

The focused `tests/test_looks_word_regression.py` tests cover:

- All eight looks with an Arabic RTL document and a mixed-language LTR document.
- OOXML package integrity, embedded Arabic/Latin font parts and relationships.
- RTL paragraphs, Latin paragraphs in bilingual documents, real Word headings.
- Arabic-led (`bidiVisual`) and English-led table order, repeated headers,
  editable cell content, no exact row heights or `noWrap` settings.
- Long Arabic text preservation, common extractable numeric content in PDF and
  DOCX, live page fields, and `STYLEREF` referring to actual heading styles.

These are **structural** tests. Text-preservation and the absence of `noWrap`
**do not prove** that a line wrapped correctly on the page. Arabic text
extraction from PDFs can differ from the OOXML reading order; numeric anchors
are used for automatic cross-format checks rather than pretending full Arabic
text equivalence.

## Visual evidence

`--visual` builds, for each look and language:

- Native PDF, editable DOCX, LibreOffice-converted PDF.
- `*-comparison.png` with the first two pages of each renderer side by side.
- `visual-report.json` and `visual-report.md` listing page counts and
  automatic geometry findings for both renderers.

Inspect the *entire* PDFs, not only the first two pages. Differences in page
count, font metrics, decorative bands, line breaks, and whitespace are leads
for review, not automatic proof that the documents must be pixel-identical.
This script does not do a pixel-by-pixel comparison of unlike formats.

## Microsoft Word final acceptance (manual)

On a machine with Microsoft Word, open each of the 16 DOCX files in
`local-qa/visual`, ideally without pre-installing the look fonts. Confirm:

1. The intended Arabic and Latin faces render without fallback/missing glyphs;
   headings and body text remain editable.
2. RTL paragraphs read naturally; the table with Arabic headers has Arabic
   visual order while the English-led table keeps LTR order.
3. Arabic-Indic digits, percentages, punctuation and mixed Latin/numeric runs
   remain positioned correctly.
4. Long body paragraphs and table cells wrap with no overlap, row truncation,
   missing lines, or unexpected blank pages.
5. Covers, title blocks, heading decorations, live page numbers, repeating
   headers/footers, and last-page pagination remain intact.
6. Compare a Word-exported PDF with the native PDF visually. Record legitimate
   engine-driven differences instead of enforcing pixel parity.

Keep screenshots of each anomaly and record Word version, OS, look and language.
Do not call the change visually verified until the Word review is complete.

## Rollback and scope

The proposed patch adds only a regression test, local runner and this guide.
No renderer, theme, golden, CI workflow or production configuration changes.
Reverting these files restores the previous test surface. Branch review and
explicit approval are required before merging.