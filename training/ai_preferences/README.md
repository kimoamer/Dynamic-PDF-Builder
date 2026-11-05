# AI preferences

These are an AI reviewer's comparisons, not human labels. Each row in `ai-preferences.jsonl`
says `reviewer_type: "ai"`, the model, the date and the method, and cites the pages seen.

Criterion scores run from -2 to +2: positive favours side A of that row, negative favours side B,
0 is equal, and a criterion that does not apply is left out.

`batches/<name>/superseded.json` lists designs later found defective. Their rows stay on record
and the trainer skips them. Renders, assets and sheets stay on this machine; rows keep the
SHA-256 of each PDF and DOCX so a row always says exactly what was judged.

## Batches

| Batch | Documents | Rows | Sheets from |
| --- | --- | --- | --- |
| `seed-001` | 12 | 36 | PDF, with a Word check |
| `m710-001` | 18 | 72 | PDF |
| `m710-002` | 18 | 72 | Microsoft Word, after the fixes the first batch led to |

Batches render different code, so a pair is only the same pair inside one batch.

Measured layout facts sit in each batch's `candidates.jsonl`, apart from the AI's opinions in this
dataset. `python -m tools.design_learning preferences readiness --out <folder>` reports whether the data
is fit to train on; the latest report is in `docs/m710-design-quality/dataset-readiness.md`.
No model has been trained on it.
