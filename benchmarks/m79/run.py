"""
M7.9 art direction: the stable output against designed variants, whole documents only.

    python benchmarks/m79/run.py OUT_DIR [--docs a,b] [--n 3] [--keep-files] [--no-memory]

``baseline`` is what ``render()`` and ``render_docx()`` deliver today. Each document then
goes through the public ``design_variants`` call. Every page of every candidate is shown,
from the PDF and, when LibreOffice is available, from the DOCX as LibreOffice sets it,
which proves nothing about Microsoft Word.

The run reports measurements and hard failures. It does not decide that a design looks
better. ``assessments.json`` beside this file holds an AI reviewer's notes from looking at
the rendered sheets; they are labelled as such and no person has judged these pages.
"""
from __future__ import annotations

import argparse
import html
import importlib.util

import json
import os
import shutil
import sys
import tempfile
import time
import tracemalloc
import warnings

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


corpus = _load("m79_corpus", os.path.join(HERE, "corpus.py"))

import pymupdf  # noqa: E402
from PIL import Image  # noqa: E402

from dynamic_pdf.design.directions import DIRECTIONS  # noqa: E402
from dynamic_pdf.qa.docx_checks import docx_to_pdf, office_version  # noqa: E402
from dynamic_pdf.qa.visual_critique import HEURISTIC_LABEL, critique_pdf  # noqa: E402

SHEET_DPI = 46
ASPECTS = {
    "composition": ("cover", "opener", "kpi"),
    "typography": ("heading_family", "body_family", "base_size", "line_height", "heading_scale"),
    "image treatment": ("hero_image", "side_image", "side_alternates"),
    "page rhythm": ("break_major", "statement", "numbered", "drop_cap", "lead"),
    "density": ("density", "margins"),
    "header and footer": ("bands",),
    "tables": ("table",),
}


def sheet(data: bytes, path: str) -> int:
    """Every page of a PDF, side by side."""
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        pix = [p.get_pixmap(dpi=SHEET_DPI) for p in doc]
    width = sum(p.width + 6 for p in pix) + 6
    out = Image.new("RGB", (width, max(p.height for p in pix) + 12), "#6f6f6f")
    x = 6
    for p in pix:
        out.paste(Image.frombytes("RGB", (p.width, p.height), p.samples), (x, 6))
        x += p.width + 6
    out.save(path, quality=76, optimize=True)
    return len(pix)


def differs(a, b) -> list:
    """The design aspects, beyond colour, on which two directions differ."""
    return [name for name, keys in ASPECTS.items() if any(getattr(a, k) != getattr(b, k) for k in keys)]


def fonts_of(data: bytes) -> list:
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        names = {f[3].split("+")[-1] for p in doc for f in p.get_fonts()}
    return sorted(names)


def office_pages(docx: bytes, target: str):
    if not office_version():
        return None
    made = docx_to_pdf(docx, timeout=120)
    return sheet(made, target) if made else None


def candidate(out, folder, name, cid, pdf, docx, keep):
    entry = {"sheet": None, "docx_sheet": None, "pdf_pages": None, "docx_pages": None,
             "pdf_kb": round(len(pdf) / 1024) if pdf else None, "docx_kb": round(len(docx) / 1024) if docx else None}
    if pdf:
        entry["sheet"] = f"{name}/{cid}-pdf.jpg"
        entry["pdf_pages"] = sheet(pdf, os.path.join(folder, f"{cid}-pdf.jpg"))
        entry["fonts"] = fonts_of(pdf)
    if docx:
        target = os.path.join(folder, f"{cid}-docx.jpg")
        entry["docx_pages"] = office_pages(docx, target)
        if entry["docx_pages"]:
            entry["docx_sheet"] = f"{name}/{cid}-docx.jpg"
    if keep:
        for ext, data in (("pdf", pdf), ("docx", docx)):
            if data:
                with open(os.path.join(folder, f"{cid}.{ext}"), "wb") as f:
                    f.write(data)
                entry[ext] = f"{name}/{cid}.{ext}"
    return entry


def peak_mb(fn) -> float:
    tracemalloc.start()
    try:
        fn()
        return round(tracemalloc.get_traced_memory()[1] / 1e6, 1)
    finally:
        tracemalloc.stop()


def run_one(name, assets, out, n, keep, memory):
    folder = os.path.join(out, name)
    os.makedirs(folder, exist_ok=True)
    builder, brand = corpus.DOCUMENTS[name](assets)
    t = time.perf_counter()
    base_pdf = builder.render()
    base_seconds = time.perf_counter() - t
    base_docx = builder.render_docx()
    t = time.perf_counter()
    designs = builder.design_variants(n=n, brand=brand or None)
    seconds = time.perf_counter() - t
    peak = peak_mb(lambda: corpus.DOCUMENTS[name](assets)[0].design_variants(n=n, brand=brand or None)) if memory else None
    base = critique_pdf(base_pdf)
    record = {
        "document": name, "title": builder.build().metadata.title if hasattr(builder.build(), "metadata") else name,
        "baseline": {**candidate(out, folder, name, "baseline", base_pdf, base_docx, keep),
                     "seconds": round(base_seconds, 2), "heuristics": base.heuristics},
        "seconds": round(seconds, 2), "peak_mb": peak, "renders": designs.stats["renders"],
        "plain_pages": designs.stats["plain_pages"], "recommended": designs.recommended.id if designs.recommended else None,
        "reasons": designs.reasons, "fallback": designs.fallback, "variants": [],
    }
    for v in designs:
        d = DIRECTIONS[v.id]
        rep = v.report
        plan = v.plan
        record["variants"].append({
            "id": v.id, "name": v.name, "status": rep.status, **candidate(out, folder, name, v.id, v.pdf, v.docx, keep),
            "seconds": rep.seconds, "renders": rep.renders, "fit": rep.fit, "index": rep.index,
            "heuristics": rep.heuristics, "hard_failures": rep.hard_failures, "refinements": rep.refinements,
            "observations": rep.observations, "unverified": rep.unverified,
            "cover": plan.cover if plan else None, "bands": plan.bands if plan else None,
            "typography": plan.typography if plan else None, "rhythm": plan.rhythm() if plan else [],
            "decisions": plan.decisions if plan else [],
            "differs_from": {o.id: differs(d, DIRECTIONS[o.id]) for o in designs if o.id != v.id},
        })
    with open(os.path.join(folder, "decisions.json"), "w", encoding="utf-8") as f:
        json.dump(designs.to_dict(), f, ensure_ascii=False, indent=1)
    return record


# ───────────────────────────── gallery ─────────────────────────────

CSS = """:root{--bg:#f4f3ef;--ink:#1f2225;--mut:#5c6166;--line:#d7d5cd;--card:#fff;--good:#1d6b45;--bad:#a0342a}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,'Segoe UI',Tahoma,sans-serif}
main{max-width:1500px;margin:0 auto;padding:24px 16px 64px}h1{font-size:26px;margin:0 0 6px}h2{font-size:19px;margin:30px 0 6px}
h3{font-size:15px;margin:0}a{color:#1d4f73}.mut{color:var(--mut)}.note{background:#fff8e3;border:1px solid #e7d9a8;padding:10px 12px;border-radius:6px}
table{border-collapse:collapse;width:100%;background:var(--card);font-size:13.5px}th,td{border:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
.row{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px;margin:14px 0}
.scroll{overflow-x:auto;margin-top:8px}.scroll img{display:block;max-width:none;height:auto}
.ok{color:var(--good);font-weight:600}.no{color:var(--bad);font-weight:600}.rec{background:var(--good);color:#fff;border-radius:4px;padding:1px 7px;font-size:12px}
ul{margin:6px 0;padding-inline-start:20px}.lbl{font-size:12.5px;color:var(--mut);margin-top:10px}details{margin-top:8px}"""


def page(title: str, body: str) -> str:
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
            f'content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title><style>{CSS}</style>'
            f"</head><body><main>{body}</main></body></html>")


def row(item: dict, title: str, extra: str, assessment: str = "") -> str:
    e = html.escape
    parts = [f'<section class="row"><h3>{title}</h3><div class="mut">{extra}</div>']
    if assessment:
        parts.append(f'<div class="lbl">AI reviewer, after viewing these pages (not a human judgement)</div><div>{e(assessment)}</div>')
    if item.get("sheet"):
        parts.append(f'<div class="lbl">PDF, every page ({item["pdf_pages"]})</div>'
                     f'<div class="scroll"><img loading="lazy" src="{os.path.basename(item["sheet"])}" alt="All PDF pages of {e(title)}"></div>')
    if item.get("docx_sheet"):
        parts.append(f'<div class="lbl">DOCX as set by LibreOffice, every page ({item["docx_pages"]})</div>'
                     f'<div class="scroll"><img loading="lazy" src="{os.path.basename(item["docx_sheet"])}" alt="All DOCX pages of {e(title)}"></div>')
    links = [f'<a href="{os.path.basename(item[k])}">{k.upper()}</a>' for k in ("pdf", "docx") if item.get(k)]
    if links:
        parts.append(f'<div class="lbl">{" · ".join(links)}</div>')
    return "".join(parts)


def document_page(r: dict, notes: dict) -> str:
    e = html.escape
    b = r["baseline"]
    my = notes.get(r["document"], {})
    body = [f'<p><a href="../index.html">All documents</a></p><h1>{e(r["document"].replace("_", " "))}</h1>',
            f'<p class="mut">Plain setting: {r["plain_pages"]} pages · {r["renders"]} renders in {r["seconds"]} s'
            + (f' · peak Python memory {r["peak_mb"]} MB' if r["peak_mb"] else "") + "</p>",
            '<h2>Why this recommendation</h2><ul>' + "".join(f"<li>{e(x)}</li>" for x in r["reasons"]) + "</ul>"]
    body.append(row(b, "Baseline: today's default output", f'{b["seconds"]} s', my.get("baseline", "")) + "</section>")
    for v in r["variants"]:
        ok = v["status"] == "valid"
        tag = f'<span class="{"ok" if ok else "no"}">{e(v["status"])}</span>'
        rec = ' <span class="rec">recommended</span>' if v["id"] == r["recommended"] else ""
        extra = f'{tag} · fit {v["fit"]:g} · ordering index {v["index"]:g} · {v["renders"]} renders · {e(v["typography"] or "")}'
        block = row(v, e(v["name"]) + rec, extra, my.get(v["id"], ""))
        if v["hard_failures"]:
            block += "<div class='lbl'>Hard failures</div><ul>" + "".join(f"<li>{e(x)}</li>" for x in v["hard_failures"]) + "</ul>"
        lines = [f'cover: {v["cover"]}', f'bands: {v["bands"]}', "rhythm: " + " → ".join(v["rhythm"])]
        block += ("<details><summary>Decisions and refinements</summary><ul>"
                  + "".join(f"<li>{e(str(x))}</li>" for x in lines + v["decisions"] + v["refinements"]) + "</ul></details>")
        body.append(block + "</section>")
    return page(r["document"], "".join(body))


def index_page(results: list, notes: dict, meta: dict) -> str:
    e = html.escape
    rows = []
    for r in results:
        valid = sum(v["status"] == "valid" for v in r["variants"])
        pages = "/".join(str(v["pdf_pages"]) for v in r["variants"])
        rows.append(f'<tr><td><a href="{r["document"]}/index.html">{e(r["document"].replace("_", " "))}</a></td>'
                    f'<td>{r["baseline"]["pdf_pages"]}</td><td>{pages}</td><td>{valid} of {len(r["variants"])}</td>'
                    f'<td>{e(str(r["recommended"]))}</td><td>{r["seconds"]} s</td><td>{r["peak_mb"] or "not measured"}</td></tr>')
    body = (f'<h1>M7.9 art direction: whole documents, before and after</h1>'
            f'<p class="note">{e(HEURISTIC_LABEL.capitalize())}. Every statement of quality here is either a measurement '
            f'or an AI reviewer\'s note, labelled as such. No person has reviewed these pages. '
            f'DOCX pages are LibreOffice {e(str(meta["office"]))}; Microsoft Word was not run, so Word compatibility is unverified.</p>'
            '<table><tr><th>Document</th><th>Baseline pages</th><th>Variant pages</th><th>Valid</th><th>Recommended</th>'
            '<th>Time</th><th>Peak MB</th></tr>' + "".join(rows) + "</table>")
    return page("M7.9 gallery", body)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("out")
    ap.add_argument("--docs", default="")
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--keep-files", action="store_true", help="also write each PDF and DOCX")
    ap.add_argument("--no-memory", action="store_true")
    args = ap.parse_args()
    warnings.simplefilter("ignore")
    os.makedirs(args.out, exist_ok=True)
    names = [n for n in args.docs.split(",") if n] or list(corpus.DOCUMENTS)
    notes_path = os.path.join(HERE, "assessments.json")
    notes = json.load(open(notes_path, encoding="utf-8")) if os.path.exists(notes_path) else {}
    results = []
    scratch = tempfile.mkdtemp(prefix="m79-assets-")
    try:
        assets = corpus.make_assets(scratch)
        for name in names:
            r = run_one(name, assets, args.out, args.n, args.keep_files, not args.no_memory)
            results.append(r)
            print(name, r["seconds"], [(v["id"], v["status"], v["pdf_pages"], v["docx_pages"]) for v in r["variants"]], flush=True)
            with open(os.path.join(args.out, name, "index.html"), "w", encoding="utf-8") as f:
                f.write(document_page(r, notes))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    meta = {"office": office_version() or "not available", "word": "not run", "heuristic_label": HEURISTIC_LABEL}
    with open(os.path.join(args.out, "index.html"), "w", encoding="utf-8") as f:
        f.write(index_page(results, notes, meta))
    with open(os.path.join(args.out, "results.json"), "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "documents": results}, f, ensure_ascii=False, indent=1)
    rejected = [(r["document"], v["id"]) for r in results for v in r["variants"] if v["status"] != "valid"]
    print("rejected:", rejected)
    return 1 if any(r["fallback"] for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
