"""
Safe SVG ingestion.

An SVG is a program as much as a picture: it can reference files, pull from the
network, expand entities and run script. Only drawing elements survive here, and a
file that asks for anything else is refused rather than quietly altered. PDF keeps
the vectors; Word gets the SVG with a PNG beside it for older readers.
"""

from __future__ import annotations

import io
import os
import re
import tempfile
import xml.etree.ElementTree as ET
from functools import lru_cache
from typing import List, Tuple

from .utils.errors import AssetError, ResourceLimitError

_SVG = "http://www.w3.org/2000/svg"
_XLINK = "http://www.w3.org/1999/xlink"
_MAX_BYTES = 4 * 1024 * 1024
_MAX_ELEMENTS = 30_000
_DRAWING = {"svg", "g", "defs", "symbol", "use", "title", "desc", "path", "rect", "circle", "ellipse",
            "line", "polyline", "polygon", "text", "tspan", "linearGradient", "radialGradient",
            "stop", "clipPath", "mask", "pattern", "style"}
_REFUSED = {"script", "foreignObject", "iframe", "image", "audio", "video", "embed", "object",
            "animate", "animateTransform", "animateMotion", "set", "a", "feImage"}
_ANY_URL = re.compile(r"url\(\s*['\"]?(?!#)", re.I)
_NUMBER = re.compile(r"^\s*([0-9.]+)\s*(px|pt|mm|cm|in)?\s*$")
_UNIT = {None: 0.75, "px": 0.75, "pt": 1.0, "mm": 72 / 25.4, "cm": 72 / 2.54, "in": 72.0}


def _length(value) -> float:
    m = _NUMBER.match(value or "")
    return float(m.group(1)) * _UNIT[m.group(2)] if m else 0.0


def _local(tag: str) -> Tuple[str, str]:
    if tag.startswith("{"):
        ns, _, name = tag[1:].partition("}")
        return ns, name
    return "", tag


def _size(root) -> Tuple[float, float]:
    w, h = _length(root.get("width")), _length(root.get("height"))
    box = re.split(r"[\s,]+", (root.get("viewBox") or "").strip())
    if len(box) == 4:
        try:
            vw, vh = abs(float(box[2])), abs(float(box[3]))
        except ValueError:
            vw = vh = 0
        if vw and vh:
            if w and not h:
                h = w * vh / vw
            elif h and not w:
                w = h * vw / vh
            elif not w:
                w, h = vw * 0.75, vh * 0.75
    return w, h


def sanitise(raw: bytes, policy, label: str) -> Tuple[bytes, float, float, List[str]]:
    """Clean SVG bytes, its intrinsic width and height in points, and notes."""
    if len(raw) > min(policy.max_bytes, _MAX_BYTES):
        raise ResourceLimitError(f"SVG is {len(raw)} bytes, above the limit: {label}")
    lowered = raw.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise AssetError(f"SVG with a DOCTYPE or entities refused: {label}")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        raise AssetError(f"Not a valid SVG: {label} ({e})") from e
    if _local(root.tag)[1] != "svg":
        raise AssetError(f"Not a valid SVG: {label}")
    notes: List[str] = ["svg_sanitised"]
    for parent in list(root.iter()):
        for el in list(parent):
            ns, tag = _local(el.tag)
            if tag in _REFUSED:
                raise AssetError(f"SVG with <{tag}> refused: {label}")
            if ns not in (_SVG, "") or tag not in _DRAWING:
                parent.remove(el)                    # editor metadata and the like
                if "svg_extras_removed" not in notes:
                    notes.append("svg_extras_removed")
    for count, el in enumerate(root.iter(), 1):
        if count > _MAX_ELEMENTS:
            raise ResourceLimitError(f"SVG has more than {_MAX_ELEMENTS} elements: {label}")
        if _local(el.tag)[1] == "style" and el.text and (
                "@import" in el.text.lower() or _ANY_URL.search(el.text)):
            raise AssetError(f"SVG stylesheet with external references refused: {label}")
        for key, value in el.attrib.items():
            attr = _local(key)[1].lower()
            if attr.startswith("on"):
                raise AssetError(f"SVG with script attribute {attr} refused: {label}")
            if attr == "href" and not value.strip().startswith("#"):
                raise AssetError(f"SVG with external link refused: {label}")
            if _ANY_URL.search(value):
                raise AssetError(f"SVG with external reference refused: {label}")
    w, h = _size(root)
    if w <= 0 or h <= 0:
        raise AssetError(f"SVG has no usable size: {label}")
    ET.register_namespace("", _SVG)
    ET.register_namespace("xlink", _XLINK)
    return ET.tostring(root, encoding="utf-8"), w, h, notes


@lru_cache(maxsize=32)
def drawing(svg: bytes):
    """A ReportLab drawing of cleaned SVG, for vector output."""
    from svglib.svglib import svg2rlg
    handle, name = tempfile.mkstemp(suffix=".svg")
    try:
        with os.fdopen(handle, "wb") as f:
            f.write(svg)
        d = svg2rlg(name)
    finally:
        os.unlink(name)
    if d is None or not d.width or not d.height:
        raise AssetError("SVG could not be drawn")
    return d


def _colour(c, opacity=None):
    if c is None:
        return "none"
    alpha = getattr(c, "alpha", 1)
    alpha = (1 if alpha is None else alpha) * (1 if opacity is None else opacity)
    return (c.red, c.green, c.blue, alpha)


def _path(shape):
    """A Matplotlib path for one ReportLab shape, or None if it draws nothing."""
    from matplotlib.path import Path
    from matplotlib.transforms import Affine2D
    from reportlab.graphics import shapes as S
    if isinstance(shape, S.Rect):
        x, y, w, h = shape.x, shape.y, shape.width, shape.height
        return Path([(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)])
    if isinstance(shape, S.Circle):
        return Path.unit_circle().transformed(Affine2D().scale(shape.r).translate(shape.cx, shape.cy))
    if isinstance(shape, S.Ellipse):
        return Path.unit_circle().transformed(
            Affine2D().scale(shape.rx, shape.ry).translate(shape.cx, shape.cy))
    if isinstance(shape, S.Line):
        return Path([(shape.x1, shape.y1), (shape.x2, shape.y2)])
    if isinstance(shape, (S.PolyLine, S.Polygon)):
        p = list(shape.points)
        pts = list(zip(p[0::2], p[1::2]))
        if isinstance(shape, S.Polygon) and pts:
            pts.append(pts[0])
        return Path(pts) if len(pts) > 1 else None
    if isinstance(shape, S.Path):
        verts, codes, i = [], [], 0
        pts = list(shape.points)
        for op in shape.operators:
            if op in (S._MOVETO, S._LINETO):
                verts.append((pts[i], pts[i + 1]))
                codes.append(Path.MOVETO if op == S._MOVETO else Path.LINETO)
                i += 2
            elif op == S._CURVETO:
                verts += [(pts[i + k], pts[i + k + 1]) for k in (0, 2, 4)]
                codes += [Path.CURVE4] * 3
                i += 6
            elif op == S._CLOSEPATH and verts:
                verts.append(verts[-1])
                codes.append(Path.CLOSEPOLY)
        return Path(verts, codes) if verts else None
    return None


def rasterise(svg: bytes, width_px: int = 1600) -> bytes:
    """A transparent PNG of cleaned SVG, for renderers that cannot keep vectors.
    Uses Matplotlib, already a core dependency: ReportLab's own bitmap renderer
    is an optional extra."""
    from .utils.optional import require_matplotlib
    require_matplotlib()
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from matplotlib.patches import PathPatch
    from matplotlib.transforms import Affine2D
    from reportlab.graphics import shapes as S
    d = drawing(svg)
    dpi = 100
    fig = Figure(figsize=(width_px / dpi, width_px * d.height / d.width / dpi), dpi=dpi)
    fig.patch.set_alpha(0)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, d.width)
    ax.set_ylim(0, d.height)
    ax.axis("off")
    stroke_scale = width_px / d.width * 72 / dpi

    def walk(node, matrix):
        for child in getattr(node, "contents", None) or []:
            if isinstance(child, S.Group):
                a, b, c, e, f, g = child.transform
                walk(child, Affine2D(matrix=[[a, c, f], [b, e, g], [0, 0, 1]]) + matrix)
                continue
            path = _path(child)
            if path is None:
                continue
            fill = _colour(getattr(child, "fillColor", None), getattr(child, "fillOpacity", None))
            if isinstance(child, S.Line) or (isinstance(child, S.PolyLine) and not isinstance(child, S.Polygon)):
                fill = "none"
            edge = _colour(getattr(child, "strokeColor", None), getattr(child, "strokeOpacity", None))
            width = (getattr(child, "strokeWidth", 1) or 0) * stroke_scale
            ax.add_patch(PathPatch(path, facecolor=fill, edgecolor=edge, linewidth=width,
                                   transform=matrix + ax.transData))

    walk(d, Affine2D())
    out = io.BytesIO()
    FigureCanvasAgg(fig).print_png(out)
    return out.getvalue()
