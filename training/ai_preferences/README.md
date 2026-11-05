# AI preferences

These are an AI reviewer's comparisons, not human labels. Each row in `ai-preferences.jsonl`
says `reviewer_type: "ai"`, the model, the date and the method, and cites the pages seen.

Criterion scores run from -2 to +2: positive favours side A of that row, negative favours side B,
0 is equal, and a criterion that does not apply is left out.

`batches/<name>/superseded.json` lists designs later found defective. Their rows stay on record
and the trainer skips them. Renders, assets and sheets stay on this machine; rows keep the
SHA-256 of each PDF and DOCX so a row always says exactly what was judged.
