"""
An MCP server for agents: guide, render, review, variants, explain, lint, kit and schema.

    pip install "dynamic-pdf-builder[mcp]"
    python -m dynamic_pdf.ai.mcp_server --out-dir ./mcp-out

The server introduces the library to the agent when it connects (``INSTRUCTIONS``), and the
``guide`` tool gives the whole guide or one topic. Tools take the document as Markdown (the easiest
for an agent to write) or as JSON (the ``schema`` tool returns its JSON Schema), and write files only
inside the output folder. Remote images stay off. An invalid document is refused with each failing
field and how to fix it. No tool calls a model.
"""
from __future__ import annotations

import argparse
import functools
import os
import typing
from typing import Optional

from pydantic import ValidationError

from ..settings import get

OUT_ENV = "DYNAMIC_PDF_MCP_OUT"
LIMITS = {"le": "at most", "lt": "below", "ge": "at least", "gt": "above"}


INSTRUCTIONS = """Dynamic PDF Builder turns content into a designed document: a PDF to read, a DOCX to edit in Word,
and the tables as a workbook. You write the content; the library designs it (fonts, colours, layout, tables,
page breaks), checks every page, and reads Arabic as well as English.

Write the document as Markdown and pass it as `markdown`. Beyond plain Markdown it understands: front matter
(title, author, language, document_type ...), tables with spreadsheet formulas (=B2*C2, =SUM(ABOVE),
=WORDS(D5) for an amount in words), ```chart blocks holding JSON, $$ equations $$ {#eq-id}, figure and table
captions with ids and {ref:id} references, [@key] citations with a BibTeX file, :::warning callouts,
coloured words ([word]{red}, [text]{bg=yellow}), quotes (> text, > — Name; > [!pullquote]), ```signature blocks holding JSON, a header and footer preset
in the front matter (header: modern, logo: logo.png, company: ...), [TOC], and suggested edits ({++added++} {--removed--} {>>comment<<}) that become tracked changes in Word.

Work in a loop: `review` the document (each issue comes with its page and what to change, and the pages come
back as pictures: look at them, since no check judges white space or whether a chart says what you meant),
fix the Markdown, review again; then `render` the PDF and the DOCX, which are checked as they are written
(status `ok`). `variants` tries several designs
and recommends one; `explain` says why the design is as it is; `lint` checks the content (totals, shares,
references). `kit` makes a ready-made document from data: invoice, quote, letter, cv, feasibility,
statements, certificate. Call `guide` for the full syntax with examples, or `guide` with a topic:
markdown, charts, tables, academic, review-and-changes, design, headers, kits, output, arabic, limits."""


class InputError(ValueError):
    """The request cannot be served as given; the message says what to change."""


def _fix(err: dict) -> str:
    kind, ctx, loc = err["type"], err.get("ctx") or {}, err["loc"]
    if kind == "missing":
        return f"add the required field {loc[-1]!r}"
    if kind in ("enum", "literal_error"):
        return f"use one of {ctx.get('expected')}"
    if kind == "union_tag_invalid":
        return "set 'type' to a known block type such as 'heading', 'paragraph' or 'table'; the schema tool lists all"
    if kind == "union_tag_not_found":
        return "give the block a 'type'"
    if kind == "extra_forbidden":
        return "remove this field"
    for key, words in LIMITS.items():
        if key in ctx:
            return f"use a value {words} {ctx[key]}"
    return "compare the field with the schema tool's JSON Schema"


def explain_errors(e: ValidationError) -> str:
    lines = [f"{'.'.join(map(str, x['loc'])) or 'document'}: {x['msg']}. Fix: {_fix(x)}" for x in e.errors()]
    return "invalid document:\n" + "\n".join(lines)


def _builder(document: Optional[dict] = None, design: Optional[str] = "auto", markdown: Optional[str] = None):
    from .. import DocumentBuilder
    from ..schema.document import Document
    if (document is None) == (markdown is None):
        raise InputError("send the document once: as `markdown` (a string) or as `document` (JSON), not both or neither")
    if markdown is not None:
        if not isinstance(markdown, str) or not markdown.strip():
            raise InputError("markdown: expected the document's text. Fix: send e.g. '# Title\\n\\nText.'")
        try:
            b = DocumentBuilder.from_markdown(markdown)
        except (ValueError, ValidationError) as e:
            raise InputError(f"markdown: {e}") from None
    else:
        if not isinstance(document, dict):
            raise InputError("document: expected a JSON object. Fix: send {'meta': {...}, 'blocks': [...]}")
        try:
            doc = Document.model_validate(document)
        except ValidationError as e:
            raise InputError(explain_errors(e)) from None
        b = DocumentBuilder(theme=doc.theme)
        b._meta, b._blocks, b._source_kind = doc.meta, list(doc.blocks), "json"
    if design:
        try:
            b.design(None if design == "none" else design)
        except ValueError as e:
            raise InputError(f"design: {e}. Fix: use 'auto', 'none' or a profile name") from None
    return b


def _inside(out_dir: str, name: str, field: str) -> str:
    if not name or os.path.basename(name) != name or name in (".", ".."):
        raise InputError(f"{field}: {name!r} is not a plain file or folder name. Fix: give a name like 'report.pdf'")
    return os.path.join(out_dir, name)


def guide(topic: Optional[str] = None) -> str:
    """What the library does and how to write for it, with examples. Without a topic, the whole guide;
    topics: overview, quickstart, markdown, charts, tables, academic, review-and-changes, design, headers, kits,
    output, python-api, arabic, safety-and-settings, limits."""
    from ..guide import guide as text
    try:
        return text(topic)
    except ValueError as e:
        raise InputError(str(e)) from None


def schema() -> dict:
    """The JSON Schema of a document, with a description of every field. Only needed to send `document`
    as JSON; Markdown (`markdown`) is easier and covers almost everything."""
    from ..schema.describe import document_schema
    return document_schema()


def render(document: Optional[dict] = None, filename: str = "document.pdf", design: str = "auto", out_dir: str = ".",
           markdown: Optional[str] = None) -> dict:
    """Write the document as a designed file in the output folder: .pdf, .docx (editable in Word) or .xlsx
    (its tables, with formulas) by the file name's extension. Send the document as `markdown` or as `document`
    (JSON). A PDF or DOCX is checked page by page as it is written, so the status is `ok` once it passes (a
    workbook has no pages to check: `unverified`). Returns the path, the status with reasons, and the pages;
    a document that fails the check is refused with what failed (`review` shows each issue's page and fix)."""
    ext = os.path.splitext(filename)[1].lower()
    if ext not in (".pdf", ".docx", ".xlsx"):
        raise InputError(f"filename: {filename!r} needs a .pdf, .docx or .xlsx extension. Fix: e.g. 'report.pdf'")
    path = _inside(out_dir, filename, "filename")
    os.makedirs(out_dir, exist_ok=True)
    from ..utils.errors import QualityError
    try:
        res = _builder(document, design, markdown).export(path, qa=ext != ".xlsx")
    except QualityError as e:
        raise InputError(f"{e}. Fix: run `review` for each issue's page and what to change") from None
    except ValueError as e:                  # a formula or a table the document cannot hold, named
        raise InputError(str(e)) from None
    return {"path": path, "status": res.status, "reasons": res.status_reasons, "pages": res.page_count,
            "diagnostics": res.diagnostics}


def variants(document: Optional[dict] = None, n: int = 3, folder: str = "variants", out_dir: str = ".",
             markdown: Optional[str] = None) -> dict:
    """Several complete designs of the document (different art directions), each checked, with a
    recommendation and the reasons; the files go to the folder."""
    if not 1 <= n <= 5:
        raise InputError(f"n: {n} is out of range. Fix: use 1 to 5")
    made = _builder(document, None, markdown).design_variants(n=n)
    return {**made.to_dict(), "files": made.export(_inside(out_dir, folder, "folder"))}


def review(document: Optional[dict] = None, design: str = "auto", folder: str = "review", dpi: int = 60,
           out_dir: str = ".", markdown: Optional[str] = None) -> dict:
    """Render once and list what a reader would notice: each issue with its page, severity, code, message and
    `fix` (what to change). The pages come back as pictures (the first eight; every page is a PNG in the folder),
    so look at them: the checks do not judge taste, white space or whether a chart says what you meant. Nothing is changed:
    fix the document and review again until `passed` is true and the warnings are ones you accept."""
    if not 20 <= dpi <= 150:
        raise InputError(f"dpi: {dpi} is out of range. Fix: use 20 to 150 (60 is enough to see the layout)")
    return _builder(document, design, markdown).review(_inside(out_dir, folder, "folder"), dpi=dpi)


def explain(document: Optional[dict] = None, design: str = "auto", markdown: Optional[str] = None) -> dict:
    """Why each design decision was made: the kind of document read, the recipe, fonts, layout and tables."""
    return _builder(document, design, markdown).design_explain()


def lint(document: Optional[dict] = None, markdown: Optional[str] = None) -> list:
    """Warnings about the content, never edits: totals that do not add up, shares that do not make 100,
    references and citations to nothing, mixed digits or date formats, missing alt text, empty sections."""
    return [w.to_dict() for w in _builder(document, None, markdown).lint()]


def kit(name: str, data: Optional[dict] = None, filename: str = "", out_dir: str = ".") -> dict:
    """A ready-made document from data, with every part it needs, in English or Arabic:
    'invoice' (seller, buyer, dates, lines with computed totals, discount, VAT, the amount in words),
    'quote' (the same as a quotation), 'letter' (letterhead, recipient, subject, body, signature),
    'cv' (set for applicant tracking systems), 'feasibility' (cash flows, NPV, IRR, payback),
    'statements' (profit or loss and financial position, comparative years) or 'certificate'.
    Without `data`, returns example data to fill in; with it, writes `filename` (.pdf, .docx or .xlsx)."""
    from ..kits import kit as make, kit_example
    try:
        if data is None:
            return {"example": kit_example(name)}
        builder = make(name, data)
    except ValueError as e:
        raise InputError(str(e)) from None
    filename = filename or f"{name}.pdf"
    ext = os.path.splitext(filename)[1].lower()
    if ext not in (".pdf", ".docx", ".xlsx"):
        raise InputError(f"filename: {filename!r} needs a .pdf, .docx or .xlsx extension. Fix: e.g. 'invoice.pdf'")
    path = _inside(out_dir, filename, "filename")
    os.makedirs(out_dir, exist_ok=True)
    res = builder.export(path)
    return {"path": path, "status": res.status, "pages": res.page_count}


def tools(out_dir: str) -> dict:
    """The tool functions, bound to the output folder. ``lint`` appears only if the builder has it."""
    from .. import DocumentBuilder
    found = {"guide": guide, "schema": schema, "render": functools.partial(render, out_dir=out_dir),
             "variants": functools.partial(variants, out_dir=out_dir), "review": functools.partial(review, out_dir=out_dir),
             "explain": explain, "kit": functools.partial(kit, out_dir=out_dir)}
    if hasattr(DocumentBuilder, "lint"):
        found["lint"] = lint
    return found


def build_server(out_dir: str):
    try:
        from mcp.server.mcpserver import Image, MCPServer as Server
        from mcp.server.mcpserver.exceptions import ToolError
    except ImportError:
        try:
            from mcp.server.fastmcp import FastMCP as Server, Image
            from mcp.server.fastmcp.exceptions import ToolError
        except ImportError as e:
            raise ImportError('the MCP server needs the mcp package: pip install "dynamic-pdf-builder[mcp]"') from e
    server = Server("dynamic-pdf-builder", instructions=INSTRUCTIONS)
    for name, fn in tools(out_dir).items():
        target = fn.func if isinstance(fn, functools.partial) else fn
        server.add_tool(_tool(fn, target, ToolError, Image if name == "review" else None), name=name,
                        description=target.__doc__)
    return server


PAGES_SHOWN = 8


def _tool(fn, target, error, image=None):
    """``fn`` as a server tool; with ``image``, the result's page images go back as pictures as well,
    for an agent that cannot open files."""
    import inspect

    @functools.wraps(target)
    def call(**kwargs):
        try:
            out = fn(**kwargs)
        except InputError as e:
            raise error(str(e)) from None
        if image is not None and isinstance(out, dict) and out.get("images"):
            return [out] + [image(path=p) for p in out["images"][:PAGES_SHOWN]]
        return out
    sig, hints = inspect.signature(target), typing.get_type_hints(target)
    # real types, not this module's postponed strings, which the server cannot resolve
    call.__signature__ = sig.replace(parameters=[p.replace(annotation=hints.get(p.name, p.annotation))
                                                 for p in sig.parameters.values() if p.name != "out_dir"],
                                     return_annotation=list if image is not None else hints.get("return", sig.return_annotation))
    call.__annotations__ = {k: v for k, v in hints.items() if k != "out_dir"}
    if image is not None:
        call.__annotations__["return"] = list
    del call.__wrapped__
    return call


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m dynamic_pdf.ai.mcp_server", description=__doc__)
    ap.add_argument("--out-dir", default=get("MCP_OUT", "mcp-out"), help="the only folder tools write to")
    a = ap.parse_args(argv)
    build_server(os.path.abspath(a.out_dir)).run("stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
