# M7.10: Professional design quality

Everything here was rendered and inspected, in PDF and in Microsoft Word 16.0.17932. All documents are
fictional. Preference results are one AI reviewer's blind judgments, labelled `reviewer_type: ai`.
They are not human judgments and they are not measurements.

The gallery with whole documents and example files stays on the author's machine:
`D:\Packages\M710_Design_Quality_Review\index.html`.

## Before and after

Same 12 documents and 48 designs. Before is batch `seed-001`. After is batch `m710-002`, without and with
grammar rules. Near-empty means a last page under a third full.

| Measure | Before | After, plain | After, grammar |
| --- | --- | --- | --- |
| Near-empty last page, PDF | 12 | 2 | 2 |
| Near-empty last page, Word | 16 | 10 | 11 |
| Word page count differs from PDF | 14 | 6 | 5 |
| Heading beside a picture, Word | 1 | 0 | 0 |

The heading detector reads line positions in Word's PDF export and may miss cases. Word improved less
than PDF, which is the main problem left.

Across all 18 documents in `m710-002` (150 designs): grammar designs have 3 near-empty last pages in PDF
and 15 in Word of 79; plain designs 2 and 11 of 71. Growth of 1.5x or more: 4 and 4 in PDF, 5 and 5 in Word.

## What was fixed

| Problem | Cause | Fix |
| --- | --- | --- |
| Headings beside floating pictures in Word | The next paragraph wrapped into the float | `docx_renderer` closes a float before a heading |
| Near-empty last pages and page growth | Variants did not treat a short tail as a fault | Tail check and a ladder of adjustments in `intelligence/variants.py` |
| Blank page, stranded opener pages | Openers kept when the budget had run out | Same budget; a design drops openers rather than adding pages |
| Poor crops | Centre crop cut the subject | `design/focal.py` picks the crop from the picture |
| RTL numbered headings | Number placed for left-to-right | Number follows the paragraph direction, in PDF and Word |
| Arabic marks drawn as blanks | Some faces lack `٫ ٪ ³ ±` | `fonts.manager.covering_face` moves to a face that has every mark used |
| Rainbow bars in `figure_matrix` | Cells were coloured after composition | `_apply_sections` colours each cell |
| Ledger total split from its rows | Keep rule covered the head only | A total stays with the row above, in PDF and Word |

No QA check was weakened and no content is hidden. The content ledger counts the new blocks.

## New composition primitives

| Primitive | What it does | Where to see it |
| --- | --- | --- |
| `image_text_panel` | Picture and text as one unit: split or overlay, either side, three tones | `harbour_feature`, `arabic_city_feature` |
| `figure_matrix` | Charts and figures on a grid of two or three columns | `arabic_health_data` |
| `paired_row_columns` | Two languages side by side, one row per passage | `bilingual_ports_review` |
| `parallel_ledger` | Grammar rule `bilingual.parallel_ledger` connected: one table for two languages, title on top | `bilingual_ports_review` |

All four work in PDF and in editable DOCX, in both directions. Word has no transparency for an overlay
panel, so the panel is solid there.

Rules still unsupported, and left that way on purpose: `figure_caption_band`, `card_grid`,
`outer_margin_column`, `first_page_margin_column`, `unequal_page_zones`, `foot_anchored_media`,
`gradient_scrim`, `masked_image_shape`.

## Blind review results

Grammar design against its own plain version, 68 comparisons over two batches: grammar 32, plain 15, tie 21.
Most ties are documents where the rules changed little.

- **Gains in both PDF and Word:** `bilingual_ports_review`, `bilingual_water_compact`, `arabic_health_data`, `bilingual_institutional`.
- **Mixed:** `harbour_feature`: panels keep paragraphs whole, but the plain large picture has more impact.
  `annual_report` `editorial_modern`: better in PDF, worse in Word.
- **Regressions:** `arabic_city_feature` `editorial_modern` and `proposal` `editorial_modern` in Word:
  dark panels hide repeated pictures. `impact_report` `executive_premium`.
- **No visible change:** `policy_brief`, `board_paper`, `technical_manual`, `arabic_annual` `financial_data`.

Bilingual and data-heavy documents gain most. Picture-led features gain least, because an overlay on a
small picture hides it.

## Remaining problems

- Word last pages are still emptier than PDF.
- An overlay panel repeated on small pictures hides them. The rule should skip such pictures.
- In Word a large picture can cut a paragraph and leave a lone line under it (`harbour_feature`).
- A panel can sit alone at the top of a page, and a section heading can land near a page foot in Word.
- `figure_matrix` charts do not share a scale.
- A design has one Arabic face. Arabic has no italic. Chart Latin labels are unchanged.
- Word panel height comes from a text estimate, and panels are not scaled by refinement.
- An Arabic font set explicitly by the user is not checked for coverage.
- A document without `direction("rtl")` keeps English labels.
- Bundled fonts add about 17 MB to the wheel.
- `research_paper` shows "References" twice; this comes from the source document.
