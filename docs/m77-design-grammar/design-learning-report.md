# M7.7 design learning report

What was learned from the 1,064 reference pages, how the engine uses it, and how far each claim can
be trusted. Each statement belongs to one of three kinds:

- **Measured:** counted or computed from files.
- **AI observation:** Claude (claude-opus-5-5) looked at rendered pages and judged. No person has
  checked these.
- **Unverified:** nobody has tested it.

## Result

The grammar has 18 rules. Nine run in the engine and nine are documented only, because they need a
layout primitive the engine does not have. With the grammar on, measured pages change in PDF and in
Microsoft Word. With it off, default output matches `origin/main` on all 30 snapshots, which compare PDF page count
and text, the DOCX body and the DOCX checks. Pixels are not part of that comparison.

The rules are AI-approved. No person has approved them, and `human_approved` is `false`.

## Coverage (measured, except where marked)

| Item | Count |
|---|---|
| Reference PDFs | 13, plus the Visual Atlas |
| Pages accounted for | 1,064 of 1,064, each with its own record |
| Inspected on a contact sheet | 909 |
| Inspected at detail size (2 per sheet) | 80 |
| Inspected at detail size (3 per sheet) | 75 |
| Family from measurement alone | 727 |
| Family from contact-sheet AI reading | 182 |
| Family from detail AI reading | 85 |
| Measured family confirmed at detail | 70 |
| Quarantined assessments kept out of rule evidence | 288 |
| Pages reviewed by a person | 0 |

Both Unilever documents stay as separate references even though one is close to a copy of the other.
Cedarline, Clearpath and Northbay share one template, so they count once as evidence.

### How reliable the family labels are

An AI re-check of 80 stratified pages at 780 px (seed 77) agreed with **55 of 80 labels (69%)**. This
is one reviewer checking its own earlier work, so it is not an independent accuracy figure.

| Pages agreeing, of 4 | Families |
|---|---|
| 4 | blank_or_notice, cover_image, data_story, kpi_dashboard, letter, multi_column_text, notes_references, section_opener, table_in_text |
| 3 | back_cover, contents, full_bleed_image, single_column_text |
| 2 | image_inset, infographic |
| 1 | editorial_asymmetric, financial_table, image_split |
| 0 | cover_type, statement (statement was then folded into financial_table) |

The 909 contact-sheet pages carry this uncertainty. Page counts per family in
[layout-family-catalog.json](layout-family-catalog.json) should be read as approximate, and weakest
for the families at 2 of 4 or lower.

## Deliverables

| Deliverable | Location |
|---|---|
| Coverage | [full-corpus-coverage.json](full-corpus-coverage.json) |
| Layout families | [layout-family-catalog.json](layout-family-catalog.json) |
| Grammar | [design-grammar.json](design-grammar.json), approvals in [grammar-approvals.json](grammar-approvals.json) |
| Packaged rules | [approved_grammar.json](../../dynamic_pdf/design/approved_grammar.json) |
| Composition graphs | `D:\Dynamic-PDF-Design-References-analysis\grammar\page-composition-graphs.json`, outside Git |
| Evidence gallery | `D:\Packages\M77_Design_Grammar_Review\index.html`, outside Git |
| Comparisons | [comparisons/](comparisons/): sheets, DOCX and PDF of fictional documents, and [results.json](comparisons/results.json) |

The graphs hold normalized boxes and sizes, with no text or pixels. They stay outside Git because
together they still describe complete reference pages. The gallery shows reference pages, so it
stays outside Git too.

## Rules

| Rule | State | Confidence (AI) | Needs |
|---|---|---|---|
| `cover.photo_over_panel` | engine | medium | |
| `cover.low_title_field` | engine | medium | titles up to 32 characters |
| `opener.edge_strip_page` | engine | high | |
| `kpi.hero_and_grid` | engine | medium | |
| `kpi.ruled_strip` | engine | medium | |
| `table.current_period_ledger` | engine | high | |
| `bands.dense_filled_head_foot` | engine | medium | |
| `image.alternating_inset` | engine | medium | |
| `closing.image_band` | engine | low | |
| `chart.caption_bar` | documented | high | `figure_caption_band` |
| `chart.small_multiples` | documented | medium | `figure_matrix` |
| `card.portrait_grid` | documented | medium | `card_grid` |
| `editorial.overlaid_panel` | documented | medium | `image_text_panel` |
| `editorial.outer_callout` | documented | low | `outer_margin_column` |
| `bilingual.parallel_columns` | documented | high | `paired_row_columns` |
| `bilingual.parallel_ledger` | documented | high | not wired to the engine |
| `academic.metadata_margin` | documented | low | `first_page_margin_column` |
| `letter.portrait_opener` | documented | medium | `unequal_page_zones` |

Each rule records its roles, required elements, constraints, RTL behaviour, evidence pages, failure
conditions and safe fallback. Three further primitives have no rule yet: `foot_anchored_media`,
`gradient_scrim` and `masked_image_shape`.

## How the engine uses it

```python
made = builder.design_variants(grammar=True)                    # all applicable rules
made = builder.design_variants(grammar=True, grammar_rules=["kpi.hero_and_grid"])
```

Rules adjust a direction through a small adapter in
[grammar.py](../../dynamic_pdf/design/grammar.py). M7.9 was not rebuilt. If a design using rules fails
the hard gates, it falls back to the same design without them and says so in its observations. The
call is opt-in, so `design_variants()` with no argument behaves as before.

## Measured comparisons

All documents are fictional. "Changed" counts pages where more than 2% of pixels differ, and
"largest" is the share of pixels changed on the page that changed most. These numbers show that the
rule changes the page. They do not show that the page is better.

| Rule | Document | PDF changed / largest | PDF pages | Word changed / largest | Word pages |
|---|---|---|---|---|---|
| `cover.photo_over_panel` | annual_report | 1 / .996 | 6 → 6 | 1 / .996 | 6 → 6 |
| `cover.low_title_field` | impact_report | 1 / .233 | 5 → 5 | 1 / .224 | 4 → 4 |
| `cover.low_title_field` | arabic_annual | 1 / .692 | 6 → 6 | 1 / .692 | 6 → 6 |
| `opener.edge_strip_page` | annual_report | 5 / .353 | 6 → 8 | 5 / .354 | 6 → 8 |
| `kpi.hero_and_grid` | annual_report | 5 / .339 | 6 → 7 | 5 / .355 | 6 → 7 |
| `table.current_period_ledger` | financial_statements | 0 / .016 | 5 → 5 | 0 / .016 | 5 → 5 |
| `bands.dense_filled_head_foot` | financial_statements | 2 / .037 | 3 → 3 | 2 / .034 | 3 → 3 |
| `bands.dense_filled_head_foot` | arabic_annual | 3 / .042 | 4 → 4 | 3 / .042 | 4 → 4 |
| `image.alternating_inset` | annual_report | 5 / .236 | 6 → 6 | 5 / .218 | 6 → 6 |
| `closing.image_band` | sustainability_report | 1 / .144 | 5 → 5 | 1 / .148 | 5 → 5 |

Seven rules change structure. `table.current_period_ledger` is a tonal change below the 2% floor;
its DOCX shaded cells go from 0 to 21. `kpi.ruled_strip` has no demonstration of its own, though it
was applied in 21 of the whole-corpus designs below.

**Whole corpus (measured):** 12 documents with 3 designs each. All 36 were valid with and without
the grammar, with 0 fallbacks. All 36 report rules, but 17 of them show no page above the pixel floor
and 5 changed page count. A reported rule therefore does not always mean a visible change.

| Rule | Designs using it |
|---|---|
| `table.current_period_ledger` | 36 |
| `kpi.ruled_strip` | 21 |
| `closing.image_band` | 18 |
| `bands.dense_filled_head_foot` | 8 |
| `cover.photo_over_panel` | 7 |
| `image.alternating_inset` | 6 |
| `cover.low_title_field` | 4 |
| `kpi.hero_and_grid` | 3 |
| `opener.edge_strip_page` | 1 |

### Microsoft Word

All 20 demonstration DOCX files were exported through Microsoft Word 16.0.17932 on this machine, one
process per file, and all 10 before/after sheets were viewed. All 48 DOCX files in the seed batch
exported too. This is one Word version on one machine, and it says nothing about other versions, Mac
Word or Word Online. LibreOffice 24.2.7.2 results are in the same folder and are not evidence for
Word.

What Word showed:

- **Layouts held (AI observation).** The rule's layout appears on all 10 sheets.
- **Page counts differ from the PDF.** The impact report is 5 pages in PDF and 4 in Word, with or
  without the rule. In the seed batch 14 of 48 designs came out one page shorter in Word (measured).
- **`image.alternating_inset` differs from the PDF.** On page 4, "5 Environment" starts at x = 265 pt
  in Word and 80 pt in the PDF, because Word set a heading beside a float that was still running (fixed in M7.10: any block that cannot wrap a float now starts below it).
- **Arabic headings sit tight to the band's right edge in Word**, with and without the rule. This is
  existing M7.9 behaviour.

## AI preferences

The seed batch `seed-001` holds 12 documents, 48 designs and 36 blind comparisons, recorded as AI
evaluations. None is a human preference.

| Item | Result |
|---|---|
| Preferred A / B / tie | 17 / 16 / 3 |
| Confidence high / medium / low | 5 / 28 / 3 |
| Reversed-order repeats that agreed | 12 of 12 |
| Rows excluded after the defect below | 8 |
| Rows the trainer can use | 16, and it needs 200 |

Limits of this batch:

- The 12 repeats came in the same session and were recognisable, so their agreement is weak evidence
  of consistency.
- Rows were judged from PDF pages only, up to 8 pages per row at 240 px, so the longest designs were
  cut short. Word was checked afterwards as a format check on 3 of the 36 sheets, recorded in
  [word-check.json](../../training/ai_preferences/batches/seed-001/word-check.json), and added no rows.
- The model that judged these also built the rules and the engine changes, which is a real source of
  bias.

One pattern was noticed: drop caps with narrow indented text were disliked in manuals and papers.
That is 1 reviewer on a small batch, so it is a question to test.

### A defect blind review found

`cover.low_title_field` cut titles of 37–50 characters, broke a word ("Infr astructure") and left a
white subtitle on an otherwise empty second page. All hard gates passed, and an earlier look at the
Arabic demo missed the cut title. The comparison sheets exposed it.

The rule is now limited to 32 characters. A new `_cover_spilled` gate catches the spill and falls
back. 9 designs are listed in `superseded.json`, and the 8 rows using them stay on record but are
skipped in training. Word shows the same empty second page on the design viewed, so the defect was
not PDF-only.

## Learned ranker

No real model was trained, and none is deployed. With 16 usable comparisons the trainer stops and
says so. The training, evaluation, gate and `design_variants(ranker_model=...)` paths ran only on a
synthetic fixture in a throwaway environment. That result was discarded and says nothing about real
preferences. `lightgbm` is not installed in the working environment and is not a production
dependency. Any future model would be AI preference distillation, not human-supervised training, and
would make no claim of human-level aesthetic judgment.

## Limits

- **Unverified:** whether any rule makes documents better for readers. No person has looked, and no
  reader test exists.
- **Unverified:** the DOCX files in any Word version other than 16.0.17932.
- **Unverified:** the grammar on real client documents. All tests here use fictional ones.
- **Evidence is thin for some rules.** `kpi.ruled_strip`, `chart.small_multiples`,
  `closing.image_band`, `bilingual.parallel_ledger` and `academic.metadata_margin` rest on 1 evidence
  entry each.
- **Rights:** most references are for study only, ESCWA's are all rights reserved, PLOS is CC BY and
  the World Bank items are under Creative Commons licences. The grammar keeps abstract relationships
  and no artwork, branding or complete page arrangement. This is an engineering reading and not a
  legal determination, so it needs a person's review before commercial use.

## Reproduce

```bash
python benchmarks/m77/run.py out-folder --keep-files --corpus
```

```bash
python benchmarks/m77/word.py out-folder
```

The first command needs LibreOffice for its office page counts, and the second needs Word on Windows.
[LEARNING_PIPELINE.md](../LEARNING_PIPELINE.md) covers adding references and regenerating evaluations.
