"""
Local evidence gallery: each grammar rule next to the reference pages it cites.

    python -m tools.reference_analyzer.gallery OUT [--demos DIR]

Reference pages are copyrighted, so OUT must be outside the repository and the gallery is
for the machine it was made on. It is never published. The ``--demos`` folder holds the
original before/after sheets from ``benchmarks/m77/run.py``.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import shutil

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
STYLE = """body{font:15px/1.5 system-ui,sans-serif;margin:0 auto;max-width:1180px;padding:24px 16px;color:#1c2024;background:#fff}
h1{font-size:26px}h2{font-size:19px;margin:40px 0 4px}.m{color:#5b6570;font-size:13px}.note{background:#f4f1e8;padding:12px 14px}
figure{display:inline-block;margin:10px 12px 0 0;width:230px;vertical-align:top}figure img{width:100%;border:1px solid #d5d8dc}
figcaption{font-size:12px;color:#444}img.d{max-width:100%;border:1px solid #d5d8dc;margin-top:10px}ul{margin:6px 0;padding-left:20px}"""


def _page(doc, number: int, out: str, width: int = 460) -> None:
    import pymupdf
    page = doc[number - 1]
    scale = width / page.rect.width
    page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False).save(out, jpg_quality=82)


def build(out: str, demos: str = "") -> dict:
    import pymupdf
    if os.path.abspath(out).startswith(ROOT):
        raise SystemExit("the gallery holds reference pages, so it must stay outside the repository")
    from tools.design_learning.pipeline import paths
    p = paths()
    base = os.path.join(ROOT, "docs", "m77-design-grammar")
    with open(os.path.join(base, "design-grammar.json"), encoding="utf-8") as f:
        grammar = json.load(f)
    with open(os.path.join(base, "full-corpus-coverage.json"), encoding="utf-8") as f:
        files = {d["doc_id"]: d["file"] for d in json.load(f)["documents"]}
    os.makedirs(os.path.join(out, "pages"), exist_ok=True)
    os.makedirs(os.path.join(out, "demos"), exist_ok=True)
    open_docs, shown = {}, 0
    body = ["<h1>M7.7 grammar evidence</h1><p class='note'>Local only: reference pages are copyrighted. Rules are an AI reviewer's reading "
            "of the corpus; no person has approved them. Captions give the page, the depth it was seen at and the reason it is cited.</p>"]
    for rule in grammar["rules"]:
        kind = "engine rule" if rule.get("engine") else "documented, needs a primitive the engine lacks"
        body.append(f"<h2>{html.escape(rule['name'])}</h2><div class='m'>{rule['id']} · {kind} · confidence {rule['confidence']}</div><ul>")
        body += [f"<li>{html.escape(str(c))}</li>" for c in rule["layout_constraints"][:3]]
        body.append("</ul>")
        for e in rule["evidence_pages"]:
            doc_id, number = e["ref"].rsplit(":", 1)
            if doc_id not in open_docs:
                open_docs[doc_id] = pymupdf.open(os.path.join(p["reference_dir"], files[doc_id]))
            name = e["ref"].replace(":", "-") + ".jpg"
            target = os.path.join(out, "pages", name)
            if not os.path.exists(target):
                _page(open_docs[doc_id], int(number), target)
            shown += 1
            caption = f"{os.path.basename(files[doc_id])} p.{number} · {e['depth']} · {e['why']}"
            body.append(f"<figure><img loading='lazy' src='pages/{name}' alt=''><figcaption>{html.escape(caption)}</figcaption></figure>")
        for sheet in sorted(os.listdir(demos)) if demos else []:
            if sheet.startswith(rule["id"].replace(".", "-") + "--") and sheet.endswith(".jpg"):
                shutil.copy(os.path.join(demos, sheet), os.path.join(out, "demos", sheet))
                body.append(f"<div class='m'>Original demonstration: {html.escape(sheet)}</div><img class='d' loading='lazy' src='demos/{sheet}' alt=''>")
    for d in open_docs.values():
        d.close()
    with open(os.path.join(out, "index.html"), "w", encoding="utf-8") as f:
        f.write(f"<!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
                f"<title>M7.7 grammar evidence</title><style>{STYLE}</style>" + "\n".join(body))
    return {"rules": len(grammar["rules"]), "evidence_pages": shown, "index": os.path.join(out, "index.html")}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("out")
    ap.add_argument("--demos", default="")
    a = ap.parse_args()
    print(json.dumps(build(a.out, a.demos)))
