import pytest

pymupdf = pytest.importorskip("pymupdf")

from dynamic_pdf.themes.registry import get_theme, register_theme


def open_pdf(data: bytes):
    return pymupdf.open(stream=data, filetype="pdf")


def pdf_text(data: bytes) -> str:
    doc = open_pdf(data)
    return "\n".join(p.get_text() for p in doc)


@pytest.fixture
def total_theme():
    """A theme whose footer prints 'Page {n} of {total}'."""
    t = get_theme("claude")
    t.name = "test_total_pages"
    t.header_footer.enabled = True
    t.header_footer.footer_style = "minimal"
    t.header_footer.show_page_number = True
    t.header_footer.page_number_format = "Page {n} of {total}"
    register_theme(t)
    return t.name


@pytest.fixture
def png_path(tmp_path):
    from PIL import Image
    p = tmp_path / "img.png"
    Image.new("RGB", (40, 20), (200, 30, 30)).save(p)
    return str(p)
