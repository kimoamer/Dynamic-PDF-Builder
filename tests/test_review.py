"""Render, look, fix: one call returns what a reader would notice, where, and what to change."""
import json
import sys

import pytest

from dynamic_pdf import DocumentBuilder

FAULTY = ("# Report\n\n" + "Text that runs on. " * 30 + "\n\n# Totals\n\n| Item | Share |\n|---|---|\n"
          "| A | 60% |\n| B | 30% |\n\n![chart](missing.png)\n")


def test_a_review_lists_each_problem_with_its_place_and_a_fix_and_changes_nothing(tmp_path):
    b = DocumentBuilder.from_markdown(FAULTY)
    r = b.review(str(tmp_path / "pages"))
    codes = {i["code"]: i for i in r["issues"]}
    assert r["passed"] is False and codes["block_render_failed"]["severity"] == "error"   # the missing image
    assert "missing.png" in codes["block_render_failed"]["message"] and "marker" in codes["block_render_failed"]["fix"]
    assert "content:percent_sum" in codes                                                 # 60 + 30 is not 100
    assert all(set(i) == {"page", "severity", "code", "message", "fix"} and i["fix"] for i in r["issues"])
    assert r["images"] == [str(tmp_path / "pages" / f"page-{n:03d}.png") for n in range(1, r["pages"] + 1)]
    assert all(open(p, "rb").read(4) == b"\x89PNG" for p in r["images"])
    assert b._policy.error_mode == "strict"                     # the review rendered permissively, then put it back
    with pytest.raises(Exception, match="missing.png"):
        b.render()


def test_a_clean_document_passes_and_writes_nothing_without_a_folder(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = DocumentBuilder.from_markdown("# Summary\n\n" + "A short and tidy paragraph. " * 20).review()
    assert r["passed"] is True and r["images"] == [] and r["pages"] == 1
    assert not [i for i in r["issues"] if i["severity"] == "error"] and list(tmp_path.iterdir()) == []


def test_a_planned_quiet_page_is_not_reported_as_empty():
    b = DocumentBuilder().cover_page("Annual report", subtitle="2026")
    b.paragraph("Body text. " * 80)
    assert not [i for i in b.review()["issues"] if i["code"] == "sparse_page" and i["page"] == 1]


def test_the_cli_prints_each_issue_with_its_fix_and_fails_on_errors(tmp_path, monkeypatch, capsys):
    from dynamic_pdf import cli
    src = tmp_path / "in.md"
    src.write_text(FAULTY, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["dynamic-pdf", "review", str(src), "-o", "pages"])
    with pytest.raises(SystemExit) as done:
        cli.main()
    out = capsys.readouterr().out
    assert done.value.code == 1 and "block_render_failed" in out and "fix:" in out and "page images in pages" in out
    monkeypatch.setattr(sys, "argv", ["dynamic-pdf", "review", str(src), "--json"])
    with pytest.raises(SystemExit):
        cli.main()
    assert json.loads(capsys.readouterr().out)["passed"] is False


def test_agents_get_the_same_review_inside_their_output_folder(tmp_path):
    from dynamic_pdf.ai import mcp_server as M
    tools = M.tools(str(tmp_path))
    doc = {"meta": {"title": "T"}, "blocks": [{"type": "heading", "text": "Summary"},
                                               {"type": "paragraph", "text": "Tidy text. " * 30}]}
    r = tools["review"](doc, folder="look")
    assert r["images"] and all(p.startswith(str(tmp_path)) for p in r["images"])
    with pytest.raises(M.InputError, match="dpi"):
        tools["review"](doc, dpi=600)
    with pytest.raises(M.InputError):
        tools["review"](doc, folder="../outside")
