"""
CLI and orchestration.

    python -m tools.reference_analyzer analyze --input REFS --output RESULTS
        [--reviewed DIR] [--max-previews 6] [--min-support 2] [--no-previews]

Writes reference-catalog.json, design-features.json, design-patterns.json,
warnings.json, analysis-report.html and previews/*.jpg into RESULTS. Output
is deterministic for the same inputs (no timestamps or absolute paths).
No network access is used.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import List, Optional

from . import NAME, __version__

OPTIONAL_DEPS = {"pymupdf": "PDF parsing, text/drawing/table extraction, page rendering",
                 "pillow": "preview images and overlays"}


def _dep_info() -> dict:
    from importlib import metadata
    out = {}
    for dist, use in OPTIONAL_DEPS.items():
        try:
            md = metadata.metadata(dist)
            lic = md.get("License-Expression") or md.get("License") or ""
            out[dist] = {"version": metadata.version(dist), "license": lic.splitlines()[0][:120] if lic else "unknown",
                         "used_for": use}
        except metadata.PackageNotFoundError:
            out[dist] = {"version": None, "license": None, "used_for": use}
    return out


def _dump(path: str, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write("\n")


def analyze(input_dir: str, output_dir: str, reviewed: Optional[List[str]] = None, max_previews: int = 6,
            min_support: int = 2, previews: bool = True, log=print) -> dict:
    from .analyze import analyze_document, preview_pages
    from .catalog import (REVIEWED_DIR, assign_ids_and_duplicates, catalog_record, discover,
                          first_page_fingerprint, load_reviewed)
    from .patterns import build_patterns
    from .report import render_preview, write_report

    input_dir = os.path.abspath(input_dir)
    os.makedirs(output_dir, exist_ok=True)
    reviewed_dirs = reviewed or [os.path.join(input_dir, REVIEWED_DIR),
                                 os.path.join(os.path.dirname(input_dir), REVIEWED_DIR)]
    rev_records, warnings = load_reviewed(reviewed_dirs)
    for w in warnings:
        w.setdefault("file", REVIEWED_DIR)
    files = discover(input_dir)
    if not files:
        warnings.append({"code": "no_pdfs_found", "severity": "error", "file": "",
                         "message": "no .pdf files under the input folder"})
    records, per_doc_warn = [], []
    for i, path in enumerate(files):
        rec, ws = catalog_record(path, input_dir, rev_records, i)
        records.append(rec)
        per_doc_warn.append((rec, ws))
    dup_warn = assign_ids_and_duplicates(records, {r["file"]: first_page_fingerprint(p)
                                                   for r, p in zip(records, files)})
    for rec, ws in per_doc_warn:
        for w in ws:
            warnings.append({"doc_id": rec["doc_id"], "file": rec["file"], **w})
    warnings += dup_warn
    features, prev = [], {}
    pdir = os.path.join(output_dir, "previews")
    for rec, path in zip(records, files):
        if rec["status"] != "ok":
            continue
        log(f"analysing {rec['file']} ({rec['page_count']} pages)")
        f, ws = analyze_document(path, rec)
        features.append(f)
        for w in ws:
            warnings.append({"doc_id": rec["doc_id"], "file": rec["file"], **w})
        if previews:
            os.makedirs(pdir, exist_ok=True)
            prev[rec["doc_id"]] = []
            for n in preview_pages(f, max_previews):
                name = f"{rec['doc_id']}-p{n:04d}.jpg"
                render_preview(path, f["pages"][n - 1], os.path.join(pdir, name))
                prev[rec["doc_id"]].append({"src": f"previews/{name}", "features": f["pages"][n - 1]})
            if rec["page_count"] and rec["page_count"] > max_previews:
                warnings.append({"doc_id": rec["doc_id"], "file": rec["file"], "code": "previews_sampled",
                                 "severity": "info", "message": f"{len(prev[rec['doc_id']])} representative pages "
                                 f"previewed of {rec['page_count']}; all pages are measured"})
    catalog = {"tool": {"name": NAME, "version": __version__, "dependencies": _dep_info(),
                        "network": "none — runs offline; nothing is uploaded"},
               "input": {"folder": os.path.basename(input_dir.rstrip(os.sep)), "pdf_files": len(files),
                         "reviewed_metadata_records": len(rev_records)},
               "documents": records}
    patterns = build_patterns(features, min_support=min_support,
                              content_id={r["doc_id"]: r["sha256"] for r in records})
    order = {"error": 0, "warning": 1, "info": 2}
    warnings.sort(key=lambda w: (w.get("file", ""), w.get("page") or 0, order.get(w["severity"], 3), w["code"]))
    _dump(os.path.join(output_dir, "reference-catalog.json"), catalog)
    _dump(os.path.join(output_dir, "design-features.json"), {"units": "pt (1/72 in) unless stated; coordinates "
                                                             "top-left origin", "documents": features})
    _dump(os.path.join(output_dir, "design-patterns.json"), patterns)
    _dump(os.path.join(output_dir, "warnings.json"), warnings)
    write_report(output_dir, catalog, features, patterns, warnings, prev)
    return {"catalog": catalog, "features": features, "patterns": patterns, "warnings": warnings}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.reference_analyzer",
                                 description="Offline analysis of professional PDF design references.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("analyze", help="analyse every PDF in a folder")
    a.add_argument("--input", required=True, help="folder with reference PDFs (searched recursively)")
    a.add_argument("--output", required=True, help="results folder (created)")
    a.add_argument("--reviewed", action="append", help="reviewed-metadata folder (default: <input>/05-Reviewed "
                                                       "and its sibling 05-Reviewed)")
    a.add_argument("--max-previews", type=int, default=6, help="preview pages per document (all pages are measured)")
    a.add_argument("--min-support", type=int, default=2, help="documents needed for a recurring pattern")
    a.add_argument("--no-previews", action="store_true")
    args = ap.parse_args(argv)
    try:
        import pymupdf  # noqa: F401
    except ImportError:
        print("PyMuPDF is required: pip install 'dynamic-pdf-builder[analyzer]' (AGPL-3.0; local use only)",
              file=sys.stderr)
        return 2
    res = analyze(args.input, args.output, args.reviewed, args.max_previews, args.min_support,
                  not args.no_previews, log=lambda s: print(s, file=sys.stderr))
    docs = res["catalog"]["documents"]
    print(f"{len(docs)} PDF(s): {sum(d['status'] == 'ok' for d in docs)} analysed; "
          f"{len(res['patterns']['recurring'])} recurring pattern(s); {len(res['warnings'])} warning(s) → {args.output}")
    return 0
