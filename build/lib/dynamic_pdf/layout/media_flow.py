"""
PDF drawing of the shared media model: images in the flow, floats that text wraps
around, and layers on the page itself.

A page layer is recorded while the page fills and drawn when it ends, because only
then is everything about the page known (its section, whether it is a cover). Layers
behind the text are then moved to the start of the page's content stream, so they
sit under text that was drawn earlier, and that text stays real, selectable text.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import List, Optional

from reportlab.lib.colors import Color, HexColor
from reportlab.lib.utils import ImageReader
from reportlab.platypus import PageBreak
from reportlab.platypus.flowables import Flowable

from ..media import (Fitted, MediaAsset, PageGeometry, cropped_raster, fit_image, page_box,
                     page_position, reference_box, rotated_size)
from ..schema.media import ImageTreatment, MediaPlacement


def _reader(canv, asset: MediaAsset, fitted: Fitted) -> ImageReader:
    cache = canv.__dict__.setdefault("_dpb_readers", {})
    key = (asset.sha256, fitted.crop, round(fitted.width), round(fitted.height))
    if key not in cache:
        cache[key] = ImageReader(io.BytesIO(cropped_raster(asset, fitted)))
    return cache[key]


def _draw_vector(canv, asset: MediaAsset, f: Fitted, x: float, y: float) -> None:
    from reportlab.graphics import renderPDF
    from ..svg_safe import drawing
    d = drawing(asset.svg)
    left, top, right, bottom = f.crop
    full_w, full_h = f.width / (1 - left - right), f.height / (1 - top - bottom)
    canv.saveState()
    path = canv.beginPath()
    path.rect(x, y, f.width, f.height)
    canv.clipPath(path, stroke=0, fill=0)
    canv.translate(x - full_w * left, y - full_h * bottom)
    canv.scale(full_w / d.width, full_h / d.height)
    renderPDF.draw(d, canv, 0, 0)
    canv.restoreState()


def _shadow(canv, x: float, y: float, w: float, h: float) -> None:
    """A soft shadow from a few stacked translucent rectangles: vector, no raster."""
    canv.saveState()
    for step in range(5, 0, -1):
        grow = step * 1.1
        canv.setFillColor(Color(0, 0, 0, alpha=0.035))
        canv.rect(x + 2.5 - grow / 2, y - 2.5 - grow / 2, w + grow, h + grow, fill=1, stroke=0)
    canv.restoreState()


def draw_media(canv, asset: MediaAsset, fitted: Fitted, x: float, y: float,
               treatment: Optional[ImageTreatment] = None) -> None:
    """Draw with the bottom left of the *image* at ``x``, ``y``."""
    t = treatment or ImageTreatment()
    w, h = fitted.width, fitted.height
    canv.saveState()
    if t.rotation:
        canv.translate(x + w / 2, y + h / 2)
        canv.rotate(-t.rotation)
        x, y = -w / 2, -h / 2
    if t.shadow:
        _shadow(canv, x, y, w, h)
    if t.opacity < 1:
        canv.setFillAlpha(t.opacity)
        canv.setStrokeAlpha(t.opacity)
    if asset.is_vector:
        _draw_vector(canv, asset, fitted, x, y)
    else:
        canv.drawImage(_reader(canv, asset, fitted), x, y, w, h, mask="auto")
    if t.border_width:
        canv.setStrokeColor(HexColor(t.border_color or "#9AA3AE"))
        canv.setLineWidth(t.border_width)
        canv.rect(x, y, w, h, fill=0, stroke=1)
    canv.restoreState()


class MediaFlowable(Flowable):
    """An image in the text flow, with border, shadow, crop, rotation and opacity."""

    def __init__(self, asset: MediaAsset, box_w: float, box_h: float, treatment=None,
                 align: str = "CENTER", bleed_left: Optional[float] = None, alt: str = ""):
        super().__init__()
        self.asset, self.box_w, self.box_h = asset, box_w, box_h
        self.treatment = treatment or ImageTreatment()
        self.hAlign = "LEFT" if bleed_left is not None else align
        self.bleed_left = bleed_left
        self.alt = alt
        self.fitted = fit_image(asset, box_w, box_h, self.treatment)
        pad = self.treatment.padding * 2
        self.outer_w, self.outer_h = rotated_size(self.fitted.width + pad, self.fitted.height + pad,
                                                  self.treatment.rotation)

    def wrap(self, aw, ah):
        self.width, self.height = self.outer_w, self.outer_h
        return self.width, self.height

    def draw(self):
        f, pad = self.fitted, self.treatment.padding
        x = (self.outer_w - f.width) / 2 if self.treatment.rotation else pad
        y = (self.outer_h - f.height) / 2 if self.treatment.rotation else pad
        if self.bleed_left is not None:
            x -= self.canv.absolutePosition(0, 0)[0]
        draw_media(self.canv, self.asset, f, x, y, self.treatment)


class _ZeroFlowable(Flowable):
    _dpb_role = "decorative"

    def __init__(self):
        super().__init__()
        self.width = self.height = 0

    def wrap(self, aw, ah):
        return 0, 0


@dataclass
class PageItem:
    """An image bound for the current page, positioned from the page's bottom left."""
    asset: MediaAsset
    fitted: Fitted
    x: float
    y: float
    treatment: ImageTreatment
    behind: bool = True
    z: int = 0
    fill: Optional[str] = None       # a plain colour panel instead of an image
    fill_opacity: float = 1.0
    w: float = 0
    h: float = 0


def add_page_item(canv, item: PageItem) -> None:
    canv.__dict__.setdefault("_dpb_items", []).append(item)


class FlowAnchoredLayer(_ZeroFlowable):
    """An image over or under the page, positioned where this point in the text falls
    (``relative_to="content"``) or against the page or margins."""

    def __init__(self, asset, placement: MediaPlacement, treatment, geo: PageGeometry,
                 box_w: float, box_h: float):
        super().__init__()
        self.asset, self.placement, self.treatment, self.geo = asset, placement, treatment, geo
        self.box = box_w, box_h

    def draw(self):
        canv, p, geo = self.canv, self.placement, self.geo
        f = fit_image(self.asset, *self.box, self.treatment)
        if p.relative_to == "content":
            ax, ay = canv.absolutePosition(0, 0)
            bw = geo.width - geo.left - geo.right
            x = ax + (bw - self.box[0]) / 2 + f.x
            y = ay - self.box[1] + (self.box[1] - f.height - f.y)
        else:
            x, top = page_position(geo, p, *self.box)
            x, y = x + f.x, geo.height - top - f.y - f.height
        add_page_item(canv, PageItem(self.asset, f, x, y, self.treatment, p.mode != "in_front_of_text",
                                     p.z_index))


class PanelMark(_ZeroFlowable):
    """Marks a page bare of bands, with optional layers such as a cover's backdrop."""

    def __init__(self, items=(), bare: bool = True):
        super().__init__()
        self.items, self.bare = list(items), bare

    def draw(self):
        for item in self.items:
            add_page_item(self.canv, item)
        if self.bare:
            self.canv._dpb_bare = True


class SectionMark(_ZeroFlowable):
    """Everything after this point belongs to the named page section."""

    def __init__(self, name: str):
        super().__init__()
        self.name = name

    def draw(self):
        self.canv._dpb_section = self.name


def page_layer_items(blocks, geo_for, page: int, section: Optional[str], assets) -> List[PageItem]:
    """The document-level layers that apply to this page."""
    out = []
    for b in blocks:
        applies = (b.scope == "every_page" or (b.scope == "cover" and page == 1)
                   or (b.scope == "sections" and section in b.sections))
        if not applies:
            continue
        asset = assets(b)
        if asset is None:
            continue
        geo = geo_for
        box = page_box(geo, b.placement)
        f = fit_image(asset, box[0], box[1], b.treatment)
        x, top = page_position(geo, b.placement, *box)
        out.append(PageItem(asset, f, x + f.x, geo.height - top - f.y - f.height, b.treatment,
                            b.layer == "behind", b.placement.z_index))
    return out


def draw_page_items(canv, items: List[PageItem]) -> None:
    for it in sorted(items, key=lambda i: i.z):
        if it.fill:
            canv.saveState()
            c = HexColor(it.fill)
            canv.setFillColor(Color(c.red, c.green, c.blue, alpha=it.fill_opacity))
            canv.rect(it.x, it.y, it.w, it.h, fill=1, stroke=0)
            canv.restoreState()
        else:
            draw_media(canv, it.asset, it.fitted, it.x, it.y, it.treatment)


def move_to_page_start(canv, start: int, mark: int) -> None:
    """Move what was drawn after ``start`` to ``mark``, under the rest of the page."""
    code = canv._code
    ops = code[start:]
    del code[start:]
    code[mark:mark] = ops


# ─────────────────────────── text wrapped around a float ───────────────────────────

class FloatPlaced(Flowable):
    """A figure and the narrow text beside it, measured and ready to draw."""

    def __init__(self, figure, beside, fig_w, side, gutter, width, height):
        super().__init__()
        self.figure, self.beside = figure, beside
        self.fig_w, self.side, self.gutter = fig_w, side, gutter
        self.width, self.height = width, height

    def wrap(self, aw, ah):
        return self.width, self.height

    def draw(self):
        canv = self.canv
        narrow = self.width - self.fig_w - self.gutter
        fig_x = 0 if self.side == "left" else self.width - self.fig_w
        text_x = self.fig_w + self.gutter if self.side == "left" else 0
        drawn = []
        y = self.height
        for f in self.figure:
            w, h = f.wrapOn(canv, self.fig_w, 1e6)
            y -= h
            x = fig_x + (self.fig_w - w) / 2 if getattr(f, "hAlign", "") == "CENTER" else fig_x
            f.drawOn(canv, x, y)
            drawn.append((f, x, y, w, h, True))
            y -= f.getSpaceAfter()
        y = self.height
        for k, f in enumerate(self.beside):
            _, h = f.wrapOn(canv, narrow, 1e6)
            if k:
                y -= f.getSpaceBefore()
            y -= h
            f.drawOn(canv, text_x, y)
            drawn.append((f, text_x, y, narrow, h, False))
            y -= f.getSpaceAfter()
        self._dpb_children = drawn


def _pieces(source, parts):
    """Pieces of a split flowable belong to the block ``source`` came from."""
    for part in parts or []:
        for attr in ("_dpb_block", "_dpb_role", "_dpb_level"):
            if hasattr(source, attr) and not hasattr(part, attr):
                setattr(part, attr, getattr(source, attr))
    return parts


class FloatRegion(Flowable):
    """Square wrap, resolved when the page position is known.

    The document template calls ``expand``: paragraphs run narrow beside the figure,
    the one that outlasts it is split there and continues at full width. With too
    little room left on the page, text moves up ahead of the figure instead of
    leaving a gap, as a float does in print."""

    def __init__(self, figure, items, fig_w, side, gutter):
        super().__init__()
        self.figure, self.items = figure, list(items)
        self.fig_w, self.side, self.gutter = fig_w, side, gutter

    def wrap(self, aw, ah):
        return aw, self._fig_height(aw)

    def draw(self):                                # reached only if never expanded
        pass

    def _fig_height(self, aw) -> float:
        total = 0.0
        for f in self.figure:
            _, h = f.wrap(self.fig_w, 1e6)
            total += h + f.getSpaceAfter()
        return total

    def _pack(self, aw):
        """The items beside the figure, those after it, and the region's height."""
        fig_h = self._fig_height(aw)
        narrow = aw - self.fig_w - self.gutter
        beside, used = [], 0.0
        for k, f in enumerate(self.items):
            if used >= fig_h:
                return beside, self.items[k:], max(fig_h, used)
            gap = f.getSpaceBefore() if beside else 0
            _, h = f.wrap(narrow, 1e6)
            if used + gap + h <= fig_h + 2:
                beside.append(f)
                used += gap + h + f.getSpaceAfter()
                continue
            room = fig_h - used - gap
            parts = _pieces(f, f.split(narrow, room)) if room > 0 and hasattr(f, "split") else []
            if len(parts) >= 2:
                head = parts[0]
                used += gap + head.wrap(narrow, 1e6)[1]
                beside.append(head)
                return beside, [*parts[1:], *self.items[k + 1:]], max(fig_h, used)
            return beside, self.items[k:], max(fig_h, used)
        return beside, [], max(fig_h, used)

    def expand(self, aw: float, avail: float, frame_h: float) -> list:
        beside, rest, height = self._pack(aw)
        if height <= avail or avail >= frame_h - 1:
            return [FloatPlaced(self.figure, beside, self.fig_w, self.side, self.gutter, aw, height),
                    *rest]
        if self.items:
            first = self.items[0]
            _, h = first.wrap(aw, avail)
            again = FloatRegion(self.figure, self.items[1:], self.fig_w, self.side, self.gutter)
            if h + first.getSpaceAfter() <= avail:
                return [first, again]
            parts = _pieces(first, first.split(aw, avail)) if hasattr(first, "split") else []
            if len(parts) >= 2:
                again.items = [*parts[1:], *self.items[1:]]
                return [parts[0], again]
        return [PageBreak(), self]


__all__ = ["MediaFlowable", "FloatRegion", "FloatPlaced", "FlowAnchoredLayer", "PanelMark",
           "SectionMark", "PageItem", "add_page_item", "draw_media", "draw_page_items",
           "move_to_page_start", "page_layer_items", "reference_box"]
