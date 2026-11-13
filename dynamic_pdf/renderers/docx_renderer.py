"""
Editable DOCX renderer (python-docx) for the canonical SemanticDocument.

Principles
----------
* Same semantic input and design tokens as the PDF renderer.
* Native, editable Word structures wherever Word has them: named styles,
  real headings (navigation pane, TOC), multi-level list numbering that
  restarts per list, real tables with repeating header rows, hyperlinks,
  bookmarks, headers/footers with PAGE/NUMPAGES fields, a TOC field,
  sections, bidi paragraphs/runs and complex-script fonts for Arabic.
* Images only where Word has no native analogue (charts, diagrams, math,
  QR codes, shapes); every image carries alt text and keeps its caption.
* Errors follow the same RenderPolicy as PDF (strict → typed exception,
  permissive → visible marker + diagnostic). Nothing is silently dropped.
"""
from __future__ import annotations

import io
import re
from typing import List, Optional

from docx import Document as new_docx
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_COLOR_INDEX
from docx.oxml.ns import qn
from docx.shared import Emu, Pt
from docx.table import _Cell

from .. import policy as _policy
from ..assets import load_image
from ..core.inline import parse_inline, plain_text
from ..core.normalize import SemanticDocument, coerce_child, is_rtl_text
from ..design.archetypes import ink as _ink, mix as _mix
from ..design.tokens import compile_tokens
from ..media import (LOW_RESOLUTION_DPI, check_resolution, fit_image, flow_box, ingest, normal_mode,
                     physical_side)
from ..schema.enums import Orientation, PageSize
from ..schema.theme import Theme
from ..utils.errors import BlockRenderError, DynamicPDFError
from . import docx_fields as F
from . import docx_media as M
from .docx_archetypes import ArchetypeDocx
from .docx_compositions import CompositionDocx
from ..fonts.manager import set_arabic_face
from .docx_fonts import embed_fonts
from .docx_styles import configure_styles, rgb, word_font

_PAGE_SIZES_PT = {PageSize.A4: (595.28, 841.89), PageSize.LETTER: (612, 792),
                  PageSize.LEGAL: (612, 1008)}
_VARIANT_COLORS = {"info": "info", "warning": "warning", "error": "error",
                   "success": "success", "tip": "tip", "danger": "error", "note": "info"}
WRAPS_FLOAT = ("paragraph", "rich_text", "bullet_list", "numbered_list", "checklist")   # may sit beside a float
_NUMERIC = re.compile(r"^[\s$€£¥%+\-−(),.\d٠-٩]+$")


class DocxRenderer(ArchetypeDocx, CompositionDocx):
    def __init__(self, sem: SemanticDocument, theme: Theme, collector=None):
        from ..utils.reproducible import render_time
        self.sem = sem
        self.theme = theme
        self.render_time = render_time()       # SOURCE_DATE_EPOCH when set, as for the PDF
        self.tokens = compile_tokens(theme)
        self.col = collector or _policy.current()
        self.rtl_doc = sem.direction == "rtl"
        self.shape_seq = 4000
        self.section_name = None
        self.band_writer = None
        self.page_sys = None
        self.doc = new_docx()
        self.bm = F.BookmarkCounter()
        self.lists = None
        self.heading_counters = [0] * 6
        self.figure_no = 0
        self.table_no = 0
        self.content_width_pt = 0.0
        self.headings_rendered: List[str] = []

    # ═════════════════════════ entry ═════════════════════════

    def render(self) -> bytes:
        doc = self.doc
        set_arabic_face(self.theme.typography.arabic_family)
        configure_styles(doc, self.tokens, self.theme, self.rtl_doc)
        self.lists = F.ListNumbering(doc, indent_twips=int(self.tokens.list_indent * 20) or 360,
                                     bullet_font=word_font(self.tokens.fonts.body))
        self._setup_section()
        self._core_properties()
        self._page_parts(doc.sections[0], None)
        from ..layout.engine import _landscape_indices
        land = _landscape_indices(self.sem.blocks)
        in_land = False
        flow = None
        for i, block in enumerate(self.sem.blocks):
            if (i in land) != in_land:
                in_land = i in land
                self._switch_orientation(landscape=in_land)
            hints = getattr(block, "hints", None) or {}
            if hints.get("flow_run") != flow:
                flow = hints.get("flow_run")
                self._switch_columns(hints.get("flow_columns", 1) if flow is not None else 1,
                                     hints.get("flow_gap", 18.0))
            self.col.block_index = i
            self.col.block_type = getattr(block, "type", None)
            self._block_safe(doc, block)
        self.col.block_index = self.col.block_type = None
        if flow is not None:
            self._switch_columns(1, 18.0)
            # The closing section still needs a paragraph. A full-height one spills
            # onto a blank last page when the balanced columns fill the page.
            tail = self.doc.add_paragraph()
            tail.paragraph_format.space_before = tail.paragraph_format.space_after = Pt(0)
            tail.paragraph_format.line_spacing = Pt(1)
            tail.add_run().font.size = Pt(1)
        if any(b.type == "table_of_contents" for b in self.sem.blocks):
            F.enable_update_fields_on_open(doc)
        F.keep_manual_breaks_unstretched(doc)
        F.mirror_bidi_justification(doc.element.body)
        for sec in doc.sections:
            for part in (sec.header, sec.footer, sec.first_page_header, sec.first_page_footer,
                         sec.even_page_header, sec.even_page_footer):
                if not part.is_linked_to_previous:
                    F.mirror_bidi_justification(part._element)
        buf = io.BytesIO()
        doc.save(buf)
        fonts = self.tokens.fonts
        return embed_fonts(buf.getvalue(), (fonts.heading, fonts.body, fonts.arabic))

    def _label(self, key):
        from ..i18n import label
        return label(key, "ar" if self.rtl_doc else self.sem.language)

    def _clear_float(self, c) -> None:
        """Word sets whatever follows a floating table beside it. A clearing break in a
        paragraph of its own moves the next block below the float and keeps the break out
        of a heading's text and the navigation pane."""
        from docx.oxml import OxmlElement
        self._float_open = False
        br = OxmlElement("w:br")
        br.set(qn("w:type"), "textWrapping")
        br.set(qn("w:clear"), "all")
        M.tiny_paragraph(c).add_run()._r.append(br)

    def _block_safe(self, container, block):
        if getattr(self, "_float_open", False) and getattr(block, "type", "") not in WRAPS_FLOAT:
            self._clear_float(container)
        try:
            self._block(container, block)
        except Exception as e:
            btype = getattr(block, "type", type(block).__name__)
            err = e if isinstance(e, BlockRenderError) else BlockRenderError(
                btype, f"{type(e).__name__}: {e}", e)
            self.col.fail("block_render_failed", str(err), err)
            p = self._para(container)
            r = p.add_run(f"[Block Error ({btype}): {type(e).__name__}: {e}]")
            r.font.color.rgb = rgb(self.tokens.colors["error"])
            r.font.size = Pt(8)

    # ═════════════════════════ document setup ═════════════════════════

    def _setup_section(self):
        meta = self.sem.meta
        sec = self.doc.sections[0]
        w, h = _PAGE_SIZES_PT.get(meta.page_size, _PAGE_SIZES_PT[PageSize.A4])
        if meta.orientation == Orientation.LANDSCAPE:
            w, h = h, w
            sec.orientation = WD_ORIENT.LANDSCAPE
        sec.page_width, sec.page_height = Pt(w), Pt(h)
        m = self.tokens.margins
        sec.top_margin, sec.bottom_margin = Pt(m["top"]), Pt(m["bottom"])
        sec.left_margin, sec.right_margin = Pt(m["left"]), Pt(m["right"])
        sec.header_distance = Pt(max(18, m["top"] * 0.45))
        sec.footer_distance = Pt(max(18, m["bottom"] * 0.45))
        self.content_width_pt = w - m["left"] - m["right"]
        system = meta.page_system
        if system is not None:
            from ..schema.page_system import settled
            system = self.page_sys = settled(system, self.sem.blocks)
            from ..fonts import register_fonts
            from ..layout.page_envelope import band_maker, reserve_bands
            register_fonts()
            maker, sample = band_maker(self.sem.to_document(), self.theme, system, self.rtl_doc,
                                       self.col.policy.assets, self.col)
            top, bottom = reserve_bands(maker, self.content_width_pt, sample, self.col)
            sec.top_margin, sec.bottom_margin = Pt(max(m["top"], top)), Pt(max(m["bottom"], bottom))
            sec.header_distance = sec.footer_distance = Pt(system.edge_distance)
            self.band_writer = M.BandWriter(self, maker, sample)
        if self.rtl_doc:
            sectPr = sec._sectPr
            el = F._get_or_add(sectPr, "w:bidi")
            el.set(F.qn("w:val"), "1")

    def _core_properties(self):
        meta = self.sem.meta
        cp = self.doc.core_properties
        cp.title = meta.title or ""
        cp.author = meta.author or ""
        cp.subject = meta.subject or ""
        cp.keywords = ", ".join(meta.keywords or [])
        cp.comments = meta.description or ""
        cp.language = meta.language or "en"
        cp.category = meta.document_type or ""
        # python-docx's template says 2013-12-23; a document is created when it is rendered
        cp.created = cp.modified = self.render_time.replace(tzinfo=None)
        cp.last_modified_by = meta.creator_tool or ""

    def next_shape(self) -> int:
        self.shape_seq += 1
        return self.shape_seq

    def band_heading_level(self, field: str) -> int:
        """Which heading a running title follows. Word's field reports an error on a
        page before the first heading of its style, so ``{section}`` follows level 2
        only in documents that have one."""
        if field == "section" and any(
                b.type == "heading" and b.level == 2 for b in self.sem.blocks):
            return 2
        return 1

    def _layers_for(self, name):
        """Document-level page layers for a section, with their assets."""
        out = []
        for b in self.sem.blocks:
            if b.type != "page_media" or b.scope == "once" or b.scope == "cover":
                continue
            if b.scope == "sections" and name not in b.sections:
                continue
            try:
                out.append((b, ingest(b.src, self.col.policy.assets)))
            except DynamicPDFError as e:
                self.col.fail("asset_failed", f"Page image: {e}", e)
        return out

    def _page_parts(self, sec, name):
        """Header and footer parts of a Word section: bands or the theme's text, and
        the page layers, which Word repeats by holding them in the header."""
        first = name is None
        layers = self._layers_for(name)
        geo = M.page_geometry(self, sec)
        system = self.page_sys
        cover = next((b for b in self.sem.blocks[:1] if b.type == "cover_page"
                      and (b.background_image or b.background_color or b.layout)), None)
        if first and cover is not None:
            sec.different_first_page_header_footer = True
        if system is None:
            if first or layers:
                self._header_footer(sec)
                if layers:
                    host = sec.header
                    host.is_linked_to_previous = False
                    for b, asset in layers:
                        M.add_layer(self, host.paragraphs[0], b, geo, asset)
            return
        over = system.sections.get(name) if name else None
        head = (over.header if over else None) or system.header
        foot = (over.footer if over else None) or system.footer
        self._band_or_blank(sec.header, head, geo, True, layers)
        self._band_or_blank(sec.footer, foot, geo, False)
        if system.even_header or system.even_footer:
            self.doc.settings.odd_and_even_pages_header_footer = True
            self._band_or_blank(sec.even_page_header, (over.header if over else None)
                                or system.even_header or head, geo, True, layers)
            self._band_or_blank(sec.even_page_footer, (over.footer if over else None)
                                or system.even_footer or foot, geo, False)
        if first and system.first_page != "same":
            sec.different_first_page_header_footer = True
            custom = system.first_page == "custom"
            self._band_or_blank(sec.first_page_header, system.first_header if custom else None,
                                geo, True, layers)
            self._band_or_blank(sec.first_page_footer, system.first_footer if custom else None, geo, False)

    def _band_or_blank(self, part, band, geo, is_header, layers=()):
        if band is not None:
            self.band_writer.write(part, band, geo, is_header, layers)
            return
        part.is_linked_to_previous = False
        for b, asset in layers:
            M.add_layer(self, part.paragraphs[0], b, geo, asset)

    def _header_footer(self, sec=None):
        hf = self.theme.header_footer
        if not hf.enabled:
            return
        sec = sec or self.doc.sections[0]
        if hf.skip_first_page_header or hf.skip_first_page_footer:
            sec.different_first_page_header_footer = True
        muted = self.tokens.colors["text_muted"]
        size = Pt(max(7.5, self.theme.typography.footer_text_size + 1))

        def style_run(r):
            r.font.size = size
            r.font.color.rgb = rgb(muted)

        if hf.header_style != "none":
            hp = sec.header.paragraphs[0]
            title = hf.title or self.sem.meta.title or ""
            if hf.logo:
                try:
                    buf, (iw, ih) = load_image(hf.logo, self.col.policy.assets)
                    h_pt = min(hf.logo_max_height, 28)
                    hp.add_run().add_picture(buf, height=Pt(h_pt))
                    hp.add_run("   ")
                except DynamicPDFError as e:
                    self.col.fail("asset_failed", f"Header logo: {e}", e)
            if title:
                self._runs(hp, title, base=style_run)
            hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT if self.rtl_doc else WD_ALIGN_PARAGRAPH.LEFT
            if self.rtl_doc:
                F.set_paragraph_bidi(hp)
            F.set_paragraph_border(hp, "bottom", self.tokens.colors["border"], 4, 4)
            if self.sem.blocks and any(b.type == "watermark" for b in self.sem.blocks):
                pass  # added by the watermark block itself

        fp = sec.footer.paragraphs[0]
        fp.alignment = WD_ALIGN_PARAGRAPH.CENTER if hf.footer_style in (
            "centered", "page_only", "academic") else (
            WD_ALIGN_PARAGRAPH.LEFT if self.rtl_doc else WD_ALIGN_PARAGRAPH.RIGHT)
        left_text = hf.footer_text or hf.copyright_text or hf.company_name
        if left_text and hf.footer_style not in ("page_only",):
            self._runs(fp, left_text, base=style_run)
            fp.add_run("    ")
        if hf.show_page_number:
            fmt = hf.page_number_format or "Page {n}"
            for part in re.split(r"(\{n\}|\{total\})", fmt):
                if part == "{n}":
                    F.add_field(fp, "PAGE", "1", style_run)
                elif part == "{total}":
                    F.add_field(fp, "NUMPAGES", "1", style_run)
                elif part:
                    style_run(fp.add_run(part))

    # ═════════════════════════ primitives ═════════════════════════

    def _para(self, container, style: Optional[str] = None, text_hint: str = ""):
        if isinstance(container, _Cell) and not getattr(container, "_dpb_used", False):
            container._dpb_used = True
            p = container.paragraphs[0]
            if style:
                p.style = self.doc.styles[style]
        else:
            p = container.add_paragraph(style=style)
        rtl = self.rtl_doc if not text_hint else (is_rtl_text(text_hint) or (
            self.rtl_doc and not re.search(r"[A-Za-z]", text_hint)))
        if rtl:
            F.set_paragraph_bidi(p)
            if p.alignment is None and style != "Body Text":
                p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        return p

    def _runs(self, paragraph, md_text: str, base=None, bold=None, italic=None,
              size: Optional[float] = None, color: Optional[str] = None):
        """Add inline Markdown as real Word runs (links, emphasis, code, sup/sub…)."""
        arabic = self.tokens.fonts.arabic
        mono = word_font(self.tokens.fonts.mono)
        for tr in parse_inline(md_text or ""):
            if tr.line_break:
                paragraph.add_run().add_break(WD_BREAK.LINE)
                continue

            def fmt(run, tr=tr):
                if base:
                    base(run)
                f = run.font
                if bold is not None:
                    f.bold = bold
                if italic is not None:
                    f.italic = italic
                if tr.bold:
                    f.bold = True
                if tr.italic:
                    f.italic = True
                if tr.strike:
                    f.strike = True
                if tr.underline:
                    f.underline = True
                if tr.superscript:
                    f.superscript = True
                if tr.subscript:
                    f.subscript = True
                if tr.highlight:
                    f.highlight_color = WD_COLOR_INDEX.YELLOW
                if size:
                    f.size = Pt(size)
                if color:
                    f.color.rgb = rgb(color)
                rtl = is_rtl_text(tr.text)
                if tr.code:
                    F.set_run_fonts(run, mono, mono)
                    F.set_run_shading(run, "EEF0F3")
                else:
                    F.set_run_fonts(run, None, arabic, rtl=rtl, bidi_lang="ar-SA" if rtl else None)
                    if F.has_complex_script(tr.text):
                        F.set_complex_script_format(run, size, bool(f.bold))

            if tr.link:
                F.add_hyperlink(paragraph, tr.link, tr.text, fmt)
            else:
                fmt(paragraph.add_run(tr.text))
        return paragraph

    def _picture(self, container, data: bytes, alt: str, max_width_pt: Optional[float] = None,
                 width_pt: Optional[float] = None, align: str = "center"):
        from PIL import Image as PILImage
        with PILImage.open(io.BytesIO(data)) as im:
            wpx, hpx = im.size
            dpi = im.info.get("dpi", (96, 96))[0] or 96
        natural_w = wpx * 72.0 / dpi
        max_w = max_width_pt or self.content_width_pt
        target = min(width_pt or natural_w, max_w)
        # keep images from exceeding ~70% of the page height
        max_h = (self.doc.sections[0].page_height.pt - self.tokens.margins["top"]
                 - self.tokens.margins["bottom"]) * 0.7
        if target * hpx / wpx > max_h:
            target = max_h * wpx / hpx
        p = self._para(container)
        p.alignment = {"left": WD_ALIGN_PARAGRAPH.LEFT, "right": WD_ALIGN_PARAGRAPH.RIGHT}.get(
            align, WD_ALIGN_PARAGRAPH.CENTER)
        shape = p.add_run().add_picture(io.BytesIO(data), width=Pt(target))
        F.set_alt_text(shape, alt or "image")
        p.paragraph_format.keep_with_next = True
        return p

    def _caption(self, container, label: str, text: Optional[str]):
        full = f"{label}: {text}" if text and label else (text or label)
        if not full:
            return
        p = self._para(container, "Caption", full)
        if not (self.rtl_doc or is_rtl_text(full)):
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        self._runs(p, full)

    def _boxed(self, container, fill: str, bar: Optional[str] = None):
        """A single-cell table used as a framed container (callouts, abstracts)."""
        t = container.add_table(rows=1, cols=1)
        F.set_table_width_pct(t, 100)
        F.set_table_borders(t, size=0)
        F.set_table_cell_margins(t, 100, 100, 160, 160)
        cell = t.rows[0].cells[0]
        F.set_cell_shading(cell, fill)
        if bar:
            side = "right" if self.rtl_doc else "left"
            F.set_cell_borders(cell, **{side: ("single", 24, bar)})
        if self.rtl_doc:
            F.set_table_bidi(t)
        self._spacer_after(container)
        return cell

    def _spacer_after(self, container, pts: Optional[float] = None):
        if isinstance(container, _Cell):
            return
        p = container.add_paragraph()
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.line_spacing = Pt(pts or self.tokens.block_gap * 0.6)

    # ═════════════════════════ dispatcher ═════════════════════════

    def _block(self, c, b):
        t = b.type
        handler = getattr(self, f"_b_{t}", None)
        if handler is None:
            raise BlockRenderError(t, "no DOCX renderer for this block type")
        handler(c, b)

    # ─── text ───

    def _b_heading(self, c, b):
        lvl = max(1, min(6, b.level))
        text = b.text
        if self.sem.meta.section_numbering or b.numbered:
            idx = lvl - 1
            self.heading_counters[idx] += 1
            for i in range(idx + 1, 6):
                self.heading_counters[i] = 0
            num = ".".join(str(n) for n in self.heading_counters[:idx + 1] if n > 0)
            text = f"{num}  {text}"
        p = self._para(c, f"Heading {lvl}", b.text)
        hints = b.hints or {}
        if hints.get("break_before") or hints.get("drop"):
            p.paragraph_format.page_break_before = True
        if hints.get("opener") or hints.get("scale") or hints.get("drop"):
            self._art_heading(p, text, b, lvl, hints)
        else:
            self._runs(p, text, color=b.color)
        if b.id:
            F.add_bookmark(p, F.bookmark_name(b.id), self.bm)
        self.headings_rendered.append(plain_text(text))

    def _art_heading(self, p, text, b, lvl, hints):
        """A real Word heading dressed as the art direction asked: it stays in the outline
        and the text stays editable."""
        size = self.tokens.heading_sizes[lvl - 1] * float(hints.get("scale", 1.0))
        dark = _ink(self.theme) if self.theme is not None else self.tokens.colors["primary"]
        kind = hints.get("opener")
        color = b.color
        if kind == "slab":
            p.style = self._slab_style(lvl, hints.get("fill") or dark)
            F.set_paragraph_shading(p, hints.get("fill") or dark)
            color = "#FFFFFF"
            p.paragraph_format.space_after = Pt(self.tokens.paragraph_after + 8)
        elif kind == "rule" or hints.get("rule"):
            F.set_paragraph_border(p, "top", hints.get("rule") or dark, int(float(hints.get("rule_width", 2.5)) * 8), 8)
        if hints.get("hang"):
            pf = p.paragraph_format
            if self.rtl_doc:
                pf.right_indent = Pt(-float(hints["hang"]))
            else:
                pf.left_indent = Pt(-float(hints["hang"]))
        if hints.get("drop"):
            frame = self.content_height_pt() * float(hints["drop"])
            p.paragraph_format.space_before = Pt(frame)
        self._runs(p, text, color=color, size=size)
        F.order_paragraph_properties(p)

    def _slab_style(self, lvl: int, fill: str):
        """LibreOffice ignores direct shading on a heading style and would leave white text
        on white, so the band lives in a style. It keeps the heading's outline level."""
        from docx.enum.style import WD_STYLE_TYPE
        from docx.oxml import OxmlElement
        name = f"Heading {lvl} Band {fill.lstrip('#').upper()}"
        styles = self.doc.styles
        if name in [s.name for s in styles]:
            return styles[name]
        style = styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        style.base_style = styles[f"Heading {lvl}"]
        style.quick_style = True
        F.set_paragraph_shading(style, fill)
        pPr = style.element.get_or_add_pPr()
        level = OxmlElement("w:outlineLvl")
        level.set(qn("w:val"), str(lvl - 1))
        pPr.append(level)
        return style

    def content_height_pt(self) -> float:
        s = self.doc.sections[-1]
        return s.page_height.pt - s.top_margin.pt - s.bottom_margin.pt

    def _b_paragraph(self, c, b):
        if (b.hints or {}).get("lead"):
            p = self._para(c, "Normal", b.text)
            p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            p.paragraph_format.space_after = Pt(self.tokens.paragraph_after * 1.5)
            self._runs(p, b.text, size=self.tokens.body_size * 1.2,
                       color=self.tokens.colors["text_secondary"])
            return
        p = self._para(c, "Body Text", b.text)
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        # keep-tail maps to Word's keep-with-next: without "keep lines together"
        # Word may still break inside the paragraph, carrying its last lines on
        if (b.hints or {}).get("keep_with_next") or (b.hints or {}).get("keep_tail_with_next"):
            p.paragraph_format.keep_with_next = True
        if is_rtl_text(b.text) or self.rtl_doc:
            p.paragraph_format.first_line_indent = None
        self._runs(p, b.text)

    def _b_rich_text(self, c, b):
        p = self._para(c, "Normal", b.text)
        p.alignment = {"center": WD_ALIGN_PARAGRAPH.CENTER, "right": WD_ALIGN_PARAGRAPH.RIGHT,
                       "justify": WD_ALIGN_PARAGRAPH.JUSTIFY}.get(b.alignment, p.alignment)
        self._runs(p, b.text, bold=b.bold or None, italic=b.italic or None,
                   size=b.font_size, color=b.color)

    def _b_note(self, c, b):
        self._runs(self._para(c, "Note", b.text), b.text)

    def _b_introduction_page(self, c, b):
        self._runs(self._para(c, "Heading 1", b.title), b.title)
        if b.subtitle:
            self._subtitle(c, b.subtitle)
        for para in (b.content or "").split("\n\n") if isinstance(b.content, str) else (b.content or []):
            if str(para).strip():
                self._runs(self._para(c, "Body Text", str(para)), str(para))
        self._page_break(c)

    # ─── lists ───

    def _list_items(self, c, items, ordered: bool, start: int = 1, level: int = 0, num_id=None):
        if num_id is None:
            num_id = self.lists.new_instance(ordered, start)
        child_ids = {}
        for it in items:
            text = it if isinstance(it, str) else it.text
            checked = None if isinstance(it, str) else it.checked
            p = self._para(c, "List Paragraph", text)
            F.ListNumbering.apply(p, num_id, level)
            if is_rtl_text(text):
                self.lists.keep_label_inside(p, level, ordered)
            if checked is not None:
                r = p.add_run("☑ " if checked else "☐ ")
                F.set_run_fonts(r, "Segoe UI Symbol", "Segoe UI Symbol")
            self._runs(p, text)
            children = [] if isinstance(it, str) else it.children
            if children:
                child_ordered = ordered if it.children_ordered is None else it.children_ordered
                key = child_ordered
                if key not in child_ids:
                    child_ids[key] = (num_id if child_ordered == ordered
                                      else self.lists.new_instance(child_ordered, 1))
                self._list_items(c, children, child_ordered, 1, level + 1, child_ids[key])
        if level == 0:
            self._spacer_after(c, 2)

    def _b_bullet_list(self, c, b):
        if (b.hints or {}).get("columns") == 2 and not isinstance(c, _Cell):
            return self._list_columns(c, b.items, False, 1)
        self._list_items(c, b.items, ordered=False)

    def _b_numbered_list(self, c, b):
        if (b.hints or {}).get("columns") == 2 and not isinstance(c, _Cell):
            return self._list_columns(c, b.items, True, b.start)
        self._list_items(c, b.items, ordered=True, start=b.start)

    def _list_columns(self, c, items, ordered: bool, start: int):
        """Short items in two columns (borderless table); numbering continues."""
        half = (len(items) + 1) // 2
        t = c.add_table(rows=1, cols=2)
        F.set_table_width_pct(t, 100)
        F.set_table_borders(t, size=0)
        F.set_cant_split(t.rows[0])
        if self.rtl_doc:
            F.set_table_bidi(t)
        left, right = t.rows[0].cells
        self._list_items(left, items[:half], ordered, start)
        self._list_items(right, items[half:], ordered, start + half if ordered else 1)
        self._spacer_after(c, 2)

    def _b_checklist(self, c, b):
        for it in b.items:
            p = self._para(c, "List Paragraph", it.text)
            r = p.add_run("☑  " if it.checked else "☐  ")
            F.set_run_fonts(r, "Segoe UI Symbol", "Segoe UI Symbol")
            self._runs(p, it.text)
        self._spacer_after(c, 2)

    def _b_definition_list(self, c, b):
        for it in b.items:
            p = self._para(c, "Normal", it.term)
            p.paragraph_format.keep_with_next = True
            p.paragraph_format.space_after = Pt(1)
            self._runs(p, it.term, bold=True)
            d = self._para(c, "Normal", it.definition)
            d.paragraph_format.left_indent = Pt(18)
            self._runs(d, it.definition)

    # ─── table ───

    def _b_table(self, c, b):
        # landscape sections are opened/closed by render() around the table's run
        self._table(c, b, b.hints or {})

    def _switch_orientation(self, landscape: bool):
        from docx.enum.section import WD_SECTION
        prev = self.doc.sections[-1]
        sec = self.doc.add_section(WD_SECTION.NEW_PAGE)
        w, h = prev.page_width, prev.page_height
        if landscape != (w > h):
            sec.page_width, sec.page_height = h, w
        sec.orientation = WD_ORIENT.LANDSCAPE if landscape else WD_ORIENT.PORTRAIT
        for attr in ("top_margin", "bottom_margin", "left_margin", "right_margin",
                     "header_distance", "footer_distance"):
            setattr(sec, attr, getattr(prev, attr))
        self.content_width_pt = sec.page_width.pt - sec.left_margin.pt - sec.right_margin.pt

    def _switch_columns(self, columns: int, gap: float):
        """A continuous section with ``columns`` real Word columns: text stays editable and reflows."""
        from docx.enum.section import WD_SECTION
        sec = self.doc.add_section(WD_SECTION.CONTINUOUS)
        sec.different_first_page_header_footer = False
        body = self.doc.element.body
        marker = body.xpath("./w:p[last()]")[-1]      # python-docx parks the break in an empty paragraph
        before = marker.getprevious()
        if before is not None and before.tag == F.qn("w:p"):
            before.get_or_add_pPr().append(marker.pPr.find(F.qn("w:sectPr")))
            body.remove(marker)
        cols = F._get_or_add(sec._sectPr, "w:cols")
        cols.set(F.qn("w:num"), str(columns))
        cols.set(F.qn("w:space"), str(int(gap * 20)))

    def _table(self, c, b, hints):
        size = hints.get("font_size")
        if b.caption or b.table_number:
            label = f"Table {b.table_number}" if b.table_number else ""
            full = f"{label}: {b.caption}" if (label and b.caption) else (b.caption or label)
            p = self._para(c, "Caption", full)
            p.alignment = None if (self.rtl_doc or is_rtl_text(full)) else WD_ALIGN_PARAGRAPH.LEFT
            p.paragraph_format.keep_with_next = True
            p.paragraph_format.space_after = Pt(3)
            self._runs(p, full)
        headers = list(b.headers or [])
        rows = [list(r) for r in b.rows]
        ncols = max([len(headers)] + [len(r) for r in rows] + [1])
        headers += [""] * (ncols - len(headers)) if headers else []
        has_header = bool(headers)
        t = c.add_table(rows=(1 if has_header else 0) + len(rows) + (1 if b.footer_row else 0),
                        cols=ncols)
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        F.set_table_width_pct(t, 100)
        F.set_table_borders(t, color=self.tokens.colors["border"], size=4,
                            inside_v=b.style in ("grid", "bordered"))
        F.set_table_cell_margins(t, 50, 50, int(hints.get("cell_padding", 6) * 20), int(hints.get("cell_padding", 6) * 20))
        # Column order follows the table's own language, not the document's
        sample = [plain_text(str(x)) for x in (headers or (rows[0] if rows else [])) if str(x).strip()]
        if sample and sum(is_rtl_text(x) for x in sample) * 2 > len(sample):
            F.set_table_bidi(t)
        # numeric columns are right-aligned (decimal-friendly)
        numeric_cols = set()
        for ci in range(ncols):
            vals = [r[ci] for r in rows if ci < len(r) and str(r[ci]).strip()]
            if vals and sum(bool(_NUMERIC.match(plain_text(str(v)))) for v in vals) / len(vals) >= 0.8:
                numeric_cols.add(ci)
        hdr_bg = b.header_bg or self.tokens.colors["table_header_bg"]
        hdr_fg = b.header_text_color or self.tokens.colors["table_header_text"]
        r0 = 0
        if has_header:
            row = t.rows[0]
            F.set_repeat_table_header(row)
            F.set_cant_split(row)
            for ci, h in enumerate(headers):
                cell = row.cells[ci]
                if not hints.get("design"):
                    F.set_cell_shading(cell, hdr_bg)
                p = self._para(cell, "Table Text", str(h))
                if ci in numeric_cols:
                    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                p.paragraph_format.keep_with_next = True
                self._runs(p, str(h), bold=True, size=size,
                           color=self.tokens.colors["text_primary"] if hints.get("design") else hdr_fg)
            r0 = 1
        alt = self.tokens.colors.get("table_row_alt", "#F7F9FC")
        all_rows = rows + ([list(b.footer_row)] if b.footer_row else [])
        for ri, data in enumerate(all_rows):
            row = t.rows[r0 + ri]
            F.set_cant_split(row)
            is_footer = b.footer_row and ri == len(all_rows) - 1
            for ci in range(ncols):
                val = str(data[ci]) if ci < len(data) else ""
                cell = row.cells[ci]
                if b.style == "striped" and ri % 2 == 1 and not is_footer and not hints.get("design"):
                    F.set_cell_shading(cell, alt)
                p = self._para(cell, "Table Text", val)
                if ci in numeric_cols:
                    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                if hints.get("keep_together") and ri < len(all_rows) - 1:
                    p.paragraph_format.keep_with_next = True
                self._runs(p, val, bold=True if is_footer else None, size=size)
        widths = None
        if b.column_widths and len(b.column_widths) == ncols:
            # v0.3 semantics: points; scaled down if wider than the text block
            scale = min(1.0, self.content_width_pt / (sum(b.column_widths) or 1))
            widths = [w * scale for w in b.column_widths]
        elif hints.get("col_fractions") and len(hints["col_fractions"]) == ncols:
            widths = [f * self.content_width_pt for f in hints["col_fractions"]]
        if widths:
            F.set_table_layout_fixed(t)
            for ci, wv in enumerate(widths):
                t.columns[ci].width = Pt(wv)
                for row in t.rows:
                    row.cells[ci].width = Pt(wv)
        if hints.get("design"):
            self._art_table(t, hints, has_header, bool(b.footer_row))
        self._spacer_after(c)

    def _art_table(self, t, hints, has_header, has_footer):
        """Rules and tone in place of a grid, cell by cell so that Word keeps them."""
        dark = _ink(self.theme) if self.theme is not None else self.tokens.colors["primary"]
        hair = self.tokens.colors["border"]
        ledger = hints["design"] == "ledger"
        F.set_table_borders(t, size=0)
        last = len(t.rows) - 1
        current = hints.get("current_col")
        for ri, row in enumerate(t.rows):
            head = has_header and ri == 0
            for ci, cell in enumerate(row.cells):
                sides = {"bottom": ("single", 3, hair), "left": None, "right": None}
                if head:
                    sides["bottom"] = ("single", 8, dark)
                    if ledger:
                        sides["top"] = ("single", 12, dark)
                if ledger and ri == last:
                    sides["bottom"] = ("single", 12, dark)
                if has_footer and ri == last:
                    sides["top"] = ("single", 8, dark)
                F.set_cell_borders(cell, **sides)
                if current == ci:
                    F.set_cell_shading(cell, _mix(dark, "#FFFFFF", 0.9))

    # ─── code / quote / callout ───

    def _b_code(self, c, b):
        label = b.filename or b.caption
        if label:
            p = self._para(c, "Caption", label)
            p.alignment = WD_ALIGN_PARAGRAPH.LEFT
            p.paragraph_format.keep_with_next = True
            p.add_run(label)
        lines = b.code.split("\n")
        width = len(str(len(lines)))
        for i, line in enumerate(lines, 1):
            p = self._para(c, "Code")
            p.paragraph_format.keep_together = True
            if i < len(lines):
                p.paragraph_format.keep_with_next = len(lines) <= 25
            prefix = f"{i:>{width}}  " if b.line_numbers else ""
            r = p.add_run(prefix + line.replace("\t", "    ") if (prefix + line) else " ")
            if (b.hints or {}).get("font_size"):
                r.font.size = Pt(b.hints["font_size"])
            if i in (b.highlight_lines or []):
                F.set_run_shading(r, "3A3F58")
        self._spacer_after(c)

    def _statement(self, c, b, hints):
        whole_page = hints.get("statement") == "page"
        base = self.tokens.body_size
        rtl = self.rtl_doc or is_rtl_text(b.text)
        p = self._para(c, "Normal", b.text)
        if whole_page:
            p.paragraph_format.page_break_before = True
            p.paragraph_format.space_before = Pt(self.content_height_pt() * float(hints.get("drop", 0.34)))
        else:
            p.paragraph_format.space_before = Pt(self.tokens.paragraph_after * 2)
        p.paragraph_format.keep_with_next = bool(b.attribution)
        p.paragraph_format.keep_together = True
        p.paragraph_format.space_after = Pt(8)
        dark = hints.get("color") or (_ink(self.theme) if self.theme is not None else self.tokens.colors["primary"])
        F.set_paragraph_border(p, "top", hints.get("rule") or self.tokens.colors["accent"], 24, 12)
        self._runs(p, b.text, size=base * float(hints.get("scale", 2.5 if whole_page else 1.7)), color=dark,
                   bold=hints.get("weight") == "bold" or None)
        if b.attribution:
            a = self._para(c, "Normal", b.attribution)
            self._runs(a, b.attribution if F.has_complex_script(b.attribution) else f"— {b.attribution}",
                       color=self.tokens.colors["text_secondary"])
            a.alignment = WD_ALIGN_PARAGRAPH.RIGHT if rtl and not self.rtl_doc else None
        if whole_page:
            self._page_break(c)

    def _b_quote(self, c, b):
        if (b.hints or {}).get("statement"):
            return self._statement(c, b, b.hints)
        for part in b.text.split("\n"):
            if part.strip():
                self._runs(self._para(c, "Quote", part), part)
        if b.attribution:
            p = self._para(c, "Quote", b.attribution)
            p.alignment = WD_ALIGN_PARAGRAPH.LEFT if self.rtl_doc else WD_ALIGN_PARAGRAPH.RIGHT
            self._runs(p, f"— {b.attribution}", italic=False)

    def _b_callout(self, c, b):
        key = _VARIANT_COLORS.get((b.variant or "info").lower(), "info")
        color = self.tokens.colors.get(key, self.tokens.colors["info"])
        cell = self._boxed(c, _tint(color, 0.9), color)
        if b.title:
            p = self._para(cell, "Normal", b.title)
            self._runs(p, b.title, bold=True, color=color)
        for part in b.text.split("\n\n"):
            if part.strip():
                p = self._para(cell, "Normal", part)
                p.paragraph_format.space_after = Pt(2)
                self._runs(p, part)

    # ─── media ───

    def _b_image(self, c, b):
        from ..layout.factory import _image_treatment
        asset = ingest(b.src, self.col.policy.assets)
        self.figure_no += 1
        t = _image_treatment(b)
        plain = not (b.placement or b.treatment or b.height or b.border or b.shadow or asset.is_vector)
        alt = b.alt_text or b.caption or "image"
        if plain:
            self._picture(c, asset.data, alt, width_pt=b.width, align=b.alignment)
            self._figure_caption(c, b)
            return
        mode = normal_mode(b.placement) if b.placement else "inline"
        if mode in ("behind_text", "in_front_of_text"):
            return self._image_on_page(c, b, asset, t, mode, alt)
        if mode == "floating" and isinstance(c, type(self.doc)) and self._can_float(b, asset, t):
            return self._image_float(c, b, asset, t, alt)
        p_ = b.placement
        geo = M.page_geometry(self, self.doc.sections[-1])
        bleed = bool(p_ and p_.bleed)
        avail_w = geo.width if bleed else self.content_width_pt
        want_w = avail_w * p_.width_ratio if p_ and p_.width_ratio else b.width
        frame_h = geo.height - geo.top - geo.bottom
        want_h = frame_h * p_.height_ratio if p_ and p_.height_ratio else b.height
        cap = 0.85 if (b.caption or b.figure_number) else 0.98
        natural = asset.width * 72.0 / ((asset.dpi or (96, 96))[0])
        w, h = flow_box(asset, want_w, want_h, avail_w, frame_h * cap, natural, t)
        f = fit_image(asset, w, h, t)
        check_resolution(asset, f, self.col, f"Image {b.alt_text or ''}".strip(), LOW_RESOLUTION_DPI)
        para = self._para(c)
        para.paragraph_format.keep_with_next = True
        if bleed:
            M.squeeze(para)
            M.add_drawing(para.add_run(), asset, f, t, alt, self.next_shape(), M.Anchor(
                h_from="page", v_from="paragraph", x=0, y=0, behind=False, wrap="top_bottom", gutter=10))
        else:
            side = physical_side(p_.horizontal, self.rtl_doc) if p_ and p_.horizontal != "center" else b.alignment
            para.alignment = {"left": WD_ALIGN_PARAGRAPH.LEFT, "right": WD_ALIGN_PARAGRAPH.RIGHT}.get(
                side, WD_ALIGN_PARAGRAPH.CENTER)
            M.add_drawing(para.add_run(), asset, f, t, alt, self.next_shape())
        self._figure_caption(c, b)

    def _figure_caption(self, c, b):
        from ..i18n import label as _i18n
        lang = "ar" if self.rtl_doc else self.sem.language
        if b.caption or b.figure_number:
            label = f"{_i18n('figure', lang)} {b.figure_number}" if b.figure_number else ""
            self._caption(c, label, b.caption)
        if b.source:
            self._caption(c, "", f"{_i18n('source', lang)}: {b.source}")

    def _image_on_page(self, c, b, asset, t, mode, alt):
        """Over or under the page's text, as in the PDF: against the page or margins,
        or at this point in the text."""
        from ..media import page_box, page_position
        p_ = b.placement
        geo = M.page_geometry(self, self.doc.sections[-1])
        host = M.tiny_paragraph(c)
        behind = mode == "behind_text"
        if p_.relative_to == "content":
            w = self.content_width_pt * (p_.width_ratio or 1.0)
            h = flow_box(asset, w, None, w, None, None, t)[1]
            f = fit_image(asset, w, h, t)
            anchor = M.Anchor(h_from="margin", v_from="paragraph", align="center", behind=behind,
                              z=p_.z_index)
        else:
            w, h = page_box(geo, p_)
            if not p_.height_ratio and t.fit == "contain":
                h = w / asset.aspect
            f = fit_image(asset, w, h, t)
            x, y = page_position(geo, p_, w, h)
            anchor = M.Anchor(x=x + f.x, y=y + f.y, behind=behind, z=p_.z_index)
        M.add_drawing(host.add_run(), asset, f, t, alt, self.next_shape(), anchor)

    def _float_width(self, b) -> float:
        ratio = b.placement.width_ratio or 0.42
        return min(b.width or self.content_width_pt * ratio, self.content_width_pt * 0.62)

    def _can_float(self, b, asset, t) -> bool:
        """The same test as the PDF: enough text must follow to wrap the image."""
        i = self.col.block_index
        fig_w = self._float_width(b)
        fig_h = flow_box(asset, fig_w, None, fig_w, None, None, t)[1]
        narrow = self.content_width_pt - fig_w - b.placement.gutter
        base = self.theme.typography.base_size
        got = 0.0
        for nxt in self.sem.blocks[(i or 0) + 1:]:
            if nxt.type not in ("paragraph", "bullet_list", "numbered_list") or got >= fig_h:
                break
            chars = len(getattr(nxt, "text", None) or "") or 80
            got += (chars * base * 0.5 / narrow + 1) * base * 1.4
        if got < fig_h * 0.4:
            self.col.warn("float_fallback", "Too little text follows this floating image to wrap it; "
                          "it was set inline")
            return False
        return True

    def _image_float(self, c, b, asset, t, alt):
        """Text wraps a floating table holding the picture and its caption. Word and
        LibreOffice keep such a table whole on a page; a bare anchored picture can run
        past the bottom margin, because nothing moves it with its paragraph."""
        p_ = b.placement
        fig_w = self._float_width(b)
        frame_h = self.doc.sections[-1].page_height.pt * 0.5
        w, h = flow_box(asset, fig_w, None, fig_w, frame_h, None, t)
        f = fit_image(asset, w, h, t)
        check_resolution(asset, f, self.col, f"Image {b.alt_text or ''}".strip(), LOW_RESOLUTION_DPI)
        side = physical_side(p_.horizontal, self.rtl_doc)
        side = side if side != "center" else ("left" if self.rtl_doc else "right")
        table = M.floating_table(c, fig_w, side, p_.gutter)
        cell = table.rows[0].cells[0]
        para = cell.paragraphs[0]
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        para.paragraph_format.space_after = Pt(3)
        M.add_drawing(para.add_run(), asset, f, t, alt, self.next_shape())
        self._figure_caption(cell, b)
        self._float_open = True

    def _b_page_media(self, c, b):
        if b.scope not in ("once", "cover"):
            return
        asset = ingest(b.src, self.col.policy.assets)
        M.add_layer(self, M.tiny_paragraph(c), b, M.page_geometry(self, self.doc.sections[-1]), asset)

    def _b_page_section(self, c, b):
        from docx.enum.section import WD_SECTION
        sec = self.doc.add_section(WD_SECTION.NEW_PAGE if b.new_page else WD_SECTION.CONTINUOUS)
        sec.different_first_page_header_footer = False
        self.section_name = b.name
        system = self.page_sys
        has_override = system is not None and b.name in system.sections
        if has_override or self._layers_for(b.name) != self._layers_for(None):
            self._page_parts(sec, b.name)

    def _b_chart(self, c, b):
        from .chart import chart_png
        png = chart_png(b, self.theme)
        alt = f"{b.chart_type} chart" + (f": {b.title}" if b.title else "")
        data_txt = _short_data(b.data)
        self._picture(c, png, f"{alt}. Data: {data_txt}" if data_txt else alt,
                      max_width_pt=min(self.content_width_pt, 6.3 * 72))
        self._spacer_after(c)

    def _b_diagram(self, c, b):
        from .diagram import diagram_png
        png = diagram_png(b, self.theme)
        labels = ", ".join(str(n.get("label", n.get("id")) if isinstance(n, dict) else n)
                           for n in (b.nodes or [])[:20])
        self._picture(c, png, f"{b.diagram_type} diagram" + (f": {b.title}" if b.title else "")
                      + (f". Nodes: {labels}" if labels else ""),
                      max_width_pt=min(self.content_width_pt, b.width * 72))
        self._spacer_after(c)

    def _b_mermaid(self, c, b):
        from .mermaid import MermaidUnavailable, mermaid_png
        try:
            png = mermaid_png(b)
        except MermaidUnavailable as e:
            self.col.warn("mermaid_fallback", f"Mermaid diagram rendered as source: {e}")
            from ..schema.blocks import CodeBlock
            return self._b_code(c, CodeBlock(language="mermaid", code=b.diagram))
        self._picture(c, png, f"Mermaid diagram: {b.diagram[:500]}")

    def _b_math(self, c, b):
        from .math import math_png
        try:
            png = math_png(b.latex)
        except Exception as e:
            self.col.warn("math_fallback", f"Math rendered as source text ({type(e).__name__}: {e})")
            p = self._para(c, "Code")
            p.add_run(b.latex)
            return
        p = self._picture(c, png, f"Equation: {b.latex}",
                          max_width_pt=min(self.content_width_pt, 5.5 * 72))
        if b.equation_number:
            p.add_run(f"   ({b.equation_number})")

    def _b_qrcode(self, c, b):
        try:
            import qrcode
        except ImportError:
            self.col.warn("qrcode_unavailable",
                          'QR code rendered as text: install "dynamic-pdf-builder[qrcode]"')
            self._runs(self._para(c, "Normal"), f"[QR Code: {b.data}]")
            return
        img = qrcode.make(b.data)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        self._picture(c, buf.getvalue(), f"QR code: {b.data}", width_pt=b.size, align=b.alignment)
        if b.caption:
            self._caption(c, "", b.caption)

    def _b_shape(self, c, b):
        # Decorative vector shape: native framed cell with its label (editable text)
        fill = b.fill_color or self.tokens.colors["surface"]
        t = c.add_table(rows=1, cols=1)
        F.set_table_borders(t, color=b.stroke_color or self.tokens.colors["border"],
                            size=max(2, int((b.stroke_width or 1) * 8)))
        t.alignment = {"left": WD_TABLE_ALIGNMENT.LEFT, "right": WD_TABLE_ALIGNMENT.RIGHT}.get(
            b.alignment, WD_TABLE_ALIGNMENT.CENTER)
        cell = t.rows[0].cells[0]
        cell.width = Pt(min(b.width, self.content_width_pt))
        t.rows[0].height = Pt(b.height)
        F.set_cell_shading(cell, fill)
        p = self._para(cell, "Normal", b.label or "")
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        if b.label:
            self._runs(p, b.label, color=b.label_color)
        self._spacer_after(c)

    # ─── data display ───

    def _art_metrics(self, c, b, style):
        band = style == "band"
        dark = _ink(self.theme) if self.theme is not None else self.tokens.colors["primary"]
        n = max(1, len(b.metrics))
        t = c.add_table(rows=1, cols=n)
        F.set_table_width_pct(t, 100)
        F.set_table_borders(t, size=0)
        F.set_table_cell_margins(t, 100, 100, 100 if band else 0, 140)
        F.set_cant_split(t.rows[0])
        if self.rtl_doc:
            F.set_table_bidi(t)
        fg = "#FFFFFF" if band else dark
        muted = "#FFFFFF" if band else self.tokens.colors["text_secondary"]
        scale = float((b.hints or {}).get("value_scale", 2.5 if n <= 3 else 2.1))
        section = self.doc.sections[-1]
        room = (section.page_width - section.left_margin - section.right_margin) / 12700 / n - 14
        longest = max(len(m.value) for m in b.metrics) if b.metrics else 1
        scale = max(1.3, min(scale, room / (longest * 0.56 * self.tokens.body_size)))
        for i, m in enumerate(b.metrics):
            cell = t.rows[0].cells[i]
            if band:
                F.set_cell_shading(cell, dark)
            else:
                F.set_cell_borders(cell, top=("single", 16, dark))
            for text, size, color, bold in ((m.value, self.tokens.body_size * scale, fg, True),
                                            (m.label, self.tokens.body_size * 0.86, muted, None),
                                            (m.delta, self.tokens.body_size * 0.8, muted, True)):
                if text:
                    p = self._para(cell, "Normal", text)
                    p.paragraph_format.space_after = Pt(1)
                    self._runs(p, text, size=size, color=color, bold=bold)
        self._spacer_after(c)

    def _b_metric_row(self, c, b):
        if (b.hints or {}).get("style"):
            return self._art_metrics(c, b, b.hints["style"])
        n = max(1, len(b.metrics))
        t = c.add_table(rows=1, cols=n)
        F.set_table_width_pct(t, 100)
        F.set_table_borders(t, color=self.tokens.colors["border"], size=4, inside_v=True)
        F.set_table_cell_margins(t, 100, 100, 120, 120)
        F.set_cant_split(t.rows[0])           # a KPI tile never splits across pages
        if self.rtl_doc:
            F.set_table_bidi(t)
        for i, m in enumerate(b.metrics):
            cell = t.rows[0].cells[i]
            F.set_cell_shading(cell, self.tokens.colors["surface"])
            p = self._para(cell, "Normal", m.label)
            p.paragraph_format.space_after = Pt(0)
            self._runs(p, m.label.upper(), size=self.tokens.caption_size,
                       color=self.tokens.colors["text_muted"], bold=True)
            p = self._para(cell, "Normal", m.value)
            p.paragraph_format.space_after = Pt(0)
            self._runs(p, m.value, size=self.tokens.body_size * 1.9, bold=True,
                       color=self.tokens.colors["primary"])
            if m.delta:
                neg = m.delta.strip().startswith(("-", "−", "▼"))
                p = self._para(cell, "Normal", m.delta)
                self._runs(p, m.delta, size=self.tokens.caption_size + 1,
                           color=self.tokens.colors["error" if neg else "success"])
        self._spacer_after(c)

    def _b_progress_bar(self, c, b):
        if b.title:
            self._runs(self._para(c, "Heading 4", b.title), b.title)
        if b.subtitle:
            self._runs(self._para(c, "Note", b.subtitle), b.subtitle)
        t = c.add_table(rows=len(b.items), cols=3)
        F.set_table_width_pct(t, 100)
        F.set_table_borders(t, size=0)
        F.set_table_layout_fixed(t)
        widths = [0.3, 0.52, 0.18]
        for i, it in enumerate(b.items):
            pct = 0 if not it.max_value else max(0.0, min(1.0, it.value / it.max_value))
            for cell, wv in zip(t.rows[i].cells, widths):
                cell.width = Pt(self.content_width_pt * wv)
            label, bar, val = t.rows[i].cells
            bar._dpb_used = True
            bar.paragraphs[0].paragraph_format.space_after = Pt(0)
            bar.paragraphs[0].paragraph_format.line_spacing = Pt(1)
            self._runs(self._para(label, "Table Text", it.label), it.label)
            inner = bar.add_table(rows=1, cols=2) if pct not in (0.0, 1.0) else bar.add_table(rows=1, cols=1)
            F.set_table_borders(inner, size=0)
            F.set_table_width_pct(inner, 100)
            inner.rows[0].height = Pt(9)
            F.set_cell_shading(inner.rows[0].cells[0],
                               it.color or self.tokens.colors["primary"] if pct > 0 else "#E5E7EB")
            bar_w = self.content_width_pt * widths[1] - 12
            if len(inner.rows[0].cells) == 2:
                F.set_table_layout_fixed(inner)
                inner.rows[0].cells[0].width = Pt(bar_w * pct)
                inner.rows[0].cells[1].width = Pt(bar_w * (1 - pct))
                F.set_cell_shading(inner.rows[0].cells[1], "#E5E7EB")
            txt = f"{it.value:g} / {it.max_value:g}" if b.show_value else f"{pct:.0%}"
            if b.show_delta and it.delta:
                txt += f"  ({it.delta})"
            p = self._para(val, "Table Text", txt)
            p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            self._runs(p, txt)
        self._spacer_after(c)

    def _b_score_display(self, c, b):
        p = self._para(c, "Normal")
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_after = Pt(0)
        self._runs(p, f"{b.score:g}", size=self.tokens.body_size * 3.2, bold=True,
                   color=b.score_color or self.tokens.colors["primary"])
        self._runs(p, f" / {b.max_score:g}", size=self.tokens.body_size * 1.4,
                   color=self.tokens.colors["text_muted"])
        if b.label:
            q = self._para(c, "Normal", b.label)
            q.alignment = WD_ALIGN_PARAGRAPH.CENTER
            q.paragraph_format.space_after = Pt(0)
            self._runs(q, b.label, bold=True, color=b.label_color)
        if b.sublabel:
            q = self._para(c, "Note", b.sublabel)
            q.alignment = WD_ALIGN_PARAGRAPH.CENTER
            self._runs(q, b.sublabel)

    def _b_legend(self, c, b):
        if b.title:
            self._runs(self._para(c, "Heading 4", b.title), b.title)
        p = None
        for it in b.items:
            if p is None or b.layout != "horizontal":
                p = self._para(c, "Normal", it.label)
            r = p.add_run("■ ")
            r.font.color.rgb = rgb(it.color)
            self._runs(p, it.label, bold=True)
            if it.description:
                self._runs(p, f" — {it.description}")
            if b.layout == "horizontal":
                p.add_run("     ")

    def _b_badge(self, c, b):
        p = self._para(c, "Normal", b.text)
        r = p.add_run(f" {plain_text(b.text)} ")
        r.font.bold = True
        r.font.size = Pt(b.font_size or self.tokens.caption_size + 1)
        r.font.color.rgb = rgb(b.color or self.tokens.colors["text_on_primary"])
        F.set_run_shading(r, b.bg_color or self.tokens.colors["primary"])

    def _b_timeline(self, c, b):
        t = c.add_table(rows=len(b.events), cols=2)
        F.set_table_width_pct(t, 100)
        F.set_table_borders(t, size=0)
        if self.rtl_doc:
            F.set_table_bidi(t)
        for i, ev in enumerate(b.events):
            F.set_cant_split(t.rows[i])
            d, body = t.rows[i].cells
            d.width = Pt(self.content_width_pt * 0.22)
            body.width = Pt(self.content_width_pt * 0.78)
            side = "right" if self.rtl_doc else "left"
            F.set_cell_borders(body, **{side: ("single", 16, ev.color or self.tokens.colors["accent"])})
            self._runs(self._para(d, "Table Text", ev.date), ev.date, bold=True,
                       color=ev.color or self.tokens.colors["accent"])
            self._runs(self._para(body, "Table Text", ev.title), ev.title, bold=True)
            if ev.description:
                self._runs(self._para(body, "Table Text", ev.description), ev.description)
        self._spacer_after(c)

    # ─── academic ───

    def _b_footnote(self, c, b):
        p = self._para(c, "Note", b.text)
        r = p.add_run(b.marker)
        r.font.superscript = True
        p.add_run(" ")
        self._runs(p, b.text)

    def _b_abstract(self, c, b):
        cell = self._boxed(c, self.tokens.colors["surface"], self.tokens.colors["accent"])
        self._runs(self._para(cell, "Heading 4", self._label("abstract")), self._label("abstract"))
        for f in b.fields:
            p = self._para(cell, "Normal", f.text)
            self._runs(p, f"{f.label}: ", bold=True)
            self._runs(p, f.text)
        if b.keywords:
            p = self._para(cell, "Normal", " ".join(b.keywords))
            self._runs(p, self._label("keywords") + ": ", bold=True, italic=True)
            self._runs(p, ", ".join(b.keywords), italic=True)

    def _b_bibliography(self, c, b):
        self._runs(self._para(c, "Heading 2", self._label("references")), self._label("references"))
        for i, e in enumerate(b.entries, 1):
            p = self._para(c, "Normal", e.title)
            pf = p.paragraph_format
            pf.left_indent = Pt(24)
            pf.first_line_indent = Pt(-24)
            if b.style == "ieee":
                self._runs(p, f"[{i}] {e.authors}, “{e.title},” *{e.source}*, {e.year}.")
            else:
                self._runs(p, f"{e.authors} ({e.year}). {e.title}. *{e.source}*.")
            if e.doi:
                p.add_run(" ")
                F.add_hyperlink(p, f"https://doi.org/{e.doi}", f"doi:{e.doi}")

    def _b_citation(self, c, b):
        self._runs(self._para(c, "Normal"), f"[{b.key}]")

    def _b_signature(self, c, b):
        sp = self._para(c, "Normal")
        sp.paragraph_format.space_before = Pt(28)
        sp.paragraph_format.keep_with_next = True
        if b.show_line:
            sp.add_run("_" * 34)
        for txt, bold in ((b.name, True), (b.title, False), (b.date, False)):
            if txt:
                p = self._para(c, "Normal", txt)
                p.paragraph_format.space_after = Pt(0)
                p.paragraph_format.keep_with_next = True
                self._runs(p, txt, bold=bold or None)

    # ─── structure ───

    def _subtitle(self, c, text: str, color=None):
        p = self._runs(self._para(c, "Subtitle", text), text, color=color)
        if F.has_complex_script(text):
            for run in p.runs:
                F.clear_style_slant_and_tracking(run)
        return p

    def _masthead(self, c, b):
        """A short document's title block: a shaded cell, with live text."""
        dark = b.background_color or (_ink(self.theme) if self.theme is not None else self.tokens.colors["primary"])
        ink = b.text_color or "#FFFFFF"
        cell = self._boxed(c, dark)
        scale = float((b.hints or {}).get("title_scale", 2.5))
        p = self._para(cell, "Title", b.title)
        size = self.tokens.title_size if self.theme.typography.title_size else self.tokens.body_size * scale
        self._runs(p, b.title, size=size, color=ink)
        for text, size in ((b.subtitle, 1.15), (b.author, 0.9)):
            if text:
                q = self._para(cell, "Normal", text)
                q.paragraph_format.space_after = Pt(2)
                self._runs(q, text, size=self.tokens.body_size * size, color=ink)

    def _designed_cover(self, c, b):
        """A cover with a backdrop: page-anchored drawings behind live text."""
        from ..layout.cover import cover_plan, title_drop
        hints = b.hints or {}
        if hints.get("masthead"):
            return self._masthead(c, b)
        geo = M.page_geometry(self, self.doc.sections[0])
        rtl = self.rtl_doc or is_rtl_text(b.title)
        layout, split, layers, ink = cover_plan(b, geo, rtl, self.col)
        host = M.tiny_paragraph(c)
        for z, item in enumerate(sorted(layers, key=lambda i: i.z), 1):
            top = geo.height - item.y - (item.h or item.fitted.height)
            if item.fill:
                F.add_page_text_box(host, self.next_shape(), item.x, top, item.w, item.h, item.fill,
                                    description="Cover panel", opacity=item.fill_opacity, z=M._Z_BASE + z)
            else:
                M.add_drawing(host.add_run(), item.asset, item.fitted, item.treatment, "Cover image",
                              self.next_shape(), M.Anchor(x=item.x, y=top, z=z))
        align = {"centered": WD_ALIGN_PARAGRAPH.CENTER}.get(
            layout, WD_ALIGN_PARAGRAPH.RIGHT if rtl else WD_ALIGN_PARAGRAPH.LEFT)
        indent = geo.width * 0.46 + 24 - geo.right if split else 0
        frame_h = geo.height - geo.top - geo.bottom

        def setup(par):
            par.alignment = align
            if indent:
                # w:ind left and right swap sides in a right-to-left paragraph
                bidi = par._p.pPr is not None and par._p.pPr.find(qn("w:bidi")) is not None
                if rtl != bidi:
                    par.paragraph_format.left_indent = Pt(indent)
                else:
                    par.paragraph_format.right_indent = Pt(indent)
            return par

        used = 0.0
        if b.logo:
            try:
                asset = ingest(b.logo, self.col.policy.assets)
                w = min(170.0, 58 * asset.aspect)
                f = fit_image(asset, w, w / asset.aspect)
                M.add_drawing(setup(self._para(c)).add_run(), asset, f, None, "logo", self.next_shape())
                used = f.height + 4
            except DynamicPDFError as e:
                self.col.fail("asset_failed", f"Cover logo: {e}", e)
        title = setup(self._para(c, "Title", b.title))
        title.paragraph_format.space_before = Pt(max(24, title_drop(b, layout, frame_h, geo.height, geo.top) - used))
        if hints.get("rule"):
            F.set_paragraph_border(title, "top", hints["rule"], 24, 14)
        if hints.get("title_scale"):
            size = (self.tokens.title_size if self.theme.typography.title_size else
                    self.tokens.body_size * self.tokens_h1_ratio() * float(hints["title_scale"]))
            self._runs(title, b.title, color=ink, size=size)
        else:
            self._runs(title, b.title, color=ink)
        if b.subtitle:
            sub = setup(self._subtitle(c, b.subtitle, color=ink))
            sub.paragraph_format.space_after = Pt(18)
        for txt in ((f"{self._label('prepared_by')} {b.author}" if b.author else None), b.date):
            if txt:
                p = setup(self._para(c, "Normal", txt))
                p.paragraph_format.space_after = Pt(2)
                self._runs(p, txt, color=ink or self.tokens.colors["text_secondary"])
        self._page_break(c)

    def tokens_h1_ratio(self) -> float:
        return self.tokens.heading_sizes[0] / self.tokens.body_size

    def _b_cover_page(self, c, b):
        if b.background_image or b.background_color or b.layout:
            return self._designed_cover(c, b)
        sp = self._para(c, "Normal")
        sp.paragraph_format.space_before = Pt(96)
        if b.logo:
            try:
                buf, _ = load_image(b.logo, self.col.policy.assets)
                self._picture(c, buf.getvalue(), "logo", width_pt=150, align="left")
            except DynamicPDFError as e:
                self.col.fail("asset_failed", f"Cover logo: {e}", e)
        self._runs(self._para(c, "Title", b.title), b.title)
        if b.subtitle:
            self._subtitle(c, b.subtitle)
        for txt in ((f"{self._label('prepared_by')} {b.author}" if b.author else None), b.date):
            if txt:
                p = self._para(c, "Normal", txt)
                p.paragraph_format.space_before = Pt(18)
                self._runs(p, txt, color=self.tokens.colors["text_muted"])
        self._page_break(c)

    def _b_table_of_contents(self, c, b):
        title = self._label("toc")
        p = self._para(c, "TOC Heading", title)
        self._runs(p, title)
        depth = max(1, min(6, getattr(b, "depth", 3) or 3))
        entries = [o for o in self.sem.outline if o.level <= depth]
        # TOC field; its cached result lists every heading as a live link so the
        # TOC is useful even before Word refreshes page numbers (updateFields).
        first = self._para(c, "TOC 1")
        F.begin_field(first, f'TOC \\o "1-{depth}" \\h \\z \\u')
        if not entries:
            first.add_run("Right-click to update table of contents.")
        counters = [0] * 6
        for i, o in enumerate(entries):
            text = o.text
            if self.sem.meta.section_numbering:
                counters[o.level - 1] += 1
                for j in range(o.level, 6):
                    counters[j] = 0
                text = ".".join(str(n) for n in counters[:o.level] if n) + "  " + text
            p = first if i == 0 else self._para(c, f"TOC {min(o.level, 3)}", o.text)
            if i == 0:
                p.style = self.doc.styles[f"TOC {min(o.level, 3)}"]
            F.add_hyperlink(p, f"#{o.id}", text)
        F.end_field(first if not entries else p)
        self._page_break(c)

    def _b_page_break(self, c, b):
        self._page_break(c)

    def _page_break(self, c):
        if isinstance(c, _Cell):
            return
        p = c.add_paragraph()
        p.add_run().add_break(WD_BREAK.PAGE)
        p.paragraph_format.space_after = Pt(0)

    def _b_divider(self, c, b):
        p = self._para(c, "Normal")
        p.paragraph_format.space_after = Pt(self.tokens.block_gap)
        F.set_paragraph_border(p, "bottom", b.color or self.tokens.colors["border"],
                               max(2, int((b.thickness or 1) * 6)), 1)

    def _b_spacer(self, c, b):
        p = self._para(c, "Normal")
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.line_spacing = Pt(max(1, b.height))

    def _b_watermark(self, c, b):
        sec = self.doc.sections[0]
        headers = [sec.header] + ([sec.first_page_header] if sec.different_first_page_header_footer else [])
        for h in headers:
            F.add_text_watermark(h, b.text, (b.color or "#C0C0C0"), max(0.05, min(1.0, b.opacity * 3)))

    def _columns(self, c, cols: list, ratios: list):
        t = c.add_table(rows=1, cols=len(cols))
        F.set_table_width_pct(t, 100)
        F.set_table_borders(t, size=0)
        F.set_table_cell_margins(t, 0, 0, 0, 160)
        if self.rtl_doc:
            F.set_table_bidi(t)
        for i, (blocks, ratio) in enumerate(zip(cols, ratios)):
            cell = t.rows[0].cells[i]
            cell.width = Pt(self.content_width_pt * ratio)
            for child in blocks:
                self._block_safe(cell, coerce_child(child))
        self._spacer_after(c)

    def _b_two_column(self, c, b):
        self._columns(c, [b.left, b.right], [b.ratio, 1 - b.ratio])

    def _b_three_column(self, c, b):
        n = max(1, len(b.columns))
        self._columns(c, b.columns, [1.0 / n] * n)

    def _b_sidebar(self, c, b):
        r = b.sidebar_ratio
        if b.sidebar_position == "left":
            self._columns(c, [b.sidebar_content, b.main_content], [r, 1 - r])
        else:
            self._columns(c, [b.main_content, b.sidebar_content], [1 - r, r])


def _tint(hex_color: str, amount: float) -> str:
    h = hex_color.lstrip("#")
    r, g, bl = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    r, g, bl = (int(v + (255 - v) * amount) for v in (r, g, bl))
    return f"#{r:02X}{g:02X}{bl:02X}"


def _short_data(data, limit: int = 400) -> str:
    try:
        if isinstance(data, dict):
            s = "; ".join(f"{k}: {v}" for k, v in data.items())
        else:
            s = str(data)
    except Exception:
        return ""
    return s if len(s) <= limit else s[:limit - 3] + "..."


def render_docx(sem: SemanticDocument, theme: Theme, policy=None):
    """Render to DOCX bytes. Returns (bytes, DiagnosticCollector)."""
    from ..policy import DiagnosticCollector, RenderPolicy
    col = DiagnosticCollector(policy or RenderPolicy())
    _policy.check_limit("Block count", len(sem.blocks), col.policy.limits.max_blocks)
    token = _policy.activate(col)
    try:
        renderer = DocxRenderer(sem, theme, col)
        data = renderer.render()
    finally:
        _policy.deactivate(token)
    from ..utils.reproducible import stamp_zip
    return stamp_zip(data, renderer.render_time), col
