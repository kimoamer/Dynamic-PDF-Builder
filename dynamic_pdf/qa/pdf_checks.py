"""
PDF layout checks on the real output (PyMuPDF text/image geometry).

Detects: text/images clipped off the page, content overflowing into the side
margins, overlapping text lines, accidental blank pages, headings stranded at
a page bottom, replacement/missing glyphs and broken internal links.
"""
from __future__ import annotations

from typing import List, Optional

from .report import ERROR, WARNING, Finding, QAReport, sha256


def _require_pymupdf():
    try:
        import pymupdf
        return pymupdf
    except ImportError as e:   # pragma: no cover
        from ..utils.errors import DynamicPDFError
        raise DynamicPDFError('Visual QA requires PyMuPDF: pip install "dynamic-pdf-builder[qa]"') from e


def _overlap(a, b) -> float:
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    if x1 <= x0 or y1 <= y0:
        return 0.0
    inter = (x1 - x0) * (y1 - y0)
    smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1])) or 1.0
    return inter / smaller


def check_pdf(data: bytes, *, margins: Optional[dict] = None, heading_texts: Optional[List[str]] = None,
              tolerance: float = 2.0, fmt: str = "pdf") -> QAReport:
    pymupdf = _require_pymupdf()
    doc = pymupdf.open(stream=data, filetype="pdf")
    rep = QAReport(format=fmt, pages=doc.page_count, sha256=sha256(data))
    headings = {h.strip() for h in (heading_texts or []) if h.strip()}
    margins = margins or {}

    for pno, page in enumerate(doc, start=1):
        W, H = page.rect.width, page.rect.height
        left = margins.get("left", 0) - tolerance
        right = W - margins.get("right", 0) + tolerance
        d = page.get_text("dict")
        lines = []
        has_image = False
        for bl in d["blocks"]:
            if bl.get("type") == 1:
                has_image = True
                x0, y0, x1, y1 = bl["bbox"]
                if x0 < -tolerance or y0 < -tolerance or x1 > W + tolerance or y1 > H + tolerance:
                    rep.findings.append(Finding(severity=ERROR, code="clipped_image", page=pno,
                                                bbox=bl["bbox"], format=fmt,
                                                message="image extends beyond the page edge", fixable=True))
                continue
            for ln in bl.get("lines", []):
                txt = "".join(s["text"] for s in ln["spans"])
                if not txt.strip():
                    continue
                lines.append((ln["bbox"], txt, max(s["size"] for s in ln["spans"])))
                if "�" in txt:
                    rep.findings.append(Finding(severity=ERROR, code="missing_glyph", page=pno,
                                                format=fmt, text=txt.strip()[:80],
                                                message="replacement character in output text"))
        for bbox, txt, size in lines:
            x0, y0, x1, y1 = bbox
            if x0 < -tolerance or x1 > W + tolerance or y0 < -tolerance or y1 > H + tolerance:
                rep.findings.append(Finding(severity=ERROR, code="clipped_text", page=pno, bbox=bbox,
                                            text=txt.strip()[:120], format=fmt, fixable=True,
                                            message=f"text runs off the page: {txt.strip()[:40]!r}"))
            elif margins and (x1 > right or x0 < left) and 40 < y0 < H - 40:
                rep.findings.append(Finding(severity=ERROR, code="overflow", page=pno, bbox=bbox,
                                            text=txt.strip()[:120], format=fmt, fixable=True,
                                            message=f"text overflows into the margin by "
                                                    f"{max(x1 - right, left - x0):.0f}pt: {txt.strip()[:40]!r}"))
        # overlapping text lines (different lines drawn on top of each other)
        for i in range(len(lines)):
            for j in range(i + 1, len(lines)):
                a, b = lines[i][0], lines[j][0]
                if abs(a[1] - b[1]) < 0.5 and abs(a[0] - b[0]) < 0.5:
                    continue          # same line split into two dict lines
                if _overlap(a, b) > 0.35:
                    rep.findings.append(Finding(
                        severity=ERROR, code="overlap", page=pno, bbox=a, format=fmt,
                        text=lines[i][1].strip()[:80],
                        message=f"text overlaps: {lines[i][1].strip()[:30]!r} / {lines[j][1].strip()[:30]!r}"))
        body = [ln for ln in lines if 40 < ln[0][1] < H - 50]
        if not body and not has_image and doc.page_count > 1:
            rep.findings.append(Finding(severity=ERROR, code="blank_page", page=pno, format=fmt,
                                        fixable=True, message="page has no content"))
        if body and pno < doc.page_count:
            last = max(body, key=lambda ln: ln[0][3])
            if last[1].strip() in headings or any(last[1].strip().endswith(h) for h in headings if len(h) > 3):
                rep.findings.append(Finding(severity=ERROR, code="stranded_heading", page=pno,
                                            bbox=last[0], text=last[1].strip(), format=fmt, fixable=True,
                                            message=f"heading {last[1].strip()[:40]!r} is the last line on its page"))
        for link in page.get_links():
            if link.get("kind") == 1 and not (0 <= link.get("page", -1) < doc.page_count):
                rep.findings.append(Finding(severity=ERROR, code="broken_link", page=pno, format=fmt,
                                            message="internal link points to a missing page"))
    return rep
