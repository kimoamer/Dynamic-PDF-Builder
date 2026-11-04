"""
Local visual atlas of every page in the reference corpus.

    python -m tools.reference_analyzer atlas --input REFS --output OUT
    python -m tools.reference_analyzer atlas-serve --output OUT

Writes into OUT, which must be outside any git repository:

    visual-atlas/index.html     browsable gallery, thumbnails and full pages
    visual-page-index.json      page descriptors and provenance
    visual-shortlist.json       diverse candidates with reasons
    human-curation.json         reviewer decisions; created empty, never overwritten

One page is rendered at a time, and a document already cached under its SHA-256 is
not opened again. Index and shortlist are deterministic for the same inputs.
"""
from __future__ import annotations

import http.server
import json
import os
import shutil
from typing import Dict, List, Optional, Tuple

from . import curation
from .visual import (LABELS, LAYOUT_TYPES, classify, geometry_facts, layout_type, picture_light_share,
                     raster_features, relate_pages, shortlist, spread_of, text_facts)

VERSION = 4                     # bump when measurements change: cached documents are measured again
FORMAT = "dynamic-pdf-builder/m75-visual-page-index"
THUMB_W, FULL_W, SHEET_W = 260, 1100, 1600
FORBIDDEN = ("beautiful", "premium", "best", "aesthetic", "quality")
MAX_BODY = 8 * 1024 * 1024


def inside_git_repo(path: str) -> Optional[str]:
    p = os.path.abspath(path)
    while True:
        if os.path.exists(os.path.join(p, ".git")):
            return p
        parent = os.path.dirname(p)
        if parent == p:
            return None
        p = parent


def _short(sha: str) -> str:
    return sha[:12]


def _image_paths(atlas: str, sha: str, page: int) -> Tuple[str, str]:
    name = f"{_short(sha)}/p{page:04d}.jpg"
    return f"thumbs/{name}", f"pages/{name}"


def _overlay(pf: dict) -> dict:
    """Measured boxes as shares of the page, for the overlay toggle."""
    s = pf["size"]["value"]
    W, H = s["width_pt"], s["height_pt"]
    n = lambda b: [round(b[0] / W, 4), round(b[1] / H, 4), round(b[2] / W, 4), round(b[3] / H, 4)]   # noqa: E731
    blocks = pf["text_blocks"]["value"]
    cols = pf["columns"]["value"]
    return {"text": [n(b["bbox"]) for b in blocks if b["role"] != "heading_candidate"],
            "heading": [n(b["bbox"]) for b in blocks if b["role"] == "heading_candidate"],
            "table": [n(t["bbox"]) for t in pf["tables"]["value"]],
            "image": [n(i["bbox"]) for i in pf["images"]["value"]],
            "vector": [n(g["bbox"]) for g in pf["vector_graphics"]["value"]],
            "rule": [n(r["bbox"]) for r in pf["rules"]["value"]],
            "column": [[round(a / W, 4), 0, round(b / W, 4), 1] for a, b in cols["intervals"]] if cols else []}


def _render_page(page, atlas: str, sha: str, sheet: bool) -> "object":
    import pymupdf
    from PIL import Image
    width = SHEET_W if sheet else FULL_W
    zoom = width / page.rect.width
    pm = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False, colorspace=pymupdf.csRGB)
    im = Image.frombytes("RGB", (pm.width, pm.height), pm.samples)
    del pm
    thumb, full = _image_paths(atlas, sha, page.number + 1)
    for rel in (thumb, full):
        os.makedirs(os.path.dirname(os.path.join(atlas, rel)), exist_ok=True)
    im.save(os.path.join(atlas, full), quality=76)
    tw = THUMB_W * 2 if sheet else THUMB_W
    im.resize((tw, max(1, round(im.height * tw / im.width))), Image.LANCZOS).save(os.path.join(atlas, thumb), quality=72)
    return im


def measure_document(path: str, rec: dict, atlas: str, log=print) -> Tuple[List[dict], List[dict], dict, List[dict]]:
    """(page records, page errors, overlays, warnings) for one document, one page in memory at a time."""
    import pymupdf

    from .analyze import analyze_document
    features, warns = analyze_document(path, rec)
    by_page = {p["page"]: p for p in features["pages"]}
    body = features["summary"]["body_size"]["value"]
    sheets = {s["page"] for s in features["summary"]["spreads"]["value"]}
    scripts = [p["script"]["value"]["class"] for p in features["pages"]]
    rtl = scripts.count("arabic_rtl") >= len(scripts) / 2 if scripts else False
    sha = rec["sha256"]
    records, errors, overlays = [], [], {}
    with pymupdf.open(path) as doc:
        total = doc.page_count
        for page in doc:
            n = page.number + 1
            pf = by_page.get(n)
            try:
                im = _render_page(page, atlas, sha, n in sheets)
                raster = raster_features(im)
                geo = geometry_facts(pf, body, text_facts(page, body)) if pf else None
                if geo and geo["largest_image_box"]:
                    geo["picture_light_share"] = picture_light_share(im, geo["largest_image_box"])
                del im
            except Exception as e:      # recorded, never dropped: every page is either indexed or an explicit error
                errors.append({"sha256": sha, "doc_id": rec["doc_id"], "file": rec["file"], "page": n,
                               "error": f"{type(e).__name__}: {e}"})
                continue
            thumb, full = _image_paths(atlas, sha, n)
            records.append({"sha256": sha, "doc_id": rec["doc_id"], "file": rec["file"], "page": n, "status": "ok",
                            "thumb": thumb, "image": full, "width_pt": page.rect.width, "height_pt": page.rect.height,
                            "sheet_spread": n in sheets, "spread": spread_of(n, total, rtl, n in sheets),
                            "geometry_measured": pf is not None, "raster": raster, "geometry": geo})
            if pf:
                overlays[str(n)] = _overlay(pf)
    return records, errors, overlays, warns


def _cached(cache: str, sha: str, atlas: str) -> Optional[dict]:
    path = os.path.join(cache, f"{sha}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if data.get("version") != VERSION or not os.path.exists(os.path.join(atlas, "data", f"overlay-{_short(sha)}.js")):
        return None
    for p in data["pages"]:
        if not (os.path.exists(os.path.join(atlas, p["thumb"])) and os.path.exists(os.path.join(atlas, p["image"]))):
            return None
    return data


def _dump(path: str, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write("\n")


def _js(path: str, name: str, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"{name}=")
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        f.write(";\n")


def gates(catalog_docs: List[dict], pages: List[dict], errors: List[dict], short: dict) -> List[dict]:
    """The atlas quality gates, recomputed from what was written."""
    ok_docs = [d for d in catalog_docs if d["status"] == "ok" and not d.get("exact_copy_of")]
    seen = {(p["sha256"], p["page"]) for p in pages} | {(e["sha256"], e.get("page")) for e in errors}
    missing = [(d["sha256"], n) for d in ok_docs for n in range(1, d["page_count"] + 1) if (d["sha256"], n) not in seen]
    in_short = {e["sha256"] for e in short["entries"]}
    words = json.dumps([sorted(LABELS), list(LABELS.values()), list(LAYOUT_TYPES)]).lower()
    shas = [d["sha256"] for d in ok_docs]
    return [
        {"gate": "every page indexed or an explicit error", "passed": not missing,
         "detail": f"{len(pages)} indexed, {len(errors)} errors, {len(missing)} missing"},
        {"gate": "every document has shortlisted pages", "passed": all(s in in_short for s in shas),
         "detail": f"{len(in_short & set(shas))} of {len(shas)} documents"},
        {"gate": "documents stay separate records", "passed": len(set(shas)) == len(shas),
         "detail": f"{len(set(shas))} distinct SHA-256 values"},
        {"gate": "no automatic quality label", "passed": not any(w in words for w in FORBIDDEN),
         "detail": "labels describe composition only"},
    ]


def build(input_dir: str, output_dir: str, reviewed=None, target: int = 120, log=print) -> dict:
    from .run import load_catalog
    repo = inside_git_repo(output_dir)
    if repo:
        raise ValueError(f"the atlas holds images of the references and must stay outside git: {repo}")
    atlas = os.path.join(output_dir, "visual-atlas")
    cache = os.path.join(output_dir, ".visual-cache")
    data_dir = os.path.join(atlas, "data")
    for d in (atlas, cache, data_dir):
        os.makedirs(d, exist_ok=True)
    records, files, warnings, _ = load_catalog(input_dir, reviewed)
    pages: List[dict] = []
    errors: List[dict] = []
    stats = {"measured_documents": 0, "cached_documents": 0}
    first_file: Dict[str, str] = {}
    for rec, path in sorted(zip(records, files), key=lambda rp: rp[0]["file"]):
        if rec["status"] == "ok" and rec["sha256"] in first_file:
            rec["exact_copy_of"] = first_file[rec["sha256"]]    # byte-identical: same pages, indexed once
            continue
        if rec["status"] == "ok":
            first_file[rec["sha256"]] = rec["file"]
        if rec["status"] != "ok":
            errors.append({"sha256": rec.get("sha256"), "doc_id": rec.get("doc_id"), "file": rec["file"], "page": None,
                           "error": f"document not readable: {rec['status']}"})
            continue
        hit = _cached(cache, rec["sha256"], atlas)
        if hit:
            stats["cached_documents"] += 1
        else:
            log(f"rendering {rec['file']} ({rec['page_count']} pages)")
            got, errs, overlays, _ = measure_document(path, rec, atlas, log)
            hit = {"version": VERSION, "pages": got, "errors": errs}
            _dump(os.path.join(cache, f"{rec['sha256']}.json"), hit)
            _js(os.path.join(data_dir, f"overlay-{_short(rec['sha256'])}.js"),
                f"ATLAS_OVERLAYS[{json.dumps(_short(rec['sha256']))}]", overlays)
            stats["measured_documents"] += 1
        for p in hit["pages"]:              # identity follows this run's catalog; rules are not cached, only pixels
            p.update(doc_id=rec["doc_id"], file=rec["file"])
            p["labels"] = classify(p["raster"], p["geometry"], p["page"], rec["page_count"])
            p["layout_type"] = layout_type(p["raster"], p["geometry"], {x["label"] for x in p["labels"]})
        pages += hit["pages"]
        errors += hit["errors"]
    relate_pages(pages)

    cur_path = os.path.join(output_dir, "human-curation.json")
    if not os.path.exists(cur_path):
        curation.save(cur_path, curation.empty())
    cur = curation.load(cur_path)
    short = shortlist(pages, curation.kept(cur), curation.rejected(cur), target=target)
    known = {(p["sha256"], p["page"]) for p in pages}
    stale = curation.stale(cur, known)
    results = gates(records, pages, errors, short)
    docs = [{"sha256": r["sha256"], "doc_id": r["doc_id"], "file": r["file"], "pages": r.get("page_count"),
             "status": r["status"], "rights_status": r.get("rights_status"), "license": r.get("license"),
             "provenance": r.get("provenance"), "exact_copy_of": r.get("exact_copy_of")} for r in sorted(records, key=lambda r: r["file"])]
    index = {"format": FORMAT, "version": VERSION,
             "note": "Measurements and inferred categories only. No field states that a page looks good: "
                     "distinctiveness ranks difference from neighbouring pages. Human decisions are in "
                     "human-curation.json.",
             "labels": LABELS, "layout_types": list(LAYOUT_TYPES), "gates": results, "documents": docs,
             "errors": errors, "pages": pages}
    _dump(os.path.join(output_dir, "visual-page-index.json"), index)
    _dump(os.path.join(output_dir, "visual-shortlist.json"), short)
    picked = {(e["sha256"], e["page"]): e for e in short["entries"]}
    lean = []
    for p in pages:
        e = picked.get((p["sha256"], p["page"]))
        lean.append({**{k: v for k, v in p.items() if k not in ("doc_id", "file", "status")},
                     "raster": {k: v for k, v in p["raster"].items() if k != "signature"},
                     "shortlist": {"reasons": e["reasons"], "source": e["source"]} if e else None})
    _js(os.path.join(atlas, "atlas-data.js"), "ATLAS", {
        "documents": docs, "labels": LABELS, "layout_types": list(LAYOUT_TYPES), "pages": lean,
        "errors": errors, "gates": results, "coverage": short["coverage"]})
    _js(os.path.join(atlas, "curation-snapshot.js"), "ATLAS_CURATION", cur)
    shutil.copyfile(os.path.join(os.path.dirname(__file__), "atlas_template.html"), os.path.join(atlas, "index.html"))
    return {"index": index, "shortlist": short, "curation": curation.summary(cur), "stale_decisions": stale,
            "stats": stats, "warnings": warnings}


class _Handler(http.server.SimpleHTTPRequestHandler):
    """Static atlas plus one endpoint that saves reviewer decisions. Same origin only."""
    curation_path = ""

    def log_message(self, *a):
        pass

    def _local(self) -> bool:
        port = self.server.server_address[1]
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        origin = self.headers.get("Origin")
        return self.headers.get("Host") in hosts and (origin is None or origin.split("://")[-1] in hosts)

    def _send(self, code: int, body: dict) -> None:
        raw = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if not self._local():
            return self._send(403, {"error": "local requests only"})
        if self.path.split("?")[0] == "/api/curation":
            return self._send(200, curation.load(self.curation_path))
        return super().do_GET()

    def do_PUT(self):
        if not self._local() or self.path != "/api/curation":
            return self._send(403, {"error": "not allowed"})
        size = int(self.headers.get("Content-Length") or 0)
        if not 0 < size <= MAX_BODY:
            return self._send(413, {"error": "body too large"})
        try:
            curation.save(self.curation_path, json.loads(self.rfile.read(size)))
        except ValueError as e:
            return self._send(400, {"error": str(e)})
        return self._send(200, curation.summary(curation.load(self.curation_path)))


def make_server(output_dir: str, port: int = 8765):
    atlas = os.path.join(output_dir, "visual-atlas")
    handler = type("Handler", (_Handler,), {"curation_path": os.path.join(output_dir, "human-curation.json")})

    def factory(*a, **k):
        return handler(*a, directory=atlas, **k)
    return http.server.ThreadingHTTPServer(("127.0.0.1", port), factory)
