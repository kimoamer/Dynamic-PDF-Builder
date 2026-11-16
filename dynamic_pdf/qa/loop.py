"""
Render → inspect → fix → re-render, with a bounded number of attempts.

Fixes are *layout* hints only (landscape, smaller type within limits, page
breaks before stranded headings, collapsing redundant page breaks, smaller
images). Content is never edited or removed.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from ..core.inline import plain_text
from ..core.normalize import block_text
from ..design.planner import MIN_TABLE_SIZE
from .glyphs import uncovered_chars
from .report import ERROR, Finding, QAReport

MAX_ATTEMPTS = 3


def _find_block(blocks, text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    needle = " ".join(text.split())[:40]
    if not needle:
        return None
    for i, b in enumerate(blocks):
        for t in block_text(b):
            hay = " ".join(plain_text(t).split()) if b.type != "code" else " ".join(t.split())
            if needle in hay or hay and hay in needle:
                return i
    return None


def _propose_fixes(blocks, report: QAReport, current: Dict[int, dict]) -> List[Tuple[int, dict, str]]:
    fixes: List[Tuple[int, dict, str]] = []
    seen = set()
    for f in report.errors:
        if not f.fixable:
            continue
        if f.code == "blank_page":
            for i, b in enumerate(blocks):
                if b.type == "page_break" and i > 0 and blocks[i - 1].type in (
                        "page_break", "cover_page", "table_of_contents", "introduction_page"):
                    if not current.get(i, {}).get("skip"):
                        fixes.append((i, {"skip": True}, f"collapsed redundant page break (block {i})"))
            continue
        idx = _find_block(blocks, f.text)
        if idx is None or idx in seen:
            continue
        seen.add(idx)
        b = blocks[idx]
        cur = {**(b.hints or {}), **current.get(idx, {})}
        if f.code in ("overflow", "clipped_text"):
            if b.type == "table":
                if not cur.get("landscape"):
                    fixes.append((idx, {"landscape": True}, f"table {idx} moved to a landscape page"))
                elif cur.get("font_size", 99) > MIN_TABLE_SIZE:
                    fixes.append((idx, {"font_size": MIN_TABLE_SIZE}, f"table {idx} set at {MIN_TABLE_SIZE}pt"))
            elif b.type == "code":
                size = cur.get("font_size", 9.0)
                if size > 7.0:
                    fixes.append((idx, {"font_size": size - 1}, f"code block {idx} reduced to {size - 1:g}pt"))
            else:
                fixes.append((idx, {"break_long_words": True}, f"block {idx}: long words allowed to break"))
        elif f.code == "clipped_image":
            fixes.append((idx, {"max_height_ratio": 0.6}, f"image {idx} scaled to fit the page"))
        elif f.code == "stranded_heading" and b.type == "heading" and not cur.get("break_before"):
            fixes.append((idx, {"break_before": True}, f"heading {idx} moved to the next page"))
            if idx + 1 < len(blocks) and blocks[idx + 1].type == "page_break":
                # the author's break belongs before the heading, not after it
                fixes.append((idx + 1, {"skip": True}, f"page break {idx + 1} moved before heading {idx}"))
    return fixes


def qa_context(doc, theme) -> dict:
    """Captions, level-1 headings, chapter openers and body size used by the PDF checks."""
    caps, majors, openers = [], [], []
    for b in doc.blocks:
        # only captions that *precede* their content (tables) can be detached by
        # ending a page; figure captions follow the image, so ending a page is normal
        if b.type == "table" and getattr(b, "caption", None):
            label = ""
            num = getattr(b, "table_number", None) or getattr(b, "figure_number", None)
            if num:
                label = ("Table " if b.type == "table" else "Figure ") + str(num) + ": "
            caps.append(plain_text(label + b.caption))
        elif b.type == "heading" and b.level == 1:
            majors.append(plain_text(b.text))
        elif b.type in ("cover_page", "table_of_contents"):
            majors.append(plain_text(getattr(b, "title", "") or "Table of Contents"))
        elif b.type == "section_opener":
            openers.append(plain_text(b.title))
    from ..i18n import LABELS
    majors += [v["toc"] for v in LABELS.values()]
    return {"captions": caps, "major_headings": majors, "body_size": theme.typography.base_size, "openers": openers}


def glyph_findings(sem, theme) -> List[Finding]:
    texts = []
    for b in sem.blocks:
        texts += [plain_text(t) for t in block_text(b)]
    missing = uncovered_chars(texts, theme.typography.body_family)
    if not missing:
        return []
    chars = "".join(sorted(missing))
    return [Finding(severity=ERROR, code="missing_glyph",
                    message=f"no installed font can draw {len(missing)} character(s): {chars[:40]!r}; "
                            "register a font that covers them (register_custom_font)",
                    text=chars[:40])]


def render_with_qa(builder, fmt: str, max_attempts: int = MAX_ATTEMPTS, visual_docx: bool = True):
    """Returns (bytes, QAReport). Applies fixes via ``builder._qa_hints``."""
    from .docx_checks import check_docx
    from .pdf_checks import check_pdf
    builder._qa_hints = {}
    applied: List[str] = []
    report: Optional[QAReport] = None
    data = b""
    for attempt in range(1, max_attempts + 1):
        if fmt == "pdf":
            data = builder.render()
            theme = builder.last_render.theme
            sem_doc = builder.last_render.document
            sp = theme.spacing
            margins = {"left": sp.page_margin_left, "right": sp.page_margin_right}
            hang = max(((b.hints or {}).get("hang") or 0 for b in sem_doc.blocks if b.type == "heading"), default=0)
            if hang:        # an art direction's headings hang into the start margin by design
                from ..core.normalize import normalize
                margins["right" if normalize(sem_doc).direction == "rtl" else "left"] -= hang
            report = check_pdf(data, margins=margins,
                               heading_texts=[o.text for o in builder.semantic().outline],
                               **qa_context(sem_doc, theme))
        else:
            data = builder.render_docx()
            from ..themes import get_theme
            doc, theme = builder._prepared()
            theme = theme or get_theme(doc.theme)
            sem_doc = doc
            report = check_docx(data, heading_texts=[o.text for o in builder.semantic().outline],
                                visual=visual_docx)
        from ..core.normalize import normalize
        report.findings += glyph_findings(normalize(sem_doc), theme)
        report.attempts = attempt
        report.fixes_applied = list(applied)
        if not report.errors or attempt == max_attempts:
            break
        # map findings onto the *unfiltered* prepared document (indices of _qa_hints)
        base_doc, _ = builder._prepared_inner()
        fixes = _propose_fixes(base_doc.blocks, report, builder._qa_hints)
        if not fixes:
            break
        for idx, hint, why in fixes:
            builder._qa_hints.setdefault(idx, {}).update(hint)
            applied.append(why)
    report.fixes_applied = applied
    return data, report
