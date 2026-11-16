"""Render every page to PNG and build contact sheets for human review."""
from __future__ import annotations

import os
from typing import List


def rasterize_pdf(data: bytes, out_dir: str, prefix: str = "page", dpi: int = 80) -> List[str]:
    from .pdf_backend import open_pdf
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    for i, page in enumerate(open_pdf(data), start=1):
        p = os.path.join(out_dir, f"{prefix}-{i:03d}.png")
        page.save_png(p, dpi)
        paths.append(p)
    return paths


def contact_sheet(images: List[str], out_path: str, columns: int = 4, thumb_width: int = 300) -> str:
    from PIL import Image
    thumbs = []
    for p in images:
        im = Image.open(p).convert("RGB")
        ratio = thumb_width / im.width
        thumbs.append(im.resize((thumb_width, int(im.height * ratio))))
    if not thumbs:
        raise ValueError("no pages to tile")
    rows = (len(thumbs) + columns - 1) // columns
    th = max(t.height for t in thumbs)
    sheet = Image.new("RGB", (columns * (thumb_width + 12) + 12, rows * (th + 12) + 12), "#d0d4da")
    for i, t in enumerate(thumbs):
        r, c = divmod(i, columns)
        sheet.paste(t, (12 + c * (thumb_width + 12), 12 + r * (th + 12)))
    sheet.save(out_path)
    return out_path
