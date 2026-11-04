"""
Reference catalog: one record per PDF file — never merged, never dropped.

Each record keeps the source filename (relative to the input folder),
SHA-256, size, page count, PDF metadata, provenance and licence/reuse status.
Licence and provenance come only from reviewed metadata supplied by a person
(``05-Reviewed`` sidecars); when absent they are reported as ``unknown``.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
from typing import Dict, List, Optional, Tuple

REVIEWED_DIR = "05-Reviewed"
LICENSE_KEYS = ("license", "licence", "license_status", "reuse", "reuse_status", "rights", "usage")
PROVENANCE_KEYS = ("source", "provenance", "url", "publisher", "origin", "downloaded_from", "obtained")


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def discover(root: str) -> List[str]:
    """PDF files under ``root`` (recursive, deterministic order), excluding the reviewed-metadata folder."""
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d != REVIEWED_DIR and not d.startswith("."))
        for fn in sorted(filenames):
            if fn.lower().endswith(".pdf") and not fn.startswith("."):
                out.append(os.path.join(dirpath, fn))
    return out


# ───────────────────────────── reviewed metadata ─────────────────────────────

def _front_matter(text: str) -> dict:
    """``key: value`` lines (optionally between --- fences). Flat values only."""
    body = text
    fm = re.match(r"^---\s*\n(.*?)\n---", text, re.S)
    if fm:
        body = fm.group(1)
    out = {}
    for line in body.splitlines():
        mm = re.match(r"^\s*([A-Za-z_][\w\- ]*)\s*:\s*(.+?)\s*$", line)
        if mm:
            out[mm.group(1).strip().lower().replace(" ", "_").replace("-", "_")] = mm.group(2).strip().strip('"\'')
    return out


def load_reviewed(dirs: List[str]) -> Tuple[List[dict], List[dict]]:
    """Records from reviewed-metadata folders: (records, warnings).

    Supported: ``*.json`` (object or list of objects), ``*.csv`` (header row),
    ``*.md``/``*.yaml``/``*.yml``/``*.txt`` (flat ``key: value`` lines). A file
    named after a PDF stem applies to that PDF. Unknown formats are reported."""
    records, warns = [], []
    for d in dirs:
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            path = os.path.join(d, fn)
            if not os.path.isfile(path) or fn.startswith("."):
                continue
            stem, ext = os.path.splitext(fn)
            ext = ext.lower()
            try:
                if ext == ".json":
                    data = json.load(open(path, encoding="utf-8"))
                    items = data if isinstance(data, list) else data.get("documents", [data]) \
                        if isinstance(data, dict) else []
                    for it in items:
                        if isinstance(it, dict):
                            records.append({"_file": fn, "_stem": stem, **{k.lower(): v for k, v in it.items()}})
                elif ext == ".csv":
                    with open(path, encoding="utf-8-sig", newline="") as f:
                        for row in csv.DictReader(f):
                            records.append({"_file": fn, "_stem": stem,
                                            **{(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}})
                elif ext in (".md", ".yaml", ".yml", ".txt"):
                    rec = _front_matter(open(path, encoding="utf-8").read())
                    records.append({"_file": fn, "_stem": stem, **rec})
                elif ext != ".pdf":
                    warns.append({"code": "reviewed_metadata_unsupported", "severity": "info",
                                  "message": f"{fn}: unsupported metadata format, ignored"})
            except Exception as e:      # malformed sidecar: reported, never guessed
                warns.append({"code": "reviewed_metadata_unreadable", "severity": "warning",
                              "message": f"{fn}: {type(e).__name__}: {e}"})
    return records, warns


def match_reviewed(records: List[dict], rel: str, sha: str) -> Optional[dict]:
    """Exact matches only: SHA-256, then filename/path, then sidecar stem == PDF stem."""
    base, stem = os.path.basename(rel), os.path.splitext(os.path.basename(rel))[0]
    for r in records:
        if str(r.get("sha256", "")).lower() == sha:
            return r
    for key in ("file", "filename", "file_name", "path", "pdf", "document"):
        for r in records:
            v = str(r.get(key, ""))
            if v and (v == rel or os.path.basename(v) == base):
                return r
    for r in records:
        if r["_stem"] == stem and not any(k in r for k in ("file", "filename", "sha256", "path")):
            return r
    return None


def _first(rec: Optional[dict], keys) -> Optional[str]:
    if not rec:
        return None
    for k in keys:
        v = rec.get(k)
        if v not in (None, ""):
            return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
    return None


# ───────────────────────────── records ─────────────────────────────

def catalog_record(path: str, root: str, reviewed: List[dict], index: int) -> Tuple[dict, list]:
    import pymupdf
    rel = os.path.relpath(path, root).replace(os.sep, "/")
    sha = sha256_file(path)
    rec = {"doc_id": f"ref-{sha[:12]}", "file": rel, "sha256": sha, "bytes": os.path.getsize(path),
           "status": "ok", "page_count": None, "pdf_metadata": {}, "encrypted": None, "page_layout": None,
           "page_sizes": [], "reviewed_metadata": None, "provenance": None, "license": None}
    warns = []
    try:
        doc = pymupdf.open(path)
    except Exception as e:
        rec["status"] = "unreadable"
        warns.append({"code": "unreadable_pdf", "severity": "error", "message": f"{type(e).__name__}: {e}"})
        doc = None
    if doc is not None:
        try:
            rec["encrypted"] = bool(doc.needs_pass)
            if doc.needs_pass:
                rec["status"] = "encrypted"
                warns.append({"code": "encrypted_pdf", "severity": "error",
                              "message": "password protected; not analysed"})
            else:
                rec["page_count"] = doc.page_count
                md = doc.metadata or {}
                rec["pdf_metadata"] = {k: md.get(k) for k in ("title", "author", "subject", "creator",
                                                              "producer", "creationDate", "modDate", "format")
                                       if md.get(k)}
                try:
                    cat = doc.xref_get_key(doc.pdf_catalog(), "PageLayout")
                    rec["page_layout"] = cat[1].lstrip("/") if cat and cat[0] == "name" else None
                except Exception:
                    rec["page_layout"] = None
                sizes: Dict[Tuple, List[int]] = {}
                for p in doc:
                    key = (round(p.rect.width, 1), round(p.rect.height, 1))
                    sizes.setdefault(key, []).append(p.number + 1)
                rec["page_sizes"] = [{"width_pt": k[0], "height_pt": k[1], "pages": len(v),
                                      "first_page": v[0]} for k, v in sorted(sizes.items(), key=lambda kv: kv[1][0])]
                if len(sizes) > 1:
                    warns.append({"code": "mixed_page_sizes", "severity": "info",
                                  "message": f"{len(sizes)} distinct page sizes"})
                if rec["page_count"] == 0:
                    rec["status"] = "empty"
                    warns.append({"code": "empty_pdf", "severity": "error", "message": "no pages"})
        finally:
            doc.close()
    match = match_reviewed(reviewed, rel, sha)
    if match:
        rec["reviewed_metadata"] = {"file": f"{REVIEWED_DIR}/{match['_file']}",
                                    "fields": {k: v for k, v in match.items() if not k.startswith("_")}}
    lic, prov = _first(match, LICENSE_KEYS), _first(match, PROVENANCE_KEYS)
    rec["license"] = {"status": lic or "unknown",
                      "source": f"{REVIEWED_DIR}/{match['_file']}" if lic else "not provided",
                      "reuse_policy": "analysis only — measurements and abstract patterns; never copy branding, "
                                      "artwork or layouts into distributed assets"}
    rec["provenance"] = {"source": prov or "local reference folder (no reviewed provenance)",
                         "recorded_from": f"{REVIEWED_DIR}/{match['_file']}" if prov else "file system"}
    if not match:
        warns.append({"code": "reviewed_metadata_missing", "severity": "info",
                      "message": "no 05-Reviewed record matched (by SHA-256, filename or stem)"})
    if not lic:
        warns.append({"code": "license_unknown", "severity": "warning",
                      "message": "licence/reuse status unknown — treat as reference only"})
    return rec, warns


def first_page_fingerprint(path: str) -> Optional[str]:
    """Hash of the first page's normalised text (for 'possible duplicate' hints only)."""
    import pymupdf
    try:
        with pymupdf.open(path) as doc:
            if doc.needs_pass or doc.page_count == 0:
                return None
            t = re.sub(r"\s+", " ", doc[0].get_text()).strip().lower()
            return hashlib.sha256(t.encode()).hexdigest() if len(t) >= 40 else None
    except Exception:
        return None


def assign_ids_and_duplicates(records: List[dict], fingerprints: Dict[str, Optional[str]]) -> List[dict]:
    """Unique doc_id per file; duplicates are flagged, never merged.

    * exact duplicate — same SHA-256 (identical bytes);
    * possible duplicate — different bytes but the same page count and the
      same first-page text (e.g. a re-saved copy). Same title/publisher alone
      is never a duplicate signal.
    """
    warns = []
    seen: Dict[str, int] = {}
    for r in records:
        n = seen.get(r["doc_id"], 0)
        seen[r["doc_id"]] = n + 1
        if n:
            r["doc_id"] = f"{r['doc_id']}-{n + 1}"
    by_sha: Dict[str, List[dict]] = {}
    for r in records:
        by_sha.setdefault(r["sha256"], []).append(r)
    for group in by_sha.values():
        if len(group) > 1:
            for r in group:
                r.setdefault("duplicates", []).append({"kind": "exact", "with": [o["doc_id"] for o in group
                                                                                  if o is not r]})
                warns.append({"doc_id": r["doc_id"], "file": r["file"], "code": "duplicate_exact",
                              "severity": "warning",
                              "message": "identical bytes to " + ", ".join(o["file"] for o in group if o is not r)
                              + " — kept as a separate record"})
    by_fp: Dict[Tuple, List[dict]] = {}
    for r in records:
        fp = fingerprints.get(r["file"])
        if fp and r["page_count"]:
            by_fp.setdefault((fp, r["page_count"]), []).append(r)
    for group in by_fp.values():
        shas = {r["sha256"] for r in group}
        if len(shas) > 1:
            for r in group:
                others = [o for o in group if o["sha256"] != r["sha256"]]
                r.setdefault("duplicates", []).append({"kind": "possible", "with": [o["doc_id"] for o in others]})
                warns.append({"doc_id": r["doc_id"], "file": r["file"], "code": "possible_duplicate",
                              "severity": "info",
                              "message": "same page count and first-page text as " +
                              ", ".join(o["file"] for o in others) + " — review; kept as a separate record"})
    for r in records:
        r.setdefault("duplicates", [])
    return warns
