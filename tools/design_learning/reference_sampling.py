"""Offline bridge from M7.7 reference measurements to M7.10 sampling.

Never creates preference labels, never trains, and never exports reference artwork.
The shared numerical dimensions are *proxies*, not calibrated equivalent measures.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import os
import random
import re
from collections import Counter, defaultdict

FORMAT = "dynamic-pdf-builder/reference-feature-profiles-v1"
PLAN_FORMAT = "dynamic-pdf-builder/blind-pair-plan-v1"
SHARED = ("cover_image_share", "image_share_mean", "text_share_mean", "pages_without_image_share")
CONTRAST = (*SHARED, "last_page_fill", "arabic_right_edge_share", "both_scripts_side_by_side")
LANG_WEIGHTS = {"arabic": 3.0, "bilingual": 2.6, "english": 1.0}
SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]*$")


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def jsonl(path):
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


def write_json(path, content):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(content, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


def _fraction(value, field):
    if not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError(f"invalid {field}: expected a finite fraction from 0 to 1")
    return float(value)


def bridge(graphs, coverage=None):
    """Aggregate measured M7.7 page graphs into abstract, non-label features.

    No page text, source paths, pixels, nodes, or subjective review notes are copied.
    """
    pages = graphs["pages"]
    documents = graphs["documents"]
    refs = [p["ref"] for p in pages]
    if not pages or len(set(refs)) != len(refs):
        raise ValueError("page graph missing pages or contains duplicate page references")
    by_doc = defaultdict(list)
    for page in pages:
        by_doc[page["doc"]].append(page)
    coverage_map, rights = {}, {}
    if coverage is not None:
        coverage_map = {p["ref"]: p for p in coverage["pages"]}
        if len(coverage_map) != len(coverage["pages"]) or set(coverage_map) != set(refs):
            raise ValueError("coverage page references do not match the graphs")
        rights = {d["doc_id"]: d.get("rights_note", "unknown") for d in coverage.get("documents", [])}
    result = []
    for doc in documents:
        did = doc["doc_id"]
        ordered = sorted(by_doc.get(did, []), key=lambda p: p["page"])
        if len(ordered) != doc["pages"] or [p["page"] for p in ordered] != list(range(1, doc["pages"] + 1)):
            raise ValueError(f"missing or out-of-range page in document {did}")
        inner = ordered[1:] or ordered
        def mean_metric(group, key):
            return round(sum(_fraction(p["measures"].get(key, 0), key) for p in group) / len(group), 4)
        family = Counter(p["family"] for p in ordered)
        weighted = defaultdict(float)
        for p in ordered:
            weighted[p["family"]] += 1.0 / max(1, p.get("cluster_in_document") or 1)
        direction = Counter(p["direction"] for p in ordered)
        language = ("bilingual" if direction["bilingual"] or (direction["rtl"] and direction["ltr"])
                    else "arabic" if direction["rtl"] else "english" if direction["ltr"] else "unknown")
        result.append({
            "document_id": did, "pages": len(ordered), "language_hint": language,
            "direction_pages": dict(sorted(direction.items())),
            "page_families": dict(sorted(family.items())),
            "cluster_weighted_families": {k: round(v, 4) for k, v in sorted(weighted.items())},
            "common_proxies": {
                "cover_image_share": round(_fraction(ordered[0]["measures"].get("image_share", 0), "image_share"), 4),
                "image_share_mean": mean_metric(inner, "image_share"),
                "text_share_mean": mean_metric(inner, "text_share"),
                "pages_without_image_share": round(sum(_fraction(p["measures"].get("image_share", 0), "image_share") < .02 for p in inner) / len(inner), 4),
            },
            "coverage_depth": dict(Counter(coverage_map[p["ref"]]["ai_observation"]["depth"] for p in ordered)) if coverage_map else {},
            "rights_status": rights.get(did, "unknown"),
            "label_kind": "none",
        })
    if set(by_doc) != {d["doc_id"] for d in documents}:
        raise ValueError("graph includes unregistered document pages")
    return {
        "format": FORMAT, "source": "M7.7 page-composition-graphs", "label_kind": "none",
        "measurement_note": "Only objective reference-derived proxies. M7.7 and M7.10 extraction methods are not calibrated; no labels or quality scores can be inferred.",
        "reference_pages": len(pages), "documents": result,
        "shared_proxies": list(SHARED),
    }


def _lang(document, c):
    facts = c.get("layout_facts") or {}
    if document.startswith("bilingual"):
        return "bilingual"
    if document.startswith("arabic"):
        return "arabic"
    if facts.get("both_scripts_side_by_side", 0) > .05:
        return "bilingual"
    if facts.get("arabic_line_share", 0) > .25:
        return "arabic"
    return "english"


def _split_index(split):
    doc_family = {}
    for f, docs in split["families"].items():
        for d in docs:
            if d in doc_family:
                raise ValueError(f"document {d} occurs in multiple families")
            doc_family[d] = f
    if set(split["evaluation_families"]) - set(split["families"]):
        raise ValueError("unknown held-out family")
    return doc_family


def _verify_hash_split(candidates, existing, split):
    family = _split_index(split)
    hashes = defaultdict(set)
    for c in candidates:
        if c["document"] not in family or not c.get("document_hash"):
            raise ValueError("candidate without registered family/source document hash")
        part = "evaluation" if family[c["document"]] in split["evaluation_families"] else "training"
        hashes[c["document_hash"]].add(part)
    for r in existing:
        if r["document"] not in family or not r.get("document_hash"):
            raise ValueError("historic comparison without registered family/source hash")
        part = "evaluation" if family[r["document"]] in split["evaluation_families"] else "training"
        hashes[r["document_hash"]].add(part)
    crossing = sorted(k for k, parts in hashes.items() if len(parts) > 1)
    if crossing:
        raise ValueError(f"source-hash leakage across training/evaluation: {len(crossing)} hashes")
    return family


def _media_file(batch_dir, candidate, source):
    doc, name = candidate["document"], candidate["candidate"]
    if not SAFE.fullmatch(doc) or not SAFE.fullmatch(name) or name in (".", ".."):
        raise ValueError("unsafe document or candidate path")
    return (os.path.join(batch_dir, "word", f"{doc}__{name}.pdf") if source == "word" else
            os.path.join(batch_dir, "renders", doc, name + ".pdf"))


def _media_ok(batch_dir, candidate, source, word_ok):
    pdf = _media_file(batch_dir, candidate, source)
    if not os.path.isfile(pdf) or os.path.getsize(pdf) == 0:
        return False
    if source == "word":
        name = candidate["document"] + "__" + candidate["candidate"]
        docx = os.path.join(batch_dir, "renders", candidate["document"], candidate["candidate"] + ".docx")
        entry = word_ok.get(name)
        if not entry or not os.path.isfile(docx):
            return False
        if not entry.get("docx_sha256") or not entry.get("pdf_sha256"):
            return False
        if entry["docx_sha256"] != candidate["docx_sha256"]:
            return False
        with open(docx, "rb") as f:
            source_ok = hashlib.sha256(f.read()).hexdigest() == entry["docx_sha256"]
        with open(pdf, "rb") as f:
            rendered_ok = hashlib.sha256(f.read()).hexdigest() == entry["pdf_sha256"]
        return source_ok and rendered_ok
    with open(pdf, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest() == candidate["pdf_sha256"]


def _contrast(a, b):
    x, y = a["layout_facts"], b["layout_facts"]
    return round(sum(min(1.0, abs(x[k] - y[k]) / (1.0 if k in SHARED or k == "last_page_fill" else .5))
                     for k in CONTRAST if k in x and k in y and isinstance(x[k], (int, float)) and isinstance(y[k], (int, float))), 3)


def plan(batch_dir, dataset, split_path, source="word", count=24, seed=79, max_per_doc=3,
         require_media=True, reference_features=None):
    """Select diverse *unjudged* candidate pairs. No opinions are created.

    Passing require_media=False produces a metadata-only queue, NOT drawable blind sheets.
    """
    if source not in ("pdf", "word") or count < 0 or max_per_doc < 1:
        raise ValueError("invalid source, count or max_per_doc")
    batch = os.path.basename(os.path.abspath(batch_dir))
    candidates = jsonl(os.path.join(batch_dir, "candidates.jsonl"))
    existing = jsonl(dataset)
    split = load(split_path)
    family = _verify_hash_split(candidates, existing, split)
    superseded_file = os.path.join(batch_dir, "superseded.json")
    superseded = {(r["document"], r["candidate"]) for r in load(superseded_file).get("candidates", [])} if os.path.exists(superseded_file) else set()
    by_doc = defaultdict(list)
    for c in candidates:
        if (c["document"], c["candidate"]) in superseded or not c.get("layout_facts"):
            continue
        _media_file(batch_dir, c, source)  # Validate path before any IO.
        by_doc[c["document"]].append(c)
    historic_pairs = set()
    historic_visuals = set()
    historic_lang = Counter()
    historic_docs = Counter()
    for r in existing:
        lang = _lang(r["document"], {"layout_facts": {}})
        if source in (r.get("formats_inspected") or []):
            historic_lang[lang] += 1
            historic_docs[r["document"]] += 1
            # Candidate names may be reused in a later batch with different code/renders.
            # Pair identities are only batch-scoped; render hashes remain global.
            if r["batch"] == batch:
                historic_pairs.add((r["document_hash"], frozenset((r["a"]["candidate"], r["b"]["candidate"]))))
            f = "pdf_sha256" if source == "pdf" else "docx_sha256"
            historic_visuals.add((r["document_hash"], frozenset((r["a"][f], r["b"][f]))))
    word_ok = {}
    word_manifest = os.path.join(batch_dir, "word", "word.json")
    word_version = None
    if source == "word" and os.path.isfile(word_manifest):
        info = load(word_manifest)
        word_ok = {x["file"]: x for x in info.get("files", []) if x.get("ok")}
        word_version = info.get("word_build")
    if source == "word" and require_media and not word_version:
        raise ValueError("Word build/version evidence missing; run preferences word first")
    ref_medians = {}
    if reference_features:
        ref = load(reference_features) if isinstance(reference_features, (str, os.PathLike)) else reference_features
        if ref.get("format") != FORMAT or ref.get("label_kind") != "none":
            raise ValueError("reference features must be objective M7.7 bridge profiles")
        for metric in SHARED:
            vals = sorted(d["common_proxies"][metric] for d in ref["documents"] if metric in d["common_proxies"])
            if vals:
                ref_medians[metric] = vals[len(vals) // 2]
    pools = []
    missing_media = 0
    for doc, rows in sorted(by_doc.items()):
        for a, b in itertools.combinations(rows, 2):
            f = "pdf_sha256" if source == "pdf" else "docx_sha256"
            if a[f] == b[f] or a["document_hash"] != b["document_hash"]:
                continue
            pair = (a["document_hash"], frozenset((a["candidate"], b["candidate"])))
            visual = (a["document_hash"], frozenset((a[f], b[f])))
            if pair in historic_pairs or visual in historic_visuals:
                continue
            if require_media and not (_media_ok(batch_dir, a, source, word_ok) and _media_ok(batch_dir, b, source, word_ok)):
                missing_media += 1
                continue
            distance = _contrast(a, b)
            directions = sum((a["layout_facts"].get(k, 0) - med) * (b["layout_facts"].get(k, 0) - med) < 0
                             for k, med in ref_medians.items())
            own_baseline = a.get("design") == b.get("design")
            pools.append((doc, a, b, distance, directions, own_baseline, pair, visual))
    rng = random.Random(seed)
    rng.shuffle(pools)
    selected, used_pairs, used_visuals = [], set(), set()
    new_docs, new_lang = Counter(), Counter()
    while len(selected) < count:
        best = None
        best_score = -1e12
        for row in pools:
            doc, a, b, dist, directions, own, pair, visual = row
            if pair in used_pairs or visual in used_visuals or new_docs[doc] >= max_per_doc:
                continue
            lang = _lang(doc, a)
            score = (12 * LANG_WEIGHTS[lang] / (1 + (historic_lang[lang] + new_lang[lang]) / 12)
                     + 8 / (1 + historic_docs[doc] + new_docs[doc])
                     + min(4, dist) + min(2, directions) + (2 if own else 0))
            if score > best_score:
                best_score, best = score, row
        if best is None:
            break
        doc, a, b, dist, directions, own, pair, visual = best
        if rng.random() < .5:
            a, b = b, a
        lang = _lang(doc, a)
        selected.append({"document": doc, "a": a["candidate"], "b": b["candidate"],
                         "language_hint": lang, "family": family[doc],
                         "split": "evaluation" if family[doc] in split["evaluation_families"] else "training",
                         "contrast": dist, "reference_median_crossings": directions, "own_baseline": own,
                         "reversed_repeat": False})
        new_lang[lang] += 1
        new_docs[doc] += 1
        used_pairs.add(pair)
        used_visuals.add(visual)
    with open(os.path.join(batch_dir, "candidates.jsonl"), "rb") as src:
        candidate_digest = hashlib.sha256(src.read()).hexdigest()
    with open(split_path, "rb") as src:
        split_digest = hashlib.sha256(src.read()).hexdigest()
    return {"format": PLAN_FORMAT, "batch": batch, "source": source,
            "candidates_sha256": candidate_digest, "split_sha256": split_digest,
            "split_source": os.path.abspath(split_path),
            "metadata_only": not require_media,
            "note": "Blind sheet input only; no labels, rankings, or human approval. Keep this key hidden from reviewers.",
            "word_build": word_version if source == "word" else None,
            "split_families_held_out": split["evaluation_families"],
            "summary": {"requested": count, "selected": len(selected), "eligible_pairs": len(pools),
                        "missing_media_pairs": missing_media,
                        "languages": dict(new_lang), "partitions": dict(Counter(p["split"] for p in selected))},
            "pairs": selected}



def sheet_pairs(batch_dir, source, plan_file):
    """Verify a frozen plan and every render before preferences.sheets can draw it."""
    planned = load(plan_file)
    if planned.get("format") != PLAN_FORMAT or planned.get("metadata_only"):
        raise ValueError("plan is not render-ready; metadata-only plans cannot be judged")
    if planned.get("batch") != os.path.basename(os.path.abspath(batch_dir)) or planned.get("source") != source:
        raise ValueError("plan batch or inspected format does not match")
    split_source = planned.get("split_source")
    if not split_source or not os.path.isfile(split_source):
        raise ValueError("frozen split manifest unavailable")
    with open(split_source, "rb") as f:
        if hashlib.sha256(f.read()).hexdigest() != planned.get("split_sha256"):
            raise ValueError("held-out family split changed after planning")
    source_file = os.path.join(batch_dir, "candidates.jsonl")
    with open(source_file, "rb") as f:
        if hashlib.sha256(f.read()).hexdigest() != planned.get("candidates_sha256"):
            raise ValueError("candidate metadata changed after planning")
    candidates = {(c["document"], c["candidate"]): c for c in jsonl(source_file)}
    word_ok = {}
    if source == "word":
        word_manifest = os.path.join(batch_dir, "word", "word.json")
        if not os.path.isfile(word_manifest):
            raise ValueError("Word export manifest missing")
        info = load(word_manifest)
        if not info.get("word_build") or info["word_build"] != planned.get("word_build"):
            raise ValueError("Word version changed since planning")
        word_ok = {r["file"]: r for r in info.get("files", []) if r.get("ok")}
    result = []
    seen = set()
    for row in planned["pairs"]:
        key = (row["document"], frozenset((row["a"], row["b"])))
        if key in seen or row["a"] == row["b"]:
            raise ValueError("duplicate or identical pair in plan")
        seen.add(key)
        try:
            a, b = candidates[(row["document"], row["a"])], candidates[(row["document"], row["b"])]
        except KeyError as e:
            raise ValueError(f"unknown planned candidate: {e}") from e
        if not (_media_ok(batch_dir, a, source, word_ok) and _media_ok(batch_dir, b, source, word_ok)):
            raise ValueError("unavailable or hash-mismatched PDF/DOCX/Word render")
        result.append((row["document"], a, b, row.get("reversed_repeat", False)))
    if not result:
        raise ValueError("empty sheet plan")
    return result


def audit(dataset, batches, split_path, human_audit=None, provenance=None):
    """Fail-closed PRE-training quality and isolation gate. No model is trained here."""
    from .readiness import _candidates, usable
    rows, split = jsonl(dataset), load(split_path)
    candidates, superseded = _candidates(batches)
    all_cands = list(candidates.values())
    family = _split_index(split)
    problems = []
    try:
        _verify_hash_split(all_cands, rows, split)
    except ValueError as e:
        problems.append(str(e))
    if any(r.get("reviewer_type") != "ai" for r in rows):
        problems.append("AI dataset contains non-AI rows")
    good = usable(rows, superseded)
    matching = []
    for r in good:
        match = [candidates.get((r["batch"], r["document"], r[s]["candidate"])) for s in ("a", "b")]
        if all(c and c.get("layout_facts") and c.get("document_hash") == r.get("document_hash") and
               all(c.get(k) == r[s].get(k) for k in ("pdf_sha256", "docx_sha256"))
               for c, s in zip(match, ("a", "b"))):
            matching.append(r)
    eval_docs = {d for f in split["evaluation_families"] for d in split["families"][f]}
    train = [r for r in matching if r["document"] not in eval_docs]
    test = [r for r in matching if r["document"] in eval_docs]
    def require(test_condition, message):
        if not test_condition:
            problems.append(message)
    require(len(matching) >= 200, "at least 200 verified, usable preference comparisons required")
    require(len({r["document"] for r in train}) >= 8, "need at least 8 independent training documents")
    require(len({r["document"] for r in test}) >= 3 and len(test) >= 40, "need 3 evaluation documents and 40 held-out comparisons")
    require(len(matching) == len(good), "every usable row needs both immutable candidate hashes and measured layout facts")
    require(sum(_lang(r["document"], candidates[(r["batch"], r["document"], r["a"]["candidate"])]) == "arabic" for r in matching) >= 30,
            "need at least 30 Arabic comparisons")
    require(sum(_lang(r["document"], candidates[(r["batch"], r["document"], r["a"]["candidate"])]) == "bilingual" for r in matching) >= 30,
            "need at least 30 bilingual comparisons")
    require(sum("word" in (r.get("formats_inspected") or []) for r in matching) >= 100,
            "need at least 100 comparisons reviewed on Word renders")
    reviews = jsonl(human_audit) if human_audit else []
    unique_reviews = {(r.get("batch"), r.get("comparison")): r for r in rows}
    verified_humans = [h for h in reviews if h.get("reviewer_type") == "human" and h.get("reviewer") and
                       h.get("review_date") and h.get("visual_evidence") and h.get("preferred") in ("A", "B", "tie", "abstain")
                       and (h.get("batch"), h.get("comparison")) in unique_reviews
                       and h.get("document_hash") == unique_reviews[(h["batch"], h["comparison"])].get("document_hash")]
    require(len({(h["batch"], h["comparison"]) for h in verified_humans}) >= 20,
            "need 20 independent, traceable human audit decisions (kept outside AI labels)")
    sources = load(provenance) if provenance and os.path.isfile(provenance) else {}
    manifest = sources.get("documents", [])
    by_hash = {m.get("document_hash"): m for m in manifest}
    missing_origins = [r["document_hash"] for r in matching if r["document_hash"] not in by_hash]
    require(bool(manifest) and not missing_origins, "source provenance manifest incomplete: author and asset pools are required")
    authors = {m.get("author_group") for m in manifest if m.get("author_group")}
    assets = {m.get("asset_pool") for m in manifest if m.get("asset_pool")}
    require(len(authors) >= 3 and len(assets) >= 3, "need at least 3 independent author groups and asset pools")
    if manifest:
        crossings = []
        for field in ("author_group", "asset_pool"):
            fit_ids = {by_hash[r["document_hash"]].get(field) for r in train if r["document_hash"] in by_hash}
            test_ids = {by_hash[r["document_hash"]].get(field) for r in test if r["document_hash"] in by_hash}
            crossings += [(field, x) for x in fit_ids & test_ids if x]
        require(not crossings, f"provenance leakage across split: {crossings[:6]}")
    return {"ready": not problems, "usable": len(matching), "held_out": len(test),
            "human_audit": len({(h["batch"], h["comparison"]) for h in verified_humans}),
            "issues": problems, "note": "Quality readiness only. No model was trained; AI and human labels remain separate."}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="action", required=True)
    b = sub.add_parser("bridge", help="M7.7 page graph to objective reference profiles")
    b.add_argument("--graphs", required=True)
    b.add_argument("--coverage")
    b.add_argument("--out", required=True)
    p = sub.add_parser("plan", help="balanced new M7.10 blind pairs, without judgments")
    p.add_argument("--batch", required=True)
    p.add_argument("--dataset", required=True)
    p.add_argument("--split", required=True)
    p.add_argument("--source", choices=("pdf", "word"), default="word")
    p.add_argument("--count", type=int, default=24)
    p.add_argument("--max-per-doc", type=int, default=3)
    p.add_argument("--reference-features")
    p.add_argument("--metadata-only", action="store_true")
    p.add_argument("--out", required=True)
    q = sub.add_parser("audit", help="fail-closed quality gate; does not train")
    q.add_argument("--dataset", required=True)
    q.add_argument("--batches", required=True)
    q.add_argument("--split", required=True)
    q.add_argument("--human-audit")
    q.add_argument("--provenance")
    args = ap.parse_args(argv)
    if args.action == "bridge":
        r = bridge(load(args.graphs), load(args.coverage) if args.coverage else None)
        write_json(args.out, r)
        print(json.dumps({"profiles": len(r["documents"]), "pages": r["reference_pages"], "out": args.out}))
    elif args.action == "plan":
        r = plan(args.batch, args.dataset, args.split, args.source, args.count, max_per_doc=args.max_per_doc,
                 require_media=not args.metadata_only, reference_features=args.reference_features)
        write_json(args.out, r)
        print(json.dumps({"out": args.out, **r["summary"], "metadata_only": r["metadata_only"]}))
    else:
        r = audit(args.dataset, args.batches, args.split, args.human_audit, args.provenance)
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0 if r["ready"] else 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
