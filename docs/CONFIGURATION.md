# Configuration

The library is a Python package and is configured in Python. Nothing is read from a settings
file, and nothing is written unless you name the place.

```python
from dynamic_pdf import DocumentBuilder
from dynamic_pdf.policy import RenderPolicy, ResourceLimits
from dynamic_pdf.assets import AssetPolicy

policy = RenderPolicy(error_mode="permissive", assets=AssetPolicy(allow_remote=False),
                      limits=ResourceLimits(max_blocks=2_000))
pdf = DocumentBuilder.from_markdown(text, policy=policy).render()
```

A policy belongs to your application, never to the document: untrusted Markdown or JSON cannot
loosen it. Build it from whatever your stack uses for settings (Django settings, a Pydantic
settings class, a plain dict) and pass it in.

## Environment variables

A deployment that is configured from outside can give the same things as variables. **What your
code passes always wins, then the variable, then the default.** Variables are read when they
are needed, not at import, so they may be set after `import dynamic_pdf`. An empty value counts
as unset.

| Variable | What it sets | Default |
| --- | --- | --- |
| `DYNAMIC_PDF_ERROR_MODE` | `strict` or `permissive`: what a failing block does when no `RenderPolicy` is passed | `strict` |
| `DYNAMIC_PDF_RENDER_TIMEOUT_S` | Seconds a request of the render worker (`python -m dynamic_pdf.service`) may take | none; the worker's command line uses 60 |
| `DYNAMIC_PDF_MAX_PAGES` | Pages a request of the render worker may produce | none; the worker's command line uses 500 |
| `DYNAMIC_PDF_MAX_MEMORY_MB` | Memory of the worker's subprocess (POSIX only) | none; the worker's command line uses 2048 |
| `DYNAMIC_PDF_AI_MODEL` | Model the optional AI layer asks when your code names none | the library's default model |
| `DYNAMIC_PDF_AI_CACHE` | Folder for the AI layer's replies, or `off` for none | `~/.cache/dynamic-pdf-builder/ai` |
| `DYNAMIC_PDF_PREFERENCES_DIR` | A `human_preferences` folder where `accept()` records a kept design when your code names none | none: `accept()` then asks for `root=` |
| `DYNAMIC_PDF_QA_BACKEND` | `pymupdf` or `pdfium`: the PDF reader the checks use when both are installed | PyMuPDF when installed |
| `DYNAMIC_PDF_MERMAID_JS` | Path of a local `mermaid.js`, so diagrams render without the network | none: the source is shown as code |
| `DYNAMIC_PDF_MCP_OUT` | The only folder the MCP server writes to | `mcp-out` |

Others the library honours without owning: `ANTHROPIC_API_KEY` (read by the `anthropic` SDK, only
when the AI layer is asked), `SOURCE_DATE_EPOCH` (reproducible dates in the output) and `TMPDIR`
(where Python puts temporary files).

`dynamic_pdf.settings.SETTINGS` holds the same list for code.

## What the library does to its host

- **No work at import.** Fonts are registered on first use; optional packages (matplotlib,
  PyMuPDF, the AI SDK, LightGBM) are imported only by the feature that needs them.
- **No network** unless your code asks: remote assets are refused by the default `AssetPolicy`,
  and the AI layer runs only when you pass a provider.
- **No writes** except the file you export, the AI cache above (skipped silently when its
  folder cannot be written, as in a read-only container) and a folder you name.
- **Per-request state** lives in `contextvars`, so renders in threads or `asyncio` tasks do not
  see each other's diagnostics or fonts.
- **matplotlib:** the non-interactive backend is selected only if your process has not started
  `pyplot`. A notebook or an application keeps the backend it chose.
- **ReportLab:** the ToUnicode map of an embedded font is corrected in two places: reshaped Arabic
  glyphs extract as the letters the author wrote, and a character beyond U+FFFF (an emoji) is written
  as the UTF-16 pair the PDF format requires. Every other entry is ReportLab's own.
- **ReportLab:** one fault of ReportLab is corrected (it drops the author's hyphen from a
  compound word when a paragraph runs onto the next page). The correction is in force only
  while this library lays out its own paragraphs; your own ReportLab documents are unchanged.

## Where it runs

| Host | Notes |
| --- | --- |
| A web application (Django, FastAPI, Flask) | Build one `RenderPolicy` at start-up and pass it per request. Rendering is CPU work: run it in a worker thread or a task queue, not in the event loop. |
| A task queue (Celery, RQ) | Nothing special. For untrusted input use `dynamic_pdf.service.render_request`, which renders in a subprocess with time and memory limits. |
| A container or a function (Docker, Lambda, Cloud Run) | Set `DYNAMIC_PDF_AI_CACHE` to a writable folder or `off`; a read-only home is tolerated. Bundled fonts ship in the wheel, so no system fonts are needed. |
| A notebook | `DocumentBuilder(...).render()` returns bytes; your plotting backend is left alone. |
