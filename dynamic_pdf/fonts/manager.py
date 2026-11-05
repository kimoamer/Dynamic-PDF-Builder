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
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

logger = logging.getLogger("dynamic_pdf.fonts")

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

        # Auto-register any manually placed fonts in the bundled dir
        catalogued = {n for v in font_catalog().values() for n in v["files"].values()}
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
