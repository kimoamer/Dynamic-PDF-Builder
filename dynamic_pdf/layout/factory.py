"""
Block → Flowable factory.
Applies professional report typography standards:
  • Paragraph first-line indent (APA 0.5in)
  • Per-heading-level spacing
  • Drop Cap on first paragraph after heading
  • Inline Markdown → ReportLab XML
  • Error-safe: every branch wrapped in try/except
"""
import re
import unicodedata
import html as html_mod
import contextvars
import copy
from functools import lru_cache
from typing import Optional
from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (
    Paragraph as _RLParagraph, ListFlowable, ListItem, Spacer, PageBreak,
    Table, TableStyle, Image, KeepTogether,
)
from reportlab.lib.colors import HexColor
from reportlab.lib.units import inch
from reportlab.platypus.flowables import Flowable
from reportlab.platypus.tableofcontents import TableOfContents as _RLTableOfContents

from ..schema.theme import Theme
from ..fonts import get_font_name
from ..fonts.manager import current_arabic_face
from ..utils.errors import BlockRenderError, DynamicPDFError
from .. import policy as _diag
from ..assets import load_image as _load_image


# Glyph-safe markers: available in the standard PDF fonts (no missing-glyph boxes)
BULLET_CHARS = ["\u2022", "\u2013", "\u00b7", "\u2022"]      # •, –, ·, •
# Checkbox glyphs come from the bundled JetBrains Mono (□ U+25A1, ✓ U+2713)
CHECK_ON = '<font name="JetBrains Mono">\u2713</font>'
CHECK_OFF = '<font name="JetBrains Mono">\u25a1</font>'


# ═══════════════════════ RTL Detection ═══════════════════════

def _is_rtl(text: str) -> bool:
    """Paragraph direction: first strong character (UAX #9), see core.normalize."""
    from ..core.normalize import is_rtl_text
    return is_rtl_text(re.sub(r"\]\([^)]*\)", "]", text or ""))   # ignore link targets


_ARABIC_RE = re.compile("[\u0600-\u06FF\u0750-\u077F]")
# base letters + presentation forms produced by reshaping
_ARABIC_SCRIPT_RE = re.compile("[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]")


_RESHAPER = None


@lru_cache(maxsize=8192)
def _reshape(text: str) -> str:
    """Arabic contextual shaping in *logical* order. Diacritics (harakat) are
    kept — they are content (arabic_reshaper deletes them by default)."""
    global _RESHAPER
    try:
        import arabic_reshaper
    except ImportError:
        return text
    if _RESHAPER is None:
        _RESHAPER = arabic_reshaper.ArabicReshaper(configuration={"delete_harakat": False})
    return _RESHAPER.reshape(text)


def _apply_rtl(text: str, base_dir: Optional[str] = None) -> str:
    """Shaping + bidi in *visual* order, for single-line text drawn directly on
    the canvas (headers, footers, outline/TOC entries). Paragraph text must
    stay logical — ``Paragraph`` below reorders each laid-out line."""
    shaped = _reshape(text)
    try:
        from bidi.algorithm import get_display
    except ImportError:
        return shaped
    return get_display(shaped, base_dir=base_dir) if base_dir else get_display(shaped)


_BIDI_RE = re.compile("[\u0590-\u08FF\uFB1D-\uFDFF\uFE70-\uFEFF]")


def _visual_order(text: str, base_dir: str):
    """UAX #9 reordering of one line: [(logical index, displayed char)] in
    visual (left-to-right) order, mirrored where required."""
    from bidi import algorithm as A
    storage = A.get_empty_storage()
    storage["base_level"] = A.PARAGRAPH_LEVELS[base_dir]
    storage["base_dir"] = base_dir
    A.get_embedding_levels(text, storage)
    for i, ch in enumerate(storage["chars"]):
        ch["idx"] = i
    A.explicit_embed_and_overrides(storage, False)
    A.resolve_weak_types(storage, False)
    A.resolve_neutral_types(storage, False)
    A.resolve_implicit_levels(storage, False)
    A.reorder_resolved_levels(storage, False)
    A.apply_mirroring(storage, False)
    return [(c["idx"], c["ch"]) for c in storage["chars"]]


def _visual_line(line, kind: int, base: str):
    """A laid-out paragraph line with its content in visual order. Line breaking
    happened in logical order; only the drawing order changes."""
    if kind == 0:
        extra, words = line[0], line[1]
        text = " ".join(words)
        if not _BIDI_RE.search(text):
            return line
        vis = "".join(ch for _, ch in _visual_order(text, base))
        return (extra, vis.split(" ")) + tuple(line[2:])
    frags = list(line.words)
    owner, chars = [], []
    for fi, f in enumerate(frags):
        for ch in getattr(f, "text", "") or "":
            chars.append(ch)
            owner.append(fi)
    text = "".join(chars)
    if not _BIDI_RE.search(text):
        return line
    lo, hi = 0, len(text)
    while lo < hi and text[lo] == " ":       # end-of-line spaces would move to the
        lo += 1                                # visual start and shift aligned text
    while hi > lo and text[hi - 1] == " ":
        hi -= 1
    runs = []
    for idx, ch in _visual_order(text[lo:hi], base):
        fi = owner[lo + idx]
        if runs and runs[-1][0] == fi:
            runs[-1][1].append(ch)
        else:
            runs.append((fi, [ch]))
    empty = [f for f in frags if not (getattr(f, "text", "") or "")]   # anchors, callbacks
    return line.clone(words=empty + [frags[fi].clone(text="".join(cs)) for fi, cs in runs])


_TAG_ATTRS = ("_dpb_role", "_dpb_level", "_dpb_key", "_dpb_cell", "_dpb_alt", "_dpb_block")


def _keep_the_authors_hyphen() -> None:
    """ReportLab joins the halves of a word it broke with ``_shyUnsplit``, which drops any hyphen
    that ends the first half. That is right for a hyphen it added and wrong for the author's own:
    "by-" and "product" came back as "byproduct" when a paragraph with inline markup ran onto
    the next page. A hyphen ReportLab added is already taken off before the halves are joined,
    so joining plain strings keeps what is there.

    ReportLab has one such function for the whole process, so the correction is in force only
    while one of this library's paragraphs is being laid out (``_laying_out``): a host
    application's own ReportLab documents behave exactly as they did."""
    import reportlab.platypus.paragraph as rl
    original = getattr(rl, "_shyUnsplit", None)
    if original is None or getattr(original, "_dpb", False):
        return

    def unsplit(s, ss=None):
        if _laying_out.get() and ss and type(s) is str and not hasattr(ss, "_shyIndices"):
            return s + ss
        return original(s, ss)
    unsplit._dpb = True
    rl._shyUnsplit = unsplit


_laying_out: contextvars.ContextVar = contextvars.ContextVar("dynamic_pdf_laying_out", default=False)
_keep_the_authors_hyphen()


class Paragraph(_RLParagraph):
    """ReportLab ``Paragraph`` with bidirectional text drawn correctly.

    Text stays in logical order for measuring, line breaking and splitting;
    each laid-out line is reordered for display (UAX #9) only when drawn, so
    multi-line Arabic reads top-to-bottom and right-to-left. The base
    direction is the paragraph's first strong character and is inherited by
    the pieces of a split paragraph. Text without RTL characters is untouched.
    """

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._bidi_base()          # decide while frags are plain fragments

    @staticmethod
    def _frags_text(frags) -> str:
        out = []
        for f in frags or []:
            if isinstance(f, (list, tuple)):     # after wrap: [width, (frag, text), ...]
                out.extend(x[1] for x in f[1:] if isinstance(x, tuple) and len(x) > 1
                           and isinstance(x[1], str))
                out.append(" ")
            else:
                out.append(getattr(f, "text", "") or "")
        return "".join(out)

    def _bidi_base(self):
        base = self.__dict__.get("_dpb_base", False)
        if base is False:
            txt = self._frags_text(getattr(self, "frags", None))
            base = None
            if _BIDI_RE.search(txt):
                from ..core.normalize import is_rtl_text
                base = "R" if is_rtl_text(txt) else "L"
            self._dpb_base = base
        return base

    def wrap(self, availWidth, availHeight):
        token = _laying_out.set(True)
        try:
            return super().wrap(availWidth, availHeight)
        finally:
            _laying_out.reset(token)

    def split(self, availWidth, availHeight):
        base = self._bidi_base()
        token = _laying_out.set(True)
        try:
            parts = super().split(availWidth, availHeight)
        finally:
            _laying_out.reset(token)
        tagged = {k: v for k, v in self.__dict__.items() if k in _TAG_ATTRS}
        if "_dpb_role" in tagged:                # the pieces are one element of the structure tree
            from .tagging import _key
            tagged["_dpb_key"] = _key(self)
        for p in parts:
            if isinstance(p, Paragraph):
                p._dpb_base = base
                p.__dict__.update(tagged)
        return parts

    def drawOn(self, canvas, x, y, _sW=0):
        from .tagging import draw_tagged
        return draw_tagged(self, canvas, lambda: super(Paragraph, self).drawOn(canvas, x, y, _sW))

    # a justified line is left at its natural spacing when each gap would grow by more than this (in ems)
    LOOSE_EM = 0.5

    def _loose_lines(self, bl) -> dict:
        """Lines justification would tear apart (the line before a long e-mail address or URL that
        cannot break): {index: extra space}. They are set at natural spacing from the start edge,
        as a last line is; the long word itself is left whole, so it copies intact."""
        if bl is None or self.style.alignment != TA_JUSTIFY:
            return {}
        out = {}
        for i, ln in enumerate(bl.lines[:-1]):
            if bl.kind == 0:
                extra, gaps = ln[0], len(ln[1]) - 1
            else:
                extra, gaps = getattr(ln, "extraSpace", 0), getattr(ln, "wordCount", 0) - 1
                if getattr(ln, "lineBreak", False):
                    continue
            if gaps > 0 and extra / gaps > self.LOOSE_EM * self.style.fontSize:
                out[i] = extra
        return out

    @staticmethod
    def _natural(ln, kind):
        if kind == 0:
            return (0,) + tuple(ln[1:])
        ln = copy.copy(ln)
        ln.lineBreak = True                      # ReportLab sets such a line without stretching
        return ln

    def drawPara(self, debug=0):
        base = self._bidi_base()
        bl = getattr(self, "blPara", None)
        loose = self._loose_lines(bl)
        if (base is None or bl is None) and not loose:
            return super().drawPara(debug)
        logical = bl.lines
        had = "_offsets" in self.__dict__
        saved = self.__dict__.get("_offsets")
        try:
            lines = [self._natural(ln, bl.kind) if i in loose else ln for i, ln in enumerate(logical)]
            bl.lines = [_visual_line(ln, bl.kind, base) for ln in lines] if base else lines
            if base == "R" and self.style.alignment == TA_JUSTIFY and logical:
                self._offsets = self._rtl_justify_offsets(bl, saved)
                # ReportLab sets a line it does not stretch (one ending in a line break, or a loose
                # one) flush left; in right-to-left text it belongs at the right
                for i, ln in enumerate(lines[:-1]):
                    if i in loose:
                        self._offsets[i] += loose[i]
                    elif bl.kind == 1 and getattr(ln, "lineBreak", False):
                        self._offsets[i] += max(0.0, getattr(ln, "extraSpace", 0))
            return super().drawPara(debug)
        finally:
            bl.lines = logical
            if had:
                self._offsets = saved
            else:
                self.__dict__.pop("_offsets", None)

    def _rtl_justify_offsets(self, bl, existing):
        """ReportLab justifies as if every line ran left to right: the first-line indent lands
        on the left and the short last line sits flush left. A right-to-left paragraph needs
        both on the right, so each line is moved by its own offset; breaking is untouched."""
        n = len(bl.lines)
        base = list(existing or [0])
        base += (n - len(base)) * [base[-1]]
        out = list(base)
        indent = self.style.firstLineIndent or 0
        out[0] -= indent                                 # the indent belongs at the right edge
        if not getattr(self, "_JustifyLast", False):
            last = bl.lines[-1]
            extra = last[0] if bl.kind == 0 else getattr(last, "extraSpace", 0)
            out[-1] += max(0.0, extra)                   # a short last line ends at the right
        return out


def _plain_markup(text: str) -> str:
    """Literal text (no Markdown) as Paragraph markup: shaped Arabic in logical
    order, XML-escaped, every character routed to a font that has it."""
    if _ARABIC_RE.search(text or ""):
        text = _reshape(text)
    # Paragraph collapses runs of spaces; keep literal spacing (e.g. "1  Title")
    text = re.sub(r" {2,}", lambda m: "\u00a0" * len(m.group(0)), text or "")
    return _glyph_fallback(html_mod.escape(text, quote=False))


# ═══════════════════════ Inline Markdown ═══════════════════════

_SAFE_TAGS = ("b", "i", "u", "strike", "sup", "sub", "super", "br")
_SAFE_LINK_SCHEMES = ("http://", "https://", "mailto:", "#")


def _restore_safe_tags(text: str) -> str:
    """Re-enable a small allowlist of attribute-free inline tags after escaping."""
    for tag in _SAFE_TAGS:
        text = re.sub(rf'&lt;(/?){tag}\s*(/?)&gt;', rf'<\1{tag}\2>', text, flags=re.IGNORECASE)
    return text


def _safe_href(url: str) -> Optional[str]:
    u = html_mod.unescape(url).strip()
    if u.lower().startswith(_SAFE_LINK_SCHEMES):
        return html_mod.escape(u, quote=True)
    return None


def _link_sub(m) -> str:
    label, url = m.group(1), m.group(2)
    href = _safe_href(url)
    if href is None:
        return label  # keep the text, drop the unsafe target
    return f'<a href="{href}" color="#1a73e8">{label}</a>'


def _i18n_label(key, lang="en"):
    from ..i18n import label
    return label(key, lang)


def _label(key):
    from .. import policy as _p
    return _i18n_label(key, getattr(_p.current(), "language", "en"))


# what joins or styles an emoji in a font that shapes sequences; here each would draw as a box or a swatch:
# the variation selectors, the skin tones, and a joiner between two pictographs (never one in Arabic text)
_EMOJI_GLUE = re.compile("[\ufe0e\ufe0f\U0001F3FB-\U0001F3FF]|(?<=[\u2190-\u2bff\U0001F000-\U0001FAFF\ufe0f])\u200d"
                         "(?=[\u2190-\u2bff\U0001F000-\U0001FAFF])")


def _glyph_fallback(text: str) -> str:
    from ..qa.glyphs import needs_fallback
    out, run_font, buf = [], None, []
    in_tag = False
    arabic = bool(_ARABIC_RE.search(text))
    for ch in _EMOJI_GLUE.sub("", text):
        if ch == "<":
            in_tag = True
        if in_tag or ch.isascii():
            font = None
        elif _ARABIC_SCRIPT_RE.match(ch):
            font = current_arabic_face()          # Arabic runs always get the Arabic face
        elif unicodedata.bidirectional(ch) in ("R", "AL", "AN"):
            font = None
        else:
            # a sign the Latin face has may be missing from the Arabic face of a right-to-left paragraph (™)
            font = needs_fallback(ch) or (needs_fallback(ch, current_arabic_face()) if arabic else None)
        if ch == ">":
            in_tag = False
        if font != run_font:
            if buf:
                out.append(f'<font name="{run_font}">{"".join(buf)}</font>' if run_font else "".join(buf))
            buf, run_font = [], font
        buf.append(ch)
    if buf:
        out.append(f'<font name="{run_font}">{"".join(buf)}</font>' if run_font else "".join(buf))
    return "".join(out)


def _md_inline(text: str) -> str:
    """Convert Markdown inline syntax to ReportLab Paragraph XML.
    Handles: **bold**, *italic*, `code`, ~~strike~~, [link](url),
    ==highlight==, <sup>, <sub>, smart quotes, em-dash, footnote refs.
    Automatically applies RTL reshaping for Arabic text.

    All input is escaped first, so author text can never inject ReportLab
    markup (e.g. ``<img src=...>`` or ``<a href="javascript:...">``); only a
    small allowlist of attribute-free tags is re-enabled and link targets are
    restricted to http(s)/mailto/anchors.
    """
    if not text:
        return ""
    from ..core.numbering import resolve_refs
    text = resolve_refs(text, lambda label, anchor: (f"[{label.replace('[', '(').replace(']', ')')}](#{anchor})"
                                                     if anchor else label))
    # Arabic is shaped here in logical order; Paragraph reorders each laid-out
    # line for display (reordering before line breaking reversed line order)
    if _ARABIC_RE.search(text):
        text = _reshape(text)
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # Inline code spans and backslash escapes ("\*" is a literal "*", as in CommonMark and
    # the DOCX) are protected from further inline processing; whichever starts first wins
    codes: list = []
    escapes: list = []

    def _stash(m):
        if m.group(1) is None:
            escapes.append(m.group(2))
            return f"\x01{len(escapes) - 1}\x01"
        codes.append(m.group(1))
        return f"\x00{len(codes) - 1}\x00"
    text = re.sub(r'`([^`]+?)`|\\(&lt;|&gt;|&amp;|[!-/:-@\[-`{-~])', _stash, text)
    text = _restore_safe_tags(text)
    text = _review_marks(text)
    # Markdown line breaks, as in the DOCX (core.inline): a blank line inside the block or a
    # hard break ("  " or "\" before the newline) starts a new line; a soft break is a space
    text = re.sub(r"\n[ \t]*\n\s*", "<br/>", text)
    text = re.sub(r"(?: {2,}|\\)\n", "<br/>", text)
    # Smart typography
    text = text.replace('---', '\u2014')    # em-dash
    text = text.replace('--', '\u2013')     # en-dash
    text = text.replace('...', '\u2026')    # ellipsis
    # Bold: **text**
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'(?<![\w_])__(.+?)__(?![\w_])', r'<b>\1</b>', text)
    # Italic: *text*
    text = re.sub(r'(?<!\*)\*([^*]+?)\*(?!\*)', r'<i>\1</i>', text)
    # Strikethrough: ~~text~~
    text = re.sub(r'~~(.+?)~~', r'<strike>\1</strike>', text)
    # Links: [text](url)  (footnote refs [^N] are handled below)
    text = re.sub(r'\[([^\]^][^\]]*)\]\(([^)\s]+)(?:\s+&quot;[^&]*&quot;)?\)', _link_sub, text)
    # Coloured text: [text]{red}, [text]{color=#C00 bg=yellow}; anything else in braces stays text
    def _span(m):
        from ..core.inline import span_style
        look = span_style(m.group("a"))
        if look is None:
            return m.group(0)
        attrs = (f' color="{look[0]}"' if look[0] else "") + (f' backColor="{look[1]}"' if look[1] else "")
        return f'<font{attrs}>{m.group("t")}</font>'
    from ..core.inline import SPAN
    text = SPAN.sub(_span, text)
    # Highlight: ==text==
    text = re.sub(r'==(.+?)==', r'<font backColor="#FEF3CD">\1</font>', text)
    # Superscript: <sup>text</sup> or ^text^
    text = re.sub(r'<sup>(.+?)</sup>', r'<super>\1</super>', text)
    text = re.sub(r'(?<!\[)\^([^\^\s][^\^]*?)\^', r'<super>\1</super>', text)
    # Footnote ref: [^N]
    text = re.sub(r'\[\^(\w+)\]', r'<super>\1</super>', text)
    # Characters the standard fonts lack (✓ → ≥ …) are drawn with a bundled
    # face that has them instead of ReportLab's silent wrong-glyph substitution.
    text = _glyph_fallback(text)
    # Restore code spans
    text = re.sub(r'\x00(\d+)\x00',
                  lambda m: f'<font face="Courier" size="9" backColor="#E8E8E8">{codes[int(m.group(1))]}</font>',
                  text)
    return _nest(re.sub(r'\x01(\d+)\x01', lambda m: escapes[int(m.group(1))], text))


# CriticMarkup on escaped text, before "--" becomes a dash and "~~" a strike (core.inline parses the same)
_CRITIC = re.compile(r"\{\+\+(?P<ins>.*?)\+\+\}|\{--(?P<del>.*?)--\}|\{~~(?P<old>.*?)~&gt;(?P<new>.*?)~~\}"
                     r"|\{==(?P<mark>.*?)==\}\{&gt;&gt;(?P<on>.*?)&lt;&lt;\}|\{&gt;&gt;(?P<note>.*?)&lt;&lt;\}", re.S)
_ADDED, _REMOVED, _NOTE = "#1A7F37", "#CF222E", "#8A6D00"


def _review_marks(text: str) -> str:
    """Suggested edits as a review copy shows them: additions underlined in green, removals
    struck through in red, commented text highlighted with the comment after it, small."""
    if "{" not in text:
        return text

    def note(c):
        return f'<font size="7" color="{_NOTE}"> [{c.strip()}]</font>'

    def sub(m):
        g = m.groupdict()
        if g["ins"] is not None:
            return f'<u><font color="{_ADDED}">{g["ins"]}</font></u>'
        if g["del"] is not None:
            return f'<strike><font color="{_REMOVED}">{g["del"]}</font></strike>'
        if g["old"] is not None:
            return (f'<strike><font color="{_REMOVED}">{g["old"]}</font></strike>'
                    f'<u><font color="{_ADDED}">{g["new"]}</font></u>')
        if g["mark"] is not None:
            return f'<font backColor="#FFF2A8">{g["mark"]}</font>{note(g["on"])}'
        return note(g["note"])
    return _CRITIC.sub(sub, text)


_TAG = re.compile(r"<(/?)([a-zA-Z]+)[^<>]*?(/?)>")


def _nest(markup: str) -> str:
    """Tags that cross are closed and opened again so that they nest: ``**a *b** c*`` gives
    ``<b>a <i>b</b> c</i>``, which ReportLab refuses, and one such paragraph stopped the whole
    document. Every tag here is ours (author text is escaped), so a stack is enough."""
    out, stack, pos = [], [], 0
    for m in _TAG.finditer(markup):
        out.append(markup[pos:m.start()])
        pos = m.end()
        closing, name, empty = m.groups()
        if empty:
            out.append(m.group(0))
        elif not closing:
            stack.append((name, m.group(0)))
            out.append(m.group(0))
        elif any(n == name for n, _ in stack):
            again = []
            while stack[-1][0] != name:
                again.append(stack.pop())
                out.append(f"</{again[-1][0]}>")
            stack.pop()
            out.append(m.group(0))
            for item in reversed(again):
                stack.append(item)
                out.append(item[1])
        # a closing tag with nothing open is dropped
    return "".join(out + [markup[pos:]] + [f"</{n}>" for n, _ in reversed(stack)])


def _safe_color(h: str, fallback: str = "#000000") -> HexColor:
    try:
        if isinstance(h, str) and re.fullmatch(r"#[0-9a-fA-F]{3}", h):
            h = "#" + "".join(ch * 2 for ch in h[1:])       # #fff is white: HexColor would read it as 0x000fff
        return HexColor(h)
    except Exception:
        return HexColor(fallback)


# ═══════════════════════ Drop Cap ═══════════════════════

def _strip_markdown(text: str) -> str:
    """Strip markdown/XML markup for plain-text measurement."""
    t = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    t = re.sub(r'(?<!\*)\*([^*]+?)\*(?!\*)', r'\1', t)
    t = re.sub(r'~~(.+?)~~', r'\1', t)
    t = re.sub(r'`([^`]+?)`', r'\1', t)
    t = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', t)
    t = re.sub(r'==(.+?)==', r'\1', t)
    t = re.sub(r'<[^>]+>', '', t)
    t = t.replace('&amp;', '&')
    return t.strip()


class DropCapParagraph(Flowable):
    """Proper drop cap: large first letter with text wrapping around it.

    The first letter is drawn on the canvas at the top-left. The first
    N lines of body text are rendered at a narrower width (beside the letter).
    Remaining lines render at full paragraph width below the letter.
    """

    def __init__(self, first_char, rest_text, cap_font, cap_size, cap_color,
                 body_font, body_size, body_leading, body_color,
                 cap_lines=3, space_after=6.0, cont_style=None):
        super().__init__()
        self.cont_style = cont_style
        self.first_char = first_char
        self.rest_text = rest_text        # plain text (no XML)
        self.cap_font = cap_font
        self.cap_size = cap_size
        self.cap_color = cap_color
        self.body_font = body_font
        self.body_size = body_size
        self.body_leading = body_leading
        self.body_color = body_color
        self.cap_lines = cap_lines
        self.space_after = space_after
        self._lines_narrow = []
        self._lines_full = []
        self._cap_w = 0

    @staticmethod
    def _word_wrap(text, max_width, font, size):
        """Break *text* into lines that fit inside *max_width* points."""
        from reportlab.pdfbase.pdfmetrics import stringWidth
        words = text.split()
        lines, current = [], ""
        for word in words:
            test = f"{current} {word}".strip()
            if stringWidth(test, font, size) <= max_width:
                current = test
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines

    # ── Flowable protocol ─────────────────────────────────────────────

    def wrap(self, availWidth, availHeight):
        from reportlab.pdfbase.pdfmetrics import stringWidth
        self._avail_w = availWidth

        # Measure the drop-cap letter
        self._cap_w = stringWidth(self.first_char, self.cap_font,
                                  self.cap_size) + 6  # 6pt right gap

        # --- word-wrap ---
        narrow_w = availWidth - self._cap_w
        all_narrow = self._word_wrap(self.rest_text, narrow_w,
                                     self.body_font, self.body_size)
        self._lines_narrow = all_narrow[:self.cap_lines]

        # Remaining text re-wrapped at full width
        leftover = " ".join(all_narrow[self.cap_lines:])
        self._lines_full = (
            self._word_wrap(leftover, availWidth,
                            self.body_font, self.body_size)
            if leftover.strip() else []
        )

        # The drop cap always occupies at least cap_lines rows vertically.
        # If the paragraph is short and produces fewer narrow lines, we still
        # must reserve cap_lines rows so that full-width lines don't start
        # inside the cap's visual zone.
        effective_narrow_rows = max(len(self._lines_narrow), self.cap_lines)
        total_lines = effective_narrow_rows + len(self._lines_full)
        cap_visual_h = self.cap_size * 0.82  # approximate visual height
        text_h = total_lines * self.body_leading
        self.height = max(text_h, cap_visual_h) + self.space_after + 2
        self.width = availWidth
        return (self.width, self.height)

    def split(self, availWidth, availHeight):
        """Split across pages: keep the cap + as many lines as fit, continue
        the remaining words as a normal paragraph (no text is dropped)."""
        self.wrap(availWidth, availHeight)
        if self.height <= availHeight:
            return [self]
        fit = int((availHeight - self.space_after - 2) // self.body_leading)
        if fit <= self.cap_lines:
            return []   # not even the cap block fits; move to next page
        lines = self._lines_narrow + self._lines_full
        n_full = fit - max(len(self._lines_narrow), self.cap_lines)
        keep_words = len(" ".join(self._lines_narrow + self._lines_full[:n_full]).split())
        words = self.rest_text.split()
        head = DropCapParagraph(
            self.first_char, " ".join(words[:keep_words]), self.cap_font, self.cap_size,
            self.cap_color, self.body_font, self.body_size, self.body_leading,
            self.body_color, self.cap_lines, self.space_after, self.cont_style)
        tail_text = " ".join(words[keep_words:])
        if not tail_text or not lines:
            return [self]
        style = self.cont_style or ParagraphStyle(
            'DropCapCont', fontName=self.body_font, fontSize=self.body_size,
            leading=self.body_leading, textColor=_safe_color(self.body_color))
        cont = ParagraphStyle('DropCapCont', parent=style, firstLineIndent=0, spaceBefore=0)
        parts = [head, Paragraph(html_mod.escape(tail_text), cont)]
        if "_dpb_role" in self.__dict__:         # tagged PDF: both pieces are one paragraph
            from .tagging import _key
            tagged = {k: v for k, v in self.__dict__.items() if k in _TAG_ATTRS}
            tagged["_dpb_key"] = _key(self)
            for p in parts:
                p.__dict__.update(tagged)
        return parts

    def draw(self):
        c = self.canv
        c.saveState()

        # Y of the first text baseline (relative to bottom of flowable)
        y_first = self.height - self.body_leading - self.space_after * 0.3

        # ── Draw the drop-cap letter ──
        # We want the TOP of the letter (ascender) aligned with the
        # top of the first text line (ascender).  drawString places at
        # baseline, so:  cap_baseline = first_ascender - cap_ascent.
        body_ascent = self.body_size * 0.75
        cap_ascent  = self.cap_size * 0.75
        cap_baseline = (y_first + body_ascent) - cap_ascent

        c.setFillColor(_safe_color(self.cap_color))
        c.setFont(self.cap_font, self.cap_size)
        c.drawString(0, cap_baseline, self.first_char)

        # ── Draw narrow lines (beside the letter) ──
        c.setFillColor(_safe_color(self.body_color))
        c.setFont(self.body_font, self.body_size)
        y = y_first
        for line in self._lines_narrow:
            c.drawString(self._cap_w, y, line)
            y -= self.body_leading

        # ── Draw full-width lines (below the letter) ──
        # Ensure full lines never start above the bottom of the cap zone,
        # even when fewer narrow lines were produced than cap_lines.
        if self._lines_full:
            y_cap_cleared = y_first - self.cap_lines * self.body_leading
            if y > y_cap_cleared:
                y = y_cap_cleared
        for line in self._lines_full:
            c.drawString(0, y, line)
            y -= self.body_leading

        c.restoreState()
        self.spaceAfter = self.space_after


# ═══════════════════════ Custom Flowables ═══════════════════════

class AccentHeading(Flowable):
    """Heading with an accent bar (on the right for RTL).

    The text is laid out by ``Paragraph`` so mixed-script headings are shaped,
    every character is drawn with a font that has it and long headings wrap
    instead of running into the margin; a one-line heading keeps its height."""
    def __init__(self, text, font_name, font_size, text_color, accent_color,
                 accent_width=4, accent_gap=8, space_before=24, space_after=10,
                 rtl=False):
        super().__init__()
        self.text_str = text
        self.font_name = font_name
        self.font_size = font_size
        self.text_color = text_color
        self.accent_color = accent_color
        self.accent_width = accent_width
        self.accent_gap = accent_gap
        self.space_before = space_before
        self.space_after = space_after
        self.rtl = rtl
        self._para = Paragraph(f"<b>{_plain_markup(text)}</b>", ParagraphStyle(
            "AccentHeadingText", fontName=font_name, fontSize=font_size, leading=font_size * 1.25,
            textColor=text_color, alignment=2 if rtl else 0))

    def wrap(self, availWidth, availHeight):
        self.width = availWidth
        tw = max(1.0, availWidth - self.accent_width - self.accent_gap)
        _, ph = self._para.wrap(tw, availHeight)
        self._text_h = ph
        self._bar_h = max(self.font_size * 1.4, ph + self.font_size * 0.15)
        self.height = self._bar_h + self.space_before + self.space_after
        return (self.width, self.height)

    def draw(self):
        c = self.canv
        c.saveState()
        y = self.space_after
        bar_h = self._bar_h
        c.setFillColor(self.accent_color)
        if self.rtl:
            # Accent bar on the RIGHT for RTL
            c.rect(self.width - self.accent_width, y, self.accent_width, bar_h, fill=1, stroke=0)
            x = 0
        else:
            c.rect(0, y, self.accent_width, bar_h, fill=1, stroke=0)
            x = self.accent_width + self.accent_gap
        c.restoreState()
        self._para.drawOn(c, x, y + (bar_h - self._text_h) / 2)


class HorizontalProgressBar(Flowable):
    """Horizontal bar chart row."""
    def __init__(self, label, value, max_value=100, bar_color="#38A169",
                 benchmark=None, delta=None, text_color="#1A1A2E",
                 bg_color="#E2E8F0", font_name="Helvetica", font_size=9,
                 label_width=160, value_width=40, delta_width=40):
        super().__init__()
        self.label = label
        self.value = value
        self.max_value = max_value
        self.bar_color = bar_color
        self.benchmark = benchmark
        self.delta = delta
        self.text_color = text_color
        self.bg_color = bg_color
        self.font_name = font_name
        self.font_size = font_size
        self.label_width = label_width
        self.value_width = value_width
        self.delta_width = delta_width
        self.row_height = 28

    def wrap(self, availWidth, availHeight):
        self.width = availWidth
        self.height = self.row_height
        return (self.width, self.height)

    def draw(self):
        c = self.canv
        c.saveState()
        y_mid = self.height / 2
        bar_h = 14
        bar_y = y_mid - bar_h / 2
        c.setFillColor(_safe_color(self.text_color))
        c.setFont(self.font_name, self.font_size)
        c.drawString(0, y_mid - 4, self.label)
        bar_x = self.label_width
        bar_w = self.width - self.label_width - self.value_width - self.delta_width - 10
        c.setFillColor(_safe_color(self.bg_color))
        c.roundRect(bar_x, bar_y, bar_w, bar_h, 3, fill=1, stroke=0)
        fill_w = max(0, min(bar_w, bar_w * (self.value / self.max_value)))
        c.setFillColor(_safe_color(self.bar_color))
        c.roundRect(bar_x, bar_y, fill_w, bar_h, 3, fill=1, stroke=0)
        if self.benchmark is not None:
            bx = bar_x + bar_w * (self.benchmark / self.max_value)
            c.setStrokeColor(_safe_color("#9CA3AF"))
            c.setLineWidth(2)
            c.line(bx, bar_y - 2, bx, bar_y + bar_h + 2)
        vx = bar_x + bar_w + 8
        c.setFillColor(_safe_color(self.text_color))
        c.setFont(self.font_name, self.font_size + 1)
        c.drawRightString(vx + self.value_width - 5, y_mid - 4, str(int(self.value)))
        if self.delta:
            dx = vx + self.value_width
            is_pos = self.delta.startswith("+")
            c.setFillColor(_safe_color("#38A169" if is_pos else "#E53E3E"))
            c.setFont(self.font_name, self.font_size - 1)
            c.drawString(dx, y_mid - 4, self.delta)
        c.restoreState()


class ScoreDisplay(Flowable):
    """Large score: big number /max + label + sublabel."""
    def __init__(self, score, max_score, label, sublabel, score_color, label_color,
                 font_name="Helvetica", big_size=36, label_size=12, sublabel_size=9):
        super().__init__()
        self.score = score
        self.max_score = max_score
        self.label_str = label
        self.sublabel_str = sublabel
        self.score_color = score_color
        self.label_color = label_color
        self.font_name = font_name
        self.big_size = big_size
        self.label_size = label_size
        self.sublabel_size = sublabel_size

    def wrap(self, availWidth, availHeight):
        self.width = availWidth
        self.height = self.big_size + 30
        return (self.width, self.height)

    def draw(self):
        c = self.canv
        c.saveState()
        c.setFillColor(_safe_color(self.score_color))
        c.setFont(self.font_name, self.big_size)
        ss = str(int(self.score))
        c.drawString(10, 20, ss)
        sw = c.stringWidth(ss, self.font_name, self.big_size)
        c.setFillColor(_safe_color("#718096"))
        c.setFont(self.font_name, self.big_size * 0.4)
        c.drawString(10 + sw + 2, 20 + self.big_size * 0.1, f"/{int(self.max_score)}")
        mw = c.stringWidth(f"/{int(self.max_score)}", self.font_name, self.big_size * 0.4)
        lx = 10 + sw + mw + 20
        c.setFillColor(_safe_color(self.label_color or "#1A1A2E"))
        c.setFont(self.font_name, self.label_size)
        c.drawString(lx, 20 + self.big_size * 0.4, self.label_str)
        if self.sublabel_str:
            c.setFillColor(_safe_color(self.score_color))
            c.setFont(self.font_name, self.label_size + 2)
            c.drawString(lx, 20 + self.big_size * 0.05, self.sublabel_str)
        c.restoreState()


class DividerFlowable(Flowable):
    def __init__(self, color="#CBD5E0", thickness=1.0, style="solid", width=None, align="left"):
        super().__init__()
        self.color_str = color
        self.thickness = thickness
        self.style = style
        self.fixed_width = width
        self.align = align                   # where a line shorter than the space sits: it works in table cells too

    def wrap(self, availWidth, availHeight):
        self.width = availWidth
        self.line_w = min(availWidth, self.fixed_width) if self.fixed_width else availWidth
        self.height = self.thickness + 16
        return (self.width, self.height)

    def draw(self):
        c = self.canv
        c.saveState()
        c.setStrokeColor(_safe_color(self.color_str))
        c.setLineWidth(self.thickness)
        if self.style == "dashed":
            c.setDash([6, 4])
        elif self.style == "dotted":
            c.setDash([1.5, 3])
        x0 = {"right": self.width - self.line_w, "center": (self.width - self.line_w) / 2}.get(self.align, 0)
        c.line(x0, 8, x0 + self.line_w, 8)
        c.restoreState()


class WatermarkFlowable(Flowable):
    """Diagonal text watermark drawn across the available content area."""
    def __init__(self, text, color="#cccccc", opacity=0.1):
        super().__init__()
        self.text = text
        self.color_str = color
        self.opacity = opacity

    def wrap(self, availWidth, availHeight):
        self.width = availWidth
        self.height = availWidth * 0.55
        return (self.width, self.height)

    def draw(self):
        c = self.canv
        c.saveState()
        hc = _safe_color(self.color_str)
        from reportlab.lib.colors import Color
        c.setFillColor(Color(hc.red, hc.green, hc.blue, alpha=self.opacity))
        font_size = min(self.width * 0.15, 72)
        c.setFont("Helvetica-Bold", font_size)
        c.translate(self.width / 2, self.height / 2)
        c.rotate(45)
        c.drawCentredString(0, 0, self.text)
        c.restoreState()


def _render_page_media(block, ctx):
    """Only a ``once`` layer lives at its place in the text; the others are the
    engine's, which draws them on every page they apply to."""
    if block.scope != "once" or getattr(ctx, "page_geometry", None) is None:
        return []
    from ..media import ingest, page_box
    from .media_flow import FlowAnchoredLayer
    asset = ingest(block.src, _diag.current().policy.assets)
    placement = block.placement.model_copy(
        update={"mode": "behind_text" if block.layer == "behind" else "in_front_of_text"})
    return [FlowAnchoredLayer(asset, placement, block.treatment, ctx.page_geometry,
                              *page_box(ctx.page_geometry, placement))]


class ShapeFlowable(Flowable):
    """Draws a vector shape (rect, circle, ellipse, line, arrow, polygon, arc, wedge)."""
    def __init__(self, block, theme):
        super().__init__()
        self.block = block
        self.theme = theme

    def wrap(self, availWidth, availHeight):
        self.width = availWidth
        self.height = self.block.height + 16
        return (self.width, self.height)

    def draw(self):
        c = self.canv
        b = self.block
        fill_c = _safe_color(b.fill_color or "none") if b.fill_color else None
        stroke_c = _safe_color(b.stroke_color or self.theme.colors.primary)

        if b.alignment == "center":
            x = (self.width - b.width) / 2
        elif b.alignment == "right":
            x = self.width - b.width
        else:
            x = 0
        y = 8

        c.saveState()
        c.setStrokeColor(stroke_c)
        c.setLineWidth(b.stroke_width)
        if b.stroke_dash:
            c.setDash(b.stroke_dash)
        if fill_c:
            c.setFillColor(fill_c)

        do_fill = 1 if fill_c else 0
        st = b.shape_type.lower().replace("-", "_")

        if st == "rect":
            c.rect(x, y, b.width, b.height, fill=do_fill, stroke=1)
        elif st == "rounded_rect":
            c.roundRect(x, y, b.width, b.height, b.corner_radius, fill=do_fill, stroke=1)
        elif st == "circle":
            r = min(b.width, b.height) / 2
            c.circle(x + b.width / 2, y + b.height / 2, r, fill=do_fill, stroke=1)
        elif st == "ellipse":
            c.ellipse(x, y, x + b.width, y + b.height, fill=do_fill, stroke=1)
        elif st == "line":
            c.line(x, y + b.height / 2, x + b.width, y + b.height / 2)
        elif st == "arrow":
            tip_x = x + b.width
            mid_y = y + b.height / 2
            arr = b.height * 0.25
            c.line(x, mid_y, tip_x - arr * 1.5, mid_y)
            c.setFillColor(stroke_c)
            p = c.beginPath()
            p.moveTo(tip_x - arr * 1.5, mid_y + arr)
            p.lineTo(tip_x - arr * 1.5, mid_y - arr)
            p.lineTo(tip_x, mid_y)
            p.close()
            c.drawPath(p, fill=1, stroke=0)
        elif st == "polygon" and b.points:
            pts = [(x + pt[0], y + pt[1]) for pt in b.points]
            p = c.beginPath()
            p.moveTo(*pts[0])
            for pt in pts[1:]:
                p.lineTo(*pt)
            p.close()
            c.drawPath(p, fill=do_fill, stroke=1)
        elif st == "arc":
            c.arc(x, y, x + b.width, y + b.height, b.start_angle,
                  b.end_angle - b.start_angle)
        elif st == "wedge":
            c.wedge(x, y, x + b.width, y + b.height, b.start_angle,
                    b.end_angle - b.start_angle, fill=do_fill, stroke=1)

        if b.label:
            # a paragraph, so Arabic is shaped, symbols find a face and a long label wraps; its colour
            # reads on the fill unless one is given
            from .page_system import readable_on
            rtl = _is_rtl(b.label)
            ink = b.label_color or (readable_on(b.fill_color) if b.fill_color else self.theme.colors.text_primary)
            font = _arabic_font(self.theme, bold=True) if rtl else get_font_name(self.theme.typography.body_family, bold=True)
            para = Paragraph(_plain_markup(b.label), ParagraphStyle(
                "ShapeLabel", fontName=font, fontSize=10, leading=16 if rtl else 13, alignment=1, textColor=_safe_color(ink)))
            _, ph = para.wrap(max(b.width - 12, 20), b.height)
            para.drawOn(c, x + 6, y + (b.height - ph) / 2)

        c.restoreState()


def shape_png(block, theme, scale: float = 3.0) -> bytes:
    """The shape exactly as the PDF draws it, as a PNG on a clear ground (for Word, which has no
    flowing vector shapes)."""
    import io
    import pypdfium2 as pdfium
    from reportlab.pdfgen.canvas import Canvas
    flow = ShapeFlowable(block.model_copy(update={"alignment": "left"}), theme)
    edge = (block.stroke_width or 1) + 1              # room for the outline, which straddles the shape's edge
    w, h = flow.wrap(block.width, 10000)
    buf = io.BytesIO()
    canv = Canvas(buf, pagesize=(w + 2 * edge, h))
    flow.drawOn(canv, edge, 0)
    canv.save()
    image = pdfium.PdfDocument(buf.getvalue())[0].render(scale=scale, fill_color=(255, 255, 255, 0)).to_pil()
    out = io.BytesIO()
    image.save(out, "PNG", dpi=(72 * scale, 72 * scale))
    return out.getvalue()


class LegendFlowable(Flowable):
    def __init__(self, items, title=None, layout="horizontal", font_name="Helvetica", font_size=8):
        super().__init__()
        self.items = items
        self.title_str = title
        self.layout = layout
        self.font_name = font_name
        self.font_size = font_size

    def wrap(self, availWidth, availHeight):
        self.width = availWidth
        title_h = (self.font_size + 14) if self.title_str else 0
        if self.layout == "horizontal":
            self.height = title_h + self.font_size + 24
        else:
            self.height = title_h + (self.font_size + 10) * len(self.items) + 10
        return (self.width, self.height)

    def draw(self):
        c = self.canv
        c.saveState()
        y = self.height - 10
        if self.title_str:
            c.setFillColor(_safe_color("#1A1A2E"))
            c.setFont(self.font_name, self.font_size + 3)
            c.drawString(10, y, self.title_str)
            y -= self.font_size + 14
        if self.layout == "horizontal":
            x = 10
            for item in self.items:
                c.setFillColor(_safe_color(item.get("color", "#888")))
                c.circle(x + 5, y + 2, 5, fill=1, stroke=0)
                c.setFillColor(_safe_color("#1A1A2E"))
                c.setFont(self.font_name, self.font_size)
                c.drawString(x + 14, y - 2, item.get("label", ""))
                desc = item.get("description", "")
                if desc:
                    c.setFillColor(_safe_color("#718096"))
                    c.setFont(self.font_name, self.font_size - 1)
                    c.drawString(x + 14, y - 2 - self.font_size, desc)
                x += 100
        else:
            for item in self.items:
                c.setFillColor(_safe_color(item.get("color", "#888")))
                c.circle(15, y + 2, 5, fill=1, stroke=0)
                c.setFillColor(_safe_color("#1A1A2E"))
                c.setFont(self.font_name, self.font_size)
                c.drawString(24, y - 2, item.get("label", ""))
                y -= self.font_size + 10
        c.restoreState()


# ═══════════════════════ Render Context (thread-safe) ═══════════════════════

FRAME_PADDING = 6.0      # ReportLab's default Frame padding, on every side; the engine keeps it


class RenderContext:
    """Thread-safe rendering context passed from LayoutEngine to the factory.

    Replaces the old module-level _ParagraphContext singleton so that
    concurrent renders (e.g., in a web server) cannot leak state.
    """

    def __init__(self, available_width: float = 460.0,
                 section_numbering: bool = False,
                 available_height: Optional[float] = None,
                 language: str = "en"):
        self.language = language
        self.cache = None
        self.available_width = available_width
        self.available_height = available_height
        self.apply_drop_cap_next = False
        self.section_numbering = section_numbering
        self.page_size = (595.28, 841.89)
        self.page_geometry = None          # margins and direction, for page-level media
        self.first_block = False           # the block being built opens the document
        self.last_block = True             # nothing follows the block being built
        self.heading_counters = [0, 0, 0, 0, 0, 0]  # H1–H6
        self.toc_entries: list = []  # (level, text) for TOC

    @property
    def usable_width(self) -> float:
        """Width a flowable is actually offered: the frame less its side padding."""
        return self.available_width - 2 * FRAME_PADDING

    @property
    def usable_height(self) -> Optional[float]:
        """Height a flowable is actually offered: the frame less its top and bottom padding.
        Anything planned to fill a page must plan with this, not with ``available_height``."""
        return None if self.available_height is None else self.available_height - 2 * FRAME_PADDING

    def next_heading_number(self, level: int) -> str:
        """Increment heading counter and return formatted number string."""
        idx = level - 1
        self.heading_counters[idx] += 1
        # Reset deeper levels
        for i in range(idx + 1, 6):
            self.heading_counters[i] = 0
        parts = []
        for i in range(idx + 1):
            if self.heading_counters[i] > 0:
                parts.append(str(self.heading_counters[i]))
        return ".".join(parts)


# ═══════════════════════ Main Factory ═══════════════════════

def create_flowables(block, theme: Theme, ctx: RenderContext = None) -> list:
    """Build flowables for one block.

    Strict mode (default): any failure raises ``BlockRenderError``.
    Permissive mode: failure is recorded as an ``error`` diagnostic and a
    visible marker is rendered in place of the block.
    """
    if ctx is None:
        ctx = RenderContext()  # backward-compat fallback
    try:
        out = _create_inner(block, theme, ctx)
        hints = getattr(block, "hints", None) or {}
        if out and hints.get("keep_with_next"):
            out[-1].keepWithNext = 1      # composer grouping (e.g. intro + its figure)
        elif out and hints.get("keep_tail_with_next") and isinstance(out[-1], Paragraph):
            # only the paragraph's last lines travel with the next block (the
            # page-break logic in the engine splits the paragraph if needed)
            out[-1].keepWithNext = 1
            out[-1]._dpb_keep_tail = int(hints["keep_tail_with_next"])
        if out and hints.get("page_start"):
            from reportlab.platypus.flowables import PageBreakIfNotEmpty
            out.insert(0, PageBreakIfNotEmpty())    # page-break optimizer (layout/breaks.py)
        return out
    except Exception as e:
        btype = getattr(block, "type", type(block).__name__)
        if isinstance(e, BlockRenderError):
            err_obj = e
        elif isinstance(e, DynamicPDFError):
            err_obj = BlockRenderError(btype, f"{type(e).__name__}: {e}", e)
        else:
            err_obj = BlockRenderError(btype, f"{type(e).__name__}: {e}", e)
        _diag.current().fail("block_render_failed", str(err_obj), err_obj)
        err = ParagraphStyle('Err', fontSize=8, textColor=HexColor(theme.colors.error))
        return [Paragraph(html_mod.escape(f"[Block Error ({btype}): {type(e).__name__}: {e}]"), err)]


def _body_style(theme: Theme, indent: bool = True) -> ParagraphStyle:
    sp = theme.spacing
    return ParagraphStyle(
        'Body',
        fontName=get_font_name(theme.typography.body_family),
        fontSize=theme.typography.base_size,
        leading=theme.typography.base_size * theme.typography.line_height,
        textColor=_safe_color(theme.colors.text_primary),
        spaceBefore=sp.paragraph_spacing_before,
        spaceAfter=sp.paragraph_spacing_after,
        firstLineIndent=sp.first_line_indent if indent else 0,
        alignment=4,  # JUSTIFY body text; last lines keep natural alignment
        allowWidows=0,      # no single last line at the top of a page
        allowOrphans=0,     # no single first line at the bottom of a page
    )


@lru_cache(maxsize=32)
def _hyphenation_lang(language: str) -> str:
    try:
        import pyphen
    except ImportError:
        return ""
    return pyphen.language_fallback((language or "en").replace("-", "_")) or ""


def _hyphenated(style: ParagraphStyle) -> ParagraphStyle:
    """Justified left-to-right body paragraphs break long words at the document language's
    hyphenation points (pyphen), so word gaps stay even. Only the body-paragraph branches call
    this: headings, tables, code and right-to-left text are never hyphenated."""
    lang = _hyphenation_lang(getattr(_diag.current(), "language", "en"))
    if not lang or style.alignment != TA_JUSTIFY:
        return style
    return ParagraphStyle(style.name + "Hy", parent=style, hyphenationLang=lang,
                          hyphenationMinWordLength=8)   # fewer breaks, equally even gaps on the corpus


def _arabic_font(theme: Theme, bold: bool = False) -> str:
    """Return the Arabic-capable font name, falling back to body/heading font."""
    if theme.typography.arabic_family:
        name = get_font_name(theme.typography.arabic_family, bold=bold)
        if name not in ("Helvetica", "Helvetica-Bold", "Helvetica-Oblique"):
            return name
    return get_font_name(theme.typography.body_family, bold=bold)


def _rtl_para(text: str, base_style: ParagraphStyle, theme: Theme,
              bold: bool = False) -> 'Paragraph':
    """Return a right-aligned Paragraph with Arabic font when text is RTL."""
    if _is_rtl(text):
        sty = ParagraphStyle(
            f'RTL_{id(base_style)}',
            parent=base_style,
            fontName=_arabic_font(theme, bold=bold),
            alignment=2,       # RIGHT
            firstLineIndent=0,
        )
        return Paragraph(_md_inline(text), sty)
    return Paragraph(_md_inline(text), base_style)


def _create_inner(block, theme: Theme, ctx: RenderContext = None) -> list:
    if ctx is None:
        ctx = RenderContext()
    bs = _body_style(theme)
    bs_no_indent = _body_style(theme, indent=False)
    sp = theme.spacing
    btype = block.type

    # a paper sets the paragraph under a heading flush left: the heading already marks its start
    flush = btype == "paragraph" and getattr(ctx, "after_heading", False) and theme.decorations.paper
    ctx.after_heading = btype == "heading"

    # ─── Reset drop cap flag for any non-paragraph block ───
    if btype not in ("heading", "paragraph") and ctx.apply_drop_cap_next:
        ctx.apply_drop_cap_next = False

    # ─── Heading ───
    if btype == "heading":
        ctx.apply_drop_cap_next = True   # next paragraph gets drop cap
        idx = max(0, min(5, block.level - 1))
        from ..design.tokens import heading_size
        fs = heading_size(theme, block.level)   # honours heading_hN_size tokens
        h_before = sp.heading_spacing_before[idx]
        h_after = sp.heading_spacing_after[idx]
        text_color = _safe_color(block.color or theme.colors.text_primary)
        accent_color = _safe_color(theme.decorations.heading_accent_bar_color or theme.colors.accent)
        is_rtl_heading = _is_rtl(block.text)
        head_font = (_arabic_font(theme, bold=True) if is_rtl_heading
                     else get_font_name(theme.typography.heading_family, bold=True))

        # Section numbering
        display_text = block.text
        if (ctx.section_numbering or block.numbered) and not (block.hints or {}).get("unnumbered"):
            from ..i18n import written_number
            number = written_number(ctx.next_heading_number(block.level), block.text)
            display_text = f"{number}  {block.text}"

        # Collect for TOC
        ctx.toc_entries.append((block.level, block.text))

        toc_entry = (block.level, _strip_markdown(display_text), block.id)
        if theme.decorations.heading_accent_bar and block.level <= 3:
            hf = AccentHeading(
                text=display_text,
                font_name=head_font,
                font_size=fs, text_color=text_color, accent_color=accent_color,
                accent_width=theme.decorations.heading_accent_bar_width,
                accent_gap=theme.decorations.heading_accent_bar_gap,
                space_before=h_before, space_after=h_after,
                rtl=is_rtl_heading,
            )
        else:
            sty = ParagraphStyle(
                f'H{block.level}',
                fontName=head_font,
                fontSize=fs, leading=fs * 1.3,
                textColor=text_color,
                spaceBefore=h_before, spaceAfter=h_after,
                alignment=2 if is_rtl_heading else 0,
                keepWithNext=1,
            )
            hf = Paragraph(_md_inline(display_text), sty)
        hints = block.hints or {}
        if hints.get("opener") or hints.get("scale"):
            from .art import designed_heading
            hf = designed_heading(block, display_text, theme, fs, block.color or theme.colors.text_primary,
                                  is_rtl_heading, h_before, h_after)
        hf.keepWithNext = 1          # never strand a heading at a page bottom
        hf._toc_entry = toc_entry    # consumed by the doc template (TOC/outline/links)
        if hints.get("drop") and ctx.available_height:
            from reportlab.platypus.flowables import PageBreakIfNotEmpty
            return [PageBreakIfNotEmpty(), Spacer(1, ctx.available_height * float(hints["drop"])), hf]
        if hints.get("break_before") == "if_not_empty":
            from reportlab.platypus.flowables import PageBreakIfNotEmpty
            return [PageBreakIfNotEmpty(), hf]
        if hints.get("break_before"):
            return [PageBreak(), hf]   # section opens a page (editorial / QA fix)
        if hints.get("min_space_before") and ctx.available_height:
            from reportlab.platypus import CondPageBreak
            # start the section on a new page when too little of this one remains
            return [CondPageBreak(ctx.available_height * float(hints["min_space_before"])), hf]
        return [hf]

    # ─── Paragraph ───
    if btype == "paragraph" and (block.hints or {}).get("lead"):
        ctx.apply_drop_cap_next = False
        size = theme.typography.base_size * 1.2
        lead = ParagraphStyle('Lead', parent=bs, fontSize=size,
                              leading=size * theme.typography.line_height,
                              firstLineIndent=0, spaceAfter=sp.paragraph_spacing_after * 1.5,
                              textColor=_safe_color(theme.colors.text_secondary),
                              alignment=4)
        if _is_rtl(block.text):
            return [Paragraph(_md_inline(block.text), lead)]
        # display text sets ragged: justified, a short lead stretches its gaps or breaks a word
        return [Paragraph(_md_inline(block.text), ParagraphStyle('LeadRagged', parent=lead, alignment=TA_LEFT))]
    if btype == "paragraph":
        raw = block.text
        is_rtl = _is_rtl(raw)
        text = _md_inline(raw)
        body_font = get_font_name(theme.typography.body_family)
        if is_rtl and theme.typography.arabic_family:
            body_font = get_font_name(theme.typography.arabic_family)

        # ── Drop Cap (proper typographic wrap-around) ──
        if ctx.apply_drop_cap_next and theme.decorations.drop_cap_enabled and not is_rtl:
            ctx.apply_drop_cap_next = False
            plain = _strip_markdown(raw)
            # Drop caps draw plain text; only use them when no inline
            # semantics (links, emphasis, code) would be lost.
            has_markup = (_md_inline(raw) != html_mod.escape(raw, quote=False)
                          or "&" in raw or "<" in raw)
            dec = theme.decorations
            # the cap needs text to wrap around it and past it: on a line or two it stands alone
            per_line = (ctx.available_width or 440) / (theme.typography.base_size * 0.5)
            if len(plain) >= (dec.drop_cap_lines + 1) * per_line and not has_markup:
                first_char = plain[0]
                rest_text  = plain[1:]
                cap_font  = get_font_name(theme.typography.heading_family, bold=True)
                cap_size  = theme.typography.base_size * dec.drop_cap_font_size_ratio
                cap_color = dec.drop_cap_color or theme.colors.drop_cap
                return [DropCapParagraph(
                    first_char=first_char,
                    rest_text=rest_text,
                    cap_font=cap_font,
                    cap_size=cap_size,
                    cap_color=cap_color,
                    body_font=body_font,
                    body_size=theme.typography.base_size,
                    body_leading=theme.typography.base_size * theme.typography.line_height,
                    body_color=theme.colors.text_primary,
                    cap_lines=dec.drop_cap_lines,
                    space_after=sp.paragraph_spacing_after,
                    cont_style=bs,
                )]

        # ── RTL alignment ──
        if is_rtl:
            # no first-line indent in Arabic, as the DOCX renderer and the RTL recipes already do
            rtl_style = ParagraphStyle('RTL', parent=bs, alignment=4, fontName=body_font, firstLineIndent=0)
            return [Paragraph(text, rtl_style)]
        return [Paragraph(text, _hyphenated(bs_no_indent if flush else bs))]

    # ─── Rich Text ───
    if btype == "rich_text":
        size = block.font_size or theme.typography.base_size
        sty = ParagraphStyle(
            'Rich', parent=bs_no_indent,
            fontSize=size, leading=max(bs_no_indent.leading, size * 1.25),     # large type needs its own line height
            textColor=_safe_color(block.color or theme.colors.text_primary),
            alignment={'left': 0, 'center': 1, 'right': 2, 'justify': 4}.get(block.alignment, 0),
        )
        text = _md_inline(block.text)
        if block.bold:
            text = f"<b>{text}</b>"
        if block.italic:
            text = f"<i>{text}</i>"
        return [Paragraph(text, sty)]

    # ─── Note ───
    if btype == "note":
        sty = ParagraphStyle(
            'Note', parent=bs_no_indent,
            fontSize=theme.typography.base_size * theme.typography.note_size_ratio,
            textColor=_safe_color(theme.colors.text_muted),
        )
        return [Paragraph(_md_inline(block.text), sty)]

    # ─── Bullet List ───
    if btype == "bullet_list":
        list_rtl = any(
            _is_rtl(i if isinstance(i, str) else i.text)
            for i in block.items
        )
        # Normalize items to ListItemModel
        from ..schema.blocks import ListItemModel as LIM
        items = [LIM(text=i) if isinstance(i, str) else i for i in block.items]
        if list_rtl:
            return _render_rtl_list(items, 'bullet', theme, bs_no_indent, sp)
        if (block.hints or {}).get("columns") == 2:
            return _two_column_list(items, 'bullet', theme, bs_no_indent, sp, ctx, 1)
        return [_build_list_flowable(items, 'bullet', theme, bs_no_indent, sp)]

    # ─── Numbered List ───
    if btype == "numbered_list":
        list_rtl = any(
            _is_rtl(i if isinstance(i, str) else i.text)
            for i in block.items
        )
        from ..schema.blocks import ListItemModel as LIM
        items = [LIM(text=i) if isinstance(i, str) else i for i in block.items]
        if list_rtl:
            return _render_rtl_list(items, 'numbered', theme, bs_no_indent, sp,
                                    start=block.start)
        if (block.hints or {}).get("columns") == 2:
            return _two_column_list(items, '1', theme, bs_no_indent, sp, ctx, block.start)
        return [_build_list_flowable(items, '1', theme, bs_no_indent, sp,
                                     start=block.start)]

    # ─── Table ───
    if btype == "table":
        return _render_table(block, theme, bs_no_indent, ctx)

    # ─── Code ───
    if btype == "code":
        return _render_code(block, theme)

    # ─── Image ───
    if btype == "image":
        return _fit_figure(_render_image(block, theme, ctx.available_width, ctx.available_height, ctx), block)

    # ─── Chart ───
    if btype == "chart":
        from ..core.numbering import exhibit_label
        number, anchor = exhibit_label(block)
        # a numbered chart carries its title as a caption under it, as a numbered image does
        drawn = block.model_copy(update={"title": None}) if number and block.title else block
        figure = _cached_figure(ctx, drawn, theme, lambda: _render_chart(drawn, theme))
        if number:
            figure = _chart_caption(figure, block, number, anchor, theme, bs_no_indent)
        return _fit_figure(figure, block)

    # ─── Diagram ───
    if btype == "diagram":
        return _fit_figure(_cached_figure(ctx, block, theme, lambda: _render_diagram(block, theme)), block)

    # ─── Math ───
    if btype == "math":
        drawn = _cached_figure(ctx, block, theme, lambda: _render_math(block, theme))
        if block.equation_number and drawn and not isinstance(drawn[0], Paragraph):
            return _numbered_equation(drawn, block.equation_number, theme, ctx.available_width)
        return drawn

    # ─── Callout ───
    if btype == "callout":
        return _render_callout(block, theme, bs_no_indent)

    # ─── Quote ───
    if btype == "quote":
        if (block.hints or {}).get("statement"):
            from .art import statement
            return statement(block, theme, ctx)
        return _render_quote(block, theme, ctx)

    if btype in ("image_text_panel", "figure_matrix", "paired_row_columns"):
        from ..renderers.compositions import render_composition
        return render_composition(block, theme, ctx)

    # ─── Layout archetypes (opt-in page compositions) ───
    if btype in ("section_opener", "performance_page", "parallel_ledger"):
        from ..renderers.archetypes import render_archetype
        return render_archetype(block, theme, ctx)

    # ─── Metrics ───
    if btype == "metric_row":
        if (block.hints or {}).get("style"):
            from .art import metric_strip
            return metric_strip(block, theme, ctx.available_width, block.hints["style"])
        return _render_metrics(block, theme, ctx.available_width)

    # ─── Progress Bar ───
    if btype == "progress_bar":
        return _render_progress(block, theme)

    # ─── Score Display ───
    if btype == "score_display":
        return _render_score(block, theme)

    # ─── Legend ───
    if btype == "legend":
        items = [{"label": i.label, "color": i.color, "description": i.description or ""} for i in block.items]
        return [LegendFlowable(items, title=block.title, layout=block.layout,
                               font_name=get_font_name(theme.typography.body_family),
                               font_size=theme.typography.base_size * 0.8)]

    # ─── Badge ───
    if btype == "badge":
        bg = block.bg_color or theme.colors.accent
        fg = block.color or theme.colors.text_on_primary
        sty = ParagraphStyle('Badge', fontName=get_font_name(theme.typography.body_family, bold=True),
                             fontSize=block.font_size, textColor=_safe_color(fg),
                             backColor=_safe_color(bg), borderPadding=4, spaceAfter=6)
        return [Paragraph(block.text, sty)]

    # ─── Divider ───
    if btype == "divider":
        return [DividerFlowable(color=block.color or theme.colors.border,
                                thickness=block.thickness, style=block.style)]

    # ─── Spacer ───
    if btype == "spacer":
        return [Spacer(1, block.height)]

    # ─── Page Break ───
    if btype == "page_break":
        return [PageBreak()]

    # ─── Cover Page ───
    if btype == "cover_page":
        return _render_cover(block, theme, ctx)

    # ─── Mermaid ───
    if btype == "mermaid":
        from ..renderers.mermaid import render_mermaid
        return render_mermaid(block, theme)

    # ─── Two Column ───
    if btype == "two_column":
        return _render_columns(block, theme, 2, ctx)

    # ─── Three Column ───
    if btype == "three_column":
        return _render_columns(block, theme, 3, ctx)

    # ─── Checklist ───
    if btype == "checklist":
        return _render_checklist(block, theme, bs_no_indent)

    # ─── Definition List ───
    if btype == "definition_list":
        return _render_definition_list(block, theme, bs_no_indent)

    # ─── Footnote ───
    if btype == "footnote":
        return _render_footnote(block, theme, bs_no_indent)

    # ─── Abstract ───
    if btype == "abstract":
        return _render_abstract(block, theme, bs_no_indent)

    # ─── Bibliography ───
    if btype == "bibliography":
        return _render_bibliography(block, theme, bs_no_indent)

    # ─── Citation ───
    if btype == "citation":
        return [Paragraph(f"<super>[{block.key}]</super>", bs_no_indent)]

    # ─── Signature ───
    if btype == "signature":
        return _render_signature(block, theme, ctx.available_width if ctx else None)

    # ─── Timeline ───
    if btype == "timeline":
        return _render_timeline(block, theme, bs_no_indent)

    # ─── Sidebar ───
    if btype == "sidebar":
        return _render_sidebar(block, theme, ctx)

    # ─── TOC ───
    if btype == "table_of_contents":
        return _render_toc_placeholder(block, theme, ctx)

    # ─── Watermark ───
    if btype == "watermark":
        return [WatermarkFlowable(text=block.text, color=block.color, opacity=block.opacity)]

    # ─── Page media and sections ───
    if btype == "page_media":
        return _render_page_media(block, ctx)
    if btype == "page_section":
        from reportlab.platypus.flowables import PageBreakIfNotEmpty
        from .media_flow import SectionMark
        return ([PageBreakIfNotEmpty()] if block.new_page else []) + [SectionMark(block.name)]

    # ─── Shape ───
    if btype == "shape":
        return [ShapeFlowable(block, theme)]

    # ─── QR Code ───
    if btype == "qrcode":
        return _render_qrcode(block, theme)

    # ─── Introduction Page ───
    if btype == "introduction_page":
        return _render_introduction_page(block, theme, ctx)

    return [Paragraph(f"[Unsupported: {btype}]", bs_no_indent)]


# ═══════════════════════ Renderer Helpers ═══════════════════════


def _flatten_list(items, list_type, start=1, depth=0):
    """Flatten nested ListItemModels into (text, marker, depth) rows."""
    rows = []
    for idx, item in enumerate(items):
        if isinstance(item, str):
            text, children, checked = item, [], None
        else:
            text, children, checked = item.text, item.children, item.checked
        if checked is not None:
            marker = CHECK_ON if checked else CHECK_OFF
        elif list_type == 'bullet':
            marker = BULLET_CHARS[min(depth, 3)]
        else:
            marker = str((start if depth == 0 else 1) + idx)
        rows.append((text, marker, depth))
        if children:
            rows.extend(_flatten_list(children, list_type, 1, depth + 1))
    return rows


def _render_rtl_list(items, list_type, theme, bs, sp, start=1):
    """Render a bullet/numbered list with RTL layout (marker on right).

    Each item is a row of its own: a nested item moves its marker in with its text, by an
    empty column at the right as wide as its depth, so the marker stays beside its words."""
    marker_style = ParagraphStyle('RTL_Marker', parent=bs, firstLineIndent=0,
                                  fontName=_arabic_font(theme),
                                  alignment=1)  # CENTER aligned
    item_style = ParagraphStyle('RTL_LI', parent=bs, firstLineIndent=0,
                                fontName=_arabic_font(theme), alignment=2)  # RIGHT aligned
    marker_col_w = 30
    from ..i18n import written_number
    out = []
    for item_text, marker_text, depth in _flatten_list(items, list_type, start):
        marker_text = written_number(marker_text, item_text)     # as the document writes its figures
        # RTL: text on LEFT, marker on RIGHT, then the depth's indent
        row = [Paragraph(_md_inline(item_text), item_style), Paragraph(marker_text, marker_style)]
        widths = [None, marker_col_w]
        if depth:
            row.append("")
            widths.append(depth * sp.list_indent)
        t = Table([row], colWidths=widths, style=TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ]))
        t.hAlign = 'RIGHT'
        out.append(t)
    if out:
        out[-1].spaceAfter = sp.block_gap
    return out


def _render_table(block, theme, bs, ctx=None):
    hints = block.hints or {}
    # Column order follows the table's own language (majority of header cells),
    # so bilingual tables led by English are not mirrored.
    sample = [str(x) for x in (block.headers or (block.rows[0] if block.rows else [])) if str(x).strip()]
    from ..core.normalize import is_rtl_table
    tbl_rtl = is_rtl_table([re.sub(r"\]\([^)]*\)", "]", x) for x in sample])     # link targets do not vote
    if hints.get("font_size"):
        bs = ParagraphStyle('TBase', parent=bs, fontSize=hints["font_size"],
                            leading=hints["font_size"] * 1.3)
    ncols = max([len(block.headers or [])] + [len(r) for r in block.rows] + [1])
    numeric = set(hints.get("numeric_cols") or [])
    pad = float(hints.get("cell_padding", 10))
    # a paper rules its tables (top, under the header, bottom) and fills nothing
    design = hints.get("design") or ("booktabs" if theme.decorations.paper and not block.header_bg else None)
    body_font = _arabic_font(theme, bold=True) if tbl_rtl else get_font_name(theme.typography.body_family, bold=True)
    cell_font = _arabic_font(theme) if tbl_rtl else get_font_name(theme.typography.body_family)
    tbl_align = 2 if tbl_rtl else 0

    h_sty = ParagraphStyle('TH', parent=bs, firstLineIndent=0,
                           fontName=body_font,
                           textColor=_safe_color(block.header_text_color or (
                               theme.colors.text_primary if design else theme.colors.text_on_primary)),
                           alignment=tbl_align)
    c_sty = ParagraphStyle('TD', parent=bs, firstLineIndent=0, fontName=cell_font, alignment=tbl_align)
    h_num = ParagraphStyle('THn', parent=h_sty, alignment=2)
    c_num = ParagraphStyle('TDn', parent=c_sty, alignment=2)

    def _row(cells, sty, num_sty):
        cells = list(cells) + [""] * (ncols - len(cells))
        out = [Paragraph(_md_inline(str(c)), num_sty if ci in numeric else sty)
               for ci, c in enumerate(cells)]
        return list(reversed(out)) if tbl_rtl else out
    data = [_row(block.headers or [], h_sty, h_num)] if block.headers else []
    totals = set(hints.get("total_rows") or [])       # rows the author labelled total: set bold, ruled above
    t_sty = ParagraphStyle('TDt', parent=c_sty, fontName=body_font)
    t_num = ParagraphStyle('TDtn', parent=t_sty, alignment=2)
    for ri, row in enumerate(block.rows):
        data.append(_row(row, t_sty, t_num) if ri in totals else _row(row, c_sty, c_num))
    # Footer row (summary/totals)
    if block.footer_row:
        f_sty = ParagraphStyle('TF', parent=bs, firstLineIndent=0,
                               fontName=body_font, alignment=tbl_align)
        data.append(_row(block.footer_row, f_sty, ParagraphStyle('TFn', parent=f_sty, alignment=2)))
    hbg = _safe_color(block.header_bg or theme.colors.primary)
    cmds = [
        ('BACKGROUND', (0, 0), (-1, 0), hbg),
        ('TEXTCOLOR', (0, 0), (-1, 0), _safe_color(block.header_text_color or theme.colors.text_on_primary)),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7 if pad >= 9 else 4),
        ('TOPPADDING', (0, 0), (-1, -1), 7 if pad >= 9 else 4),
        ('LEFTPADDING', (0, 0), (-1, -1), pad),
        ('RIGHTPADDING', (0, 0), (-1, -1), pad),
        ('GRID', (0, 0), (-1, -1), 0.5, _safe_color(theme.colors.border)),
    ]
    if theme.decorations.table_row_alternating:
        for i in range(1, len(data)):
            if i % 2 == 0:
                cmds.append(('BACKGROUND', (0, i), (-1, i), _safe_color(theme.colors.surface)))
    if block.footer_row:
        cmds.append(('BACKGROUND', (0, -1), (-1, -1), _safe_color(theme.colors.surface)))
        cmds.append(('LINEABOVE', (0, -1), (-1, -1), 1.5, _safe_color(theme.colors.text_primary)))
    if design:
        from .art import table_commands
        cmds = table_commands(design, theme, len(data), ncols, bool(block.headers), bool(block.footer_row),
                              pad, hints.get("current_col"), tbl_rtl)
    head = 1 if block.headers else 0
    from ..core.table_types import row_spans
    raw_rows = [list(r) for r in block.rows] + ([list(block.footer_row)] if block.footer_row else [])
    for ri, (first, last, content) in row_spans(block).items():
        r_vis = ri + head
        a, b = (ncols - 1 - last, ncols - 1 - first) if tbl_rtl else (first, last)
        sty = t_sty if (ri in totals or ri >= len(block.rows)) else c_sty
        text = str(raw_rows[ri][content]) if content < len(raw_rows[ri]) else ""
        for vc in range(a, b + 1):              # what the joined cells held moves to the one that shows it
            data[r_vis][vc] = Paragraph("", sty)
        data[r_vis][a] = Paragraph(_md_inline(text), sty)
        cmds.append(('SPAN', (a, r_vis), (b, r_vis)))
    for ri in sorted(totals):
        if 0 <= ri < len(block.rows):
            cmds.append(('LINEABOVE', (0, ri + head), (-1, ri + head), 0.9, _safe_color(theme.colors.text_primary)))
    avail = ctx.available_width if ctx else None
    col_widths = block.column_widths
    if not col_widths and hints.get("col_fractions") and avail:
        fr = hints["col_fractions"]
        total = sum(fr) or 1.0
        col_widths = [f / total * (avail - 1.0) for f in fr]     # exact fit, never overflow
    elif col_widths and avail and sum(col_widths) > avail:
        col_widths = [w * avail / sum(col_widths) for w in col_widths]   # never overflow the frame
    centred = False
    if design == "booktabs" and not block.column_widths and avail:
        # a small table in a paper is as wide as its content and centred, not stretched to the measure
        from ..design.measure import column_metrics
        size = float(hints.get("font_size") or theme.typography.base_size)
        _, nats = column_metrics([str(h) for h in block.headers or []], [[str(c) for c in r] for r in block.rows],
                                 theme.typography.body_family, size, padding=pad * 1.2 + 22)
        if len(nats) == ncols and sum(nats) <= avail * 0.8:
            col_widths, centred = list(nats), True
    if col_widths and tbl_rtl:
        col_widths = list(reversed(col_widths))
    from .tagging import new_key
    tkey = new_key()
    for ri, row in enumerate(data):              # structure tree: Table > TR > TH/TD, reading order
        for ci, cell in enumerate(row):
            cell._dpb_cell = (tkey, ri, len(row) - 1 - ci if tbl_rtl else ci, ri == 0 and bool(block.headers))
    t = Table(data, colWidths=col_widths, style=TableStyle(cmds),
              repeatRows=1 if block.headers else 0)
    t.hAlign = 'CENTER' if centred else 'RIGHT' if tbl_rtl else 'LEFT'
    t.spaceAfter = theme.spacing.block_gap * (1.6 if theme.decorations.paper else 1.0)
    flowables = []
    from ..core.numbering import exhibit_label
    number, anchor = exhibit_label(block)
    label = number or ""
    if block.caption:
        label = f"{label}: {block.caption}" if label else block.caption
    if label:
        cap_font = _arabic_font(theme) if _is_rtl(label) else get_font_name(theme.typography.body_family)
        cap_align = 2 if _is_rtl(label) else 0
        cap_sty = ParagraphStyle('Cap', parent=bs, firstLineIndent=0,
                                 fontSize=theme.typography.base_size * theme.typography.caption_size_ratio,
                                 textColor=_safe_color(theme.colors.text_muted), spaceAfter=4,
                                 fontName=cap_font, alignment=cap_align)
        if theme.decorations.paper:
            cap_sty = _paper_caption(theme, bs, label, after=6)
            if number and block.caption:           # "Table 1:" in bold, then the caption
                label = f"**{number}:** {block.caption}"
        cap = Paragraph(_md_inline(label), cap_sty)
        cap.keepWithNext = 1          # caption never separated from its table
        if anchor:
            from ..core.inline import plain_text
            cap._exhibit_entry = ("table", plain_text(label), anchor)
        flowables.append(cap)
    flowables.append(t)
    if hints.get("keep_together"):
        return [KeepTogether(flowables)]
    return flowables


def _render_code(block, theme):
    import html as html_mod
    try:
        from pygments import lex
        from pygments.lexers import get_lexer_by_name, guess_lexer
        from pygments.styles import get_style_by_name
        from pygments.util import ClassNotFound
        try:
            lexer = get_lexer_by_name(block.language)
        except ClassNotFound:
            try:
                lexer = guess_lexer(block.code)
            except ClassNotFound:
                lexer = get_lexer_by_name("text")
        pname = "monokai" if "dark" in theme.name or "claude" in theme.name or "corporate" in theme.name else "default"
        pstyle = get_style_by_name(pname)
        parts = []
        for ttype, value in lex(block.code, lexer):
            color = None
            ct = ttype
            while ct is not None:
                sd = pstyle.style_for_token(ct)
                if sd and sd.get("color"):
                    color = sd["color"]
                    break
                ct = ct.parent
            val = html_mod.escape(value).replace("\n", "<br/>").replace(" ", "&nbsp;")
            if color:
                parts.append(f'<font color="#{color}">{val}</font>')
            else:
                parts.append(f'<font color="{theme.colors.code_text}">{val}</font>')
        html_code = "".join(parts)
    except ImportError:
        html_code = f'<font color="{theme.colors.code_text}">{html_mod.escape(block.code).replace(chr(10), "<br/>")}</font>'

    # ── Line numbers & highlight ──
    if block.line_numbers or block.highlight_lines:
        lines = html_code.split('<br/>')
        max_ln = len(str(len(lines)))
        new_lines = []
        highlight_set = set(block.highlight_lines) if block.highlight_lines else set()
        for i, line in enumerate(lines, 1):
            ln_str = str(i).rjust(max_ln)
            ln_prefix = f'<font color="#6272A4">{ln_str} \u2502 </font>'
            if i in highlight_set:
                new_lines.append(f'<font backColor="#44475a">{ln_prefix}{line}  </font>')
            else:
                new_lines.append(f'{ln_prefix}{line}')
        html_code = '<br/>'.join(new_lines)

    flowables = []
    # Filename header bar (VS Code style)
    if block.filename:
        fn_sty = ParagraphStyle('CodeFn', fontName=get_font_name(theme.typography.mono_family),
                                fontSize=theme.typography.base_size * theme.typography.caption_size_ratio,
                                textColor=_safe_color("#A0AEC0"),
                                backColor=_safe_color("#2D2D3F"), borderPadding=6, spaceAfter=0)
        fn = Paragraph(html_mod.escape(block.filename), fn_sty)
        fn.keepWithNext = 1           # the filename label never ends a page alone
        flowables.append(fn)
    elif block.caption:
        cap_sty = ParagraphStyle('CCap', fontName=get_font_name(theme.typography.mono_family),
                                 fontSize=theme.typography.base_size * theme.typography.caption_size_ratio,
                                 textColor=_safe_color("#A0AEC0"),
                                 backColor=_safe_color("#2D2D3F"), borderPadding=6, spaceAfter=0)
        cap = Paragraph(_md_inline(block.caption), cap_sty)
        cap.keepWithNext = 1
        flowables.append(cap)
    code_size = (block.hints or {}).get("font_size") or theme.typography.base_size * 0.85
    code_sty = ParagraphStyle(
        'Code', fontName=get_font_name(theme.typography.mono_family),
        fontSize=code_size,
        leading=code_size * 1.4,
        textColor=_safe_color(theme.colors.code_text),
        backColor=_safe_color(theme.colors.code_bg),
        borderPadding=12, spaceAfter=theme.spacing.block_gap + 6, wordWrap='CJK',
        spaceBefore=12,     # the background box extends 12pt above; keep it off the heading
    )
    flowables.append(Paragraph(html_code, code_sty))
    return flowables


def _image_treatment(block):
    """The block's treatment, with the older ``border`` and ``shadow`` switches."""
    from ..schema.media import ImageTreatment
    t = block.treatment or ImageTreatment()
    updates = {}
    if block.border and not t.border_width:
        updates["border_width"] = 0.75
    if block.shadow:
        updates["shadow"] = True
    return t.model_copy(update=updates) if updates else t


def _figure_text(block, theme, width=None):
    """Caption and source lines of a figure."""
    from ..i18n import label as _i18n
    lang = _diag.current().language
    size = theme.typography.base_size * theme.typography.caption_size_ratio
    out = []
    from ..core.numbering import exhibit_label
    number, anchor = exhibit_label(block)
    text = number or ""
    if block.caption:
        text = f"{text}: {block.caption}" if text else block.caption
    if text:
        rtl = _is_rtl(text)
        sty = ParagraphStyle('ImgCap', fontSize=size, leading=size * (1.5 if rtl else 1.2),
                             fontName=get_font_name(theme.typography.arabic_family or "Amiri") if rtl
                             else "Helvetica",
                             textColor=_safe_color(theme.colors.text_muted),
                             alignment=2 if rtl and width else 1, spaceAfter=theme.spacing.block_gap)
        if theme.decorations.paper:              # as the paper's table and chart captions
            shown = f"**{number}:** {block.caption}" if number and block.caption else text
            out.append(Paragraph(_md_inline(shown), _paper_caption(theme, _body_style(theme, indent=False), text,
                                                                   before=2, after=theme.spacing.block_gap)))
        else:
            out.append(Paragraph(_md_inline(text) if rtl else f"<i>{_md_inline(text)}</i>", sty))
        if anchor:
            from ..core.inline import plain_text
            out[-1]._exhibit_entry = ("figure", plain_text(text), anchor)
    if block.source:
        note = f"{_i18n('source', lang)}: {block.source}"
        rtl = _is_rtl(note)
        sty = ParagraphStyle('ImgSrc', fontSize=size * 0.9, leading=size * (1.4 if rtl else 1.15),
                             fontName=get_font_name(theme.typography.arabic_family or "Amiri") if rtl
                             else "Helvetica",
                             textColor=_safe_color(theme.colors.text_muted),
                             alignment=2 if rtl and width else 1, spaceAfter=theme.spacing.block_gap)
        if out:
            out[-1].style = out[-1].style.clone('ImgCap2', spaceAfter=2)
        out.append(Paragraph(_md_inline(note), sty))
    return out


def _render_image(block, theme, available_width=460, available_height=None, ctx=None):
    from ..media import check_resolution, flow_box, ingest, normal_mode, page_box, PageGeometry
    from .media_flow import FlowAnchoredLayer, MediaFlowable
    collector = _diag.current()
    asset = ingest(block.src, collector.policy.assets)
    treatment = _image_treatment(block)
    placement = block.placement
    mode = normal_mode(placement) if placement else "inline"
    geo = getattr(ctx, "page_geometry", None)
    if mode in ("behind_text", "in_front_of_text") and geo is not None:
        box = page_box(geo, placement)
        if placement.relative_to == "content":
            box = (available_width * (placement.width_ratio or 1.0),
                   flow_box(asset, available_width * (placement.width_ratio or 1.0), None,
                            available_width, None, None, treatment)[1])
        elif not placement.height_ratio and treatment.fit == "contain":
            box = (box[0], box[0] / asset.aspect)
        return [FlowAnchoredLayer(asset, placement, treatment, geo, *box)]

    avail_w = available_width
    bleed = None
    if placement and placement.bleed and geo is not None:
        avail_w = geo.width
        bleed = geo.left
    want_w = block.width
    if placement and placement.width_ratio:
        want_w = avail_w * placement.width_ratio
    want_h = block.height
    if placement and placement.height_ratio and available_height:
        want_h = available_height * placement.height_ratio
    avail_h = None
    if available_height:
        # leave room for a caption so figure + caption fit on one page
        ratio = (block.hints or {}).get("max_height_ratio") or (
            0.85 if (block.caption or block.figure_number) else 0.98)
        avail_h = available_height * ratio
    w, h = flow_box(asset, want_w, want_h, avail_w, avail_h, None, treatment)
    side = block.alignment
    if placement and placement.horizontal != "center":
        from ..media import physical_side
        side = physical_side(placement.horizontal, bool(geo and geo.rtl))
    img = MediaFlowable(asset, w, h, treatment, side.upper(), bleed, block.alt_text or "")
    check_resolution(asset, img.fitted, collector, f"Image {block.alt_text or ''}".strip())
    img.spaceAfter = theme.spacing.block_gap
    flowables = [img, *_figure_text(block, theme)]
    if len(flowables) > 1:
        # keep figure and caption on the same page
        return [KeepTogether(flowables)]
    return flowables


class FitFigure(Flowable):
    """A figure that may shrink (down to ``min_scale``) to fit the space left on
    the page instead of jumping to the next page and leaving a gap. Captions
    passed as ``reserve`` keep their room so figure + caption stay together."""

    def __init__(self, inner, min_scale: float = 0.8, reserve=None):
        super().__init__()
        self.inner = inner
        self.min_scale = max(0.5, min(1.0, float(min_scale)))
        self.reserve = reserve or []
        self.hAlign = getattr(inner, "hAlign", "CENTER")
        self._scale = 1.0

    def wrap(self, aW, aH):
        w, h = self.inner.wrapOn(self.canv, aW, aH) if hasattr(self, "canv") else self.inner.wrap(aW, aH)
        res = 0.0
        for r in self.reserve:
            res += r.wrap(aW, aH)[1] + r.getSpaceBefore() + r.getSpaceAfter()
        # reserve the caption *and* this figure's own spacing (+1pt slack) so the
        # figure group really fits in what is left of the page
        room = aH - res - self.inner.getSpaceBefore() - self.inner.getSpaceAfter() - 1.0
        self._scale = 1.0
        if h > room and room >= h * self.min_scale and h > 0:
            self._scale = room / h
        self.width, self.height = w * self._scale, h * self._scale
        return self.width, self.height

    def min_height(self, aW):
        w, h = self.inner.wrap(aW, 1e6)
        return h * self.min_scale

    def getSpaceBefore(self):
        return self.inner.getSpaceBefore()

    def getSpaceAfter(self):
        return self.inner.getSpaceAfter()

    def draw(self):
        c = self.canv
        c.saveState()
        c.scale(self._scale, self._scale)
        self.inner.drawOn(c, 0, 0)
        c.restoreState()


class FigureGroup(KeepTogether):
    """Figure + caption kept together, measured at the *actual* remaining
    height (ReportLab's KeepTogether measures with unlimited height, which
    would hide a FitFigure's ability to shrink)."""

    def wrap(self, aW, aH):
        W, H, first = 0.0, 0.0, 0.0
        for i, f in enumerate(self._content):
            w, h = f.wrapOn(self.canv, aW, aH)
            W = max(W, w)
            H += h + (f.getSpaceBefore() if i else 0) + f.getSpaceAfter()
            if i == 0:
                first = h
        self._H, self._H0, self._wrapInfo = H, first, (aW, aH)
        return W, 0xffffff


def _fit_figure(flowables, block):
    """Wrap the figure in ``FitFigure`` when the composer allows shrinking."""
    min_scale = (getattr(block, "hints", None) or {}).get("shrink_to_fit")
    if not min_scale or not flowables:
        return flowables
    out = list(flowables)
    target = out
    if len(out) == 1 and isinstance(out[0], KeepTogether):
        out[0] = FigureGroup(list(out[0]._content))     # a copy: the cached figure must stay unwrapped
        target = out[0]._content
    for k, f in enumerate(target):
        if not isinstance(f, (Paragraph, Spacer)) and getattr(f, "bleed_left", None) is None:
            captions = [c for c in target[k + 1:] if isinstance(c, Paragraph)]
            target[k] = FitFigure(f, min_scale, captions)
            break
    return out


def _two_column_list(items, bullet_type, theme, bs, sp, ctx, start=1):
    """Short list items in two balanced columns, reading order column by column."""
    half = (len(items) + 1) // 2
    left = _build_list_flowable(items[:half], bullet_type, theme, bs, sp, start=start)
    right = _build_list_flowable(items[half:], bullet_type, theme, bs, sp,
                                 start=start + half if bullet_type == '1' else start)
    w = (ctx.available_width if ctx else 460) / 2
    t = Table([[left, right]], colWidths=[w, w], style=TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))
    t.hAlign = 'LEFT'
    t.spaceAfter = sp.block_gap
    return [t]


def _chart_caption(figure: list, block, number: str, anchor, theme, bs) -> list:
    """The figure with "Figure N: title" set under it in place of its trailing gap, kept on one page."""
    text = f"{number}: {block.title}" if block.title else number
    if theme.decorations.paper:
        style = _paper_caption(theme, bs, text, before=2, after=theme.spacing.block_gap * 1.4)
        text = f"**{number}:** {block.title}" if block.title else f"**{number}**"
    else:
        size = theme.typography.base_size * theme.typography.caption_size_ratio
        style = ParagraphStyle('ChartCap', parent=bs, fontSize=size, leading=size * 1.3, alignment=1,
                               textColor=_safe_color(theme.colors.text_muted), spaceAfter=theme.spacing.block_gap)
    cap = Paragraph(_md_inline(text), style)
    if anchor:
        from ..core.inline import plain_text
        cap._exhibit_entry = ("figure", plain_text(text), anchor)
    return [KeepTogether([f for f in figure if not isinstance(f, Spacer)] + [cap])]     # as a captioned image


def _cached_figure(ctx, block, theme, build):
    """Reuse expensive figure flowables (matplotlib → drawing) across the
    candidate renders of one composition (request-local cache)."""
    cache = getattr(ctx, "cache", None)
    if cache is None:
        return build()
    key = ("fig", block.model_dump_json(exclude={"hints"}), theme.colors.model_dump_json(),
           theme.spacing.block_gap, theme.decorations.paper, (block.hints or {}).get("figure_scale"),
           str((block.hints or {}).get("figure_size")))
    if key not in cache:
        cache[key] = build()
    # fresh copies: a render sets keep-with-next and size state on its flowables, which must not
    # carry into the next render that reuses this figure
    import copy
    return [copy.copy(f) for f in cache[key]]


def _render_chart(block, theme):
    from ..renderers.chart import render_chart
    return render_chart(block, theme)


def _render_diagram(block, theme):
    from ..renderers.diagram import render_diagram
    return render_diagram(block, theme)


def _numbered_equation(drawn: list, number: int, theme, width: float) -> list:
    """A displayed equation centred, its number at the far edge, as papers set it."""
    side = 40.0
    style = ParagraphStyle("EqNo", fontName=get_font_name(theme.typography.body_family),
                           fontSize=theme.typography.base_size, alignment=TA_RIGHT,
                           textColor=_safe_color(theme.colors.text_primary))
    rtl = getattr(_diag.current(), "language", "en") == "ar"
    cells = [Paragraph(f"({number})", style), drawn[0], ""] if rtl else ["", drawn[0], Paragraph(f"({number})", style)]
    t = Table([cells], colWidths=[side, max(width - 2 * side, 10), side])
    t.setStyle(TableStyle([("ALIGN", (1, 0), (1, 0), "CENTER"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                           ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    return [t] + drawn[1:]


def _render_math(block, theme):
    try:
        from ..utils.optional import require_matplotlib
        require_matplotlib()
        import matplotlib.pyplot as plt
        import matplotlib.mathtext as mathtext
        import tempfile, os
        from svglib.svglib import svg2rlg

        # Use a dedicated figure sized to fit the math expression
        from ..renderers.chart import _paper_rc
        with _paper_rc(theme):          # a paper's equations in a Times-like face, as its text
            fig = plt.figure(figsize=(7, 1.2))
            fig.patch.set_alpha(0)
            fig.text(0.5, 0.5, f"${block.latex}$", fontsize=13,
                     ha='center', va='center',
                     usetex=False)          # matplotlib mathtext — no LaTeX install needed

            with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as tf:
                fig.savefig(tf.name, format="svg", bbox_inches="tight",
                            transparent=True, dpi=150)
                tf_name = tf.name
            plt.close(fig)

        drawing = svg2rlg(tf_name)
        os.unlink(tf_name)

        if drawing and drawing.width:
            target_w = min(drawing.width, theme.spacing.page_margin_left * 5)
            scale = target_w / drawing.width
            drawing.width = target_w
            drawing.height = drawing.height * scale
            drawing.transform = (scale, 0, 0, scale, 0, 0)
            drawing.hAlign = 'CENTER'
            return [drawing, Spacer(1, theme.spacing.block_gap)]
        return []
    except Exception as e:
        _diag.current().warn("math_fallback",
                             f"Math rendered as source text ({type(e).__name__}: {e})")
        # Fallback: render as styled monospace text (no raw $ signs)
        mono = ParagraphStyle('MathFallback',
                              fontName=get_font_name(theme.typography.mono_family),
                              fontSize=theme.typography.base_size * 0.9,
                              textColor=_safe_color(theme.colors.text_secondary),
                              spaceAfter=theme.spacing.block_gap,
                              leftIndent=24)
        return [Paragraph(html_mod.escape(block.latex), mono)]


def _render_callout(block, theme, bs):
    variant_colors = {"info": theme.colors.info, "warning": theme.colors.warning,
                      "error": theme.colors.error, "success": theme.colors.success, "tip": theme.colors.tip}
    bar_color = _safe_color(variant_colors.get(block.variant, theme.colors.info))
    bg_map = {"info": "#EBF5FF", "warning": "#FFF8E1", "error": "#FFF0F0",
              "success": "#F0FFF4", "tip": "#F5F0FF"}
    bg_color = _safe_color(bg_map.get(block.variant, "#F7F9FC"))
    from ..schema.theme import ColorPalette
    own = variant_colors.get(block.variant)
    if own and own != getattr(ColorPalette(), block.variant):     # a design's own colour tints its own ground
        from ..design.archetypes import mix
        bg_color = _safe_color(mix(own, "#FFFFFF", 0.92))

    is_rtl = _is_rtl(block.text) or (block.title and _is_rtl(block.title))
    body_font = _arabic_font(theme) if is_rtl else get_font_name(theme.typography.body_family)
    align = 2 if is_rtl else 0  # RIGHT or LEFT

    inner_sty = ParagraphStyle('CalloutInner', parent=bs, firstLineIndent=0, spaceAfter=0,
                               fontSize=theme.typography.base_size * 0.95,
                               fontName=body_font, alignment=align)
    parts = []
    if block.title:
        parts.append(f"<b>{_plain_markup(block.title)}</b><br/>")
    parts.append(_md_inline(block.text))
    inner = Paragraph("".join(parts), inner_sty)

    pad = theme.spacing.callout_padding
    bar_width = theme.decorations.callout_left_bar_width
    style_cmds = [
        ('BACKGROUND', (0, 0), (-1, -1), bg_color),
        ('TOPPADDING', (0, 0), (-1, -1), pad),
        ('BOTTOMPADDING', (0, 0), (-1, -1), pad),
    ]
    if is_rtl:
        # RTL: bar on the RIGHT side, extra padding on right
        style_cmds.append(('LINEAFTER', (-1, 0), (-1, -1), bar_width, bar_color))
        style_cmds.append(('RIGHTPADDING', (0, 0), (-1, -1), pad + 4))
        style_cmds.append(('LEFTPADDING', (0, 0), (-1, -1), pad))
    else:
        style_cmds.append(('LINEBEFORE', (0, 0), (0, -1), bar_width, bar_color))
        style_cmds.append(('LEFTPADDING', (0, 0), (-1, -1), pad + 4))
        style_cmds.append(('RIGHTPADDING', (0, 0), (-1, -1), pad))
    t = Table([[inner]], style=TableStyle(style_cmds))
    t.hAlign = 'LEFT'
    t.spaceAfter = theme.spacing.block_gap
    return [t]


def _render_quote(block, theme, ctx=None):
    """Three looks, chosen by ``style``: a blockquote with a bar of the accent colour along its start
    edge; a pullquote set large under a short rule (the design's statement); an epigraph, small and
    narrow toward the end edge. Each mirrors in right-to-left text; the attribution follows the quote."""
    style = (block.style or "blockquote").lower()
    if style == "pullquote":
        from .art import statement
        return statement(block.model_copy(update={"hints": {**(block.hints or {}), "statement": True}}), theme, ctx)
    is_rtl = _is_rtl(block.text)
    body_font = _arabic_font(theme) if is_rtl else get_font_name(theme.typography.body_family)
    base = theme.typography.base_size
    width = getattr(ctx, "available_width", None) or 460
    epigraph = style == "epigraph"
    size = base * (0.95 if epigraph else 1.05)
    indent = width * 0.42 if epigraph else 0
    q_sty = ParagraphStyle(
        'Quote', fontName=body_font, fontSize=size, leading=size * theme.typography.line_height,
        textColor=_safe_color(theme.colors.text_secondary if epigraph else theme.colors.text_primary),
        leftIndent=0 if is_rtl else indent, rightIndent=indent if is_rtl else 0,
        spaceAfter=4, alignment=2 if is_rtl else 0,
    )
    parts = [p for p in re.split(r"\n[ \t]*\n", block.text) if p.strip()] or [block.text]
    # italic carries the voice in Latin text; Arabic has no italic
    body = [Paragraph(_md_inline(p) if is_rtl else f"<i>{_md_inline(p)}</i>", q_sty) for p in parts]
    if block.attribution:
        attr_rtl = is_rtl or _is_rtl(block.attribution)
        attr = ParagraphStyle('Attr', parent=q_sty, fontSize=base * theme.typography.caption_size_ratio,
                              leading=base * theme.typography.caption_size_ratio * 1.5,
                              textColor=_safe_color(theme.colors.text_muted),
                              fontName=_arabic_font(theme) if attr_rtl else get_font_name(theme.typography.body_family),
                              alignment=(0 if attr_rtl else 2) if epigraph else (2 if attr_rtl else 0), spaceBefore=2)
        body.append(Paragraph(_plain_markup(("" if attr_rtl else "\u2014 ") + block.attribution), attr))
    if epigraph:
        return body + [Spacer(1, theme.spacing.block_gap * 1.5)]
    # the bar is the cell's start border: left, or right in right-to-left text
    bar = ('LINEAFTER', (0, 0), (0, 0), 2.5, _safe_color(theme.colors.accent)) if is_rtl else \
        ('LINEBEFORE', (0, 0), (0, 0), 2.5, _safe_color(theme.colors.accent))
    t = Table([[body]], colWidths=[width], style=TableStyle([
        bar, ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 4 if is_rtl else theme.spacing.quote_indent * 0.6),
        ('RIGHTPADDING', (0, 0), (-1, -1), theme.spacing.quote_indent * 0.6 if is_rtl else 4),
        ('TOPPADDING', (0, 0), (-1, -1), 2), ('BOTTOMPADDING', (0, 0), (-1, -1), 2)]))
    t.hAlign = 'RIGHT' if is_rtl else 'LEFT'
    return [t, Spacer(1, theme.spacing.block_gap)]


def _render_metrics(block, theme, available_width=460):
    base = theme.typography.base_size
    arabic_face = _arabic_font(theme) != get_font_name(theme.typography.body_family)

    def face(text, bold=False, heading=False):
        if _is_rtl(text) or _ARABIC_RE.search(text or ""):
            return _arabic_font(theme, bold=bold)
        fam = theme.typography.heading_family if heading else theme.typography.body_family
        return get_font_name(fam, bold=bold)

    cells = []
    for m in block.metrics:
        lbl_sty = ParagraphStyle('ML', fontName=face(m.label), fontSize=base * theme.typography.caption_size_ratio,
                                 leading=base * theme.typography.caption_size_ratio * 1.5,
                                 textColor=_safe_color(theme.colors.text_muted),
                                 alignment=2 if _diag.current().language == "ar" else 0)
        vsize = base * 2.2
        val_sty = ParagraphStyle('MV', fontName=face(m.value, bold=True, heading=True), fontSize=vsize,
                                 textColor=_safe_color(theme.colors.text_primary),
                                 leading=vsize * (1.85 if face(m.value).startswith("Amiri") else       # Arabic letters
                                                  1.6 if _ARABIC_RE.search(m.value or "") else 1.2),   # reach below the line
                                 spaceBefore=2, spaceAfter=2,
                                 alignment=2 if _diag.current().language == "ar" else 0)
        label = m.label if _ARABIC_RE.search(m.label) else m.label.upper()
        parts = [Paragraph(_md_inline(label), lbl_sty), Paragraph(_md_inline(m.value), val_sty)]
        if m.delta:
            neg = m.delta.strip().startswith(("-", "\u2212", "\u25bc"))
            dc = theme.colors.error if neg else theme.colors.success
            d_sty = ParagraphStyle('MD', fontName=face(m.delta, bold=True), textColor=_safe_color(dc),
                                   fontSize=base * 0.8, leading=base * 1.2,
                                   alignment=2 if _diag.current().language == "ar" else 0)
            parts.append(Paragraph(_md_inline(m.delta), d_sty))
        cells.append(parts)
    w = available_width / max(len(cells), 1)
    t = Table([cells], colWidths=[w] * len(cells), style=TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
    ]))
    t.hAlign = 'LEFT'
    t.spaceAfter = theme.spacing.block_gap * 1.5
    return [t]


def _render_progress(block, theme):
    flowables = []
    if block.title:
        flowables.append(AccentHeading(
            block.title, font_name=get_font_name(theme.typography.heading_family, bold=True),
            font_size=theme.typography.base_size * 1.3,
            text_color=_safe_color(theme.colors.text_primary),
            accent_color=_safe_color(theme.colors.accent),
            accent_width=theme.decorations.heading_accent_bar_width,
            accent_gap=theme.decorations.heading_accent_bar_gap))
    if block.subtitle:
        sub = ParagraphStyle('PSub', fontSize=theme.typography.base_size * theme.typography.caption_size_ratio,
                             textColor=_safe_color(theme.colors.text_muted), spaceAfter=8)
        flowables.append(Paragraph(_md_inline(block.subtitle), sub))
    for item in block.items:
        flowables.append(HorizontalProgressBar(
            label=item.label, value=item.value, max_value=item.max_value,
            bar_color=item.color or theme.colors.success, benchmark=item.benchmark,
            delta=item.delta, text_color=theme.colors.text_primary,
            bg_color=theme.colors.surface,
            font_name=get_font_name(theme.typography.body_family),
            font_size=theme.typography.base_size * 0.9))
    flowables.append(Spacer(1, theme.spacing.block_gap))
    return flowables


def _render_score(block, theme):
    return [
        ScoreDisplay(
            score=block.score, max_score=block.max_score,
            label=block.label, sublabel=block.sublabel,
            score_color=block.score_color or theme.colors.accent,
            label_color=block.label_color or theme.colors.text_primary,
            font_name=get_font_name(theme.typography.heading_family, bold=True)),
        Spacer(1, theme.spacing.block_gap),
    ]


def _render_cover(block, theme, ctx=None):
    if (block.hints or {}).get("title_block"):
        from .cover import title_block
        return title_block(block, theme)
    if ctx is not None and getattr(ctx, "page_geometry", None) is not None:        # every cover is a designed page
        from .cover import designed_cover
        return designed_cover(block, theme, ctx)
    flowables = [Spacer(1, 80)]
    if block.logo:
        try:
            buf, (w, h) = _load_image(block.logo, _diag.current().policy.assets)
        except DynamicPDFError as e:
            _diag.current().fail("asset_failed", f"Cover logo: {e}", e)
            buf = None
        if buf is not None:
            if w > 200:
                h = h * (200 / w)
                w = 200
            img = Image(buf, width=w, height=h)
            img.hAlign = 'LEFT'
            flowables.append(img)
            flowables.append(Spacer(1, 30))
    ty = theme.typography
    # the same size the designed cover, the tokens and the DOCX cover use
    size = ty.title_size or ty.base_size * ty.heading_scale[0] * 1.4
    rtl = _is_rtl(block.title)
    align = 2 if rtl else 0
    # Arabic faces draw well above and below their nominal size: give them taller lines
    ratio = 1.4 if rtl else 1.2
    ts = ParagraphStyle('CoverTitle', fontName=get_font_name(ty.heading_family, bold=True),
                        fontSize=size, leading=size * ratio, alignment=align,
                        textColor=_safe_color(theme.colors.text_primary), spaceAfter=size * 0.45)
    flowables.append(Paragraph(_md_inline(block.title), ts))

    def line(name, text, fs, color, after=0.0):
        return Paragraph(text, ParagraphStyle(name, fontName=get_font_name(ty.body_family), fontSize=fs,
                                              leading=fs * (1.6 if _is_rtl(text) else 1.3),
                                              alignment=2 if _is_rtl(text) else align,
                                              textColor=_safe_color(color), spaceAfter=after))
    if block.subtitle:
        flowables.append(line('CoverSub', _md_inline(block.subtitle), ty.base_size * 1.3,
                              theme.colors.text_secondary, 30))
    if block.author:
        flowables.append(line('CoverAuthor', f"{_label('prepared_by')} {_md_inline(block.author)}",
                              ty.base_size, theme.colors.text_muted))
    if block.date:
        flowables.append(Spacer(1, 60))
        flowables.append(line('CoverDate', _md_inline(block.date), ty.base_size, theme.colors.text_muted))
    flowables.append(PageBreak())
    return flowables


def _coerce_child(b):
    """Nested layout children may be Blocks, plain strings or JSON dicts."""
    if isinstance(b, str):
        from ..schema.blocks import ParagraphBlock
        return ParagraphBlock(text=b)
    if isinstance(b, dict):
        from pydantic import TypeAdapter
        from ..schema.blocks import Block
        return TypeAdapter(Block).validate_python(b)
    return b


def _render_columns(block, theme, count, ctx=None):
    col_lists = [block.left, block.right] if count == 2 else (block.columns or [])
    ratios = [block.ratio, 1 - block.ratio] if count == 2 else [1.0 / max(len(col_lists), 1)] * len(col_lists)
    col_lists = [[_coerce_child(b) for b in col] for col in col_lists]
    sample = " ".join(str(getattr(b, "text", None) or getattr(b, "title", None) or "") for col in col_lists for b in col)
    rtl = _is_rtl(sample)
    if rtl:                       # right-to-left text reads its first column on the right, as Word sets it
        col_lists, ratios = col_lists[::-1], ratios[::-1]
    total_w = ctx.available_width if ctx else 460
    col_widths = [total_w * r for r in ratios]
    rendered = []
    for col, cw in zip(col_lists, col_widths):
        inner = copy.copy(ctx) if ctx else None
        if inner is not None:
            inner.available_width = cw - 8                  # what a block in this column may use
        cf = []
        for b in col:
            cf.extend(create_flowables(b, theme, inner))
        rendered.append(cf)
    # signatures side by side stand on one line, whether or not each has a picture over it
    signing = all(getattr(b, "type", None) == "signature" for col in col_lists for b in col)
    t = Table([rendered], colWidths=col_widths, style=TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'BOTTOM' if signing else 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 8 if rtl else 0),       # the gap sits between the columns
        ('RIGHTPADDING', (0, 0), (-1, -1), 0 if rtl else 8),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))
    t.hAlign = 'LEFT'
    t.spaceAfter = theme.spacing.block_gap
    return [t]


# ═══════════════════════ New Block Renderers ═══════════════════════

def _render_checklist(block, theme, bs):
    """GFM task list: checkmark/box characters."""
    flowables = []
    for item in block.items:
        marker = CHECK_ON if item.checked else CHECK_OFF
        is_rtl = _is_rtl(item.text)
        text = _md_inline(item.text)
        if item.checked:
            text = f"<strike>{text}</strike>"
        font = _arabic_font(theme) if is_rtl else get_font_name(theme.typography.body_family)
        sty = ParagraphStyle('CL', parent=bs, firstLineIndent=0,
                             leftIndent=theme.spacing.list_indent,
                             spaceBefore=2, spaceAfter=2,
                             fontName=font, alignment=2 if is_rtl else 0)
        flowables.append(Paragraph(f"{marker}  {text}", sty))
    flowables.append(Spacer(1, theme.spacing.block_gap))
    return flowables


def _render_definition_list(block, theme, bs):
    """Definition list: bold term + indented definition."""
    flowables = []
    all_text = " ".join(item.term + item.definition for item in block.items)
    is_rtl = _is_rtl(all_text)
    font = _arabic_font(theme) if is_rtl else get_font_name(theme.typography.body_family)
    align = 2 if is_rtl else 0
    term_sty = ParagraphStyle('DT', parent=bs, firstLineIndent=0,
                              fontName=_arabic_font(theme, bold=True) if is_rtl else get_font_name(theme.typography.body_family, bold=True),
                              spaceBefore=6, spaceAfter=2, alignment=align)
    defn_sty = ParagraphStyle('DD', parent=bs, firstLineIndent=0,
                              fontName=font,
                              leftIndent=0 if is_rtl else theme.spacing.list_indent,
                              rightIndent=theme.spacing.list_indent if is_rtl else 0,
                              textColor=_safe_color(theme.colors.text_secondary),
                              spaceAfter=4, alignment=align)
    for item in block.items:
        flowables.append(Paragraph(_md_inline(item.term), term_sty))
        flowables.append(Paragraph(_md_inline(item.definition), defn_sty))
    flowables.append(Spacer(1, theme.spacing.block_gap))
    return flowables


def _render_footnote(block, theme, bs):
    """Footnote: superscript marker with indented text."""
    sty = ParagraphStyle('FN', parent=bs, firstLineIndent=0,
                         fontSize=theme.typography.base_size * theme.typography.caption_size_ratio,
                         textColor=_safe_color(theme.colors.text_secondary),
                         leftIndent=theme.spacing.list_indent,
                         spaceBefore=2, spaceAfter=2)
    marker = block.marker
    return [Paragraph(f"<super>{marker}</super> {_md_inline(block.text)}", sty)]


def _paper_caption(theme, bs, text: str, before: float = 0.0, after: float = 0.0) -> ParagraphStyle:
    """A paper's caption: centred, in the text colour, a size under the body."""
    size = theme.typography.base_size * 0.9
    return ParagraphStyle('PaperCap', parent=bs, firstLineIndent=0, fontSize=size, leading=size * 1.35,
                          fontName=_arabic_font(theme) if _is_rtl(text) else get_font_name(theme.typography.body_family),
                          textColor=_safe_color(theme.colors.text_primary), alignment=1,
                          spaceBefore=before, spaceAfter=after)


def _paper_abstract(block, theme, bs):
    """A paper's abstract: a centred label, then the text set narrower and a little smaller
    than the body, with each part's label run into its first line."""
    ty = theme.typography
    inset = 28.0
    size = ty.base_size * 0.92
    label = ParagraphStyle('AbsHead', fontName=get_font_name(ty.heading_family, bold=True), fontSize=ty.base_size,
                           leading=ty.base_size * 1.3, alignment=1, spaceAfter=ty.base_size * 0.5,
                           textColor=bs.textColor)
    text = ParagraphStyle('AbsBody', parent=bs, firstLineIndent=0, leftIndent=inset, rightIndent=inset,
                          fontSize=size, leading=size * ty.line_height, spaceBefore=0, spaceAfter=size * 0.25)
    out = [Paragraph(_md_inline(_label("abstract")), label)]
    for field in block.fields:
        run_in = f"<b>{_md_inline(field.label)}:</b> " if (field.label or "").strip() else ""
        out.append(Paragraph(run_in + _md_inline(field.text), _hyphenated(text)))
    if block.keywords:
        words = ", ".join(block.keywords)
        out.append(Paragraph(f"<b>{_md_inline(_label('keywords'))}:</b> {_md_inline(words)}",
                             ParagraphStyle('AbsKW', parent=text, alignment=2 if _is_rtl(words) else 0,
                                            spaceBefore=size * 0.4)))
    out[-1].style = ParagraphStyle('AbsLast', parent=out[-1].style, spaceAfter=theme.spacing.block_gap * 1.6)
    out[0].keepWithNext = 1
    return out


def _render_abstract(block, theme, bs):
    """IMRAD structured abstract in a bordered box."""
    if theme.decorations.paper:
        return _paper_abstract(block, theme, bs)
    flowables = []
    title_sty = ParagraphStyle('AbsTitle',
                               fontName=get_font_name(theme.typography.heading_family, bold=True),
                               fontSize=theme.typography.base_size * 1.3,
                               spaceBefore=4, spaceAfter=8)
    flowables.append(Paragraph(_md_inline(_label("abstract")), title_sty))
    for field in block.fields:
        label_sty = ParagraphStyle('AbsLabel', parent=bs, firstLineIndent=0,
                                   fontName=get_font_name(theme.typography.body_family, bold=True),
                                   spaceBefore=4, spaceAfter=1)
        text_sty = ParagraphStyle('AbsText', parent=bs, firstLineIndent=0,
                                  leftIndent=0, spaceAfter=4)
        flowables.append(Paragraph(f"{field.label}:", label_sty))
        flowables.append(Paragraph(_md_inline(field.text), text_sty))
    if block.keywords:
        kw_sty = ParagraphStyle('AbsKW', parent=bs, firstLineIndent=0,
                                fontName=get_font_name(theme.typography.body_family, italic=True),
                                fontSize=theme.typography.base_size * 0.9,
                                spaceBefore=6)
        flowables.append(Paragraph(f"<b>{_md_inline(_label('keywords'))}:</b> "
                                   f"{_md_inline(', '.join(block.keywords))}", kw_sty))
    # Wrap in a bordered table; each flowable is its own row so ReportLab can
    # split long abstracts across pages (a single KeepTogether would overflow).
    pad = theme.spacing.callout_padding
    rows = [[f] for f in flowables]
    t = Table(rows, style=TableStyle([
        ('BOX', (0, 0), (-1, -1), 1, _safe_color(theme.colors.border)),
        ('LEFTPADDING', (0, 0), (-1, -1), pad + 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), pad),
        ('TOPPADDING', (0, 0), (0, 0), pad),
        ('TOPPADDING', (1, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-2, -1), 0),
        ('BOTTOMPADDING', (0, -1), (-1, -1), pad),
    ]))
    t.hAlign = 'LEFT'
    t.spaceAfter = theme.spacing.block_gap * 2
    return [t]


def _render_bibliography(block, theme, bs):
    """Reference list with numbered entries and hanging indent."""
    flowables = []
    title_sty = ParagraphStyle('BibTitle',
                               fontName=get_font_name(theme.typography.heading_family, bold=True),
                               fontSize=theme.typography.base_size * 1.3,
                               spaceBefore=12, spaceAfter=8)
    paper = theme.decorations.paper
    if paper:                       # set as the paper's sections are, without a number
        from ..design.tokens import heading_size
        size = heading_size(theme, 1)
        title_sty = ParagraphStyle('BibTitleP', parent=title_sty, fontSize=size, leading=size * 1.2,
                                   textColor=_safe_color(theme.colors.text_primary),
                                   spaceBefore=theme.spacing.heading_spacing_before[0],
                                   spaceAfter=theme.spacing.heading_spacing_after[0])
    if not (block.hints or {}).get("titled"):
        flowables.append(Paragraph(_md_inline(_label("references")), title_sty))
        flowables[-1].keepWithNext = 1
    ref_sty = ParagraphStyle('BibEntry', parent=bs, firstLineIndent=-24,
                             leftIndent=24,
                             fontSize=theme.typography.base_size * 0.9,
                             spaceBefore=2, spaceAfter=4)
    # the text cites [1], [2]: entries keyed by number carry that number, whatever the style
    keyed = paper and block.style != "ieee" and all((e.key or "").strip().isdigit() for e in block.entries)
    if paper:
        ref_sty = ParagraphStyle('BibEntryP', parent=ref_sty, alignment=0, spaceBefore=0, spaceAfter=3)
    for i, entry in enumerate(block.entries, 1):
        if keyed:
            text = f"[{entry.key.strip()}] {entry.authors} ({entry.year}). {entry.title}. <i>{entry.source}</i>."
        elif block.style == "ieee":
            text = f"[{i}] {entry.authors}, \"{entry.title},\" <i>{entry.source}</i>, {entry.year}."
        elif block.style == "chicago":
            text = f"{entry.authors}. {entry.title}. <i>{entry.source}</i>, {entry.year}."
        else:  # apa
            text = f"{entry.authors} ({entry.year}). {entry.title}. <i>{entry.source}</i>."
        if entry.doi:
            text += f" https://doi.org/{entry.doi}"
        flowables.append(Paragraph(text, ref_sty))
    flowables.append(Spacer(1, theme.spacing.block_gap))
    return flowables


def _side(alignment: str, rtl: bool) -> str:
    """A physical side for start, center or end (left and right stay as they are)."""
    a = (alignment or "start").lower()
    return {"start": "right" if rtl else "left", "end": "left" if rtl else "right"}.get(a, a if a in ("left", "right", "center") else "left")


def _render_signature(block, theme, width=None):
    """A signature: its picture over the line when there is one, then the name, title and date, all
    set to one side (the start edge by default) of the space it is given: the page, or a column."""
    rtl = _is_rtl(" ".join(x for x in (block.name, block.title, block.date) if x))
    side = _side(block.alignment, rtl)
    align = {"left": 0, "center": 1, "right": 2}[side]
    font = (lambda bold=False: _arabic_font(theme, bold=bold)) if rtl else \
        (lambda bold=False: get_font_name(theme.typography.body_family, bold=bold))
    flows = []
    if block.image:
        try:
            buf, (iw, ih) = _load_image(block.image, _diag.current().policy.assets)
            scale = min(block.line_width / iw, 46 / ih, 1.0 if iw <= block.line_width else 1e9)
            flows.append(Image(buf, width=iw * scale, height=ih * scale))
        except DynamicPDFError as e:
            _diag.current().fail("asset_failed", f"Signature image: {e}", e)
    if block.show_line:
        flows.append(DividerFlowable(color=theme.colors.text_primary, thickness=0.8, width=block.line_width, align=side))
    # names are literal text: shaped, escaped, never read as markup
    size, lh = theme.typography.base_size, theme.typography.line_height
    for text, sz, color, bold in ((block.name, size, theme.colors.text_primary, True),
                                  (block.title, size * 0.9, theme.colors.text_secondary, False),
                                  (block.date, size * 0.85, theme.colors.text_muted, False)):
        if text:
            flows.append(Paragraph(_plain_markup(text), ParagraphStyle(
                'Sig', fontName=font(bold), fontSize=sz, leading=sz * lh, textColor=_safe_color(color),
                spaceBefore=4 if bold else 0, spaceAfter=2, alignment=align)))
    # one cell: its alignment places the picture and the line, here and inside a column alike
    t = Table([[flows]], colWidths=[width] if width else None, style=TableStyle([
        ('ALIGN', (0, 0), (-1, -1), side.upper()), ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 0)]))
    t.hAlign = side.upper()
    return [Spacer(1, 12 if block.image else 30), t, Spacer(1, theme.spacing.block_gap)]


class TimelineDot(Flowable):
    """Single timeline event with a colored dot and vertical line."""
    def __init__(self, date_str, title, description, dot_color, line_color,
                 font_name, font_size, is_last=False):
        super().__init__()
        self.date_str = date_str
        self.title_str = title
        self.desc_str = description
        self.dot_color = dot_color
        self.line_color = line_color
        self.font_name = font_name
        self.font_size = font_size
        self.is_last = is_last

    def wrap(self, availWidth, availHeight):
        self.width = availWidth
        self.height = self.font_size * 4 + (10 if self.desc_str else 0)
        return (self.width, self.height)

    def draw(self):
        c = self.canv
        c.saveState()
        dot_x = 20
        text_x = 40
        y_top = self.height - 8
        # Vertical line
        if not self.is_last:
            c.setStrokeColor(_safe_color(self.line_color))
            c.setLineWidth(1.5)
            c.line(dot_x, y_top - 6, dot_x, 0)
        # Dot
        c.setFillColor(_safe_color(self.dot_color))
        c.circle(dot_x, y_top, 5, fill=1, stroke=0)
        # Date
        c.setFillColor(_safe_color("#718096"))
        c.setFont(self.font_name, self.font_size * 0.85)
        c.drawString(text_x, y_top - 3, self.date_str)
        # Title
        c.setFillColor(_safe_color("#1A1A2E"))
        c.setFont(self.font_name, self.font_size)
        c.drawString(text_x, y_top - 3 - self.font_size * 1.3, self.title_str)
        # Description
        if self.desc_str:
            c.setFillColor(_safe_color("#718096"))
            c.setFont(self.font_name, self.font_size * 0.9)
            c.drawString(text_x, y_top - 3 - self.font_size * 2.5, self.desc_str)
        c.restoreState()


def _render_timeline(block, theme, bs):
    """Vertical timeline with dots and connecting line."""
    flowables = []
    for i, event in enumerate(block.events):
        is_last = (i == len(block.events) - 1)
        dot_color = event.color or theme.colors.accent
        flowables.append(TimelineDot(
            date_str=event.date, title=event.title,
            description=event.description or "",
            dot_color=dot_color, line_color=theme.colors.border,
            font_name=get_font_name(theme.typography.body_family),
            font_size=theme.typography.base_size,
            is_last=is_last))
    flowables.append(Spacer(1, theme.spacing.block_gap))
    return flowables


def _render_qrcode(block, theme):
    """Render a QR code using the qrcode library → PIL Image → ReportLab Image."""
    try:
        import qrcode
        from PIL import Image as PILImage
        import io as _io
        ec_map = {"L": qrcode.constants.ERROR_CORRECT_L,
                  "M": qrcode.constants.ERROR_CORRECT_M,
                  "Q": qrcode.constants.ERROR_CORRECT_Q,
                  "H": qrcode.constants.ERROR_CORRECT_H}
        qr = qrcode.QRCode(
            error_correction=ec_map.get(block.error_correction.upper(),
                                        qrcode.constants.ERROR_CORRECT_M),
            box_size=10, border=2)
        qr.add_data(block.data)
        qr.make(fit=True)
        img: PILImage.Image = qr.make_image(fill_color="black", back_color="white").convert("RGB")
        buf = _io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        from reportlab.lib.utils import ImageReader
        rl_img = Image(buf, width=block.size, height=block.size)
        rl_img.hAlign = block.alignment.upper()
        rl_img.spaceAfter = theme.spacing.block_gap
        flowables = [rl_img]
        if block.caption:
            cap_sty = ParagraphStyle(
                "QRCap",
                fontSize=theme.typography.base_size * theme.typography.caption_size_ratio,
                textColor=_safe_color(theme.colors.text_muted),
                alignment=1, spaceAfter=theme.spacing.block_gap)
            flowables.append(Paragraph(f"<i>{_md_inline(block.caption)}</i>", cap_sty))
        return flowables
    except ImportError:
        _diag.current().warn(
            "qrcode_unavailable",
            'QR code rendered as text: install "dynamic-pdf-builder[qrcode]"')
        bs = _body_style(theme, indent=False)
        return [Paragraph(
            f'[QR Code: {html_mod.escape(block.data)}]', bs)]


def _render_sidebar(block, theme, ctx=None):
    """Main content + floating sidebar via 2-column table."""
    main_f, side_f = [], []
    for b in block.main_content:
        main_f.extend(create_flowables(_coerce_child(b), theme, ctx))
    for b in block.sidebar_content:
        side_f.extend(create_flowables(_coerce_child(b), theme, ctx))
    total_w = ctx.available_width if ctx else 460
    side_w = total_w * block.sidebar_ratio
    main_w = total_w - side_w - 10
    if block.sidebar_position == "left":
        cols = [side_f, main_f]
        widths = [side_w, main_w]
    else:
        cols = [main_f, side_f]
        widths = [main_w, side_w]
    t = Table([cols], colWidths=widths, style=TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))
    t.hAlign = 'LEFT'
    t.spaceAfter = theme.spacing.block_gap
    return [t]


def _build_list_flowable(items, bullet_type, theme, bs, sp, start=1, depth=0):
    """Recursively build a nested ListFlowable from ListItemModel objects."""
    from reportlab.platypus import ListFlowable, ListItem
    bullet_char = BULLET_CHARS[min(depth, len(BULLET_CHARS) - 1)]

    li_list = []
    for idx, item in enumerate(items):
        item_sty = ParagraphStyle(
            f'LI_d{depth}',
            parent=bs,
            firstLineIndent=0,
        )
        text = _md_inline(item.text).replace("\n", "<br/>")
        if item.checked is not None:
            text = (CHECK_ON if item.checked else CHECK_OFF) + "  " + text
        para = Paragraph(text, item_sty)

        if item.children:
            # Nested sub-list: explicit ordered-ness wins, else inherit parent's
            if item.children_ordered is not None:
                child_type = '1' if item.children_ordered else 'bullet'
            else:
                child_type = '1' if bullet_type == '1' else 'bullet'
            child_flow = _build_list_flowable(
                item.children, child_type, theme, bs, sp, depth=depth + 1)
            li_list.append(ListItem([para, child_flow],
                                    leftIndent=sp.list_indent))
        else:
            li_list.append(ListItem(para, leftIndent=sp.list_indent))

    item_size = bs.fontSize                # nested items keep the list's size: one text size per page
    kwargs = dict(
        leftIndent=sp.list_indent,
        spaceBefore=0 if depth > 0 else sp.block_gap / 2,
        # a nested group ends with the gap its items keep, so the next item is not drawn up to it
        spaceAfter=bs.spaceAfter if depth > 0 else sp.block_gap / 2,
        bulletFontName=bs.fontName,
        bulletFontSize=item_size,
        bulletOffsetY=0,
    )
    if bullet_type == '1':
        # 1. → a. → i. for nested ordered levels (matches the DOCX numbering)
        kwargs['bulletType'] = ['1', 'a', 'i'][depth % 3]
        kwargs['start'] = start if depth == 0 else 1
        kwargs['bulletFormat'] = '%s.'
    else:
        kwargs['bulletType'] = 'bullet'
        kwargs['start'] = bullet_char

    return ListFlowable(li_list, **kwargs)


class DocumentTOC(_RLTableOfContents):
    """Page-aware, linked table of contents.

    Entries are collected for *all* headings in the document (before or after
    the TOC) during ReportLab ``multiBuild`` passes, so page numbers are final
    and every entry links to its heading destination.
    """

    def __init__(self, depth: int = 3, rtl: bool = False, number_style=None, kind: str = "contents", **kw):
        super().__init__(**kw)
        self.kind = kind                 # "contents", or "figures" / "tables": a list of captions
        self.depth = depth
        self.rtl = rtl
        self.number_style = number_style

    def wrap(self, availWidth, availHeight):
        if self.kind != "contents" and not self._lastEntries:
            # nothing numbered (yet): an empty list, not ReportLab's placeholder text
            self._table = Table([[""]], colWidths=[availWidth])
            self.width, self.height = self._table.wrapOn(self.canv, availWidth, availHeight)
            return self.width, self.height
        if not self.rtl:
            return super().wrap(availWidth, availHeight)
        # Right-to-left TOC: title flush right, page number on the left (start of
        # the reading line's end), dotted leader between, every cell linked.
        rows = []
        for level, text, page, key in (self._lastEntries or [(0, "", 0, None)]):
            sty = ParagraphStyle(f'TOCR{level}', parent=self.getLevelStyle(level), alignment=2,
                                 leftIndent=0, firstLineIndent=0, rightIndent=level * 18)
            link = (lambda t: f'<a href="#{key}">{t}</a>') if key else (lambda t: t)
            # entries arrive in visual order (engine.afterFlowable): plain Paragraph
            rows.append([_RLParagraph(link(str(page)), self.number_style or sty),
                         _RLParagraph(link(text), sty)])
        self._table = Table(rows, colWidths=[36, availWidth - 36], style=TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('LINEBELOW', (0, 0), (-1, -1), 0.25, HexColor("#D5D9DF")),
            ('TOPPADDING', (0, 0), (-1, -1), 3), ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
        self._table.hAlign = 'RIGHT'
        self.width, self.height = self._table.wrapOn(self.canv, availWidth, availHeight)
        return self.width, self.height

    def notify(self, kind, stuff):
        if self.kind != "contents":
            if kind == f"DPBExhibit:{self.kind}":
                super().notify('TOCEntry', stuff)
            return
        if kind == 'TOCEntry' and stuff[0] >= self.depth:
            return
        super().notify(kind, stuff)


def _render_toc_placeholder(block, theme, ctx):
    """Real table of contents (final page numbers, clickable entries)."""
    from reportlab.platypus import HRFlowable

    flowables = []

    title_sty = ParagraphStyle(
        'TOCTitle',
        fontName=get_font_name(theme.typography.heading_family, bold=True),
        fontSize=theme.typography.base_size * 1.4,
        leading=theme.typography.base_size * 1.8,
        textColor=_safe_color(theme.colors.text_primary),
        spaceBefore=0, spaceAfter=12,
    )
    lang = getattr(ctx, "language", "en") if ctx else "en"
    kind = getattr(block, "kind", "contents")
    toc_title = _i18n_label({"figures": "lof", "tables": "lot"}.get(kind, "toc"), lang)
    if _is_rtl(toc_title):
        title_sty = ParagraphStyle('TOCTitleRTL', parent=title_sty, alignment=2,
                                   fontName=_arabic_font(theme, bold=True))
    flowables.append(Paragraph(_md_inline(toc_title), title_sty))
    flowables.append(HRFlowable(
        width="100%", thickness=1,
        color=_safe_color(theme.colors.accent), spaceAfter=8))

    depth_limit = max(1, min(6, getattr(block, 'depth', 3) or 3))
    level_styles = []
    for lvl in range(6):
        fs = theme.typography.base_size * (1.0 if lvl == 0 else 0.9)
        level_styles.append(ParagraphStyle(
            f'TOC_L{lvl + 1}',
            fontName=get_font_name(theme.typography.body_family, bold=lvl <= 1),
            fontSize=fs,
            leading=fs * 1.45,
            leftIndent=lvl * 18 + 18,
            firstLineIndent=-18,
            spaceBefore=5 if lvl == 0 else 1,
            textColor=_safe_color(theme.colors.text_primary if lvl <= 1
                                  else theme.colors.text_secondary),
        ))
    rtl = lang == "ar"
    num_sty = ParagraphStyle('TOCNum', fontName=get_font_name(theme.typography.body_family),
                             fontSize=theme.typography.base_size * 0.9,
                             textColor=_safe_color(theme.colors.text_secondary), alignment=0)
    toc = DocumentTOC(depth=depth_limit, rtl=rtl, number_style=num_sty, levelStyles=level_styles,
                      dotsMinLevel=0, rightColumnWidth=48, kind={"figures": "figure", "tables": "table"}.get(kind, kind))
    flowables.append(toc)
    flowables.append(Spacer(1, 8))
    flowables.append(PageBreak())
    return flowables


def _render_introduction_page(block, theme, ctx=None):
    """A preface or a conclusion on a page of its own: a rule of the accent colour, the title, an
    optional line under it, then the text. It reads from the right when its title does."""
    ty = theme.typography
    rtl = _is_rtl(block.title + " " + (block.content or ""))
    align = 2 if rtl else 0

    def face(bold=False, italic=False, heading=False):
        return _arabic_font(theme, bold=bold) if rtl else get_font_name(
            ty.heading_family if heading else ty.body_family, bold=bold, italic=italic)
    size = ty.base_size * ty.heading_scale[0] * 1.2
    from reportlab.platypus.flowables import PageBreakIfNotEmpty
    back = block.position == "back"
    flowables = ([PageBreakIfNotEmpty()] if back and not getattr(ctx, "first_block", False) else []) + [
        Spacer(1, 40),
        DividerFlowable(color=block.accent_color or theme.colors.accent, thickness=3.0, width=64,
                        align="right" if rtl else "left"),
        Spacer(1, 10),
        Paragraph(_md_inline(block.title), ParagraphStyle(
            'IntroTitle', fontName=face(bold=True, heading=True), fontSize=size, leading=size * (1.6 if rtl else 1.25),
            textColor=_safe_color(theme.colors.text_primary), spaceAfter=8, alignment=align))]
    if block.subtitle:
        flowables.append(Paragraph(_md_inline(block.subtitle), ParagraphStyle(
            'IntroSub', fontName=face(italic=True), fontSize=ty.base_size * 1.15, leading=ty.base_size * 1.15 * ty.line_height,
            textColor=_safe_color(theme.colors.text_secondary), spaceAfter=16, alignment=align)))
    flowables.append(Spacer(1, 12))
    body_sty = ParagraphStyle('IntroBody', fontName=face(), fontSize=ty.base_size * 1.05,
                              leading=ty.base_size * 1.05 * ty.line_height * (1.1 if rtl else 1.0),
                              textColor=_safe_color(theme.colors.text_primary), spaceAfter=10, alignment=4)
    for para in (block.content or "").split('\n\n'):
        if para.strip():
            flowables.append(Paragraph(_md_inline(para.strip()), body_sty))
    if not back and not getattr(ctx, "last_block", False):
        flowables.append(PageBreak())
    return flowables
