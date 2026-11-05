"""
Turn page graphs and review notes into the coverage file, the family catalog and the grammar.

    python -m tools.reference_analyzer.grammar_build [--analysis DIR] [--out DIR]

Rules are written by hand in ``grammar_rules.py``. This module adds what can be counted:
how many pages support a rule, in how many documents, and the spread of the measures the
rule's constraints depend on. Nothing here stores page text, pixels or absolute layouts.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
from collections import Counter, defaultdict
from typing import Dict, Iterable, List

from . import coverage as C
from .grammar_rules import FAMILY_TEXT, GRAMMAR_VERSION, RULES, UNSUPPORTED
from .graphs import FAMILIES

CATALOG_FORMAT = "dynamic-pdf-builder/m77-layout-family-catalog"
GRAMMAR_FORMAT = "dynamic-pdf-builder/m77-design-grammar"
# One template refilled three times counts once; both Unilever reports stay separate
# references, as asked, though they share a template and the report says so.
SOURCE_GROUPS = {"ref-b7b9ddcb4981": "cedarline-template", "ref-cc8416043d9b": "cedarline-template",
                 "ref-582bd105b7d9": "cedarline-template"}
MEASURES = ("text_share", "image_share", "largest_image", "table_share", "vector_share", "ink", "chars",
            "max_size_pt", "display_ratio", "column_ratio", "numeric_big", "balance_lr", "edge_contact",
            "header_items", "footer_items")


def _load(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _write(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=False)
        f.write("\n")


def spread(values: Iterable[float]) -> dict:
    v = sorted(float(x) for x in values if x is not None)
    if not v:
        return {"n": 0}
    q = statistics.quantiles(v, n=4) if len(v) > 1 else [v[0]] * 3
    return {"n": len(v), "p25": round(q[0], 3), "median": round(q[1], 3), "p75": round(q[2], 3)}


def groups(docs: Iterable[str]) -> int:
    return len({SOURCE_GROUPS.get(d, d) for d in docs})


def evidence(pages: List[dict], limit: int = 6) -> List[dict]:
    """Pages an AI reviewer saw closely first, one per template cluster, spread across documents."""
    rank = {"detail_2up": 0, "detail_3up": 1, "contact_sheet": 2, "measured_only": 3}
    ordered = sorted(pages, key=lambda p: (rank[p["ai_observation"]["depth"]], -p["weight"], p["ref"]))
    picked, clusters, docs = [], set(), Counter()
    for p in ordered:
        key = (p["doc"], p["template_cluster"])
        if key in clusters or docs[p["doc"]] >= 2:
            continue
        clusters.add(key)
        docs[p["doc"]] += 1
        picked.append(p)
        if len(picked) == limit:
            break
    return [{"ref": p["ref"], "depth": p["ai_observation"]["depth"], "shown_px": p["ai_observation"]["shown_px"],
             "note": p["ai_observation"]["note"]} for p in picked]


def precision(analysis_dir: str) -> Dict[str, dict]:
    """Agreement of the assigned family with a close look, from the seeded stratified sample."""
    path = os.path.join(analysis_dir, "grammar", "review-notes-detail.jsonl")
    out: Dict[str, dict] = defaultdict(lambda: {"sampled": 0, "agreed": 0, "seen_as": Counter()})
    with open(path, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("sample") != "family_precision_seed77":
                continue
            s = out[r["sample_family"]]
            s["sampled"] += 1
            s["agreed"] += not r["corrects_family"]
            if r["corrects_family"]:
                s["seen_as"][r["family"]] += 1
    return {k: {**v, "seen_as": dict(v["seen_as"])} for k, v in out.items()}


def family_catalog(coverage: dict, graphs: dict, sample: Dict[str, dict]) -> dict:
    by_ref = {g["ref"]: g for g in graphs["pages"]}
    fams: Dict[str, List[dict]] = defaultdict(list)
    for p in coverage["pages"]:
        fams[p["ai_observation"]["family"]].append(p)
    rows = []
    for fam, pages in sorted(fams.items(), key=lambda kv: -sum(p["weight"] for p in kv[1])):
        graph = [by_ref[p["ref"]] for p in pages]
        docs = sorted({p["doc"] for p in pages})
        rows.append({
            "id": fam,
            "description": {**FAMILIES, **C.EXTRA_FAMILIES}.get(fam, fam),
            "definition": FAMILY_TEXT.get(fam, ""),
            "measured": {
                "pages": len(pages), "weighted_pages": round(sum(p["weight"] for p in pages), 1),
                "documents": len(docs), "independent_source_groups": groups(docs),
                "directions": dict(Counter(g["direction"] for g in graph)),
                "columns": dict(Counter(str((g["grid"] or {}).get("columns")) for g in graph)),
                "measures": {m: spread(g["measures"].get(m) for g in graph) for m in MEASURES},
            },
            "ai_observation": {
                "inspection_depth": dict(Counter(p["ai_observation"]["depth"] for p in pages)),
                "family_source": dict(Counter(p["ai_observation"]["family_source"] for p in pages)),
                "precision_sample": sample.get(fam),
                "evidence_pages": evidence(pages),
            },
            "unverified": {"human_reviewed_pages": 0,
                           "note": "Contact-sheet pages keep the family the measurements and notes gave them."},
        })
    agreed = sum(s["agreed"] for s in sample.values())
    total = sum(s["sampled"] for s in sample.values())
    return {"format": CATALOG_FORMAT, "version": GRAMMAR_VERSION,
            "note": "Page counts and measures are measured. Families are an AI reviewer's assignment, not a human "
                    "label. weighted_pages counts a repeated template once per document.",
            "precision": {"sampled": total, "agreed": agreed, "rate": round(agreed / total, 3) if total else None,
                          "method": "four pages per family, seed 77, drawn from pages not yet seen closely, viewed at "
                                    "780 px; families that failed were corrected only on the pages seen"},
            "families": rows}


def _support(rule: dict, coverage: dict, by_ref: dict) -> dict:
    families = set(rule["families"])
    pages = [p for p in coverage["pages"] if p["ai_observation"]["family"] in families]
    named = {e["ref"] for e in rule["evidence_pages"]}
    known = {p["ref"] for p in coverage["pages"]}
    missing = sorted(named - known)
    if missing:
        raise ValueError(f"{rule['id']}: evidence pages not in the corpus: {missing}")
    docs = {p["doc"] for p in pages}
    keys = rule.get("measures") or ()
    return {"family_pages": len(pages), "weighted_pages": round(sum(p["weight"] for p in pages), 1),
            "documents": len(docs), "independent_source_groups": groups(docs),
            "rtl_pages": sum(by_ref[p["ref"]]["direction"] == "rtl" for p in pages),
            "evidence_documents": len({r.split(":")[0] for r in named}),
            "measures": {k: spread(by_ref[p["ref"]]["measures"].get(k) for p in pages) for k in keys}}


def grammar(coverage: dict, graphs: dict) -> dict:
    by_ref = {g["ref"]: g for g in graphs["pages"]}
    depth = {p["ref"]: p["ai_observation"] for p in coverage["pages"]}
    rules = []
    for rule in RULES:
        r = {k: v for k, v in rule.items() if k != "measures"}
        r["evidence_pages"] = [{**e, "depth": depth[e["ref"]]["depth"], "shown_px": depth[e["ref"]]["shown_px"]}
                               for e in rule["evidence_pages"]]
        r["measured_support"] = _support(rule, coverage, by_ref)
        rules.append(r)
    return {"format": GRAMMAR_FORMAT, "version": GRAMMAR_VERSION, "status": "ai_reviewed",
            "note": "Rules state relationships in normalized page terms. They are an AI reviewer's reading of the "
                    "corpus, supported by measurements. No person has approved them. No branding, artwork or complete "
                    "page arrangement is reproduced.",
            "coordinates": "x runs from the reading start edge (0) to the reading end edge (1); y from top to bottom",
            "rules": rules, "unsupported_primitives": UNSUPPORTED}


def approved(full: dict, approval: dict) -> dict:
    """The packaged subset: only what the engine can consume, without evidence pages or notes."""
    keep = ("id", "name", "slot", "page_roles", "required_elements", "layout_constraints", "rtl_behavior", "confidence",
            "failure_conditions", "safe_fallback", "when", "engine")
    rules = [{k: r[k] for k in keep} for r in full["rules"] if r.get("engine")]
    return {"format": "dynamic-pdf-builder/approved-design-grammar", "version": full["version"], "status": "approved",
            "approval": approval, "rules": rules}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--analysis", default="D:/Dynamic-PDF-Design-References-analysis")
    ap.add_argument("--out", default="docs/m77-design-grammar")
    a = ap.parse_args(argv)
    graphs = _load(os.path.join(a.analysis, "grammar", "page-composition-graphs.json"))
    catalog = _load(os.path.join(a.analysis, "reference-catalog.json"))
    cov = C.build(a.analysis, catalog, graphs)
    sample = precision(a.analysis)
    _write(os.path.join(a.out, "full-corpus-coverage.json"), cov)
    _write(os.path.join(a.out, "layout-family-catalog.json"), family_catalog(cov, graphs, sample))
    _write(os.path.join(a.out, "design-grammar.json"), grammar(cov, graphs))
    print(json.dumps(cov["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
