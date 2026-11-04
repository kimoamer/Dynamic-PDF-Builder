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


def load_catalog(input_dir: str, reviewed: Optional[List[str]] = None) -> tuple:
    """(catalog records, their paths, warnings) for every PDF under ``input_dir``."""
    from .catalog import (REVIEWED_DIR, assign_ids_and_duplicates, catalog_record, discover,
                          first_page_fingerprint, load_reviewed)
    input_dir = os.path.abspath(input_dir)
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
    return records, files, warnings, len(rev_records)


def analyze(input_dir: str, output_dir: str, reviewed: Optional[List[str]] = None, max_previews: int = 6,
            min_support: int = 2, previews: bool = True, log=print) -> dict:
    from .analyze import analyze_document, preview_pages
    from .patterns import build_patterns, template_families
    from .report import render_preview, write_report

    input_dir = os.path.abspath(input_dir)
    os.makedirs(output_dir, exist_ok=True)
    records, files, warnings, reviewed_count = load_catalog(input_dir, reviewed)
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
                         "reviewed_metadata_records": reviewed_count},
               "documents": records}
    identity = {r["doc_id"]: r["sha256"] for r in records}
    for family in template_families(features):
        members = {identity[f["doc_id"]] for f in family}
        if len(members) > 1:
            for f in family:
                identity[f["doc_id"]] = min(members)
                others = ", ".join(o["file"] for o in family if o is not f)
                warnings.append({"doc_id": f["doc_id"], "file": f["file"], "code": "possible_template_family",
                                 "severity": "info", "message": f"same page count, formats, body size, fonts and "
                                 f"margins as {others} — kept as a separate record, counted once in patterns"})
    patterns = build_patterns(features, min_support=min_support, content_id=identity)
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
    r = sub.add_parser("review", help="validate the machine-readable pattern review")
    r.add_argument("--file", default=None, help="review file (default: the committed pattern_review.json)")
    r.add_argument("--patterns", help="design-patterns.json of a run: also check ids and support against it")
    v = sub.add_parser("atlas", help="build the visual atlas of every page, with shortlist and curation file")
    v.add_argument("--input", required=True, help="folder with reference PDFs (searched recursively)")
    v.add_argument("--output", required=True, help="results folder, outside any git repository")
    v.add_argument("--reviewed", action="append", help="reviewed-metadata folder")
    v.add_argument("--shortlist", type=int, default=120, help="target number of candidate pages")
    s = sub.add_parser("atlas-serve", help="serve the atlas on 127.0.0.1 and save decisions to human-curation.json")
    s.add_argument("--output", required=True, help="results folder of an atlas run")
    s.add_argument("--port", type=int, default=8765)
    c = sub.add_parser("curation", help="validate a human curation file")
    c.add_argument("file")
    args = ap.parse_args(argv)
    if args.cmd == "curation":
        from .curation import load, summary
        try:
            print(summary(load(args.file)))
        except ValueError as e:
            print(e, file=sys.stderr)
            return 1
        return 0
    if args.cmd == "atlas-serve":
        from .atlas import make_server
        with make_server(args.output, args.port) as srv:
            print(f"atlas at http://127.0.0.1:{srv.server_address[1]}/ (Ctrl+C to stop)")
            try:
                srv.serve_forever()
            except KeyboardInterrupt:
                pass
        return 0
    if args.cmd == "review":
        from .review import REVIEW_PATH, check
        errs = check(args.file or REVIEW_PATH, args.patterns)
        print("\n".join(errs) if errs else "pattern review OK")
        return 1 if errs else 0
    try:
        import pymupdf  # noqa: F401
    except ImportError:
        print("PyMuPDF is required: pip install 'dynamic-pdf-builder[analyzer]' (AGPL-3.0; local use only)",
              file=sys.stderr)
        return 2
    if args.cmd == "atlas":
        from .atlas import build
        try:
            res = build(args.input, args.output, args.reviewed, args.shortlist,
                        log=lambda m: print(m, file=sys.stderr))
        except ValueError as e:
            print(e, file=sys.stderr)
            return 2
        idx, cov = res["index"], res["shortlist"]["coverage"]
        failed = [g for g in idx["gates"] if not g["passed"]]
        print(f"{len(idx['pages'])} page(s), {len(idx['errors'])} error(s); {cov['pages']} candidates, "
              f"{res['curation']['decisions']} human decision(s) → {args.output}")
        if res["stale_decisions"]:
            print(f"{len(res['stale_decisions'])} human decision(s) point at pages no longer in the corpus; "
                  "they stay in the file", file=sys.stderr)
        for g in failed:
            print(f"FAILED: {g['gate']}: {g['detail']}", file=sys.stderr)
        return 1 if failed else 0
    res = analyze(args.input, args.output, args.reviewed, args.max_previews, args.min_support,
                  not args.no_previews, log=lambda s: print(s, file=sys.stderr))
    docs = res["catalog"]["documents"]
    print(f"{len(docs)} PDF(s): {sum(d['status'] == 'ok' for d in docs)} analysed; "
          f"{len(res['patterns']['recurring'])} recurring pattern(s); {len(res['warnings'])} warning(s) → {args.output}")
    return 0
