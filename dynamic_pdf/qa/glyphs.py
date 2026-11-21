"""Glyph coverage: which characters the configured fonts can actually draw."""
from __future__ import annotations

import unicodedata
from functools import lru_cache
from typing import Dict, Iterable, Optional, Set

from ..fonts import get_font_name, register_fonts

_STANDARD = {"Helvetica", "Helvetica-Bold", "Helvetica-Oblique", "Helvetica-BoldOblique",
             "Times-Roman", "Times-Bold", "Times-Italic", "Times-BoldItalic",
             "Courier", "Courier-Bold", "Courier-Oblique", "Courier-BoldOblique"}
FALLBACK_FONTS = ("JetBrains Mono", "Amiri", "DejaVu Sans", "Noto Emoji")
_EMOJI_FIRST = ("Noto Emoji", "DejaVu Sans")        # pictographs keep one look: the emoji face before a symbol face


@lru_cache(maxsize=64)
def _ttf_cmap(font_name: str) -> Optional[frozenset]:
    from reportlab.pdfbase.pdfmetrics import getFont
    try:
        f = getFont(font_name)
    except Exception:
        return None
    face = getattr(f, "face", None)
    cmap = getattr(face, "charToGlyph", None)
    return frozenset(cmap.keys()) if cmap else None


def font_covers(font_name: str, ch: str) -> bool:
    if ch.isspace() or unicodedata.category(ch) in ("Cc", "Cf"):
        return True
    if font_name in _STANDARD:
        try:
            ch.encode("cp1252")
            return True
        except UnicodeEncodeError:
            return False
    cmap = _ttf_cmap(font_name)
    return True if cmap is None else ord(ch) in cmap


def fallback_font_for(ch: str) -> Optional[str]:
    register_fonts()
    from ..fonts.manager import _available_fonts
    import unicodedata
    # a minus, a multiplication sign or a dash sits in running text: a proportional face, not a monospace one
    order = (_EMOJI_FIRST if ord(ch) >= 0x1F000 else
             ("DejaVu Sans",) + FALLBACK_FONTS if unicodedata.category(ch) in ("Sm", "Pd") else FALLBACK_FONTS)
    for fam in order:
        name = fam if fam in _EMOJI_FIRST and fam in _available_fonts else get_font_name(fam)
        if name not in _STANDARD and font_covers(name, ch):
            return name
    return None


def uncovered_chars(texts: Iterable[str], family: str) -> Dict[str, int]:
    """Characters that neither ``family`` nor any bundled fallback can render."""
    register_fonts()
    base = get_font_name(family)
    missing: Dict[str, int] = {}
    for t in texts:
        for ch in t:
            if font_covers(base, ch):
                continue
            if unicodedata.bidirectional(ch) in ("R", "AL", "AN"):
                continue   # rendered through the Arabic face
            if fallback_font_for(ch):
                continue
            missing[ch] = missing.get(ch, 0) + 1
    return missing


def needs_fallback(ch: str, base_font: str = "Helvetica") -> Optional[str]:
    register_fonts()            # before any coverage is read: an unregistered face would cache as covering all
    if font_covers(base_font, ch):
        return None
    return fallback_font_for(ch)


_SKIP: Set[str] = set()
