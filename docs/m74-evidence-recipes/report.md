# M7.4 comparison: automated facts

Identical content, rendered with the existing design (baseline) and with the recipe forced on (proposed). Human review is pending for every recipe: nothing here is a preference.

## arabic_bilingual

**Status: inconclusive.** larger body text is safe on three of four documents; the long Arabic report goes over the page limit and falls back; no human review yet.

4 documents, 1 with defects, 2 with measured gains and no measured costs.

| document | pages | size/leading | chars per line | body page fill | split tables | PDF QA | PDF warm s | peak MB |
|---|---|---|---|---|---|---|---|---|
| ar_annual_report | 20 → 25 | 9.5/1.6 → 12/1.4 | 50 → 54.0 | 0.806 → 0.768 | 1 → 1 | fail → fail | 4.784 → 11.958 | 145.3 → 153.1 |
| ar_financial_statements | 2 → 2 | 9.5/1.6 → 12/1.4 | 84 → 81 | 0.854 → 0.873 | 1 → 1 | pass → pass | 0.504 → 1.131 | 74.7 → 75.4 |
| ar_memo | 1 → 1 | 10.5/1.6 → 12/1.4 | 63.5 → 66.0 | None → None | 0 → 0 | pass → pass | 0.084 → 0.198 | 73.6 → 74.2 |
| bilingual_board_report | 3 → 3 | 10.5/1.55 → 12/1.4 | 81.0 → 73 | 0.831 → 0.709 | 0 → 0 | pass → pass | 1.044 → 2.488 | 126.8 → 128.8 |

* **ar_annual_report**: gains: body size 9.5 → 12 pt; readability score 0.72 → 1.00. Costs: pages 20 → 25; line gaps clear of ink 100% → 90%. Defects: pages: 20 → 25 (limit 23).
* **ar_financial_statements**: gains: body size 9.5 → 12 pt; readability score 0.72 → 1.00. Costs: none. Defects: none.
* **ar_memo**: gains: body size 10.5 → 12 pt; readability score 0.94 → 1.00. Costs: none. Defects: none.
* **bilingual_board_report**: gains: body size 10.5 → 12 pt. Costs: mean body page fill 0.83 → 0.71. Defects: none.

## editorial_executive

**Status: inconclusive.** safe on all three documents, but columns were used on one fictional briefing only, the proposal lost body size, and no human review exists yet.

3 documents, 0 with defects, 2 with measured gains and no measured costs.

| document | pages | size/leading | chars per line | body page fill | split tables | PDF QA | PDF warm s | peak MB |
|---|---|---|---|---|---|---|---|---|
| editorial_briefing | 3 → 3 | 9.5/1.35 → 10/1.38 | 109 → 48.0 | 0.726 → 0.852 | 0 → 0 | pass → pass | 0.093 → 0.351 | 71.5 → 72.2 |
| en_executive_report | 2 → 2 | 9.5/1.35 → 10/1.38 | 103.0 → 96.0 | 0.728 → 0.78 | 0 → 0 | pass → pass | 1.106 → 2.527 | 123.0 → 134.7 |
| proposal | 3 → 3 | 10.5/1.4 → 10/1.3 | 90.0 → 80.5 | 0.928 → 0.919 | 0 → 0 | pass → pass | 0.082 → 0.218 | 71.5 → 71.9 |

* **editorial_briefing**: gains: chars per line 109 → 48, back inside 90; body size 9.5 → 10 pt; readability score 0.78 → 0.90. Costs: none. Defects: none.
* **en_executive_report**: gains: body size 9.5 → 10 pt; readability score 0.78 → 0.90. Costs: none. Defects: none.
* **proposal**: gains: none. Costs: body size 10.5 → 10 pt; readability score 0.99 → 0.94. Defects: none.

## financial_corporate

**Status: inconclusive.** no measured gain on either document: no page or table-split saved, lower readability score, and a heading separated from its table; no human review yet.

2 documents, 0 with defects, 0 with measured gains and no measured costs.

| document | pages | size/leading | chars per line | body page fill | split tables | PDF QA | PDF warm s | peak MB |
|---|---|---|---|---|---|---|---|---|
| business_memo | 1 → 1 | 10.5/1.4 → 10/1.25 | 72.0 → 72.0 | None → None | 0 → 0 | pass → pass | 0.017 → 0.033 | 71.1 → 71.7 |
| financial_statements | 5 → 5 | 10/1.4 → 10/1.25 | 84.0 → 84.0 | 0.883 → 0.824 | 1 → 1 | pass → pass | 0.14 → 0.338 | 72.3 → 72.9 |

* **business_memo**: gains: none. Costs: body size 10.5 → 10 pt; readability score 1.00 → 0.89. Defects: none.
* **financial_statements**: gains: none. Costs: readability score 0.93 → 0.81; mean body page fill 0.88 → 0.82. Defects: none.
