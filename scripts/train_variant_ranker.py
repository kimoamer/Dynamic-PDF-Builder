"""
Train the optional ranker of design variants from AI preference comparisons.

    python scripts/train_variant_ranker.py --dataset D --batches DIR --split S --out M.json
    python scripts/train_variant_ranker.py --kind weights ... --out W.json

``--kind weights`` fits calibrated, monotone weights over measured facts
(``dynamic_pdf.intelligence.variant_weights``) and needs no LightGBM; ``lightgbm`` is
the optional booster. Both read the same facts (``variant_ranker.from_candidate``), pass the
same preflight audit and the same gate, and are written as one JSON file: the training record
with the model inside. LightGBM is needed to train the booster, never to use it: its trees
are stored in the record and walked in plain Python.

This is AI preference distillation, not human-supervised training. Ties, abstentions,
low-confidence answers and pairs that flipped when reversed are left out. Documents are
split by ``training/document-split.json``; the split names reference families, and no
family crosses from training to evaluation. The evaluation documents never train.

The booster is held to the known direction of a fact (``variant_weights.MONOTONE``), and its
number of trees and the confidence it needs before it overrules the fixed selector are chosen
on training documents only, by leaving whole families out in turn.

A model is written with its record whatever the result, and ``gate.passed`` says whether
it may be loaded. Finishing training is not a reason to deploy. The gate asks for more than a
better average: the gain must hold when the evaluation documents are resampled, and where the
model would overrule the fixed selector on an evaluation document, the judges must have
preferred its choice more often than the fixed one.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from dynamic_pdf.intelligence.objective import design_score  # noqa: E402
from dynamic_pdf.intelligence.variant_ranker import (CONTEXT, FEATURES, MODEL_FORMAT, OVERRIDE, VariantRanker,  # noqa: E402
                                                    choose, context_vector, from_candidate, model_digest, pair_features)
from dynamic_pdf.intelligence.variant_weights import MONOTONE  # noqa: E402

GATE = {"min_pairs": 200, "min_training_documents": 8, "min_evaluation_documents": 10, "min_evaluation_pairs": 150,
        "min_gain": 0.03, "min_agreement": 0.6, "bootstrap_draws": 2000, "bootstrap_quantile": 0.05,
        "override_precision": 0.7, "override_win_rate": 0.6, "slice_pairs": 10, "slice_tolerance": 0.1}
ROUNDS = (10, 20, 40, 80)
THRESHOLDS = (0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9)


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
    seen, once = {}, set()
    for r in rows:
        seen.setdefault(pair(r), set()).add(won(r))
    out = []
    for r in rows:                                  # judges who agree on a comparison count it once
        if r["preferred"] in ("A", "B") and r["confidence"] != "low" and len(seen[pair(r)]) == 1 \
                and not r["reversed_repeat"] and (r["batch"], r["comparison"]) not in once:
            once.add((r["batch"], r["comparison"]))
            out.append(r)
    return out


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
    """(document, preferred design, other design) for each comparison, and the same as training rows."""
    picks = []
    for r in rows:
        a, b = cands[(r["batch"], r["document"], r["a"]["candidate"])], cands[(r["batch"], r["document"], r["b"]["candidate"])]
        picks.append((r["document"], a, b) if r["preferred"] == "A" else (r["document"], b, a))
    X, y, docs = matrix(picks)
    return X, y, docs, picks


def matrix(picks):
    X, y, docs = [], [], []
    for doc, win, lose in picks:
        w, lo, ctx = from_candidate(win), from_candidate(lose), context_vector(win.get("context"))
        X += [pair_features(w, lo) + ctx, pair_features(lo, w) + ctx]
        y += [1, 0]
        docs += [doc] * 2
    return X, y, docs


def deterministic_agreement(picks):
    """How often the shipped selector's ordering (the objective's design score) matches the comparison."""
    def score(c):
        return design_score(c["features"]["fit"], c["features"]["index"])
    hits = sum(score(w) > score(lo) for _, w, lo in picks)
    return hits / len(picks) if picks else None


def train(X, y, params=None, rounds=80):
    import lightgbm as lgb
    import numpy as np
    data = lgb.Dataset(np.array(X, dtype=float), label=np.array(y), free_raw_data=False,
                       feature_name=[f"d_{k}" for k in FEATURES] + [f"c_{k}" for k in CONTEXT])
    p = {"objective": "binary", "num_leaves": 7, "learning_rate": 0.08, "min_data_in_leaf": 20, "lambda_l2": 1.0,
         "feature_fraction": 0.8, "verbosity": -1, "num_threads": 1, "deterministic": True, "force_col_wise": True, "seed": 79,
         # a fact whose direction is known may only move the preference that way; the context is free
         "monotone_constraints": [MONOTONE.get(k, 0) for k in FEATURES] + [0] * len(CONTEXT)}
    p.update(params or {})
    return lgb.train(p, data, num_boost_round=rounds)


def to_trees(booster) -> list:
    """LightGBM's trees in the form the package walks: ``[feature, threshold, at or below, above]``, a leaf its value."""
    def node(n):
        if "leaf_value" in n:
            return float(n["leaf_value"])
        if n.get("decision_type") != "<=":
            raise SystemExit("only numerical splits can be exported")
        return [int(n["split_feature"]), float(n["threshold"]), node(n["left_child"]), node(n["right_child"])]
    return [node(t["tree_structure"]) for t in booster.dump_model()["tree_info"]]


def win_probabilities(ranker, picks):
    """The model's chance for the preferred design of each comparison, as it will be used."""
    return [ranker.prob(from_candidate(w), from_candidate(lo), w.get("context")) for _, w, lo in picks]


def learned_agreement(ranker, picks):
    return sum(p > 0.5 for p in win_probabilities(ranker, picks)) / len(picks) if picks else None


def calibration(probs):
    if not probs:
        return {"agreement": None, "brier": None, "log_loss": None}
    return {"agreement": sum(p > 0.5 for p in probs) / len(probs), "brier": round(sum((1 - p) ** 2 for p in probs) / len(probs), 4),
            "log_loss": round(-sum(math.log(max(p, 1e-12)) for p in probs) / len(probs), 4)}


def cross_validate(make, picks, family, folds=4):
    """Out-of-fold chances: each family's comparisons are predicted by a model that never saw the
    family. Empty when the training documents are one family."""
    names = sorted({family.get(d, d) for d, *_ in picks})
    if len(names) < 2:
        return []
    out = [None] * len(picks)
    for k in range(min(folds, len(names))):
        held = {f for i, f in enumerate(names) if i % folds == k}
        ranker = make([p for p in picks if family.get(p[0], p[0]) not in held])
        for i, p in enumerate(picks):
            if family.get(p[0], p[0]) in held:
                out[i] = win_probabilities(ranker, [p])[0]
    return out


def override_threshold(probs):
    """The lowest confidence at which the out-of-fold preferences were right often enough to
    overrule the fixed selector; with none, a threshold the model will rarely reach."""
    for t in THRESHOLDS:
        sure = [p for p in probs if max(p, 1 - p) >= t]
        if len(sure) >= 20 and sum(p > 0.5 for p in sure) / len(sure) >= GATE["override_precision"]:
            return t, {"asserted": len(sure), "precision": round(sum(p > 0.5 for p in sure) / len(sure), 4)}
    return 0.95, {"asserted": 0, "precision": None}


def resampled_gain(learned, fixed, docs, draws, quantile, seed=79):
    """The gain in agreement that holds when the evaluation documents are drawn again with
    replacement: its low quantile. ``learned`` and ``fixed`` say per comparison who was right."""
    by = {}
    for hit, base, doc in zip(learned, fixed, docs):
        by.setdefault(doc, []).append(hit - base)
    names, rng, gains = sorted(by), random.Random(seed), []
    if not names:
        return None
    for _ in range(draws):
        drawn = [x for d in rng.choices(names, k=len(names)) for x in by[d]]
        gains.append(sum(drawn) / len(drawn))
    return round(sorted(gains)[int(quantile * (draws - 1))], 4)


def language(candidate) -> str:
    c = candidate.get("context") or {}
    return "bilingual" if c.get("bilingual") else "arabic" if c.get("arabic") else "english"


def slices(probs, picks):
    """Agreement of both selectors by the document's language."""
    out = {}
    for p, (_, w, lo) in zip(probs, picks):
        s = out.setdefault(language(w), {"comparisons": 0, "learned": 0, "deterministic": 0})
        s["comparisons"] += 1
        s["learned"] += p > 0.5
        s["deterministic"] += design_score(w["features"]["fit"], w["features"]["index"]) > design_score(lo["features"]["fit"], lo["features"]["index"])
    return {k: {"comparisons": v["comparisons"], "learned": round(v["learned"] / v["comparisons"], 4),
                "deterministic": round(v["deterministic"] / v["comparisons"], 4)} for k, v in sorted(out.items())}


def overrides(ranker, rows, cands):
    """What the model would do on each evaluation document, and what the judges said of the
    designs it would swap: right when they preferred its choice to the fixed one."""
    judged = {}
    for r in rows:
        win = r["a"]["candidate"] if r["preferred"] == "A" else r["b"]["candidate"]
        judged[(r["batch"], r["document"], frozenset((r["a"]["candidate"], r["b"]["candidate"])))] = win
    out = {"documents": 0, "overrode": 0, "right": 0, "wrong": 0, "unjudged": 0, "abstained": 0}
    for batch, doc in sorted({(r["batch"], r["document"]) for r in rows}):
        pool = [c for (b, d, _), c in cands.items() if (b, d) == (batch, doc)]
        fixed = next((c for c in pool if c.get("deterministic_pick")), None)
        if fixed is None or len(pool) < 2:
            continue
        out["documents"] += 1
        pick, note = choose(pool, fixed, "trained.json", lambda _: ranker, context=fixed.get("context"),
                            features=from_candidate, name=lambda c: c["candidate"])
        out["abstained"] += bool(note.get("abstained"))
        if pick is not fixed:
            won = judged.get((batch, doc, frozenset((pick["candidate"], fixed["candidate"]))))
            out["overrode"] += 1
            out["right" if won == pick["candidate"] else "wrong" if won == fixed["candidate"] else "unjudged"] += 1
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--batches", required=True)
    ap.add_argument("--split", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--kind", choices=("lightgbm", "weights"), default="lightgbm")
    ap.add_argument("--min-pairs", type=int, default=GATE["min_pairs"])
    ap.add_argument("--synthetic-fixture", action="store_true", help="tests only: marks the record, and the gate never passes")
    ap.add_argument("--human-audit", help="separate traceable human quality review JSONL; never treated as AI labels")
    ap.add_argument("--provenance", help="local document author/asset provenance JSON; required by preflight gate")
    ap.add_argument("--delegated-audit", help="owner's waiver: blind audit decisions an AI reviewer gave at the owner's "
                                              "request, in place of the human ones; named in the record")
    ap.add_argument("--pdf-only", action="store_true", help="owner's waiver: no Word-verified comparisons; named in the record")
    a = ap.parse_args(argv)
    if not a.out.lower().endswith(".json"):
        sys.exit("a model is one JSON file: give --out a .json path")
    # Fail before importing LightGBM, creating datasets or touching a model output.
    # This gate complements (rather than replaces) the post-training evaluation gate.
    from tools.design_learning.reference_sampling import audit
    preflight = audit(a.dataset, a.batches, a.split, a.human_audit, a.provenance, delegated_audit=a.delegated_audit,
                      pdf_only=a.pdf_only)
    if not preflight["ready"]:
        sys.exit("M7.7/M7.10 data-quality preflight blocked training: " + "; ".join(preflight["issues"]))
    if a.kind == "lightgbm":
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
    family = {d: f for f, ds in split["families"].items() for d in ds}
    fit = [r for r in kept if r["document"] not in held]
    test = [r for r in kept if r["document"] in held]
    _, _, _, train_picks = examples(fit, cands)
    _, _, _, test_picks = examples(test, cands)
    if not train_picks:
        sys.exit("no comparisons outside the evaluation documents")
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    extra, chosen = {}, {}
    if a.kind == "weights":
        from dynamic_pdf.intelligence import variant_weights as W
        extra = {"format": W.FORMAT}

        def make(picks):
            model = W.fit([(from_candidate(w), from_candidate(lo)) for _, w, lo in picks])
            return W.WeightsRanker({"model": model, "model_sha256": model_digest(model)})
    else:
        def make(picks, rounds=80):
            model = {"trees": to_trees(train(*matrix(picks)[:2], rounds=rounds))}
            return VariantRanker({"model": model, "model_sha256": model_digest(model)})
        tried = {r: calibration(cross_validate(lambda ps, r=r: make(ps, r), train_picks, family))["log_loss"] for r in ROUNDS}
        if None not in tried.values():           # the number of trees that predicts left-out families best
            chosen = {"rounds": min(tried, key=lambda r: (tried[r], r)), "cv_log_loss_by_rounds": tried}
            make = lambda picks, make=make, r=chosen["rounds"]: make(picks, r)  # noqa: E731
    out_of_fold = cross_validate(make, train_picks, family)
    threshold, sure = override_threshold(out_of_fold) if out_of_fold else (OVERRIDE, None)
    ranker = make(train_picks)
    model, digest = ranker.model if a.kind == "weights" else {"trees": ranker.trees}, ranker.digest
    ranker.record = {"model": model, "model_sha256": digest, "override_threshold": threshold, "labels": "ai_preference_distillation"}
    probs = win_probabilities(ranker, test_picks)
    held_out = calibration(probs)
    learned = held_out["agreement"]
    fixed = deterministic_agreement(test_picks)

    def score(c):
        return design_score(c["features"]["fit"], c["features"]["index"])
    low = resampled_gain([p > 0.5 for p in probs], [score(w) > score(lo) for _, w, lo in test_picks],
                         [d for d, *_ in test_picks], GATE["bootstrap_draws"], GATE["bootstrap_quantile"])
    swapped = overrides(ranker, test, cands)
    judged = swapped["right"] + swapped["wrong"]
    by_language = slices(probs, test_picks)
    train_docs, test_docs = {d for d, *_ in train_picks}, {d for d, *_ in test_picks}
    checks = {"enough_pairs": len(kept) >= GATE["min_pairs"], "enough_training_documents": len(train_docs) >= GATE["min_training_documents"],
              "enough_evaluation_documents": len(test_docs) >= GATE["min_evaluation_documents"],
              "enough_evaluation_pairs": len(test) >= GATE["min_evaluation_pairs"],
              "no_leakage": not (train_docs & test_docs),
              "better_than_deterministic": learned is not None and fixed is not None and learned >= fixed + GATE["min_gain"],
              "agreement_floor": learned is not None and learned >= GATE["min_agreement"],
              "gain_holds_when_resampled": low is not None and low > 0,
              "overrides_help": judged > 0 and swapped["right"] / judged >= GATE["override_win_rate"],
              "no_language_worse": all(v["learned"] >= v["deterministic"] - GATE["slice_tolerance"]
                                       for v in by_language.values() if v["comparisons"] >= GATE["slice_pairs"]),
              "not_a_fixture": not a.synthetic_fixture}
    record = {"format": MODEL_FORMAT, "labels": "ai_preference_distillation", "human_labels": 0, "features": FEATURES,
              "context": CONTEXT, "override_threshold": threshold, "model": model, "model_sha256": digest,
              "comparisons": {"total": len(rows), "usable": len(kept), "training": len(fit), "evaluation": len(test)},
              "documents": {"training": sorted(train_docs), "evaluation": sorted(test_docs)},
              "agreement": {"learned": learned, "deterministic": fixed, "gain_low": low, "by_language": by_language},
              "overrides": swapped,
              "calibration": {"held_out_brier": held_out["brier"], "held_out_log_loss": held_out["log_loss"],
                              "cross_validated": calibration(out_of_fold), "override_threshold_from": sure, **chosen},
              "preflight": {"waivers": preflight.get("waivers", []), "delegated_audit": preflight.get("delegated_audit", 0),
                            "human_audit": preflight.get("human_audit", 0)},
              "synthetic_fixture": a.synthetic_fixture,
              "gate": {"rules": GATE, "checks": checks, "passed": all(checks.values())},
              "note": "A pass allows the model to be loaded when a caller asks for it. It is never activated by itself.", **extra}
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(record, f, ensure_ascii=False, indent=1)
    print(json.dumps({"agreement": record["agreement"], "overrides": swapped, "threshold": threshold,
                      "gate": record["gate"]["passed"], "checks": checks}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
