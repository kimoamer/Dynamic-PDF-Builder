"""
PDF layout checks on the real output (PyMuPDF text/image geometry).

Detects: text/images clipped off the page, content overflowing into the side
margins, overlapping text lines, accidental blank pages, headings stranded at
a page bottom, replacement/missing glyphs and broken internal links.
"""
from __future__ import annotations

import re
from typing import List, Optional

from .report import ERROR, WARNING, Finding, QAReport, sha256
from .percent_geometry import misplaced_arabic_percent


_SYMBOL_FONTS = ("ZapfDingbats", "Symbol")    # never used for text by this library
_SENTENCE_END = re.compile(r"^\s*[.!?\u061f\u06d4\u2026]|[.!?\u061f\u06d4\u2026]\s*$")


def _require_pymupdf():
    try:
        import pymupdf
        return pymupdf
    except ImportError as e:   # pragma: no cover
        from ..utils.errors import DynamicPDFError
        raise DynamicPDFError('Visual QA requires PyMuPDF: pip install "dynamic-pdf-builder[qa]"') from e


def _key(text: str) -> frozenset:
    """Order/shape-insensitive word key: extracted RTL text is in visual order
    and Arabic presentation forms, so compare NFKC words up to reversal."""
    import re
    import unicodedata
    words = re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", text or "").lower())
    return frozenset(min(w, w[::-1]) for w in words if not w.isdigit())


def _matches(line: str, target_key: frozenset) -> bool:
    return bool(target_key) and target_key <= _key(line)


def _contents_keys() -> list:
    from ..i18n import LABELS
    return [_key(v["toc"]) for v in LABELS.values()]


def _overlap(a, b) -> float:
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    if x1 <= x0 or y1 <= y0:
        return 0.0
    inter = (x1 - x0) * (y1 - y0)
    smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1])) or 1.0
    return inter / smaller


def _ink_beyond(page, bbox, left: float, right: float, pymupdf) -> float:
    """How far drawn ink of a line reaches past ``left``/``right`` (0 when it does not).

    A line's box comes from font metrics: for Arabic faces such as Amiri it reaches well past
    the glyphs themselves, so a box over the margin is not yet text in the margin. Only the
    strip outside the edge is rendered. Anything drawn there counts, so a band or picture in
    the margin still reports the line."""
    x0, y0, x1, y1 = bbox
    worst = 0.0
    for a, b, edge, outward in ((right, x1, right, 1), (x0, left, left, -1)):
        if b - a <= 0.05:
            continue
        clip = pymupdf.Rect(a, y0, b, y1) & page.rect
        if clip.is_empty:
            continue
        zoom = 3.0
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), colorspace=pymupdf.csGRAY, clip=clip, alpha=False)
        w, h, s = pix.width, pix.height, pix.samples
        ink = [c for c in range(w) if any(s[r * w + c] < 160 for r in range(h))]
        if ink:
            far = (clip.x0 + (max(ink) + 1) / zoom) if outward > 0 else (clip.x0 + min(ink) / zoom)
            worst = max(worst, (far - edge) * outward)
    return worst


def _separate_lines(a, b) -> bool:
    """Whether two lines stand clear of each other although their boxes meet: LibreOffice
    reports Amiri lines with the font's full extent, far taller than its ink. Lines drawn
    on top of each other have centres well under a text size apart."""
    centre = lambda line: (line[0][1] + line[0][3]) / 2                  # noqa: E731
    return abs(centre(a) - centre(b)) >= 0.8 * min(a[2], b[2])


def check_pdf(data: bytes, *, margins: Optional[dict] = None, heading_texts: Optional[List[str]] = None,
              tolerance: float = 2.0, fmt: str = "pdf", captions: Optional[List[str]] = None,
              major_headings: Optional[List[str]] = None, body_size: Optional[float] = None) -> QAReport:
    pymupdf = _require_pymupdf()
    doc = pymupdf.open(stream=data, filetype="pdf")
    rep = QAReport(format=fmt, pages=doc.page_count, sha256=sha256(data))
    caps = [_key(c) for c in (captions or []) if c.strip()]
    majors = [_key(h) for h in (major_headings or []) if _key(h)]
    head_keys = [_key(h) for h in (heading_texts or []) if _key(h)]
    head_ends = [(_key(h), bool(_SENTENCE_END.search(h))) for h in (heading_texts or []) if _key(h)]
    page_firsts = []          # first body line text of each page
    contents_keys = _contents_keys()
    page_texts = []
    image_bottoms = {}
    margins = margins or {}

    for pno, page in enumerate(doc, start=1):
        W, H = page.rect.width, page.rect.height
        left = margins.get("left", 0) - tolerance
        right = W - margins.get("right", 0) + tolerance
        d = page.get_text("dict")
        for bbox, text in misplaced_arabic_percent(page.get_text("rawdict")):
            rep.findings.append(Finding(
                severity=WARNING, code="arabic_percent_position", page=pno,
                bbox=bbox, text=text, format=fmt,
                message="percent sign is drawn to the RIGHT of the Arabic number; move it visually left"))
        lines = []
        has_image = False
        for bl in d["blocks"]:
            if bl.get("type") == 1:
                has_image = True
                image_bottoms[pno] = max(image_bottoms.get(pno, 0), bl["bbox"][3])
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
                # a font lacking the characters makes ReportLab fall back to a
                # symbol font: real letters come out as boxes/dingbats
                bad = [s_ for s_ in ln["spans"] if s_["font"] in _SYMBOL_FONTS and s_["text"].strip()]
                if bad:
                    rep.findings.append(Finding(severity=ERROR, code="missing_glyph", page=pno,
                                                format=fmt, text=txt.strip()[:80], bbox=ln["bbox"],
                                                message=f"text drawn with the {bad[0]['font']} symbol font "
                                                        f"(characters missing from the intended font): "
                                                        f"{txt.strip()[:40]!r}"))
        for bbox, txt, size in lines:
            x0, y0, x1, y1 = bbox
            x1 -= (len(txt) - len(txt.rstrip())) * size * 0.3    # a line's trailing space hangs
            if x0 < -tolerance or x1 > W + tolerance or y0 < -tolerance or y1 > H + tolerance:
                rep.findings.append(Finding(severity=ERROR, code="clipped_text", page=pno, bbox=bbox,
                                            text=txt.strip()[:120], format=fmt, fixable=True,
                                            message=f"text runs off the page: {txt.strip()[:40]!r}"))
            elif margins and (x1 > right or x0 < left) and 40 < y0 < H - 40:
                over = _ink_beyond(page, (x0, y0, x1, y1), left, right, pymupdf)
                if over > 0:
                    rep.findings.append(Finding(severity=ERROR, code="overflow", page=pno, bbox=bbox,
                                                text=txt.strip()[:120], format=fmt, fixable=True,
                                                message=f"text overflows into the margin by "
                                                        f"{max(over, 1):.0f}pt: {txt.strip()[:40]!r}"))
        # overlapping text lines (different lines drawn on top of each other)
        for i in range(len(lines)):
            for j in range(i + 1, len(lines)):
                a, b = lines[i][0], lines[j][0]
                if abs(a[1] - b[1]) < 0.5 and abs(a[0] - b[0]) < 0.5:
                    continue          # same line split into two dict lines
                if fmt == "docx" and _separate_lines(lines[i], lines[j]):
                    continue
                if _overlap(a, b) > 0.35:
                    rep.findings.append(Finding(
                        severity=ERROR, code="overlap", page=pno, bbox=a, format=fmt,
                        text=lines[i][1].strip()[:80],
                        message=f"text overlaps: {lines[i][1].strip()[:30]!r} / {lines[j][1].strip()[:30]!r}"))
        body = [ln for ln in lines if 40 < ln[0][1] < H - 50]
        # page fill: how far down the text block the content reaches, charts drawn as vectors included
        top = min([ln[0][1] for ln in body], default=72)
        drawn = [d["rect"].y1 for d in page.get_drawings() if d["rect"].y0 > 40 and d["rect"].y1 < H - 50]
        bottom = max([ln[0][3] for ln in body] + [image_bottoms.get(pno, 0)] + drawn, default=0)
        area = (H - 50) - min(top, 90)
        rep.page_fill.append(round(max(0.0, (bottom - min(top, 90)) / area), 2) if bottom else 0.0)
        page_firsts.append(" ".join(min(body, key=lambda ln: ln[0][1])[1].split()) if body else "")
        page_texts.append([ln[1] for ln in body])
        sizes = sorted(sz for _, _, sz in body)
        if sizes and body_size:
            biggest = sizes[-1]
            if biggest > body_size * 3.4 and pno > 1:
                rep.findings.append(Finding(severity=WARNING, code="oversized_heading", page=pno, format=fmt,
                                            message=f"{biggest:.0f}pt text is {biggest / body_size:.1f}× body size"))
        if body and pno < doc.page_count and caps:
            last = max(body, key=lambda ln: ln[0][3])
            lt = " ".join(last[1].split())
            # captions are set smaller than body text: a body-size line that shares words with a
            # caption is the end of a paragraph
            small = body_size is None or last[2] < body_size - 0.25
            if small and any(_matches(lt, c) or (_key(lt) and _key(lt) <= c and len(_key(lt)) >= 2) for c in caps):
                rep.findings.append(Finding(severity=ERROR, code="detached_caption", page=pno, bbox=last[0],
                                            text=lt, format=fmt,
                                            message=f"caption {lt[:40]!r} is separated from its table/figure"))
        if not body and not has_image and len(drawn) < 3 and doc.page_count > 1:
            rep.findings.append(Finding(severity=ERROR, code="blank_page", page=pno, format=fmt,
                                        fixable=True, message="page has no content"))
        if body and pno < doc.page_count:
            last = max(body, key=lambda ln: ln[0][3])
            lk = _key(last[1])
            # a contents page or an opening page's chapter strip lists headings; it does not strand one
            listed = sum(_key(ln[1]) in head_keys for ln in body) >= 3
            contents_page = listed or any(_matches(page_firsts[-1], k) for k in contents_keys)
            # a line that ends a sentence is the end of a paragraph, unless the heading itself
            # ends that way (extracted right-to-left lines may carry the stop at either end)
            sentence = bool(_SENTENCE_END.search(last[1]))
            if lk and not contents_page and any((hk == lk or (len(hk) >= 2 and hk <= lk and len(lk) <= len(hk) + 1))
                                                and (not sentence or ends)
                                                for hk, ends in head_ends):
                rep.findings.append(Finding(severity=ERROR, code="stranded_heading", page=pno,
                                            bbox=last[0], text=last[1].strip(), format=fmt, fixable=True,
                                            message=f"heading {last[1].strip()[:40]!r} is the last line on its page"))
        for link in page.get_links():
            if link.get("kind") == 1 and not (0 <= link.get("page", -1) < doc.page_count):
                rep.findings.append(Finding(severity=ERROR, code="broken_link", page=pno, format=fmt,
                                            message="internal link points to a missing page"))
    # wasted space: a short non-final page followed by ordinary continuing content
    orient = [p.rect.width > p.rect.height for p in doc]
    for i in range(len(rep.page_fill) - 1):
        nxt = page_firsts[i + 1]
        intentional = (orient[i] != orient[i + 1] or i == 0
                       or any(_matches(nxt, m) for m in majors)                 # next page opens a section
                       or any(_matches(page_firsts[i], m) for m in majors))     # e.g. a TOC page
        if rep.page_fill[i] < 0.45 and not intentional:
            rep.findings.append(Finding(severity=WARNING, code="wasted_space", page=i + 1, format=fmt,
                                        message=f"page {i + 1} is only {rep.page_fill[i]:.0%} full before "
                                                "ordinary continuing content"))
    inner = rep.page_fill[1:-1]
    if len(inner) >= 3 and sum(inner) / len(inner) < 0.55:
        rep.findings.append(Finding(severity=WARNING, code="low_density", format=fmt,
                                    message=f"inner pages average {sum(inner) / len(inner):.0%} full"))
    return rep
