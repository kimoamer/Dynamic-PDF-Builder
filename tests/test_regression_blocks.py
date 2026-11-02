"""Backward-compatibility regression: every fluent block, every theme, strict mode."""
import warnings
import pytest
from dynamic_pdf import DocumentBuilder, list_themes, render_from_json
from conftest import pdf_text


def _kitchen_sink(theme, png):
    return (DocumentBuilder(theme=theme)
            .meta(title="Regression", author="CI")
            .cover_page("Cover Title", subtitle="Sub", author="Team", date="2026")
            .table_of_contents()
            .heading("Intro").paragraph("First paragraph with **bold**, *italics*, `code` and a [link](https://example.com).")
            .paragraph("Second paragraph & symbols < >.")
            .rich_text("Rich", bold=True)
            .note("A note")
            .bullet_list(["a", "b", {"text": "c", "children": ["c1"]}])
            .numbered_list(["one", "two"], start=2)
            .checklist([{"text": "done", "checked": True}, {"text": "todo"}])
            .definition_list([{"term": "T", "definition": "D"}])
            .table(["H1", "H2"], [["1", "2"], ["3", "4"]])
            .code("python", "print('hi')")
            .image(png, caption="Figure caption")
            .chart("bar", data={"Q1": 3.1, "Q2": 3.4})
            .math(r"E = mc^2")
            .diagram("flowchart", nodes=[{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
                     edges=[("a", "b")])
            .callout("Careful", variant="warning", title="Heads up")
            .quote("Quote text", attribution="Someone")
            .metric_row([{"label": "Rev", "value": "$1M", "delta": "+5%"}])
            .progress_bar([{"label": "Done", "value": 60}])
            .score_display(80, label="Score")
            .legend([{"label": "L", "color": "#ff0000"}])
            .badge("NEW")
            .heading("Academic", level=2)
            .footnote("1", "Footnote text")
            .abstract([{"label": "Background", "text": "bg"}], keywords=["k"])
            .bibliography([{"key": "s", "authors": "Smith", "title": "T", "source": "J", "year": "2024"}])
            .citation("s")
            .signature("Jane Doe", title="CEO")
            .timeline([{"date": "2024", "title": "Start"}])
            .shape("rect")
            .divider().spacer(10)
            .watermark("DRAFT")
            .two_column(left=["left text"], right=["right text"])
            .sidebar(main_content=["main text"], sidebar_content=["side text"])
            .page_break()
            .heading("End").paragraph("Final words."))


@pytest.mark.parametrize("theme", list_themes())
def test_kitchen_sink_renders_strict(theme, png_path):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        b = _kitchen_sink(theme, png_path)
        pdf = b.render()
    text = pdf_text(pdf)
    for needle in ("Cover Title", "Intro", "First paragraph", "Second paragraph & symbols < >.",
                   "left text", "right text", "side text", "inal words.", "Footnote text"):
        assert needle in text, needle
    assert b.last_render.diagnostics.errors == []
    assert "Block Error" not in text


def test_json_payload_v03_shape():
    res = render_from_json({
        "meta": {"title": "J"}, "theme": "academic",
        "blocks": [{"type": "heading", "text": "H"},
                   {"type": "paragraph", "text": "P"},
                   {"type": "bullet_list", "items": ["x", {"text": "y", "children": [{"text": "z"}]}]},
                   {"type": "table_of_contents"}],
    })
    assert res["success"] is True and res["metadata"]["page_count"] >= 1


def test_public_v03_helpers(tmp_path):
    from dynamic_pdf import markdown_to_pdf, render_to_bytes, render_to_base64, render
    from dynamic_pdf.schema.blocks import ParagraphBlock
    out = tmp_path / "m.pdf"
    markdown_to_pdf("# T\n\nbody", str(out))
    assert out.read_bytes().startswith(b"%PDF")
    assert render_to_bytes([ParagraphBlock(text="x")]).startswith(b"%PDF")
    assert render_to_base64([ParagraphBlock(text="x")])
    render([ParagraphBlock(text="x")], str(tmp_path / "r.pdf"))


HEADER_STYLES = ["bar", "gradient", "line", "double_line", "logo_centered", "logo_left",
                 "logo_right", "minimal", "banner", "accent_top", "underline", "boxed",
                 "split", "sidebar", "academic", "modern"]
FOOTER_STYLES = ["bar", "gradient", "line", "minimal", "centered", "three_column",
                 "two_column", "page_only", "logo_right", "logo_left", "copyright_line",
                 "academic", "sidebar"]


@pytest.mark.parametrize("header,footer", list(zip(HEADER_STYLES, FOOTER_STYLES * 2)))
def test_header_footer_styles_with_logo_and_total(header, footer, png_path):
    from dynamic_pdf.themes.registry import get_theme, register_theme
    t = get_theme("claude")
    t.name = f"hf_{header}_{footer}"
    hf = t.header_footer
    hf.enabled = True
    hf.header_style, hf.footer_style = header, footer
    hf.logo = png_path
    hf.footer_logo = png_path if hasattr(hf, "footer_logo") else None
    hf.show_page_number = True
    hf.page_number_format = "Page {n} of {total}"
    hf.title, hf.company_name, hf.copyright_text = "Doc", "Co", "(c) Co"
    register_theme(t)
    b = DocumentBuilder(theme=t.name)
    for i in range(3):
        b.heading(f"H{i}").paragraph("text " * 500)
    pdf = b.render()
    text = pdf_text(pdf)
    assert "of ?" not in text
    assert b.last_render.diagnostics.errors == []
