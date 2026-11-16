"""M10 charts: data that fits the chart, readable funnels, no redundant legends, a palette that does
not repeat, figures in the document's digits, Arabic chart text shaped like body text."""
import matplotlib
import matplotlib.colors as mcolors
import matplotlib.text
import pytest

from dynamic_pdf import DocumentBuilder
from dynamic_pdf.renderers import chart as C
from dynamic_pdf.schema.blocks import ChartBlock
from dynamic_pdf.themes import get_theme
from dynamic_pdf.utils.errors import BlockRenderError

THEME = get_theme("claude")


def figure(chart_type, data, **kw):
    block = ChartBlock(chart_type=chart_type, data=data, **kw)
    C._check_data(chart_type, data)
    fig = C._RENDERERS[chart_type](block, THEME)
    C._shape_arabic(fig, block)
    fig.canvas.draw()
    return fig


def texts(fig):
    return [t for t in fig.findobj(matplotlib.text.Text) if t.get_text().strip()]


@pytest.mark.parametrize("chart_type, data, says", [
    ("pie", {"Profit": 40, "Loss": -10}, "negative"),
    ("pie", {"A": 0, "B": 0}, "zero"),
    ("bar", {"North": "12%", "South": 3}, "must be numbers"),
    ("pie", {"2024": {"A": 1}, "2025": {"A": 2}}, "one series"),
    ("funnel", {}, "no data"),
])
def test_data_that_does_not_fit_the_chart_is_refused_with_a_reason(chart_type, data, says):
    b = DocumentBuilder().chart(chart_type, data)
    with pytest.raises(BlockRenderError, match=says):
        b.render()
    with pytest.raises(BlockRenderError, match=says):
        b.render_docx()


def test_valid_data_still_draws():
    for chart_type, data in (("bar", {"A": 1, "B": 2}), ("waterfall", {"Start": 10, "Cost": -3, "End": 7}),
                             ("line", {"A": {"Q1": 1, "Q2": 2}, "B": {"Q1": 2, "Q2": 1}}), ("pie", [3, 4, 5])):
        assert DocumentBuilder().chart(chart_type, data).render()[:4] == b"%PDF"


def test_single_series_bar_chart_has_no_legend():
    fig = figure("bar", {"Riyadh": 5, "Jeddah": 3, "Dammam": 2})
    assert fig.axes[0].get_legend() is None
    fig = figure("grouped_bar", {"categories": ["Q1", "Q2"], "series": {"Sales": [1, 2]}})
    assert fig.axes[0].get_legend() is None
    fig = figure("grouped_bar", {"categories": ["Q1", "Q2"], "series": {"Sales": [1, 2], "Costs": [2, 1]}})
    assert fig.axes[0].get_legend() is not None


def test_palette_does_not_repeat_past_eight_or_twelve_categories():
    colors = C._colors(ChartBlock(chart_type="bar", data={}), 24)
    assert len(set(colors)) == 24
    rgb = [mcolors.to_rgb(c) for c in colors[:12]]
    closest = min(sum((a - b) ** 2 for a, b in zip(x, y)) ** 0.5
                  for i, x in enumerate(rgb) for y in rgb[i + 1:])
    assert closest > 0.15                      # no two of the first twelve read as the same colour
    assert C._colors(ChartBlock(chart_type="bar", data={}, colors=["#123456"]), 3) == ["#123456"] * 3


def test_funnel_labels_in_narrow_stages_sit_beside_them_in_dark_ink():
    fig = figure("funnel", {"Visitors": 10000, "Add to cart": 900, "Checkout": 300, "Purchase": 120})
    labels = {t.get_text().split("  ")[0]: t for t in texts(fig)}
    assert labels["Visitors"].get_color() == "white"
    for narrow in ("Add to cart", "Checkout", "Purchase"):
        assert labels[narrow].get_color() != "white"
        assert labels[narrow].get_ha() == "left"
    ax = fig.axes[0]
    renderer = fig.canvas.get_renderer()
    box = ax.get_window_extent(renderer)
    for t in labels.values():                  # every label stays inside the plot area
        ext = t.get_window_extent(renderer)
        assert ext.x1 <= box.x1 + 1 and ext.x0 >= box.x0 - 1


def test_figures_have_thousands_separators_not_exponents():
    fig = figure("bar", {"North": 12400, "South": 980000})
    shown = [t.get_text() for t in texts(fig)]
    assert "12,400" in shown and "980,000" in shown
    assert not any("e+" in s for s in shown)


def test_arabic_document_figures_use_arabic_indic_digits():
    b = DocumentBuilder().meta(language="ar").paragraph("بلغت الإيرادات ١٢٬٤٠٠ ريال في عام ٢٠٢٤.") \
        .chart("bar", {"الرياض": 12400, "جدة": 9800})
    from dynamic_pdf import policy
    from dynamic_pdf.i18n import digit_style
    col = policy.DiagnosticCollector(policy.RenderPolicy())
    col.digits = digit_style(b.build())
    token = policy.activate(col)
    try:
        fig = figure("bar", {"الرياض": 12400, "جدة": 9800})
        assert C._num(12400) == "١٢٬٤٠٠"
    finally:
        policy.deactivate(token)
    assert col.digits == "arabic"
    assert b.render()[:4] == b"%PDF" and b.render_docx()[:2] == b"PK"


def test_arabic_chart_text_is_shaped_like_body_text_and_keeps_diacritics():
    from dynamic_pdf.layout.factory import _apply_rtl
    fig = figure("bar", {"الإيراداتُ": 3, "المصروفات": 2}, title="الأداءُ المالي")
    shown = [t.get_text() for t in texts(fig)]
    assert _apply_rtl("الأداءُ المالي", "R") in shown          # the body's reshaper, harakat kept
    assert any("ُ" in s for s in shown)
