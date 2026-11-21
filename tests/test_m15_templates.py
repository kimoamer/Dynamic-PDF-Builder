"""M15: templates over a data context, data sources, batch rendering, CLI."""
import json
import subprocess
import sys

import pytest

from dynamic_pdf.markdown.parser import markdown_to_blocks
from dynamic_pdf.templates import (TemplateError, load_context, load_data, render_batch,
                                   render_document, render_json_template, render_template)
from dynamic_pdf.utils.errors import MissingDependencyError

INVOICE = """# Invoice {{ invoice.number }}

{% for item in items %}
- {{ item.name }}: {{ item.price }} (#{{ loop.index }})
{% endfor %}

{% if paid %}
Paid, thank you.
{% elif overdue %}
Overdue.
{% else %}
Due on {{ due }}.
{% endif %}

{{ items | table }}
"""
CTX = {"invoice": {"number": "A-17"}, "paid": False, "overdue": False, "due": "1 May",
       "items": [{"name": "Widget", "price": "1,200"}, {"name": "Gadget", "price": "-5"}]}


def test_variables_loops_conditions():
    out = render_template(INVOICE, CTX)
    blocks = markdown_to_blocks(out)
    assert [b.type for b in blocks] == ["heading", "bullet_list", "paragraph", "table"]
    assert blocks[0].text == "Invoice A-17"
    assert blocks[1].items == ["Widget: 1,200 (#1)", "Gadget: -5 (#2)"]
    assert blocks[2].text == "Due on 1 May."
    assert blocks[3].headers == ["name", "price"] and blocks[3].rows == [["Widget", "1,200"], ["Gadget", "-5"]]
    assert "\n\n\n" not in out                      # tag lines leave no blank lines behind
    assert render_template("{% if paid %}x{% elif overdue %}y{% endif %}", {**CTX, "overdue": True}) == "y"
    assert render_template("{% for i in xs %}{{ i }}{% if not loop.last %}, {% endif %}{% endfor %}",
                           {"xs": [1, 2, 3]}) == "1, 2, 3"


def test_missing_variable_is_named():
    with pytest.raises(TemplateError, match=r"line 3: undefined variable 'customer'"):
        render_template("a\n\n{{ customer.name }}", {})
    with pytest.raises(TemplateError, match=r"undefined variable 'invoice.numbr'"):
        render_template("{{ invoice.numbr }}", CTX)
    with pytest.raises(TemplateError, match=r"undefined variable 'items.5'"):
        render_template("{{ items.5.name }}", CTX)
    with pytest.raises(TemplateError, match="never closed"):
        render_template("{% for x in items %}x", CTX)


@pytest.mark.parametrize("expr", ["{{ __import__('os') }}", "{{ items.__class__ }}", "{{ 1 + 1 }}",
                                  "{% import os %}", "{{ items | system('ls') }}", "{{ invoice }}"])
def test_no_code_execution(expr):
    with pytest.raises(TemplateError):
        render_template(expr, CTX)


EVIL = ("# Injected heading\n\n- injected list\n\n| a | b |\n|---|---|\n"
        "**bold** [click](https://evil.example) <b>tag</b> $$x^2$$ ```\n:::warning\n[^1]: note")


def test_injection_is_escaped_in_markdown_pdf_and_docx(tmp_path):
    out = render_template("# Report\n\n{{ evil }}\n\nName: {{ evil }}\n", {"evil": EVIL})
    blocks = markdown_to_blocks(out)
    assert [b.type for b in blocks] == ["heading", "paragraph", "paragraph"]
    b = render_document("# Report\n\n{{ evil }}\n", {"evil": EVIL}).design(None)
    b.export(str(tmp_path / "e.pdf"))
    b.export(str(tmp_path / "e.docx"))
    import pymupdf
    page = pymupdf.open(str(tmp_path / "e.pdf"))[0]
    text = " ".join(page.get_text().split())
    for literal in ("# Injected heading", "- injected list", "**bold**", "[click](https://evil.example)",
                    "<b>tag</b>", "$$x^2$$", "```"):
        assert literal in text, literal
    assert "\\" not in text                         # the escapes themselves never show
    assert not [l for l in page.get_links() if l.get("uri")]
    from docx import Document as Docx
    docx_text = " ".join(p.text for p in Docx(str(tmp_path / "e.docx")).paragraphs)
    assert "**bold** [click](https://evil.example)" in docx_text and "\\" not in docx_text
    # marked safe, the same data is Markdown
    assert markdown_to_blocks(render_template("{{ evil | safe }}", {"evil": EVIL}))[0].type == "heading"


def test_code_contexts():
    out = render_template("```text\n{{ code }}\n```\n\nRun `{{ cmd }}`.\n",
                          {"code": "a * b\n  [x]", "cmd": "ls -la *.md"})
    blocks = markdown_to_blocks(out)
    assert blocks[0].code == "a * b\n  [x]" and blocks[1].text == "Run `ls -la *.md`."
    with pytest.raises(TemplateError, match="close the code fence"):
        render_template("```\n{{ code }}\n```", {"code": "x\n```\n# escaped"})
    with pytest.raises(TemplateError, match="inline code"):
        render_template("`{{ cmd }}`", {"cmd": "a` **b**"})


def test_pdf_inline_backslash_escapes():
    from dynamic_pdf.layout.factory import _md_inline
    assert _md_inline(r"\*a\* \[b\](c) \<sup>x\</sup> \-\-") == "*a* [b](c) &lt;sup&gt;x&lt;/sup&gt; --"
    assert _md_inline("`a\\*b` line\\\nnext") == \
        '<font face="Courier" size="9" backColor="#E8E8E8">a\\*b</font> line<br/>next'


def test_data_sources(tmp_path):
    (tmp_path / "s.csv").write_text("region,sales\nNorth,\"1,200\"\nSouth,900\n", encoding="utf-8")
    (tmp_path / "c.json").write_text(json.dumps({"title": "Q3"}), encoding="utf-8")
    assert load_data(str(tmp_path / "s.csv")) == [{"region": "North", "sales": "1,200"},
                                                   {"region": "South", "sales": "900"}]
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    wb.active.append(["region", "sales"])
    wb.active.append(["East", 300])
    wb.active.append([None, None])
    wb.save(tmp_path / "s.xlsx")
    assert load_data(str(tmp_path / "s.xlsx")) == [{"region": "East", "sales": 300}]
    ctx = load_context([str(tmp_path / "c.json"), f"sales={tmp_path / 's.xlsx'}", str(tmp_path / "s.csv")])
    assert ctx["title"] == "Q3" and ctx["sales"][0]["region"] == "East" and len(ctx["rows"]) == 2
    with pytest.raises(TemplateError, match="unsupported data file"):
        load_data(str(tmp_path / "x.txt"))


def test_xlsx_without_openpyxl_explains(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "openpyxl", None)
    with pytest.raises(MissingDependencyError, match=r"dynamic-pdf-builder\[xlsx\]"):
        load_data(str(tmp_path / "s.xlsx"))


JSON_TPL = json.dumps({
    "meta": {"title": "Sales {{ quarter }}"},
    "blocks": [
        {"type": "heading", "text": "Sales {{ quarter }}", "level": 1},
        {"type": "table", "headers": "{{ sales | headers }}", "rows": "{{ sales | rows }}"},
        {"type": "chart", "chart_type": "bar", "title": "By region",
         "data": "{{ sales | chart(\"region\", \"sales\") }}"},
        {"type": "paragraph", "text": "{{ note }}"},
    ]})


def test_json_template_binds_tables_and_charts(tmp_path):
    ctx = {"quarter": "Q3", "note": "**not bold**",
           "sales": [{"region": "North", "sales": "1,200"}, {"region": "So*uth", "sales": "900"}]}
    payload = render_json_template(json.loads(JSON_TPL), ctx)
    blocks = payload["blocks"]
    assert blocks[1]["headers"] == ["region", "sales"]
    assert blocks[1]["rows"] == [["North", "1,200"], ["So\\*uth", "900"]]      # cells escaped
    assert blocks[2]["data"] == {"North": 1200.0, "So*uth": 900.0}               # chart labels are not Markdown
    assert blocks[3]["text"] == "\\*\\*not bold\\*\\*"
    res = render_document(JSON_TPL, ctx).export(str(tmp_path / "sales.pdf"))
    assert not res.diagnostics and (tmp_path / "sales.pdf").read_bytes().startswith(b"%PDF")
    with pytest.raises(TemplateError, match="non-numeric"):
        render_json_template({"d": "{{ s | chart('region', 'region') }}"},
                             {"s": [{"region": "x"}]})


def test_batch_renders_many_documents_with_shared_figures(tmp_path):
    tpl = "# Letter for {{ name }}\n\nDear {{ name }}, your total is {{ total }}.\n\n$$a^2 + b^2$$\n"
    records = [{"id": "a1", "name": "Ada", "total": "10"}, {"id": "b2", "name": "Bob", "total": "20"},
               {"id": "c3", "name": "Cy", "total": "30"}]
    results = render_batch(tpl, records, str(tmp_path), name="letter-{{ id }}", formats=("pdf", "docx"),
                           design=None)
    from pathlib import Path
    assert [Path(r.pdf_path).name for r in results] == ["letter-a1.pdf", "letter-b2.pdf", "letter-c3.pdf"]
    assert all((tmp_path / f"letter-{r['id']}.docx").exists() for r in records)
    import pymupdf
    assert "your total is 20." in pymupdf.open(str(tmp_path / "letter-b2.pdf"))[0].get_text()
    with pytest.raises(TemplateError, match="already used"):
        render_batch(tpl, records, str(tmp_path / "dup"), name="same")


def test_batch_shares_one_figure_cache(tmp_path, monkeypatch):
    from dynamic_pdf.layout import factory
    calls = []
    real = factory._render_math
    monkeypatch.setattr(factory, "_render_math", lambda b, t: calls.append(1) or real(b, t))
    render_batch("# {{ name }}\n\n$$a^2 + b^2$$\n", [{"name": "A"}, {"name": "B"}], str(tmp_path), design=None)
    assert len(calls) == 1                          # the second document reused the figure


def _cli(*args):
    return subprocess.run([sys.executable, "-m", "dynamic_pdf.cli", *args], capture_output=True, text=True)


def test_cli_render_data_and_batch(tmp_path):
    (tmp_path / "t.md").write_text("# Hello {{ name }}\n\n{{ rows | table }}\n", encoding="utf-8")
    (tmp_path / "d.json").write_text(json.dumps({"name": "World"}), encoding="utf-8")
    (tmp_path / "r.csv").write_text("name\nAda\nBob\n", encoding="utf-8")
    r = _cli("render", str(tmp_path / "t.md"), "-o", str(tmp_path / "o.pdf"),
             "--data", str(tmp_path / "d.json"), "--data", f"rows={tmp_path / 'r.csv'}")
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "o.pdf").read_bytes().startswith(b"%PDF")
    r = _cli("render", str(tmp_path / "t.md"), "-o", str(tmp_path / "bad.pdf"))   # no data: template text kept
    assert r.returncode == 0, r.stderr
    r = _cli("render", str(tmp_path / "t.md"), "-o", str(tmp_path / "x.pdf"), "--data", str(tmp_path / "r.csv"))
    assert r.returncode == 2 and "undefined variable 'name'" in r.stderr
    r = _cli("batch", str(tmp_path / "t.md"), "--data", str(tmp_path / "r.csv"), "--context",
             f"rows={tmp_path / 'r.csv'}", "-o", str(tmp_path / "out"), "--name", "hi-{{ name }}",
             "-f", "docx", "--design", "none")
    assert r.returncode == 0, r.stderr
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == ["hi-Ada.docx", "hi-Bob.docx"]
