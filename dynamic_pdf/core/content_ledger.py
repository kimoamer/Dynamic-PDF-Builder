"""
A record of what a document says, independent of how it is laid out.

The ledger keeps every author string exactly as written, in order, with repeats, plus
the bytes of each asset. Moving or resizing an image leaves it unchanged; losing,
repeating, reordering or rewording anything does not. Text the renderers generate (a
table of contents, figure numbers) is not part of it.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any, Iterable, List, Optional, Tuple

from pydantic import BaseModel

from .normalize import _NON_TEXT_FIELDS

# How a block is presented, not what it says. An image's size and place belong here.
PRESENTATION_FIELDS = {"id", "hints", "placement", "treatment", "width", "height", "alignment", "border",
                       "shadow", "intent", "lang"}
_META_FIELDS = ("title", "subject", "author", "language")
_LIVE = ("{page}", "{pages}", "{section}", "{chapter}", "{date}")


@dataclass(frozen=True)
class LedgerEntry:
    block: int
    node_id: Optional[str]
    block_type: str
    kind: str                # the field the text came from: text, caption, alt_text, source ...
    text: str


@dataclass(frozen=True)
class ContentLedger:
    entries: Tuple[LedgerEntry, ...]
    block_digests: Tuple[Tuple[int, str, str], ...]     # block, type, digest of its content
    meta: Tuple[Tuple[str, str], ...]
    bands: Tuple[str, ...]                              # band items as declared
    band_texts: Tuple[str, ...]                         # those with fixed text, fields filled in
    assets: Tuple[Tuple[str, str], ...]                 # where an asset is used, sha256 of its bytes

    def fingerprint(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), ensure_ascii=False, sort_keys=True).encode()).hexdigest()

    def strings(self, kinds: Optional[Iterable[str]] = None) -> List[str]:
        wanted = set(kinds) if kinds is not None else None
        return [e.text for e in self.entries if wanted is None or e.kind in wanted]

    def diff(self, other: "ContentLedger") -> List[str]:
        """How ``other`` departs from this ledger; empty when they say the same thing."""
        out: List[str] = []
        mine, theirs = [_key(e) for e in self.entries], [_key(e) for e in other.entries]
        have, got = Counter(mine), Counter(theirs)
        out += [f"lost: {k[1]} {k[2][:60]!r}" for k in (have - got)]
        out += [f"added: {k[1]} {k[2][:60]!r}" for k in (got - have)]
        if not out and mine != theirs:
            out.append("reordered: the same text in a different order")
        if not out and self.block_digests != other.block_digests:
            out.append("changed: a block's content differs")
        for name in ("meta", "bands", "assets"):
            if getattr(self, name) != getattr(other, name):
                out.append(f"changed: {name}")
        return out


def _key(e: LedgerEntry) -> Tuple[str, str, str]:
    return (e.block_type, e.kind, e.text)


def _fields(value: Any, key: Optional[str] = None, owner: str = "text") -> Iterable[Tuple[str, str]]:
    """Each author string with the name of the field it sits in."""
    if key in _NON_TEXT_FIELDS:
        return
    if isinstance(value, str):
        if value.strip():
            yield owner, value
    elif isinstance(value, BaseModel):
        for k in type(value).model_fields:
            yield from _fields(getattr(value, k), k, k)
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from _fields(v, k if isinstance(k, str) else None, k if isinstance(k, str) else owner)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _fields(v, None, owner)


def _digest(block: BaseModel) -> str:
    content = block.model_dump(mode="json", exclude=PRESENTATION_FIELDS)
    return hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def _asset_hash(src: str, assets) -> str:
    from ..media import ingest
    from ..utils.errors import DynamicPDFError
    try:
        return ingest(src, assets).sha256
    except (DynamicPDFError, OSError, ValueError):
        return "unreadable"


def _band_items(system) -> List[Any]:
    from ..schema.page_system import Logo
    heads, feet = system.bands()
    out: List[Any] = []
    for band in heads + feet:
        for row in band.rows:
            for name in ("left", "center", "right", "start", "end"):
                out += getattr(row, name)
    return [i for i in dict.fromkeys(i.src if isinstance(i, Logo) else i for i in out)]


def build_content_ledger(doc, assets=None, theme=None) -> ContentLedger:
    """The ledger of ``doc``. ``assets`` is the asset policy files are read under."""
    if assets is None:
        from ..policy import RenderPolicy
        assets = RenderPolicy().assets
    entries, digests, hashes = [], [], []
    for i, block in enumerate(doc.blocks):
        kind = getattr(block, "type", "")
        entries += [LedgerEntry(i, getattr(block, "id", None), kind, field, text)
                    for field, text in _fields(block)]
        digests.append((i, kind, _digest(block)))
        if kind == "image":
            hashes.append((f"block:{i}", _asset_hash(block.src, assets)))
        elif kind == "image_text_panel":
            hashes.append((f"block:{i}", _asset_hash(block.image.src, assets)))
    meta = tuple((name, str(getattr(doc.meta, name, "") or "")) for name in _META_FIELDS)
    bands, band_texts = (), ()
    system = doc.meta.page_system
    if system is not None:
        from ..design.page_values import band_values
        from ..layout.page_system import fill_fields
        from ..schema.page_system import Logo
        heads, feet = system.bands()
        logos = dict.fromkeys(i.src for band in heads + feet for row in band.rows
                              for name in ("left", "center", "right", "start", "end")
                              for i in getattr(row, name) if isinstance(i, Logo))
        hashes += [(f"logo:{src}", _asset_hash(src, assets)) for src in logos]
        bands = tuple(i for i in _band_items(system) if i not in logos)
        values = band_values(doc, theme.header_footer if theme is not None else None)[0]
        band_texts = tuple(filled for filled in (fill_fields(i, values) for i in bands
                                                 if not any(f in i for f in _LIVE)) if filled)
    return ContentLedger(tuple(entries), tuple(digests), meta, bands, band_texts, tuple(hashes))
