"""
What a reader would notice on the rendered pages, as a list a person or an agent can act on.

``DocumentBuilder.review()`` renders once and returns this. Nothing is changed and nothing is
fixed: the caller edits the document and reviews again (render, look, fix). Every issue says
where it is, how serious it is, and what to change in the document.
"""
from __future__ import annotations

import os
from typing import List, Optional

# what to change in the document, by finding code; a code without an entry gets the message alone
FIXES = {
    "overflow": "Shorten the text, or give it more room: a wider column, a smaller table, fewer columns.",
    "clipped_text": "The text runs past its box: shorten it or let the block break across pages.",
    "clipped_image": "Give the image a smaller width or height, or let it take a page of its own.",
    "overlap": "Two things are drawn on top of each other: remove a fixed position or a negative spacing.",
    "blank_page": "Remove the page break or the empty block that makes this page.",
    "stranded_heading": "Add a page break before this heading, or shorten what precedes it, so it starts the next page with its text.",
    "detached_caption": "Keep the caption with its table: shorten what precedes it or add a page break before it.",
    "missing_glyph": "Use a font that has these characters (register_custom_font), or remove them from the text.",
    "oversized_heading": "Use a lower heading level, or a shorter title.",
    "low_contrast": "Use a darker text colour or a lighter background.",
    "low_density": "The page holds little: join it with its neighbour or add the content it was meant to have.",
    "wasted_space": "A large empty area: move a figure or table nearer its text, or let the text flow around it.",
    "broken_link": "Point the link at a heading or bookmark that exists.",
    "arabic_percent_position": "Write the percentage sign where Arabic places it (after the number in reading order).",
    "sparse_page": "Most of this page is empty: move the following figure or table nearer its text, or remove the page break.",
    "alike_pages": "These two pages look the same: vary them with a figure, a pull quote or a different layout.",
    # render diagnostics
    "block_render_failed": "This block could not be drawn and shows a marker: correct what the message names.",
    "asset_failed": "Check the image path or address; remote images need AssetPolicy(allow_remote=True).",
    "image_low_resolution": "Use a larger image, or draw it smaller, so it is sharp in print.",
    "math_fallback": "The formula is shown as source: correct the LaTeX the message names.",
    "mermaid_fallback": "The diagram is shown as source: install the diagrams extra or set DYNAMIC_PDF_MERMAID_JS.",
    "qrcode_unavailable": 'Install the qrcode extra: pip install "dynamic-pdf-builder[qrcode]".',
    "band_overflow": "The header or footer text is too long for its band: shorten it.",
}


def _issue(page, severity, code, message, fix=None):
    return {"page": page, "severity": severity, "code": code, "message": message, "fix": fix or FIXES.get(code, "")}


def collect(builder, data: bytes, report, folder: Optional[str] = None, dpi: int = 60) -> dict:
    """The review of one rendered PDF (``data``) and its QA ``report``."""
    from ..intelligence.facts import read_pdf
    from ..intelligence.variants import _intended
    from .visual_critique import critique_facts
    issues: List[dict] = [_issue(f.page, f.severity, f.code, f.message) for f in report.findings]
    doc = builder.last_render.document
    facts = read_pdf(data)
    if facts.available:
        from ..i18n import LABELS
        titles = [b.title for b in doc.blocks if b.type == "section_opener"]
        if any(b.type == "table_of_contents" for b in doc.blocks):
            titles += [v["toc"] for v in LABELS.values()]
        quiet = _intended(any(b.type == "cover_page" for b in doc.blocks), facts.pages, titles)
        for o in critique_facts(facts, intended=quiet).observations:
            issues.append(_issue(o.page, "warning", o.code, o.note))
    else:
        issues.append(_issue(None, "warning", "unreviewed", "no PDF reader is installed, so the pages were not measured",
                             'pip install "dynamic-pdf-builder[qa-permissive]"'))
    for d in builder.diagnostics:
        code = d.get("code", "diagnostic")
        issues.append(_issue(None, "error" if d.get("level") == "error" else "warning", code, d.get("message", ""),
                             FIXES.get(code, "The block was drawn another way than asked: see the message.")))
    for w in builder.lint():
        issues.append(_issue(None, "warning", f"content:{w.rule}", str(w), "Correct the content the message names."))
    issues.sort(key=lambda i: (i["severity"] != "error", i["page"] is None, i["page"] or 0))
    images: List[str] = []
    if folder:
        from .pdf_backend import open_pdf
        os.makedirs(folder, exist_ok=True)
        pdf = open_pdf(data)
        try:
            for i in range(pdf.page_count):
                path = os.path.join(folder, f"page-{i + 1:03d}.png")
                pdf[i].save_png(path, dpi)
                images.append(path)
        finally:
            pdf.close()
    return {"pages": report.pages, "passed": not any(i["severity"] == "error" for i in issues),
            "issues": issues, "images": images}
