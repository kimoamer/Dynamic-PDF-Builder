"""M1: deterministic profile selection, recipes, brand kits, design_explain."""
import pytest
from dynamic_pdf import DocumentBuilder
from dynamic_pdf.design import BrandKit, Profile, compile_tokens, heading_size
from dynamic_pdf.themes import get_theme
from conftest import fixture_text, pdf_text, open_pdf

EXPECTED = {
    "executive.md": "executive_report",
    "proposal.md": "proposal",
    "academic.md": "academic_report",
    "manual.md": "technical_manual",
    "financial.md": "financial_report",
    "letter.md": "letter",
    "arabic_report.md": "executive_report",
}


@pytest.mark.parametrize("name,profile", sorted(EXPECTED.items()))
def test_auto_profile_selection(name, profile):
    b = DocumentBuilder.from_markdown(fixture_text(name)).design("auto")
    ex = b.design_explain()
    assert ex["profile"] == profile, ex
    assert ex["reasons"]


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_designed_render_preserves_content(name):
    md = fixture_text(name)
    plain = DocumentBuilder.from_markdown(md)
    designed = DocumentBuilder.from_markdown(md).design("auto")
    t_plain = pdf_text(plain.render())
    t_designed = pdf_text(designed.render())
    for sem_text in designed.semantic().all_text():
        for word in sem_text.split()[:6]:
            w = word.strip("*`[]()!:#|.,")
            if len(w) > 3 and w.isalpha() and w in t_plain:
                assert w in t_designed, (name, w)


def test_explicit_type_wins_and_is_validated():
    b = DocumentBuilder.from_markdown(fixture_text("letter.md")).design("academic")
    assert b.design_explain()["profile"] == "academic_report"
    assert b.design_explain()["explicit"] is True
    with pytest.raises(ValueError):
        DocumentBuilder().design("brochure-ish")
    b = DocumentBuilder().document_type("proposal").heading("x").design()
    assert b.design_explain()["profile"] == "proposal"


def test_profiles_produce_distinct_designs():
    md = fixture_text("executive.md")
    seen = set()
    for prof in ("executive_report", "proposal", "academic_report", "corporate_memo", "letter"):
        b = DocumentBuilder.from_markdown(md).design(prof)
        b.render()
        t = b.last_render.theme
        seen.add((t.typography.body_family, t.typography.base_size,
                  t.spacing.page_margin_left, t.header_footer.header_style,
                  t.header_footer.page_number_format))
    assert len(seen) == 5


def test_auto_toc_inserted_for_long_structured_docs():
    # the manual fixture fits on one page, so it gets no contents page (M10); a long one does
    md = "---\ntitle: Widget Manual\n---\n" + "".join(
        f"# Chapter {i}\n\n" + ("Install the widget and configure the server with care. " * 60 + "\n\n") * 3
        for i in range(1, 7))
    b = DocumentBuilder.from_markdown(md).design("auto")
    b.render()
    assert b.last_design.toc_inserted
    doc = open_pdf(b.render())
    assert any("Table of Contents" in doc[i].get_text() for i in range(2))    # after the cover
    assert len(doc.get_toc()) >= 4


def test_rtl_recipe_uses_arabic_face():
    b = DocumentBuilder.from_markdown(fixture_text("arabic_report.md")).design()
    b.render()
    assert b.last_render.theme.typography.body_family == "Amiri"
    assert b.design_explain()["direction"] == "rtl"


def test_brand_kit_applied_with_contrast_guard(png_path):
    brand = BrandKit(name="Acme", primary="#FFE600", accent="#0050FF", logo=png_path)
    b = DocumentBuilder.from_markdown(fixture_text("executive.md")).design("auto", brand=brand)
    pdf = b.render()
    t = b.last_render.theme
    assert t.colors.primary != "#FFE600"           # darkened for contrast on white
    assert t.header_footer.logo == png_path
    assert any("darkened" in n for n in b.design_explain()["notes"])
    assert "Executive Summary" in pdf_text(pdf)


def test_heading_size_tokens_are_honoured():
    t = get_theme("claude")
    t.typography.heading_h1_size = 30
    assert heading_size(t, 1) == 30
    assert compile_tokens(t).heading_sizes[0] == 30
    assert heading_size(t, 2) == t.typography.base_size * t.typography.heading_scale[1]
