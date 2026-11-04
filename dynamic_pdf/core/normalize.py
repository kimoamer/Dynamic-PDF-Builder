"""
Normalization: any input (Markdown, JSON, fluent API) → ``SemanticDocument``.

The semantic document is the single, renderer-independent contract consumed by
the design layer (profile selection, recipes) and by every renderer (PDF,
DOCX). Normalization never rewrites or drops author content; it only:

* deep-copies blocks (the caller's document is never mutated),
* coerces loose inputs (plain-string list items / layout children, JSON dicts)
  into typed models,
* assigns stable, unique heading IDs (used for TOC links and bookmarks),
* resolves text direction per document,
* computes an outline, content statistics and a provenance hash.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Any, Dict, Iterable, List, Optional

from pydantic import BaseModel, Field, TypeAdapter

from ..schema.blocks import Block, ListItemModel, ParagraphBlock
from ..schema.document import Document, Meta
from .inline import plain_text

RTL_LANGS = {"ar", "he", "fa", "ur", "ps", "sd", "yi", "dv", "ckb"}

# Fields that never carry author-visible text
_NON_TEXT_FIELDS = {
    "type", "id", "lang", "color", "bg_color", "fill_color", "stroke_color", "text_color",
    "border_color", "score_color", "style", "variant", "alignment", "src", "logo", "language",
    "format", "marker_style", "icon", "shape_type", "layout", "position", "sidebar_position",
    "chart_type", "diagram_type", "direction", "error_correction", "colors", "orientation",
    "doi", "key", "highlight_lines", "stroke_dash", "background", "hints",
}

_block_adapter = TypeAdapter(Block)


class OutlineEntry(BaseModel):
    id: str
    level: int
    text: str
    block_index: int


class ContentStats(BaseModel):
    words: int = 0
    blocks: int = 0
    headings: int = 0
    max_heading_level: int = 0
    paragraphs: int = 0
    tables: int = 0
    table_rows: int = 0
    max_table_cols: int = 0
    figures: int = 0
    charts: int = 0
    diagrams: int = 0
    code_blocks: int = 0
    lists: int = 0
    math: int = 0
    callouts: int = 0
    metrics: int = 0
    footnotes: int = 0
    citations: int = 0
    bibliography_entries: int = 0
    has_cover: bool = False
    has_toc: bool = False
    has_abstract: bool = False
    has_signature: bool = False
    rtl_ratio: float = 0.0
    numeric_ratio: float = 0.0
    bilingual: bool = False             # substantial Latin *and* RTL-script text          # share of numeric tokens in table cells + metrics
    heading_texts: List[str] = Field(default_factory=list)
    table_headers: List[str] = Field(default_factory=list)
    row_labels: List[str] = Field(default_factory=list)     # first-column cells (line items)
    first_paragraph: str = ""
    last_paragraphs: List[str] = Field(default_factory=list)


class Provenance(BaseModel):
    source_kind: str = "api"            # "markdown" | "json" | "api"
    source_sha256: Optional[str] = None
    content_sha256: str = ""


class SemanticDocument(BaseModel):
    meta: Meta
    theme: str
    blocks: List[Any]
    outline: List[OutlineEntry]
    stats: ContentStats
    direction: str                      # "ltr" | "rtl"
    language: str
    front_matter: Dict[str, Any] = Field(default_factory=dict)
    provenance: Provenance = Field(default_factory=Provenance)

    def to_document(self) -> Document:
        return Document(meta=self.meta, theme=self.theme, blocks=self.blocks)

    def all_text(self) -> List[str]:
        out: List[str] = []
        for b in self.blocks:
            out.extend(block_text(b))
        return out


# ─────────────────────────── text extraction ───────────────────────────

def _walk_text(value: Any, key: Optional[str] = None) -> Iterable[str]:
    if key in _NON_TEXT_FIELDS:
        return
    if isinstance(value, str):
        if value.strip():
            yield value
    elif isinstance(value, BaseModel):
        for k in type(value).model_fields:
            yield from _walk_text(getattr(value, k), k)
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from _walk_text(v, k if isinstance(k, str) else None)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _walk_text(v)


def block_text(block: Any) -> List[str]:
    """All author-visible text strings of a block (recursively, incl. children)."""
    return list(_walk_text(block))


# ─────────────────────────── helpers ───────────────────────────

def is_rtl_text(text: str) -> bool:
    """Paragraph direction by the Unicode first-strong-character rule (UAX #9
    P2/P3, as Word and HTML ``dir=auto`` do): mixed text such as
    "Revenue / الإيرادات" stays LTR, "الإيرادات (SAR 4.2bn)" is RTL."""
    for ch in text or "":
        d = unicodedata.bidirectional(ch)
        if d == "L":
            return False
        if d in ("R", "AL"):
            return True
    return False


def _slug(text: str) -> str:
    s = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s[:60]


def _coerce_items(items: list) -> list:
    out = []
    for it in items:
        if isinstance(it, ListItemModel):
            out.append(it.model_copy(update={"children": _coerce_items(it.children)}))
        elif isinstance(it, dict):
            out.append(ListItemModel.model_validate(it))
        else:
            out.append(it)
    return out


def coerce_child(b: Any):
    if isinstance(b, str):
        return ParagraphBlock(text=b)
    if isinstance(b, dict):
        return _block_adapter.validate_python(b)
    return b


def _normalize_block(block: Any):
    b = block.model_copy(deep=True)
    t = getattr(b, "type", None)
    if t in ("bullet_list", "numbered_list"):
        b.items = _coerce_items(b.items)
    elif t == "two_column":
        b.left = [_normalize_block(coerce_child(x)) for x in b.left]
        b.right = [_normalize_block(coerce_child(x)) for x in b.right]
    elif t == "three_column":
        b.columns = [[_normalize_block(coerce_child(x)) for x in col] for col in b.columns]
    elif t == "sidebar":
        b.main_content = [_normalize_block(coerce_child(x)) for x in b.main_content]
        b.sidebar_content = [_normalize_block(coerce_child(x)) for x in b.sidebar_content]
    return b


def _is_number(s: str) -> bool:
    return bool(re.fullmatch(r"[\s$€£¥%+\-−(),.\d٠-٩]+", s or "")) and any(c.isdigit() for c in s)


# ─────────────────────────── main entry ───────────────────────────

def normalize(document: Document, *, source_kind: str = "api",
              source_text: Optional[str] = None,
              front_matter: Optional[Dict[str, Any]] = None) -> SemanticDocument:
    blocks = [_normalize_block(b) for b in document.blocks]

    stats = ContentStats(blocks=len(blocks))
    outline: List[OutlineEntry] = []
    used_ids = set()
    words = rtl_chars = alpha_chars = 0
    numeric = cells = 0

    for i, b in enumerate(blocks):
        t = b.type
        texts = block_text(b)
        for s in texts:
            p = plain_text(s) if "\n" not in s or t != "code" else s
            words += len(p.split())
            for ch in p:
                if ch.isalpha():
                    alpha_chars += 1
                    if unicodedata.bidirectional(ch) in ("R", "AL"):
                        rtl_chars += 1
        if t in ("heading", "section_opener", "performance_page"):
            level = b.level if t == "heading" else 1
            stats.headings += 1
            stats.max_heading_level = max(stats.max_heading_level, level)
            text = plain_text(b.text if t == "heading" else b.title)
            stats.heading_texts.append(text)
            hid = b.id or _slug(text) or f"section-{i + 1}"
            base, n = hid, 2
            while hid in used_ids:
                hid = f"{base}-{n}"
                n += 1
            used_ids.add(hid)
            b.id = hid
            outline.append(OutlineEntry(id=hid, level=level, text=text, block_index=i))
            if t == "performance_page":
                stats.metrics += 1
        elif t in ("paragraph", "rich_text", "note"):
            stats.paragraphs += 1
            ptxt = plain_text(b.text)
            if not stats.first_paragraph:
                stats.first_paragraph = ptxt[:200]
            stats.last_paragraphs = (stats.last_paragraphs + [ptxt[:200]])[-3:]
        elif t == "table":
            stats.tables += 1
            stats.table_headers.extend(plain_text(h) for h in (b.headers or []))
            stats.row_labels.extend(plain_text(str(r[c])) for r in b.rows[:200]
                                    for c in range(min(2, len(r))))
            stats.table_rows += len(b.rows)
            stats.max_table_cols = max(stats.max_table_cols, len(b.headers or []),
                                       *(len(r) for r in b.rows)) if b.rows else max(
                stats.max_table_cols, len(b.headers or []))
            for row in b.rows:
                for c in row:
                    cells += 1
                    numeric += _is_number(str(c))
        elif t == "parallel_ledger":
            stats.tables += 1
            stats.table_rows += sum(len(s.rows) for s in b.sections)
        elif t == "image":
            stats.figures += 1
        elif t == "chart":
            stats.charts += 1
        elif t in ("diagram", "mermaid"):
            stats.diagrams += 1
        elif t == "code":
            stats.code_blocks += 1
        elif t in ("bullet_list", "numbered_list", "checklist", "definition_list"):
            stats.lists += 1
        elif t == "math":
            stats.math += 1
        elif t == "callout":
            stats.callouts += 1
        elif t in ("metric_row", "score_display", "progress_bar"):
            stats.metrics += 1
            if t == "metric_row":
                for m in b.metrics:
                    cells += 1
                    numeric += _is_number(m.value)
        elif t == "footnote":
            stats.footnotes += 1
        elif t == "citation":
            stats.citations += 1
        elif t == "bibliography":
            stats.bibliography_entries += len(b.entries)
        elif t == "cover_page":
            stats.has_cover = True
        elif t == "table_of_contents":
            stats.has_toc = True
        elif t == "abstract":
            stats.has_abstract = True
        elif t == "signature":
            stats.has_signature = True

    stats.words = words
    stats.rtl_ratio = round(rtl_chars / alpha_chars, 3) if alpha_chars else 0.0
    stats.numeric_ratio = round(numeric / cells, 3) if cells else 0.0
    stats.bilingual = 0.12 <= stats.rtl_ratio <= 0.88

    meta = document.meta.model_copy(deep=True)
    lang = (meta.language or "en").split("-")[0].lower()
    explicit = getattr(meta, "direction", None)
    if explicit in ("ltr", "rtl"):
        direction = explicit
    elif meta.rtl or lang in RTL_LANGS or stats.rtl_ratio > 0.7:
        direction = "rtl"
    else:
        direction = "ltr"

    content_hash = hashlib.sha256(json.dumps(
        [b.model_dump(mode="json") for b in document.blocks],
        sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    prov = Provenance(
        source_kind=source_kind,
        source_sha256=hashlib.sha256(source_text.encode()).hexdigest() if source_text else None,
        content_sha256=content_hash,
    )
    return SemanticDocument(
        meta=meta, theme=document.theme, blocks=blocks, outline=outline, stats=stats,
        direction=direction, language=lang, front_matter=dict(front_matter or {}),
        provenance=prov,
    )
