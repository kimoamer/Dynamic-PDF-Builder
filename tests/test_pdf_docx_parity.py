"""M2: structural parity — PDF and DOCX come from the same semantic document."""
import os
import re
import shutil
import subprocess
import unicodedata
import pytest
from dynamic_pdf import DocumentBuilder
from dynamic_pdf.core.inline import plain_text
from conftest import fixture_text, all_fixtures, docx_text, open_docx, pdf_text

WORD = re.compile(r"[^\W_]{3,}", re.UNICODE)


def _words(s: str) -> set:
    return set(WORD.findall(unicodedata.normalize("NFKC", s).lower()))


def _ast_words(builder) -> set:
    from dynamic_pdf.core.normalize import block_text
    sem = builder.semantic()
    out = set()
    for blk in sem.blocks:
        if blk.type in ("math", "chart", "diagram", "mermaid"):
            continue          # rendered visually; carried as image alt text
        for t in block_text(blk):
            out |= _words(plain_text(t))
    return out


@pytest.mark.parametrize("name", all_fixtures())
def test_docx_contains_every_ast_word(name):
    b = DocumentBuilder.from_markdown(fixture_text(name)).design()
    docx_words = _words(docx_text(b.render_docx()))
    missing = _ast_words(b) - docx_words
    assert not missing, sorted(missing)[:15]


@pytest.mark.parametrize("name", [n for n in all_fixtures() if "arabic" not in n and "bilingual" not in n])
def test_pdf_and_docx_share_content(name):
    b = DocumentBuilder.from_markdown(fixture_text(name)).design()
    ast = _ast_words(b)
    pdf_words = _words(pdf_text(b.render()).replace("-\n", ""))
    docx_words = _words(docx_text(b.render_docx()))
    # PDF extraction splits drop-capped first letters; allow suffix matches
    pdf_missing = {w for w in ast - pdf_words if not any(p.endswith(w[1:]) for p in pdf_words)}
    assert not pdf_missing, sorted(pdf_missing)[:15]
    assert ast <= docx_words


@pytest.mark.parametrize("name", all_fixtures())
def test_heading_structure_parity(name):
    b = DocumentBuilder.from_markdown(fixture_text(name)).design()
    outline = [o.text for o in b.semantic().outline]
    d = open_docx(b.render_docx())
    docx_headings = [re.sub(r"^[\d.]+\s+", "", p.text) for p in d.paragraphs
                     if p.style.name.startswith("Heading")]
    assert docx_headings == outline
    import pymupdf
    pdf = pymupdf.open(stream=b.render(), filetype="pdf")
    pdf_headings = [re.sub(r"^[\d.]+\s+", "", t[1]) for t in pdf.get_toc()]
    if b.semantic().direction == "ltr":
        assert pdf_headings == outline


@pytest.mark.skipif(not shutil.which("soffice"), reason="LibreOffice not installed")
@pytest.mark.parametrize("name", ["executive.md", "arabic_report.md", "financial.md", "manual.md"])
def test_docx_opens_and_converts_in_libreoffice(name, tmp_path):
    b = DocumentBuilder.from_markdown(fixture_text(name)).design()
    src = tmp_path / "doc.docx"
    b.render_docx(str(src))
    r = subprocess.run(["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(tmp_path), str(src)],
                       capture_output=True, text=True, timeout=180)
    out = tmp_path / "doc.pdf"
    assert out.exists(), r.stderr
    import pymupdf
    pdf = pymupdf.open(out)
    assert pdf.page_count >= 1
    text = "".join(p.get_text() for p in pdf)
    for o in b.semantic().outline[:3]:
        if b.semantic().direction == "ltr":
            assert o.text in text
