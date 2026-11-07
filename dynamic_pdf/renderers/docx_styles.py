"""
Word style sheet compiled from the same DesignTokens the PDF renderer uses.

Every paragraph the DOCX renderer emits uses a *named* Word style (Normal,
Body Text, Title, Subtitle, Heading 1-6, Caption, Quote, List Paragraph,
Code, Note, TOC Heading …) so documents stay editable: changing a style in
Word restyles the whole document.
"""
from __future__ import annotations

from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.shared import Pt, RGBColor

from ..design.tokens import DesignTokens
from ..fonts.manager import font_catalog
from ..schema.theme import Theme
from .docx_fields import set_paragraph_shading, set_style_fonts

# PDF base-14 / bundled names → widely available Word fonts
_WORD_FONT = {
    "Helvetica": "Arial", "Inter": "Arial", "Times-Roman": "Times New Roman",
    "Times": "Times New Roman", "Serif": "Times New Roman", "Courier": "Courier New",
    "Monospace": "Courier New", "JetBrains Mono": "Consolas",
}


def word_font(name: str) -> str:
    return _WORD_FONT.get(name, name)


def rgb(hex_str: str) -> RGBColor:
    h = (hex_str or "#000000").lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        return RGBColor.from_string(h[:6].upper())
    except ValueError:
        return RGBColor(0, 0, 0)


def _style(doc, name: str, kind=WD_STYLE_TYPE.PARAGRAPH, base: str = None):
    styles = doc.styles
    try:
        st = styles[name]
    except KeyError:
        st = styles.add_style(name, kind)
        if base:
            st.base_style = styles[base]
    return st


def configure_styles(doc, tokens: DesignTokens, theme: Theme, rtl: bool) -> None:
    body = word_font(tokens.fonts.body)
    heading = word_font(tokens.fonts.heading)
    mono = word_font(tokens.fonts.mono)
    arabic = tokens.fonts.arabic or "Amiri"
    bidi_lang = "ar-SA"
    c = tokens.colors

    normal = doc.styles["Normal"]
    normal.font.name = body
    normal.font.size = Pt(tokens.body_size)
    normal.font.color.rgb = rgb(c["text_primary"])
    set_style_fonts(normal, body, arabic, bidi_lang, int(tokens.body_size * 2))
    pf = normal.paragraph_format
    pf.space_before = Pt(0)
    pf.space_after = Pt(tokens.paragraph_after)
    pf.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
    natural = font_catalog().get(arabic if rtl else tokens.fonts.body, {}).get("line")
    # Word's "multiple" counts in the font's own line height; the PDF counts in its size
    pf.line_spacing = max(0.9, round(tokens.line_height / natural, 2)) if natural else round(tokens.line_height * 0.87, 2)
    pf.widow_control = True

    bt = _style(doc, "Body Text", base="Normal")
    bt.font.name = body
    bt.paragraph_format.first_line_indent = Pt(tokens.first_line_indent) if tokens.first_line_indent else None
    bt.paragraph_format.space_after = Pt(tokens.paragraph_after)
    bt.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

    for lvl in range(1, 7):
        st = _style(doc, f"Heading {lvl}", base="Normal")
        st.font.name = heading
        st.font.size = Pt(tokens.heading_sizes[lvl - 1])
        st.font.bold = True
        st.font.italic = False
        st.font.color.rgb = rgb(c["text_primary"] if lvl > 1 else c.get("primary", c["text_primary"]))
        set_style_fonts(st, heading, arabic, bidi_lang, int(tokens.heading_sizes[lvl - 1] * 2))
        hp = st.paragraph_format
        hp.space_before = Pt(tokens.heading_before[lvl - 1])
        hp.space_after = Pt(tokens.heading_after[lvl - 1])
        hp.keep_with_next = True
        hp.keep_together = True
        hp.first_line_indent = None

    title = _style(doc, "Title", base="Normal")
    title.font.name = heading
    title.font.size = Pt(tokens.title_size)
    title.font.bold = True
    title.font.color.rgb = rgb(c["text_primary"])
    set_style_fonts(title, heading, arabic, bidi_lang)
    title.paragraph_format.space_after = Pt(10)
    # The default template draws a border under Title; remove for a clean cover
    pPr = title.element.pPr
    if pPr is not None and pPr.find("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}pBdr") is not None:
        pPr.remove(pPr.find("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}pBdr"))

    sub = _style(doc, "Subtitle", base="Normal")
    sub.font.name = body
    sub.font.size = Pt(tokens.body_size * 1.3)
    sub.font.italic = False
    sub.font.color.rgb = rgb(c["text_secondary"])
    set_style_fonts(sub, body, arabic, bidi_lang)

    cap = _style(doc, "Caption", base="Normal")
    cap.font.size = Pt(tokens.caption_size)
    cap.font.italic = False
    cap.font.bold = False
    cap.font.color.rgb = rgb(c["text_muted"])
    set_style_fonts(cap, body, arabic, bidi_lang, int(tokens.caption_size * 2))
    cap.paragraph_format.space_after = Pt(tokens.block_gap)

    note = _style(doc, "Note", base="Normal")
    note.font.size = Pt(tokens.note_size)
    note.font.italic = False
    note.font.color.rgb = rgb(c["text_secondary"])
    set_style_fonts(note, body, arabic, bidi_lang, int(tokens.note_size * 2))

    q = _style(doc, "Quote", base="Normal")
    q.font.italic = True
    q.font.color.rgb = rgb(c["text_secondary"])
    q.paragraph_format.left_indent = Pt(24)
    q.paragraph_format.right_indent = Pt(24)
    q.paragraph_format.space_before = Pt(tokens.block_gap)

    code = _style(doc, "Code", base="Normal")
    code.font.name = mono
    code.font.size = Pt(tokens.code_size)
    code.font.color.rgb = rgb(c["code_text"])
    set_style_fonts(code, mono, mono)
    cp = code.paragraph_format
    cp.space_after = Pt(0)
    cp.space_before = Pt(0)
    cp.line_spacing = 1.0
    cp.first_line_indent = None
    cp.left_indent = Pt(6)
    set_paragraph_shading(_PStyleShim(code), c["code_bg"])

    lp = _style(doc, "List Paragraph", base="Normal")
    lp.paragraph_format.space_after = Pt(max(1.0, tokens.paragraph_after / 3))
    lp.paragraph_format.first_line_indent = None

    toch = _style(doc, "TOC Heading", base="Heading 1")
    toch.paragraph_format.keep_with_next = True
    for lvl in range(1, 4):
        st = _style(doc, f"TOC {lvl}", base="Normal")
        st.paragraph_format.left_indent = Pt(14 * (lvl - 1))
        st.paragraph_format.space_after = Pt(2)
        st.font.bold = lvl == 1

    link = _style(doc, "Hyperlink", WD_STYLE_TYPE.CHARACTER)
    link.font.color.rgb = rgb(c.get("link", c["primary"]))
    link.font.underline = True

    tc = _style(doc, "Table Text", base="Normal")
    tc.paragraph_format.space_after = Pt(0)
    tc.paragraph_format.first_line_indent = None
    tc.font.size = Pt(max(8.0, tokens.body_size - 1))


class _PStyleShim:
    """Lets paragraph-level XML helpers operate on a style's pPr."""

    def __init__(self, style):
        self._p = _PPrHolder(style.element)


class _PPrHolder:
    def __init__(self, el):
        self._el = el

    def get_or_add_pPr(self):
        return self._el.get_or_add_pPr()
