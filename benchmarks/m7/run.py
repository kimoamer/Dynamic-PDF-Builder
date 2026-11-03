"""
M7 visual-quality and performance benchmark (reproducible, CPU-only, offline).

    python benchmarks/m7/run.py OUT_DIR [--docs a,b] [--jobs N]

For every corpus document and both variants — ``baseline`` (designed layout,
``design("auto")``) and ``smart`` (``design("auto").compose("smart")``) — a
fresh worker process renders PDF and DOCX and records:

* cold (first in process) and warm PDF/DOCX render time, CPU time, peak RSS,
  layout renders and composition candidates;
* rendered-geometry score and score-independent layout facts (pages,
  underfilled body pages, separated figures, oversize figures, RTL alignment);
* PDF QA (PyMuPDF) and DOCX QA incl. the LibreOffice-rendered layout;
* content preservation: missing words (PDF, DOCX), duplicated or reordered
  paragraphs (DOCX logical text for every script; PDF text for LTR text;
  rendered geometry for every block);
* DOCX editability: real Word tables carrying each source table's header,
  Word heading styles, figures as images and text as text;
* network attempts (sockets are blocked; any attempt is recorded).

Then a packaging/import audit is run and ``report.md``, ``results.json`` and
an offline gallery (``gallery/index.html``) are written. Human preferences are
never generated: the gallery only *collects* them.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import statistics
import subprocess
import sys
import time
import unicodedata
import warnings

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path[:0] = [HERE, ROOT, os.path.join(ROOT, "tests"), os.path.join(ROOT, "scripts")]

VARIANTS = ("baseline", "smart")
_TOKEN = re.compile(r"[A-Za-z]{2,}|[ء-يٱ-ۓ]{2,}|[0-9٠-٩]+")
_ARABIC = re.compile(r"[؀-ۿ]")


# ───────────────────────────── helpers ─────────────────────────────

def _norm_tokens(text: str):
    text = "".join(c for c in unicodedata.normalize("NFKC", text) if unicodedata.category(c) != "Mn")
    return _TOKEN.findall(text.lower())


def _rss_mb() -> float:
    import resource
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(peak / (1024 * 1024) if sys.platform == "darwin" else peak / 1024, 1)


def _guard_network(log: list):
    """Block and record any outbound connection attempt (composition must be offline)."""
    import socket

    def deny(*a, **k):
        log.append(repr(a[:2])[:120])
        raise OSError("network disabled by M7 benchmark")
    socket.socket.connect = lambda self, *a, **k: deny(*a)
    socket.create_connection = deny
    socket.getaddrinfo = deny


def _count_layout_renders():
    from dynamic_pdf.layout.engine import LayoutEngine
    calls = []
    real = LayoutEngine.render

    def render(self, *a, **k):
        calls.append(1)
        return real(self, *a, **k)
    LayoutEngine.render = render
    return calls


def _fingerprints(doc):
    """(block index, first-6-token tuple) for every paragraph of ≥ 6 tokens."""
    from dynamic_pdf.core.inline import plain_text
    out = []
    for i, b in enumerate(doc.blocks):
        if b.type == "paragraph" and isinstance(b.text, str):
            toks = _norm_tokens(plain_text(b.text))
            if len(toks) >= 6:
                out.append((i, tuple(toks[:6]), bool(_ARABIC.search(b.text))))
    return out


def _find_all(stream, fp):
    n, k, hits = len(stream), len(fp), []
    first = fp[0]
    for j in range(n - k + 1):
        if stream[j] == first and tuple(stream[j:j + k]) == fp:
            hits.append(j)
    return hits


def _sequence_check(fps, text, ltr_only: bool):
    """Missing / duplicated / reordered paragraphs by token fingerprints."""
    stream = _norm_tokens(text)
    expected = {}
    for _, fp, _ in fps:
        expected[fp] = expected.get(fp, 0) + 1
    missing, dup, last, reordered, checked = [], [], -1, [], 0
    for i, fp, rtl in fps:
        if ltr_only and rtl:
            continue
        checked += 1
        hits = _find_all(stream, fp)
        if not hits:
            missing.append(i)
            continue
        if len(hits) > expected[fp]:
            dup.append(i)
        pos = next((h for h in hits if h > last), None)
        if pos is None:
            reordered.append(i)
        else:
            last = pos
    return {"checked": checked, "missing": missing, "duplicated": dup, "reordered": reordered}


def _geometry_facts(geo, score, doc):
    """Score-independent layout facts from the rendered geometry."""
    pages = {p.page: p for p in score.pages}
    under = [p.page for p in score.pages if p.role == "body" and p.fill < 0.6]
    # each block's regions must cover a contiguous page range (no duplicated placement)
    spans = {}
    for r in geo.regions:
        if r.block is not None:
            spans.setdefault(r.block, set()).add(r.page)
    dup_geo = [b for b, ps in spans.items() if len(ps) != max(ps) - min(ps) + 1]
    types = {i: b.type for i, b in enumerate(doc.blocks)}
    frame_h = statistics.mean(geo.pages[p].frame_height for p in geo.pages) if geo.pages else 1
    figs = [r for r in geo.regions if types.get(r.block) in ("chart", "image", "diagram", "mermaid")]
    oversize = sorted({r.block for r in figs if r.bottom < r.top and (r.top - r.bottom) > 0.8 * frame_h})
    # a figure that starts a page while the previous body page is under 60 % full
    first_page = {}
    for r in sorted(geo.regions, key=lambda r: (r.page, -r.top)):
        first_page.setdefault(r.block, r.page)
    pushed = []
    for b in sorted({r.block for r in figs}):
        p = first_page.get(b)
        prev = pages.get(p - 1) if p else None
        if prev is not None and prev.role == "body" and prev.fill < 0.6:
            pushed.append(b)
    # Arabic paragraphs (in any document) should hug the right edge of the text block;
    # frames carry 6pt padding, so "right-aligned" = within 8pt of the frame edge and
    # closer to the right edge than to the left one
    from dynamic_pdf.core.normalize import is_rtl_text
    from dynamic_pdf.core.inline import plain_text
    rtl_blocks = {i for i, b in enumerate(doc.blocks)
                  if b.type == "paragraph" and isinstance(b.text, str) and is_rtl_text(plain_text(b.text))}
    paras = [r for r in geo.regions if r.block in rtl_blocks]
    rtl = None
    if paras:
        right = 0
        for r in paras:
            info = geo.pages[r.page]
            gap_r = info.frame_x0 + info.frame_width - r.x1
            if gap_r <= 8 and gap_r <= r.x0 - info.frame_x0:
                right += 1
        rtl = round(right / len(paras), 3)
    return {"underfilled_body_pages": under, "geometry_duplicates": dup_geo, "oversize_figures": oversize,
            "figures_after_gap": pushed, "rtl_right_aligned_share": rtl}


_HARAKAT = re.compile(r"[\u064B-\u0652]")


def _rtl_checks(pdf, geo, doc, docx_plain: str):
    """Arabic-specific PDF checks the generic QA does not cover:

    * line order — for every Arabic paragraph laid out on ≥ 2 lines of one page,
      the line holding its first word must be above the line holding its last word;
    * box glyphs — spans drawn with ZapfDingbats/Symbol that carry text (≥ 3 chars),
      i.e. letters replaced by a symbol font;
    * diacritics — harakat present in the source vs in the PDF and DOCX text.
    """
    import pymupdf
    from dynamic_pdf.core.inline import plain_text
    from dynamic_pdf.core.normalize import is_rtl_text
    pdfdoc = pymupdf.open(stream=pdf, filetype="pdf")
    norm = lambda w: "".join(c for c in unicodedata.normalize("NFKC", w)  # noqa: E731
                             if c.isalpha() and unicodedata.category(c) != "Mn")
    checked, reversed_ = 0, []
    for i, b in enumerate(doc.blocks):
        if b.type != "paragraph" or not isinstance(b.text, str) or not is_rtl_text(plain_text(b.text)):
            continue
        regs = [r for r in geo.regions if r.block == i]
        if len(regs) != 1:
            continue
        r = regs[0]
        page = pdfdoc[r.page - 1]
        H = page.rect.height
        words = [w for w in page.get_text("words")
                 if H - r.top - 2 <= (w[1] + w[3]) / 2 <= H - r.bottom + 2]
        lines = sorted({round(w[3]) for w in words})
        toks = [norm(t) for t in plain_text(b.text).split() if norm(t)]
        if len(lines) < 2 or len(toks) < 6:
            continue
        def line_of(tok):
            ys = [round(w[3]) for w in words if norm(w[4]) == tok]
            return ys
        first, last = line_of(toks[0]), line_of(toks[-1])
        if not first or not last or toks.count(toks[0]) > 1 or toks.count(toks[-1]) > 1:
            continue
        checked += 1
        # reading order: first word on the top line, last word on the bottom line
        if min(first) != lines[0] or max(last) != lines[-1]:
            reversed_.append(i)
    boxes = 0
    for page in pdfdoc:
        for bl in page.get_text("dict")["blocks"]:
            for ln in bl.get("lines", []):
                for sp in ln["spans"]:
                    if sp["font"] in ("ZapfDingbats", "Symbol") and len(sp["text"].strip()) >= 3:
                        boxes += 1
    from dynamic_pdf.core.normalize import block_text
    src = sum(len(_HARAKAT.findall(plain_text(t))) for b in doc.blocks for t in block_text(b))
    pdf_text = "".join(p.get_text() for p in pdfdoc)
    return {"arabic_paragraphs_checked": checked, "line_order_defects": reversed_,
            "symbol_font_text_spans": boxes, "harakat_source": src,
            "harakat_pdf": len(_HARAKAT.findall(pdf_text)), "harakat_docx": len(_HARAKAT.findall(docx_plain))}


def _docx_editability(data, doc):
    import docx
    d = docx.Document(io.BytesIO(data))
    norm = lambda s: " ".join(_norm_tokens(s))  # noqa: E731
    word_tables = [[norm(c.text) for c in t.rows[0].cells] for t in d.tables if t.rows]
    src_tables = [b for b in doc.blocks if b.type == "table"]
    matched = 0
    for b in src_tables:
        hdr = [norm(h) for h in (b.headers or [])]
        if any(w[:len(hdr)] == hdr or w[-len(hdr):] == hdr[::-1] for w in word_tables if hdr):
            matched += 1
    headings = [p for p in d.paragraphs if p.style.name.startswith("Heading")]
    W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
    images = len(list(d.element.body.iter(A + "blip")))
    figures = sum(1 for b in doc.blocks if b.type in ("chart", "image", "diagram", "mermaid", "math"))
    text_chars = sum(len(t.text) for t in d.element.body.iter(W + "t"))
    return {"word_tables": len(d.tables), "source_tables": len(src_tables), "source_tables_editable": matched,
            "heading_styles": len(headings), "source_headings": sum(1 for b in doc.blocks if b.type == "heading"),
            "images": images, "figure_blocks": figures, "text_chars": text_chars}


def _sheet(pdf_bytes, work_dir, out_jpg, cols=5, width=230):
    from PIL import Image
    from dynamic_pdf.qa import contact_sheet, rasterize_pdf
    imgs = rasterize_pdf(pdf_bytes, work_dir, dpi=60)
    png = out_jpg[:-4] + ".png"
    contact_sheet(imgs, png, columns=cols, thumb_width=width)
    Image.open(png).convert("RGB").save(out_jpg, quality=72, optimize=True)
    os.remove(png)
    return len(imgs)


# ───────────────────────────── worker ─────────────────────────────

def worker(name: str, variant: str, out: str) -> dict:
    warnings.simplefilter("ignore")
    net: list = []
    _guard_network(net)
    t_imp = time.perf_counter()
    from dynamic_pdf.layout.engine import LayoutEngine  # noqa: F401  (import cost measured separately)
    import_s = time.perf_counter() - t_imp
    from corpus import CORPUS
    calls = _count_layout_renders()
    category, size, factory = CORPUS[name]

    def build():
        b = factory().design()
        return b.compose("smart") if variant == "smart" else b

    rss0 = _rss_mb()
    b = build()
    t0, c0 = time.perf_counter(), time.process_time()
    pdf = b.render()
    pdf_wall, pdf_cpu = time.perf_counter() - t0, time.process_time() - c0
    renders = len(calls)
    t1 = time.perf_counter()
    docx = b.render_docx()
    docx_wall = time.perf_counter() - t1
    rss_render = _rss_mb()
    # warm repeat (same process, fresh builder)
    b2 = build()
    t2 = time.perf_counter()
    b2.render()
    warm_pdf = time.perf_counter() - t2
    t3 = time.perf_counter()
    b2.render_docx()
    warm_docx = time.perf_counter() - t3

    # ── verification (not timed) ──
    import pymupdf
    from conftest import docx_text
    from dynamic_pdf.core.normalize import normalize
    from dynamic_pdf.intelligence.geometry import Geometry
    from dynamic_pdf.intelligence.scoring import score_layout
    from dynamic_pdf.qa import check_docx, check_pdf
    from dynamic_pdf.qa.loop import glyph_findings, qa_context
    from benchmark_compose import _keys, _source_words  # scripts/ (same tokenizer as M6 benchmarks)
    doc, theme = b._prepared()
    geo = Geometry()
    LayoutEngine(doc, theme=theme, geometry=geo).render(io.BytesIO())
    score = score_layout(geo, doc, theme)
    sem = normalize(doc)
    sp = theme.spacing
    pqa = check_pdf(pdf, margins={"left": sp.page_margin_left, "right": sp.page_margin_right},
                    heading_texts=[o.text for o in sem.outline], **qa_context(doc, theme))
    pqa.findings += glyph_findings(sem, theme)
    dqa = check_docx(docx, heading_texts=[o.text for o in sem.outline], visual=True)
    docx_pdf = getattr(dqa, "_pdf", None)
    src = b.build()
    words = _source_words(src)
    raw = "\n".join(p.get_text() for p in pymupdf.open(stream=pdf, filetype="pdf"))
    pdf_missing = sorted(words - (_keys(raw.replace("-\n", "")) | _keys(raw.replace("\n", ""))))
    dtext = docx_text(docx)
    docx_missing = sorted(words - _keys(dtext))
    fps = _fingerprints(doc)
    comp = b.last_composition
    rec = {
        "name": name, "variant": variant, "category": category, "size": size,
        "pages": pqa.pages, "pdf_sha256": hashlib.sha256(pdf).hexdigest(),
        # deterministic identity of the layout (PDF bytes embed a timestamp/ID)
        "layout_id": hashlib.sha256(json.dumps(sorted(
            (r.page, r.block if r.block is not None else -1, round(r.top), round(r.bottom)) for r in geo.regions
        )).encode()).hexdigest()[:16],
        "timing": {"pdf_cold_s": round(pdf_wall, 3), "pdf_cold_cpu_s": round(pdf_cpu, 3),
                   "docx_cold_s": round(docx_wall, 3), "pdf_warm_s": round(warm_pdf, 3),
                   "docx_warm_s": round(warm_docx, 3), "engine_import_s": round(import_s, 3)},
        "memory": {"rss_before_mb": rss0, "rss_peak_mb": rss_render},
        "renders": renders,
        "composition": None if comp is None else {
            "strategy": comp.strategy, "status": comp.status, "preflight": comp.preflight,
            "candidates_considered": len(comp.candidates) - 1,
            "candidates_rendered": sum(1 for c in comp.candidates if c.rendered) - 1,
            "render_attempts": comp.render_attempts, "repair_renders": comp.repair_renders,
            "design_trial_renders": comp.design_trial_renders, "fallbacks": comp.fallbacks},
        "score": {"value": score.score, "valid": score.valid, "hard_errors": score.hard_errors,
                  **{k: score.metrics.get(k) for k in ("utilization", "wasted", "readability", "cpl",
                                                         "separated_figures", "efficiency", "placement")}},
        "page_roles": [[p.page, p.role, p.fill] for p in score.pages],
        "layout": _geometry_facts(geo, score, doc),
        "rtl": _rtl_checks(pdf, geo, doc, dtext),
        "pdf_qa": {"status": pqa.status, "errors": [f"{f.code}: {f.message}" for f in pqa.errors],
                   "warnings": sorted({f.code for f in pqa.findings if f.severity == "warning"})},
        "docx_qa": {"status": dqa.status, "pages": dqa.pages, "unverified": dqa.unverified,
                    "errors": [f"{f.code}: {f.message}" for f in dqa.errors],
                    "warnings": sorted({f.code for f in dqa.findings if f.severity == "warning"})},
        "content": {"source_words": len(words), "pdf_missing_words": pdf_missing[:20],
                    "docx_missing_words": docx_missing[:20],
                    "pdf_sequence": _sequence_check(fps, raw, ltr_only=True),
                    "docx_sequence": _sequence_check(fps, dtext, ltr_only=False)},
        "docx_editability": _docx_editability(docx, doc),
        "diagnostics": [d.get("message", "")[:160] for d in b.diagnostics],
        "network_attempts": net,
    }
    gdir = os.path.join(out, "gallery", "img")
    os.makedirs(gdir, exist_ok=True)
    wdir = os.path.join(out, "work", name, variant)
    rec["sheets"] = {"pdf": f"img/{name}-{variant}-pdf.jpg"}
    _sheet(pdf, os.path.join(wdir, "pdf"), os.path.join(gdir, f"{name}-{variant}-pdf.jpg"))
    if docx_pdf:
        rec["sheets"]["docx"] = f"img/{name}-{variant}-docx.jpg"
        _sheet(docx_pdf, os.path.join(wdir, "docx"), os.path.join(gdir, f"{name}-{variant}-docx.jpg"))
    for ext, data in (("pdf", pdf), ("docx", docx)):
        os.makedirs(os.path.join(out, "outputs"), exist_ok=True)
        with open(os.path.join(out, "outputs", f"{name}-{variant}.{ext}"), "wb") as f:
            f.write(data)
    return rec


# ───────────────────────────── packaging audit ─────────────────────────────

def _dist_size(name: str):
    from importlib import metadata
    try:
        dist = metadata.distribution(name)
    except metadata.PackageNotFoundError:
        return None
    total = 0
    for f in dist.files or []:
        try:
            total += os.path.getsize(dist.locate_file(f))
        except OSError:
            pass
    return round(total / 2 ** 20, 2)


def _requires_closure(names):
    from importlib import metadata
    seen, todo = {}, list(names)
    while todo:
        n = re.split(r"[\s;<>=!~\[]", todo.pop(), maxsplit=1)[0].lower()
        if not n or n in seen:
            continue
        try:
            dist = metadata.distribution(n)
        except metadata.PackageNotFoundError:
            seen[n] = None
            continue
        seen[n] = dist.version
        for r in dist.requires or []:
            if "extra ==" not in r:
                todo.append(r)
    return seen


def perf_audit() -> dict:
    py = sys.executable
    code = ("import time,sys;t=time.perf_counter();import dynamic_pdf;"
            "d=time.perf_counter()-t;import resource;"
            "print(d, resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, "
            "' '.join(m for m in ('matplotlib','numpy','PIL','pymupdf','docx','reportlab','pydantic',"
            "'pygments','svglib','latex2mathml','pyphen','arabic_reshaper','bidi','lxml') if m in sys.modules))")
    runs = []
    for _ in range(7):
        o = subprocess.run([py, "-c", code], capture_output=True, text=True, cwd=ROOT, check=True).stdout.split()
        runs.append((float(o[0]), int(o[1]) / 1024, o[2:]))
    imp = subprocess.run([py, "-X", "importtime", "-c", "import dynamic_pdf"], capture_output=True, text=True,
                         cwd=ROOT).stderr
    by_root = {}             # self time summed per top-level package (incl. all submodules)
    for line in imp.splitlines():
        m = re.match(r"import time:\s+(\d+) \|\s+\d+ \|\s+(\S+)", line)
        if m:
            root = m.group(2).split(".")[0]
            by_root[root] = by_root.get(root, 0) + int(m.group(1)) / 1e6
    top = sorted(by_root.items(), key=lambda kv: -kv[1])[:12]
    text_only = ("import sys,io;from dynamic_pdf import DocumentBuilder;"
                 "DocumentBuilder().heading('T').paragraph('Body text.').table(['a','b'],[['1','2']]).render();"
                 "DocumentBuilder().heading('T').paragraph('Body').render_docx();"
                 "print(' '.join(m for m in ('matplotlib','numpy','pymupdf') if m in sys.modules))")
    loaded_text = subprocess.run([py, "-c", text_only], capture_output=True, text=True, cwd=ROOT).stdout.split()
    core = ["reportlab", "pydantic", "markdown-it-py", "pygments", "matplotlib", "Pillow", "latex2mathml",
            "svglib", "pyphen", "arabic-reshaper", "python-bidi", "python-docx"]
    closure = {n.replace("_", "-"): v for n, v in _requires_closure(core).items()}
    sizes = {n: _dist_size(n) for n in closure}
    optional = {n: _dist_size(n) for n in ("pymupdf", "pikepdf", "playwright", "lightgbm", "plotly", "kaleido")}
    mpl_closure = _requires_closure(["matplotlib"])
    mpl_only = set(mpl_closure) - set(_requires_closure([c for c in core if c != "matplotlib"]))
    return {
        "python": sys.version.split()[0], "cpu_count": os.cpu_count(),
        "import_s_median": round(statistics.median(r[0] for r in runs), 3),
        "import_s_min": round(min(r[0] for r in runs), 3),
        "import_rss_mb_median": round(statistics.median(r[1] for r in runs), 1),
        "modules_loaded_by_import": runs[0][2],
        "importtime_self_s_by_package": [[k, round(v, 3)] for k, v in top],
        "heavy_modules_after_text_only_render": loaded_text,
        "core_closure": {n: {"version": v, "mb": sizes[n]} for n, v in sorted(closure.items())},
        "core_closure_mb": round(sum(v or 0 for v in sizes.values()), 1),
        "matplotlib_only_mb": round(sum(sizes.get(n) or 0 for n in mpl_only), 1),
        "matplotlib_only_packages": sorted(mpl_only),
        "optional_installed_mb": optional,
    }


# ───────────────────────────── driver ─────────────────────────────

def main():
    if sys.argv[1:2] == ["--worker"]:
        _, _, name, variant, out = sys.argv[:5]
        rec = worker(name, variant, out)
        os.makedirs(os.path.join(out, "results"), exist_ok=True)
        with open(os.path.join(out, "results", f"{name}.{variant}.json"), "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False, indent=1)
        return
    out = os.path.abspath(sys.argv[1])
    from corpus import CORPUS
    only = sys.argv[sys.argv.index("--docs") + 1].split(",") if "--docs" in sys.argv else list(CORPUS)
    os.makedirs(out, exist_ok=True)
    for name in only:
        for v in VARIANTS:
            t = time.perf_counter()
            r = subprocess.run([sys.executable, __file__, "--worker", name, v, out], cwd=ROOT,
                               capture_output=True, text=True)
            ok = "ok" if r.returncode == 0 else "FAILED\n" + r.stderr[-2000:]
            print(f"{name:26} {v:8} {time.perf_counter() - t:6.1f}s {ok}", flush=True)
    perf = perf_audit()
    with open(os.path.join(out, "perf.json"), "w") as f:
        json.dump(perf, f, indent=1)
    from report import build
    build(out)


if __name__ == "__main__":
    main()
