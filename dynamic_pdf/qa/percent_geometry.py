"""Detect percent signs rendered on the wrong side of Arabic numbers.

Use PDF glyph coordinates: extracted text order is unreliable for RTL text.
"""
from __future__ import annotations

_ARABIC_DIGITS = set("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹")
_DIGITS = _ARABIC_DIGITS | set("0123456789")


def misplaced_arabic_percent(rawdict: dict):
    """Yield (bbox, text) when % or U+066A is physically RIGHT of a digit.

    A nearby number is required so neighbouring table columns are not mixed.
    Latin-only percent expressions in English text are not affected.
    """
    for block in rawdict.get("blocks", []):
        for line in block.get("lines", []):
            chars = [c for s in line.get("spans", []) for c in s.get("chars", [])]
            if not chars:
                continue
            text = "".join(c["c"] for c in chars)
            arabic_context = any(c in _ARABIC_DIGITS or "\u0600" <= c <= "\u06ff" for c in text)
            if not arabic_context:
                continue
            digits = [c for c in chars if c["c"] in _DIGITS]
            for sign in chars:
                if sign["c"] not in ("%", "٪"):
                    continue
                s = sign["bbox"]
                nearby = []
                for digit in digits:
                    box = digit["bbox"]
                    dy = abs((s[1] + s[3]) / 2 - (box[1] + box[3]) / 2)
                    height = max(s[3] - s[1], box[3] - box[1])
                    gap = max(s[0] - box[2], box[0] - s[2], 0)
                    if dy <= height * 0.45 and gap <= 3.0:
                        nearby.append((gap, abs((s[0] + s[2]) / 2 - (box[0] + box[2]) / 2), digit))
                if nearby:
                    neighbour = min(nearby, key=lambda row: (row[0], row[1]))[2]
                    if s[0] >= neighbour["bbox"][2] - 1.0:
                        yield (s, text.strip()[:80])
