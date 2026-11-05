"""
M7.8 automatic image placement: before and after, with the reason for each outcome.

    python benchmarks/m78/run.py OUT_DIR [--cases a,b] [--examples]

``before`` is what the library delivers with Auto off. ``after`` asks for Auto on both
formats. DOCX pages come from LibreOffice, which proves nothing about Microsoft Word; without
LibreOffice the DOCX is reported as unverified. The run fails only on facts: a default that
moved, lost content, or a failure case that passed. It states measurements and shows pages:
it never decides that one page looks better.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import time
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


cases = _load("m78_cases", os.path.join(HERE, "cases.py"))

import pymupdf  # noqa: E402
from PIL import Image  # noqa: E402

from dynamic_pdf import DocumentBuilder  # noqa: E402
from dynamic_pdf.core.normalize import normalize  # noqa: E402
from dynamic_pdf.design.media_planner import apply_media_plan, plan_media  # noqa: E402
from dynamic_pdf.design.media_policy import media_policy_for  # noqa: E402
from dynamic_pdf.intelligence import AutoMediaOptions  # noqa: E402
from dynamic_pdf.intelligence.analysis import measure_blocks, simulate  # noqa: E402
from dynamic_pdf.layout.engine import LayoutEngine  # noqa: E402
from dynamic_pdf.layout.page_envelope import resolve_page_envelope  # noqa: E402
from dynamic_pdf.policy import RenderPolicy  # noqa: E402
from dynamic_pdf.qa.docx_checks import docx_to_pdf, office_version  # noqa: E402
from dynamic_pdf.renderers.docx_renderer import render_docx  # noqa: E402
from dynamic_pdf.schema.media_intent import MediaIntent  # noqa: E402
from dynamic_pdf.schema.page_system import Band, BandRow, PageSystem  # noqa: E402

AUTO = AutoMediaOptions(mode="auto", targets=("pdf", "docx"))
LO_TIMEOUT_S = 180
PREVIEW_DPI = 60


def pixel_hash(pdf: bytes) -> str:
    digest = hashlib.sha256()
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        for page in doc:
            digest.update(page.get_pixmap(dpi=72).samples)
            digest.update(page.get_text().encode("utf-8"))
    return digest.hexdigest()


def docx_hash(data: bytes) -> str:
    digest = hashlib.sha256()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for name in sorted(z.namelist()):
            if name != "docProps/core.xml":
                digest.update(name.encode() + z.read(name))
    return digest.hexdigest()


def page_count(pdf) -> int | None:
    if pdf is None:
        return None
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        return len(doc)


def strip(pdf: bytes) -> Image.Image:
    """The pages of ``pdf`` side by side."""
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        shots = [page.get_pixmap(dpi=PREVIEW_DPI) for page in doc]
    pages = [Image.frombytes("RGB", (p.width, p.height), p.samples) for p in shots]
    sheet = Image.new("RGB", (sum(p.width + 8 for p in pages), max(p.height for p in pages) + 8), "#8a8f94")
    x = 4
    for page in pages:
        sheet.paste(page, (x, 4))
        x += page.width + 8
    return sheet


def save_strip(pdf, path: str) -> str | None:
    if pdf is None:
        return None
    strip(pdf).save(path, optimize=True)
    return os.path.basename(path)


def candidates(report) -> list:
    return [{"name": c.name, "rendered": c.rendered, "pages": c.pages, "score": c.score,
             "adjusted": (c.metrics or {}).get("adjusted"), "legibility": (c.metrics or {}).get("image_legibility"),
             "outcome": "delivered" if c.name == report.strategy else (c.rejected or "scored lower than the delivered layout")}
            for c in report.candidates]


def to_pdf(data: bytes):
    return docx_to_pdf(data, LO_TIMEOUT_S)


def compare(name: str, assets: dict, out: str, examples: bool) -> dict:
    before = cases.make_case(name, assets)
    before.compose("smart")
    pdf0, docx0 = before.render(), before.render_docx()
    off = cases.make_case(name, assets)
    off.compose("smart", media=AutoMediaOptions())
    off_same = (pixel_hash(off.render()) == pixel_hash(pdf0) and docx_hash(off.render_docx()) == docx_hash(docx0))

    start = time.perf_counter()
    after = cases.make_case(name, assets)
    after.compose("smart", media=AUTO)
    pdf1 = after.render()
    seconds = time.perf_counter() - start
    docx1 = after.render_docx()
    r, base = after.last_composition, before.last_composition

    lo0, lo1 = to_pdf(docx0), to_pdf(docx1)
    gallery = os.path.join(out, "gallery")
    row = {
        "case": name,
        "off_identical": off_same,
        "before": {"strategy": base.strategy, "pdf_pages": base.page_count, "score": base.final_score,
                   "docx_pages_libreoffice": page_count(lo0)},
        "after": {"strategy": r.strategy, "pdf_pages": r.page_count, "score": r.final_score,
                  "docx_pages_libreoffice": page_count(lo1), "status": r.status,
                  "validation": r.validation_by_format, "fallback_reason": r.fallback_reason},
        "changed": {"pdf": pixel_hash(pdf0) != pixel_hash(pdf1), "docx": docx_hash(docx0) != docx_hash(docx1)},
        "seconds": round(seconds, 2),
        "render_attempts": r.render_attempts,
        "candidates": candidates(r),
        "media_decisions": r.media_decisions,
        "gallery": {"pdf_before": save_strip(pdf0, os.path.join(gallery, f"{name}-pdf-before.png")),
                    "pdf_after": save_strip(pdf1, os.path.join(gallery, f"{name}-pdf-after.png")),
                    "docx_before": save_strip(lo0, os.path.join(gallery, f"{name}-docx-before.png")),
                    "docx_after": save_strip(lo1, os.path.join(gallery, f"{name}-docx-after.png"))},
    }
    if examples:
        folder = os.path.join(out, "examples", name)
        os.makedirs(folder, exist_ok=True)
        for file, data in (("before.pdf", pdf0), ("after.pdf", pdf1), ("before.docx", docx0), ("after.docx", docx1)):
            with open(os.path.join(folder, file), "wb") as f:
                f.write(data)
    return row


def plan_preview(name: str, assets: dict, out: str) -> dict:
    """What the best plan looks like when another layout won. Shown, never delivered."""
    b = cases.make_case(name, assets)
    doc, theme = b._prepared_base()
    measures, frame = measure_blocks(doc, theme, None, {})
    positions = {}
    for region in simulate(measures, frame).regions:
        positions.setdefault(region.block, region)
    found = plan_media(doc, media_policy_for(b.last_design.decision.profile.value), resolve_page_envelope(doc, theme),
                       AUTO, RenderPolicy().assets, positions, measures, "preview")
    plan = found[0]
    done = normalize(apply_media_plan(doc, plan))
    buf = io.BytesIO()
    LayoutEngine(done, theme=theme).render(buf)
    lo = to_pdf(render_docx(done, theme, None)[0])
    gallery = os.path.join(out, "gallery")
    return {"case": name, "plan": plan.name, "placement": plan.decisions[0].placement, "width_pt": plan.decisions[0].box[0],
            "pdf": save_strip(buf.getvalue(), os.path.join(gallery, f"{name}-plan-pdf.png")),
            "docx": save_strip(lo, os.path.join(gallery, f"{name}-plan-docx.png")),
            "pdf_pages": page_count(buf.getvalue()), "docx_pages_libreoffice": page_count(lo)}


# ── cases that must not pass ────────────────────────────────────────────────────

def unfit_bands(assets):
    b = cases.make_case("executive_narrative", assets)
    b.page_system(PageSystem(header=Band(rows=[BandRow(start=["word " * 400], max_lines=1)])))
    b.compose("smart", media=AutoMediaOptions(mode="auto"))
    b.render()
    r = b.last_composition
    return r.status == "failed" and r.fallback_reason == "band_content_unfit", {"status": r.status, "reason": r.fallback_reason}


def word_required(assets):
    b = cases.make_case("executive_narrative", assets)
    b.compose("smart", media=AutoMediaOptions(mode="auto", targets=("pdf", "docx"), docx_validation="structural",
                                              word_required=True))
    b.render()
    r = b.last_composition
    return (r.status == "unverified" and not r.strategy.startswith("media:")
            and r.validation_by_format.get("word") == "unverified"), {"status": r.status, "strategy": r.strategy,
                                                                      "word": r.validation_by_format.get("word")}


def broken_asset(assets):
    with tempfile.TemporaryDirectory() as folder:
        bad = os.path.join(folder, "broken.png")
        with open(bad, "wb") as f:
            f.write(b"not an image")
        b = DocumentBuilder()
        b.paragraph(cases.EN)
        b.image(bad, intent=MediaIntent(role="photo"))
        b.compose("smart", media=AutoMediaOptions(mode="auto"))
        try:
            b.render()
        except Exception as e:
            return True, {"raised": type(e).__name__}
    return False, {"raised": None}


def too_small_for_its_minimum(assets):
    b = DocumentBuilder()
    b.paragraph(cases.EN)
    b.image(assets["tiny"], intent=MediaIntent(role="photo", min_display_width_pt=300))
    b.paragraph(cases.EN)
    b.compose("smart", media=AutoMediaOptions(mode="auto"))
    b.render()
    r = b.last_composition
    return not r.strategy.startswith("media:"), {"strategy": r.strategy}


def explicit_width(assets):
    b = cases.make_case("executive_narrative", assets)
    block = next(x for x in b._blocks if x.type == "image")
    block.width = 180
    b.compose("smart", media=AutoMediaOptions(mode="auto"))
    b.render()
    kept = next(x for x in b._prepared()[0].blocks if x.type == "image")
    return kept.width == 180 and kept.placement is None, {"width": kept.width, "strategy": b.last_composition.strategy}


FAILURE_CASES = {"bands that cannot fit": unfit_bands, "Word required, no adapter": word_required,
                 "broken asset": broken_asset, "minimum width above the DPI limit": too_small_for_its_minimum,
                 "explicit width": explicit_width}


# ── report ──────────────────────────────────────────────────────────────────────

def report_md(rows, failures, office) -> str:
    lines = ["# M7.8 Auto Media: measured results", "",
             f"LibreOffice: {office or 'not available: DOCX pages unverified'}. Microsoft Word: not run.", "",
             "| Case | Before | After | PDF pages | LibreOffice DOCX pages | Status | DOCX check |",
             "|---|---|---|---|---|---|---|"]
    for x in rows:
        b, a = x["before"], x["after"]
        lines.append(f"| {x['case']} | {b['strategy']} | {a['strategy']} | {b['pdf_pages']} → {a['pdf_pages']} | "
                     f"{b['docx_pages_libreoffice']} → {a['docx_pages_libreoffice']} | {a['status']} | "
                     f"{a['validation'].get('docx', '-')} |")
    for x in rows:
        lines += ["", f"## {x['case']}", "", "| Candidate | Rendered | Pages | Score | With gain | Outcome |",
                  "|---|---|---|---|---|---|"]
        for c in x["candidates"]:
            lines.append(f"| {c['name']} | {'yes' if c['rendered'] else 'no'} | {c['pages'] or '-'} | "
                         f"{c['score'] if c['score'] is not None else '-'} | "
                         f"{c['adjusted'] if c['adjusted'] is not None else '-'} | {c['outcome']} |")
    lines += ["", "## Cases that must not pass", "", "| Case | Held | Evidence |", "|---|---|---|"]
    lines += [f"| {k} | {'yes' if v['held'] else 'NO'} | `{json.dumps(v['evidence'], ensure_ascii=False)}` |"
              for k, v in failures.items()]
    return "\n".join(lines) + "\n"


def gallery_html(rows, previews) -> str:
    parts = ["<!doctype html><meta charset='utf-8'><title>M7.8 before and after</title>",
             "<style>body{font:14px system-ui;margin:16px;background:#f4f5f6}img{max-width:100%;display:block}"
             "section{margin-bottom:32px}.g{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}</style>",
             "<h1>M7.8 before and after</h1><p>Measured output only. No human has approved these pages. "
             "DOCX pages are LibreOffice's; Word was not run.</p>"]
    for x in rows:
        parts.append(f"<section><h2>{html.escape(x['case'])}</h2><p>{html.escape(x['before']['strategy'])} → "
                     f"{html.escape(x['after']['strategy'])}</p><div class='g'>")
        for key, label in (("pdf_before", "PDF before"), ("pdf_after", "PDF after"),
                           ("docx_before", "DOCX before"), ("docx_after", "DOCX after")):
            src = x["gallery"][key]
            parts.append(f"<div><b>{label}</b>" + (f"<img src='{src}' alt='{label}'>" if src else "<p>unverified</p>")
                         + "</div>")
        parts.append("</div></section>")
    for x in previews:
        parts.append(f"<section><h2>{html.escape(x['case'])}: plan not delivered</h2><div class='g'>"
                     f"<div><b>PDF</b><img src='{x['pdf']}' alt='PDF'></div>"
                     + (f"<div><b>DOCX</b><img src='{x['docx']}' alt='DOCX'></div>" if x["docx"] else "") + "</div></section>")
    return "".join(parts)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("out")
    parser.add_argument("--cases", default=",".join(cases.CASES))
    parser.add_argument("--examples", action="store_true", help="also keep before and after PDF and DOCX files")
    args = parser.parse_args(argv)
    warnings.simplefilter("ignore")
    gallery = os.path.join(args.out, "gallery")
    shutil.rmtree(gallery, ignore_errors=True)
    os.makedirs(gallery)
    folder = tempfile.mkdtemp(prefix="m78-")
    try:
        assets = cases.assets(folder)
        rows = []
        for name in args.cases.split(","):
            rows.append(compare(name, assets, args.out, args.examples))
            print(name, rows[-1]["before"]["strategy"], "->", rows[-1]["after"]["strategy"],
                  rows[-1]["after"]["status"], rows[-1]["after"]["validation"], flush=True)
        previews = [plan_preview("arabic_dense_bands", assets, args.out)]
        failures = {}
        for label, check in FAILURE_CASES.items():
            held, evidence = check(assets)
            failures[label] = {"held": held, "evidence": evidence}
            print(label, "held" if held else "DID NOT HOLD", evidence, flush=True)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    office = office_version()
    with open(os.path.join(args.out, "results.json"), "w", encoding="utf-8") as f:
        json.dump({"libreoffice": office, "word": "not run", "human_review": "none", "cases": rows,
                   "plan_previews": previews, "must_not_pass": failures}, f, ensure_ascii=False, indent=1, default=str)
    with open(os.path.join(args.out, "report.md"), "w", encoding="utf-8") as f:
        f.write(report_md(rows, failures, office))
    with open(os.path.join(gallery, "index.html"), "w", encoding="utf-8") as f:
        f.write(gallery_html(rows, previews))
    broken = [x["case"] for x in rows if not x["off_identical"] or x["after"]["validation"].get("pdf") == "failed"]
    broken += [k for k, v in failures.items() if not v["held"]]
    if broken:
        print("FAILED:", ", ".join(broken))
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
