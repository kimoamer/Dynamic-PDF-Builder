# Real-corpus review (M7.3)

The analyzer was run on 13 reference PDFs (1,064 pages) kept outside this repository, and its output was
compared with rendered pages. This file holds measurements and page numbers only: no page images, no
extracted text, no colour values. A verdict is a statement about the evidence for a pattern, not about the
quality of a design.

Run: `python -m tools.reference_analyzer analyze --input <references> --output <analysis>`, CPU only, offline,
about 6 minutes. 13 of 13 analysed, 20 recurring patterns, 3 single-document observations. All 13 PDFs matched both
reviewed records (`observed-features.json`, `review-index.csv`), with no SHA-256 or page-count conflict. The
index holds a reviewer's `rights_status` for all 13. That is a note on permitted use, not a verified legal
licence, so since M7.4 `license` stays `unknown` and warns on all 13; provenance stays `unknown` because the
reviewed data has no provenance key.

The verdicts below are also held in [`pattern_review.json`](pattern_review.json), linked to doc ids, SHA-256
values and pages. Run `python -m tools.reference_analyzer review` to check that the two agree.

**The two Unilever reports are independent records**: EN-01 (`ref-db25596332d2`, 224 pages) and EN-01-1
(`ref-0b2bf0ebc355`, 32 pages) have different document ids and SHA-256 values, the right page counts, no
duplicate flag and no template-family flag. They are one publisher, so a pattern resting on those two alone is
marked below.

## Per document

Sizes in pt. Margins are top/bottom/left/right. "Median" is where text stops on a typical page; "frame" is the
10th percentile per side, the frame nearly-full pages reach. Every document has status `ok`.

| Doc | Pages | Body (confidence, share) | Leading | Margins median | Margins frame | Heading sizes | Columns (pages) | Tables / boxes | Scripts (pages) |
|---|---:|---|---:|---|---|---|---|---:|---|
| EN-01-1 | 32 | 8 (high, .70) | 1.20 | 75.0/113.5/42.5/41.7 | 74.3/50.4/42.5/40.6 | 15, 11, 10 | 1: 18, 2: 13 | 29 / 8 | Latin 32 |
| EN-01 | 224 | 8 (medium, .42) | 1.20 | 74.8/117.3/42.5/41.4 | 72.3/52.1/42.5/40.2 | 24, 18, 17, 16, 15, 14 | 1: 112, 2: 61, 3: 2 | 142 / 24 | Latin 224 |
| EN-02 | 162 | 12.5 (high, .51) | 1.12 | 51.4/70.2/54.0/52.6 | 47.5/34.7/54.0/50.2 | 28, 25, 22, 20, 19, 17 | 1: 42, 2: 66 | 50 / 9 | Latin 162 |
| EN-03 | 9 | 10 (high, .82) | 1.40 | 95.4/80.3/36.0/34.6 | 95.4/79.3/36.0/33.2 | none found | 1: 7 | 2 / 0 | Latin 9 |
| AR-01 | 42 | 10.5 (high, .71) | 1.33 | 86.7/59.5/59.0/59.0 | 86.7/36.0/55.9/57.5 | 25, 15.5, 12.5 | 1: 36 | 20 / 12 | Arabic 37, bilingual 1, Latin 2, none 2 |
| AR-02 | 404 | 9.5 (high, .64) | 1.58 | 103.4/55.9/57.1/56.7 | 97.7/48.7/54.2/56.0 | 26, 22, 17, 16, 15, 13 | 1: 88, 2: 192 | 85 / 1 | Arabic 335, bilingual 30, Latin 22, none 17 |
| AR-03 | 48 | 12 (high, .77) | 1.17 | 51.8/86.2/58.2/45.0 | 38.7/44.3/34.2/35.6 | 43, 39, 31, 27.5, 23, 18 | 1: 7, 2: 37 | 11 / 27 | Arabic 47, bilingual 1 |
| BI-01 | 45 | 10 (high, .54) | 1.23 | 111.6/92.5/60.0/84.3 | 38.9/18.6/41.4/41.1 | 28 | 1: 26, 2: 4 | 30 / 32 | bilingual 13, Latin 32 |
| BI-02 | 57 | 9 (low, .58) | 1.15 | 68.6/75.7/54.8/77.1 | 57.4/9.0/40.3/38.6 | 21, 16, 14, 13, 12, 11 | 1: 11, 2: 2 | 22 / 9 | Arabic 15, bilingual 30, Latin 12 |
| BI-04 | 17 | 15 (high, .77) | 1.48 | 58.2/79.3/53.3/56.1 | 57.4/45.5/39.1/41.9 | none found | 1: 13 | 3 / 17 | undetermined 16, Latin 1 |
| BI-05 | 8 | 10.5 (medium, .29) | 1.72 | 24.0/62.7/29.6/37.9 | 10.2/11.7/23.3/36.4 | 22.5, 19.5, 16.5, 13.5 | 1: 5 | 0 / 0 | Arabic 4, Latin 4 |
| BI-06 | 8 | 10.5 (medium, .28) | n/a | 24.0/59.5/29.6/37.9 | 10.2/7.0/23.3/36.4 | 22.5, 19.5, 16.5, 13.5 | 1: 4 | 0 / 0 | Arabic 4, Latin 4 |
| BI-07 | 8 | 10.5 (medium, .31) | n/a | 24.0/62.8/29.6/37.9 | 10.2/7.0/23.3/36.4 | 22.5, 19.5, 13.5 | 1: 4, 2: 1 | 0 / 0 | Arabic 4, Latin 4 |

Facing pages: AR-01, AR-03 and BI-04. AR-03 is stored as 48 spread sheets, measured per half.

Warnings per document (pages affected):

| Doc | Warnings |
|---|---|
| EN-01-1 | sampled previews only |
| EN-01 | full-page image with text layer 25, image-only page 1 |
| EN-02 | fragmented images 4, full-page image with text layer 11 |
| EN-03 | sampled previews only |
| AR-01 | Arabic presentation forms 3, fragmented images 1, full-page image with text layer 2 |
| AR-02 | Arabic presentation forms 5, broken text extraction 8, image-only page 17 |
| AR-03 | broken text extraction 43, full-page image with text layer 3, spread 48 |
| BI-01 | Arabic presentation forms 1, fragmented images 1, full-page image with text layer 1 |
| BI-02 | Arabic presentation forms 6, fragmented images 28, full-page image with text layer 2, image-only page 1, `mixed_design_system` |
| BI-04 | broken text extraction 16, fragmented images 1 |
| BI-05, BI-06, BI-07 | full-page image with text layer 2 each, `possible_template_family` (counted once) |

## How the output was checked

Each document's report previews were viewed with their overlays (90 preview images, all 13 documents). Single pages
were also rendered locally with PyMuPDF and overlaid with the extracted blocks, tables, images and margins:

* margins, running elements, columns: EN-01 p40, p165; EN-01-1 p13; EN-02 p25; EN-03 p3; AR-01 p12; AR-02 p110,
  p252; AR-03 p3, p19; BI-01 p3; BI-04 p7; BI-05 p2
* tables and fills: EN-01 p58, p114, p143, p146, p165; AR-02 p60; BI-01 p3
* headings: AR-02 p372; AR-03 p4; EN-02 p18; AR-01 p7; BI-02 p19
* captions: EN-02 p3, p21, p46; EN-03 p3; AR-01 p17; AR-02 p50, p60, p81, p142; BI-01 p27; BI-05 p7
* RTL and bilingual layout: BI-01 p3 (parallel columns), BI-02 p3-6, AR-02 p110, BI-05 p5-8

Leading was confirmed from baselines on AR-02 p110 (about 15.3 pt on 9.5 pt text). The other leading values are
measured from baselines and were not re-derived by hand.

## Defects found and fixed

Each has a synthetic regression test in `tests/test_reference_analyzer.py`. Seventeen of the tests written in
the first pass fail on the previous code; one more guards a fix made in the same work (first body lines are not
running elements), and a last one covers caption evidence pages.

| # | Defect on real pages | Fix |
|---|---|---|
| 1 | Licence `unknown` on all 13: only the first matching record was read, and `rights_status` was not a known key | merge every matching reviewed record, read `rights_status`, `rights_evidence`, `original_relative_path`; report SHA-256 and page-count conflicts |
| 2 | PyMuPDF 2.1 `find_tables` ran an ONNX layout model by default: seconds per page, and it dropped ruled tables | layout model off |
| 3 | Running elements missed where they change by section or alternate left and right | match by position and size, on all, odd or even pages; lines in the body flow excluded |
| 4 | Columns under-counted (multi-column body: 2 documents before, 5 now) | sweep across the text height, tables and running elements excluded |
| 5 | Garbled text layers classified as a script | mojibake and U+FFFD detection, script `undetermined` with a font hint |
| 6 | Tiled images counted as hundreds of pictures (AR-01: 1,827 stored, 8 placements) | touching images merged, pieces counted as `fragments` |
| 7 | Spreads treated as wide single pages, which distorted margins and columns | spreads recognised by sheet size and centre crossing, measured per half |
| 8 | One-row boxes counted as tables; padding, header and banding read wrongly | tables need 2×2 cells, the rest are `ruled_boxes`; fills read at mid-row; padding is the nearer side inset |
| 9 | Cover and opener type counted as heading levels (heading-ramp >2.6× had 7 documents, 4 now) | text pages only, up to 5× body; the rest go to `display_sizes` |
| 10 | Template refills and a compilation counted as independent support | `possible_template_family` counts once; `mixed_design_system` stays as evidence but supports nothing |
| 11 | A few picture pages made a document read as scanned | `image_only_page` when those pages are a minority |
| 12 | Credits, band text and small pictures counted as captions (below: 10 documents, now 4; above: 9, now 5) | bleeds, bands, pictures under 40 pt tall and running lines skipped |
| 13 | Leading lost on justified or fragmented lines | line blocks coalesced, ±0.25 pt size tolerance, sample-weighted |
| 14 | Rotated text and off-page text gave negative margins | rotated text sets no margin, margins clamp at 0 |
| 15 | The median margin described short pages, not the text frame | `margins_body_frame` added; it feeds the recipe candidate |
| 16 | Caption patterns cited every page with a picture, so their evidence could not be checked | they cite the pages with the caption |

## Pattern verdicts

Evidence is `doc pages`. Support counts independent documents; template families count once, and compilations
(BI-02) do not count.

### Accept

| Pattern | Support | Finding | Evidence |
|---|---:|---|---|
| Leading ≤1.25× | 5 | 1.12-1.23× across five sources | EN-01-1 p1-5; EN-01 p1, 3-6; EN-02 p2-6; AR-03 p1-5; BI-01 p2-6 |
| Leading 1.26-1.40× | 2 | 1.33× and 1.40×, one Arabic and one Latin source | EN-03 p1-5; AR-01 p6-10 |
| Multi-column body | 5 | two columns on at least 30 % of text pages, counting pages that could not be classified: EN-01-1 .41, EN-01 .32, EN-02 .45, AR-02 .52, AR-03 .82 (M7.3 left those pages out and read .42, .36, .61, .69, .84) | EN-01-1 p2-6; EN-01 p9, 11, 14, 16, 19; EN-02 p4, 8, 20, 25, 26; AR-02 p4-8; AR-03 p2, 4-7 |
| Body size 9.5-10.4 pt | 3 | 9.5-10 pt, high confidence on all three | EN-03 p1-5; AR-02 p2-6; BI-01 p2-6 |
| Body size ≥11.5 pt, narrowed to 12-12.5 pt | 2 | BI-04 at 15 pt is an outlier with an unreliable text layer, left out | EN-02 p2-6; AR-03 p1-5 |
| H1 over 2.6× body | 4 | 2.74-3.58×; headings confirmed on rendered pages | EN-01 p6-13; AR-02 p372, 381, 393; AR-03 p2-12; BI-01 p26, 27 |
| Facing pages | 3 | inner margin wider than outer, mirrored | AR-01 p6-10; AR-03 p1-5; BI-04 p1-5 |
| Arabic RTL body | 4 | block alignment measured per document | AR-01 p3-7; AR-02 p1-5; AR-03 p2-6; BI-05 to BI-07 p5-8 |
| Bilingual pages, at page level | 4 | a real layout in BI-01 and BI-02; single incidental pages in AR-01 and AR-03 | BI-01 p1-5; BI-02 p3-6, 19; AR-02 p25, 44, 47, 65, 86; AR-01 p1; AR-03 p1 |
| One to three accent colours, as a role | 6 | a consistent accent is visible on the previews; only the role is proposed, no colour is copied | EN-01-1 p2-6; EN-02 p3-9; AR-03 p1-5; BI-01 p2-6; BI-05, BI-07 p1-5 |

### Reject

| Pattern | Support | Why | Evidence |
|---|---:|---|---|
| Caption above figure | 5 | One real case of the four documents checked. The rest are a table source note above a photo, section rows above a photo, and text beside a signature stamp | real: AR-01 p17. False: AR-02 p60, p81; BI-05 p7; BI-01 p27. Not checked: EN-02 p42, 47 |

### Needs More Evidence

| Pattern | Support | What is missing | Evidence |
|---|---:|---|---|
| Caption below figure | 4 | Two documents confirmed, two false | real: EN-02 p21; EN-03 p3. False: AR-02 p50 (side box); BI-01 p27 (stamp) |
| Table padding | 9 | The range 1.9-15.2 pt is too wide to be a rule, and the top end comes from ruled boxes | EN-01 p21, 22; EN-02 p2, 7; EN-03 p2, 6; BI-04 p10-12 |
| Side margins 13-17 mm | 4 | The bucket follows the smaller side: left reaches 67.4 pt (about 24 mm) on facing pages; two of four are one publisher | EN-01-1 p1-5; EN-01 p1, 3-6; AR-03 p1-5; BI-04 p1-5 |
| Side margins 18-22 mm | 4 | Same problem: left 54-105.4 pt, right 52.6-84.3 pt; BI-01 mixes two page formats | EN-02 p2-6; AR-01 p6-10; AR-02 p2-6; BI-01 p2-6 |
| Side margins ≤12 mm | 2 | One paper and one fictional template family | EN-03 p1-5; BI-05 to BI-07 p1-5 |
| Body size 10.5-11.4 pt | 2 | One real document; in the family body text is under a third of the characters | AR-01 p6-10; BI-05 to BI-07 p1-5 |
| Body size ≤9.4 pt | 2 | Both supporters are one publisher | EN-01-1 p1-5; EN-01 p1, 3-6 |
| H1 2.0-2.6× body | 3 | One supporter is the family, and the cited heading on EN-02 p18 could not be told apart on the render; AR-01 p7 is a contents title | EN-02 p2, 18, 84, 111; AR-01 p7-13; BI-05 to BI-07 p4, 8 |
| Leading over 1.55× | 2 | AR-02 is confirmed at 1.58×; BI-05 has few samples | AR-02 p2-6; BI-05 p1-5 |
| H1 1.5-2.0× body (observation) | 1 | One document | EN-01-1 p7, 8, 10, 11 |
| Leading 1.41-1.55× (observation) | 1 | One document, unreliable text layer | BI-04 p1-5 |
| Spreads (observation) | 1 | One document | AR-03 p1-5 |

## Remaining limitations

* Caption detection does not know what the text says. Treat its counts as candidates.
* Ruled diagrams can read as tables: an organisation chart (EN-01 p58) and a bar chart (EN-01 p114) gave false
  tables with false header fills. EN-01's header-fill share is small (.01) but not zero.
* Tables ruled with horizontal lines only and unruled tables are missed, because the layout model is off.
* Same-size bold headings are not detected (EN-03 and most of BI-01), so "none found" is not "no headings".
* Text set as images is not measured (BI-02 p3, p27, p56).
* AR-03 and BI-04 text layers are unreliable: sizes and geometry are usable, text content and script are not.
* BI-02 is a compilation and BI-01 mixes A4 and letter pages, so one body size or margin set describes neither.
* A spread of two A5 pages cannot be told from an A4 landscape page. Template families need equal page counts.
* Reviewed metadata is only matched, not cross-checked against the printed cover or printed page numbers: the
  year in EN-02's metadata title differs from its cover, and BI-01 prints a numbering that differs from its 45
  PDF pages. Neither is detected automatically.
* Provenance is `unknown` for all 13. The inspiration folder holds link files only, reported as unsupported.
* PyMuPDF 2.1 pulls in onnxruntime as a dependency of its own, even though the analyzer no longer uses it.
