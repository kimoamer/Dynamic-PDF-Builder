# Plan: a learned selector that is used, and worth using

- **Repository:** `kimoamer/Dynamic-PDF-Builder`
- **Reviewed revision:** `48d0d96` (branch `claude/quirky-knuth-3f3mhw`; `main` is `ae2eb2f`)
- **Date:** 2026-11-16
- **Status:** plan only. This document changes no runtime code and trains nothing.
- **Continues:** M12 of `ADVANCED_INTELLIGENCE_PLAN.md` ("Learning that can pass its own gate").

## 1. Where it stands

Checked today in the repository, not taken from earlier reports.

| # | Finding | Evidence |
| --- | --- | --- |
| L1 | **No model exists and none runs.** `training/models/` holds a README only. LightGBM is not installed. Every choice is made by fixed rules and hand-set weights. | `ls training/models`; `intelligence/objective.py` |
| L2 | **A trained model could still not be used in the main path.** Only `design_variants(ranker_model=<path>)` can name one. `design(variants=...)`, which is what `export()` uses, does not pass it, and the CLI has no option for it. | `builder.py` (`_variant_set`), `cli.py` |
| L3 | **Two rankers that share nothing.** The composer has its own (10 layout metrics, its own trainer and label format, a 40-pair floor but no evaluation gate and no record). The variant ranker has 22 features and a strict gate. | `intelligence/ranker.py`, `scripts/train_ranker.py`; `intelligence/variant_ranker.py`, `scripts/train_variant_ranker.py` |
| L4 | **Loading needs LightGBM at run time.** It is an optional extra, so a shipped model would be dead weight for most installs. | `variant_ranker.py` `VariantRanker.load` |
| L5 | **The labels are thin.** 180 rows from one judge model. 85 are usable (ties, abstentions, 41 low-confidence rows and repeats are left out); 23 of them are held out. Only 69 carry the layout facts and hashes the preflight asks for, and none has a locally verified render. | `python -m tools.design_learning preferences readiness` |
| L6 | **The judge saw thumbnails.** Every row was judged on a contact sheet with pages 240 px wide. Only 30 of 180 answers are high confidence. | `shown_px` in `ai-preferences.jsonl` |
| L7 | **The judge may be rewarding what a thumbnail shows.** The winner had the more colourful cover in 40 of 50 pairs where covers differed, more type sizes in 46 of 62, more opening pages in 33 of 48. `executive_premium` won 32 of 43; `editorial_modern` 15 of 47. No person has checked whether this is taste or an artefact. | readiness report, `signals` |
| L8 | **The corpus is narrow.** 18 fictional documents by one author, sharing five pictures, in seven families. | `training/document-split.json`, readiness report |
| L9 | **Half the features describe the plan, not the page.** Cover and band flags, counts of grammar rules and refinements. The 29 measured layout facts recorded for each candidate are not read by the LightGBM trainer, and the per-criterion answers (hierarchy, rhythm, whitespace ...) recorded on 154 rows are read by nothing. A direction added later (`academic_paper`) is invisible to flags. | `variant_ranker.FEATURES`; `candidates.jsonl`; `criteria` in the rows |
| L10 | **The booster is set up to memorise.** 80 rounds, no validation, no early stopping, no monotone constraints, no calibration. The weights model beside it does have constraints. | `scripts/train_variant_ranker.py` `train` |
| L11 | **The gate's margin is smaller than its noise.** It asks for +0.03 agreement over the fixed selector on 40 held-out comparisons. At 40 comparisons the 95% interval of an agreement rate is about ±15 points. A pass or a fail could be chance. | `GATE` in the trainer; binomial interval |

## 2. Targets

**Used** means: a gated model ships inside the wheel as a small JSON file, is evaluated by
plain Python with no LightGBM at run time, and is the selector wherever variants are produced,
including `export()` and the CLI. It overrides the fixed rule only when it is confident, says so
in the result, and can be switched off with one argument.

**More intelligent** means: it learns from judgments made on real pages by more than one judge,
anchored by people; from measured facts, with the kind of document as context; and it can say
which criteria carried a choice.

**More powerful** means: the same learned score decides at every point where the engine
chooses (variants, refinements, layout candidates), and then drives a search over more designs
than the six presets.

## 3. Rules kept

1. Author content is never altered. The model only orders designs that passed the hard gates.
2. Offline, deterministic, CPU-only at run time. One package version gives one output.
3. AI judgments are never recorded as human ones. Human rows are for evaluation, not training.
4. A model that fails its gate ships nothing. Finishing training is not a reason to deploy.
5. No training on the current 85 comparisons.

One existing rule changes, and only with the owner's decision (section 6, decision 1): today a
model loads only when a caller names it.

## 4. Roadmap

Sizes follow the other plan: S up to a week, M two to three weeks, L four to six, for one
engineer. Thresholds under "Done when" are proposals to confirm against the M17 pilot.

### M16. A model slot that can be used (S; code only, no data needed)

- **One feature function** over `PageFacts` and the document's context (type, script, length,
  table and figure density). Both trainers, the dataset and the scoreboard read it. Plan
  descriptors leave the feature list (L9).
- **Inference without LightGBM.** Train with LightGBM, export `dump_model()` as JSON, walk the
  trees in the package (about 40 lines). The `ranker` extra becomes a training-only extra (L4).
- **One argument, `ranker=`:** `"off"`, `"auto"` (the packaged model, if it passed its gate) or
  a path. On `design_variants()`, `design(variants=...)` so that `export()` gets it,
  `compose()` and the CLI (L2). Default `"off"` until M19.
- **Selective use.** The learned choice replaces the fixed one only when its win probability
  over the fixed choice clears a threshold stored in the model's record. Otherwise the fixed
  rule stands and the result says the model abstained.
- **Reasons.** The selection report gives the margin and the facts that moved it most.
- **One ranker.** The composer's separate ranker, trainer and label format fold into this slot (L3).
- The scoreboard reports which selector chose, how often it overrode and how often it abstained.

Done when: with a fixture model (marked as one, refused outside tests) `export()` and the CLI
deliver the learned choice end to end and report it; with `ranker="off"` every fixture renders
byte for byte as today; the tree walker matches LightGBM's own predictions on 1,000 random
vectors; rendering never imports LightGBM.

**Progress (2026-11-16): done.** Each point is tested in `tests/test_m16_selector.py`.

- `intelligence/variant_ranker.py` is the one slot: 47 measured facts (`FEATURES`), the
  document's context (`CONTEXT`, recorded once a document in `stats["context"]` and in new
  `candidates.jsonl` rows), both model kinds, the checks on a record, and `choose`.
- A model is one JSON file. The trainer exports LightGBM's trees into it; the package walks
  them. On 1,000 random vectors the walker and LightGBM differ by less than 1e-9, and an
  80-tree model is 25 KB. A subprocess test uses a tree model with LightGBM made unimportable.
- `ranker=` is on `design_variants()`, `design()` (so `export()` and `render()`), `compose()`
  and the CLI (`--ranker`). `"auto"` finds no packaged model yet and says so.
- The model abstains below its record's `override_threshold` (0.6 until M18 calibrates it),
  and a choice it makes lists the facts that moved it.
- The composer's separate ranker, `scripts/train_ranker.py` and `scripts/collect_preferences.py`
  are gone; `compose("smart", ranker=...)` uses the same slot on the layout facts.
- The scoreboard reports, for the three-variant pass, how often a model chose, overrode,
  abstained or was refused, and takes `--ranker`.
- With no model, or `ranker="off"`, or a refused model, output is byte for byte as before.

Not done here, by design: no model is trained or packaged, the booster's training settings
(L10) and the gate (L11) are unchanged until M18.

### M17. Labels worth learning from (M elapsed; mostly unattended)

- **Judges see pages, not thumbnails** (L6). Each comparison sends the two designs as PDFs or
  as page images at least 1,000 px wide. The answer keeps today's schema: preference, the nine
  per-criterion signs, confidence, the pages that decided it.
- **Two judges of different models**, every pair repeated with sides swapped. Agreement
  between judges and each judge's position bias are reported. Rows stay `reviewer_type: "ai"`.
- **A pilot of 20 comparisons first.** It measures cost, the share of high-confidence answers
  and agreement between judges. The large run starts only if both rise against today.
- **Cover control** (L7). A quarter of the comparisons are judged without the cover page, and
  win rates are reported with and without. If the cover alone decides, the rubric changes
  before more is spent.
- **Corpus from 18 to at least 60 documents**, in three or more independent author groups and
  asset pools, a third of them Arabic or bilingual (L8). In order of value: the owner's real
  documents, anonymised; open-licence documents with the licence recorded; the existing set.
  One provenance manifest covers all of them, as the preflight requires.
- **A human anchor: 60 A/B decisions** on the local page (`preferences judge`), about an hour.
  Half from pairs the judges agreed on, half from pairs they split on. Evaluation only.
- **Sanity pairs without a judge.** A valid design against a copy with one soft fault put in
  (page-break search off, a table parted from its lead-in, the tightest allowed leading).
  Marked `synthetic`, low weight in training, never in evaluation.
- **Word pages** from the owner's Windows machine, as the preflight requires (decision 3).

Done when: the preflight audit reports ready; at least 400 usable comparisons, 150 of them
held out across 10 or more documents; judges agree on 75% of clear answers; judges agree with
people on 70% of the anchor; half the answers or more are high confidence.

### M18. A first model through an honest gate (S to M)

- **The ladder stays:** fixed selector, then calibrated monotone weights, then LightGBM, kept
  only if it beats the weights. With a few hundred comparisons the weights will probably match
  the booster; LightGBM earns its place once context lets it learn that a financial statement
  and a photo feature want different things. That is an expectation, not a measurement.
- **LightGBM for small data** (L10): monotone constraints on facts whose direction is known,
  at most 7 leaves, at least 20 rows a leaf, feature subsampling, L2, early stopping inside
  cross-validation grouped by family. Context enters beside the differences. Predictions are
  made antisymmetric, so preferring A to B is exactly not preferring B to A.
- **Reference typicality as features**, if the owner exports the anonymous profile numbers of
  the 1,064 reference pages: how far a design sits from what professional documents of its
  kind measure. Knowledge from references without using them as labels.
- **Per-criterion models** from the nine signs already recorded (L9). They supply the reasons.
- **Calibration and the abstention threshold**, set on out-of-fold predictions so that at
  least 70% of overrides are right.
- **The gate, replacing +0.03 on 40 comparisons** (L11):
  - lower 95% bound of (learned minus fixed agreement) above zero, by paired bootstrap over
    documents, on 150 or more held-out comparisons;
  - agreement of 0.60 or more (kept);
  - an override test: where the two selectors pick different designs on held-out documents,
    the two picks are compared directly; the learned pick wins 60% or more with the judges
    and is not below 50% with people;
  - 95% or more of the sanity pairs;
  - no language or family worse than the fixed selector beyond its interval.
- **The record** holds the data hash, the `PageFacts` version, fold scores, intervals, slices
  and library versions.

Done when: the gate passes and the model ships in the wheel under 200 KB with its record; or
it fails, and the report names the check and the data that would change it.

### M19. On by default, and one score everywhere (M)

- After decision 1, `ranker="auto"` is the default wherever variants are produced.
  `ranker="off"` restores the fixed rule.
- **Refinements:** a trial is kept when the model prefers it to the current render by the
  margin. Today the rule is fault count, then the visual index.
- **Layout candidates:** `compose("smart")` chooses by the same score. This closes the item
  M9 left open.
- **Direction prior:** the hand-set table of purpose by direction (`_FIT`) becomes a prior
  that counted wins update, with smoothing, and the result reports it.
- Scoreboard budgets cover override rate, abstention rate and the last measured override win rate.

Done when: the scoreboard shows the learned selector in use within budgets; documents without
variants render as before; the override win rate holds on a fresh batch judged after the
switch and never used in training.

### M20. Search, and a loop that keeps learning (L)

- **Search beyond six presets.** Candidates are a direction with bounded parameters (density,
  opener, table style, cover kind, columns, image policy), all inside the reviewed standard.
  Many are screened by forecast with a small pre-render model, the best few are rendered
  within today's render budget, and the learned score chooses. The gates do not change.
- **The loop.** `accept()` and the A/B page feed a scheduled retrain, the gate, and the next
  release's model. New judge pairs are drawn where the model is least sure.
- **House style.** A per-brand prior from accepted designs, stored with the brand kit.
- A `PageFacts` version change refuses the old model and starts a retrain.

Done when: on held-out documents the searched design beats the best preset in 60% or more of
judged comparisons at no more than 1.5 times the three-variant time; a retrain from logged
accepts runs end to end with no manual step.

## 5. Order, time and cost

```text
M16 -> M17 -> M18 -> M19 -> M20
```

M16 needs no data and no decision, so it starts first. M17 is the long pole because it waits
on documents, people and Word.

Judging cost is an estimate from one measurement: today a request carrying a one- or two-page
PDF used about 4,000 input tokens. A comparison of two four-page designs is then about 20,000.
At list prices through Message Batches, one judgment costs about $0.045 on Opus 5.5 and $0.022
on Sonnet 5.5. A comparison judged by both models in both orders is about $0.13, and 800
comparisons $100 to $200 depending on how much the judges write. The pilot measures the real
figure. The run needs a long-lived API key kept as an environment secret.

## 6. Decisions for the owner

1. **May a packaged model be on by default?** Recommended: yes, after the M18 gate, with
   abstention and `ranker="off"`. Until then it is opt-in with `ranker="auto"`.
2. **Who gives the 60 human decisions?** They are what the model is finally checked against.
3. **Word.** Can the Word export run on the Windows machine for 100 or more comparisons, or
   does version one accept LibreOffice pages with a note?
4. **Documents.** May real documents of the owner enter the corpus, anonymised? Which
   open-licence sources are acceptable?
5. **Budget and key** for the judging runs.

## 7. Risks

- **The student cannot beat its teachers.** The model distils AI judges. The human anchor, two
  judges and the override test bound that; they do not remove it.
- **Judge bias** towards covers and colour (L7). Cover-masked comparisons and slice reports
  are there to catch it; the rubric may need rework after the pilot.
- **Small data.** Monotone weights first, intervals in the gate and abstention keep a weak
  model from deciding.
- **A default that changes output.** Mitigated by one switch, a version-pinned model and
  goldens for the single-design path.
- **Upkeep.** Every `PageFacts` change invalidates the model; M20's retrain job is the answer.

## 8. Not in this plan

- Training on today's 85 comparisons.
- A neural model over page images. It would need a large dependency or a GPU.
- Letting a model override a hard gate or change content.
- Using reference PDFs as quality labels. They stay grammar and anonymous profiles.
