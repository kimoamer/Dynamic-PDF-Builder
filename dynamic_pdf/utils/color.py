"""Color utilities — hex/rgb/hsl parsing and WCAG contrast ratio."""
import re, math
from typing import Tuple


def hex_to_rgb(h: str) -> Tuple[int, int, int]:
    h = h.lstrip("#")
    if len(h) == 3:
        h = h[0]*2 + h[1]*2 + h[2]*2
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{r:02x}{g:02x}{b:02x}"


def _relative_luminance(r: int, g: int, b: int) -> float:
    """WCAG 2.x relative luminance formula."""
    def lin(v):
        v /= 255.0
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def contrast_ratio(c1: str, c2: str) -> float:
    """WCAG 2.x contrast ratio between two hex colors."""
    l1 = _relative_luminance(*hex_to_rgb(c1))
    l2 = _relative_luminance(*hex_to_rgb(c2))
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def passes_wcag_aa(text_color: str, bg_color: str, large_text: bool = False) -> bool:
    """Check WCAG 2.x AA: 4.5:1 for normal text, 3:1 for large text (≥18pt or 14pt bold)."""
    ratio = contrast_ratio(text_color, bg_color)
    return ratio >= (3.0 if large_text else 4.5)


def lighten(hex_color: str, factor: float = 0.2) -> str:
    r, g, b = hex_to_rgb(hex_color)
    r = min(255, int(r + (255 - r) * factor))
    g = min(255, int(g + (255 - g) * factor))
    b = min(255, int(b + (255 - b) * factor))
    return rgb_to_hex(r, g, b)


def darken(hex_color: str, factor: float = 0.2) -> str:
    r, g, b = hex_to_rgb(hex_color)
    r = max(0, int(r * (1 - factor)))
    g = max(0, int(g * (1 - factor)))
    b = max(0, int(b * (1 - factor)))
    return rgb_to_hex(r, g, b)
