# M6.2 benchmark — M6.1 vs M6.2 (smart composition, identical documents)

`python scripts/benchmark_compose.py OUT` run on `main` (M6.1) and on this branch; values are the composed
output (`a → b` where they differ). Renders include design page-fit renders. Timings are single runs on one CPU.

| document | strategy | status | pages | score | wasted | body_fill | separated | readability | hard_errors | qa_errors | pdf_words_missing | docx_words_missing | renders | wall_s | cpu_s | peak_mb |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| arabic_long_report | baseline → grouped | ok | 25 → 26 | 90.15 → 93.01 | 0.0 | 0.866 → 0.84 | 3.0 → 0.0 | 0.939 | 0 | 0 | 0 | 0 | 3 → 4 | 6.389 → 6.969 | 6.351 → 6.939 | 13.2 → 14.8 |
| bilingual_corporate | baseline | ok | 5 | 97.61 | 0.0 | 0.849 | 0.0 | 0.991 | 0 | 0 | 0 | 0 | 2 | 0.29 → 0.237 | 0.286 → 0.237 | 2.3 |
| executive_proposal | baseline | ok | 2 | 100.0 | 0.0 | 0.882 | 0.0 | 1.0 | 0 | 0 | 0 | 0 | 4 | 0.112 → 0.12 | 0.112 → 0.12 | 0.8 |
| financial_complex | compact | ok | 6 | 99.41 | 0.0 | 0.964 | 0.0 | 0.983 | 0 | 0 | 0 | 0 | 6 | 2.176 → 2.101 | 2.162 → 2.095 | 4.3 → 4.6 |
| academic_paper | baseline | ok | 5 | 95.8 | 0.0 | 0.807 | 0.0 | 1.0 | 0 | 0 | 0 | 0 | 2 | 0.552 → 0.563 | 0.551 → 0.545 | 3.7 → 2.7 |
| technical_manual | balanced | ok | 6 | 86.83 | 0.0 | 0.727 | 0.0 | 1.0 | 0 | 0 | 0 | 0 | 4 | 0.933 → 0.889 | 0.932 → 0.884 | 8.9 → 8.0 |
| chart_report | compact | ok | 6 | 91.68 | 0.0 | 0.881 | 0.0 | 0.9 | 0 | 0 | 0 | 0 | 6 | 6.58 → 5.845 | 6.531 → 5.823 | 16.6 → 16.2 |
| fx_academic | baseline | ok | 2 | 81.98 | 0.0 | 0.0 | 0.0 | 1.0 | 0 | 0 | 0 | 0 | 4 | 0.272 → 0.263 | 0.263 → 0.259 | 1.8 → 2.5 |
| fx_arabic_report | balanced | ok | 1 | 89.09 | 0.0 | 0.0 | 0.0 | 1.0 | 0 | 0 | 0 | 0 | 3 | 0.067 → 0.113 | 0.067 → 0.109 | 1.2 |
| fx_bilingual | baseline | ok | 1 | 85.98 | 0.0 | 0.0 | 0.0 | 0.991 | 0 | 0 | 0 | 0 | 2 | 0.039 → 0.036 | 0.039 → 0.036 | 1.0 |
| fx_executive | baseline | ok | 1 | 94.91 | 0.0 | 0.0 | 0.0 | 0.991 | 0 | 0 | 0 | 0 | 2 | 0.031 → 0.032 | 0.029 → 0.032 | 0.5 |
| fx_financial | balanced | ok | 2 | 100.0 | 0.0 | 0.954 | 0.0 | 1.0 | 0 | 0 | 0 | 0 | 6 | 0.487 → 0.575 | 0.483 → 0.567 | 1.6 → 1.5 |
| fx_invoice | balanced | ok | 1 | 82.75 | 0.0 | 0.0 | 0.0 | 1.0 | 0 | 0 | 0 | 0 | 3 | 0.044 → 0.041 | 0.043 → 0.041 | 0.6 |
| fx_letter | baseline | ok | 1 | 79.8 | 0.0 | 0.0 | 0.0 | 1.0 | 0 | 0 | 0 | 0 | 2 | 0.013 → 0.011 | 0.013 → 0.011 | 0.4 |
| fx_manual | balanced | ok | 2 | 83.63 | 0.0 | 0.0 | 0.0 | 1.0 | 0 | 0 | 0 | 0 | 5 | 0.125 → 0.126 | 0.123 → 0.121 | 1.2 |
| fx_memo | baseline | ok | 1 | 80.11 | 0.0 | 0.0 | 0.0 | 1.0 | 0 | 0 | 0 | 0 | 2 | 0.015 → 0.014 | 0.015 → 0.014 | 0.4 |
| fx_proposal | baseline | ok | 1 | 99.3 | 0.0 | 0.0 | 0.0 | 1.0 | 0 | 0 | 0 | 0 | 3 | 0.048 → 0.047 | 0.048 → 0.047 | 0.6 |
| fx_wide_data | compact | ok | 2 | 98.0 | 0.0 | 0.917 | 0.0 | 0.9 | 0 | 0 | 0 | 0 | 6 | 0.662 → 0.723 | 0.662 → 0.712 | 1.9 |

Only `arabic_long_report` changes layout: the `grouped` candidate (designed theme unchanged) keeps each
table's lead-in lines with it. 17 other documents: identical strategy, pages, score and quality metrics.

* `arabic_tables_before_after.png` — PDF pages around the three formerly separated tables.
* `arabic_long_report-docx.png` — DOCX rendered by LibreOffice (first 12 pages).
