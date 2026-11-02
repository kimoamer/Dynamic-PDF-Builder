"""
DOCX structural checks (package integrity and Word semantics) and optional
visual checks through LibreOffice (DOCX → PDF → the same PDF checks).
"""
from __future__ import annotations

import io
import os
import shutil
import subprocess
import tempfile
import zipfile
from typing import List, Optional

from .report import ERROR, WARNING, Finding, QAReport, sha256

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def check_docx(data: bytes, *, heading_texts: Optional[List[str]] = None,
               visual: bool = True, timeout: int = 180) -> QAReport:
    rep = QAReport(format="docx", sha256=sha256(data))
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        bad = z.testzip()
    except zipfile.BadZipFile as e:
        rep.findings.append(Finding(severity=ERROR, code="corrupt_package", format="docx",
                                    message=f"not a valid DOCX zip: {e}"))
        return rep
    if bad:
        rep.findings.append(Finding(severity=ERROR, code="corrupt_package", format="docx",
                                    message=f"corrupt zip member {bad}"))
    from lxml import etree
    for name in z.namelist():
        if name.endswith(".xml") or name.endswith(".rels"):
            try:
                etree.fromstring(z.read(name))
            except etree.XMLSyntaxError as e:
                rep.findings.append(Finding(severity=ERROR, code="invalid_xml", format="docx",
                                            message=f"{name}: {e}"))
    import docx
    d = docx.Document(io.BytesIO(data))
    body = d.element.body
    # numbering references
    num_ids = set()
    if "word/numbering.xml" in z.namelist():
        num = etree.fromstring(z.read("word/numbering.xml"))
        num_ids = {n.get(W + "numId") for n in num.iter(W + "num")}
    for numId in body.iter(W + "numId"):
        if numId.get(W + "val") not in num_ids:
            rep.findings.append(Finding(severity=ERROR, code="broken_numbering", format="docx",
                                        message=f"paragraph references missing numId {numId.get(W + 'val')}"))
    # bookmarks & internal links
    names = [b.get(W + "name") for b in body.iter(W + "bookmarkStart")]
    if len(names) != len(set(names)):
        rep.findings.append(Finding(severity=ERROR, code="duplicate_bookmark", format="docx",
                                    message="duplicate bookmark names"))
    for hl in body.iter(W + "hyperlink"):
        a = hl.get(W + "anchor")
        if a and a not in names:
            rep.findings.append(Finding(severity=ERROR, code="broken_link", format="docx",
                                        message=f"internal link to missing bookmark {a}"))
    # tables: consistent grid
    for ti, t in enumerate(d.tables):
        widths = {len(r.cells) for r in t.rows}
        if len(widths) > 1:
            rep.findings.append(Finding(severity=ERROR, code="broken_table", format="docx",
                                        message=f"table {ti + 1} has rows with different cell counts {sorted(widths)}"))
    # images need alt text
    WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"
    for docPr in body.iter(WP + "docPr"):
        if not (docPr.get("descr") or "").strip():
            rep.findings.append(Finding(severity=WARNING, code="missing_alt_text", format="docx",
                                        message="image without alt text"))
    # headings are real heading styles
    got = [p.text for p in d.paragraphs if p.style.name.startswith("Heading")]
    for h in heading_texts or []:
        if not any(g.endswith(h) for g in got):
            rep.findings.append(Finding(severity=ERROR, code="missing_heading", format="docx",
                                        message=f"heading {h!r} is not a Word heading"))
    if visual:
        pdf = docx_to_pdf(data, timeout=timeout)
        if pdf is None:
            # Never report a visual PASS that did not happen
            rep.unverified.append("visual")
            rep.findings.append(Finding(severity=WARNING, code="visual_check_skipped", format="docx",
                                        message="LibreOffice not available; DOCX layout is UNVERIFIED"))
        else:
            from .pdf_checks import check_pdf
            sec = d.sections[0]
            # LibreOffice lets Arabic glyph overhang reach ~1-2pt past the margin;
            # use a slightly larger tolerance than for our own PDF output
            vis = check_pdf(pdf, margins={"left": sec.left_margin.pt, "right": sec.right_margin.pt},
                            heading_texts=None, fmt="docx", tolerance=4.0)
            rep.pages = vis.pages
            # Word/LibreOffice paginate themselves; only geometry defects are actionable
            rep.findings += [f for f in vis.findings if f.code in ("clipped_text", "clipped_image",
                                                                    "overlap", "overflow", "missing_glyph")]
            rep.page_fill = vis.page_fill
            rep.page_images = []
            rep._pdf = pdf  # type: ignore[attr-defined]
    return rep


def docx_to_pdf(data: bytes, timeout: int = 180) -> Optional[bytes]:
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "doc.docx")
        with open(src, "wb") as f:
            f.write(data)
        profile = "file://" + os.path.join(tmp, "lo-profile")
        subprocess.run([soffice, f"-env:UserInstallation={profile}", "--headless",
                        "--convert-to", "pdf", "--outdir", tmp, src],
                       capture_output=True, timeout=timeout, check=False)
        out = os.path.join(tmp, "doc.pdf")
        if not os.path.exists(out):
            return None
        with open(out, "rb") as f:
            return f.read()
