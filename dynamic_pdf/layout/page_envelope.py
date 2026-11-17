"""
How much of a page the body may use.

The engine, the DOCX renderer and the composer's prediction all ask this question, so
it is answered once here. A theme's margins are a floor; a header or footer band that
needs more room raises them. The tallest band of the system is reserved for every page,
which is conservative on pages with a shorter band, but no body text is laid out in
room that a band will take.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Optional, Tuple

_BAR_HEADERS = {"bar", "gradient", "banner", "split", "logo_left", "logo_right", "modern"}
_BAR_FOOTERS = {"bar", "gradient"}
FRAME_PADDING = 6.0          # ReportLab's default on each side of a frame


@dataclass(frozen=True)
class PageEnvelope:
    page_width: float
    page_height: float
    left: float
    right: float
    top: float
    bottom: float
    band_losses: tuple = ()

    @property
    def width(self) -> float:
        return self.page_width - self.left - self.right

    @property
    def height(self) -> float:
        return self.page_height - self.top - self.bottom

    @property
    def inner_width(self) -> float:
        return self.width - 2 * FRAME_PADDING

    @property
    def inner_height(self) -> float:
        return self.height - 2 * FRAME_PADDING

    @property
    def landscape_size(self) -> Tuple[float, float]:
        w, h = self.page_width, self.page_height
        return (h, w) if h > w else (w, h)


def header_extent(theme) -> float:
    """How far down the page the header style draws: the banner is a tall band, and a centred
    logo stands over a title at twice the header size."""
    hf, ts = theme.header_footer, theme.typography.header_title_size
    if hf.header_style == "banner":
        return max(hf.height, 80.0)
    if hf.header_style == "logo_centered":
        logo = min(hf.logo_max_height, hf.height * 0.5) + 8 if hf.logo else 0
        return max(hf.height, 12 + logo + ts * 2 + 6)
    return hf.height


def page_margins(theme, band_needs: Optional[Tuple[float, float]] = None) -> Tuple[float, float, float, float]:
    """Top, bottom, left and right margins. ``band_needs`` is what a page system asks
    for; without one, the theme's own header and footer styles set the clearance."""
    sp, hf = theme.spacing, theme.header_footer
    top, bottom = sp.page_margin_top, sp.page_margin_bottom
    if band_needs is not None:
        top, bottom = max(top, band_needs[0]), max(bottom, band_needs[1])
    elif hf.enabled:
        top = max(top, header_extent(theme) + (16 if hf.header_style in _BAR_HEADERS else 4))
        bottom = max(bottom, hf.footer_height + 12 if hf.footer_style in _BAR_FOOTERS else 40)
    left, right = sp.page_margin_left, sp.page_margin_right
    if hf.header_style == "sidebar" or hf.footer_style == "sidebar":
        if hf.sidebar_position == "left":
            left += hf.sidebar_width + 4
        else:
            right += hf.sidebar_width + 4
    return top, bottom, left, right


def band_maker(document, theme, system, rtl: bool, assets, collector):
    """The band layout of a document, and its sample field values."""
    from ..design.page_values import band_values, section_texts
    from .page_system import BandMaker
    values, sample = band_values(document, theme.header_footer)
    maker = BandMaker(theme, system, rtl, assets, collector, values)
    if system.lossless:
        maker.section_samples = section_texts(document)
    return maker, sample


def reserve_bands(maker, width: float, sample, collector) -> Tuple[float, float]:
    """The room the bands need. In a lossless system, content that cannot be set whole
    is an error here, before any page is drawn."""
    from .page_system import BandContentUnfit, margin_needs
    needs = margin_needs(maker, width, sample)
    if maker.system.lossless:
        losses = maker.audit(width, sample)
        if losses:
            collector.fail("band_content_unfit", "; ".join(x.describe() for x in losses[:4]),
                           error_cls=BandContentUnfit)
    return needs


def resolve_page_envelope(doc, theme, policy=None, size: Optional[Tuple[float, float]] = None) -> PageEnvelope:
    """The envelope the renderers will use for ``doc``, without rendering it."""
    from ..intelligence.analysis import page_size
    w, h = size or page_size(doc)
    system = doc.meta.page_system
    if system is None:
        top, bottom, left, right = page_margins(theme)
        return PageEnvelope(w, h, left, right, top, bottom)
    from ..fonts import register_fonts
    from ..policy import DiagnosticCollector, RenderPolicy
    from ..schema.page_system import settled
    from .engine import is_rtl_document
    from .page_system import margin_needs
    register_fonts()
    policy = policy or RenderPolicy(error_mode="permissive")
    collector = DiagnosticCollector(policy)
    sp = theme.spacing
    width = w - sp.page_margin_left - sp.page_margin_right
    maker, sample = band_maker(doc, theme, settled(system, doc.blocks), is_rtl_document(doc),
                               policy.assets, collector)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        needs = margin_needs(maker, width, sample)
        losses = tuple(maker.audit(width, sample))
    top, bottom, left, right = page_margins(theme, needs)
    return PageEnvelope(w, h, left, right, top, bottom, losses)
