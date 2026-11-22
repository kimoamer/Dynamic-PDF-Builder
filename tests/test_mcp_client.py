"""The MCP server as an agent meets it: a real client starts the server as its own process over stdio,
negotiates, discovers the tools from their descriptions, and works through whole tasks with them."""
import json
import os
import sys

import pytest

pytest.importorskip("mcp")
anyio = pytest.importorskip("anyio")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

LONG = "# Annual review\n\n" + "\n\n".join(
    f"## Part {i}\n\n" + "Revenue grew in every region this year, led by the north. " * 40 for i in range(1, 13))


def _session(out_dir, steps):
    """Run ``steps(session)`` against the server started as a subprocess; returns what it returns."""
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    async def run():
        params = StdioServerParameters(command=sys.executable, cwd=ROOT,
                                       args=["-m", "dynamic_pdf.ai.mcp_server", "--out-dir", str(out_dir)])
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as s:
                init = await s.initialize()
                return await steps(s, init)
    return anyio.run(run)


def _json(result):
    return json.loads(result.content[0].text)


def _error(result):
    assert result.is_error
    text = result.content[0].text
    return json.loads(text[text.index("{"):])["error"]


def test_an_agent_discovers_the_tools_and_writes_checked_documents_in_three_languages(tmp_path):
    async def steps(s, init):
        names = {t.name for t in (await s.list_tools()).tools}
        made = {}
        for name, md in {"en.pdf": "# Report\n\nRevenue grew 12% this year.\n",
                         "ar.pdf": "---\nlanguage: ar\n---\n\n# التقرير\n\nنمت الإيرادات ١٢٪ هذا العام.\n",
                         "both.docx": "# Report / التقرير\n\nRevenue grew. نمت الإيرادات.\n"}.items():
            made[name] = _json(await s.call_tool("render", {"markdown": md, "filename": name}))
        return init.instructions, names, made
    instructions, names, made = _session(tmp_path, steps)
    assert "review" in instructions and "error_code" in instructions
    assert {"guide", "schema", "render", "review", "kit", "lint", "explain", "variants"} <= names
    for name, out in made.items():
        assert out["status"] in ("ok", "unverified") and os.path.exists(out["path"]), (name, out)
    assert made["en.pdf"]["status"] == "ok" and made["ar.pdf"]["status"] == "ok"


def test_a_kit_is_written_checked_and_reviewed_in_one_loop(tmp_path):
    async def steps(s, init):
        example = _json(await s.call_tool("kit", {"name": "invoice"}))["example"]
        written = _json(await s.call_tool("kit", {"name": "invoice", "data": example, "theme": "ledger"}))
        seen = await s.call_tool("review", {"kit": "invoice", "kit_data": example})
        missing = _error(await s.call_tool("kit", {"name": "invoice", "data": {"number": "7"}}))
        return written, seen, missing
    written, seen, missing = _session(tmp_path, steps)
    assert written["status"] == "ok" and written["reasons"] is not None and os.path.exists(written["path"])
    report = _json(seen)
    assert report["passed"] and report["verified"] and report["shown"] == [1, 1]
    assert [c.type for c in seen.content[1:]] == ["image"]                       # the page, as a picture
    assert missing["error_code"] == "invalid_input" and missing["retryable"]
    assert set(missing["fields"]) == {"seller", "buyer", "date", "items"}          # every missing field at once


def test_every_refusal_says_where_what_to_change_and_whether_to_retry(tmp_path):
    async def steps(s, init):
        return [_error(await s.call_tool(*call)) for call in (
            ("render", {"filename": "x.pdf"}),
            ("render", {"markdown": "# T\n", "filename": "x.txt"}),
            ("render", {"document": {"blocks": [{"type": "nonsense"}]}, "filename": "x.pdf"}),
            ("review", {"markdown": "# T\n", "dpi": 5}),
            ("kit", {"name": "payslip", "data": {}}))]
    errors = _session(tmp_path, steps)
    for e in errors:
        assert set(e) == {"error_code", "field", "fields", "message", "fix", "retryable"} and e["message"]
        assert e["retryable"] and e["fix"], e
    assert [e["field"] for e in errors[:2]] == ["markdown", "filename"] and errors[3]["field"] == "dpi"


def test_a_long_document_can_be_seen_page_by_page_past_the_eighth(tmp_path):
    async def steps(s, init):
        first = await s.call_tool("review", {"markdown": LONG})
        later = await s.call_tool("review", {"markdown": LONG, "first_page": 9})
        beyond = _error(await s.call_tool("review", {"markdown": LONG, "first_page": 99}))
        return first, later, beyond
    first, later, beyond = _session(tmp_path, steps)
    pages = _json(first)["pages"]
    assert pages > 9 and _json(first)["shown"] == [1, 8] and len(first.content) == 9
    assert _json(later)["shown"] == [9, min(16, pages)] and len(later.content) == 1 + min(16, pages) - 8
    assert beyond["field"] == "first_page"


def test_a_word_review_says_whether_its_pages_were_seen(tmp_path):
    import shutil

    async def steps(s, init):
        return _json(await s.call_tool("review", {"markdown": "# Report\n\nText.\n", "format": "docx"}))
    out = _session(tmp_path, steps)
    seen = bool(shutil.which("soffice") or shutil.which("libreoffice"))
    assert out["verified"] is seen and ("visual" in out["unverified"]) is not seen
