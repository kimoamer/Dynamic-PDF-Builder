# M7.7 -> M7.10: measurable reference bridge and blind sample expansion

This workflow does **not** turn reference pages into quality labels. It does not train LightGBM, change the production engine, or re-use evaluation documents as training examples.

## Files and provenance

- Local M7.7: `D:/Dynamic-PDF-Design-References-analysis/grammar/page-composition-graphs.json` and optionally the full coverage JSON. These were generated from the 1,064 reference pages; original PDFs, page imagery, review notes and any rights documentation remain outside Git.
- Local M7.10: `training/ai_preferences/batches/<new-batch>/candidates.jsonl`, render PDFs and DOCX, `word/word.json` and Word-exported PDFs. Use `generate`, `word` and the steps below.
- Versioned metadata in Git: `training/document-split.json`, AI preference rows, candidate hashes, tool code. Keep human audit judgments in a **separate** `training/human_preferences` file; never copy them into AI preferences.
- Local provenance manifest, also outside Git: list each source document hash, distinct author/editor group, asset pool, and rights information. Do not store source-page contents or licensed reference artwork in the generated bridge output.

## 1. Extract objective profiles without re-analyzing the 1,064 pages

```powershell
python -m tools.design_learning.reference_sampling bridge `
  --graphs 'D:/Dynamic-PDF-Design-References-analysis/grammar/page-composition-graphs.json' `
  --coverage 'D:/Dynamic-PDF-Design-References-analysis/grammar/full-corpus-coverage.json' `
  --out 'D:/Dynamic-PDF-Design-References-analysis/grammar/reference-feature-profiles-v1.json'
```

`--coverage` is optional. Supply the **actual coverage path** from your analysis directory; if it is missing, omit the option. The builder validates page IDs, per-document page counts and normalized ratios. Output includes only anonymous document IDs, reference page-family frequencies, cluster-adjusted weights, script directions and four numerical design proxies.

The four M7.7-to-M7.10 proxies are: `cover_image_share`, `image_share_mean`, `text_share_mean` and `pages_without_image_share`. Their names overlap, but their extractors have different treatment of text/geometry. **They are only coarse sampling/coverage guides until cross-render calibration exists.** Do not add reference observations to `ai-preferences.jsonl`, and do not substitute page-family classification for a visual preference.

## 2. Expand the balanced comparison pool

Generate a fresh batch **without overwriting historic keys or answers**. For example:

```powershell
python -m tools.design_learning preferences generate m710-003 --n 4 --baseline
python -m tools.design_learning preferences word m710-003
```

Build a fresh plan for Word and a separate plan for PDF. Word is a real Microsoft Word export, not a LibreOffice substitute. The updated `preferences word` exporter records the source DOCX SHA-256 and Word-exported PDF SHA-256 for each file. Rerun it for new batches; legacy Word manifests without hashes are not accepted by the strict planner:

```powershell
python -m tools.design_learning.reference_sampling plan `
  --batch training/ai_preferences/batches/m710-003 `
  --dataset training/ai_preferences/ai-preferences.jsonl `
  --split training/document-split.json `
  --reference-features 'D:/Dynamic-PDF-Design-References-analysis/grammar/reference-feature-profiles-v1.json' `
  --source word --count 36 `
  --out training/ai_preferences/batches/m710-003/plan-word.json
```

Use `--source pdf --out .../plan-pdf.json` for PDF. The planner prioritizes scarce Arabic/bilingual documents, independent documents, own-baseline comparisons, strong *feature differences* and broader reference-feature strata. It does **not** predict a preferred side or convert a metric into a quality label. Each pair remains in its preassigned train/held-out family; any shared source hash across splits fails closed. It skips superseded/missing-feature variants, duplicate judged pairs, duplicate visual hashes and unavailable/hash-mismatched renders.

For a code-only machine without renders, `--metadata-only` will produce a **non-judgeable** metadata queue. That plan cannot be sent to `sheets` until proper PDF/Word renders are present and a fresh checked plan is produced. Its `summary.missing_media_pairs` is diagnostic, not usable training data.

After reviewing the plan's selection **internally**, create the blind sheets without showing `plan` or the keyed candidate identities to reviewers:

```powershell
python -m tools.design_learning preferences sheets m710-003 --source word --plan training/ai_preferences/batches/m710-003/plan-word.json
```

Plan-derived sheets use the existing blind recording flow and `key-word.json`. Reviewers see pages only; the file keyed to candidate names is kept separate. Follow the existing `preferences record` and `preferences check` workflow. Never re-run `sheets` with an existing key: use a fresh batch to avoid invalidating old judgments and hashes.

## 3. Preflight gate before training

```powershell
python -m tools.design_learning.reference_sampling audit `
  --dataset training/ai_preferences/ai-preferences.jsonl `
  --batches training/ai_preferences/batches `
  --split training/document-split.json `
  --human-audit training/human_preferences/audit.jsonl `
  --provenance 'D:/Dynamic-PDF-Design-References-analysis/grammar/source-provenance.json'
```

The same audit is enforced automatically by the CLI wrapper's `train` subcommand, with explicit local inputs:

```powershell
python -m tools.design_learning train --name ranker-future `
  --human-audit training/human_preferences/audit.jsonl `
  --provenance 'D:/Dynamic-PDF-Design-References-analysis/grammar/source-provenance.json'
```

**Do not run this training command with the current dataset.** It is shown only to document the future command's preflight contract and must refuse while the gate is incomplete.

The trainer calls the same audit first. The audit returns nonzero (2) when **any** requirement is missing; no LightGBM import or training run is attempted. The conservative initial quality policy requires: 200 verified usable comparisons, 8 training documents, 3 evaluation documents with >=40 held-out judgments, >=30 Arabic, >=30 bilingual, >=100 Microsoft-Word-reviewed, measured facts and matching immutable hashes for every usable pair, 20 separately recorded human audit decisions, and at least 3 independent author groups and asset pools with no cross-split reuse. These are project policy defaults for review, not industry-standard guarantees or proof of preference quality.

An independent human audit row is **not** an AI reviewer row. Example schema:

```json
{"batch":"m710-003","comparison":"w-001","document_hash":"<sha256>","reviewer_type":"human","reviewer":"Real reviewer name","review_date":"2026-11-06","preferred":"A","visual_evidence":"Word export, pages A2 and B2; reason for choice"}
```

The human reviewer must actually inspect the blind sheets and confirm provenance; do not auto-populate these rows from model output. The audit is a check of traceability and sample size, not an authenticity verification service.

A local source-provenance manifest uses:

```json
{"documents":[{"document_hash":"<sha256>","author_group":"writer-team-1","asset_pool":"licensed-assets-1","rights_status":"cleared"}]}
```

Document-level content hashes, author groups and asset pools must be truthful and independent between the existing held-out and training families. If there are not enough independent sources, collect additional genuinely different documents, instead of generating more pairs from the same 18 fictional ones. Update the family split **before new labeling** and keep the existing held-out families untouched. Human audits are for quality validation; the AI trainer continues to distill AI labels, not to misrepresent them as human preferences.

## Remaining local inputs, not in GitHub

1. M7.7 graph JSON and matching coverage/rights metadata for all 1,064 pages; the abstract feature bridge cannot recreate the 909 pages inspected only at contact-sheet depth.
2. Render PDFs and DOCX for a fresh batch, Word-exported PDFs with `word/word.json` recording Word build, assets and full-page blind sheets, plus a verified rendering environment.
3. More independently authored Arabic, bilingual and English content; distinguish source and asset pools and maintain different held-out families.
4. Actual human visual decisions with evidence, plus rights/usage checks for reference documents.
5. Cross-render measurement calibration for the common metrics. Until then reference metrics are used for **sampling only**, not for loss, labels, nor model inputs.

**Current verdict:** 85 usable pairs/200 minimum, 23 held-out, 14 Arabic, 17 bilingual, 34 Word and zero human audits; not ready. Do not train or publish a model.
