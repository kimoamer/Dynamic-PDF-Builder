"""
Inline Markdown → typed ``TextRun`` spans.

Parsed once with markdown-it (CommonMark + strikethrough), then extended with
the project's inline conventions (``==highlight==``, ``^sup^``, ``~sub~`` via
``<sub>``, footnote refs ``[^n]``). Renderers (PDF, DOCX) consume runs instead
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
        pos = m.end()
    if pos < len(text):
        runs.append(TextRun(text=text[pos:], **style))
    return runs


def parse_inline(text: str) -> List[TextRun]:
    """Parse inline Markdown into a flat list of styled runs (lossless text)."""
    if not text:
        return []
    from .numbering import resolve_refs
    # {ref:id} reads "Table 2" (linked) while a document is rendered; otherwise it stays as written
    text = resolve_refs(text, lambda label, anchor: f"[{_md_escape(label)}](#{anchor})" if anchor else label)
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
