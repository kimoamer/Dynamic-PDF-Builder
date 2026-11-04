# Visual atlas review (M7.5, PR A)

The atlas was built from the 13 reference PDFs (1,064 pages) kept outside this repository, and its labels were
checked against rendered pages. This file holds counts and page numbers only: no page images, no extracted text.
A label describes composition. Nothing here says a page is good. Human decisions live in `human-curation.json`, and
there are none yet. [`ai-design-curation.json`](ai-design-curation.json) records a separate AI review, which is not a
human decision.

Run: `python -m tools.reference_analyzer atlas --input <references> --output <analysis>`, CPU only, offline.

## Result

| Measure | Value |
|---|---|
| Pages indexed | 1,064 of 1,064, 0 errors |
| Documents | 13 of 13 measured and shortlisted, 13 distinct SHA-256 values |
| Quality gates | 4 of 4 pass |
| First build | about 10 minutes, one render per page |
| Cached rebuild | 6 to 12 seconds, no page rendered |
| Two cached rebuilds | `visual-page-index.json` and `visual-shortlist.json` byte-identical |
| Output size | 238 MB, all outside the repository (thumbnails 18 MB, page images 212 MB) |
| Human decisions | 0 |

EN-01 (224 pages) and EN-01-1 (32 pages) stay separate records, with separate pages, thumbnails and shortlist
entries.

## Shortlist

120 candidates: 113 distinct layouts, 64 document chapters, largest layout share 0.025. The reasons were document
coverage 52, distinct layout 43, label coverage 25. Every label reached the shortlist.

| Doc | Pages | Share of corpus | Candidates | Share of shortlist |
|---|---:|---:|---:|---:|
| AR-02 | 404 | .380 | 20 | .167 |
| EN-01 | 224 | .211 | 12 | .100 |
| EN-02 | 162 | .152 | 16 | .133 |
| BI-02 | 57 | .054 | 11 | .092 |
| AR-03 | 48 | .045 | 10 | .083 |
| BI-01 | 45 | .042 | 9 | .075 |
| AR-01 | 42 | .039 | 12 | .100 |
| EN-01-1 | 32 | .030 | 8 | .067 |
| BI-04 | 17 | .016 | 6 | .050 |
| EN-03 | 9 | .008 | 4 | .033 |
| BI-05 | 8 | .008 | 4 | .033 |
| BI-06 | 8 | .008 | 4 | .033 |
| BI-07 | 8 | .008 | 4 | .033 |

AR-02 is 38% of the pages and 17% of the shortlist.

The M7.3 run previewed 90 of the 1,064 pages. Only 37 of the 120 candidates are among them, and the previews held
few of the pages these labels mark:

| Label | Pages | In the M7.3 previews |
|---|---:|---:|
| `cover_title` | 11 | 9 |
| `section_opener` | 51 | 6 |
| `full_bleed` | 47 | 11 |
| `image_led` | 94 | 22 |
| `split_image_text` | 115 | 18 |
| `infographic` | 29 | 2 |
| `open_whitespace` | 10 | 2 |

## Labels

Counted over all pages; a page can hold several. "Docs" is how many documents the label appears in.

| Label | Pages | Docs | Confidence | Judgement from rendered pages |
|---|---:|---:|---|---|
| `arabic_rtl` | 446 | 7 | high | Reliable: it comes from script measurement |
| `multi_column` | 378 | 8 | medium | Reliable |
| `repeating_system` | 315 | 9 | medium | Reliable, and mostly running furniture |
| `editorial_asymmetric` | 181 | 7 | medium | Broad; still takes ordinary uneven columns |
| `visual_separator` | 151 | 9 | low | Usable after rules were limited to thick ones (was 823) |
| `split_image_text` | 115 | 9 | medium | Good; many are the shared template in BI-05 to BI-07 |
| `large_type` | 113 | 7 | high | Good |
| `image_led` | 94 | 11 | high | Good after scans were excluded |
| `callout` | 80 | 4 | low | Weak; any tinted box counts |
| `bilingual` | 75 | 5 | medium | Mixed; takes Arabic pages with some Latin, as well as true two-language pages |
| `section_opener` | 51 | 9 | medium | Good |
| `pull_quote` | 49 | 6 | low | Weak; most are lead statements, not quotations |
| `full_bleed` | 47 | 10 | high | Good after tinted backdrops were excluded (was 74); a few gradient pages remain |
| `data_story` | 39 | 5 | low | Mixed; also takes contents pages and logo walls |
| `accent_band` | 37 | 2 | medium | Weak; mostly a running header band |
| `financial_table` | 36 | 4 | medium | Good |
| `infographic` | 29 | 5 | medium | Good |
| `cover_title` | 11 | 10 | high | Good |
| `open_whitespace` | 10 | 4 | medium | Good after text run-out and scans were excluded |
| `alternating_layout` | 8 | 2 | medium | Weak; found mirrored running heads on plain text pages |
| `kpi_dashboard` | 6 | 2 | medium | Under-counts; misses highlight pages without large numerals |

Layout types: multi-column text 297, single-column text 232, mixed 166, table 139, split 115, full-page visual 47,
chart or diagram 31, display 25, image-led 10, blank 2.

These judgements come from one automated pass over contact sheets of up to 40 pages per label. They are not measured
precision or recall, and no human has confirmed them.

## What was learned

- **Geometry alone misreads pages.** Scanned letters read as full-page images, and tinted text pages read as
  full-bleed. Pixels were needed to tell them apart: `picture_light_share` for scans, and the amount of text over the
  image for backdrops.
- **The old previews found covers and little else.** They caught 9 of 11 covers but 6 of 51 section openers and 2
  of 29 infographics, because they follow the first table, image and chart in each document.
- **Corpus share and visual interest are unrelated.** The three smallest bilingual documents share one template, so
  document coverage spends 12 candidates on near-identical pages. A reviewer should expect this.
- **Text-only documents take slots.** The minimum of 4 per document puts plain pages from EN-03 and BI-04 in the
  shortlist. This is deliberate: the gate asks for all 13 documents.

## What remains unverified

- Label precision and recall are not measured; there is no labelled ground truth for the real corpus.
- Which pages are worth learning from. Distinctiveness measures difference from neighbours, so a strange page ranks
  high. An AI reviewer has since given its own opinion; no human has confirmed it.
- The gallery was exercised in one Chromium pane through `atlas-serve` and a plain static server. Opening
  `index.html` directly from disk uses the same code path, but it could not be run in the test browser. Other
  browsers are untested.
- Spread pairing in AR-01 and BI-04 is inferred from the facing-page measurement; the pairs were not checked one
  by one.

## What came next

The atlas PR left archetypes, heading orphaning, the LibreOffice DOCX check and the garbled Arabic chart title open.
M7.5's AI art direction took them up without waiting for human curation:
[`docs/m75-ai-art-director`](../../docs/m75-ai-art-director/README.md) has the results. `human-curation.json` stays
empty until a person writes to it.
