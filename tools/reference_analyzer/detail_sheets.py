"""
Pages at a chosen size for visual review. Sheets stay in the analysis folder: they show
reference pages and never enter the repository. Each sheet lists what it shows and at what
size, so a review note can state how closely a page was seen.
"""
from __future__ import annotations

import json
import os
from typing import List, Sequence, Tuple

ATLAS = os.path.join("visual", "visual-atlas", "pages")


def page_image(analysis_dir: str, ref: str):
    from PIL import Image
    doc, page = ref.rsplit(":", 1)
    return Image.open(os.path.join(analysis_dir, ATLAS, doc.replace("ref-", ""), f"p{int(page):04d}.jpg")).convert("RGB")


def sheet(analysis_dir: str, refs: Sequence[str], out: str, cols: int = 2, cell_w: int = 780,
          captions: Sequence[str] = ()) -> List[dict]:
    """One sheet of ``refs``. Returns where each page sits and the size it is shown at."""
    from PIL import Image, ImageDraw
    pics = [page_image(analysis_dir, r) for r in refs]
    scaled = []
    for im in pics:
        w, h = im.size
        scaled.append(im.resize((cell_w, round(h * cell_w / w)), Image.LANCZOS) if w >= h else
                      im.resize((cell_w, round(h * cell_w / w)), Image.LANCZOS))
    rows = -(-len(scaled) // cols)
    cell_h = max(i.size[1] for i in scaled) + 26
    board = Image.new("RGB", (cols * (cell_w + 8), rows * cell_h), "#555555")
    draw = ImageDraw.Draw(board)
    shown = []
    for n, (ref, im) in enumerate(zip(refs, scaled)):
        x, y = (n % cols) * (cell_w + 8), (n // cols) * cell_h
        board.paste(im, (x, y + 24))
        draw.text((x + 4, y + 6), captions[n] if n < len(captions) else ref, fill="#FFFFFF")
        shown.append({"ref": ref, "slot": n + 1, "shown_px": list(im.size), "sheet": os.path.basename(out)})
    os.makedirs(os.path.dirname(out), exist_ok=True)
    board.save(out, quality=86)
    return shown


def batches(refs: Sequence[str], size: int) -> List[Tuple[int, List[str]]]:
    return [(i // size + 1, list(refs[i:i + size])) for i in range(0, len(refs), size)]


def write_manifest(path: str, rows: List[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"format": "dynamic-pdf-builder/m77-detail-sheets", "pages": rows}, f, ensure_ascii=False, indent=0)
