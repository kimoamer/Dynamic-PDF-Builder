"""The library explains itself: the guide, the MCP server's instructions and Markdown input, the
described schema, and ```chart fences."""
import pytest

import dynamic_pdf
from dynamic_pdf import DocumentBuilder
from dynamic_pdf.guide import guide, topics
from dynamic_pdf.qa.lint import RULES

CHART_TYPES = ("bar", "vertical_bar", "horizontal_bar", "grouped_bar", "stacked_bar", "line", "area", "pie",
               "donut", "scatter", "bubble", "histogram", "heatmap", "waterfall", "funnel", "gauge", "sparkline",
               "treemap")


def test_the_guide_has_topics_and_names_what_an_agent_needs():
    assert dynamic_pdf.guide is guide
    assert {"overview", "quickstart", "markdown", "charts", "tables", "limits"} <= set(topics())
    assert guide("tables").startswith("## Tables") and guide("tab").startswith("## Tables")
    with pytest.raises(ValueError, match="topics:"):
        guide("nothing-like-this")
    text = guide()
    missing = [t for t in CHART_TYPES if t not in text] + [r for r in RULES if r not in text]
    assert not missing, missing


def test_the_chart_fence_makes_a_chart_and_bad_json_says_how():
    md = '# R\n\n```chart {#fig-sales}\n{"type": "bar", "title": "Sales", "data": {"Q1": 3, "Q2": 5}}\n```\n'
    chart = [b for b in DocumentBuilder.from_markdown(md)._blocks if b.type == "chart"][0]
    assert (chart.chart_type, chart.title, chart.id, chart.data) == ("bar", "Sales", "fig-sales", {"Q1": 3, "Q2": 5})
    with pytest.raises(ValueError, match="holds JSON"):
        DocumentBuilder.from_markdown("```chart\n{type: bar}\n```\n")
    with pytest.raises(ValueError, match='needs "type"'):
        DocumentBuilder.from_markdown('```chart\n{"data": {"A": 1}}\n```\n')


def test_the_schema_describes_its_fields():
    from dynamic_pdf.schema.describe import document_schema
    defs = document_schema()["$defs"]
    fields = [p for d in defs.values() for p in d.get("properties", {}).values()]
    assert sum("description" in p for p in fields) / len(fields) > 0.7
    assert "formula" in defs["TableBlock"]["properties"]["rows"]["description"]
    assert "donut" in defs["ChartBlock"]["properties"]["chart_type"]["description"]
    assert defs["ParagraphBlock"]["description"]


class TestMCP:
    MD = "# Report\n\nRevenue rose.\n"

    def test_instructions_and_markdown_input(self, tmp_path):
        from dynamic_pdf.ai import mcp_server as M
        assert "markdown" in M.INSTRUCTIONS and "review" in M.INSTRUCTIONS
        tools = M.tools(str(tmp_path))
        assert {"guide", "render", "review", "lint", "schema"} <= set(tools)
        assert tools["render"](markdown=self.MD, filename="a.docx")["path"].endswith("a.docx")
        assert isinstance(tools["lint"](markdown=self.MD), list)
        assert tools["guide"]("charts").startswith("## Charts")
        for kwargs in ({}, {"markdown": self.MD, "document": {"blocks": []}}):
            with pytest.raises(M.InputError, match="not both or neither"):
                M.explain(**kwargs)
        with pytest.raises(M.InputError, match="markdown"):
            M.explain(markdown="```chart\nnope\n```\n")

    def test_the_server_sends_its_instructions(self, tmp_path):
        pytest.importorskip("mcp")
        from dynamic_pdf.ai import mcp_server as M
        server = M.build_server(str(tmp_path))
        assert server.instructions == M.INSTRUCTIONS
