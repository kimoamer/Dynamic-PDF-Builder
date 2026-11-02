"""Text measurement helpers (ReportLab font metrics) for layout planning."""
from __future__ import annotations

from typing import List

from reportlab.pdfbase.pdfmetrics import stringWidth

from ..core.inline import plain_text
from ..fonts import get_font_name, register_fonts


def text_width(text: str, family: str, size: float, bold: bool = False) -> float:
    register_fonts()
    font = get_font_name(family, bold=bold)
    try:
        return stringWidth(text, font, size)
    except Exception:
        return len(text) * size * 0.5


def avg_char_width(family: str, size: float) -> float:
    sample = "the quick brown fox jumps over the lazy dog ETAOIN 0123456789"
    return text_width(sample, family, size) / len(sample)


def chars_per_line(width_pt: float, family: str, size: float) -> float:
    return width_pt / max(0.1, avg_char_width(family, size))


def column_metrics(headers: List[str], rows: List[List[str]], family: str, size: float,
                   padding: float = 20.0):
    """Per column: (min width = longest word, natural width = longest line), in pt."""
    ncols = max([len(headers)] + [len(r) for r in rows] + [1])
    mins = [0.0] * ncols
    nats = [0.0] * ncols
    cells = [(headers, True)] + [(r, False) for r in rows]
    for row, is_head in cells:
        for ci in range(ncols):
            txt = plain_text(str(row[ci])) if ci < len(row) else ""
            w_nat = text_width(txt, family, size, bold=is_head) + padding
            longest_word = max((text_width(wd, family, size, bold=is_head) for wd in txt.split()),
                               default=0.0) + padding + 2.0   # slack: avoid splitting a word

            mins[ci] = max(mins[ci], longest_word)
            nats[ci] = max(nats[ci], w_nat)
    return mins, nats


def fit_columns(mins: List[float], nats: List[float], avail: float):
    """CSS-like auto table layout. Returns (fractions, fits_without_overflow)."""
    n = len(nats)
    total_nat = sum(nats)
    total_min = sum(mins)
    if total_nat <= avail:
        # everything fits on one line; share spare space proportionally
        widths = [w + (avail - total_nat) * (w / total_nat) for w in nats] if total_nat else [avail / n] * n
        return [w / avail for w in widths], True
    if total_min <= avail:
        # give each column its minimum, distribute the rest by (natural - min)
        spare = avail - total_min
        flex = [max(0.0, nt - mn) for mn, nt in zip(mins, nats)]
        fsum = sum(flex) or 1.0
        widths = [mn + spare * f / fsum for mn, f in zip(mins, flex)]
        return [w / avail for w in widths], True
    return [mn / total_min for mn in mins], False


def wrap_ratio(nats: List[float], fractions: List[float], avail: float) -> float:
    """Mean lines per cell implied by a column split (1.0 = no wrapping)."""
    if not nats:
        return 1.0
    ratios = [max(1.0, nt / max(1.0, f * avail)) for nt, f in zip(nats, fractions)]
    return sum(ratios) / len(ratios)
