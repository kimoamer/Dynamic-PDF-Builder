# M7.6 media and page-system results

Facts from one run. `before` is the same content without the media model or page system.

| Example | Variant | PDF pp | DOCX pp (LO) | PDF QA | DOCX QA | Inline | Anchored | Fields | PDF s | DOCX s | Heap MB | PDF KB | DOCX KB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| corporate_background | before | 3 | 3 | pass | pass | 2 | 0 | 1 | 0.119 | 0.297 | 18.1 | 96 | 65 |
| corporate_background | after | 3 | 3 | pass | pass | 3 | 5 | 3 | 0.726 | 0.396 | 26.1 | 171 | 72 |
| editorial_floats | before | 5 | 4 | pass | pass | 3 | 0 | 1 | 0.518 | 0.136 | 36.1 | 236 | 113 |
| editorial_floats | after | 4 | 3 | pass | pass | 2 | 2 | 1 | 0.444 | 0.157 | 19.2 | 145 | 115 |
| arabic_bilingual | before | 5 | 4 | pass | pass | 2 | 0 | 1 | 0.52 | 0.138 | 25.9 | 193 | 88 |
| arabic_bilingual | after | 3 | 3 | pass | pass | 3 | 1 | 2 | 0.456 | 0.19 | 11.7 | 133 | 94 |
| financial_report | before | 3 | 3 | pass | pass | 2 | 0 | 1 | 0.219 | 0.215 | 18.2 | 97 | 65 |
| financial_report | after | 3 | 2 | pass | pass | 2 | 1 | 3 | 0.195 | 0.244 | 9.3 | 78 | 68 |
| long_report | before | 12 | 11 | pass | pass | 5 | 0 | 0 | 0.419 | 0.235 | 17.3 | 128 | 87 |
| long_report | after | 10 | 10 | pass | pass | 6 | 7 | 5 | 0.772 | 0.569 | 29.4 | 183 | 103 |
| image_failures | before | 2 | 2 | pass | pass | 1 | 0 | 1 | 0.058 | 0.123 | 0.6 | 6 | 39 |
| image_failures | after | 2 | 2 | pass | pass | 1 | 0 | 1 | 0.027 | 0.11 | 0.6 | 6 | 39 |
| hf_simple | before | 3 | 3 | pass | pass | 0 | 0 | 1 | 0.046 | 0.141 | 0.6 | 5 | 37 |
| hf_simple | after | 3 | 3 | pass | pass | 0 | 0 | 1 | 0.049 | 0.163 | 0.6 | 5 | 37 |
| hf_dense_header | before | 3 | 3 | pass | pass | 0 | 0 | 1 | 0.054 | 0.147 | 0.6 | 5 | 37 |
| hf_dense_header | after | 3 | 3 | pass | pass | 1 | 1 | 4 | 0.085 | 0.18 | 0.8 | 14 | 41 |
| hf_dense_footer | before | 4 | 4 | pass | pass | 0 | 0 | 1 | 0.047 | 0.149 | 0.6 | 5 | 37 |
| hf_dense_footer | after | 4 | 4 | pass | pass | 0 | 0 | 3 | 0.065 | 0.18 | 0.7 | 6 | 38 |
| hf_odd_even | before | 5 | 5 | pass | pass | 0 | 0 | 0 | 0.06 | 0.165 | 0.7 | 6 | 35 |
| hf_odd_even | after | 5 | 5 | pass | pass | 0 | 0 | 3 | 0.071 | 0.19 | 0.7 | 6 | 39 |
| hf_arabic | before | 3 | 3 | pass | pass | 0 | 0 | 1 | 0.62 | 0.15 | 3.3 | 42 | 37 |
| hf_arabic | after | 3 | 3 | pass | pass | 1 | 0 | 2 | 0.282 | 0.173 | 3.6 | 48 | 41 |
| hf_bilingual | before | 4 | 4 | pass | pass | 0 | 0 | 1 | 0.046 | 0.145 | 0.6 | 5 | 37 |
| hf_bilingual | after | 4 | 4 | pass | pass | 1 | 0 | 1 | 0.093 | 0.182 | 1.0 | 29 | 41 |
| hf_cover_none | before | 3 | 3 | pass | pass | 0 | 0 | 1 | 0.037 | 0.131 | 0.6 | 4 | 37 |
| hf_cover_none | after | 3 | 3 | pass | pass | 1 | 3 | 3 | 0.16 | 0.191 | 7.5 | 45 | 68 |
| hf_section | before | 2 | 2 | pass | pass | 0 | 0 | 1 | 0.041 | 0.144 | 0.6 | 4 | 37 |
| hf_section | after | 3 | 3 | pass | pass | 1 | 2 | 4 | 0.056 | 0.181 | 0.7 | 11 | 43 |
