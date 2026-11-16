"""Data sources (CSV, JSON, XLSX), templated documents and batch rendering."""
import csv
import json
import os
import re
from typing import Any, Iterable, List, Optional, Sequence

from ..utils.errors import MissingDependencyError, TemplateError
from .engine import render_json_template, render_template

XLSX_HINT = "Reading .xlsx files needs openpyxl: pip install 'dynamic-pdf-builder[xlsx]'"


def load_data(path: str) -> Any:
    """Load ``.json`` (any value), ``.csv`` or ``.xlsx`` (a list of row dicts keyed by
    the header row; XLSX reads the first sheet's stored values)."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".json":
        with open(path, encoding="utf-8-sig") as fh:
            return json.load(fh)
    if ext in (".csv", ".tsv"):
        with open(path, encoding="utf-8-sig", newline="") as fh:
            return list(csv.DictReader(fh, delimiter="\t" if ext == ".tsv" else ","))
    if ext in (".xlsx", ".xlsm"):
        try:
            import openpyxl
        except ImportError as e:
            raise MissingDependencyError(XLSX_HINT) from e
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        try:
            rows = list(wb.worksheets[0].iter_rows(values_only=True))
        finally:
            wb.close()
        if not rows:
            return []
        headers = [str(h) if h is not None else f"column_{i + 1}" for i, h in enumerate(rows[0])]
        return [{h: ("" if v is None else v) for h, v in zip(headers, r)}
                for r in rows[1:] if any(v is not None for v in r)]
    raise TemplateError(f"unsupported data file {path!r}; use .json, .csv, .tsv or .xlsx")


def load_context(specs: Iterable[str]) -> dict:
    """``FILE`` merges a JSON object into the context (any other data becomes ``rows``);
    ``NAME=FILE`` binds the file's data to ``NAME``."""
    context: dict = {}
    for spec in specs or ():
        name, sep, path = spec.partition("=")
        if sep and name.isidentifier() and not os.path.exists(spec):
            context[name] = load_data(path)
            continue
        data = load_data(spec)
        if isinstance(data, dict):
            context.update(data)
        else:
            context["rows"] = data
    return context


def render_document(template: str, context: dict, kind: Optional[str] = None, theme: Optional[str] = None,
                    policy=None):
    """A ``DocumentBuilder`` for ``template`` (Markdown or JSON text) filled with ``context``."""
    from ..builder import DocumentBuilder
    kind = kind or ("json" if template.lstrip().startswith("{") else "markdown")
    if kind not in ("markdown", "json"):
        raise ValueError(f"kind must be 'markdown' or 'json', got {kind!r}")
    if kind == "markdown":
        return DocumentBuilder.from_markdown(render_template(template, context), theme=theme, policy=policy)
    from ..schema.document import Document
    payload = render_json_template(json.loads(template), context)
    if theme:
        payload["theme"] = theme
    doc = Document.model_validate(payload)
    b = DocumentBuilder(theme=doc.theme, policy=policy)
    b._meta, b._blocks = doc.meta, list(doc.blocks)
    b._source_kind, b._source_text = "json", json.dumps(payload, ensure_ascii=False)
    return b


def render_batch(template: str, records: Sequence[Any], out_dir: str, kind: Optional[str] = None,
                 name: str = "document-{{ index }}", formats: Sequence[str] = ("pdf",),
                 design: Optional[str] = "auto", theme: Optional[str] = None, policy=None,
                 context: Optional[dict] = None, qa: bool = False) -> List[Any]:
    """Render one document per record into ``out_dir``; returns one ``ExportResult`` each.

    Each record's context is ``context`` plus the record's own keys (when it is a dict),
    ``record`` and ``index`` (from 1). ``name`` is a template for the file stem. The
    template is parsed once per record but fonts (process-wide) and rendered figures
    (one cache for the batch) are shared between documents."""
    os.makedirs(out_dir, exist_ok=True)
    formats = tuple(formats)
    if not formats or any(f not in ("pdf", "docx") for f in formats):
        raise ValueError(f"formats must be 'pdf' and/or 'docx', got {formats!r}")
    figures: dict = {}
    seen, results = set(), []
    for i, record in enumerate(records, 1):
        ctx = {**(context or {}), **(record if isinstance(record, dict) else {}),
               "record": record, "index": i}
        stem = re.sub(r"[^\w.-]+", "_", render_template(name, ctx, mode="plain")).strip("._")
        if not stem or stem in seen:
            raise TemplateError(f"record {i}: file name {stem!r} is empty or already used; "
                                "make the name template unique per record")
        seen.add(stem)
        try:
            b = render_document(template, ctx, kind=kind, theme=theme, policy=policy).design(design)
            if len(figures) > 256:          # shortcut: whole-cache reset bounds memory; LRU if batches mix many charts
                figures.clear()
            b._figure_cache = figures
            if len(formats) == 2:
                res = b.export_both(out_dir, basename=stem, qa=qa)
            else:
                res = b.export(os.path.join(out_dir, f"{stem}.{formats[0]}"), qa=qa)
        except Exception as e:
            if hasattr(e, "add_note"):
                e.add_note(f"while rendering record {i} ({stem})")
            raise
        results.append(res)
    return results


__all__ = ["load_data", "load_context", "render_document", "render_batch", "XLSX_HINT"]
