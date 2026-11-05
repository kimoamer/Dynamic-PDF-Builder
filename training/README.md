# Training data

Nothing here is used at run time unless a caller names a model.

| Folder | What it holds | In Git |
|---|---|---|
| `ai_preferences/` | Blind comparisons by an AI reviewer, one row each in `ai-preferences.jsonl`; `batches/<name>/` holds candidates, sheets and the key | rows and sheets of fictional documents; renders stay local |
| `human_preferences/` | Comparisons by people, when any exist. Never mixed with AI rows | yes |
| `models/` | Trained rankers: `<name>.txt` with its record `<name>.json` | no |
| `document-split.json` | Which documents train and which evaluate | yes |

Reference PDFs never come here. See `docs/LEARNING_PIPELINE.md`.
