# M7.4 evidence-based design recipes

Three opt-in recipes built only from patterns accepted in
[`pattern_review.json`](../../tools/reference_analyzer/pattern_review.json), compared with the existing design
on identical content. **All three stay `inconclusive`:** no human has reviewed them, so `design()` and
`design(recipe=...)` keep the existing design until one is activated. Every document here is fictional; no
reference page, logo or artwork is used.

* [`gallery/index.html`](gallery/index.html): blind A/B/Tie review of the rendered pages. Open it locally.
* [`report.md`](report.md): per-document metrics. [`results.json`](results.json): the same facts, machine-readable.

```bash
python benchmarks/m74/run.py OUT_DIR
python benchmarks/m74/preferences.py validate FILE.json
python benchmarks/m74/preferences.py summary docs/m74-evidence-recipes/results.json FILE.json
```

## Results

| recipe | documents | safety failures | status | why |
|---|---|---|---|---|
| Financial / Corporate | 2 | 0 | inconclusive | no measured gain; readability score falls; a heading separates from its table |
| Editorial / Executive | 3 | 0 | inconclusive | columns used on one fictional briefing only; the proposal loses body size |
| Arabic / Bilingual | 4 | 1 | inconclusive | safe on three; the long Arabic report goes from 20 to 25 pages and falls back |

## Recipe changes

Accepted into the proposed recipes, pending human review:

* Editorial: 10 pt / 1.38 leading and balanced two-column runs of long prose. On the briefing, chars per line go
  from 109 to 48, with the same page count and no new QA findings. Columns are real Word columns in the DOCX.
* Arabic / Bilingual: 12 pt / 1.4 leading. Harakat counts and line order are unchanged on all four documents.

Rejected or withdrawn:

* H1 at 2.75× for Arabic / Bilingual: withdrawn. It added a table split, wrapped bilingual headings mid-phrase and
  overlapped the Arabic cover subtitle.
* Financial compact leading of 1.25 and the 2.75× H1: kept as a proposal only. No page or table split is saved, the
  statement table splits after fewer rows, and the segment table moves away from its heading.
* Multi-column Arabic: not attempted, because the column flow is left-to-right only.
* Margins, table padding, whitespace, Arabic spacing and facing pages: not applied. No accepted evidence or signal.

## Activating a recipe

A recipe needs passing safety checks, rendered DOCX pages and exported human judgments that favour it. Then set
`status="active"` in `EVIDENCE_RECIPES` and rerun the comparison. The per-document gate still falls back when a
document fails: hard layout errors, more split tables, or pages above the baseline plus 15% (at least one page).

## Limitations

* DOCX pages are missing from the committed gallery: this machine has no LibreOffice, so DOCX QA reads `unverified`.
  CI renders them on Python 3.12 and uploads the full gallery as the `m74-comparison` artifact.
* No human judgment exists. The readability score is an engine heuristic, not a measure of quality.
* Columns reach 48 chars per line, below the scoring's 55 ideal. Only one document has a long enough prose run.
* A recipe run takes about twice as long as the baseline, because the gate renders both designs. This applies only
  when a recipe is requested; the default path is unchanged.
* The bilingual proposal still wraps one H1 and drops mean body page fill from 0.83 to 0.71.
* The Arabic chart title is garbled in both variants, and the 0 pt overflow findings on the annual report exist in
  the baseline too. Both are older defects, not caused by a recipe.
