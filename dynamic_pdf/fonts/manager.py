"""
Font Manager — registers bundled fonts and resolves deterministic fallbacks.
Thread-safe: only registers once. Rendering never downloads fonts.
"""
import contextvars
import json
import os
import logging
import threading
import urllib.request
from functools import lru_cache
from typing import Dict, List, Optional
import unicodedata
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase import ttfonts as _ttfonts
from reportlab.pdfbase.ttfonts import TTFont

logger = logging.getLogger("dynamic_pdf.fonts")


def _is_presentation_form(cp: int) -> bool:
    return 0xFB50 <= cp <= 0xFDFF or 0xFE70 <= cp <= 0xFEFF


def _base_letters_cmap(fontname, subset, _plain=_ttfonts.makeToUnicodeCMap):
    """ToUnicode CMap in which reshaped Arabic glyphs (presentation forms) extract as the base
    letters the author wrote (NFKC, so lam-alef gives two letters): a verbatim search of the
    PDF then finds the source text. A character beyond U+FFFF is written as its UTF-16 pair. Every
    other code keeps ReportLab's own mapping.

    A ligature's letters are listed in visual order, as its glyph is drawn: bidi-aware
    extractors (MuPDF, PDFium) reverse the line and read them logically, and raw extractors
    (pdfminer) give the exact mirror of the source."""
    cmap = _plain(fontname, subset)
    for i, v in enumerate(subset):
        if v > 0xFFFF:
            # ReportLab writes five hex digits, which is invalid: an emoji would copy out as another
            # character. The map wants UTF-16, the surrogate pair.
            cmap = cmap.replace("<%02X> <%04X>" % (i, v), "<%02X> <%s>" % (i, chr(v).encode("utf-16-be").hex().upper()), 1)
        elif _is_presentation_form(v):
            base = (unicodedata.normalize("NFKC", chr(v)).strip() or chr(v))[::-1]
            cmap = cmap.replace("<%02X> <%04X>" % (i, v),
                                "<%02X> <%s>" % (i, base.encode("utf-16-be").hex().upper()), 1)
    return cmap


# ReportLab builds every subset's ToUnicode through this module function; wrapping it is the one
# seam that covers paragraphs, canvas strings, tables and charts alike.
if getattr(_ttfonts.makeToUnicodeCMap, "__name__", "") != "_base_letters_cmap":
    _ttfonts.makeToUnicodeCMap = _base_letters_cmap

BUNDLED_DIR = os.path.join(os.path.dirname(__file__), "bundled")

# Reliable direct download URLs
FONT_URLS = {
    "JetBrainsMono-Regular.ttf": "https://github.com/JetBrains/JetBrainsMono/raw/master/fonts/ttf/JetBrainsMono-Regular.ttf",
    "JetBrainsMono-Bold.ttf": "https://github.com/JetBrains/JetBrainsMono/raw/master/fonts/ttf/JetBrainsMono-Bold.ttf",
    "Amiri-Regular.ttf": "https://github.com/google/fonts/raw/main/ofl/amiri/Amiri-Regular.ttf",
    "Amiri-Bold.ttf":    "https://github.com/google/fonts/raw/main/ofl/amiri/Amiri-Bold.ttf",
}

_lock = threading.Lock()
_registered = False
_available_fonts: set = set()
_arabic_face = contextvars.ContextVar("dynamic_pdf_arabic_face", default="Amiri")


@lru_cache(maxsize=1)
def font_catalog() -> Dict[str, dict]:
    """The open-licence families shipped with the package, by family name. They are registered
    when first used, so a document pays only for the fonts it sets."""
    path = os.path.join(BUNDLED_DIR, "catalog.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def list_font_families(script: Optional[str] = None) -> List[str]:
    """Bundled family names, for ``theme.typography``: ``"arabic"``, ``"latin"`` or both."""
    return sorted(k for k, v in font_catalog().items() if script in (None, v["script"]))


def _use_family(family: str) -> None:
    """Register one catalog family and tie its styles together for bold and italic markup."""
    from reportlab.lib.fonts import addMapping
    with _lock:
        if family in _available_fonts:
            return
        files = font_catalog()[family]["files"]
        names = {style: family if style == "regular" else f"{family}-{style.title()}" for style in files}
        for style, name in names.items():
            _try_register(name, files[style])
        regular = names["regular"]
        bold = names.get("bold", regular)
        italic = names.get("italic", regular)
        for name in names.values():
            addMapping(name, 0, 0, regular)
            addMapping(name, 1, 0, bold)
            addMapping(name, 0, 1, italic)
            addMapping(name, 1, 1, bold)


def covers(family: str, chars: str) -> bool:
    """Whether a bundled family draws every one of these characters, in regular and bold."""
    entry = font_catalog().get(family)
    if entry is None:
        return True                     # not ours to measure, as with Amiri and custom faces
    from reportlab.pdfbase import pdfmetrics
    _use_family(family)
    for style in entry["files"]:
        if style not in ("regular", "bold"):
            continue
        name = family if style == "regular" else f"{family}-Bold"
        try:
            glyphs = pdfmetrics.getFont(name).face.charToGlyph
        except (KeyError, AttributeError):
            return False
        if any(ord(c) not in glyphs for c in chars):
            return False
    return True


def covering_face(family: str, chars: str) -> str:
    """The family itself when it can set these characters, or else the nearest that can.

    A design's Arabic face must not turn a percent sign or a decimal separator into an empty box.
    """
    if covers(family, chars):
        return family
    catalog = font_catalog()
    style = catalog.get(family, {}).get("style")
    arabic = sorted(k for k, v in catalog.items() if v["script"] == "arabic")
    for name in sorted(arabic, key=lambda k: catalog[k].get("style") != style):
        if covers(name, chars):
            return name
    return family


def set_arabic_face(family: Optional[str]) -> None:
    """The face Arabic text takes in the render under way."""
    _arabic_face.set(family or "Amiri")


def current_arabic_face() -> str:
    family = _arabic_face.get()
    if family in font_catalog():
        _use_family(family)
    return family


def ensure_fonts_downloaded():
    """Explicitly download missing bundled fonts (network). Never raises.

    This is NOT called during rendering: rendering is offline and
    deterministic. Fonts ship inside the package (see ``bundled/LICENSES``).
    """
    os.makedirs(BUNDLED_DIR, exist_ok=True)
    for filename, url in FONT_URLS.items():
        path = os.path.join(BUNDLED_DIR, filename)
        if not os.path.exists(path):
            try:
                logger.info("Downloading font: %s", filename)
                urllib.request.urlretrieve(url, path)
                logger.info("Downloaded font: %s", filename)
            except Exception as e:
                logger.warning("Could not download %s: %s", filename, e)


def _try_register(name: str, filename: str) -> bool:
    """Try to register a single font. Return True if successful."""
    path = os.path.join(BUNDLED_DIR, filename)
    if os.path.exists(path):
        try:
            pdfmetrics.registerFont(TTFont(name, path))
            _available_fonts.add(name)
            logger.debug("Registered font: %s from %s", name, filename)
            return True
        except Exception as e:
            logger.warning("Could not register font %s: %s", name, e)
    return False


def register_fonts():
    """Register all bundled fonts. Thread-safe — only runs once."""
    global _registered
    with _lock:
        if _registered:
            return
        # No network access here: only fonts shipped in bundled/ are used.

        # Monospace
        _try_register("JetBrains Mono", "JetBrainsMono-Regular.ttf")
        _try_register("JetBrains Mono-Bold", "JetBrainsMono-Bold.ttf")

        # Arabic
        _try_register("Amiri", "Amiri-Regular.ttf")
        _try_register("Amiri-Bold", "Amiri-Bold.ttf")
        if {"Amiri", "Amiri-Bold"} <= _available_fonts:
            # lets <font name="Amiri"> inside bold text pick Amiri-Bold
            from reportlab.lib.fonts import addMapping
            addMapping("Amiri", 0, 0, "Amiri")
            addMapping("Amiri", 1, 0, "Amiri-Bold")
            addMapping("Amiri", 0, 1, "Amiri")
            addMapping("Amiri", 1, 1, "Amiri-Bold")
            addMapping("Amiri-Bold", 0, 0, "Amiri")
            addMapping("Amiri-Bold", 1, 0, "Amiri-Bold")
            addMapping("Amiri-Bold", 0, 1, "Amiri")
            addMapping("Amiri-Bold", 1, 1, "Amiri-Bold")

        # Symbols and emoji no text face draws: fallbacks, chosen a character at a time
        from reportlab.lib.fonts import addMapping
        for name, fname in (("DejaVu Sans", "DejaVuSans.ttf"), ("Noto Emoji", "NotoEmoji-Regular.ttf")):
            if _try_register(name, fname):
                for bold in (0, 1):                 # one cut: bold and italic text keep the same glyph
                    for italic in (0, 1):
                        addMapping(name, bold, italic, name)

        # Auto-register any manually placed fonts in the bundled dir
        catalogued = {n for v in font_catalog().values() for n in v["files"].values()} | {
            "DejaVuSans.ttf", "NotoEmoji-Regular.ttf"}
        for fname in os.listdir(BUNDLED_DIR):
            if fname.endswith(".ttf") and fname not in catalogued:
                name = fname.replace(".ttf", "")
                if name not in _available_fonts:
                    _try_register(name, fname)

        _registered = True
        logger.info("Font registration complete. Available: %s", sorted(_available_fonts))


def register_custom_font(name: str, path: str) -> bool:
    """Register a custom font from an absolute file path.

    Example::

        register_custom_font("MyBrand", "/fonts/MyBrand-Regular.ttf")
    """
    with _lock:
        try:
            pdfmetrics.registerFont(TTFont(name, path))
            _available_fonts.add(name)
            logger.info("Registered custom font: %s", name)
            return True
        except Exception as e:
            logger.warning("Failed to register custom font %s: %s", name, e)
            return False


def get_font_name(family: str, bold: bool = False, italic: bool = False) -> str:
    """Get a registered font name, with bulletproof Helvetica fallback."""
    if family in font_catalog():
        _use_family(family)
        if bold and f"{family}-Bold" in _available_fonts:
            return f"{family}-Bold"
        if italic and f"{family}-Italic" in _available_fonts:
            return f"{family}-Italic"
        if family in _available_fonts:
            return family

    # JetBrains Mono
    if family in ("JetBrains Mono", "JetBrains Mono-Bold"):
        if bold and "JetBrains Mono-Bold" in _available_fonts:
            return "JetBrains Mono-Bold"
        if "JetBrains Mono" in _available_fonts:
            return "JetBrains Mono"
        return "Courier"

    # Amiri (Arabic)
    if family == "Amiri":
        if bold and "Amiri-Bold" in _available_fonts:
            return "Amiri-Bold"
        if "Amiri" in _available_fonts:
            return "Amiri"
        return "Helvetica"

    # Inter
    if family == "Inter":
        if bold and italic and "Inter-BoldItalic" in _available_fonts:
            return "Inter-BoldItalic"
        if bold and "Inter-Bold" in _available_fonts:
            return "Inter-Bold"
        if italic and "Inter-Italic" in _available_fonts:
            return "Inter-Italic"
        if "Inter-Regular" in _available_fonts:
            return "Inter-Regular"
        if "Inter" in _available_fonts:
            return "Inter"
        if bold and italic:
            return "Helvetica-BoldOblique"
        if bold:
            return "Helvetica-Bold"
        if italic:
            return "Helvetica-Oblique"
        return "Helvetica"

    # Times / Serif
    if family in ("Times-Roman", "Times", "Serif"):
        if bold and italic:
            return "Times-BoldItalic"
        if bold:
            return "Times-Bold"
        if italic:
            return "Times-Italic"
        return "Times-Roman"

    # Courier
    if family in ("Courier", "Monospace"):
        if bold:
            return "Courier-Bold"
        if italic:
            return "Courier-Oblique"
        return "Courier"

    # Check custom-registered fonts
    if family in _available_fonts:
        return family
    if bold:
        bold_name = f"{family}-Bold"
        if bold_name in _available_fonts:
            return bold_name

    # Generic Helvetica fallback
    if bold and italic:
        return "Helvetica-BoldOblique"
    if bold:
        return "Helvetica-Bold"
    if italic:
        return "Helvetica-Oblique"
    return "Helvetica"


def list_available_fonts() -> list:
    """Return sorted list of all registered font names."""
    return sorted(_available_fonts)


def font_signature() -> str:
    """Name and size of every bundled font, to tell one font set from another."""
    if not os.path.isdir(BUNDLED_DIR):
        return ""
    names = sorted(n for n in os.listdir(BUNDLED_DIR) if n.lower().endswith((".ttf", ".otf")))
    return ";".join(f"{n}:{os.path.getsize(os.path.join(BUNDLED_DIR, n))}" for n in names)
