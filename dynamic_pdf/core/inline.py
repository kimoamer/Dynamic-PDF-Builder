"""
Inline Markdown → typed ``TextRun`` spans.

Parsed once with markdown-it (CommonMark + strikethrough), then extended with
the project's inline conventions (``==highlight==``, ``^sup^``, ``~sub~`` via
``<sub>``, footnote refs ``[^n]``) and CriticMarkup for suggested edits:
``{++added++}``, ``{--removed--}``, ``{~~old~>new~~}``, ``{==text==}{>>comment<<}`` and
``{>>comment<<}``. Renderers (PDF, DOCX) consume runs instead
of re-parsing or regex-rewriting Markdown, so link targets, emphasis and code
spans keep their semantics in every output format.
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import List, Optional

from pydantic import BaseModel

_SAFE_LINK = ("http://", "https://", "mailto:", "#")


class TextRun(BaseModel):
    text: str
    bold: bool = False
    italic: bool = False
    code: bool = False
    strike: bool = False
    underline: bool = False
    superscript: bool = False
    subscript: bool = False
    highlight: bool = False
    link: Optional[str] = None          # validated href (http/https/mailto/#)
    footnote_ref: Optional[str] = None  # marker of a referenced footnote
    line_break: bool = False            # hard/soft line break run (text == "\n")
    inserted: bool = False              # a suggested addition (CriticMarkup {++ ++})
    deleted: bool = False               # a suggested removal (CriticMarkup {-- --})
    comment: Optional[str] = None       # a reviewer's comment on this text (CriticMarkup {>> <<})
    color: Optional[str] = None         # the text's colour, #RRGGBB ([text]{red})
    background: Optional[str] = None    # the colour behind it, #RRGGBB ([text]{bg=yellow})

    def same_style(self, other: "TextRun") -> bool:
        a = self.model_dump(exclude={"text"})
        b = other.model_dump(exclude={"text"})
        return a == b and not self.line_break and not other.line_break


@lru_cache(maxsize=1)
def _md():
    from markdown_it import MarkdownIt
    return MarkdownIt("commonmark", {"html": False}).enable(["strikethrough"])


def safe_href(url: str) -> Optional[str]:
    u = (url or "").strip()
    return u if u.lower().startswith(_SAFE_LINK) else None


# ── coloured text: [text]{red}, [text]{color=#C00 bg=yellow}, [text]{أحمر} (Pandoc's bracketed span) ──
COLORS = {"red": "#C62828", "green": "#2E7D32", "blue": "#1565C0", "orange": "#EF6C00", "purple": "#6A1B9A",
          "teal": "#00796B", "pink": "#C2185B", "brown": "#5D4037", "gray": "#616161", "grey": "#616161",
          "black": "#000000", "white": "#FFFFFF", "yellow": "#F9A825", "gold": "#B8893A", "navy": "#1F3A5F",
          "أحمر": "#C62828", "أخضر": "#2E7D32", "أزرق": "#1565C0", "برتقالي": "#EF6C00", "بنفسجي": "#6A1B9A",
          "وردي": "#C2185B", "بني": "#5D4037", "رمادي": "#616161", "أسود": "#000000", "أبيض": "#FFFFFF",
          "أصفر": "#F9A825", "ذهبي": "#B8893A", "كحلي": "#1F3A5F"}
# behind text a named colour is its pale tint, as a highlighter lays it
BACKGROUNDS = {"red": "#FFD9D9", "green": "#D7F5DD", "blue": "#DCEBFF", "orange": "#FFE4C7", "purple": "#EBDDFB",
               "teal": "#D3F1EC", "pink": "#FFD9EC", "gray": "#E8E8E8", "grey": "#E8E8E8", "yellow": "#FFF2A8",
               "أحمر": "#FFD9D9", "أخضر": "#D7F5DD", "أزرق": "#DCEBFF", "برتقالي": "#FFE4C7", "بنفسجي": "#EBDDFB",
               "وردي": "#FFD9EC", "رمادي": "#E8E8E8", "أصفر": "#FFF2A8"}
SPAN = re.compile(r"\[(?P<t>[^\[\]]+)\]\{(?P<a>[^{}\n]{1,80})\}")
_HEX = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def _colour(value: str, table: dict) -> Optional[str]:
    import unicodedata
    v = unicodedata.normalize("NFKC", value).strip().lstrip(".").lower()     # NFKC: Arabic shaped for the PDF reads as written
    if _HEX.match(v):
        return ("#" + "".join(c * 2 for c in v[1:]) if len(v) == 4 else v).upper()
    return table.get(v) or (COLORS.get(v) if table is BACKGROUNDS else None)


def span_style(attrs: str):
    """(colour, background) of a span's ``{...}``, or None when it names neither: then the brackets
    are ordinary text. A value is a name from ``COLORS`` or a hex colour; nothing else passes."""
    color = background = None
    for token in attrs.replace("&quot;", "").replace('"', "").split():
        key, _, value = token.partition("=")
        if not value:
            color = _colour(key, COLORS) or color
            if _colour(key, COLORS) is None:
                return None
        elif key.lower() in ("color", "colour"):
            color = _colour(value, COLORS)
            if color is None:
                return None
        elif key.lower() in ("bg", "background"):
            background = _colour(value, BACKGROUNDS)
            if background is None:
                return None
        else:
            return None
    return (color, background) if color or background else None


_BLANK_LINE = re.compile(r"\n[ \t]*\n\s*")      # a paragraph boundary inside one block

_EXT = re.compile(
    r"(?P<fn>\[\^(?P<fnm>[\w-]+)\])"
    r"|(?P<hl>==(?P<hlt>.+?)==)"
    r"|(?P<sup><sup>(?P<supt>.+?)</sup>)"
    r"|(?P<sub><sub>(?P<subt>.+?)</sub>)"
    r"|(?P<car>\^(?P<cart>[^\^\s][^\^]*?)\^)"
    r"|(?P<b><b>(?P<bt>.+?)</b>)"
    r"|(?P<i><i>(?P<it>.+?)</i>)"
    r"|(?P<u><u>(?P<ut>.+?)</u>)"
    r"|(?P<span>\[(?P<spant>[^\[\]]+)\]\{(?P<spana>[^{}\n]{1,80})\})"
)


def _split_extensions(text: str, style: dict) -> List[TextRun]:
    runs: List[TextRun] = []
    pos = 0
    for m in _EXT.finditer(text):
        if m.start() > pos:
            runs.append(TextRun(text=text[pos:m.start()], **style))
        if m.group("fn"):
            runs.append(TextRun(text=m.group("fnm"), footnote_ref=m.group("fnm"),
                                **{**style, "superscript": True}))
        elif m.group("hl"):
            runs.extend(_split_extensions(m.group("hlt"), {**style, "highlight": True}))
        elif m.group("sup"):
            runs.extend(_split_extensions(m.group("supt"), {**style, "superscript": True}))
        elif m.group("sub"):
            runs.extend(_split_extensions(m.group("subt"), {**style, "subscript": True}))
        elif m.group("car"):
            runs.extend(_split_extensions(m.group("cart"), {**style, "superscript": True}))
        elif m.group("b"):
            runs.extend(_split_extensions(m.group("bt"), {**style, "bold": True}))
        elif m.group("i"):
            runs.extend(_split_extensions(m.group("it"), {**style, "italic": True}))
        elif m.group("u"):
            runs.extend(_split_extensions(m.group("ut"), {**style, "underline": True}))
        elif m.group("span"):
            # shortcut: emphasis goes outside the span (**[word]{red}**), since Markdown is parsed before it
            look = span_style(m.group("spana"))
            if look is None:
                runs.append(TextRun(text=m.group("span"), **style))
            else:
                extra = {k: v for k, v in zip(("color", "background"), look) if v}
                runs.extend(_split_extensions(m.group("spant"), {**style, **extra}))
        pos = m.end()
    if pos < len(text):
        runs.append(TextRun(text=text[pos:], **style))
    return runs


# shortcut: a suggestion is parsed on its own, so emphasis cannot open outside it and close inside; CriticMarkup asks the same
CRITIC = re.compile(r"\{\+\+(?P<ins>.*?)\+\+\}|\{--(?P<del>.*?)--\}|\{~~(?P<old>.*?)~>(?P<new>.*?)~~\}"
                    r"|\{==(?P<mark>.*?)==\}\{>>(?P<on>.*?)<<\}|\{>>(?P<note>.*?)<<\}", re.S)


def parse_inline(text: str) -> List[TextRun]:
    """Parse inline Markdown into a flat list of styled runs (lossless text). Suggested edits
    and comments (CriticMarkup) mark the runs they cover; a comment's own words are not text."""
    if not text:
        return []
    from .numbering import resolve_refs
    # {ref:id} reads "Table 2" (linked) while a document is rendered; otherwise it stays as written
    text = resolve_refs(text, lambda label, anchor: f"[{_md_escape(label)}](#{anchor})" if anchor else label)
    if "{" not in text or not CRITIC.search(text):
        return _parse(text)
    out: List[TextRun] = []
    pos = 0
    for m in CRITIC.finditer(text):
        out += _parse(text[pos:m.start()])
        pos = m.end()
        g = m.groupdict()
        if g["ins"] is not None:
            out += [r.model_copy(update={"inserted": True}) for r in _parse(g["ins"])]
        elif g["del"] is not None:
            out += [r.model_copy(update={"deleted": True}) for r in _parse(g["del"])]
        elif g["old"] is not None:
            out += [r.model_copy(update={"deleted": True}) for r in _parse(g["old"])]
            out += [r.model_copy(update={"inserted": True}) for r in _parse(g["new"])]
        elif g["mark"] is not None:
            out += [r.model_copy(update={"comment": g["on"].strip()}) for r in _parse(g["mark"])]
        elif out and out[-1].text.strip() and not out[-1].line_break:
            # a comment alone remarks on the word before it
            last = out.pop()
            head, word = re.match(r"(.*?)(\S+\s*)$", last.text, re.S).groups()
            out += ([last.model_copy(update={"text": head})] if head else []) + [
                last.model_copy(update={"text": word, "comment": g["note"].strip()})]
    out += _parse(text[pos:])
    return _merge(out)


def _parse(text: str) -> List[TextRun]:
    if not text:
        return []
    out: List[TextRun] = []
    # Markdown decides what a newline means: a soft break inside a paragraph is a space
    # (text wrapped by an editor), a hard break ("  " or "\" before it) is a new line. A
    # blank line inside one block separates its paragraphs, so it breaks the line too.
    for seg_idx, segment in enumerate(_BLANK_LINE.split(text)):
        if seg_idx:
            out.append(TextRun(text="\n", line_break=True))
        tokens = _md().parseInline(segment)
        children = tokens[0].children if tokens and tokens[0].children else []
        style = {}
        link_stack: List[Optional[str]] = []
        for tok in children:
            t = tok.type
            if t == "text":
                out.extend(_split_extensions(tok.content, dict(style)))
            elif t == "code_inline":
                out.append(TextRun(text=tok.content, code=True, **{k: v for k, v in style.items() if k == "link"}))
            elif t == "strong_open":
                style["bold"] = True
            elif t == "strong_close":
                style.pop("bold", None)
            elif t == "em_open":
                style["italic"] = True
            elif t == "em_close":
                style.pop("italic", None)
            elif t == "s_open":
                style["strike"] = True
            elif t == "s_close":
                style.pop("strike", None)
            elif t == "link_open":
                href = safe_href(tok.attrGet("href") or "")
                link_stack.append(style.get("link"))
                if href:
                    style["link"] = href
            elif t == "link_close":
                prev = link_stack.pop() if link_stack else None
                if prev:
                    style["link"] = prev
                else:
                    style.pop("link", None)
            elif t in ("softbreak", "hardbreak"):
                out.append(TextRun(text="\n" if t == "hardbreak" else " ",
                                   line_break=t == "hardbreak"))
            elif t == "image":
                alt = tok.content or "".join(c.content for c in (tok.children or []))
                out.append(TextRun(text=alt or "[image]", italic=True))
            else:
                if tok.content:
                    out.append(TextRun(text=tok.content, **style))
    return _merge(out)


def _md_escape(text: str) -> str:
    return re.sub(r"([\\`*_\[\]<>])", r"\\\1", text)


def _merge(runs: List[TextRun]) -> List[TextRun]:
    merged: List[TextRun] = []
    for r in runs:
        if not r.text:
            continue
        if merged and merged[-1].same_style(r) and not r.footnote_ref and not merged[-1].footnote_ref:
            merged[-1] = merged[-1].model_copy(update={"text": merged[-1].text + r.text})
        else:
            merged.append(r)
    return merged


def runs_to_plain(runs: List[TextRun]) -> str:
    return "".join(r.text for r in runs)


def plain_text(markdown_inline: str) -> str:
    """Visible text of an inline Markdown string."""
    return runs_to_plain(parse_inline(markdown_inline))
