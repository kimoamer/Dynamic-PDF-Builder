"""Where the subject of a photograph sits, so a crop keeps it in the frame.

A plain measurement: a pixel counts as subject when it stands out from the rest of its own
row. A sky with a moon, or a field with a figure, has its subject found; a flat texture has
none and the crop stays centred. No model and no network.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Tuple

CENTRE = (0.5, 0.5)
GRID = 64
TOP_SHARE = 0.05          # the strongest cells that make up the subject
MIN_CONTRAST = 24         # out of 255; below this the picture has no clear subject


@lru_cache(maxsize=64)
def _measure(path: str, stamp: float) -> Tuple[float, float]:
    from PIL import Image
    with Image.open(path) as image:
        grey = image.convert("L").resize((GRID, GRID))
    px = grey.load()
    cells = []
    for y in range(GRID):
        middle = sorted(px[x, y] for x in range(GRID))[GRID // 2]
        cells += [(abs(px[x, y] - middle), x, y) for x in range(GRID)]
    cells.sort(reverse=True)
    top = cells[:max(1, int(len(cells) * TOP_SHARE))]
    weight = sum(c[0] for c in top)
    if weight / len(top) < MIN_CONTRAST:
        return CENTRE
    fx = sum(c[0] * c[1] for c in top) / weight / (GRID - 1)
    fy = sum(c[0] * c[2] for c in top) / weight / (GRID - 1)
    return round(fx, 3), round(fy, 3)


def focal_point(src) -> Tuple[float, float]:
    """The subject's centre as shares of width and height; the middle when unknown."""
    if not isinstance(src, str) or not os.path.isfile(src):
        return CENTRE
    try:
        return _measure(src, os.path.getmtime(src))
    except (OSError, ValueError):
        return CENTRE
