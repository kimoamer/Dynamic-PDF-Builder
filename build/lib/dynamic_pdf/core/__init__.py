"""Canonical semantic document model (renderer-independent)."""
from .inline import TextRun, parse_inline, runs_to_plain
from .normalize import SemanticDocument, ContentStats, OutlineEntry, normalize, block_text

__all__ = ["TextRun", "parse_inline", "runs_to_plain", "SemanticDocument",
           "ContentStats", "OutlineEntry", "normalize", "block_text"]
