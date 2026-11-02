"""
Font Manager — registers bundled fonts and resolves deterministic fallbacks.
Thread-safe: only registers once. Rendering never downloads fonts.
"""
import os
import logging
import threading
import urllib.request
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

        # Auto-register any manually placed fonts in the bundled dir
        for fname in os.listdir(BUNDLED_DIR):
            if fname.endswith(".ttf"):
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
