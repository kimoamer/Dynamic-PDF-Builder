"""A cover page with a backdrop: full-page image, colour or split panel, with the text
kept as live text over it. The legacy cover in ``factory`` stays for plain covers."""

from __future__ import annotations

from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Indenter, PageBreak, Spacer

from .. import policy as _diag
from ..fonts import get_font_name
from ..media import (LOGO_RESOLUTION_DPI, PageGeometry, check_resolution, cover_text_color, fit_image,
                     ingest)
from ..schema.media import ImageTreatment
from ..utils.errors import DynamicPDFError
from .media_flow import MediaFlowable, PageItem, PanelMark
from .page_system import readable_on


def _load(src, label, collector):
    try:
        return ingest(src, collector.policy.assets)
    except DynamicPDFError as e:
        collector.fail("asset_failed", f"{label}: {e}", e)
        return None


def _panel(geo: PageGeometry, split: bool, rtl: bool):
    """x, y from the bottom, width and height of the image area."""
    if not split:
        return 0.0, 0.0, geo.width, geo.height
    w = geo.width * 0.46
    return (0.0 if rtl else geo.width - w), 0.0, w, geo.height


def cover_plan(block, geo: PageGeometry, rtl: bool, collector):
    """What a designed cover draws, for both renderers: the layout, the layers and
    the text colour."""
    layout = block.layout or "left_aligned"
    split = layout == "split" and bool(block.background_image)
    layers = []
    fill = block.background_color
    if fill:
        layers.append(PageItem(None, None, 0, 0, ImageTreatment(), True, -2, fill=fill,
                               w=geo.width, h=geo.height))
    asset = _load(block.background_image, "Cover background", collector) if block.background_image else None
    overlay, opacity = block.overlay_color, block.overlay_opacity
    ink = block.text_color
    if asset is not None:
        x, y, w, h = _panel(geo, split, rtl)
        t = block.background_treatment or ImageTreatment(fit="cover")
        if t.fit != "cover":
            t = t.model_copy(update={"fit": "cover"})
        f = fit_image(asset, w, h, t)
        check_resolution(asset, f, collector, "Cover background", 96)
        layers.append(PageItem(asset, f, x, y, t, True, -1))
        if not split:
            auto_ink, auto_overlay = cover_text_color(asset, f, overlay, opacity)
            ink = ink or auto_ink
            if auto_overlay and not overlay:
                overlay, opacity = auto_overlay
        if overlay and opacity:
            layers.append(PageItem(None, None, x, y, t, True, 0, fill=overlay, fill_opacity=opacity,
                                   w=w, h=h))
    if not ink and fill and not split:
        ink = readable_on(fill)
    return layout, split, layers, ink


def designed_cover(block, theme, ctx) -> list:
    from .factory import Paragraph, _is_rtl, _md_inline, _safe_color, _label
    geo = ctx.page_geometry
    rtl = _is_rtl(block.title) or geo.rtl
    layout, split, layers, ink = cover_plan(block, geo, rtl, _diag.current())
    primary = _safe_color(ink or theme.colors.text_primary)
    secondary = _safe_color(ink or theme.colors.text_secondary)
    align = 1 if layout == "centered" else (2 if rtl else 0)
    size = theme.typography.base_size * theme.typography.heading_scale[0] * 1.4
    arabic = get_font_name(theme.typography.arabic_family or "Amiri", bold=True)
    arabic_body = get_font_name(theme.typography.arabic_family or "Amiri")

    def face(text, regular, bold=False):
        return (arabic if bold else arabic_body) if _is_rtl(text) else regular

    frame_h = ctx.available_height or geo.height - geo.top - geo.bottom
    story = [PanelMark(layers)]
    indent = geo.width * 0.46 + 24 - geo.right if split else 0
    if indent:
        story.append(Indenter(left=indent) if rtl else Indenter(right=indent))
    used = 0.0
    if block.logo:
        asset = _load(block.logo, "Cover logo", _diag.current())
        if asset is not None:
            w = min(170.0, 58 * asset.aspect)
            logo = MediaFlowable(asset, w, w / asset.aspect, ImageTreatment(),
                                 {0: "RIGHT" if rtl else "LEFT", 1: "CENTER", 2: "RIGHT"}[align])
            check_resolution(asset, logo.fitted, _diag.current(), "Cover logo", LOGO_RESOLUTION_DPI)
            story.append(logo)
            used += logo.outer_h
    drop = frame_h * (0.30 if layout == "centered" else 0.46)
    story.append(Spacer(1, max(24, drop - used)))
    title = ParagraphStyle(
        "CoverTitle", fontName=face(block.title, get_font_name(theme.typography.heading_family, bold=True), True),
        fontSize=size, leading=size * (1.5 if _is_rtl(block.title) else 1.18), textColor=primary,
        alignment=align, spaceAfter=size * 0.45)
    story.append(Paragraph(_md_inline(block.title), title))
    body = get_font_name(theme.typography.body_family)
    if block.subtitle:
        sub = ParagraphStyle("CoverSub", fontName=face(block.subtitle, body), textColor=secondary,
                             fontSize=theme.typography.base_size * 1.35,
                             leading=theme.typography.base_size * (2.2 if _is_rtl(block.subtitle) else 1.75),
                             alignment=align, spaceAfter=22)
        story.append(Paragraph(_md_inline(block.subtitle), sub))
    for text in ((f"{_label('prepared_by')} {block.author}" if block.author else None), block.date):
        if text:
            line = ParagraphStyle("CoverLine", fontName=face(text, body), textColor=secondary,
                                  fontSize=theme.typography.base_size,
                                  leading=theme.typography.base_size * (1.9 if _is_rtl(text) else 1.45),
                                  alignment=align, spaceAfter=3)
            story.append(Paragraph(_md_inline(text), line))
    if indent:
        story.append(Indenter(left=-indent) if rtl else Indenter(right=-indent))
    story.append(PageBreak())
    return story
