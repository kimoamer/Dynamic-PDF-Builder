"""
Mermaid renderer — isolated, offline, data-only.

Security model
--------------
* The diagram source is **never** interpolated into HTML. It is passed to the
  page as a JSON argument of ``page.evaluate`` and rendered with
  ``mermaid.render`` using ``securityLevel: 'strict'``.
* No CDN: Mermaid JS must be provided locally via the ``DYNAMIC_PDF_MERMAID_JS``
  environment variable (path to ``mermaid.min.js``). It is injected as inline
  script content; every network request from the page is aborted.
* A Content-Security-Policy forbids external scripts/connections.
* Source length and render time are bounded by ``ResourceLimits``.

If Playwright or the local Mermaid bundle is unavailable, the diagram source is
rendered as a code block and a ``mermaid_fallback`` warning diagnostic is
recorded (content preserved, never silent).
"""
import io
import os

from .. import policy as _diag
from ..utils.errors import BlockRenderError

MERMAID_JS_ENV = "DYNAMIC_PDF_MERMAID_JS"

HARNESS_HTML = (
    "<!DOCTYPE html><html><head><meta charset='utf-8'>"
    "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; "
    "script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; font-src data:\">"
    "</head><body style='background:white;margin:0'><div id='out'></div></body></html>"
)

RENDER_JS = """
async (src) => {
  mermaid.initialize({startOnLoad: false, securityLevel: 'strict', htmlLabels: false,
                      flowchart: {htmlLabels: false}});
  const { svg } = await mermaid.render('dpb_diagram', src);
  document.getElementById('out').innerHTML = svg;
  return true;
}
"""


def _mermaid_script_path():
    path = os.environ.get(MERMAID_JS_ENV)
    if path and os.path.isfile(path):
        return path
    return None


def _fallback(block, theme, reason: str):
    from .code_block import render_code_block
    from ..schema.blocks import CodeBlock
    _diag.current().warn("mermaid_fallback", f"Mermaid diagram rendered as source: {reason}")
    return render_code_block(CodeBlock(language="mermaid", code=block.diagram), theme)


def render_mermaid(block, theme):
    col = _diag.current()
    limits = col.policy.limits
    _diag.check_limit("Mermaid source length", len(block.diagram), limits.max_mermaid_chars)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return _fallback(block, theme, 'Playwright not installed (pip install "dynamic-pdf-builder[diagrams]")')

    script_path = _mermaid_script_path()
    if not script_path:
        return _fallback(block, theme,
                         f"no local Mermaid bundle; set {MERMAID_JS_ENV}=/path/to/mermaid.min.js")
    with open(script_path, "r", encoding="utf-8") as f:
        script = f.read()

    timeout_ms = int(limits.renderer_timeout_s * 1000)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                context = browser.new_context(java_script_enabled=True, offline=True)
                page = context.new_page()
                page.set_default_timeout(timeout_ms)
                page.route("**/*", lambda route: route.abort())   # no network at all
                page.set_content(HARNESS_HTML)
                page.add_script_tag(content=script)
                page.evaluate(RENDER_JS, block.diagram)            # diagram is data
                png = page.locator("#out svg").first.screenshot()
            finally:
                browser.close()
    except Exception as e:
        raise BlockRenderError("mermaid", f"Mermaid render failed: {type(e).__name__}: {e}", e) from e

    from reportlab.platypus import Image
    from reportlab.lib.utils import ImageReader
    w, h = ImageReader(io.BytesIO(png)).getSize()
    max_w = 450
    if w > max_w:
        h = h * (max_w / w)
        w = max_w
    rl_img = Image(io.BytesIO(png), width=w, height=h)
    rl_img.hAlign = 'CENTER'
    rl_img.spaceAfter = theme.spacing.block_gap
    return [rl_img]
