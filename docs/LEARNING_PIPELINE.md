# Learning pipeline

```text
Reference PDFs → Design Grammar → Generate Variants → Claude Visual Review
    → AI Preference Dataset → Train LightGBM → Evaluate → Optional Deployment
```

Production needs none of this. The engine runs offline on CPU, with no API call. It reads one
small packaged file when a caller asks for the grammar, and it reads a model only when a caller
names one. Everything else on this page is offline work.

Commands run from the repository root. In the main checkout that root is
`D:\Packages\Dynamic PDF Builder`. Folder paths come from
[`config/design-learning.json`](../config/design-learning.json); `DPB_LEARNING_CONFIG` or
`--config` points at another file. `python -m tools.design_learning paths` prints what is in use.

## Directory map

| What | Where | In Git |
| --- | --- | --- |
| New PDFs waiting to be imported | `D:\Dynamic-PDF-Design-References\00-Inbox` | No |
| Original reference PDFs | `D:\Dynamic-PDF-Design-References\01-English`, `02-Arabic`, `03-Bilingual`, `04-Design-Inspiration` | No |
| Reviewed reference metadata | `D:\Dynamic-PDF-Design-References\05-Reviewed` | No |
| Measurements, atlas, previews | `D:\Dynamic-PDF-Design-References-analysis` | No |
| Contact sheets and review notes | `D:\Dynamic-PDF-Design-References-analysis\visual\review-sheets` | No |
| Page graphs, detail notes, import log | `D:\Dynamic-PDF-Design-References-analysis\grammar` | No |
| Evidence gallery with reference pages | `D:\Packages\M77_Design_Grammar_Review\index.html` | No |
| Rule definitions | `tools/reference_analyzer/grammar_rules.py` | Yes |
| Reviewed grammar and families | `docs/m77-design-grammar/` | Yes |
| Approvals record | `docs/m77-design-grammar/grammar-approvals.json` | Yes |
| Approved grammar read at runtime | `dynamic_pdf/design/approved_grammar.json` | Yes, in the wheel |
| AI preference rows | `training/ai_preferences/ai-preferences.jsonl` | Yes |
| AI batch records | `training/ai_preferences/batches/<batch>/` | Candidates, key and notes only |
| AI batch renders and sheets | `training/ai_preferences/batches/<batch>/renders`, `assets`, `sheets` | No |
| Future human preferences | `training/human_preferences/` | Rows yes, never mixed with AI rows |
| Training and evaluation split | `training/document-split.json` | Yes |
| Trained models and their records | `training/models/` | No |

Keep copyrighted PDFs and full-page previews out of the repository. Only the abstract grammar
and configuration enter it: no page text, artwork or complete page arrangement.

## Runtime and offline

| Runtime | Offline |
| --- | --- |
| `approved_grammar.json`, only with `grammar=True` | PDFs, analysis, graphs, review notes |
| A model file, only with `ranker_model=<path>` | Preference rows, batches, the trainer |

Without those arguments `design_variants()` behaves exactly as it did in M7.9. Nothing is
loaded from `D:\`, `training/` or `docs/` at runtime.

```python
made = builder.design_variants(n=4, brand=brand, grammar=True)
made = builder.design_variants(n=4, brand=brand, grammar=True, ranker_model=r"training\models\ranker-1.txt")
```

## Add 10 or 100 new reports

1. Copy the PDFs into `D:\Dynamic-PDF-Design-References\00-Inbox`, or import them from any folder:

```bash
python -m tools.design_learning import "D:/path/to/new-reports"
```

2. Register what is in the inbox. A file seen before is skipped by its hash, so a repeat cannot count twice:

```bash
python -m tools.design_learning import
```

3. Measure every PDF and rebuild the atlas and page graphs:

```bash
python -m tools.design_learning analyze
```

4. Check that every page is accounted for and that all evidence still exists:

```bash
python -m tools.design_learning validate
```

5. Draw review sheets of the pages nobody has inspected:

```bash
python -m tools.design_learning review --limit 24
```

6. After looking at those sheets, record what was seen:

```bash
python -m tools.design_learning review --record notes.jsonl
```

7. Add or change rules in `tools/reference_analyzer/grammar_rules.py` when the new pages justify it, then rebuild:

```bash
python -m tools.reference_analyzer.grammar_build
```

8. Approve. An AI approval says so. A human approval needs a name:

```bash
python -m tools.design_learning approve --rules all --reviewer-type ai --model claude-opus-5-5
```

```bash
python -m tools.design_learning approve --rules kpi.ruled_strip --reviewer-type human --reviewer "Full Name"
```

9. Publish the approved rules into the package:

```bash
python -m tools.design_learning publish
```

Adding PDFs alone changes no design. The engine benefits only after step 9, and only for rules
that were written or changed in step 7. Record the licence of each new file before relying on it.

## Regenerate comparisons and AI evaluations

```bash
python -m tools.design_learning preferences generate seed-002 --n 4
```

```bash
python -m tools.design_learning preferences sheets seed-002 --pairs 2 --repeats 1
```

Claude then looks at every sheet in `training/ai_preferences/batches/seed-002/sheets` and writes an
answers file before opening `key.json`. One row per comparison:

```json
{"comparison": "cmp-001", "preferred": "A", "criteria": {"hierarchy": 1, "rhythm": 2}, "justification": "...", "confidence": "medium", "pages": ["A2", "B1"], "formats_inspected": ["pdf"]}
```

`preferred` is `A`, `B`, `tie` or `abstain`. A comparison with no sheet is refused.

```bash
python -m tools.design_learning preferences record seed-002 answers.jsonl --model claude-opus-5-5 --date 2026-11-05
```

```bash
python -m tools.design_learning preferences check
```

Rows read `reviewer_type: "ai"` and are never human labels. Repeats with swapped sides show
contradictions; when the reviewer can recognise a sheet they are a weak test. If a design is later
found defective, list it in `batches/<batch>/superseded.json`: the row stays, and training skips it.

### Check the DOCX in Microsoft Word

On Windows with Word installed, render a batch's DOCX through Word and build the same blind sheets
from those pages:

```bash
python -m tools.design_learning preferences word seed-002
```

```bash
python -m tools.design_learning preferences sheets seed-002 --pairs 2 --repeats 1 --source word
```

Exports go to `batches/seed-002/word/`, sheets to `sheets-word/`, and the key to `key-word.json`.
Git ignores all three. Each file runs in its own Word process with a time limit, opened read-only.
The result holds only for the Word version named in `word/word.json`. A LibreOffice result does not
stand in for Word.

## Train and validate the optional ranker

This is AI preference distillation. The student learns to imitate Claude's comparisons, not people.

```bash
pip install -e ".[ranker]"
```

```bash
python -m tools.design_learning train --name ranker-1
```

```bash
python -m tools.design_learning evaluate --name ranker-1
```

Training stops with a message below 200 usable comparisons. Ties, abstentions, low-confidence
rows, pairs that flipped, repeats and superseded designs are left out. A trained model is written
to `training/models/ranker-1.txt` with `ranker-1.json`, and the record's gate decides whether it
may load:

| Gate | Required |
| --- | --- |
| Usable comparisons | 200 or more |
| Training documents | 8 or more |
| Evaluation documents | 3 or more, from a family unseen in training |
| Leakage | None between training and evaluation documents |
| Learned against the deterministic selector | At least 0.03 better on the evaluation documents |
| Agreement with held-out comparisons | At least 0.60 |

Finishing training is not a pass. The ranker only reorders designs that already passed the hard
QA gates. A model that fails any check, is altered or is missing leaves the deterministic selector
in charge. It never activates itself: a caller must name it.

## Automatic and needing approval

| Automatic | Needs a decision |
| --- | --- |
| Import by hash, measuring, atlas, graphs, coverage | Rights of each new PDF |
| Validation and the review queue | Whether a page reading becomes a rule |
| Rendering variants, blind sheets, hashes | Approving rules, and which reviewer type applies |
| Consistency check and the training gate | Publishing the grammar |
| Fallback when a grammar design fails a gate | Passing `grammar=True` in a caller |
| | Training a model, and naming it in a caller |

`publish` refuses rules without an approval. An AI approval is recorded with
`human_approved: false`. The user has delegated visual curation to Claude, so the current grammar
is AI-approved, and nothing is recorded as a human decision.

## Confirm rules and the ranker are really used

```bash
python -m tools.design_learning trace annual_report
```

```bash
python -m tools.design_learning trace annual_report --model training/models/ranker-1.txt
```

`trace` generates a fictional document. In your own code the same facts are on the result:

```python
for v in made.variants:
    print(v.id, v.report.grammar_version, v.report.grammar_rules)
    print([d for d in v.plan.decisions if d.startswith("grammar")])
print(made.stats["selection"])
```

- `grammar_rules` empty means no rule was applied to that design.
- An observation ending in "does without them" means a rule failed a gate and the design fell back.
- `selection.selector` is `learned` only when a model chose. It then gives the model, its hash, the
  scores and what the deterministic selector would have chosen.
- `selection.fallback_reason` says why a named model was not used.

To see the grammar changing pages, run the measured comparison:

```bash
python benchmarks/m77/run.py out-folder --keep-files
```

Then the same comparison as Word lays it out:

```bash
python benchmarks/m77/word.py out-folder
```
