"""Text contrast on the rendered page (WCAG 2.x AA).

Each text span's fill colour is compared with the colour actually painted behind it: the
commonest pixel colour in the span's box that is not the text colour itself. Body text needs
4.5:1 and large text (18 pt, or 14 pt bold) 3:1. Findings are warnings, never gate failures.
"""
from __future__ import annotations

from typing import Iterator, Tuple

from ..utils.color import contrast_ratio, rgb_to_hex

AA_BODY, AA_LARGE = 4.5, 3.0
ZOOM = 1.0


def is_large(size: float, font: str, flags: int = 0) -> bool:
    bold = "bold" in (font or "").lower() or bool(flags & 16)
    return size >= 18 or (bold and size >= 14)


def _background(img, box, fg, pad: float) -> Tuple[int, int, int] | None:
    # padded: a tight glyph box (PDFium's) holds more anti-aliased edge than background
    x0, y0, x1, y1 = (int(round(v * ZOOM)) for v in (box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad))
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(img.width, x1), min(img.height, y1)
    if x1 <= x0 or y1 <= y0:
        return None
    colours = img.crop((x0, y0, x1, y1)).getcolors(maxcolors=(x1 - x0) * (y1 - y0)) or []
    ranked = [rgb for _, rgb in sorted(colours, reverse=True)]
    for rgb in ranked:
        if max(abs(a - b) for a, b in zip(rgb, fg)) > 24:      # not the text's own pixels
            return tuple(rgb)
    return tuple(ranked[0]) if ranked else None               # nothing else there: invisible text


def _image(page):
    from PIL import Image
    w, h, samples = page.rgb(ZOOM)
    return Image.frombytes("RGB", (w, h), samples)


def low_contrast(page, text_dict) -> Iterator[Tuple[float, float, str, str, str, tuple]]:
    """(ratio, needed, text colour, background colour, text, bbox) for spans under AA."""
    img = _image(page)
    for block in text_dict.get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = span.get("text", "").strip()
                if not text:
                    continue
                c = span.get("color", 0)
                fg = ((c >> 16) & 255, (c >> 8) & 255, c & 255)
                bg = _background(img, span["bbox"], fg, max(1.5, 0.2 * span.get("size", 0)))
                if bg is None:
                    continue
                ratio = contrast_ratio(rgb_to_hex(*fg), rgb_to_hex(*bg))
                needed = AA_LARGE if is_large(span.get("size", 0), span.get("font", ""), span.get("flags", 0)) else AA_BODY
                if ratio < needed:
                    yield ratio, needed, rgb_to_hex(*fg), rgb_to_hex(*bg), text, tuple(span["bbox"])
