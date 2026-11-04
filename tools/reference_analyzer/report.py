"""Offline HTML report with page previews and measured overlays."""
from __future__ import annotations

import html
import json
import os
from typing import Dict, List

LEGEND = [("content box (text, images, drawings)", "#d6007a"), ("text block", "#2f6fdb"),
          ("heading candidate", "#7a3fd1"), ("table (ruled)", "#1f9d55"), ("image", "#e07b00"),
          ("vector graphic region (possible chart)", "#c9a400"), ("rule", "#d62828"),
          ("body column", "#00a6b8")]
_C = dict((k.split(" (")[0], v) for k, v in LEGEND)


def render_preview(pdf_path: str, page_feat: dict, out_path: str, width_px: int = 560) -> None:
    import pymupdf
    from PIL import Image, ImageDraw
    with pymupdf.open(pdf_path) as doc:
        page = doc[page_feat["page"] - 1]
        zoom = width_px / page.rect.width
        pm = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        im = Image.frombytes("RGB", (pm.width, pm.height), pm.samples)
    d = ImageDraw.Draw(im, "RGBA")
    sc = lambda b: [b[0] * zoom, b[1] * zoom, b[2] * zoom, b[3] * zoom]   # noqa: E731
    cols = page_feat["columns"]["value"]
    if cols:
        for a, b in cols["intervals"]:
            d.rectangle([a * zoom, 0, b * zoom, 6], fill=(0, 166, 184, 160))
    if page_feat.get("content_box"):
        d.rectangle(sc(page_feat["content_box"]), outline=_C["content box"], width=2)
    for b in page_feat["text_blocks"]["value"]:
        color = _C["heading candidate"] if b["role"] == "heading_candidate" else _C["text block"]
        d.rectangle(sc(b["bbox"]), outline=color, width=2 if b["role"] == "heading_candidate" else 1)
    for t in page_feat["tables"]["value"]:
        d.rectangle(sc(t["bbox"]), outline=_C["table"], width=3)
    for i in page_feat["images"]["value"]:
        d.rectangle(sc(i["bbox"]), outline=_C["image"], width=3)
    for g in page_feat["vector_graphics"]["value"]:
        d.rectangle(sc(g["bbox"]), outline=_C["vector graphic region"], width=2)
    for rl in page_feat["rules"]["value"]:
        x0, y0, x1, y1 = sc(rl["bbox"])
        d.rectangle([x0, y0 - 1, x1, y1 + 1], fill=(214, 40, 40, 140))
    im.save(out_path, quality=72, optimize=True)


def _e(x) -> str:
    return html.escape("" if x is None else str(x))


def _val(v) -> str:
    if isinstance(v, (dict, list)):
        s = json.dumps(v, ensure_ascii=False)
        return f"<code>{_e(s if len(s) < 420 else s[:420] + ' …')}</code>"
    return _e(v)


def _badge(conf: str, basis: str) -> str:
    return f'<span class="b {_e(conf)}">{_e(conf)}</span> <span class="basis">{_e(basis)}</span>'


def write_report(out_dir: str, catalog: dict, features: List[dict], patterns: dict, warnings: List[dict],
                 previews: Dict[str, List[dict]]) -> str:
    docs = catalog["documents"]
    wcount: Dict[str, int] = {}
    for w in warnings:
        wcount[w.get("doc_id", "")] = wcount.get(w.get("doc_id", ""), 0) + 1
    H = ['<!doctype html><html lang="en"><head><meta charset="utf-8">'
         '<meta name="viewport" content="width=device-width, initial-scale=1">'
         '<title>Reference Analysis</title><style>'
         ':root{--bg:#f6f7f9;--card:#fff;--ink:#1d232b;--muted:#5d6774;--line:#d9dee5}'
         '@media (prefers-color-scheme:dark){:root{--bg:#14171c;--card:#1d2128;--ink:#e7eaee;--muted:#a3acb8;--line:#333a44}}'
         'body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 system-ui,sans-serif}'
         'main{max-width:1400px;margin:0 auto;padding:16px}section{background:var(--card);border:1px solid var(--line);'
         'border-radius:10px;padding:14px 16px;margin:16px 0}h1{font-size:22px}h2{font-size:18px;margin:4px 0 8px}'
         'h3{font-size:15px;margin:12px 0 6px}table{border-collapse:collapse;width:100%;font-size:12.5px}'
         'td,th{border:1px solid var(--line);padding:3px 6px;text-align:left;vertical-align:top}'
         'code{font-size:11.5px;word-break:break-word}.muted{color:var(--muted)}'
         '.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px}'
         'figure{margin:0}figure img{width:100%;border:1px solid var(--line);border-radius:4px;background:#fff}'
         'figcaption{font-size:12px;color:var(--muted)}.b{padding:0 6px;border-radius:8px;font-size:11px;color:#fff}'
         '.high{background:#1f7a4d}.medium{background:#9a6b00}.low{background:#b3261e}.basis{font-size:11px;color:var(--muted)}'
         '.legend span{display:inline-block;margin-right:14px;font-size:12px}.legend i{display:inline-block;width:12px;'
         'height:12px;margin-right:4px;vertical-align:-2px}</style></head><body><main>',
         '<h1>Reference design analysis</h1>',
         f'<p class="muted">{len(docs)} PDF file(s), analysed offline with {_e(catalog["tool"]["name"])} '
         f'{_e(catalog["tool"]["version"])}. <b>measured</b> values come directly from PDF objects; <b>inferred</b> '
         'values are heuristics with the stated confidence. Nothing here is a judgement of aesthetic quality. '
         'Patterns are proposals for human review.</p>',
         '<div class="legend">' + "".join(f'<span><i style="background:{c}"></i>{_e(n)}</span>' for n, c in LEGEND)
         + '</div>']
    H.append('<section><h2>Catalogue</h2><table><tr><th>doc_id</th><th>file</th><th>pages</th><th>status</th>'
             '<th>SHA-256</th><th>licence / reuse</th><th>provenance</th><th>duplicates</th><th>warnings</th></tr>')
    for d in docs:
        dup = "; ".join(f'{x["kind"]}: {", ".join(x["with"])}' for x in d["duplicates"]) or "—"
        H.append(f'<tr><td><a href="#{_e(d["doc_id"])}">{_e(d["doc_id"])}</a></td><td>{_e(d["file"])}</td>'
                 f'<td>{_e(d["page_count"])}</td><td>{_e(d["status"])}</td><td><code>{_e(d["sha256"][:16])}…</code></td>'
                 f'<td>{_e(d["license"]["status"])}</td><td>{_e(d["provenance"]["source"])}</td><td>{_e(dup)}</td>'
                 f'<td>{wcount.get(d["doc_id"], 0)}</td></tr>')
    H.append('</table></section>')
    for f in features:
        H.append(f'<section id="{_e(f["doc_id"])}"><h2>{_e(f["file"])} <span class="muted">({_e(f["doc_id"])}, '
                 f'{len(f["pages"])} pages)</span></h2><table><tr><th>measurement</th><th>value</th><th>unit</th>'
                 '<th>method</th><th>confidence</th></tr>')
        for k, v in f["summary"].items():
            H.append(f'<tr><td>{_e(k)}</td><td>{_val(v["value"])}</td><td>{_e(v["unit"])}</td><td>{_e(v["method"])}</td>'
                     f'<td>{_badge(v["confidence"], v["basis"])}</td></tr>')
        rc = f["recipe_candidate"]
        H.append(f'</table><h3>Recipe candidate <span class="muted">({_e(rc["status"])})</span></h3>'
                 f'<p>{_val(rc["fields"])} → nearest existing recipe: {_val(rc["nearest_existing_recipe"])}</p>'
                 '<h3>Page previews with measured overlays</h3><div class="grid">')
        for pv in previews.get(f["doc_id"], []):
            pg = pv["features"]
            mt = pg["margins_text"]["value"] or {}
            fonts = ", ".join(f'{x["family"]} {x["size_pt"]}' for x in pg["fonts"]["value"][:3])
            cols = pg["columns"]["value"]["count"] if pg["columns"]["value"] else "—"
            H.append(f'<figure id="{_e(f["doc_id"])}-p{pg["page"]}"><img loading="lazy" src="{_e(pv["src"])}" '
                     f'alt="page {pg["page"]} with overlays"><figcaption>p.{pg["page"]} · '
                     f'{pg["size"]["value"]["width_mm"]}×{pg["size"]["value"]["height_mm"]} mm · margins L/R/T/B '
                     f'{_e(mt.get("left"))}/{_e(mt.get("right"))}/{_e(mt.get("top"))}/{_e(mt.get("bottom"))} pt · '
                     f'{_e(pg["script"]["value"]["class"])} · columns {_e(cols)} · {_e(fonts)} · extraction '
                     f'{_e(", ".join(pg["extraction"]["value"]))}</figcaption></figure>')
        H.append('</div></section>')
    H.append('<section><h2>Proposed patterns (inferred — need human review)</h2>'
             f'<p class="muted">{_e(patterns["note"])}</p>')
    for title, group in (("Recurring", patterns["recurring"]), ("Single-document observations",
                                                                 patterns["observations"])):
        H.append(f'<h3>{title} ({len(group)})</h3><table><tr><th>pattern</th><th>proposal</th><th>support</th>'
                 '<th>evidence (pages)</th></tr>')
        for p in group:
            ev = "<br>".join(
                f'<a href="#{_e(e["doc_id"])}">{_e(e["file"])}</a>: '
                + ", ".join(f'<a href="#{_e(e["doc_id"])}-p{n}">{n}</a>' for n in e["pages"][:10])
                for e in p["evidence"])
            H.append(f'<tr><td>{_e(p["title"])}<br><span class="muted">{_e(p["id"])}</span></td>'
                     f'<td>{_val(p["proposal"])}</td><td>{p["support_docs"]} doc(s) {_badge(p["confidence"], p["basis"])}'
                     f'</td><td>{ev}</td></tr>')
        H.append('</table>')
    H.append('</section><section><h2>Warnings</h2><table><tr><th>document</th><th>page</th><th>code</th>'
             '<th>severity</th><th>message</th></tr>')
    for w in warnings:
        H.append(f'<tr><td>{_e(w.get("file", ""))}</td><td>{_e(w.get("page", ""))}</td><td>{_e(w["code"])}</td>'
                 f'<td>{_e(w["severity"])}</td><td>{_e(w["message"])}</td></tr>')
    H.append('</table></section></main></body></html>')
    path = os.path.join(out_dir, "analysis-report.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(H))
    return path
