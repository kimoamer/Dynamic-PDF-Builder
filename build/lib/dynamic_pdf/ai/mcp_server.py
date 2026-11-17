"""
An MCP server for agents: schema, render, variants, explain, and lint when the builder has it.

    pip install "dynamic-pdf-builder[mcp]"
    python -m dynamic_pdf.ai.mcp_server --out-dir ./mcp-out

Tools take a document as JSON (the ``schema`` tool returns its JSON Schema) and write files
only inside the output folder. Remote images stay off. An invalid document is refused with
each failing field and how to fix it. No tool calls a model.
"""
from __future__ import annotations

import argparse
import functools
import os
from typing import Optional

from pydantic import ValidationError

from ..settings import get

OUT_ENV = "DYNAMIC_PDF_MCP_OUT"
LIMITS = {"le": "at most", "lt": "below", "ge": "at least", "gt": "above"}


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


def _builder(document: dict, design: Optional[str] = "auto"):
    from .. import DocumentBuilder
    from ..schema.document import Document
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


def schema() -> dict:
    """The JSON Schema of a document."""
    from ..schema.document import Document
    return Document.model_json_schema()


def render(document: dict, filename: str = "document.pdf", design: str = "auto", out_dir: str = ".") -> dict:
    """Render a document to PDF or DOCX (by the file extension) in the output folder."""
    ext = os.path.splitext(filename)[1].lower()
    if ext not in (".pdf", ".docx"):
        raise InputError(f"filename: {filename!r} needs a .pdf or .docx extension. Fix: e.g. 'report.pdf'")
    path = _inside(out_dir, filename, "filename")
    os.makedirs(out_dir, exist_ok=True)
    res = _builder(document, design).export(path)
    return {"path": path, "status": res.status, "reasons": res.status_reasons, "pages": res.page_count,
            "diagnostics": res.diagnostics}


def variants(document: dict, n: int = 3, folder: str = "variants", out_dir: str = ".") -> dict:
    """Several art-directed designs, each gated, with a recommendation; files go to the folder."""
    if not 1 <= n <= 5:
        raise InputError(f"n: {n} is out of range. Fix: use 1 to 5")
    made = _builder(document, None).design_variants(n=n)
    return {**made.to_dict(), "files": made.export(_inside(out_dir, folder, "folder"))}


def explain(document: dict, design: str = "auto") -> dict:
    """Why each design decision was made."""
    return _builder(document, design).design_explain()


def lint(document: dict) -> object:
    """Warnings about the content; never edits it."""
    return _builder(document, None).lint()


def tools(out_dir: str) -> dict:
    """The tool functions, bound to the output folder. ``lint`` appears only if the builder has it."""
    from .. import DocumentBuilder
    found = {"schema": schema, "render": functools.partial(render, out_dir=out_dir),
             "variants": functools.partial(variants, out_dir=out_dir), "explain": explain}
    if hasattr(DocumentBuilder, "lint"):
        found["lint"] = lint
    return found


def build_server(out_dir: str):
    try:
        from mcp.server.mcpserver import MCPServer as Server
        from mcp.server.mcpserver.exceptions import ToolError
    except ImportError:
        try:
            from mcp.server.fastmcp import FastMCP as Server
            from mcp.server.fastmcp.exceptions import ToolError
        except ImportError as e:
            raise ImportError('the MCP server needs the mcp package: pip install "dynamic-pdf-builder[mcp]"') from e
    server = Server("dynamic-pdf-builder")
    for name, fn in tools(out_dir).items():
        target = fn.func if isinstance(fn, functools.partial) else fn
        server.add_tool(_tool(fn, target, ToolError), name=name, description=target.__doc__)
    return server


def _tool(fn, target, error):
    import inspect

    @functools.wraps(target)
    def call(**kwargs):
        try:
            return fn(**kwargs)
        except InputError as e:
            raise error(str(e)) from None
    sig = inspect.signature(target)
    call.__signature__ = sig.replace(parameters=[p for p in sig.parameters.values() if p.name != "out_dir"])
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
