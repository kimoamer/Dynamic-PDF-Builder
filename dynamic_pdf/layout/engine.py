"""
Layout Engine — orchestrates Document → Theme → Flowables → Paginated PDF.

Supports 15+ header styles and 13+ footer styles that can be combined
into 100+ unique variations.  Every colour, font-size, position, and
decoration is individually overridable from the theme configuration.
"""
from io import BytesIO
from datetime import datetime
from reportlab.platypus import (SimpleDocTemplate, PageBreak, Spacer,
                                Frame, PageTemplate, BaseDocTemplate)
from reportlab.lib.pagesizes import A4, LETTER, LEGAL, landscape
from reportlab.lib.colors import HexColor, Color
from reportlab.lib.units import inch
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus.flowables import Flowable, KeepTogether
from reportlab.platypus.doctemplate import ActionFlowable
from xml.sax.saxutils import escape as xml_escape
from ..schema.document import Document
from ..schema.enums import PageSize, Orientation
from ..schema.theme import Theme
from ..themes import get_theme
from ..fonts import register_fonts, get_font_name
from .factory import create_flowables, RenderContext
from .. import policy as _policy
from ..policy import RenderPolicy, DiagnosticCollector
from ..assets import load_image
from ..utils.errors import EncryptionError, DynamicPDFError

import os
import math


# ═══════════════════════ Page-count + TOC aware doc template ═══════════════════════

class NumberedCanvas(Canvas):
    """Kept for backward compatibility (import path). Page totals are now
    resolved by ``_PageCounter`` + ``multiBuild``; this canvas adds nothing."""


class _PageCounter(Flowable):
    """Zero-size indexing flowable that makes ``multiBuild`` re-run until the
    page total used while drawing headers/footers equals the real total."""

    def __init__(self, doc):
        super().__init__()
        self._doc = doc
        self.total = None      # total from the previous completed pass
        self._prev = None
        self.width = self.height = 0

    def isIndexing(self):
        return 1

    def isSatisfied(self):
        return self.total is not None and self.total == self._prev

    def beforeBuild(self):
        self._prev = self.total

    def afterBuild(self):
        self.total = self._doc.page

    def notify(self, kind, stuff):
        pass

    def wrap(self, aw, ah):
        return 0, 0

    def draw(self):
        pass


def _landscape_indices(blocks) -> set:
    """Blocks rendered on landscape pages: each flagged block plus the heading
    and short intro that lead into it (so they are not stranded alone on a
    portrait page); adjacent landscape blocks share one landscape run."""
    out = set()
    for i, b in enumerate(blocks):
        if not (getattr(b, "hints", None) or {}).get("landscape"):
            continue
        start, chars, j = i, 0, i - 1
        while j >= 0 and blocks[j].type in ("paragraph", "note", "rich_text") and chars < 900:
            chars += len(getattr(blocks[j], "text", ""))
            j -= 1
        if j >= 0 and blocks[j].type == "heading" and chars < 900:
            start = j
        out.update(range(start, i + 1))
    return out


_ARABIC_BASE = __import__("re").compile("[\u0600-\u06FF\u0750-\u077F]")


class _BidiCanvas(Canvas):
    """Shapes Arabic in header/footer strings (drawn with canvas.drawString)."""
    _dpb_bidi = False

    def _shape(self, text):
        if not (self._dpb_bidi and isinstance(text, str) and _ARABIC_BASE.search(text)):
            return text, None
        from .factory import _apply_rtl
        from ..fonts import get_font_name
        font = get_font_name("Amiri", bold="Bold" in self._fontname)
        return _apply_rtl(text), font

    def _draw(self, fn, x, y, text, *a, **k):
        shaped, font = self._shape(text)
        if font:
            prev = (self._fontname, self._fontsize)
            self.setFont(font, prev[1])
            fn(x, y, shaped, *a, **k)
            self.setFont(*prev)
        else:
            fn(x, y, text, *a, **k)

    def drawString(self, x, y, text, *a, **k):
        self._draw(super().drawString, x, y, text, *a, **k)

    def drawRightString(self, x, y, text, *a, **k):
        self._draw(super().drawRightString, x, y, text, *a, **k)

    def drawCentredString(self, x, y, text, *a, **k):
        self._draw(super().drawCentredString, x, y, text, *a, **k)


class _FlowKeep(KeepTogether):
    """keep-with-next that never wastes a page.

    ReportLab's KeepTogether inserts a frame break whenever the whole group
    (e.g. heading + long table) is taller than the remaining space, leaving
    large gaps. Here the group only moves to the next page when the heading(s)
    plus the first splittable part of the following block do not fit.
    """

    def wrap(self, aW, aH):
        # nested KeepTogether groups report a sentinel height (0xffffff) from
        # wrap(); use their real content height so the outer group is measured right
        W, H = 0.0, 0.0
        for i, f in enumerate(self._content):
            w, h = f.wrapOn(self.canv, aW, aH)
            if isinstance(f, KeepTogether):
                h = getattr(f, "_H", h)
            W = max(W, w)
            H += h + (f.getSpaceBefore() if i else 0) + f.getSpaceAfter()
        self._H = H
        self._H0 = self._content[0].wrapOn(self.canv, aW, aH)[1] if self._content else 0
        self._wrapInfo = aW, aH
        return W, 0xffffff

    def split(self, aW, aH):
        if getattr(self, "_wrapInfo", None) != (aW, aH):
            self.wrap(aW, aH)
        S = self._content[:]
        if self._H <= aH:
            return S
        cf = getattr(self, "_frame", None)
        at_top = bool(cf and getattr(cf, "_atTop", False))
        lead, last = S[:-1], S[-1]
        # a figure group that may shrink (FitFigure) fits if its *minimum* does
        inner = last._content if isinstance(last, KeepTogether) else [last]
        if any(hasattr(f, "min_height") for f in inner):
            lead_h0 = sum(f.wrapOn(self.canv, aW, aH)[1] + f.getSpaceBefore() + f.getSpaceAfter()
                          for f in lead)
            need = 0.0
            for f in inner:
                mh = f.min_height(aW) if hasattr(f, "min_height") else f.wrapOn(self.canv, aW, aH)[1]
                need += mh + f.getSpaceBefore() + f.getSpaceAfter()
            if lead_h0 + need <= aH:
                return S
        lead_h = 0.0
        for f in lead:
            lead_h += f.wrapOn(self.canv, aW, aH)[1] + f.getSpaceBefore() + f.getSpaceAfter()
        rest = aH - lead_h - last.getSpaceBefore()
        fits_part = False
        if rest > 24:
            try:
                parts = last.splitOn(self.canv, aW, rest)
            except Exception:
                parts = []
            # the first real piece must fit beside the heading (KeepTogether groups
            # "split" into their parts, or into a frame break, without shrinking)
            real = [p for p in parts if not isinstance(p, ActionFlowable)]
            if len(parts) > 1 and real and len(real) == len(parts) and not isinstance(last, KeepTogether):
                fits_part = True
            elif real and len(parts) == len(real):
                h0 = real[0].wrapOn(self.canv, aW, rest)[1] + real[0].getSpaceBefore()
                fits_part = h0 <= rest and not isinstance(last, KeepTogether)
        if not fits_part and not at_top:
            tail = self._split_tail(S, aW, aH)
            if tail is not None:
                return tail
            S.insert(0, self.FrameBreak())
        return S

    def _split_tail(self, S, aW, aH):
        """An intro paragraph marked keep-tail (composer hint) does not drag its
        whole body to the next page: it is split so that ≥ 2 lines stay here and
        its last lines move on with the block(s) it introduces."""
        k = max((i for i, f in enumerate(S[:-1]) if getattr(f, "_dpb_keep_tail", 0)), default=None)
        if k is None or not hasattr(S[k], "blPara"):
            return None
        p = S[k]
        above = 0.0
        for f in S[:k]:
            above += f.wrapOn(self.canv, aW, aH)[1] + f.getSpaceBefore() + f.getSpaceAfter()
        p.wrapOn(self.canv, aW, aH)
        leading = p.style.leading
        n_lines = len(getattr(p.blPara, "lines", []) or [])
        keep = n_lines - p._dpb_keep_tail
        h = min(aH - above - p.getSpaceBefore(), keep * leading + 0.01)
        if keep < 2 or h < 2 * leading:
            return None
        parts = p.split(aW, h)
        if len(parts) != 2:
            return None
        for part in parts:              # geometry tags travel with the pieces
            for a in ("_dpb_block", "_dpb_role", "_dpb_level"):
                if hasattr(p, a) and not hasattr(part, a):
                    setattr(part, a, getattr(p, a))
        return list(S[:k]) + [parts[0], self.__class__([parts[1]] + list(S[k + 1:]))]


class _EngineDocTemplate(BaseDocTemplate):
    """Registers heading destinations, PDF outline entries and TOC entries."""

    keepTogetherClass = _FlowKeep

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.keepTogetherClass = _FlowKeep   # BaseDocTemplate sets the default per instance
        self._heading_seq = 0
        self._outline_level = -1

    def handle_keepWithNext(self, flowables):
        """As ReportLab's, but a heading may also be kept with a following
        KeepTogether group (figure + caption, short table) — ReportLab skips
        containers there, which left such headings stranded at page bottoms."""
        from reportlab.platypus.doctemplate import _ktAllow
        i, n = 0, len(flowables)
        while i < n and flowables[i].getKeepWithNext() and _ktAllow(flowables[i]):
            i += 1
        if not i:
            return
        if i < n and (_ktAllow(flowables[i]) or isinstance(flowables[i], KeepTogether)):
            i += 1
        K = self.keepTogetherClass(flowables[:i])
        mbe = getattr(self, '_multiBuildEdits', None)
        for f in K._content[:-1]:
            if mbe:
                if hasattr(f, 'keepWithNext'):
                    mbe((setattr, f, 'keepWithNext', f.keepWithNext))
                else:
                    mbe((delattr, f, 'keepWithNext'))
            f.__dict__['keepWithNext'] = 0
        del flowables[:i]
        flowables.insert(0, K)

    def handle_documentBegin(self):
        self._heading_seq = 0
        self._outline_level = -1
        geo = getattr(self, "_dpb_geometry", None)
        if geo is not None:
            geo.reset()          # keep only the final multiBuild pass
        super().handle_documentBegin()

    def afterFlowable(self, flowable):
        entry = getattr(flowable, "_toc_entry", None)
        if not entry:
            return
        level, text, explicit_id = entry
        self._heading_seq += 1
        key = explicit_id or f"h{self._heading_seq}"
        c = self.canv
        c.bookmarkPage(key)
        # PDF outline levels may not skip (H1 -> H3); clamp to parent+1
        olevel = min(level - 1, self._outline_level + 1)
        self._outline_level = olevel
        c.addOutlineEntry(text, key, level=olevel, closed=olevel >= 1)
        entry = xml_escape(text)
        if _ARABIC_BASE.search(text):
            from .factory import _apply_rtl
            from ..fonts import get_font_name
            entry = f'<font name="{get_font_name("Amiri")}">{xml_escape(_apply_rtl(text))}</font>'
        self.notify('TOCEntry', (level - 1, entry, self.page, key))


# ═══════════════════════ Colour Helpers ═══════════════════════

def _hc(hex_str: str, fallback: str = "#000000") -> HexColor:
    try:
        return HexColor(hex_str)
    except Exception:
        return HexColor(fallback)


def _draw_gradient(canvas, x, y, w, h, c1, c2, direction="horizontal", steps=60):
    """Draw a smooth gradient rectangle."""
    hc1, hc2 = _hc(c1), _hc(c2)
    for i in range(steps):
        t = i / steps
        r = hc1.red   + (hc2.red   - hc1.red)   * t
        g = hc1.green + (hc2.green - hc1.green) * t
        b = hc1.blue  + (hc2.blue  - hc1.blue)  * t
        canvas.setFillColor(Color(r, g, b))
        if direction == "horizontal":
            sx = x + w * t
            sw = w / steps + 1
            canvas.rect(sx, y, sw, h, fill=1, stroke=0)
        elif direction == "vertical":
            sy = y + h * (1 - t)
            sh = h / steps + 1
            canvas.rect(x, sy - sh, w, sh, fill=1, stroke=0)
        else:  # diagonal
            sx = x + w * t
            sy = y + h * (1 - t)
            sw = w / steps + 1
            canvas.rect(sx, sy, sw, h * t + 1, fill=1, stroke=0)


def _draw_image(canvas, path, x, y, max_w, max_h, align="left"):
    """Draw an image (validated through the AssetPolicy), scaled to fit.

    Returns (drawn_width, drawn_height). Asset failures follow the active
    error policy: raise in strict mode, diagnostic + skip in permissive mode.
    """
    from reportlab.lib.utils import ImageReader
    col = _policy.current()
    try:
        buf, (iw, ih) = load_image(path, col.policy.assets)
    except DynamicPDFError as e:
        col.fail("asset_failed", f"Header/footer image: {e}", e)
        return 0, 0
    scale = min(max_w / iw, max_h / ih)
    dw, dh = iw * scale, ih * scale
    if align == "center":
        x = x + (max_w - dw) / 2
    elif align == "right":
        x = x + max_w - dw
    canvas.drawImage(ImageReader(buf), x, y, width=dw, height=dh, mask='auto')
    return dw, dh


# ═══════════════════════ Layout Engine ═══════════════════════

def _role_for(block):
    """Classify a block's flowables (heading/caption/table/figure/…) for geometry."""
    t = getattr(block, "type", "")

    def role(f):
        entry = getattr(f, "_toc_entry", None)
        if entry:
            f._dpb_level = entry[0]
            return "heading"
        name = type(f).__name__
        if name in ("Spacer", "CondPageBreak", "HRFlowable"):
            return "space"            # intentional whitespace / rules: not content density
        if t == "table":
            return "table" if name in ("Table", "LongTable") else (
                "caption" if name == "Paragraph" else "other")
        if t in ("image", "chart", "diagram", "mermaid", "math", "qrcode"):
            return "caption" if name == "Paragraph" else "figure"
        if t in ("bullet_list", "numbered_list", "checklist", "definition_list"):
            return "list"
        if t in ("paragraph", "rich_text", "note", "quote", "callout", "abstract", "footnote",
                 "introduction_page"):
            return "body"
        if t == "code":
            return "code"
        if t in ("page_break", "cover_page", "table_of_contents", "watermark"):
            return "structure"
        return "other"
    return role


class LayoutEngine:
    def __init__(self, document: Document, policy: RenderPolicy = None, theme: Theme = None,
                 geometry=None, cache: dict = None):
        """``geometry`` (intelligence.geometry.Geometry) records occupied regions;
        ``cache`` is a request-local dict reused across candidate renders."""
        self.geometry = geometry
        self.cache = cache
        self.document = document
        self.theme = theme.model_copy(deep=True) if theme is not None else get_theme(document.theme)
        self.policy = policy or RenderPolicy()
        self.diagnostics = DiagnosticCollector(self.policy)
        self.page_count = 0
        self.last_page_fill = None
        self._page_counter = None

    # ─── Page Size ───

    def _get_pagesize(self):
        sizes = {PageSize.A4: A4, PageSize.LETTER: LETTER, PageSize.LEGAL: LEGAL}
        ps = sizes.get(self.document.meta.page_size, A4)
        if self.document.meta.orientation == Orientation.LANDSCAPE:
            return landscape(ps)
        return ps

    # ─── Resolved colours / fonts ───

    def _hdr_bg(self):
        hf = self.theme.header_footer
        return hf.header_bg or self.theme.colors.header_bg

    def _hdr_text(self):
        hf = self.theme.header_footer
        return hf.header_text_color or self.theme.colors.header_text

    def _ftr_bg(self):
        hf = self.theme.header_footer
        return hf.footer_bg or self.theme.colors.footer_bg

    def _ftr_text(self):
        hf = self.theme.header_footer
        return hf.footer_text_color or self.theme.colors.footer_text

    def _hdr_font(self, bold=False, italic=False):
        return get_font_name(self.theme.typography.heading_family, bold=bold, italic=italic)

    def _body_font(self, bold=False, italic=False):
        return get_font_name(self.theme.typography.body_family, bold=bold, italic=italic)

    # ═══════════════════════ HEADER DRAWING ═══════════════════════

    def _draw_header(self, canvas, doc):
        hf = self.theme.header_footer
        if not hf.enabled:
            return
        if hf.skip_first_page_header and doc.page == 1:
            return

        style = hf.header_style.lower().replace("-", "_").replace(" ", "_")
        if style == "none":
            return
        w, h = self._page_wh(canvas)
        bar_h = hf.height
        canvas.saveState()

        # Dispatch to style method
        method = getattr(self, f"_header_{style}", None)
        if method:
            method(canvas, w, h, bar_h, hf)
        else:
            self._header_bar(canvas, w, h, bar_h, hf)

        canvas.restoreState()

    # ─── Header Styles ─────────────────────────────────────────────

    def _header_bar(self, c, w, h, bar_h, hf):
        """Full-width solid colour bar + logo + title + subtitle."""
        c.setFillColor(_hc(self._hdr_bg()))
        c.rect(0, h - bar_h, w, bar_h, fill=1, stroke=0)
        self._header_content(c, w, h, bar_h, hf)

    def _header_gradient(self, c, w, h, bar_h, hf):
        """Gradient bar."""
        end = hf.header_bg_gradient_end or self.theme.colors.secondary
        _draw_gradient(c, 0, h - bar_h, w, bar_h,
                       self._hdr_bg(), end, hf.header_bg_gradient_direction)
        self._header_content(c, w, h, bar_h, hf)

    def _header_line(self, c, w, h, bar_h, hf):
        """Thin line at bottom of header area + text above."""
        lc = hf.header_border_color or hf.header_accent_color or self.theme.colors.border
        # Text
        self._header_content(c, w, h, bar_h, hf, text_color=self.theme.colors.text_primary)
        # Line
        c.setStrokeColor(_hc(lc))
        c.setLineWidth(hf.header_border_width)
        c.line(30, h - bar_h, w - 30, h - bar_h)

    def _header_double_line(self, c, w, h, bar_h, hf):
        """Two parallel lines at bottom."""
        lc = hf.header_border_color or self.theme.colors.border
        self._header_content(c, w, h, bar_h, hf, text_color=self.theme.colors.text_primary)
        c.setStrokeColor(_hc(lc))
        c.setLineWidth(hf.header_border_width)
        c.line(30, h - bar_h, w - 30, h - bar_h)
        c.line(30, h - bar_h - 3, w - 30, h - bar_h - 3)

    def _header_logo_centered(self, c, w, h, bar_h, hf):
        """Centred logo with title underneath — like Oxfam style."""
        y_top = h - 12
        if hf.logo:
            logo_h = min(hf.logo_max_height, bar_h * 0.5)
            _draw_image(c, hf.logo, 30, y_top - logo_h, w - 60, logo_h, align="center")
            y_top -= logo_h + 8
        title = hf.title or self.document.meta.title or ""
        if title:
            ts = self.theme.typography.header_title_size
            c.setFillColor(_hc(self.theme.colors.text_primary))
            c.setFont(self._hdr_font(bold=True), ts * 2)
            c.drawCentredString(w / 2, y_top - ts * 2 + 4, title)

    def _header_logo_left(self, c, w, h, bar_h, hf):
        """Logo left + title right on a bar."""
        c.setFillColor(_hc(self._hdr_bg()))
        c.rect(0, h - bar_h, w, bar_h, fill=1, stroke=0)
        x = 30
        if hf.logo:
            dw, dh = _draw_image(c, hf.logo, x, h - bar_h + (bar_h - hf.logo_max_height) / 2,
                                 hf.logo_max_height * 3, hf.logo_max_height)
            x += dw + 14
        self._header_content(c, w, h, bar_h, hf, x_start=x)

    def _header_logo_right(self, c, w, h, bar_h, hf):
        """Logo right + title left on a bar."""
        c.setFillColor(_hc(self._hdr_bg()))
        c.rect(0, h - bar_h, w, bar_h, fill=1, stroke=0)
        if hf.logo:
            _draw_image(c, hf.logo, w - 30 - hf.logo_max_height * 3,
                        h - bar_h + (bar_h - hf.logo_max_height) / 2,
                        hf.logo_max_height * 3, hf.logo_max_height, align="right")
        self._header_content(c, w, h, bar_h, hf)

    def _header_minimal(self, c, w, h, bar_h, hf):
        """No background — just text."""
        self._header_content(c, w, h, bar_h, hf, text_color=self.theme.colors.text_primary)

    def _header_banner(self, c, w, h, bar_h, hf):
        """Large full-bleed colour band — taller than normal bar."""
        actual_h = max(bar_h, 80)
        c.setFillColor(_hc(self._hdr_bg()))
        c.rect(0, h - actual_h, w, actual_h, fill=1, stroke=0)
        self._header_content(c, w, h, actual_h, hf)

    def _header_accent_top(self, c, w, h, bar_h, hf):
        """Thin accent colour strip at very top of page + text below."""
        ac = hf.header_accent_color or self.theme.colors.accent
        strip_h = 6
        c.setFillColor(_hc(ac))
        c.rect(0, h - strip_h, w, strip_h, fill=1, stroke=0)
        self._header_content(c, w, h, bar_h, hf, text_color=self.theme.colors.text_primary,
                             y_offset=strip_h)

    def _header_underline(self, c, w, h, bar_h, hf):
        """Title with decorative underline."""
        title = hf.title or self.document.meta.title or ""
        ts = self.theme.typography.header_title_size
        tc = self.theme.colors.text_primary
        c.setFillColor(_hc(tc))
        c.setFont(self._hdr_font(bold=True), ts)
        c.drawCentredString(w / 2, h - bar_h * 0.5, title)
        # Underline
        ac = hf.header_accent_color or self.theme.colors.accent
        c.setStrokeColor(_hc(ac))
        c.setLineWidth(2)
        tw = len(title) * ts * 0.4
        c.line(w / 2 - tw / 2, h - bar_h * 0.55, w / 2 + tw / 2, h - bar_h * 0.55)

    def _header_boxed(self, c, w, h, bar_h, hf):
        """Text inside a bordered rectangle."""
        bc = hf.header_border_color or self.theme.colors.border
        c.setStrokeColor(_hc(bc))
        c.setLineWidth(hf.header_border_width)
        c.rect(30, h - bar_h - 2, w - 60, bar_h, fill=0, stroke=1)
        self._header_content(c, w, h, bar_h, hf, text_color=self.theme.colors.text_primary,
                             x_start=42)

    def _header_split(self, c, w, h, bar_h, hf):
        """Two-tone: left half primary, right half secondary."""
        c.setFillColor(_hc(self._hdr_bg()))
        c.rect(0, h - bar_h, w / 2, bar_h, fill=1, stroke=0)
        end = hf.header_bg_gradient_end or self.theme.colors.secondary
        c.setFillColor(_hc(end))
        c.rect(w / 2, h - bar_h, w / 2, bar_h, fill=1, stroke=0)
        self._header_content(c, w, h, bar_h, hf)

    def _header_sidebar(self, c, w, h, bar_h, hf):
        """Vertical colour bar on left or right edge (full page height)."""
        sw = hf.sidebar_width
        sc = hf.sidebar_color or hf.header_accent_color or self.theme.colors.accent
        if hf.sidebar_gradient_end:
            if hf.sidebar_position == "right":
                _draw_gradient(c, w - sw, 0, sw, h, sc, hf.sidebar_gradient_end, "vertical")
            else:
                _draw_gradient(c, 0, 0, sw, h, sc, hf.sidebar_gradient_end, "vertical")
        else:
            c.setFillColor(_hc(sc))
            if hf.sidebar_position == "right":
                c.rect(w - sw, 0, sw, h, fill=1, stroke=0)
            else:
                c.rect(0, 0, sw, h, fill=1, stroke=0)
        # Optional header text on top
        self._header_content(c, w, h, bar_h, hf, text_color=self.theme.colors.text_primary)

    def _header_academic(self, c, w, h, bar_h, hf):
        """Centred italic title + thin rule below — classic academic style."""
        title = hf.title or self.document.meta.title or ""
        ts = self.theme.typography.header_title_size
        c.setFillColor(_hc(self.theme.colors.text_secondary))
        c.setFont(self._body_font(italic=True), ts - 1)
        c.drawCentredString(w / 2, h - bar_h * 0.5, title)
        c.setStrokeColor(_hc(self.theme.colors.border))
        c.setLineWidth(0.5)
        c.line(30, h - bar_h, w - 30, h - bar_h)

    def _header_modern(self, c, w, h, bar_h, hf):
        """Full bar + large white sans-serif title."""
        c.setFillColor(_hc(self._hdr_bg()))
        c.rect(0, h - bar_h, w, bar_h, fill=1, stroke=0)
        title = hf.title or self.document.meta.title or ""
        ts = self.theme.typography.header_title_size
        c.setFillColor(_hc(self._hdr_text()))
        c.setFont(self._hdr_font(bold=True), ts + 2)
        c.drawCentredString(w / 2, h - bar_h + (bar_h - ts) / 2, title)

    # ─── Shared header content helper ──────────────────────────────

    def _header_content(self, c, w, h, bar_h, hf, text_color=None, x_start=30, y_offset=0):
        """Draw logo + title + subtitle (shared across bar-based styles)."""
        tc = text_color or self._hdr_text()
        ts = self.theme.typography.header_title_size
        sts = self.theme.typography.header_subtitle_size
        x = x_start

        # Logo
        if hf.logo:
            max_lh = min(hf.logo_max_height, bar_h - 16)
            dw, dh = _draw_image(c, hf.logo, x,
                                 h - bar_h + (bar_h - max_lh) / 2 - y_offset,
                                 hf.logo_max_height * 4, max_lh)
            if dw:
                x += dw + 14

        # Title (flush right in right-to-left documents)
        rtl = self._language() == "ar"
        draw = (lambda yy, txt: c.drawRightString(w - x_start, yy, txt)) if rtl else \
            (lambda yy, txt: c.drawString(x, yy, txt))
        title = hf.title or self.document.meta.title or ""
        if title:
            c.setFillColor(_hc(tc))
            c.setFont(self._hdr_font(bold=True), ts)
            if hf.subtitle:
                draw(h - bar_h + bar_h * 0.55 - y_offset, title)
            else:
                draw(h - bar_h + (bar_h - ts) / 2 - y_offset, title)

        # Subtitle
        if hf.subtitle:
            c.setFont(self._body_font(italic=True), sts)
            c.setFillColor(_hc(tc))
            draw(h - bar_h + bar_h * 0.22 - y_offset, hf.subtitle)

    # ═══════════════════════ FOOTER DRAWING ═══════════════════════

    def _draw_footer(self, canvas, doc):
        hf = self.theme.header_footer
        if not hf.enabled:
            return
        if hf.skip_first_page_footer and doc.page == 1:
            return

        style = hf.footer_style.lower().replace("-", "_").replace(" ", "_")
        if style == "none":
            return
        w, h = self._page_wh(canvas)
        bar_h = hf.footer_height
        canvas.saveState()

        method = getattr(self, f"_footer_{style}", None)
        if method:
            method(canvas, w, h, bar_h, hf, doc)
        else:
            self._footer_bar(canvas, w, h, bar_h, hf, doc)

        canvas.restoreState()

    # ─── Footer Styles ─────────────────────────────────────────────

    def _footer_bar(self, c, w, h, bar_h, hf, doc):
        """Full-width solid colour bar."""
        c.setFillColor(_hc(self._ftr_bg()))
        c.rect(0, 0, w, bar_h, fill=1, stroke=0)
        self._footer_content(c, w, bar_h, hf, doc)

    def _footer_gradient(self, c, w, h, bar_h, hf, doc):
        """Gradient bar."""
        end = hf.footer_bg_gradient_end or self.theme.colors.secondary
        _draw_gradient(c, 0, 0, w, bar_h, self._ftr_bg(), end, hf.footer_bg_gradient_direction)
        self._footer_content(c, w, bar_h, hf, doc)

    def _footer_line(self, c, w, h, bar_h, hf, doc):
        """Thin line above + text below."""
        lc = hf.footer_border_color or hf.footer_accent_color or self.theme.colors.border
        c.setStrokeColor(_hc(lc))
        c.setLineWidth(hf.footer_border_width)
        c.line(30, bar_h, w - 30, bar_h)
        self._footer_content(c, w, bar_h, hf, doc, text_color=self.theme.colors.text_secondary)

    def _footer_minimal(self, c, w, h, bar_h, hf, doc):
        """No background — just text."""
        self._footer_content(c, w, bar_h, hf, doc, text_color=self.theme.colors.text_muted)

    def _footer_centered(self, c, w, h, bar_h, hf, doc):
        """All text centred."""
        tc = self.theme.colors.text_muted
        fs = self.theme.typography.footer_text_size
        c.setFillColor(_hc(tc))
        c.setFont(self._body_font(), fs)
        parts = []
        if hf.copyright_text:
            parts.append(hf.copyright_text)
        if hf.show_page_number:
            parts.append(self._fmt_page(hf, doc))
        c.drawCentredString(w / 2, 16, "   |   ".join(parts))

    def _footer_three_column(self, c, w, h, bar_h, hf, doc):
        """Left | Centre | Right columns — no background."""
        tc = self.theme.colors.text_secondary
        fs = self.theme.typography.footer_text_size
        c.setFillColor(_hc(tc))
        c.setFont(self._body_font(), fs)
        # Left
        left = self._resolve_slot(hf.footer_left, hf, doc) or ""
        if left or hf.show_date:
            txt = left or datetime.now().strftime(hf.date_format)
            c.drawString(30, 16, txt)
        # Centre
        centre = self._resolve_slot(hf.footer_center, hf, doc) or hf.copyright_text or ""
        if centre:
            c.drawCentredString(w / 2, 16, centre)
        # Right
        right = self._resolve_slot(hf.footer_right, hf, doc) or ""
        if right:
            c.drawRightString(w - 30, 16, right)
        elif hf.show_page_number:
            c.drawRightString(w - 30, 16, self._fmt_page(hf, doc))

    def _footer_two_column(self, c, w, h, bar_h, hf, doc):
        """Left + Right only."""
        tc = self.theme.colors.text_secondary
        fs = self.theme.typography.footer_text_size
        c.setFillColor(_hc(tc))
        c.setFont(self._body_font(), fs)
        left = hf.footer_text or hf.copyright_text or ""
        c.drawString(30, 16, left)
        if hf.show_page_number:
            c.drawRightString(w - 30, 16, self._fmt_page(hf, doc))

    def _footer_page_only(self, c, w, h, bar_h, hf, doc):
        """Just page number centred."""
        c.setFillColor(_hc(self.theme.colors.text_muted))
        c.setFont(self._body_font(), self.theme.typography.footer_text_size)
        c.drawCentredString(w / 2, 16, self._fmt_page(hf, doc))

    def _footer_logo_right(self, c, w, h, bar_h, hf, doc):
        """Logo right-aligned (like Averroes style)."""
        self._footer_content(c, w, bar_h, hf, doc, text_color=self.theme.colors.text_secondary)
        logo = hf.footer_logo or hf.logo
        if logo:
            _draw_image(c, logo, w - 30 - hf.footer_logo_max_height * 5, 8,
                        hf.footer_logo_max_height * 5, hf.footer_logo_max_height, align="right")

    def _footer_logo_left(self, c, w, h, bar_h, hf, doc):
        """Logo left-aligned."""
        logo = hf.footer_logo or hf.logo
        if logo:
            _draw_image(c, logo, 30, 8,
                        hf.footer_logo_max_height * 5, hf.footer_logo_max_height)
        self._footer_content(c, w, bar_h, hf, doc, text_color=self.theme.colors.text_secondary)

    def _footer_copyright_line(self, c, w, h, bar_h, hf, doc):
        """Thin line + copyright centred + page right."""
        lc = hf.footer_border_color or self.theme.colors.border
        c.setStrokeColor(_hc(lc))
        c.setLineWidth(0.5)
        c.line(30, bar_h - 4, w - 30, bar_h - 4)
        tc = self.theme.colors.text_muted
        fs = self.theme.typography.footer_text_size
        c.setFillColor(_hc(tc))
        c.setFont(self._body_font(), fs)
        if hf.copyright_text:
            c.drawCentredString(w / 2, 12, hf.copyright_text)
        if hf.show_page_number:
            c.drawRightString(w - 30, 12, self._fmt_page(hf, doc))

    def _footer_academic(self, c, w, h, bar_h, hf, doc):
        """Centred italic text + page number — classic academic."""
        tc = self.theme.colors.text_secondary
        fs = self.theme.typography.footer_text_size
        c.setFillColor(_hc(tc))
        c.setFont(self._body_font(italic=True), fs)
        text = hf.footer_text or hf.title or ""
        c.drawString(30, 16, text)
        if hf.show_page_number:
            c.drawRightString(w - 30, 16, str(doc.page))

    def _footer_sidebar(self, c, w, h, bar_h, hf, doc):
        """Sidebar footer (same as header sidebar — drawn as full-page strip)."""
        # The sidebar is drawn in header; footer just adds text
        self._footer_content(c, w, bar_h, hf, doc, text_color=self.theme.colors.text_secondary)

    # ─── Shared footer content helper ──────────────────────────────

    def _footer_content(self, c, w, bar_h, hf, doc, text_color=None):
        """Draw 3-row footer: copyright | company+address | contacts + page/date."""
        tc = text_color or self._ftr_text()
        fs = self.theme.typography.footer_text_size
        ds = self.theme.typography.footer_detail_size
        center_x = w / 2

        c.setFillColor(_hc(tc))

        # Row 1: copyright / footer_text
        row1_y = bar_h - 12
        line1 = hf.footer_text or hf.copyright_text or ""
        if line1:
            c.setFont(self._body_font(), fs)
            c.drawCentredString(center_x, row1_y, line1)

        # Row 2: company + address
        row2_y = row1_y - 11
        parts2 = [p for p in [hf.company_name, hf.address] if p]
        if parts2:
            c.setFont(self._body_font(), ds)
            c.drawCentredString(center_x, row2_y, "  •  ".join(parts2))

        # Row 3: website, email, phone
        row3_y = row2_y - 10
        parts3 = [p for p in [hf.website, hf.email, hf.phone] if p]
        if parts3:
            c.setFont(self._body_font(), ds)
            c.drawCentredString(center_x, row3_y, "    ".join(parts3))

        # Page number (right)
        if hf.show_page_number:
            c.setFont(self._body_font(), fs)
            c.drawRightString(w - 30, row1_y, self._fmt_page(hf, doc))

        # Date (left)
        if hf.show_date:
            c.setFont(self._body_font(), fs)
            c.drawString(30, row1_y, datetime.now().strftime(hf.date_format))

    # ─── Helpers ──────────────────────────────────────────────────

    def _fmt_page(self, hf, doc):
        fmt = hf.page_number_format
        counter = self._page_counter
        # During the first multiBuild pass the total is unknown; that pass is
        # always re-run (see _PageCounter), so a provisional value never ships.
        total = counter.total if counter is not None and counter.total else doc.page
        return fmt.replace("{n}", str(doc.page)).replace("{total}", str(total))

    def _resolve_slot(self, slot, hf, doc):
        """Resolve a slot value: 'page', 'date', 'text:Foo', etc."""
        if not slot:
            return None
        if slot == "page":
            return self._fmt_page(hf, doc)
        if slot == "date":
            return datetime.now().strftime(hf.date_format)
        if slot.startswith("text:"):
            return slot[5:]
        if slot == "title":
            return hf.title or self.document.meta.title or ""
        if slot == "copyright":
            return hf.copyright_text or ""
        return slot

    # ─── Combined Page Handler ──────────────────────────────────────

    def _on_page(self, canvas, doc):
        canvas._dpb_bidi = True          # header/footer strings get Arabic shaping
        try:
            self._draw_header(canvas, doc)
            self._draw_footer(canvas, doc)
        finally:
            canvas._dpb_bidi = False
        # Draw sidebar for sidebar style (full page height)
        hf = self.theme.header_footer
        if hf.header_style == "sidebar" or hf.footer_style == "sidebar":
            self._draw_sidebar_strip(canvas)

    def _language(self) -> str:
        meta = self.document.meta
        if meta.rtl or getattr(meta, "direction", None) == "rtl":
            return "ar" if not (meta.language or "").startswith(("he", "fa", "ur")) else meta.language
        return (meta.language or "en").split("-")[0]

    def _page_wh(self, canvas):
        """Actual size of the page being drawn (landscape pages differ)."""
        ps = getattr(canvas, "_pagesize", None)
        return tuple(ps) if ps else self._get_pagesize()

    def _draw_sidebar_strip(self, canvas):
        """Vertical strip for sidebar style (drawn on every page)."""
        hf = self.theme.header_footer
        w, h = self._page_wh(canvas)
        sw = hf.sidebar_width
        sc = hf.sidebar_color or self.theme.colors.accent
        canvas.saveState()
        if hf.sidebar_gradient_end:
            if hf.sidebar_position == "right":
                _draw_gradient(canvas, w - sw, 0, sw, h, sc, hf.sidebar_gradient_end, "vertical")
            else:
                _draw_gradient(canvas, 0, 0, sw, h, sc, hf.sidebar_gradient_end, "vertical")
        else:
            canvas.setFillColor(_hc(sc))
            if hf.sidebar_position == "right":
                canvas.rect(w - sw, 0, sw, h, fill=1, stroke=0)
            else:
                canvas.rect(0, 0, sw, h, fill=1, stroke=0)
        canvas.restoreState()

    # ═══════════════════════ RENDER ═══════════════════════

    def render(self, output) -> None:
        register_fonts()
        theme = self.theme
        sp = theme.spacing
        hf = theme.header_footer
        pagesize = self._get_pagesize()
        w, h = pagesize

        # Compute text frame area based on style
        top_m = sp.page_margin_top
        bot_m = sp.page_margin_bottom
        if hf.enabled:
            # Styles that draw a bar need margin clearance
            bar_styles = {"bar", "gradient", "banner", "split", "logo_left",
                          "logo_right", "modern"}
            if hf.header_style in bar_styles:
                top_m = max(top_m, hf.height + 16)
            else:
                top_m = max(top_m, hf.height + 4)

            fbar_styles = {"bar", "gradient"}
            if hf.footer_style in fbar_styles:
                bot_m = max(bot_m, hf.footer_height + 12)
            else:
                bot_m = max(bot_m, 40)

        # Sidebar offset
        left_m = sp.page_margin_left
        right_m = sp.page_margin_right
        if hf.header_style == "sidebar" or hf.footer_style == "sidebar":
            if hf.sidebar_position == "left":
                left_m += hf.sidebar_width + 4
            else:
                right_m += hf.sidebar_width + 4

        frame_width = w - left_m - right_m

        from ..intelligence.geometry import GeoFrame
        frame = GeoFrame(
            left_m, bot_m,
            frame_width,
            h - top_m - bot_m,
            id='main'
        )
        frame.geometry = self.geometry

        template = PageTemplate(id='AllPages', frames=[frame], onPage=self._on_page,
                                pagesize=pagesize)
        # Landscape pages for content the planner marks as too wide for portrait
        lw, lh = (h, w) if h > w else (w, h)
        land_frame = GeoFrame(left_m, bot_m, lw - left_m - right_m, lh - top_m - bot_m, id='land')
        land_frame.geometry = self.geometry
        land_frame.landscape = True
        land_template = PageTemplate(id='Landscape', frames=[land_frame], onPage=self._on_page,
                                     pagesize=(lw, lh))
        land_width = lw - left_m - right_m

        meta = self.document.meta
        limits = self.policy.limits
        _policy.check_limit("Block count", len(self.document.blocks), limits.max_blocks)

        # Fail closed: refuse *before* rendering if encryption cannot be honoured
        needs_encrypt = bool(meta.encrypt)
        if needs_encrypt:
            if not (meta.owner_password or meta.user_password):
                raise EncryptionError("encrypt=True requires owner_password and/or user_password")
            try:
                import pikepdf  # noqa: F401
            except ImportError as e:
                raise EncryptionError(
                    "PDF encryption was requested but pikepdf is not installed; "
                    "refusing to write an unencrypted file. Install with: "
                    'pip install "dynamic-pdf-builder[pdf]"') from e

        # Always render to memory: nothing is written unless rendering succeeds
        render_target = BytesIO()

        doc_template = _EngineDocTemplate(
            render_target, pagesize=pagesize,
            title=meta.title or "",
            author=meta.author or "",
            subject=meta.subject or "",
            creator=meta.creator_tool,
            keywords=meta.keywords if meta.keywords else [],
        )
        if hasattr(doc_template, 'lang'):
            doc_template.lang = meta.language
        doc_template.addPageTemplates([template, land_template])

        # Create thread-safe render context
        ctx = RenderContext(
            available_width=frame_width,
            section_numbering=meta.section_numbering,
            available_height=h - top_m - bot_m,
            language=self._language(),
        )
        ctx.cache = self.cache
        self.diagnostics.language = ctx.language
        doc_template._dpb_geometry = self.geometry

        token = _policy.activate(self.diagnostics)
        try:
            self._page_counter = _PageCounter(doc_template)
            flowables = [self._page_counter]
            land = _landscape_indices(self.document.blocks) if lw > w else set()
            in_land = False
            from reportlab.platypus import NextPageTemplate
            from reportlab.platypus.flowables import PageBreakIfNotEmpty
            for i, block in enumerate(self.document.blocks):
                if (i in land) != in_land:
                    in_land = i in land
                    flowables += [NextPageTemplate('Landscape' if in_land else 'AllPages'),
                                  PageBreakIfNotEmpty()]
                    ctx.available_width = land_width if in_land else frame_width
                self.diagnostics.block_index = i
                self.diagnostics.block_type = getattr(block, "type", None)
                if getattr(block, "type", None) == "table":
                    width = max([len(block.headers or [])] + [len(r) for r in block.rows] + [1])
                    _policy.check_limit("Table cells", (len(block.rows) + 1) * width,
                                        limits.max_table_cells)
                result = create_flowables(block, theme, ctx)
                if result:
                    if self.geometry is not None:
                        from ..intelligence.geometry import tag
                        tag(result, i, _role_for(block))
                    flowables.extend(result)
            self.diagnostics.block_index = None
            self.diagnostics.block_type = None

            if len(flowables) == 1:
                flowables.append(Spacer(1, 1))

            doc_template.multiBuild(flowables, canvasmaker=_BidiCanvas)
            self.page_count = self._page_counter.total
            # how full the final page is (0..1) — used by the page-fit step
            fr = getattr(doc_template, "frame", None)
            try:
                self.last_page_fill = round(1 - (fr._y - fr._y1) / fr._height, 3) if fr else None
            except Exception:
                self.last_page_fill = None
        finally:
            _policy.deactivate(token)

        pdf_bytes = render_target.getvalue()
        if needs_encrypt:
            pdf_bytes = self._encrypt_bytes(pdf_bytes, meta)
        _write_output(output, pdf_bytes)

    def _encrypt_bytes(self, pdf_bytes: bytes, meta) -> bytes:
        """Encrypt with pikepdf (AES-256). Raises EncryptionError on any failure."""
        try:
            import pikepdf
            permissions = pikepdf.Permissions(
                extract=False, modify_annotation=False,
                modify_form=False, modify_other=False,
            )
            out = BytesIO()
            with pikepdf.open(BytesIO(pdf_bytes)) as pdf:
                pdf.save(
                    out,
                    encryption=pikepdf.Encryption(
                        owner=meta.owner_password or meta.user_password or "",
                        user=meta.user_password or "",
                        R=6,  # AES-256
                        allow=permissions,
                    ),
                )
            return out.getvalue()
        except Exception as e:
            raise EncryptionError(f"PDF encryption failed: {e}") from e


def _write_output(output, data: bytes) -> None:
    if hasattr(output, 'write'):
        output.write(data)
    else:
        with open(output, 'wb') as f:
            f.write(data)
