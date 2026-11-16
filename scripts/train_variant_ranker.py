"""
Train the optional ranker of design variants from AI preference comparisons.

    python scripts/train_variant_ranker.py --dataset D --batches DIR --split S --out M.txt

This is AI preference distillation, not human-supervised training. Ties, abstentions,
low-confidence answers and pairs that flipped when reversed are left out. Documents are
split by ``training/document-split.json``; the split names reference families, and no
family crosses from training to evaluation. The evaluation documents never train.

A model is written with its record whatever the result, and ``gate.passed`` says whether
it may be loaded. Finishing training is not a reason to deploy.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from dynamic_pdf.intelligence.objective import design_score  # noqa: E402
from dynamic_pdf.intelligence.variant_ranker import FEATURES, MODEL_FORMAT, pair_features  # noqa: E402

GATE = {"min_pairs": 200, "min_training_documents": 8, "min_evaluation_documents": 3, "min_gain": 0.03, "min_agreement": 0.6}


def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


def usable(rows):
    """Clear AI answers only, without pairs that contradicted themselves."""
    def pair(r):
        return r["batch"], r["document"], frozenset((r["a"]["candidate"], r["b"]["candidate"]))    # batches render different code

    def won(r):
        return r["a"]["candidate"] if r["preferred"] == "A" else r["b"]["candidate"] if r["preferred"] == "B" else None

    for r in rows:
        if r.get("reviewer_type") != "ai":
            raise SystemExit("this trainer takes AI comparisons only; human labels stay in their own dataset")
    seen = {}
    for r in rows:
        seen.setdefault(pair(r), set()).add(won(r))
    return [r for r in rows if r["preferred"] in ("A", "B") and r["confidence"] != "low" and len(seen[pair(r)]) == 1
            and not r["reversed_repeat"]]


def load_candidates(batches):
    out = {}
    for name in sorted(os.listdir(batches)):
        path = os.path.join(batches, name, "candidates.jsonl")
        if os.path.exists(path):
            for c in read_jsonl(path):
                out[(name, c["document"], c["candidate"])] = c
        path = os.path.join(batches, name, "superseded.json")       # designs later found defective stay on record, unused
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                for s in json.load(f)["candidates"]:
                    out.pop((name, s["document"], s["candidate"]), None)
    return out


def examples(rows, cands):
    X, y, docs, picks = [], [], [], []
    for r in rows:
        a, b = cands[(r["batch"], r["document"], r["a"]["candidate"])], cands[(r["batch"], r["document"], r["b"]["candidate"])]
        win, lose = (a, b) if r["preferred"] == "A" else (b, a)
        X += [pair_features(win["features"], lose["features"]), pair_features(lose["features"], win["features"])]
        y += [1, 0]
        docs += [r["document"]] * 2
        picks.append((r["document"], win, lose))
    return X, y, docs, picks


def deterministic_agreement(picks):
    """How often the shipped selector's ordering (the objective's design score) matches the comparison."""
    def score(c):
        return design_score(c["features"]["fit"], c["features"]["index"])
    hits = sum(score(w) > score(lo) for _, w, lo in picks)
    return hits / len(picks) if picks else None


def train(X, y, params=None):
    import lightgbm as lgb
    import numpy as np
    data = lgb.Dataset(np.array(X, dtype=float), label=np.array(y),  feature_name=[f"d_{k}" for k in FEATURES], free_raw_data=False)
    p = {"objective": "binary", "num_leaves": 7, "learning_rate": 0.08, "min_data_in_leaf": 6, "verbosity": -1,
         "num_threads": 1, "deterministic": True, "force_col_wise": True, "seed": 79}
    p.update(params or {})
    return lgb.train(p, data, num_boost_round=80)


def learned_agreement(model, picks):
    if not picks:
        return None
    import numpy as np
    rows = np.array([pair_features(w["features"], lo["features"]) for _, w, lo in picks], dtype=float)
    swapped = np.array([pair_features(lo["features"], w["features"]) for _, w, lo in picks], dtype=float)
    p, q = model.predict(rows), model.predict(swapped)
    return float(sum(a > b for a, b in zip(p, q)) / len(picks))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--batches", required=True)
    ap.add_argument("--split", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--min-pairs", type=int, default=GATE["min_pairs"])
    ap.add_argument("--synthetic-fixture", action="store_true", help="tests only: marks the record, and the gate never passes")
    ap.add_argument("--human-audit", help="separate traceable human quality review JSONL; never treated as AI labels")
    ap.add_argument("--provenance", help="local document author/asset provenance JSON; required by preflight gate")
    a = ap.parse_args(argv)
    # Fail before importing LightGBM, creating datasets or touching a model output.
    # This gate complements (rather than replaces) the post-training evaluation gate.
    from tools.design_learning.reference_sampling import audit
    preflight = audit(a.dataset, a.batches, a.split, a.human_audit, a.provenance)
    if not preflight["ready"]:
        sys.exit("M7.7/M7.10 data-quality preflight blocked training: " + "; ".join(preflight["issues"]))
    try:
        import lightgbm  # noqa: F401
    except ImportError:
        sys.exit('lightgbm is required: pip install "dynamic-pdf-builder[ranker]"')
    rows = read_jsonl(a.dataset)
    cands = load_candidates(a.batches)
    kept = [r for r in usable(rows) if all((r["batch"], r["document"], r[s]["candidate"]) in cands for s in "ab")]
    if len(kept) < a.min_pairs:
        sys.exit(f"only {len(kept)} usable comparisons of {len(rows)} (need {a.min_pairs}); nothing was trained")
    with open(a.split, encoding="utf-8") as f:
        split = json.load(f)
    held = {d for f, ds in split["families"].items() if f in split["evaluation_families"] for d in ds}
    fit = [r for r in kept if r["document"] not in held]
    test = [r for r in kept if r["document"] in held]
    X, y, _, train_picks = examples(fit, cands)
    _, _, _, test_picks = examples(test, cands)
    if not X:
        sys.exit("no comparisons outside the evaluation documents")
    model = train(X, y)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    model.save_model(a.out)
    with open(a.out, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    learned, fixed = learned_agreement(model, test_picks), deterministic_agreement(test_picks)
    train_docs, test_docs = {d for d, *_ in train_picks}, {d for d, *_ in test_picks}
    checks = {"enough_pairs": len(kept) >= GATE["min_pairs"], "enough_training_documents": len(train_docs) >= GATE["min_training_documents"],
              "enough_evaluation_documents": len(test_docs) >= GATE["min_evaluation_documents"],
              "no_leakage": not (train_docs & test_docs),
              "better_than_deterministic": learned is not None and fixed is not None and learned >= fixed + GATE["min_gain"],
              "agreement_floor": learned is not None and learned >= GATE["min_agreement"], "not_a_fixture": not a.synthetic_fixture}
    record = {"format": MODEL_FORMAT, "labels": "ai_preference_distillation", "human_labels": 0, "features": FEATURES, "model_sha256": digest,
              "comparisons": {"total": len(rows), "usable": len(kept), "training": len(fit), "evaluation": len(test)},
              "documents": {"training": sorted(train_docs), "evaluation": sorted(test_docs)},
              "agreement": {"learned": learned, "deterministic": fixed}, "synthetic_fixture": a.synthetic_fixture,
              "gate": {"rules": GATE, "checks": checks, "passed": all(checks.values())},
              "note": "A pass allows the model to be loaded when a caller names it. It is never activated by itself."}
    with open(os.path.splitext(a.out)[0] + ".json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(record, f, ensure_ascii=False, indent=1)
    print(json.dumps({"agreement": record["agreement"], "gate": record["gate"]["passed"], "checks": checks}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
