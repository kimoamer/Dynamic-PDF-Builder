"""
Word page-count forecast: the PDF's measured pagination (``layout.breaks``), with block
heights scaled by a per-font line-height factor for Word.

Word sets "multiple" line spacing in the font's own line height, and its line breaking and
space handling differ from ReportLab's, so a DOCX can run longer or shorter than the PDF.
The factors were fitted against LibreOffice's layout of this library's DOCX files
(``benchmarks/m11/run.py --docx``); Microsoft Word was not available to fit them.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Optional

# Word height / PDF height, by body font; fonts not listed use DEFAULT. Fitted in LibreOffice
# 24.2 on the 25 golden fixtures and M7 corpus documents of benchmarks/m11; over those and the 7
# stress documents (32) the forecast gives LibreOffice's page count for 28, the PDF page count
# for 25. Misses: one page on the proposal, chart report and Arabic annual report, and 4 to 6 on
# the long Arabic stress report. Arabic text runs longer in Word, Latin text shorter.
WORD_LINE_FACTOR = {"Amiri": 1.14, "Helvetica": 0.9}
DEFAULT = 1.0


def word_factor(theme) -> float:
    ty = theme.typography
    return WORD_LINE_FACTOR.get(ty.body_family, DEFAULT)


def predict_word_pages(doc, theme, policy=None, factor: Optional[float] = None) -> Optional[int]:
    """Pages Word is forecast to lay the document out on, or None where the model does not
    cover the document (page layers, images placed on the page)."""
    from .breaks import _items, natural_pages, without_page_starts
    segments, H = _items(without_page_starts(doc), theme, policy)    # the PDF's page starts stay in the PDF
    if segments is None:
        return None
    k = word_factor(theme) if factor is None else factor
    pages = 0
    for items, final, _ in segments:
        scaled = [replace(it, height=it.height * k, ink=it.ink * k, space_before=it.space_before * k,
                          space_after=it.space_after * k, min_piece=it.min_piece * k) for it in items]
        pages += natural_pages(scaled, H, final)[0] if scaled else 0
    return pages
