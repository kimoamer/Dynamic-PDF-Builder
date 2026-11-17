"""
Proof that a rendered document still says what its source says.

Four layers are checked, each only as far as it can be: the source itself, the placed
fragments, the DOCX XML and the PDF text. A layer reports ``verified``, ``failed`` or
``unknown``. Text extraction cannot be trusted with shaped Arabic, so a difference
there is ``unknown``: neither a pass nor a proven loss.
"""

from __future__ import annotations

import io
import re
import unicodedata
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from typing import List, Optional, Sequence
from xml.etree import ElementTree

from ..core.content_ledger import ContentLedger
from ..core.inline import parse_inline, plain_text

VERIFIED, FAILED, UNKNOWN = "verified", "failed", "unknown"
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"
_MC_FALLBACK = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"
_R_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
# Western and Arabic-Indic digits are never one number: extraction sets neighbouring table cells
# side by side without a space, and "99" beside "٨" must not read as a third number
_LATIN = re.compile(r"[A-Za-z]{2,}|[0-9]+|[٠-٩]+")
_INDIC = "٠١٢٣٤٥٦٧٨٩"
_ARABIC = re.compile(r"[ء-يٱ-ۓ]{2,}")
_ARABIC_ANY = re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")
_FLOW_TYPES = {"paragraph", "heading"}
_SHOWN_TYPES = _FLOW_TYPES | {"bullet_list", "numbered_list", "checklist", "table", "image", "quote", "note",
                              "callout"}
_HIDDEN_KINDS = {"alt_text"}
_NO_REGION = {"page_break", "spacer", "watermark", "divider"}
_SHORT = 20         # shorter strings occur inside other text, so a surplus proves nothing


@dataclass
class LayerResult:
    name: str
    status: str
    details: List[str] = field(default_factory=list)


@dataclass
class PreservationReport:
    layers: List[LayerResult]

    @property
    def status(self) -> str:
        found = {x.status for x in self.layers}
        if FAILED in found:
            return FAILED
        return UNKNOWN if UNKNOWN in found or not self.layers else VERIFIED

    def layer(self, name: str) -> Optional[LayerResult]:
        return next((x for x in self.layers if x.name == name), None)

    def to_dict(self) -> dict:
        return {"status": self.status,
                "layers": {x.name: {"status": x.status, "details": x.details} for x in self.layers}}


def _result(name: str, failed: List[str], unsure: List[str]) -> LayerResult:
    if failed:
        return LayerResult(name, FAILED, failed[:12])
    return LayerResult(name, UNKNOWN if unsure else VERIFIED, unsure[:12])


def _squash(text: str) -> str:
    return " ".join(text.split())


def _as_set(text: str, ledger: ContentLedger) -> str:
    """The visible text of an author string: a ``{ref:id}`` reads as its label."""
    if "{ref:" in text and ledger.refs:
        from ..core.numbering import REF
        labels = dict(ledger.refs)
        text = REF.sub(lambda m: labels.get(m.group(1), m.group(0)), text)
    return plain_text(text)


def _shown(ledger: ContentLedger) -> List[tuple]:
    """Block type, kind and visible text of what readers are meant to see."""
    return [(e.block_type, e.kind, _squash(_as_set(e.text, ledger))) for e in ledger.entries
            if e.block_type in _SHOWN_TYPES and e.kind not in _HIDDEN_KINDS]


def check_source(ledger: ContentLedger, candidate: ContentLedger) -> LayerResult:
    return _result("source", ledger.diff(candidate), [])


def _set_length(text: str) -> int:
    """Characters of ``text`` as set: shaping joins some Arabic letter pairs into one."""
    if not _ARABIC_ANY.search(text):
        return len(text)
    from ..layout.factory import _apply_rtl
    return len(_apply_rtl(text))


def check_fragments(ledger: ContentLedger, geometry) -> LayerResult:
    """Every block was placed, once, and its pieces add up to its text."""
    failed: List[str] = []
    unsure: List[str] = []
    placed = {b for r in geometry.regions for b in (r.block, *r.extra_blocks)}
    for block, kind, _ in ledger.block_digests:
        if kind not in _NO_REGION and block not in placed:
            failed.append(f"block {block} ({kind}) was not placed")
    seen = Counter((r.page, r.block, round(r.top, 1), round(r.bottom, 1), round(r.x0, 1)) for r in geometry.regions
                   if r.chars)
    failed += [f"block {k[1]} was placed twice on page {k[0]}" for k, n in seen.items() if n > 1]
    for e in ledger.entries:
        if e.block_type != "paragraph" or e.kind != "text":
            continue
        pieces = geometry.fragments(e.block)
        if not pieces:
            unsure.append(f"block {e.block}: no text fragments were recorded")
            continue
        got, want = pieces[-1][2], _set_length(_as_set(e.text, ledger))
        if abs(got - want) <= len(pieces):
            continue
        message = f"block {e.block}: {got} characters placed, {want} in the source"
        (unsure if _ARABIC_ANY.search(e.text) else failed).append(message)
    return _result("fragments", failed, unsure)


def _paragraphs(root) -> List[str]:
    for parent in list(root.iter()):
        for child in list(parent):
            if child.tag == _MC_FALLBACK:
                parent.remove(child)
    breaks = {_W + "br", _W + "cr", _W + "tab"}
    # a Word footnote reference shows its number; a custom mark follows it as text
    numbers = {el: str(i) for i, el in enumerate(
        (r for r in root.iter(_W + "footnoteReference") if r.get(_W + "customMarkFollows") not in ("1", "true")), 1)}

    def piece(e) -> str:
        if e.tag in (_W + "t", _W + "delText"):        # a suggested removal is still on the page
            return e.text or ""
        return numbers.get(e, "") if e.tag == _W + "footnoteReference" else " "

    def text(p) -> str:              # a line break or tab between runs separates words
        return "".join(piece(e) for e in p.iter()
                       if e.tag in (_W + "t", _W + "delText", _W + "footnoteReference") or e.tag in breaks)
    return [_squash(text(p)) for p in root.iter(_W + "p")]


def _toc_entries(body) -> List[str]:
    """Texts of the contents-list entries (paragraph styles TOC1, TOC2 ...), numbers included."""
    out = []
    for p in body.iter(_W + "p"):
        style = p.find(f"{_W}pPr/{_W}pStyle")
        val = style.get(_W + "val", "") if style is not None else ""
        if re.fullmatch(r"TOC\d", val):
            out.append(_squash("".join(t.text or "" for t in p.iter(_W + "t"))))
    return out


def check_docx_content(ledger: ContentLedger, data: bytes) -> LayerResult:
    """The XML holds every string the expected number of times, the flow in order,
    with its images, alt text, links and band text."""
    failed: List[str] = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = z.namelist()
        body = ElementTree.fromstring(z.read("word/document.xml"))
        bands = [" ".join(_paragraphs(ElementTree.fromstring(z.read(n)))) for n in names
                 if re.fullmatch(r"word/(header|footer)\d*\.xml", n)]
        rels = z.read("word/_rels/document.xml.rels") if "word/_rels/document.xml.rels" in names else b""
    alts = [d.get("descr") or "" for d in body.iter(_WP + "docPr")]
    full = "\n".join(_paragraphs(body))
    shown = _shown(ledger)
    wanted = Counter(text for _, _, text in shown if text)
    # a contents list repeats the headings it lists, down to its depth: count its own entries
    entries = _toc_entries(body)
    headings = {text for kind, _, text in shown if kind in ("heading", "section_opener", "performance_page")}
    listed = Counter({h: sum(1 for e in entries if e == h or e.endswith(" " + h)) for h in headings})
    # and an opening page's strip lists the chapters
    listed.update(_squash(plain_text(e.text)) for e in ledger.entries if e.kind.startswith("chapters"))
    lines = Counter(full.split("\n"))
    for text, count in wanted.items():
        found = full.count(text) - listed[text]
        whole = lines[text] - listed[text]        # a phrase inside a sentence is no repeat
        if found < count:
            failed.append(f"expected {count}, found {found}: {text[:60]!r}")
        elif whole > count and len(text) >= _SHORT:
            failed.append(f"repeated: expected {count}, found {whole}: {text[:60]!r}")
    cursor = 0
    for kind, field_name, text in shown:
        if kind in _FLOW_TYPES and field_name == "text" and text:
            at = full.find(text, cursor)
            if at < 0:
                if text in full:
                    failed.append(f"out of order: {text[:60]!r}")
                continue
            cursor = at + len(text)
    for entry in ledger.entries:
        if entry.kind == "alt_text" and entry.text not in alts:
            failed.append(f"alt text missing: {entry.text[:60]!r}")
    images = sum(1 for e in ledger.block_digests if e[1] == "image")
    if len(alts) < images:
        failed.append(f"{images} images in the source, {len(alts)} drawings in the XML")
    targets = {r.get("Target") for r in ElementTree.fromstring(rels).iter(_R_NS + "Relationship")} if rels else set()
    for e in ledger.entries:
        if e.block_type in _SHOWN_TYPES:
            for run in parse_inline(e.text):
                if run.link and not run.link.startswith("#") and run.link not in targets:
                    failed.append(f"link missing: {run.link}")
    text_of_bands = " ".join(bands)
    failed += [f"band text missing: {t[:60]!r}" for t in ledger.band_texts if _squash(t) not in text_of_bands]
    return _result("docx", failed, [])


def _fold(text: str) -> str:
    """Forms and marks that PDF extraction changes without any loss."""
    return "".join(c for c in unicodedata.normalize("NFKC", text.lower()) if not unicodedata.combining(c))


# a page or column break between the two halves comes out as blank lines in between
_SOFT_BREAK = re.compile(r"(?<=[^\W\d_])-\n\s*(?=[^\W\d_])")


def _split_over_bands(text: str, word: str, need: int) -> int:
    """How many times ``word`` was hyphenated at a page or column end, with the running foot and
    head extracted between its halves ("estim-", "Page 3 of 4", "ated"): the first part ends a
    line with a hyphen and the rest starts a later line close after it."""
    found = 0
    for m in re.finditer(r"([^\W\d_]+)-\n", text):
        head = m.group(1).split()[-1] if m.group(1) else ""
        if found >= need or not head or not word.startswith(head) or len(head) >= len(word):
            continue
        tail = re.escape(word[len(head):])
        if re.search(rf"(?m)^\s*{tail}(?![^\W\d_])", text[m.end():m.end() + 400]):
            found += 1
    return found


def _dehyphenate(text: str) -> str:
    """Rejoin words that justified text broke at a hyphenation point ("ex-\\ncluded")."""
    return _SOFT_BREAK.sub("", text)


def _arabic_tokens(text: str) -> Counter:
    return Counter(min(w, w[::-1]) for w in _ARABIC.findall(_fold(text)))


def _either_way(word: str) -> str:
    """Arabic-Indic digits come out of PDF extraction reversed, as Arabic words do. The
    source check and the DOCX check still compare these numbers exactly."""
    return min(word, word[::-1]) if word[:1] in _INDIC else word


def check_pdf_content(ledger: ContentLedger, data: bytes, initials: Sequence[str] = ()) -> LayerResult:
    """The page text holds every word of the source. Extra words prove nothing here:
    bands and contents repeat text, which is why repeats are checked on the fragments."""
    from .pdf_backend import open_pdf
    try:
        pdf = open_pdf(data)
    except ImportError:
        return LayerResult("pdf", UNKNOWN, ["no PDF reader (PyMuPDF or pypdfium2) is installed"])
    with pdf:
        page_text = pdf.text()
    source = "\n".join([t for _, _, t in _shown(ledger)] + list(ledger.band_texts))
    folded = _fold(page_text)
    # either reading of a line-end hyphen: a hyphenation break, or the author's own hyphen
    have = (Counter(map(_either_way, _LATIN.findall(folded)))
            | Counter(map(_either_way, _LATIN.findall(_dehyphenate(folded)))))
    want = Counter(map(_either_way, _LATIN.findall(_fold(source))))
    for word in map(_fold, initials):             # a drop cap draws its letter apart from the word
        if have[word] < want[word] and word[1:] in folded:
            want[word] -= 1
    missing = want - have
    for word in list(missing):
        missing[word] -= _split_over_bands(folded, word, missing[word])
    failed = [f"missing {n}: {w!r}" for w, n in (+missing).items()]
    short = _arabic_tokens(source) - _arabic_tokens(page_text)
    unsure = [f"{sum(short.values())} Arabic words could not be matched in the extracted text"] if short else []
    return _result("pdf", failed, unsure)


def same_extracted_words(first: bytes, second: bytes) -> Optional[bool]:
    """Whether two PDFs use the same Arabic and Latin words. Shaping and extraction are
    the same on both sides, so this holds where a comparison with the source cannot.
    Counts and digits are left out: a shorter document repeats its bands and page
    numbers fewer times. None when no PDF reader is installed."""
    from .pdf_backend import backend_name, open_pdf
    if backend_name() is None:
        return None

    def words(data: bytes) -> set:
        with open_pdf(data) as pdf:
            text = _dehyphenate(pdf.text())
        return set(_arabic_tokens(text)) | {w for w in _LATIN.findall(_fold(text)) if w.isalpha()}
    return words(first) == words(second)


def check_preservation(ledger: ContentLedger, *, candidate: Optional[ContentLedger] = None, geometry=None,
                       pdf: Optional[bytes] = None, docx: Optional[bytes] = None,
                       initials: Sequence[str] = ()) -> PreservationReport:
    """Every layer the given artifacts allow. A layer with nothing to check is left out."""
    layers: List[LayerResult] = []
    if candidate is not None:
        layers.append(check_source(ledger, candidate))
    if geometry is not None:
        layers.append(check_fragments(ledger, geometry))
    if docx is not None:
        layers.append(check_docx_content(ledger, docx))
    if pdf is not None:
        layers.append(check_pdf_content(ledger, pdf, initials))
    return PreservationReport(layers)
