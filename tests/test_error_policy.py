"""P1-03: strict mode raises typed errors; permissive mode is explicitly degraded."""
import pytest
from dynamic_pdf import (DocumentBuilder, BlockRenderError, AssetError, RenderPolicy,
                         render_from_json, ResourceLimits, ResourceLimitError)
from dynamic_pdf.schema.blocks import ChartBlock, ImageBlock
from conftest import pdf_text


def _bad_chart():
    return ChartBlock(chart_type="no_such_chart_type", data={"labels": [1], "values": "bad"})


def test_strict_is_default_and_raises_typed_error(tmp_path):
    out = tmp_path / "o.pdf"
    b = DocumentBuilder().paragraph("ok").add_block(ImageBlock(src="/nonexistent/x.png"))
    with pytest.raises((BlockRenderError, AssetError)) as ei:
        b.render(str(out))
    assert "x.png" in str(ei.value)
    assert not out.exists()


def test_permissive_marks_degraded_with_diagnostics():
    b = (DocumentBuilder().quality("permissive")
         .paragraph("still here").add_block(ImageBlock(src="/nonexistent/x.png")))
    pdf = b.render()
    text = pdf_text(pdf)
    assert "still here" in text
    assert "Block Error (image)" in text
    diags = b.diagnostics
    assert diags and diags[0]["level"] == "error" and diags[0]["block_type"] == "image"
    assert diags[0]["block_index"] == 1
    assert b.last_render.diagnostics.status == "degraded"


def test_render_from_json_status():
    payload = {"blocks": [{"type": "paragraph", "text": "x"},
                          {"type": "image", "src": "/nope.png"}]}
    with pytest.raises(Exception):
        render_from_json(payload)
    res = render_from_json(payload, policy=RenderPolicy(error_mode="permissive"))
    assert res["status"] == "degraded" and res["diagnostics"]
    ok = render_from_json({"blocks": [{"type": "paragraph", "text": "x"}]})
    assert ok["status"] == "ok" and ok["diagnostics"] == [] and ok["metadata"]["page_count"] == 1


def test_nested_column_failure_is_not_swallowed():
    b = DocumentBuilder().two_column(left=[ImageBlock(src="/nope.png")], right=["text"])
    with pytest.raises((BlockRenderError, AssetError)):
        b.render()


def test_invalid_error_mode():
    with pytest.raises(ValueError):
        RenderPolicy(error_mode="yolo")


def test_block_limit():
    b = DocumentBuilder().limits(max_blocks=3)
    for i in range(4):
        b.paragraph(str(i))
    with pytest.raises(ResourceLimitError):
        b.render()


def test_markdown_input_limit_is_not_silent_truncation():
    from dynamic_pdf.markdown.sanitizer import sanitize_markdown, validate_block_count
    with pytest.raises(ResourceLimitError):
        sanitize_markdown("x" * 20, max_length=10)
    with pytest.raises(ResourceLimitError):
        validate_block_count([1, 2, 3], max_count=2)
    with pytest.raises(ResourceLimitError):
        DocumentBuilder.from_markdown("x" * 50, policy=RenderPolicy(limits=ResourceLimits(max_input_chars=10)))
