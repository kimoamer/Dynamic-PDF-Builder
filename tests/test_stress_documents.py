"""M5: real-world stress documents — rendered pages checked, content preserved."""
import re
import shutil
import unicodedata
import pytest
import pymupdf
from dynamic_pdf.core.inline import plain_text
from dynamic_pdf.core.normalize import block_text
from dynamic_pdf.qa import check_docx, check_pdf
from dynamic_pdf.qa.loop import qa_context
from conftest import docx_text
from stress_docs import STRESS


_TOKEN = re.compile(r"[A-Za-z]{3,}|[\u0600-\u06FF]{3,}|\d{3,}")


def _keys(text):
    """Script-separated tokens, insensitive to visual (reversed) RTL order: PDF
    extraction may glue an Arabic cell to its English neighbour."""
    text = "".join(c for c in unicodedata.normalize("NFKC", text) if unicodedata.category(c) != "Mn")
    words = _TOKEN.findall(text.lower())     # harakat (combining marks) dropped
    return {min(w, w[::-1]) for w in words}


@pytest.fixture(scope="module")
def rendered(tmp_path_factory):
    out = {}
    assets = str(tmp_path_factory.mktemp("assets"))
    for name, make in STRESS.items():
        b = make(assets).design()
        out[name] = (b, b.render(), b.render_docx())
    return out


@pytest.mark.parametrize("name", list(STRESS))
def test_pdf_qa_passes_without_wasted_pages(rendered, name):
    b, pdf, _ = rendered[name]
    rep = check_pdf(pdf, margins={"left": b.last_render.theme.spacing.page_margin_left,
                                  "right": b.last_render.theme.spacing.page_margin_right},
                    heading_texts=[o.text for o in b.semantic().outline],
                    **qa_context(b.last_render.document, b.last_render.theme))
    assert not rep.errors, [f.message for f in rep.errors]
    assert not [f for f in rep.findings if f.code in ("wasted_space", "low_density", "blank_page")], \
        [f.message for f in rep.findings]


@pytest.mark.parametrize("name", list(STRESS))
def test_every_word_survives_in_pdf_and_docx(rendered, name):
    b, pdf, dx = rendered[name]
    words = set()
    for blk in b.semantic().blocks:
        if blk.type in ("math", "chart", "diagram", "mermaid"):
            continue
        visible = blk.model_copy(update={"alt_text": None}) if blk.type == "image" else blk
        for t in block_text(visible):           # alt text is not visible page text
            words |= _keys(plain_text(t))
    raw = "\n".join(p.get_text() for p in pymupdf.open(stream=pdf, filetype="pdf"))
    pdf_words = _keys(raw.replace("-\n", "")) | _keys(raw.replace("\n", ""))   # wrapped long tokens
    assert not (words - pdf_words), sorted(words - pdf_words)[:10]
    assert not (words - _keys(docx_text(dx))), sorted(words - _keys(docx_text(dx)))[:10]


def test_arabic_report_is_20_to_50_pages(rendered):
    _, pdf, _ = rendered["arabic_long_report"]
    assert 20 <= pymupdf.open(stream=pdf, filetype="pdf").page_count <= 50


def test_multi_page_tables_repeat_headers(rendered):
    _, pdf, _ = rendered["financial_complex"]
    doc = pymupdf.open(stream=pdf, filetype="pdf")
    pages_with_rows = [p for p in doc if "Line item" in p.get_text() or "Account" in p.get_text()]
    assert len(pages_with_rows) >= 4
    for p in pages_with_rows:
        t = p.get_text()
        assert ("Period" in t and "Line item" in t) or ("Account" in t and "FY2026" in t)


@pytest.mark.skipif(not shutil.which("soffice"), reason="LibreOffice not installed")
@pytest.mark.parametrize("name", ["arabic_long_report", "bilingual_corporate", "financial_complex",
                                  "technical_manual"])
def test_docx_visual_qa(rendered, name):
    b, _, dx = rendered[name]
    rep = check_docx(dx, heading_texts=[o.text for o in b.semantic().outline])
    assert rep.status == "pass", rep.summary() + str([f.message for f in rep.errors])
