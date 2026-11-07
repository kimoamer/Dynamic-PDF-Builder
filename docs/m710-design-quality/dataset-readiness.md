# Dataset readiness

Written by `python -m tools.design_learning preferences readiness`. No model was trained.

**Verdict: not ready.** 85 usable comparisons against a gate of 200: 62 for training and 23 held out, from 180 rows.

## Excluded

- ties or abstentions: 31
- low confidence: 41
- reversed repeats: 48

## Coverage

| Slice | Usable |
| --- | --- |
| languages: arabic | 14 |
| languages: bilingual | 17 |
| languages: english | 54 |
| families: annual | 19 |
| families: bilingual_review | 10 |
| families: data_story | 6 |
| families: feature | 12 |
| families: financial | 5 |
| families: governance | 17 |
| families: technical | 16 |
| formats: pdf | 51 |
| formats: word | 34 |
| batches: m710-001 | 35 |
| batches: m710-002 | 34 |
| batches: seed-001 | 16 |

18 documents appear. Fewest: arabic_financial (2), financial_statements (3), arabic_annual (3), transit_data_story (3).

## Consistency

- Reversed repeats: 47 of 48 agreed; flipped: cmp-046.
- Side A won 59 of 113 clear answers.
- Confidence: {"medium": 109, "high": 30, "low": 41}.

## Provenance

- Reviewer types: ai. Models: claude-opus-5-5.
- Rows missing a traced field: 0.
- Rows whose hash matches no render on record: 0.
- Usable rows with measured layout facts on both sides: 69.

## Leakage

- Held-out families: governance, data_story.
- Documents on both sides: 0. Same source hash on both sides: 0.
- Documents outside the split: 0.
- Families never cross the split, but all documents share the same generated pictures and author.

## What the rows say

Grammar design against the same design without it: 11 of 16 went to the grammar. These are one AI reviewer's preferences on fictional documents, not a measure of quality.

| Direction | Won | Of |
| --- | --- | --- |
| arabic_institutional | 6 | 10 |
| corporate_conservative | 16 | 32 |
| editorial_modern | 15 | 47 |
| executive_premium | 32 | 43 |
| financial_data | 16 | 38 |

Facts most often higher on the preferred side (descriptive only):

- cover_colour_share: 40 of 50
- both_scripts_side_by_side: 11 of 14
- font_faces: 9 of 36
- distinct_sizes: 46 of 62
- opener_page_share: 33 of 48
- band_words_spread: 17 of 52
- short_pages_before_last: 10 of 29
- last_page_words: 40 of 62
- interior_gap_pages: 17 of 26
- cover_words: 16 of 45

## Remaining weaknesses

- 85 usable comparisons against a gate of 200: not enough to train
- only 23 held-out comparisons: an agreement figure would be too noisy to trust
- 18 documents: all fictional, written by one author, sharing five generated pictures, so a model could learn this corpus and not design
- one reviewer model: its taste and blind spots are in every row, and no human has checked them
- 30 of 180 answers are high confidence: thumbnails limit what can be seen
- 34 of 85 usable comparisons were judged on Word pages
- 16 usable comparisons predate the layout facts and lack them
