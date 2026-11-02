import subprocess
import sys
import json


def _run(*args, cwd=None):
    return subprocess.run([sys.executable, "-m", "dynamic_pdf.cli", *args],
                          capture_output=True, text=True, cwd=cwd)


def test_cli_markdown_ok(tmp_path):
    src = tmp_path / "in.md"
    src.write_text("# Title\n\n- Parent\n  - Child\n- Sibling\n", encoding="utf-8")
    r = _run("render", str(src), "-o", str(tmp_path / "out.pdf"))
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "out.pdf").read_bytes().startswith(b"%PDF")


def test_cli_strict_failure_exit_code_and_no_file(tmp_path):
    src = tmp_path / "in.json"
    src.write_text(json.dumps({"blocks": [{"type": "image", "src": "/missing.png"}]}))
    out = tmp_path / "out.pdf"
    r = _run("render", str(src), "-o", str(out))
    assert r.returncode == 2
    assert "AssetError" in r.stderr or "BlockRenderError" in r.stderr
    assert not out.exists()
    r = _run("render", str(src), "-o", str(out), "--permissive")
    assert r.returncode == 3 and out.exists()
    assert "block_render_failed" in r.stderr
