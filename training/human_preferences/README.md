# Human preferences

Empty until people judge designs. Keep these apart from `../ai_preferences`.
The trainer for AI comparisons refuses rows that are not marked as AI work.

Two files are written here, and nowhere else:

- `accepted.jsonl`: one row per `VariantSet.accept(id, reviewer)`, the design a person kept.
- `human-audit.jsonl`: A/B decisions from the local page
  (`python -m tools.design_learning preferences judge <batch> --reviewer "Name"`), in the format the
  preflight audit reads with `--human-audit`. The training gate needs 20 of these.
