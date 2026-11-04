"""
Structural checks of placed images, on the finished files.

PDF: paint order decides what the reader sees, so text painted before an image that
covers it is hidden whatever the layout intended, and a source image drawn at another
shape than its own is stretched. DOCX: every drawing must point at an embedded image,
keep the shape of the part of the image it shows, carry alt text and have its own id.

Each finding is ``{"code", "page" or "part", "detail"}``; no findings means no fault of
these kinds, not that the page looks good.
"""

from __future__ import annotations

import io
import posixpath
import re
import zipfile
from typing import Dict, List

from lxml import etree
from PIL import Image

_NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
}
_EMBED = f"{{{_NS['r']}}}embed"
_PARTS = re.compile(r"word/(document|header\d*|footer\d*)\.xml$")
_HIDDEN_SHARE = 0.3
_ASPECT_TOLERANCE = 0.03


def _area(rect) -> float:
    return max(0.0, rect[2] - rect[0]) * max(0.0, rect[3] - rect[1])


def _covered(text, image) -> float:
    overlap = (max(text[0], image[0]), max(text[1], image[1]), min(text[2], image[2]), min(text[3], image[3]))
    return _area(overlap) / (_area(text) or 1.0)


def check_pdf_media(data: bytes) -> List[Dict]:
    import pymupdf
    findings = []
    doc = pymupdf.open(stream=data, filetype="pdf")
    for number, page in enumerate(doc, start=1):
        painted = []
        for kind, rect in page.get_bboxlog():
            if kind == "fill-text":
                painted.append(rect)
            elif kind == "fill-image":
                hidden = sum(_covered(t, rect) > _HIDDEN_SHARE for t in painted)
                if hidden:
                    findings.append({"code": "text_under_image", "page": number,
                                     "detail": f"{hidden} text runs are painted before an image over them"})
        for info in page.get_image_info():
            a, b, c, d, _, _ = info["transform"]
            if abs(b) > 1e-3 or abs(c) > 1e-3 or not (a and d and info["width"] and info["height"]):
                continue                                  # rotated: its box is not its shape
            drawn, source = abs(a / d), info["width"] / info["height"]
            if abs(drawn / source - 1) > _ASPECT_TOLERANCE:
                findings.append({"code": "image_distorted", "page": number,
                                 "detail": f"source shape {source:.3f}, drawn at {drawn:.3f}"})
    return findings


def _rels(z: zipfile.ZipFile, part: str) -> Dict[str, str]:
    path = posixpath.join(posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels")
    if path not in z.namelist():
        return {}
    root = etree.fromstring(z.read(path))
    return {r.get("Id"): posixpath.normpath(posixpath.join(posixpath.dirname(part), r.get("Target")))
            for r in root if r.get("TargetMode") != "External"}


def _drawing_findings(z, part, drawing, rels, seen) -> List[Dict]:
    out = []
    blip = drawing.find(".//a:blip", _NS)
    if blip is None:
        return out                                        # a shape, not a picture
    doc_pr = drawing.find("wp:docPr", _NS)
    extent = drawing.find("wp:extent", _NS)
    shape_id = doc_pr.get("id")
    if (part, shape_id) in seen:
        out.append({"code": "docx_duplicate_shape_id", "part": part, "detail": shape_id})
    seen.add((part, shape_id))
    if not (doc_pr.get("descr") or "").strip():
        out.append({"code": "docx_image_no_alt", "part": part, "detail": f"shape {shape_id}"})
    target = rels.get(blip.get(_EMBED))
    if target is None or target not in z.namelist():
        out.append({"code": "docx_image_not_embedded", "part": part, "detail": f"shape {shape_id}"})
        return out
    with Image.open(io.BytesIO(z.read(target))) as image:
        width, height = image.size
    crop = drawing.find(".//a:srcRect", _NS)
    if crop is not None:
        share = {k: int(crop.get(k, 0)) / 100000 for k in "ltrb"}
        width *= 1 - share["l"] - share["r"]
        height *= 1 - share["t"] - share["b"]
    drawn = int(extent.get("cx")) / int(extent.get("cy"))
    if abs(drawn / (width / height) - 1) > _ASPECT_TOLERANCE:
        out.append({"code": "docx_image_distorted", "part": part,
                    "detail": f"shape {shape_id}: source {width / height:.3f}, drawn {drawn:.3f}"})
    return out


def check_docx_media(data: bytes) -> List[Dict]:
    findings: List[Dict] = []
    seen = set()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for part in z.namelist():
            if not _PARTS.match(part):
                continue
            root = etree.fromstring(z.read(part))
            rels = _rels(z, part)
            for drawing in root.iterfind(".//wp:inline", _NS):
                findings += _drawing_findings(z, part, drawing, rels, seen)
            for drawing in root.iterfind(".//wp:anchor", _NS):
                findings += _drawing_findings(z, part, drawing, rels, seen)
    return findings


def docx_media_summary(data: bytes) -> Dict:
    """Counts that show the DOCX stayed a Word document."""
    out = {"inline": 0, "anchored": 0, "embedded_images": 0, "text_runs": 0, "live_fields": 0}
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        out["embedded_images"] = sum(n.startswith("word/media/") for n in z.namelist())
        for part in z.namelist():
            if _PARTS.match(part):
                xml = z.read(part)
                root = etree.fromstring(xml)
                out["inline"] += len(root.findall(".//wp:inline", _NS))
                out["anchored"] += len(root.findall(".//wp:anchor", _NS))
                out["text_runs"] += len(root.findall(".//w:t", _NS))
                out["live_fields"] += len(root.findall(".//w:instrText", _NS))
    return out
