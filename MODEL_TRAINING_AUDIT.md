# Dynamic PDF Builder: Local Model and Training Audit

**Date:** 2026-11-05
**Code audited:** branch `claude/m7-9-art-direction` at `0dc6a16`. Its tree (`ee23609`) is identical to `origin/main` at `b72fe10`, the merge of PR #17.
**Method:** read-only. Nothing was trained, installed, replaced or labelled. Production ranking was not changed. GitHub CI was ignored, as requested.

## Verdict

**No LightGBM model exists, and none has ever been trained.** There are no human preference labels, and LightGBM is not installed. The repository contains ranker code only. Every M7.9 selection comes from hand-written rules and page measurements.

| State | Result | Evidence |
|---|---|---|
| Trained | **No** | No model file on disk or in git history; 0 labelled pairs; LightGBM absent |
| Validated | **No** | Nothing to validate; no validation report exists |
| Integrated | **Code path only** | Optional, opt-in `ranker_model` in `compose("smart")`. Tested with fake rankers. A real booster has never run through it |
| Actively used | **No** | No default enables it, and `design_variants()` never calls it |

| Question | Answer |
|---|---|
| Model path, size, creation date, format, SHA-256 | Not applicable: no model exists |
| LightGBM installed | No |
| `PreferenceRanker.load()` | Fails with `RankerUnavailable: lightgbm is not installed` |
| Labelled pairs / distinct documents | 0 / 0 |
| `compose("smart")` and `design_variants()` share a selection path | No: they are separate |
| Features compatible with M7.9 | Keys yes, meaning no. A model trained on M6 candidates would be out of distribution |
| M7.9 local tests | 802 passed, 1 skipped, 4 failed on a harness path issue; those 4 pass when `soffice` is resolved (see section 7) |
| M7.7 deliverables | All 5 required files are missing |

## 1. Paths inspected

| Location | Looked for | Found |
|---|---|---|
| Worktree, including untracked files | Directories named `*train*`, `*model*`, `*rank*`, `*preference*`, `*lightgbm*`, `*lgb*` | No such directories |
| Main checkout `D:\Packages\Dynamic PDF Builder` (at `c18af4f`, behind `main` by 15) | Same names, plus untracked `.claude-flow/`, `.swarm/` | No such directories, no model files |
| All of `D:\Packages`, including worktrees and venvs | `*.lgb`, `*.lgbm`, `*.joblib`, `*.pkl`, `*.model`, `*.onnx` | No LightGBM ranker model |
| All `*.txt` under 3 MB in `D:\Packages` and the analysis folder | LightGBM text header (`tree` first line) | None |
| `D:\Dynamic-PDF-Design-References-analysis` | Model, pair and preference files | None |
| User Downloads, Documents, Desktop | `pairs*.csv`, `*human*pref*`, `*preferences*.json`, `*.lgb`, `*.lgbm`, `model*.txt`, `*ranker*` | None |
| Git history, all refs | `*.lgb`, `*.lgbm`, `models/*`, `*.csv`, `*pairs*`, `*model*.txt` | Never added |

The only untracked file in the worktree is `tools/reference_analyzer/review_sheets.py`, which builds contact sheets and has no training role.

Not searched: other folders on `C:`, other folders on `D:`, external drives and cloud storage. A model stored there would not appear in this audit, though nothing in the repository refers to one.

## 2. Ranker code that exists

| File | Role | SHA-256 |
|---|---|---|
| `dynamic_pdf/intelligence/ranker.py` | `PreferenceRanker`, 10 features, 2 MiB limit, `load_optional` | `40a68154…1c9e` |
| `scripts/train_ranker.py` | Trainer: minimum 40 pairs, document-grouped CV, `LGBMClassifier` | `9963463f…aab6` |
| `scripts/collect_preferences.py` | Generates contact sheets and an unlabelled `pairs.csv` | `bc43339d…2a62` |
| `benchmarks/m7/human_preferences.template.json` | Empty template, 135 bytes | `9408fc89…801a` |

`pyproject.toml` declares the optional extra `ranker = ["lightgbm>=4.0"]`; it is not part of `all`. `ranker.py` itself says that no model ships with the library.

## 3. LightGBM and model loading

- `import lightgbm` raises `ModuleNotFoundError`, and `pip show lightgbm` finds nothing.
- No `lightgbm*` directory exists under AppData Python, Roaming Python or uv, or the `D:\Packages` venv.
- `PreferenceRanker.load("no-such-model.txt")` raises `RankerUnavailable: lightgbm is not installed`.
- `load_optional("no-such-model.txt")` returns `None`.

**Limit of this result:** `load()` imports LightGBM before it looks at the file, so this proves only the missing-dependency branch. Successful loading is untested, here and in the test suite.

**Gap in `load()`:** it compares `feature_names` only when that line is present, so a model file without the line would skip the feature check.

## 4. Training dataset and history

| Source | Content |
|---|---|
| `benchmarks/m7/human_preferences.template.json` | `reviewer: ""`, 0 judgments |
| `human-curation.json` (format `m75-human-curation`) | 0 decisions |
| `ai-design-curation.json`, `layout-archetypes.json` | `human_approved: false`, `human_review: "none"` |
| `docs/m74` results | `human_review.status: pending`, 0 judgments |
| `docs/m78` results | `human_review: none` |

- **Labelled pairs:** 0. **Distinct labelled documents:** 0.
- **Provenance:** none, because there are no labels. AI assessments exist, but they are AI assessments and must not be used as human labels.
- **Training history:** none. There is no log, metric report or model artifact. `train_ranker.py` would stop at import without LightGBM, and it saves no training record even when it succeeds.
- **Dry run:** `collect_preferences.py` produced 176 pairs over 18 documents, all with `preferred` empty. Candidates were `baseline`, `balanced`, `compact`, `editorial` and `data`. The output stayed in the session scratch folder.

**Design gaps that would affect real labelling:**

1. There are two disconnected label channels. `benchmarks/m7/preferences.py` reads JSON with a reviewer, comparing baseline with smart. `train_ranker.py` reads CSV. Neither feeds the other.
2. The CSV has no reviewer, timestamp or source column, so a trained model could not prove where its labels came from.
3. The trainer stores no record of its data hash, fold scores or library version.

## 5. Selection paths

`compose("smart")` and `design_variants()` are separate.

```text
compose("smart", ranker_model=None)          builder.py:183
  composer._select                           composer.py, about line 421
    best = max(eligible, key=adjusted)       deterministic
    _apply_ranker                            about line 461
      no ranker_model      -> best           default path
      model or lib missing -> best + fallback note
      model loaded         -> ranker.rank(), eligible layouts and valid baseline only

design_variants(...)                         builder.py:340
  variants.generate_variants                 no ranker import
    best = max(valid, key=fit * 6 + index)   rules and page measurements
```

`_apply_ranker` is the **only** place learned ranking is invoked.

| Fresh process | `ranker` module imported | `composer` imported | LightGBM imported |
|---|---|---|---|
| `design_variants()` | No | Yes (not used for selection) | No |
| `compose("smart")` | No | Yes | No |
| `compose("smart", ranker_model=...)` | Yes, then fallback note | Yes | No |

A counting stub, patched in-process only, gave this:

| Call | `load` calls | `rank` calls |
|---|---|---|
| `compose("smart", ranker_model="stub")` | 1 | 1 |
| `design_variants()` | 0 | 0 |
| `design_variants()` after `compose` set the option | 0 | 0 |

**Consequence:** training a model today would not change `design_variants()` at all.

**Test coverage:** `tests/test_m6_composer.py` covers the fallback, and `tests/test_m61_scoring_safety.py` uses a fake ranker to prove it cannot leave the eligible set. No test covers `rank()` with a real booster, `train_ranker.py` or `collect_preferences.py`.

## 6. Compatibility with M7.9

**Keys are compatible.** All 10 features are present on all 36 M7.9 candidates.

**Candidate types are not.** Training candidates are M6 presets. M7.9 candidates are 5 art directions with covers, openers and rhythm. `collect_preferences.py` has no route to produce M7.9 pairs.

**Distributions differ.** This compares 14 valid M6 candidates with 36 M7.9 candidates on the same 12 documents:

| Feature | M6 range | M7.9 range | M7.9 outside M6 range |
|---|---|---|---|
| `utilization` | 0.833–1.000 | 0.495–0.896 | 31/36 |
| `balance` | 0.618–1.000 | 0.336–1.000 | 3/36 |
| `efficiency` | 0.750–1.000 | 0.625–1.000 | 3/36 |
| `readability` | 1.000 | 0.682–1.000 | 17/36 |
| `typography` | 1.000 | 1.000 | 0/36 |
| `placement` | 0.600–1.000 | 0.850–1.000 | 0/36 |
| `tables` | 1.000 | 1.000 | 0/36 |
| `wasted` | 0–0.173 | 0–1.012 | 8/36 |
| `pages` | 2–6 | 2–9 | 2/36 |
| `cpl` | 85.4 | 72.5–112.1 | 36/36 |

Fourteen candidates are a small base, and `cpl` has only one M6 value, so its 36/36 says little. The direction is still clear: M7.9 deliberately gives up utilization for covers and whitespace, which M6-era features would read as waste.

**Features miss what M7.9 changes.** They do not describe covers, rhythm, imagery, headers and footers, typefaces or the `visual_critique` heuristics. Within a document, `typography` and `tables` take one value, so they carry no signal there. No two designs in the 36 within-document pairs had identical vectors (mean 5.78 of 10 features differ), so vectors do separate designs, but that does not show that they capture preference.

**The two selectors disagree.** The top design by `score_layout` matches the M7.9 recommendation in only 4 of 12 documents. Neither has human validation, so this does not show which is better.

## 7. M7.9 verification

| Check | Result | Run |
|---|---|---|
| Full test suite | 802 passed, 1 skipped (`pikepdf` missing), 4 failed | Rerun for this audit |
| The 4 failures | All `test_docx_opens_and_converts_in_libreoffice`, with `FileNotFoundError`: Windows `subprocess` could not launch the bare name `soffice` through the Docker shim. With the path resolved, `tests/test_pdf_docx_parity.py` gives 35 passed, including these 4 | Rerun for this audit |
| Benchmark, 12 documents | 36 of 36 valid, 0 rejected, 0 fallbacks, 36 of 36 DOCX converted in LibreOffice | Rerun for this audit |
| Default output against `main` | 30 of 30 match; PDF 39.6 s to 37.2 s, DOCX 27.1 s to 27.3 s | M7.9 work, before commit; not repeated |
| Numbers in PDF and DOCX | 849 checks over 36 candidates, 0 missing in either | This audit |
| Chart data | `data`, `title`, type and labels identical in 36 of 36; only `colors` and `height` differ, by design | This audit |
| Arabic marks | 170 in source; no candidate short in DOCX | This audit |
| DOCX structure | All 36 have tables and headings; at most 5 media files, none a page raster | This audit |
| Microsoft Word | **Not run.** DOCX was checked in LibreOffice 24.2.7.2 only, which does not prove Word compatibility | n/a |
| Human review | **None.** All visual notes are AI assessments | n/a |

The content checks walk source blocks directly instead of relying on the M7.9 content ledger. The number check is a substring match, so `4` can be satisfied by `14`, which makes it weaker than exact token matching. The 849 is a sum of per-document unique numbers across three designs, not 849 distinct numbers.

### Known visual regressions

These are measurements and AI observations, not quality verdicts.

**Last page at least 60% blank: 8 of 36.**

| Document | Design | Last-page words | Blank share |
|---|---|---|---|
| `annual_report` | `financial_data` | 65 | 0.676 |
| `research_paper` | `financial_data` | 45 | 0.735 |
| `proposal` | `corporate` | 50 | 0.706 |
| `impact_report` | `executive` | 37 | 0.676 |
| `policy_brief` | `corporate` | 40 | 0.735 |
| `policy_brief` | `editorial` | 26 | 0.706 |
| `arabic_annual` | `arabic_institutional` | 40 | 0.618 |
| `sustainability` | `financial_data` | 57 | 0.647 |

- **Last page with 70 words or fewer:** 15 of 36. Word count alone overstates this, because such pages can hold images or tables.
- **Sparse mid-document page:** `arabic_annual` editorial, page 4.
- **Page growth of 1.5× or more against the plain render:** `annual_report` executive 9/6; `research_paper` executive 5/3; `policy_brief` corporate and editorial 3/2; `arabic_annual` institutional 6/4, executive 8/4, editorial 6/4; `arabic_financial` corporate 3/2.
- **Other known items:**
  - The annual report editorial crop clips the moon.
  - DOCX Arabic slabs are inset rather than bleeding to the edge.
  - Some designs differ in page count between PDF and DOCX.
  - The existing numbered-heading feature places the digit wrongly in RTL.
  - The research paper shows "References" twice.
  - Amiri is the only bundled Arabic face.
  - `n=5` returns 4 designs for LTR documents.

## 8. Corrections to earlier reports

- **Short last pages:** PR #17 and `docs/m79-art-direction/README.md` named only `policy_brief` and `proposal`. The measured list above has 8 designs across 7 documents.
- **Page growth:** PR #17 mentioned only `arabic_annual` executive. There are 8 designs at 1.5× or more.

## 9. M7.7 design grammar

**M7.7 was never delivered.** `git log --all --grep='M7.7'` is empty. Each of these files is absent from disk and has no commit:

| Required deliverable | State |
|---|---|
| `full-corpus-coverage.json` | Missing |
| `page-composition-graphs.json` | Missing, and no page-level composition graph was built |
| `design-grammar.json` | Missing |
| `layout-family-catalog.json` | Missing |
| `design-learning-report.md` | Missing |
| M7.7 PR | None |

**Partial work that exists, all local:**

- `tools/reference_analyzer/review_sheets.py`: untracked, never committed.
- `visual/review-sheets/` in the analysis folder: 133 sheets, 13 documents, 1,064 page slots.
- `review-notes.txt`: covers **1,024 of 1,064 pages**, marked as AI assessment. 75 of its lines cover several pages each, so a page having a note does not mean it received its own note.
- **40 pages have no valid note:** sheets 129–133, in `BI-04-Academic` (16), `Cedarline Contracting`, `Clearpath Cleaning` and `Northbay Facilities` (8 each).
- `review-notes-unverified.txt`: 288 pages, quarantined because it was written while the sheet image was unavailable. Every one of those pages also has a note in `review-notes.txt`, so the quarantine does not reduce the count above. The quarantined file must not be used as evidence.
- Pages on the sheets are shown at about 454×642 from sources of about 1100×1557. Whether that meets the spec's "readable resolution" has not been established.
- `layout-archetypes.json` (7 archetypes), `ai-design-curation.json` (39 selected) and `pattern_review.json` exist from M7.5.

**Also open:** `editorial_sink` and `figure_matrix` are not implemented, and `image_slab_divider` is partial. The runtime cannot read grammar files; design principles exist only as hand-written rules.

## 10. Recommended next steps

Nothing below was done in this audit.

1. **Finish M7.7 first.** Review the 40 missing pages, build the composition graphs, then write the five deliverables. It needs no human labels and informs which features matter.
2. **Decide what learned ranking should choose.** It could rank M7.9 designs, M6 layouts or both. This decides everything below, and today's model slot cannot affect M7.9.
3. **Unify the label format before collecting labels.** Use one channel with reviewer, timestamp, source and tool version on every judgment, and keep AI assessments in a separate field that the trainer rejects.
4. **Add M7.9 pairs to `collect_preferences.py`,** using the gallery's 36 designs and showing whole documents to reviewers.
5. **Collect real human judgments.** The trainer's floor is 40 pairs; that is a refusal limit and does not guarantee a useful model. Twelve documents is also a narrow base for document-grouped validation.
6. **Extend features before training,** using cover, rhythm, imagery and critique measurements. Revisit `utilization` and `cpl`, which M7.9 moved furthest.
7. **Harden the trainer and loader,** and write a training record (data hash, fold scores, library versions). Make `load()` reject files without `feature_names`. Add a test with a tiny synthetic booster, clearly marked as a test fixture.
8. **Only then train, as a separate approved phase,** and report it against the rules-based selector on held-out documents. Connect it to `design_variants()` as opt-in, with the existing validity gates still deciding what is eligible.
9. **Separately:**
   - Open the DOCX files in Microsoft Word.
   - Have a person review the gallery.
   - Reduce the 8 near-empty last pages.
   - Correct the short-last-page and page-growth statements in `docs/m79-art-direction/README.md`.

## 11. Commands executed

Paths are shortened. `$S` is the session scratch folder; its audit scripts are temporary and not part of the repository.

```bash
# State and history
git status --short
git rev-parse HEAD^{tree} origin/main^{tree}
git log --all --oneline -- '*.lgb' '*.lgbm' 'models/*' '*.csv' '*pairs*' '*model*.txt'
git log --all --oneline --grep='M7.7'
git log --all --oneline -- dynamic_pdf/intelligence/ranker.py scripts/train_ranker.py

# Files on disk
find /d/Packages /d/Dynamic-PDF-Design-References-analysis \
  -iname '*.lgb' -o -iname '*.lgbm' -o -iname '*.joblib' -o -iname '*.pkl' -o -iname '*.model' -o -iname '*.onnx'
find <repo> -type d \( -iname '*train*' -o -iname '*model*' -o -iname '*rank*' -o -iname '*preference*' -o -iname '*lgb*' \)
sha256sum dynamic_pdf/intelligence/ranker.py scripts/train_ranker.py scripts/collect_preferences.py

# LightGBM and loading
python -c "import lightgbm"
python -m pip show lightgbm
python $S/audit1.py        # load, fresh-process imports, stub counts, features, last pages

# Dataset
python scripts/collect_preferences.py $S/prefs   # unlabelled dry run, scratch output only

# Analysis
python $S/audit2.py        # feature ranges and vector differences
python $S/audit3.py        # numbers, chart data, Arabic marks, selector agreement
python $S/audit4.py        # chart blocks compared field by field

# Tests and benchmark, with LibreOffice through Docker
python $S/withlo.py $S/fullpytest.py
python $S/withlo.py $S/lotest.py     # same parity tests, soffice path resolved
python $S/withlo.py benchmarks/m79/run.py $S/g7 --no-memory
```

## 12. Changes made by this audit

This file is the only addition to the repository, and it is not committed. Scratch output stayed in the session temp folder. No PDF, preview or extracted content was added to the repository.
