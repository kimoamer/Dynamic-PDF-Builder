# M7.5 archetype comparison

Identical fictional content, before (plain blocks) and after (archetype). Facts only; the pages are in `gallery/index.html`.

## opener_en (asymmetric_opener)

|  | PDF pages | DOCX pages | PDF QA | DOCX QA | missing words PDF / DOCX | harakat source / PDF / DOCX | render s PDF / DOCX |
|---|---|---|---|---|---|---|---|
| before | 1 | 1 | pass | pass | 0 / 0 | 0 / 0 / 0 | 0.147 / 0.237 |
| after | 2 | 2 | pass | pass | 0 / 0 | 0 / 0 / 0 | 0.037 / 0.079 |

## opener_ar (asymmetric_opener)

|  | PDF pages | DOCX pages | PDF QA | DOCX QA | missing words PDF / DOCX | harakat source / PDF / DOCX | render s PDF / DOCX |
|---|---|---|---|---|---|---|---|
| before | 1 | 1 | pass | pass | 0 / 0 | 43 / 43 / 43 | 0.395 / 0.116 |
| after | 2 | 2 | pass | pass | 0 / 0 | 43 / 43 / 43 | 0.7 / 0.161 |

## performance_en (performance_page)

|  | PDF pages | DOCX pages | PDF QA | DOCX QA | missing words PDF / DOCX | harakat source / PDF / DOCX | render s PDF / DOCX |
|---|---|---|---|---|---|---|---|
| before | 1 | 1 | pass | pass | 0 / 0 | 0 / 0 / 0 | 0.37 / 0.267 |
| after | 2 | 2 | pass | pass | 0 / 0 | 0 / 0 / 0 | 0.668 / 0.265 |

## performance_ar (performance_page)

|  | PDF pages | DOCX pages | PDF QA | DOCX QA | missing words PDF / DOCX | harakat source / PDF / DOCX | render s PDF / DOCX |
|---|---|---|---|---|---|---|---|
| before | 2 | 2 | fail | pass | 0 / 0 | 51 / 51 / 51 | 1.041 / 0.285 |
| after | 2 | 2 | pass | pass | 0 / 0 | 51 / 51 / 51 | 1.588 / 0.228 |
- before PDF error: overflow: text overflows into the margin by 0pt: 'ﻣﻌﺪﻝ ﺍﻹﺻﺎﺑﺎﺕ ﻟﻜﻞ ﻣﻠﻴﻮﻥ ﺳﺎﻋﺔ'
- before PDF error: overflow: text overflows into the margin by 0pt: '١٢٫٠'
- before PDF error: overflow: text overflows into the margin by 0pt: '−٣١٫٠'
- before PDF error: overflow: text overflows into the margin by 0pt: '٩ ﻧﻘﺎﻁ+'

## ledger_en (parallel_ledger)

|  | PDF pages | DOCX pages | PDF QA | DOCX QA | missing words PDF / DOCX | harakat source / PDF / DOCX | render s PDF / DOCX |
|---|---|---|---|---|---|---|---|
| before | 1 | 1 | pass | pass | 0 / 0 | 0 / 0 / 0 | 0.367 / 0.427 |
| after | 1 | 1 | pass | pass | 0 / 0 | 0 / 0 / 0 | 0.205 / 0.317 |

## ledger_ar (parallel_ledger)

|  | PDF pages | DOCX pages | PDF QA | DOCX QA | missing words PDF / DOCX | harakat source / PDF / DOCX | render s PDF / DOCX |
|---|---|---|---|---|---|---|---|
| before | 1 | 1 | pass | pass | 0 / 0 | 5 / 5 / 5 | 0.885 / 0.425 |
| after | 1 | 1 | pass | pass | 0 / 0 | 5 / 5 / 5 | 0.637 / 0.333 |

## ledger_bilingual (parallel_ledger)

|  | PDF pages | DOCX pages | PDF QA | DOCX QA | missing words PDF / DOCX | harakat source / PDF / DOCX | render s PDF / DOCX |
|---|---|---|---|---|---|---|---|
| before | 1 | 1 | pass | pass | 0 / 0 | 5 / 5 / 5 | 1.373 / 0.41 |
| after | 1 | 1 | pass | pass | 0 / 0 | 5 / 5 / 5 | 0.417 / 0.456 |

