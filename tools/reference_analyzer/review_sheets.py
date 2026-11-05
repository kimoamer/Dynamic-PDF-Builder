"""
Sheets for reviewing every page by eye, at a size where a composition can be read.

Pages run in document order, so a sheet also shows how pages follow one another. The
manifest records the size each page was really shown at. Sheets hold reference pages,
so they stay local: write them outside any repository.
"""
from __future__ import annotations

import json
import os
from typing import Dict, List

from PIL import Image, ImageDraw

CELL_W, CELL_H = 480, 660
COLUMNS, ROWS = 4, 2
PER_SHEET = COLUMNS * ROWS
LABEL_H = 18


def page_key(page: Dict) -> str:
    return f"{page['sha256'][:12]}:{page['page']}"


def ordered_pages(index: Dict) -> List[Dict]:
    pages = [p for p in index["pages"] if p.get("image")]
    return sorted(pages, key=lambda p: (p["file"], p["page"]))


def _cell(image: Image.Image) -> Image.Image:
    scale = min(CELL_W / image.width, (CELL_H - LABEL_H) / image.height)
    return image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))),
                        Image.LANCZOS)


def build(atlas_root: str, out: str, index: Dict) -> Dict:
    os.makedirs(out, exist_ok=True)
    pages = ordered_pages(index)
    documents = {name: i + 1 for i, name in enumerate(sorted({p["file"] for p in pages}))}
    manifest = {"cell": [CELL_W, CELL_H], "per_sheet": PER_SHEET, "documents": documents, "sheets": []}
    for start in range(0, len(pages), PER_SHEET):
        number = start // PER_SHEET + 1
        sheet = Image.new("RGB", (COLUMNS * (CELL_W + 6), ROWS * (CELL_H + 6)), "#59606a")
        draw = ImageDraw.Draw(sheet)
        entries = []
        for slot, page in enumerate(pages[start:start + PER_SHEET]):
            x, y = slot % COLUMNS * (CELL_W + 6), slot // COLUMNS * (CELL_H + 6)
            with Image.open(os.path.join(atlas_root, page["image"])) as source:
                source_px = source.size
                shown = _cell(source.convert("RGB"))
            sheet.paste(shown, (x, y + LABEL_H))
            draw.text((x + 4, y + 3), f"#{slot + 1}  D{documents[page['file']]} p{page['page']}", fill="#ffffff")
            entries.append({"key": page_key(page), "slot": slot + 1, "doc": documents[page["file"]],
                            "page": page["page"], "shown_px": list(shown.size), "source_px": list(source_px)})
        name = f"sheet-{number:03d}.jpg"
        sheet.save(os.path.join(out, name), quality=82)
        manifest["sheets"].append({"name": name, "pages": entries})
    with open(os.path.join(out, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False)
    return manifest


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("visual", help="folder holding visual-page-index.json and visual-atlas/")
    parser.add_argument("out", help="output folder, outside any repository")
    args = parser.parse_args(argv)
    with open(os.path.join(args.visual, "visual-page-index.json"), encoding="utf-8") as f:
        index = json.load(f)
    manifest = build(os.path.join(args.visual, "visual-atlas"), args.out, index)
    print(len(manifest["sheets"]), "sheets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
