# M7.8 Auto Media: measured results

LibreOffice: LibreOffice 24.2.7.2 420(Build:2). Microsoft Word: not run.

| Case | Before | After | PDF pages | LibreOffice DOCX pages | Status | DOCX check |
|---|---|---|---|---|---|---|
| executive_narrative | editorial | media:mix | 3 → 2 | 3 → 2 | ok | libreoffice (LibreOffice 24.2.7.2 420(Build:2)); pages 3 -> 2 |
| technical_figure | baseline | baseline | 1 → 1 | 1 → 1 | ok | - |
| arabic_dense_bands | balanced | balanced | 2 → 2 | 3 → 3 | ok | - |
| near_page_end | editorial | media:mix | 3 → 2 | 3 → 2 | ok | libreoffice (LibreOffice 24.2.7.2 420(Build:2)); pages 3 -> 2 |
| short_bilingual | baseline | baseline | 1 → 1 | 1 → 1 | ok | - |
| low_dpi | baseline | media:mix | 1 → 1 | 1 → 1 | ok | libreoffice (LibreOffice 24.2.7.2 420(Build:2)); pages 1 -> 1 |

## executive_narrative

| Candidate | Rendered | Pages | Score | With gain | Outcome |
|---|---|---|---|---|---|
| baseline | yes | 3 | 62.65 | - | scored lower than the delivered layout |
| media:mix | yes | 2 | 99.29 | 99.29 | delivered |
| media:full_width | no | - | - | - | not rendered (render budget) |
| media:compact | no | - | - | - | not rendered (render budget) |
| grouped | no | - | - | - | no plausible improvement predicted |
| balanced | no | - | - | - | no plausible improvement predicted |
| compact | no | - | - | - | no plausible improvement predicted |
| editorial | yes | 3 | 91.64 | 91.64 | scored lower than the delivered layout |

## technical_figure

| Candidate | Rendered | Pages | Score | With gain | Outcome |
|---|---|---|---|---|---|
| baseline | yes | 1 | 98.86 | - | delivered |
| media:mix | no | - | - | - | not rendered (render budget) |
| media:compact | no | - | - | - | not rendered (render budget) |
| grouped | yes | 1 | 98.86 | 98.86 | below the baseline non-regression threshold |
| balanced | yes | 1 | 98.72 | 98.72 | below the baseline non-regression threshold |
| compact | no | - | - | - | not rendered (render budget) |

## arabic_dense_bands

| Candidate | Rendered | Pages | Score | With gain | Outcome |
|---|---|---|---|---|---|
| baseline | yes | 3 | 61.75 | - | scored lower than the delivered layout |
| media:mix | no | - | - | - | not rendered (render budget) |
| media:full_width | no | - | - | - | not rendered (render budget) |
| media:compact | no | - | - | - | not rendered (render budget) |
| grouped | no | - | - | - | no plausible improvement predicted |
| balanced | yes | 2 | 99.69 | 99.69 | delivered |
| compact | yes | 2 | 98.78 | 98.78 | scored lower than the delivered layout |

## near_page_end

| Candidate | Rendered | Pages | Score | With gain | Outcome |
|---|---|---|---|---|---|
| baseline | yes | 3 | 81.61 | - | scored lower than the delivered layout |
| media:mix | yes | 2 | 99.52 | 99.52 | delivered |
| media:full_width | no | - | - | - | not rendered (render budget) |
| media:compact | no | - | - | - | not rendered (render budget) |
| grouped | no | - | - | - | no plausible improvement predicted |
| balanced | no | - | - | - | no plausible improvement predicted |
| compact | no | - | - | - | no plausible improvement predicted |
| editorial | yes | 3 | 86.77 | 86.77 | scored lower than the delivered layout |

## short_bilingual

| Candidate | Rendered | Pages | Score | With gain | Outcome |
|---|---|---|---|---|---|
| baseline | yes | 1 | 86.51 | - | delivered |
| media:mix | yes | 1 | 80.4 | 80.4 | below the baseline non-regression threshold |

## low_dpi

| Candidate | Rendered | Pages | Score | With gain | Outcome |
|---|---|---|---|---|---|
| baseline | yes | 1 | 86.98 | - | scored lower than the delivered layout |
| media:mix | yes | 1 | 86.71 | 89.47 | delivered |

## Cases that must not pass

| Case | Held | Evidence |
|---|---|---|
| bands that cannot fit | yes | `{"status": "failed", "reason": "band_content_unfit"}` |
| Word required, no adapter | yes | `{"status": "unverified", "strategy": "editorial", "word": "unverified"}` |
| broken asset | yes | `{"raised": "BlockRenderError"}` |
| minimum width above the DPI limit | yes | `{"strategy": "baseline"}` |
| explicit width | yes | `{"width": 180, "strategy": "baseline"}` |
