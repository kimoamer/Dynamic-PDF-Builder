# M7.5 AI art direction

An AI reviewer looked at all 1,064 reference pages, selected 39, drew 7 layout archetypes from them, and three of
those archetypes are now opt-in blocks in PDF and editable DOCX. Every example here is fictional (the invented Saltmere
Harbour Authority). No reference page, logo or artwork is used or committed.

**These are AI judgements, not human decisions.** Scores are opinions about visual quality, not measurements.
`human-curation.json` still holds human decisions only, and there are none.

* [`gallery/index.html`](gallery/index.html): before and after pages, PDF and LibreOffice-rendered DOCX. Open it locally.
* [`report.md`](report.md): per-example facts. [`results.json`](results.json): the same, machine-readable.
* [`ai-design-curation.json`](../../tools/reference_analyzer/ai-design-curation.json): selections, scores, rejections.
* [`layout-archetypes.json`](../../tools/reference_analyzer/layout-archetypes.json): archetypes and principles.

```bash
python benchmarks/m75/run.py OUT_DIR
python benchmarks/m75/default_output.py snapshot --root TREE OUT.json
python benchmarks/m75/default_output.py compare MAIN.json BRANCH.json
```

## What was reviewed

| How the page was seen | Pages |
|---|---|
| Full size (1,100 px wide) | 10 |
| Enlarged (about 516 px wide), not counting the 10 above | 73 |
| Contact sheet only (about 144 to 184 px wide) | 981 |
| Not viewed | 0 |

A contact sheet shows composition only: those 981 pages were seen, but their text and fine detail were not assessed.
Both Unilever reports were reviewed as separate documents. BI-04, BI-06 and BI-07 had no selected page.

## What was selected

39 pages from 10 documents, scored 1 to 5 on eight criteria. The highest means:

| Page | Kind | Mean |
|---|---|---|
| AR-02 p25 | Section opener | 4.75 |
| EN-01 p21 | Financial table | 4.71 |
| AR-01 p5 | Title page | 4.62 |
| AR-03 p8 | KPI page | 4.62 |
| BI-02 p19 | Bilingual text | 4.62 |
| BI-01 p4 | Bilingual table | 4.50 |

28 candidates were rejected with a reason. Most were near-duplicates of a selected page, depended on brand artwork, or
left a large part of the page unresolved.

## Archetypes

| Archetype | Status | Block |
|---|---|---|
| Asymmetric section opener | prototype, opt-in | `section_opener()` |
| Performance page | prototype, opt-in | `performance_page()` |
| Parallel ledger | prototype, opt-in | `parallel_ledger()` |
| Statement page | documented | none |
| Editorial sink | documented | none |
| Image and slab divider | documented | none |
| Figure matrix | documented | none |

Each prototype measures its content before drawing. If the content cannot fit, it falls back to plain blocks with a
warning and loses no text. Proportions are relative to the page, and nothing reads a reference at run time.

## Default output

The three blocks change nothing unless a document uses them. The correctness fixes do change existing output, and
`default_output.py` lists each change across 15 documents, plain and with `design()`:

| Result | Outputs |
|---|---|
| Identical to `main`: PDF text and pages, and DOCX body | 16 of 30 |
| DOCX body differs in `keepNext` only (5 English documents with `design()`) | 5 |
| PDF gains a page and DOCX gains `keepNext` (`chart_analytics_report` 7 to 8 with `design()`) | 1 |
| Arabic or bilingual DOCX fixes (8 outputs); `ar_annual_report` with `design()` also gains a PDF page, 20 to 21 | 8 |

The six English differences were checked by removing `keepNext`: each DOCX body is then identical to `main`. Plain
English output is unchanged. DOCX QA errors did not rise on any document, and render time did not rise (PDF 58.8 s to
39.5 s, DOCX 33.0 s to 27.1 s across the set, one run each on one machine).

## Fixes

* **Orphaned headings.** A short paragraph between a heading and its table or chart now stays with them. On the chart
  report, heading 1.2 no longer sits at the foot of a page with its chart on the next.
* **Garbled Arabic chart titles.** Matplotlib drew unshaped letters in a Latin face. Arabic chart text is now shaped and
  set in Amiri.
* **Arabic DOCX alignment.** `w:jc` means start and end in a right-to-left paragraph, so text meant for the right edge
  landed on the left. It is now mirrored just before saving.
* **Arabic DOCX size and weight.** Arabic text reads `w:szCs` and `w:bCs`, which were never set.
* **Arabic DOCX lists and subtitles.** List labels stay inside the margin, and the Subtitle style's slant and tracking
  are cancelled for Arabic text.
* **DOCX columns.** A closing paragraph stops columns at the end of a document adding a blank page.
* **Page fill in QA.** The measure ignored charts drawn as vectors, so a page holding a half-page chart read as 5% full.
  It now counts them.
* **Speed.** The Arabic reshaper re-read its configuration for every character. Caching it made the slowest example
  about five times faster.

## Limitations

* No person has reviewed any of this, and Microsoft Word itself was not tested: DOCX pages were rendered with
  LibreOffice. The opener's strip uses a text box, which needs Word 2010 or later.
* The opener strip holds a chapter list only. The image version seen in the references is not built.
* LibreOffice shifts a right-to-left ledger table about 6 pt to the left.
* Keeping exhibits with their headings can add a page and leave space at the foot of the one before. In a chart-heavy
  stress document, two pages end about half full. `compose("smart")` still packs those charts more tightly.
* On `ar_annual_report` with the Arabic recipe, a heading, list and paragraph still precede a table on the next page.
  The heading has content under it, so it is not stranded, but the table is apart from it.
* `bilingual_board_report` with the proposed Arabic / Bilingual recipe runs to 4 DOCX pages against 3 in PDF: one list
  item spills. The default design gives 3 and 3.
