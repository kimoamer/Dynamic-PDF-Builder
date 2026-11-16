"""
Measured facts about a rendered document, for the preference dataset.

Everything here is read from a PDF: positions, sizes, fonts and image boxes. None of it says
whether a page is good, and none of it comes from a reviewer. Reviewer judgments stay in
ai-preferences.jsonl, so a trainer can never confuse the two.

The measurements are the document facts of ``dynamic_pdf.intelligence.facts.PageFacts``,
the same facts the engine scores and ranks with.
"""
from __future__ import annotations

from typing import Dict, Optional

from dynamic_pdf.intelligence.facts import FACTS_VERSION, read_pdf


def measure(pdf: bytes, plain_pages: Optional[int] = None) -> Dict[str, float]:
    import pymupdf  # noqa: F401 - the dataset needs real measurements, never an empty record
    return read_pdf(pdf, plain_pages=plain_pages, image=False).document


__all__ = ["FACTS_VERSION", "measure"]
