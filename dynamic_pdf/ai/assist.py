"""
Content assistance: alt text, subject and keywords, a summary, structure repairs.

Each function is its own switch and nothing runs unless called. Every result is a
``Suggestion`` labelled AI-written. None of them changes the document: the author's ledger
holds only what the author wrote, and a caller who wants a suggestion applies it by hand
(structure repairs come as a diff, plus the repaired copy, for exactly that).
"""
from __future__ import annotations

import base64
import difflib
from dataclasses import dataclass, field
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, Field

from .design import content_sha, document_text
from .provider import Provider, ask, check_context, text_block

LABEL = "AI-written"


@dataclass
class Suggestion:
    kind: str                                   # alt_text | metadata | summary | structure
    value: Any                                  # None when the model's answer was not used
    report: dict = field(default_factory=dict)
    label: str = LABEL

    @property
    def model(self) -> str:
        return self.report.get("model", "")

    def as_block(self):
        """A summary as a callout whose title says who wrote it. Adding it is the caller's choice."""
        from ..schema.blocks import CalloutBlock
        if self.kind != "summary" or not self.value:
            raise ValueError("only a summary that came back can become a block")
        return CalloutBlock(title=f"Summary ({LABEL})", text=self.value, variant="abstract")


def _doc(document):
    return document.build() if hasattr(document, "build") else document


def _provider(provider: Optional[Provider]) -> Provider:
    if provider is None:
        from .provider import AnthropicProvider
        return AnthropicProvider()
    return provider


def _call(document, provider, feature: str, system: str, reply_model, extra: Optional[list] = None, facts=None):
    doc = _doc(document)
    facts = {"title": doc.meta.title, "language": doc.meta.language, "blocks": document_text(doc), **(facts or {})}
    content = (extra or []) + [text_block(facts)]
    return ask(_provider(provider), feature=feature, context="pages" if extra else "text", system=system,
               content=content, reply_model=reply_model, content_hash=content_sha(doc), facts=facts)


class AltItem(BaseModel):
    index: int
    alt_text: str = Field(min_length=1, max_length=400)


class AltReply(BaseModel):
    items: List[AltItem]


IMAGE_TYPES = {b"\x89PNG": "image/png", b"\xff\xd8\xff": "image/jpeg", b"GIF8": "image/gif", b"RIFF": "image/webp"}


def alt_text(document, provider: Optional[Provider] = None, *, context: str = "text", policy=None) -> Suggestion:
    """Alt text for images that have none, by block index. ``context="pages"`` also sends each
    image that loads under ``policy`` (local files only by default)."""
    doc = _doc(document)
    missing = [i for i, b in enumerate(doc.blocks) if b.type == "image" and not (b.alt_text or "").strip()]
    if not missing:
        return Suggestion("alt_text", {}, {"status": "skipped", "reason": "every image has alt text"})
    extra = []
    if check_context(context) == "pages":
        from ..assets import load_asset_bytes
        for i in missing:
            try:
                data = load_asset_bytes(doc.blocks[i].src, policy)
            except Exception:  # noqa: BLE001 - an image that cannot load is described from its text
                continue
            kind = next((t for magic, t in IMAGE_TYPES.items() if data.startswith(magic)), None)
            if kind:
                extra += [text_block(f"image at block {i}:"),
                          {"type": "image", "source": {"type": "base64", "media_type": kind,
                                                       "data": base64.standard_b64encode(data).decode("ascii")}}]
    reply, report = _call(doc, provider, "alt_text", "Write short, literal alt text for each listed image, from what it "
                          "shows and the text around it. Describe; do not interpret or add facts.", AltReply, extra,
                          {"images_without_alt_text": [{"index": i, "caption": doc.blocks[i].caption} for i in missing]})
    if reply is None:
        return Suggestion("alt_text", None, report)
    return Suggestion("alt_text", {it.index: it.alt_text for it in reply.items if it.index in missing}, report)


class MetaReply(BaseModel):
    subject: str = Field(max_length=300)
    keywords: List[str] = Field(max_length=12)


def metadata(document, provider: Optional[Provider] = None) -> Suggestion:
    """A subject line and keywords for the PDF properties."""
    reply, report = _call(document, provider, "metadata", "Suggest a one-sentence subject and up to twelve keywords "
                          "for this document's file properties, in the document's language.", MetaReply)
    return Suggestion("metadata", reply.model_dump() if reply else None, report)


class SummaryReply(BaseModel):
    summary: str = Field(min_length=1, max_length=1500)


def summary(document, provider: Optional[Provider] = None) -> Suggestion:
    """A short summary of the document, to add as a labelled block if the caller wants it."""
    reply, report = _call(document, provider, "summary", "Summarise this document in at most five sentences, in its "
                          "language, using only what it says.", SummaryReply)
    return Suggestion("summary", reply.summary if reply else None, report)


class Edit(BaseModel):
    index: int
    op: Literal["set_heading_level", "paragraph_to_heading"]
    level: int = Field(ge=1, le=6)
    reason: str = ""


class StructureReply(BaseModel):
    edits: List[Edit]


def structure(document, provider: Optional[Provider] = None) -> Suggestion:
    """Heading repairs (skipped levels, paragraphs that act as headings), as a diff of the
    document JSON and a repaired copy. Words never change; the document is never touched."""
    doc = _doc(document)
    outline = [{"index": i, "type": b.type, "level": getattr(b, "level", None)} for i, b in enumerate(doc.blocks)]
    reply, report = _call(doc, provider, "structure", "Find heading problems: skipped levels, and paragraphs that are "
                          "really headings. Return edits by block index. Never change words.", StructureReply,
                          facts={"outline": outline})
    if reply is None:
        return Suggestion("structure", None, report)
    fixed = doc.model_copy(deep=True)
    kept, dropped = [], []
    for e in reply.edits:
        b = fixed.blocks[e.index] if 0 <= e.index < len(fixed.blocks) else None
        if b is not None and e.op == "set_heading_level" and b.type == "heading":
            b.level = e.level
        elif b is not None and e.op == "paragraph_to_heading" and b.type == "paragraph":
            from ..schema.blocks import HeadingBlock
            fixed.blocks[e.index] = HeadingBlock(text=b.text, level=e.level, id=b.id, lang=b.lang)
        else:
            dropped.append(e.model_dump())
            continue
        kept.append(e.model_dump())
    if dropped:
        report["dropped"] = dropped
    before, after = doc.model_dump_json(indent=1), fixed.model_dump_json(indent=1)
    diff = "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True), "document.json",
                                        "document.repaired.json"))
    return Suggestion("structure", {"edits": kept, "diff": diff, "document": fixed}, report)


__all__ = ["LABEL", "Suggestion", "alt_text", "metadata", "structure", "summary"]
