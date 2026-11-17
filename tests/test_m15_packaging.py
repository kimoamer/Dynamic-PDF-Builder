"""M15 packaging (R5): matplotlib is the "charts" extra, and the wheel stays within budget."""
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Measured 2026-11-16: 8.3 MB wheel, 17.6 MB unpacked, of which bundled fonts are 16.4 MB.
WHEEL_BUDGET_BYTES = 10_000_000
UNPACKED_BUDGET_BYTES = 20_000_000

NO_MATPLOTLIB = r"""
import sys
class Block:
    def find_spec(self, name, path=None, target=None):
        if name == "matplotlib" or name.startswith("matplotlib."):
            raise ImportError("blocked for the test: " + name)
sys.meta_path.insert(0, Block())
import warnings
from dynamic_pdf import DocumentBuilder, BlockRenderError
out = sys.argv[1]
b = DocumentBuilder.from_markdown("# Title\n\nText only, with a table.\n\n| a | b |\n|---|---|\n| 1 | 2 |\n")
b.export(out + "/t.pdf"); b.export(out + "/t.docx")
assert "matplotlib" not in sys.modules
try:
    DocumentBuilder().chart("bar", {"a": 1}).render(out + "/c.pdf")
    raise SystemExit("chart rendered without matplotlib")
except BlockRenderError as e:
    assert "pip install 'dynamic-pdf-builder[charts]'" in str(e), str(e)
with warnings.catch_warnings(record=True) as w:
    warnings.simplefilter("always")
    DocumentBuilder().math("a^2").render(out + "/m.pdf")
assert any("dynamic-pdf-builder[charts]" in str(x.message) for x in w), [str(x.message) for x in w]
print("OK")
"""


def test_text_only_documents_render_without_matplotlib(tmp_path):
    r = subprocess.run([sys.executable, "-c", NO_MATPLOTLIB, str(tmp_path)], capture_output=True, text=True,
                       cwd=ROOT, env={**os.environ, "PYTHONPATH": str(ROOT)})
    assert r.returncode == 0 and "OK" in r.stdout, r.stdout + r.stderr
    assert (tmp_path / "t.pdf").stat().st_size and (tmp_path / "t.docx").stat().st_size
    assert not (tmp_path / "c.pdf").exists()        # strict mode: no output for a failed chart


def test_charts_extra_declared_and_still_core():
    try:
        import tomllib
    except ImportError:                              # Python 3.10
        pytest.skip("tomllib needs Python 3.11")
    meta = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert any(d.startswith("matplotlib") for d in meta["optional-dependencies"]["charts"])
    assert any(d.startswith("matplotlib") for d in meta["dependencies"])      # default-on this release
    assert any(d.startswith("openpyxl") for d in meta["optional-dependencies"]["xlsx"])
    assert not any(d.startswith("openpyxl") for d in meta["dependencies"])


def test_wheel_size_budget(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    for name in ("pyproject.toml", "README.md", "LICENSE", "MANIFEST.in"):
        shutil.copy(ROOT / name, src / name)
    shutil.copytree(ROOT / "dynamic_pdf", src / "dynamic_pdf", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    r = subprocess.run([sys.executable, "-m", "pip", "wheel", str(src), "--no-deps", "-q", "-w", str(tmp_path / "out")],
                       capture_output=True, text=True, timeout=300)
    wheels = list((tmp_path / "out").glob("*.whl")) if r.returncode == 0 else []
    if not wheels:
        pytest.skip("cannot build a wheel here: " + (r.stderr.strip().splitlines() or ["?"])[-1])
    wheel = wheels[0]
    with zipfile.ZipFile(wheel) as z:
        infos = z.infolist()
    names = [i.filename for i in infos]
    assert wheel.stat().st_size <= WHEEL_BUDGET_BYTES, f"wheel is {wheel.stat().st_size / 1e6:.1f} MB"
    assert sum(i.file_size for i in infos) <= UNPACKED_BUDGET_BYTES
    assert not [n for n in names if n.endswith(".pyc") or n.startswith("tests/")]
    assert "dynamic_pdf/design/approved_grammar.json" in names
    assert any(n.startswith("dynamic_pdf/fonts/bundled/") and n.endswith(".ttf") for n in names)


def test_a_plain_install_can_check_its_pages_and_pulls_no_agpl_package():
    """Design variants and QA read the rendered pages, so the reader they need is a core
    dependency; PyMuPDF (AGPL) stays something a user asks for by name, never through [all]."""
    tomllib = pytest.importorskip("tomllib", reason="tomllib needs Python 3.11")
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    core = " ".join(project["dependencies"]).lower()
    assert "pypdfium2" in core and "pymupdf" not in core
    extras = project["optional-dependencies"]
    assert "qa" not in extras["all"][0].split("[")[1] and "pymupdf" in " ".join(extras["qa"])
    assert project["license"] == "MIT AND OFL-1.1"
    assert (ROOT / "dynamic_pdf" / "py.typed").is_file()
