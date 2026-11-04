"""
Asset engine and placement geometry, shared by the PDF and DOCX renderers.

``ingest`` turns a source into a validated ``MediaAsset``: orientation applied,
colour in sRGB, formats a renderer cannot embed converted, cached by content hash.
The rest is plain geometry: both renderers ask the same questions here, so an image
lands in the same place, at the same size and with the same crop in both.
"""

from __future__ import annotations

import hashlib
import io
import math
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Optional, Tuple

from .assets import AssetPolicy, load_asset_bytes
from .schema.media import ImageTreatment, MediaPlacement
from .utils.errors import AssetError, ResourceLimitError

_CACHE_BYTES = 96 * 1024 * 1024
LOW_RESOLUTION_DPI = 110        # below this a photograph looks soft at print size
LOGO_RESOLUTION_DPI = 150       # small marks show softness sooner
PDF_MAX_DPI = 300


class _ByteBoundCache:
    """Least recently used, bounded by the bytes it holds rather than by entries."""

    def __init__(self, limit: int):
        self.limit, self.size = limit, 0
        self.items: "OrderedDict[str, tuple]" = OrderedDict()
        self.lock = threading.Lock()

    def get(self, key: str):
        with self.lock:
            hit = self.items.get(key)
            if hit is None:
                return None
            self.items.move_to_end(key)
            return hit[0]

    def put(self, key: str, value, size: int) -> None:
        with self.lock:
            if key in self.items or size > self.limit:
                return
            self.items[key] = (value, size)
            self.size += size
            while self.size > self.limit:
                _, (_, freed) = self.items.popitem(last=False)
                self.size -= freed

    def clear(self) -> None:
        with self.lock:
            self.items.clear()
            self.size = 0


_cache = _ByteBoundCache(_CACHE_BYTES)


@dataclass(frozen=True)
class MediaAsset:
    sha256: str
    data: bytes                      # PNG or JPEG; empty for SVG, see raster_bytes
    format: str                      # "png", "jpeg" or "svg"
    width: int                       # pixels; SVG: its intrinsic size in points
    height: int
    dpi: Optional[Tuple[float, float]] = None
    has_alpha: bool = False
    notes: Tuple[str, ...] = ()
    svg: Optional[bytes] = field(default=None, repr=False)

    @property
    def aspect(self) -> float:
        return self.width / self.height

    @property
    def is_vector(self) -> bool:
        return self.svg is not None


def _is_svg(raw: bytes) -> bool:
    head = raw[:1024].lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    return head.startswith(b"<svg") or (head.startswith((b"<?xml", b"<!--")) and b"<svg" in head)


def _to_srgb(im, notes: list):
    """sRGB pixels, keeping any alpha. A wide-gamut or CMYK image would otherwise
    show the wrong colours in viewers that ignore embedded profiles."""
    from PIL import ImageCms
    icc = im.info.get("icc_profile")
    alpha = im.getchannel("A") if im.mode in ("RGBA", "LA") else None
    if icc:
        try:
            profile = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            name = (ImageCms.getProfileDescription(profile) or "").lower()
            if "srgb" in name and im.mode != "CMYK":
                return im, False
            base = im.convert("RGB") if im.mode not in ("RGB", "CMYK", "L") else im
            out = ImageCms.profileToProfile(base, profile, ImageCms.createProfile("sRGB"), outputMode="RGB")
            notes.append("colour_profile_converted")
            if alpha is not None:
                out.putalpha(alpha)
            out.info.pop("icc_profile", None)
            return out, True
        except (OSError, ImageCms.PyCMSError, ValueError):
            notes.append("colour_profile_ignored")
    if im.mode == "CMYK":
        notes.append("cmyk_converted")
        return im.convert("RGB"), True
    return im, False


def _encode(im, lossy: bool) -> Tuple[bytes, str]:
    out = io.BytesIO()
    if lossy and im.mode in ("RGB", "L"):
        im.save(out, "JPEG", quality=92, optimize=True)
        return out.getvalue(), "jpeg"
    if im.mode not in ("1", "L", "LA", "P", "RGB", "RGBA"):
        im = im.convert("RGBA" if "A" in im.getbands() else "RGB")
    im.save(out, "PNG")
    return out.getvalue(), "png"


def _normalise(raw: bytes, digest: str, policy: AssetPolicy, label: str) -> MediaAsset:
    from PIL import Image, ImageOps
    notes: list = []
    try:
        with Image.open(io.BytesIO(raw)) as im:
            source = (im.format or "").upper()
            w, h = im.size
            if w * h > policy.max_pixels:
                raise ResourceLimitError(f"Image {w}x{h} exceeds pixel limit {policy.max_pixels}: {label}")
            if getattr(im, "n_frames", 1) > 1:
                notes.append("first_frame_only")
            im.load()
            info = dict(im.info)
            orientation = im.getexif().get(0x0112, 1)
            work, changed = im, False
            if orientation not in (0, 1):
                work = ImageOps.exif_transpose(work)
                if "icc_profile" in info:
                    work.info["icc_profile"] = info["icc_profile"]
                notes.append("exif_orientation_applied")
                changed = True
            work, converted = _to_srgb(work, notes)
            changed = changed or converted
            dpi = info.get("dpi")
            dpi = (float(dpi[0]), float(dpi[1])) if dpi and dpi[0] and dpi[1] else None
            alpha = work.mode in ("RGBA", "LA", "PA") or "transparency" in info
            if source in ("PNG", "JPEG") and not changed:
                data, fmt = raw, "png" if source == "PNG" else "jpeg"
            else:
                if source not in ("PNG", "JPEG"):
                    notes.append(f"{source.lower()}_converted")
                if work.mode == "P" and not alpha:
                    work = work.convert("RGB")
                data, fmt = _encode(work, source in ("JPEG", "WEBP", "MPO") and not alpha)
            return MediaAsset(digest, data, fmt, work.width, work.height, dpi, alpha, tuple(notes))
    except ResourceLimitError:
        raise
    except Image.DecompressionBombError as e:
        raise ResourceLimitError(f"Image is too large to decode safely: {label} ({e})") from e
    except Exception as e:
        raise AssetError(f"Not a valid image: {label} ({e})") from e


def ingest(src: str, policy: Optional[AssetPolicy] = None) -> MediaAsset:
    """The validated asset for ``src``, under the same policy as every other asset.
    Identical content is decoded once, whatever path or data URI it arrives by."""
    policy = policy or AssetPolicy()
    raw = load_asset_bytes(src, policy)
    digest = hashlib.sha256(raw).hexdigest()
    asset = _cache.get(digest)
    label = src if len(src) <= 80 else src[:77] + "..."
    if asset is None:
        if _is_svg(raw):
            from .svg_safe import sanitise
            clean, w, h, notes = sanitise(raw, policy, label)
            asset = MediaAsset(digest, b"", "svg", max(1, round(w)), max(1, round(h)), None, True,
                               tuple(notes), clean)
        else:
            asset = _normalise(raw, digest, policy, label)
        _cache.put(digest, asset, len(asset.data) + len(asset.svg or b"") + 1024)
    elif asset.width * asset.height > policy.max_pixels and not asset.is_vector:
        raise ResourceLimitError(
            f"Image {asset.width}x{asset.height} exceeds pixel limit {policy.max_pixels}: {label}")
    return asset


def raster_bytes(asset: MediaAsset, width_px: int = 1600) -> bytes:
    """PNG or JPEG bytes for renderers that need pixels, vectors included."""
    if not asset.is_vector:
        return asset.data
    key = f"svgpng:{asset.sha256}:{width_px}"
    png = _cache.get(key)
    if png is None:
        from .svg_safe import rasterise
        png = rasterise(asset.svg, width_px)
        _cache.put(key, png, len(png))
    return png


# ─────────────────────────── fitting an image into a box ───────────────────────────

Crop = Tuple[float, float, float, float]      # fractions removed: left, top, right, bottom


@dataclass(frozen=True)
class Fitted:
    width: float                 # the drawn size, points
    height: float
    x: float = 0                 # offset of the drawn image inside its box
    y: float = 0                 # measured from the top of the box
    crop: Crop = (0, 0, 0, 0)


def _user_crop(t: ImageTreatment) -> Crop:
    if t.crop_left + t.crop_right >= 0.98 or t.crop_top + t.crop_bottom >= 0.98:
        raise AssetError("Image crop removes the whole image")
    return t.crop_left, t.crop_top, t.crop_right, t.crop_bottom


def fit_image(asset: MediaAsset, box_w: float, box_h: float,
              treatment: Optional[ImageTreatment] = None) -> Fitted:
    """Place the image in the box without distorting it. ``contain`` shows all of
    it, centred; ``cover`` fills the box and crops around the focal point."""
    t = treatment or ImageTreatment()
    left, top, right, bottom = _user_crop(t)
    keep_w, keep_h = 1 - left - right, 1 - top - bottom
    aspect = asset.aspect * keep_w / keep_h
    if t.fit == "contain":
        w = min(box_w, box_h * aspect)
        h = w / aspect
        return Fitted(w, h, (box_w - w) / 2, (box_h - h) / 2, (left, top, right, bottom))
    target = box_w / box_h
    fx = min(1, max(0, (t.focal_x - left) / keep_w))
    fy = min(1, max(0, (t.focal_y - top) / keep_h))
    if aspect > target:                      # too wide: trim the sides
        share = target / aspect
        start = min(1 - share, max(0, fx - share / 2))
        left, right = left + keep_w * start, right + keep_w * (1 - share - start)
    else:                                    # too tall: trim top and bottom
        share = aspect / target
        start = min(1 - share, max(0, fy - share / 2))
        top, bottom = top + keep_h * start, bottom + keep_h * (1 - share - start)
    return Fitted(box_w, box_h, 0, 0, (left, top, right, bottom))


def flow_box(asset: MediaAsset, width: Optional[float], height: Optional[float],
             avail_w: float, avail_h: Optional[float], natural_w: Optional[float] = None,
             treatment: Optional[ImageTreatment] = None) -> Tuple[float, float]:
    """The box an in-flow image occupies. Both sizes given are a box to fit; one size
    gives the other through the aspect ratio; neither means the natural size."""
    t = treatment or ImageTreatment()
    left, top, right, bottom = _user_crop(t)
    aspect = asset.aspect * (1 - left - right) / (1 - top - bottom)
    natural_w = natural_w if natural_w is not None else float(asset.width)
    if width and height:
        w, h = width, height
        if t.fit == "contain":
            w = min(w, h * aspect)
            h = w / aspect
    elif width:
        w, h = width, width / aspect
    elif height:
        w, h = height * aspect, height
    else:
        w, h = natural_w, natural_w / aspect
    if w > avail_w:
        h, w = h * avail_w / w, avail_w
    if avail_h and h > avail_h:
        w, h = w * avail_h / h, avail_h
    return w, h


def rotated_size(w: float, h: float, degrees: float) -> Tuple[float, float]:
    """The upright box around a rotated image."""
    a = math.radians(degrees % 180)
    return (abs(w * math.cos(a)) + abs(h * math.sin(a)),
            abs(w * math.sin(a)) + abs(h * math.cos(a)))


def effective_dpi(asset: MediaAsset, fitted: Fitted) -> Optional[float]:
    """Pixels per inch at the drawn size, after cropping. None for vector art."""
    if asset.is_vector or fitted.width <= 0:
        return None
    left, _, right, _ = fitted.crop
    return asset.width * (1 - left - right) / (fitted.width / 72.0)


def check_resolution(asset: MediaAsset, fitted: Fitted, collector, label: str = "Image",
                     minimum: float = LOW_RESOLUTION_DPI) -> None:
    dpi = effective_dpi(asset, fitted)
    if dpi is not None and dpi < minimum and collector is not None:
        collector.warn("image_low_resolution",
                       f"{label} is {dpi:.0f} dpi at its drawn size of {fitted.width:.0f} x "
                       f"{fitted.height:.0f} pt and may look blurry (aim for {minimum:.0f} or more)")


def mean_luminance(asset: MediaAsset, fitted: Fitted) -> float:
    """Average brightness, 0 to 1, of the part of the image that shows."""
    from PIL import Image, ImageStat
    data = raster_bytes(asset, 200)
    with Image.open(io.BytesIO(data)) as im:
        left, top, right, bottom = fitted.crop
        rgba = im.convert("RGBA").crop((round(im.width * left), round(im.height * top),
                                        round(im.width * (1 - right)), round(im.height * (1 - bottom))))
        rgba.thumbnail((64, 64))
        flat = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        flat.alpha_composite(rgba)
        return ImageStat.Stat(flat.convert("L")).mean[0] / 255


def cover_text_color(asset: MediaAsset, fitted: Fitted, overlay: Optional[str], opacity: float):
    """A readable text colour for an image, and the scrim to add when the image is
    too mid-toned for either dark or light text to read on it."""
    lum = mean_luminance(asset, fitted)
    if overlay and opacity:
        c = int(overlay.lstrip("#")[:6], 16)
        o = (0.2126 * (c >> 16 & 255) + 0.7152 * (c >> 8 & 255) + 0.0722 * (c & 255)) / 255
        lum = lum * (1 - opacity) + o * opacity
        return ("#FFFFFF" if lum < 0.55 else "#1F2933"), None
    if 0.32 < lum < 0.72:
        return "#FFFFFF", ("#101820", 0.46)
    return ("#FFFFFF" if lum <= 0.32 else "#1F2933"), None


def cropped_raster(asset: MediaAsset, fitted: Fitted, max_dpi: float = PDF_MAX_DPI) -> bytes:
    """Pixels for a PDF: cropped, and reduced when far finer than print needs, so the
    full source is not embedded for a small crop of it. Cached, so a background on
    every page is prepared once."""
    if asset.is_vector:
        return raster_bytes(asset)
    dpi = effective_dpi(asset, fitted) or 0
    if fitted.crop == (0, 0, 0, 0) and dpi <= max_dpi * 1.25:
        return asset.data
    key = (f"crop:{asset.sha256}:{[round(c, 4) for c in fitted.crop]}:"
           f"{round(fitted.width)}x{round(fitted.height)}:{max_dpi}")
    out = _cache.get(key)
    if out is None:
        from PIL import Image
        with Image.open(io.BytesIO(asset.data)) as im:
            im.load()
            left, top, right, bottom = fitted.crop
            part = im.crop((round(im.width * left), round(im.height * top),
                            round(im.width * (1 - right)), round(im.height * (1 - bottom))))
            limit = max(1, round(fitted.width / 72 * max_dpi))
            if part.width > limit:
                part = part.resize((limit, max(1, round(part.height * limit / part.width))),
                                   Image.Resampling.LANCZOS)
            out, _ = _encode(part, asset.format == "jpeg" and not asset.has_alpha)
        _cache.put(key, out, len(out))
    return out


# ─────────────────────────── placing it on the page ───────────────────────────

@dataclass(frozen=True)
class PageGeometry:
    width: float
    height: float
    left: float
    right: float
    top: float
    bottom: float
    rtl: bool = False


def physical_side(horizontal: str, rtl: bool) -> str:
    """``left``, ``right`` or ``center``, with reading sides mirrored for RTL."""
    if horizontal == "start":
        return "right" if rtl else "left"
    if horizontal == "end":
        return "left" if rtl else "right"
    return horizontal


def reference_box(geo: PageGeometry, relative_to: str) -> Tuple[float, float, float, float]:
    """x, y, width and height of a reference box, y measured from the page top."""
    if relative_to == "page":
        return 0.0, 0.0, geo.width, geo.height
    return geo.left, geo.top, geo.width - geo.left - geo.right, geo.height - geo.top - geo.bottom


def page_position(geo: PageGeometry, p: MediaPlacement, w: float, h: float) -> Tuple[float, float]:
    """Top-left corner of a ``w`` x ``h`` image on the page, from the page's top left."""
    bx, by, bw, bh = reference_box(geo, p.relative_to)
    side = physical_side(p.horizontal, geo.rtl)
    x = {"left": bx, "right": bx + bw - w, "center": bx + (bw - w) / 2}[side]
    x += -p.offset_x if geo.rtl else p.offset_x
    y = {"top": by, "bottom": by + bh - h, "middle": by + (bh - h) / 2}[p.vertical] + p.offset_y
    return x, y


def page_box(geo: PageGeometry, p: MediaPlacement) -> Tuple[float, float]:
    """The size a placement asks for against its reference box."""
    _, _, bw, bh = reference_box(geo, p.relative_to)
    return bw * (p.width_ratio or 1.0), bh * (p.height_ratio or 1.0)


def normal_mode(p: MediaPlacement, in_columns: bool = False) -> str:
    """The behaviour both renderers carry out. Anything that pushes text aside is
    anchored to its paragraph, the one form PDF flow and Word agree on, so a square
    wrap against the page becomes a float at the same side, in step in both."""
    mode, wrap = p.mode, p.text_wrap()
    if mode in ("anchored", "floating"):
        if wrap == "square":
            return "inline" if in_columns else "floating"
        if wrap in ("top_bottom", "inline"):
            return "inline"
        return "in_front_of_text" if p.z_index >= 0 else "behind_text"
    return mode
