"""
AI design preferences: blind comparisons of whole documents, stored apart from human labels.

``generate`` renders the variants of each fictional document and records hashes and
features. ``sheets`` draws blind A/B comparison images with random labels and keeps the key
in a separate file. ``record`` turns a reviewer's answers into the dataset, and ``check``
reports reversed-order consistency. Every row says the reviewer is an AI. A comparison can
only be recorded against a sheet that exists, so nothing can be labelled unseen.
"""
from __future__ import annotations

import hashlib
import importlib.util
import itertools
import json
import os
import random
import sys
import warnings
from collections import Counter
from typing import Dict, List, Optional

from .pipeline import ROOT, _dump, _jsonl, _load

FORMAT = "dynamic-pdf-builder/ai-preference"
CRITERIA = ("typography", "hierarchy", "balance", "whitespace", "imagery", "tables", "bands", "readability", "rhythm")
ANSWERS = ("A", "B", "tie", "abstain")
CONFIDENCE = ("high", "medium", "low")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _corpus():
    path = os.path.join(ROOT, "benchmarks", "m79", "corpus.py")
    spec = importlib.util.spec_from_file_location("m79_corpus", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["m79_corpus"] = module
    spec.loader.exec_module(module)
    return module


PLAIN = "@plain"                # a candidate rendered without the grammar


def generate(batch_dir: str, docs: Optional[List[str]] = None, n: int = 4, grammar: bool = True,
             baseline: bool = False, sources: Optional[dict] = None, max_pages: Optional[int] = None) -> dict:
    """Render ``n`` designs per document into ``batch_dir`` and write candidates.jsonl.
    ``baseline`` also renders each design without the grammar, under the id ``<design>@plain``,
    so a comparison can set a design against itself with and without the rules. A baseline
    identical to its grammar design is dropped: there would be nothing to compare.
    ``sources`` are the documents of ``corpus.documents`` in place of the m79 corpus; a design
    longer than ``max_pages`` is left out, and a document that cannot be built is reported."""
    from dynamic_pdf.intelligence.variant_ranker import variant_features

    from .layout_facts import measure
    assets = os.path.join(batch_dir, "assets")
    os.makedirs(batch_dir, exist_ok=True)
    if sources is None:
        corpus = _corpus()
        shared = corpus.make_assets(assets)
        sources = {k: {"make": lambda _, fn=fn: fn(shared)} for k, fn in corpus.DOCUMENTS.items()}
    rows, failed = [], {}
    for name in docs or list(sources):
        try:
            builder, brand = sources[name]["make"](assets)
            source = builder.build().model_dump_json().encode("utf-8")
            made = []
            for rules, suffix in [(grammar or None, "")] + ([(None, PLAIN)] if baseline else []):
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    made.append((builder.design_variants(n=n, brand=brand, grammar=rules), suffix))
        except Exception as e:  # noqa: BLE001 - one document that cannot be built must not lose the batch
            failed[name] = f"{type(e).__name__}: {e}"[:200]
            continue
        seen = set()
        for result, suffix in made:
            for v in result.variants:
                if not v.valid or _sha(v.pdf) in seen or (max_pages and v.report.pages > max_pages):
                    continue
                seen.add(_sha(v.pdf))
                candidate = v.id + suffix
                base = os.path.join(batch_dir, "renders", name)
                os.makedirs(base, exist_ok=True)
                for ext, blob in (("pdf", v.pdf), ("docx", v.docx)):
                    with open(os.path.join(base, f"{candidate}.{ext}"), "wb") as f:
                        f.write(blob)
                rows.append({"document": name, "document_hash": _sha(source), "candidate": candidate, "design": v.id,
                             "pdf_sha256": _sha(v.pdf), "docx_sha256": _sha(v.docx), "pages": v.report.pages,
                             "grammar_rules": v.report.grammar_rules, "grammar_version": v.report.grammar_version,
                             "deterministic_pick": result.recommended is v, "features": variant_features(v),
                             "context": result.stats.get("context"),
                             "layout_facts": measure(v.pdf, result.stats.get("plain_pages"))})
    with open(os.path.join(batch_dir, "candidates.jsonl"), "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return {"documents": len({r["document"] for r in rows}), "candidates": len(rows), **({"failed": failed} if failed else {})}


def trace(document: str, grammar: bool = True, model: Optional[str] = None) -> dict:
    """What actually ran for one fictional document: rules per design, and which selector chose."""
    import tempfile
    corpus = _corpus()
    with tempfile.TemporaryDirectory() as tmp, warnings.catch_warnings():
        warnings.simplefilter("ignore")
        builder, brand = corpus.DOCUMENTS[document](corpus.make_assets(tmp))
        made = builder.design_variants(n=4, brand=brand, grammar=grammar or None, ranker_model=model)
    return {"recommended": made.recommended.id if made.recommended else None, "selection": made.stats["selection"],
            "designs": {v.id: {"valid": v.valid, "grammar_version": v.report.grammar_version, "rules": v.report.grammar_rules,
                               "notes": [o for o in v.report.observations if o.startswith("grammar")]} for v in made.variants}}


def _page_images(pdf_path: str, width: int, limit: int):
    import pymupdf
    from PIL import Image
    doc = pymupdf.open(pdf_path)
    out = []
    for p in list(doc)[:limit]:
        s = width / p.rect.width
        pix = p.get_pixmap(matrix=pymupdf.Matrix(s, s), alpha=False)
        out.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
    return out, doc.page_count


def blind_sheet(a_pdf: str, b_pdf: str, out: str, width: int = 240, limit: int = 8) -> dict:
    """Two rows of whole-document pages, labelled only A and B."""
    from PIL import Image, ImageDraw
    a, na = _page_images(a_pdf, width, limit)
    b, nb = _page_images(b_pdf, width, limit)
    cols = max(len(a), len(b))
    h = max(x.height for x in a + b)
    im = Image.new("RGB", (cols * (width + 8) + 34, 2 * (h + 8) + 8), "#d8d8d8")
    d = ImageDraw.Draw(im)
    for r, (label, pages) in enumerate((("A", a), ("B", b))):
        y = 8 + r * (h + 8)
        d.text((10, y + h // 2), label, fill="#000000")
        for c, pic in enumerate(pages):
            im.paste(pic, (30 + c * (width + 8), y))
    im.save(out, quality=84)
    return {"pages_shown": [len(a), len(b)], "pages_total": [na, nb], "shown_px": width}


def _choose(rows: List[dict], count: int, rng: random.Random) -> list:
    """Pairs for one document. Each design against its own baseline comes first, so a rule's effect
    is judged with the art direction held still; the rest are random pairs of different designs."""
    pairs = list(itertools.combinations(rows, 2))
    rng.shuffle(pairs)
    own = [p for p in pairs if p[0].get("design", p[0]["candidate"]) == p[1].get("design", p[1]["candidate"])]
    other = [p for p in pairs if p not in own]
    return (own[:max(1, count // 2)] + other)[:count]


def sheets(batch_dir: str, pairs_per_doc: int = 2, seed: int = 79, repeats: int = 1, source: str = "pdf",
           docs: Optional[List[str]] = None, plan: Optional[str] = None) -> dict:
    """Blind PDF/Word sheets; an optional frozen plan chooses balanced, verified pairs.

    Plan contents must never be shown to the reviewing model/person. Missing, stale or
    hash-mismatched render files stop the run before any answer can be recorded.
    """
    rng = random.Random(seed)
    word = source == "word"
    out = os.path.join(batch_dir, "sheets-word" if word else "sheets")
    key_path = os.path.join(batch_dir, "key-word.json" if word else "key.json")
    if plan:
        from .reference_sampling import sheet_pairs
        if os.path.exists(key_path):
            raise SystemExit("the blind key already exists; use a fresh batch instead of overwriting reviewed sheets")
        pairs = sheet_pairs(batch_dir, source, plan)
        intended = {d for d, *_ in pairs}
        plan_rows = list(pairs)
        for doc in sorted(intended):
            plan_rows += [(d, b, a, True) for (d, a, b, _) in pairs if d == doc][:repeats]
    else:
        cands = _jsonl(os.path.join(batch_dir, "candidates.jsonl"))
        by: Dict[str, List[dict]] = {}
        for c in cands:
            if docs is None or c["document"] in docs:
                by.setdefault(c["document"], []).append(c)
        plan_rows = []
        for doc, rows in sorted(by.items()):
            for a, b in _choose(rows, pairs_per_doc, rng):
                if rng.random() < 0.5:
                    a, b = b, a
                plan_rows.append((doc, a, b, False))
            plan_rows += [(doc, b, a, True) for (d, a, b, _) in [p for p in plan_rows if p[0] == doc][:repeats]]
    rng.shuffle(plan_rows)
    os.makedirs(out, exist_ok=True)
    key = []
    for i, (doc, a, b, repeat) in enumerate(plan_rows, 1):
        cid = f"{'w' if word else 'cmp'}-{i:03d}"
        path = os.path.join(out, cid + ".jpg")

        def rendered(c):
            if word:
                return os.path.join(batch_dir, "word", f"{doc}__{c['candidate']}.pdf")
            return os.path.join(batch_dir, "renders", doc, c["candidate"] + ".pdf")

        info = blind_sheet(rendered(a), rendered(b), path)
        key.append({"comparison": cid, "document": doc, "a": a["candidate"], "b": b["candidate"],
                    "reversed_repeat": repeat, **info})
    _dump(key_path, {"note": "Do not open before the answers are written.", "comparisons": key})
    return {"sheets": len(key), "folder": out}

def record(batch_dir: str, answers: str, dataset: str, *, model: str, date: str, method: str,
           source: str = "pdf", extra: Optional[dict] = None) -> dict:
    """Join answers to the key, and append the dataset rows.

    An answer row: ``{comparison, preferred, criteria, justification, confidence, pages, formats_inspected}``.
    ``pages`` cites pages on the sheet as ``A3`` or ``B1``. ``extra`` adds traced fields, such as
    the prompt hash of a scripted review, to every row."""
    word = source == "word"
    key = {k["comparison"]: k for k in _load(os.path.join(batch_dir, "key-word.json" if word else "key.json"))["comparisons"]}
    cands = {(c["document"], c["candidate"]): c for c in _jsonl(os.path.join(batch_dir, "candidates.jsonl"))}
    rows = []
    for ans in _jsonl(answers):
        k = key.get(ans["comparison"])
        if k is None or not os.path.exists(os.path.join(batch_dir, "sheets-word" if word else "sheets", ans["comparison"] + ".jpg")):
            raise SystemExit(f"{ans['comparison']}: no such sheet; a comparison not seen cannot be recorded")
        if ans["preferred"] not in ANSWERS or ans["confidence"] not in CONFIDENCE:
            raise SystemExit(f"{ans['comparison']}: bad answer")
        if ans["preferred"] != "abstain" and not (ans.get("justification") and ans.get("pages")):
            raise SystemExit(f"{ans['comparison']}: an answer needs a visual reason and pages")
        unknown = set(ans.get("criteria") or {}) - set(CRITERIA)
        if unknown:
            raise SystemExit(f"{ans['comparison']}: unknown criteria {sorted(unknown)}")
        a, b = cands[(k["document"], k["a"])], cands[(k["document"], k["b"])]
        rows.append({"format": FORMAT, "comparison": ans["comparison"], "batch": os.path.basename(batch_dir.rstrip("/\\")),
                     "document": k["document"], "document_hash": a["document_hash"],
                     "a": {"candidate": a["candidate"], "pdf_sha256": a["pdf_sha256"], "docx_sha256": a["docx_sha256"]},
                     "b": {"candidate": b["candidate"], "pdf_sha256": b["pdf_sha256"], "docx_sha256": b["docx_sha256"]},
                     "preferred": ans["preferred"], "criteria": ans.get("criteria") or {},
                     "justification": ans.get("justification", ""), "confidence": ans["confidence"],
                     "supporting_pages": ans.get("pages") or [], "formats_inspected": ans.get("formats_inspected") or (["word"] if word else ["pdf"]),
                     "pages_shown": k["pages_shown"], "pages_total": k["pages_total"], "shown_px": k["shown_px"],
                     "reversed_repeat": k["reversed_repeat"], "reviewer_type": "ai", "model": model, "review_date": date,
                     "evaluation_method": method, "grammar_version": a.get("grammar_version"), **(extra or {})})
    os.makedirs(os.path.dirname(dataset), exist_ok=True)
    with open(dataset, "a", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return {"recorded": len(rows)}


def winner(row: dict) -> Optional[str]:
    if row["preferred"] == "A":
        return row["a"]["candidate"]
    if row["preferred"] == "B":
        return row["b"]["candidate"]
    return None


def check(dataset: str) -> dict:
    """Schema, counts and whether reversed repeats agreed."""
    rows = _jsonl(dataset)
    bad = [r.get("comparison") for r in rows if r.get("reviewer_type") != "ai" or not r.get("model")]
    if bad:
        raise SystemExit(f"rows that do not say they are AI work: {bad}")
    pair = lambda r: (r.get("model"), r["batch"], r["document"], frozenset((r["a"]["candidate"], r["b"]["candidate"])))  # noqa: E731
    first = {pair(r): r for r in rows if not r["reversed_repeat"]}
    same = differ = 0
    flips = []
    for r in rows:
        if r["reversed_repeat"] and pair(r) in first:
            x, y = winner(first[pair(r)]), winner(r)
            if x == y:
                same += 1
            else:
                differ += 1
                flips.append(r["comparison"])
    return {"rows": len(rows), "documents": len({r["document"] for r in rows}), "answers": dict(Counter(r["preferred"] for r in rows)),
            "confidence": dict(Counter(r["confidence"] for r in rows)), "reversed_pairs": same + differ,
            "reversed_consistent": same, "reversed_inconsistent": flips, "reviewer_types": sorted({r["reviewer_type"] for r in rows})}
