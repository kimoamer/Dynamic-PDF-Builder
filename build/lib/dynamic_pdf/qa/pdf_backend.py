"""
The one way QA and the variant gates read a rendered PDF (F16).

PyMuPDF (AGPL) is preferred when installed, so existing results do not change. Without it,
PDFium through ``pypdfium2`` (BSD-3/Apache-2.0, ``pip install "dynamic-pdf-builder[qa-permissive]"``)
gives the same measures: text lines with fonts and boxes, images, vector shapes, internal
links, paint order and greyscale rasters. With neither, ``open_pdf`` raises ``ImportError``,
which every caller already reports as "not verified".

Pages speak PyMuPDF's shapes (``text_dict()`` is ``get_text("dict")``, ``rawdict()`` is
``get_text("rawdict")``), so the checks read the same structure from either backend. Boxes
are (x0, y0, x1, y1) in points from the top-left corner.
"""
from __future__ import annotations

import ctypes
import os
import unicodedata
from typing import Iterator, List, Optional, Tuple

Box = Tuple[float, float, float, float]
_FORCE = "QA_BACKEND"        # DYNAMIC_PDF_QA_BACKEND: "pymupdf" or "pdfium" pins one, e.g. to compare them


def backend_name() -> Optional[str]:
    """The backend ``open_pdf`` would use, or None when no PDF reader is installed."""
    from ..settings import get
    want = (get(_FORCE) or "").lower()
    for name, module in (("pymupdf", "pymupdf"), ("pdfium", "pypdfium2")):
        if want and want != name:
            continue
        try:
            __import__(module)
            return name
        except ImportError:
            continue
    return None


def open_pdf(data: bytes) -> "Document":
    name = backend_name()
    if name == "pymupdf":
        return _MuDocument(data)
    if name == "pdfium":
        return _PdfiumDocument(data)
    raise ImportError('Reading PDF pages needs PyMuPDF or pypdfium2: '
                      'pip install "dynamic-pdf-builder[qa-permissive]"')


class Document:
    page_count: int

    def __len__(self) -> int:
        return self.page_count

    def __iter__(self) -> Iterator["Page"]:
        return (self[i] for i in range(self.page_count))

    def __getitem__(self, i: int) -> "Page":
        raise NotImplementedError

    def text(self) -> str:
        return "\n".join(p.text() for p in self)

    def close(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class Page:
    width: float
    height: float

    def text(self) -> str: ...
    def text_dict(self) -> dict: ...
    def rawdict(self) -> dict: ...
    def drawings(self) -> List[Box]: ...
    def fills(self) -> List[Box]: ...                      # boxes of filled paths (panels, bands, rules)
    def images(self) -> List[dict]: ...                     # bbox, transform, width, height
    def paint_log(self) -> List[Tuple[str, Box]]: ...      # ("fill-text" | "fill-image", box) in paint order
    def link_targets(self) -> List[int]: ...               # internal links' page index, -1 if unresolved
    def gray(self, zoom: float, clip: Optional[Box] = None) -> Tuple[int, int, bytes]: ...
    def rgb(self, zoom: float) -> Tuple[int, int, bytes]: ...                # the whole page

    def save_png(self, path: str, dpi: int) -> None: ...

    def clip(self, box: Box) -> Optional[Box]:
        """``box`` cut to the page, or None when nothing of it is on the page."""
        x0, y0 = max(box[0], 0.0), max(box[1], 0.0)
        x1, y1 = min(box[2], self.width), min(box[3], self.height)
        return (x0, y0, x1, y1) if x1 > x0 and y1 > y0 else None


# ── PyMuPDF ──────────────────────────────────────────────────────────────

class _MuDocument(Document):
    def __init__(self, data: bytes):
        import pymupdf
        self._m = pymupdf
        self._doc = pymupdf.open(stream=data, filetype="pdf")
        self.page_count = self._doc.page_count

    def __getitem__(self, i):
        return _MuPage(self._doc[i], self._m)

    def close(self):
        self._doc.close()


class _MuPage(Page):
    def __init__(self, page, m):
        self._p, self._m = page, m
        self.width, self.height = page.rect.width, page.rect.height

    def text(self):
        return self._p.get_text()

    def text_dict(self):
        return self._p.get_text("dict")

    def rawdict(self):
        return self._p.get_text("rawdict")

    def drawings(self):
        return [tuple(d["rect"]) for d in self._p.get_drawings()]

    def fills(self):
        return [tuple(d["rect"]) for d in self._p.get_drawings() if d.get("fill") is not None]

    def images(self):
        return self._p.get_image_info()

    def paint_log(self):
        return [(kind, tuple(rect)) for kind, rect in self._p.get_bboxlog()]

    def link_targets(self):
        return [ln.get("page", -1) for ln in self._p.get_links() if ln.get("kind") == 1]

    def gray(self, zoom, clip=None):
        m = self._m
        kw = {"clip": m.Rect(clip)} if clip else {}
        pix = self._p.get_pixmap(matrix=m.Matrix(zoom, zoom), colorspace=m.csGRAY, alpha=False, **kw)
        return pix.width, pix.height, pix.samples

    def rgb(self, zoom):
        pix = self._p.get_pixmap(matrix=self._m.Matrix(zoom, zoom), colorspace=self._m.csRGB, alpha=False)
        return pix.width, pix.height, pix.samples

    def save_png(self, path, dpi):
        self._p.get_pixmap(dpi=dpi).save(path)


# ── PDFium (pypdfium2) ───────────────────────────────────────────────────

class _PdfiumDocument(Document):
    def __init__(self, data: bytes):
        import pypdfium2
        self._doc = pypdfium2.PdfDocument(data)
        self.page_count = len(self._doc)

    def __getitem__(self, i):
        return _PdfiumPage(self._doc, self._doc[i])

    def close(self):
        self._doc.close()


class _PdfiumPage(Page):
    def __init__(self, doc, page):
        import pypdfium2.raw as raw
        self._raw, self._doc, self._p = raw, doc, page
        self.width, self.height = page.get_size()
        self._tp = None

    def _textpage(self):
        if self._tp is None:
            self._tp = self._p.get_textpage()
        return self._tp

    def _box(self, l, b, r, t) -> Box:                    # PDF space -> top-left points
        return (l, self.height - t, r, self.height - b)

    def text(self):
        # PDFium joins a word broken at a line-end hyphen with U+FFFE; give it back as MuPDF does
        return self._textpage().get_text_range().replace("\r\n", "\n").replace("\ufffe", "-\n")

    def _chars(self):
        """(char, box or None, font, size, colour) per character, in content order."""
        raw, tp = self._raw, self._textpage()
        h = tp.raw
        l, r, b, t = (ctypes.c_double() for _ in range(4))
        cr, cg, cb, ca = (ctypes.c_uint() for _ in range(4))
        flags = ctypes.c_int()
        buf = ctypes.create_string_buffer(256)
        fonts = {}
        out = []
        for i in range(tp.count_chars()):
            code = raw.FPDFText_GetUnicode(h, i)
            ch = "-" if code == 2 else chr(code or 0xFFFD)      # PDFium reports a line-end hyphen as U+0002
            box = None
            if not raw.FPDFText_IsGenerated(h, i) and raw.FPDFText_GetCharBox(
                    h, i, ctypes.byref(l), ctypes.byref(r), ctypes.byref(b), ctypes.byref(t)):
                box = self._box(l.value, b.value, r.value, t.value)
            n = raw.FPDFText_GetFontInfo(h, i, buf, len(buf), ctypes.byref(flags))
            name = buf.raw[:max(0, n - 1)].decode("utf-8", "replace")
            font = fonts.setdefault(name, name.split("+", 1)[1] if name[6:7] == "+" else name)
            colour = 0
            if raw.FPDFText_GetFillColor(h, i, ctypes.byref(cr), ctypes.byref(cg), ctypes.byref(cb), ctypes.byref(ca)):
                colour = (cr.value << 16) | (cg.value << 8) | cb.value
            out.append((ch, box, font, round(raw.FPDFText_GetFontSize(h, i), 2), colour))
        return out

    def _lines(self):
        """Characters grouped into lines (PDFium marks line ends) and spans (font, size, colour)."""
        lines, cur = [], []
        for c in self._chars():
            ch, box = c[0], c[1]
            if ch in "\r\n":
                if cur:
                    lines.append(cur)
                cur = []
                continue
            if box is not None and cur and not unicodedata.combining(ch):     # a mark sits on its letter
                boxes = [x[1] for x in cur if x[1] is not None and not unicodedata.combining(x[0])]
                if boxes:
                    top, bottom = min(x[1] for x in boxes), max(x[3] for x in boxes)
                    # clear of the line, drawn far back to its left (marks step back a little), or a
                    # wide jump ahead, as into the next table cell
                    size = max(c[3], 1)
                    if (box[1] >= bottom or box[3] <= top or box[0] < boxes[-1][0] - 2 * size
                            or box[0] > boxes[-1][2] + 1.5 * size):
                        lines.append(cur)
                        cur = []
            cur.append(c)
        if cur:
            lines.append(cur)
        return lines

    @staticmethod
    def _union(boxes) -> Box:
        return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))

    def _dicts(self, raw_chars: bool):
        blocks = []
        for line in self._lines():
            spans = []
            for c in line:
                key = c[2:]
                if not spans or spans[-1]["_key"] != key:
                    spans.append({"_key": key, "font": c[2], "size": c[3], "color": c[4], "flags": 0, "items": []})
                spans[-1]["items"].append(c)
            out_spans = []
            for s in spans:
                boxes = [c[1] for c in s["items"] if c[1] is not None]
                if not boxes:
                    if out_spans:                              # a generated space joins the span before it
                        _append(out_spans[-1], s["items"], raw_chars)
                    continue
                span = {k: s[k] for k in ("font", "size", "color", "flags")}
                span["bbox"] = self._union(boxes)
                span["text" if not raw_chars else "chars"] = "" if not raw_chars else []
                _append(span, s["items"], raw_chars)
                out_spans.append(span)
            if out_spans:
                bbox = self._union([s["bbox"] for s in out_spans])
                blocks.append({"type": 0, "bbox": bbox, "lines": [{"bbox": bbox, "spans": out_spans}]})
        for info in self.images():
            blocks.append({"type": 1, "bbox": info["bbox"]})
        return {"width": self.width, "height": self.height, "blocks": blocks}

    def text_dict(self):
        return self._dicts(False)

    def rawdict(self):
        return self._dicts(True)

    def _objects(self, kind):
        return list(self._p.get_objects(filter=[kind]))

    def drawings(self):
        return [self._box(*o.get_bounds()) for o in self._objects(self._raw.FPDF_PAGEOBJ_PATH)]

    def fills(self):
        raw, out = self._raw, []
        mode, stroke = ctypes.c_int(), ctypes.c_int()
        for o in self._objects(raw.FPDF_PAGEOBJ_PATH):
            if raw.FPDFPath_GetDrawMode(o.raw, ctypes.byref(mode), ctypes.byref(stroke)) and \
                    mode.value != raw.FPDF_FILLMODE_NONE:
                out.append(self._box(*o.get_bounds()))
        return out

    def images(self):
        out = []
        for o in self._objects(self._raw.FPDF_PAGEOBJ_IMAGE):
            m = o.get_matrix()
            w, h = o.get_px_size()
            out.append({"bbox": self._box(*o.get_bounds()), "transform": (m.a, m.b, m.c, m.d, m.e, m.f),
                        "width": w, "height": h})
        return out

    def paint_log(self):
        raw = self._raw
        kinds = {raw.FPDF_PAGEOBJ_TEXT: "fill-text", raw.FPDF_PAGEOBJ_IMAGE: "fill-image"}
        return [(kinds[o.type], self._box(*o.get_bounds())) for o in self._p.get_objects() if o.type in kinds]

    def link_targets(self):
        raw, doc = self._raw, self._doc.raw
        out = []
        pos, link = ctypes.c_int(0), raw.FPDF_LINK()
        while raw.FPDFLink_Enumerate(self._p.raw, ctypes.byref(pos), ctypes.byref(link)):
            dest = raw.FPDFLink_GetDest(doc, link)
            if not dest:
                action = raw.FPDFLink_GetAction(link)
                if not action or raw.FPDFAction_GetType(action) != raw.PDFACTION_GOTO:
                    continue                                   # a web or file link, not internal
                dest = raw.FPDFAction_GetDest(doc, action)
            out.append(raw.FPDFDest_GetDestPageIndex(doc, dest) if dest else -1)
        return out

    def _render(self, zoom, clip=None, gray=True):
        crop = (0, 0, 0, 0)
        if clip:
            x0, y0, x1, y1 = clip
            crop = (x0, self.height - y1, self.width - x1, y0)
        return self._p.render(scale=zoom, crop=crop, grayscale=gray).to_pil()

    def gray(self, zoom, clip=None):
        img = self._render(zoom, clip).convert("L")
        return img.width, img.height, img.tobytes()

    def rgb(self, zoom):
        img = self._render(zoom, gray=False).convert("RGB")
        return img.width, img.height, img.tobytes()

    def save_png(self, path, dpi):
        self._render(dpi / 72.0, gray=False).convert("RGB").save(path)


def _append(span: dict, items, raw_chars: bool) -> None:
    if raw_chars:
        span["chars"] += [{"c": c[0], "bbox": c[1] or span["bbox"]} for c in items]
    else:
        span["text"] += "".join(c[0] for c in items)
