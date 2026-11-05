"""
M7.7: does the approved grammar change new pages? One rule at a time, on fictional documents.

    python benchmarks/m77/run.py OUT_DIR [--rules a,b] [--keep-files] [--corpus]

Each demonstration renders the same document in the same direction twice: without the
grammar, then with one rule. It reports what can be measured from the PDF and the DOCX and
draws the changed pages side by side. It does not decide which looks better.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
import warnings
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


corpus = _load("m79_corpus", os.path.join(ROOT, "benchmarks", "m79", "corpus.py"))

import numpy as np  # noqa: E402
import pymupdf  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from dynamic_pdf.design import grammar as G  # noqa: E402
from dynamic_pdf.qa.docx_checks import docx_to_pdf, office_version  # noqa: E402

# rule, document, direction, what to read in the measurements
DEMOS = [
    ("cover.photo_over_panel", "annual_report", "corporate_conservative", "cover"),
    ("cover.low_title_field", "impact_report", "executive_premium", "cover"),
    ("cover.low_title_field", "arabic_annual", "arabic_institutional", "cover"),
    ("opener.edge_strip_page", "annual_report", "corporate_conservative", "openers"),
    ("kpi.hero_and_grid", "annual_report", "corporate_conservative", "figures"),
    ("table.current_period_ledger", "financial_statements", "executive_premium", "tables"),
    ("bands.dense_filled_head_foot", "financial_statements", "financial_data", "bands"),
    ("bands.dense_filled_head_foot", "arabic_annual", "financial_data", "bands"),
    ("image.alternating_inset", "annual_report", "corporate_conservative", "images"),
    ("closing.image_band", "sustainability_report", "corporate_conservative", "images"),
]


def page_measure(page) -> dict:
    w, h = page.rect.width, page.rect.height
    images = []
    for info in page.get_image_info():
        x0, y0, x1, y1 = info["bbox"]
        images.append([round(x0 / w, 3), round(y0 / h, 3), round(x1 / w, 3), round(y1 / h, 3)])
    fills = []
    for d in page.get_drawings():
        r = d.get("rect")
        if d.get("fill") and r and r.width * r.height > 0.002 * w * h:
            fills.append([round(r.x0 / w, 3), round(r.y0 / h, 3), round(r.x1 / w, 3), round(r.y1 / h, 3)])
    spans = [s for b in page.get_text("dict")["blocks"] for ln in b.get("lines", ()) for s in ln["spans"] if s["text"].strip()]
    biggest = max(spans, key=lambda s: s["size"], default=None)
    words = len(page.get_text().split())
    return {"images": images, "fills": fills, "words": words,
            "largest_type_pt": round(biggest["size"], 1) if biggest else 0,
            "largest_type_top": round(biggest["bbox"][1] / h, 3) if biggest else None,
            "largest_type_centre_x": round((biggest["bbox"][0] + biggest["bbox"][2]) / 2 / w, 3) if biggest else None,
            "head_band": any(f[1] <= 0.002 and f[3] < 0.08 and f[2] - f[0] > 0.9 for f in fills),
            "foot_band": any(f[3] >= 0.998 and f[1] > 0.92 and f[2] - f[0] > 0.9 for f in fills),
            "side_images": ["start" if i[2] < 0.62 else "end" if i[0] > 0.38 else "wide" for i in images
                            if i[2] - i[0] < 0.7]}


def pdf_measure(data: bytes) -> dict:
    doc = pymupdf.open(stream=data, filetype="pdf")
    return {"pages": doc.page_count, "by_page": [page_measure(p) for p in doc]}


def docx_measure(data: bytes) -> dict:
    import io
    z = zipfile.ZipFile(io.BytesIO(data))
    body = z.read("word/document.xml").decode("utf-8")
    parts = [n for n in z.namelist() if re.match(r"word/(header|footer)\d*\.xml", n)]
    return {"anchored_drawings": body.count("<wp:anchor"), "inline_drawings": body.count("<wp:inline"),
            "shaded_cells_and_paragraphs": body.count("<w:shd"), "media_files": sum(n.startswith("word/media/") for n in z.namelist()),
            "header_footer_parts": len(parts), "tables": body.count("<w:tbl>"), "bytes": len(data)}


def _pixels(data: bytes, dpi=40):
    doc = pymupdf.open(stream=data, filetype="pdf")
    out = []
    for p in doc:
        pix = p.get_pixmap(dpi=dpi, alpha=False)
        out.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples).convert("L").resize((120, 170)))
    return out


def changed_pages(a: bytes, b: bytes, floor=0.02) -> dict:
    """Share of each page that changed, on matched page numbers, and pages only one side has."""
    pa, pb = _pixels(a), _pixels(b)
    n = min(len(pa), len(pb))
    diff = [float((np.abs(np.asarray(x, float) - np.asarray(y, float)) > 24).mean()) for x, y in zip(pa[:n], pb[:n])]
    return {"compared": n, "pages_changed": sum(d > floor for d in diff), "largest_change": round(max(diff or [0]), 3),
            "mean_change": round(float(np.mean(diff or [0])), 3), "change_by_page": [round(d, 3) for d in diff],
            "extra_pages": abs(len(pa) - len(pb))}


def sheet(a: bytes, b: bytes, pages, path, width=420):
    da, db = pymupdf.open(stream=a, filetype="pdf"), pymupdf.open(stream=b, filetype="pdf")

    def draw(doc, i):
        if i >= doc.page_count:
            return None
        p = doc[i]
        pix = p.get_pixmap(matrix=pymupdf.Matrix(width / p.rect.width, width / p.rect.width), alpha=False)
        return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

    rows = [(draw(da, i), draw(db, i), i) for i in pages]
    h = max((x.height for r in rows for x in r[:2] if x), default=100)
    im = Image.new("RGB", (len(rows) * (width + 12) + 12, 2 * (h + 30) + 12), "#dddddd")
    d = ImageDraw.Draw(im)
    for c, (x, y, i) in enumerate(rows):
        for r, (pic, name) in enumerate(((x, "without grammar"), (y, "with rule"))):
            X, Y = 12 + c * (width + 12), 8 + r * (h + 30)
            d.text((X, Y), f"{name}, page {i + 1}", fill="#222222")
            if pic:
                im.paste(pic, (X, Y + 16))
    im.save(path, quality=86)


def whole_corpus(assets, grammar) -> list:
    """Every fictional document, three designs, without and with the whole grammar."""
    rows = []
    for name, make in corpus.DOCUMENTS.items():
        builder, brand = make(assets)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            plain = builder.design_variants(brand=brand)
            ruled = builder.design_variants(brand=brand, grammar=grammar)
        pairs = zip(plain.variants, ruled.variants)
        rows.append({"document": name,
                     "valid": [sum(v.valid for v in plain.variants), sum(v.valid for v in ruled.variants)],
                     "fell_back": sum(any(o.startswith("grammar") for o in v.report.observations) for v in ruled.variants),
                     "designs": [{"direction": b.id, "rules": b.report.grammar_rules, "pages": [a.report.pages, b.report.pages],
                                  "pages_changed": changed_pages(a.pdf, b.pdf)["pages_changed"] if a.valid and b.valid else None}
                                 for a, b in pairs]})
        print(name, rows[-1]["valid"], rows[-1]["fell_back"], flush=True)
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("out")
    ap.add_argument("--rules", default="")
    ap.add_argument("--keep-files", action="store_true")
    ap.add_argument("--corpus", action="store_true", help="also run all twelve documents with the whole grammar")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    assets = corpus.make_assets(os.path.join(a.out, "assets"))
    grammar = G.load()
    wanted = set(filter(None, a.rules.split(",")))
    results = []
    for rule, name, family, focus in DEMOS:
        if wanted and rule not in wanted:
            continue
        builder, brand = corpus.DOCUMENTS[name](assets)
        if rule == "closing.image_band":          # the rule needs a last photograph; both sides get it
            corpus.photo(builder, assets["coast"], "The harbour at the end of the survey season")
        if rule == "cover.low_title_field" and name == "arabic_annual":     # the rule fits titles of up to 32 characters
            builder.meta(title="التقرير السنوي ٢٠٢٥")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            base = builder.design_variants(families=[family], brand=brand).variants[0]
            used = builder.design_variants(families=[family], brand=brand, grammar=grammar, grammar_rules=[rule]).variants[0]
        row = {"rule": rule, "document": name, "direction": family, "focus": focus,
               "baseline_valid": base.valid, "valid": used.valid, "rules_reported": used.report.grammar_rules,
               "observations": [x for x in used.report.observations if x.startswith("grammar")]}
        if base.valid and used.valid:
            row["applied"] = rule in used.report.grammar_rules
            row["pixels"] = changed_pages(base.pdf, used.pdf)
            mb, mu = pdf_measure(base.pdf), pdf_measure(used.pdf)
            row["pdf"] = {"baseline_pages": mb["pages"], "pages": mu["pages"]}
            row["measures"] = {"baseline": mb["by_page"], "with_rule": mu["by_page"]}
            row["docx"] = {"baseline": docx_measure(base.docx), "with_rule": docx_measure(used.docx)}
            slug = f"{rule.replace('.', '-')}--{name}"
            order = sorted(range(len(row["pixels"]["change_by_page"])), key=lambda i: -row["pixels"]["change_by_page"][i])
            sheet(base.pdf, used.pdf, sorted(order[:3]), os.path.join(a.out, slug + ".jpg"))
            if office_version():
                try:
                    ob, ou = docx_to_pdf(base.docx), docx_to_pdf(used.docx)
                    row["docx"]["office_pages"] = {
                        "baseline": pymupdf.open(stream=ob, filetype="pdf").page_count,
                        "with_rule": pymupdf.open(stream=ou, filetype="pdf").page_count,
                        "pixels": changed_pages(ob, ou),
                        "note": "as LibreOffice sets it; this proves nothing about Microsoft Word"}
                    sheet(ob, ou, sorted(order[:3]), os.path.join(a.out, slug + ".docx.jpg"))
                except Exception as e:                # noqa: BLE001 - a missing office is a fact to report
                    row["docx"]["office_pages"] = {"error": str(e)[:120]}
            if a.keep_files:
                for label, v in (("baseline", base), ("grammar", used)):
                    for ext, blob in (("pdf", v.pdf), ("docx", v.docx)):
                        with open(os.path.join(a.out, f"{slug}.{label}.{ext}"), "wb") as f:
                            f.write(blob)
        else:
            row["failures"] = used.report.hard_failures[:4]
        results.append(row)
        print(rule, name, "applied" if row.get("applied") else "NOT APPLIED", row.get("pixels", {}).get("pages_changed"),
              "pages", row.get("pdf"), flush=True)
    whole = whole_corpus(assets, grammar) if a.corpus else None
    with open(os.path.join(a.out, "results.json"), "w", encoding="utf-8") as f:
        json.dump({"note": "Measurements only. No statement here says a design looks better.", "grammar": grammar.version,
                   "demonstrations": results, "whole_corpus": whole}, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
