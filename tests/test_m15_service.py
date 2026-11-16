"""M15 service mode: a stdlib worker that enforces ResourceLimits per request in a subprocess."""
import base64
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from dynamic_pdf.policy import RenderPolicy, ResourceLimits
from dynamic_pdf.service import render_request

ROOT = Path(__file__).resolve().parents[1]
ENV = {**os.environ, "PYTHONPATH": str(ROOT)}


def _policy(**limits):
    return RenderPolicy(limits=ResourceLimits(**{"render_timeout_s": 120, **limits}))


def test_renders_markdown_template_and_json(monkeypatch):
    monkeypatch.setenv("PYTHONPATH", str(ROOT))
    r = render_request({"id": "a", "markdown": "# Hi {{ name }}", "data": {"name": "Ada"}}, _policy())
    assert r["id"] == "a" and r["format"] == "pdf" and r["page_count"] == 1, r
    assert base64.b64decode(r["content_base64"]).startswith(b"%PDF")
    r = render_request({"id": "b", "document": {"blocks": [{"type": "paragraph", "text": "x"}]},
                        "format": "docx", "design": None}, _policy())
    assert r["format"] == "docx" and base64.b64decode(r["content_base64"])[:2] == b"PK", r


def test_limits_are_enforced(monkeypatch):
    monkeypatch.setenv("PYTHONPATH", str(ROOT))
    r = render_request({"markdown": "# Slow"}, _policy(render_timeout_s=0.05))
    assert r["status"] == "error" and "render time exceeds limit" in r["error"]
    r = render_request({"markdown": "a\n\n" + "\n\n".join(["text " * 400] * 12)}, _policy(max_pages=1))
    assert r["status"] == "error" and "Page count" in r["error"], r
    r = render_request({"markdown": "# x", "data": {}}, _policy(max_input_chars=2))
    assert r["status"] == "error" and "ResourceLimitError" in r["error"]


@pytest.mark.skipif(sys.platform == "win32", reason="RLIMIT_AS is POSIX only")
def test_memory_limit(monkeypatch):
    monkeypatch.setenv("PYTHONPATH", str(ROOT))
    r = render_request({"markdown": "# x"}, _policy(max_memory_mb=64))
    assert r["status"] == "error" and "memory limit is 64 MB" in r["error"], r
    r = render_request({"markdown": "# x\n\n$$a^2$$"}, _policy(max_memory_mb=2048))     # the service default
    assert r["status"] != "error", r


def test_requests_cannot_change_policy(monkeypatch):
    monkeypatch.setenv("PYTHONPATH", str(ROOT))
    r = render_request({"markdown": "# x", "limits": {"max_pages": 10 ** 6}}, _policy())
    assert r["status"] == "error" and "unknown fields ['limits']" in r["error"]
    r = render_request({"markdown": "![x](https://example.com/a.png)"}, _policy())
    assert r["status"] == "error" and "AssetError" in r["error"], r     # remote assets stay refused


def test_json_lines_loop():
    lines = [json.dumps({"id": 1, "markdown": "# One"}), "not json", json.dumps({"id": 3, "format": "txt",
                                                                                 "markdown": "x"})]
    p = subprocess.run([sys.executable, "-m", "dynamic_pdf.service", "--timeout", "120"],
                       input="\n".join(lines) + "\n", capture_output=True, text=True, env=ENV, cwd=ROOT)
    out = [json.loads(line) for line in p.stdout.splitlines()]
    assert [o["id"] for o in out] == [1, None, 3], p.stderr
    assert out[0]["status"] != "error" and out[1]["status"] == out[2]["status"] == "error"
    assert "format must be" in out[2]["error"]
