"""
Streaming Markdown: parse text as it arrives, preview it, render it once complete.

    with stream("out.pdf", design="auto") as s:
        for chunk in chunks:
            s.write(chunk)
            if want_preview:
                pdf_bytes = s.preview()
    s.result            # ExportResult of the final export()

Only complete blocks are committed. A block is complete once a later top-level
block has started (CommonMark never reopens a closed block), outside an open
``$$`` display-math span, a ``:::`` callout or front matter. Everything after the
last committed block stays pending, so an open code fence, a half-written table
or list, or unterminated emphasis is never committed early. The final render
parses the whole text through ``DocumentBuilder.from_markdown(...).export()``, so
its blocks are exactly those of a one-shot parse.
"""
import re
from contextlib import contextmanager
from typing import Optional

from .builder import DocumentBuilder
from .markdown.parser import _parse_body, _tokens, split_front_matter
from .markdown.preprocessors import preprocess_markdown
from .policy import RenderPolicy
from .utils.errors import ResourceLimitError

_FM_OPEN = re.compile(r"﻿?---[ \t]*$")


def _callout_opens(content: str) -> bool:
    # mirrors the callout rule of markdown.parser._parse_body
    return content.startswith(":::") and content.strip() != ":::"


class MarkdownStream:
    """Incremental Markdown parser. ``blocks`` holds the committed blocks."""

    def __init__(self, max_chars: Optional[int] = None):
        self.max_chars = max_chars
        self.blocks: list = []
        self.front_matter: Optional[dict] = None   # None until the opening lines are known
        self._parts: list = []      # every chunk as written (the final render uses these)
        self._size = 0
        self._head = ""             # normalized text before the body is known (front matter)
        self._carry = ""            # a trailing "\r" that may be half of "\r\n"
        self._raw = ""              # body text not yet preprocessed (partial line, open $$)
        self._pending = ""          # preprocessed text of the uncommitted blocks

    @property
    def text(self) -> str:
        return "".join(self._parts)

    def write(self, chunk: str) -> None:
        self._size += len(chunk)
        if self.max_chars is not None and self._size > self.max_chars:
            raise ResourceLimitError(
                f"Markdown input length ({self._size}) exceeds limit ({self.max_chars})")
        self._parts.append(chunk)
        text = self._carry + chunk
        self._carry = "\r" if text.endswith("\r") else ""
        text = text[:-1] if self._carry else text
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        if self.front_matter is None:
            self._head += text
            if not self._split_head():
                return
        else:
            self._raw += text
        self._advance()

    def _split_head(self) -> bool:
        """Separate front matter from the body once that can be decided."""
        if "\n" not in self._head:
            return False
        if _FM_OPEN.match(self._head.split("\n", 1)[0]):
            complete = self._head[:self._head.rfind("\n") + 1]    # the closing line must be whole
            fm, body = split_front_matter(complete)
            if body is complete:            # front matter not closed yet
                return False
            self.front_matter, self._raw = fm, body + self._head[len(complete):]
        else:
            self.front_matter, self._raw = {}, self._head
        self._head = ""
        return True

    def _advance(self) -> None:
        # move complete lines with balanced "$$" (display math) into the pending text
        lines, ends, count, cut = self._raw.split("\n")[:-1], 0, 0, 0
        for line in lines:
            ends += len(line) + 1
            count += line.count("$$")
            if count % 2 == 0:
                cut = ends
        if not cut:
            return
        self._pending += preprocess_markdown(self._raw[:cut])
        self._raw = self._raw[cut:]
        self._commit()

    def _commit(self) -> None:
        tokens = _tokens(self._pending)
        top = [(i, t) for i, t in enumerate(tokens) if t.level == 0 and t.nesting >= 0 and t.map]
        safe, callout = None, False
        for n, (i, t) in enumerate(top):
            para = t.type == "paragraph_open"
            if n and not (callout and para):
                safe = t.map[0]             # cutting before this block cannot change the ones above
            content = tokens[i + 1].content if para else ""
            if not para:
                callout = False
            elif callout:
                callout = not content.rstrip().endswith(":::")
            elif _callout_opens(content):
                rest = content.split("\n", 1)
                callout = not (len(rest) > 1 and rest[1].rstrip().endswith(":::"))
        if safe is None:
            return
        lines = self._pending.split("\n")
        offset = sum(len(line) + 1 for line in lines[:safe])
        self.blocks.extend(_parse_body(self._pending[:offset]))
        self._pending = self._pending[offset:]

    def pending_blocks(self) -> list:
        """A tentative parse of what has not been committed (unfinished constructs
        parse as far as they go: an open fence is code to the end, and so on)."""
        if self.front_matter is None:
            return []
        return _parse_body(self._pending + self._raw)

    def front_matter_text(self) -> str:
        """The raw front matter block (empty when there is none or it is not closed)."""
        text = self.text
        _, body = split_front_matter(text)
        return text[:len(text) - len(body)] if self.front_matter else ""


class StreamingDocument:
    """A document whose Markdown arrives in pieces; rendered with ``export()`` on close."""

    def __init__(self, output_path: str, theme: Optional[str] = None, design: Optional[str] = "auto",
                 policy: Optional[RenderPolicy] = None, format: Optional[str] = None,
                 qa: bool = False):
        self.output_path, self.theme, self.design = output_path, theme, design
        self.policy = policy or RenderPolicy()
        self.format, self.qa = format, qa
        self.parser = MarkdownStream(max_chars=self.policy.limits.max_input_chars)
        self.result = None
        self.builder: Optional[DocumentBuilder] = None

    @property
    def blocks(self) -> list:
        return self.parser.blocks

    def write(self, chunk: str) -> None:
        self.parser.write(chunk)

    def preview(self, output=None, design: Optional[str] = None) -> Optional[bytes]:
        """Render the pages of what has arrived so far: committed blocks plus a tentative
        parse of the rest. Classic theme by default (fast); pass ``design`` to preview
        a designed layout. Returns PDF bytes when ``output`` is None."""
        p = self.parser
        b = DocumentBuilder.from_markdown(p.front_matter_text(), theme=self.theme, policy=self.policy)
        b._blocks = p.blocks + p.pending_blocks()
        b._source_text = p.text
        b.design(design)
        return b.render(output)

    def close(self):
        """Final render of the whole text through ``export()`` (design and policy apply)."""
        if self.result is None:
            self.builder = DocumentBuilder.from_markdown(self.parser.text, theme=self.theme,
                                                         policy=self.policy).design(self.design)
            self.result = self.builder.export(self.output_path, format=self.format, qa=self.qa)
        return self.result


@contextmanager
def stream(output_path: str, theme: Optional[str] = "claude", design: Optional[str] = "auto",
           policy: Optional[RenderPolicy] = None, format: Optional[str] = None, qa: bool = False):
    """Stream Markdown into a document::

        with stream("out.pdf", design="auto", policy=RenderPolicy()) as s:
            s.write("# Hello")

    ``design=None`` renders with the classic theme. Nothing is written when the
    ``with`` body raises.
    """
    doc = StreamingDocument(output_path, theme=theme, design=design, policy=policy,
                            format=format, qa=qa)
    yield doc
    doc.close()


__all__ = ["stream", "StreamingDocument", "MarkdownStream"]
