"""
Train the optional LightGBM preference ranker from *human-labelled* pairs.

    python scripts/train_ranker.py pairs.csv model.txt [--min-pairs 40] [--folds 5]

Only rows with ``preferred`` ∈ {left, right} are used (``equal`` and empty rows
are skipped). Refuses to train with fewer than ``--min-pairs`` labelled pairs,
reports k-fold cross-validated pairwise accuracy (grouped by document so a
document never appears in both train and test), and saves LightGBM's
plain-text model format (no pickle).
"""
import csv
import json
import sys


def main():
    try:
        import lightgbm as lgb
        import numpy as np
    except ImportError:
        sys.exit('lightgbm is required: pip install "dynamic-pdf-builder[ranker]"')
    sys.path.insert(0, ".")
    from dynamic_pdf.intelligence.ranker import FEATURES, pair_features
    src, dst = sys.argv[1], sys.argv[2]
    min_pairs = int(sys.argv[sys.argv.index("--min-pairs") + 1]) if "--min-pairs" in sys.argv else 40
    folds = int(sys.argv[sys.argv.index("--folds") + 1]) if "--folds" in sys.argv else 5
    X, y, groups = [], [], []
    with open(src, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            pref = (row.get("preferred") or "").strip().lower()
            if pref not in ("left", "right"):
                continue
            a, b = json.loads(row["left_metrics"]), json.loads(row["right_metrics"])
            # symmetric augmentation: (a−b → 1) and (b−a → 0) when left preferred
            win, lose = (a, b) if pref == "left" else (b, a)
            X += [pair_features(win, lose), pair_features(lose, win)]
            y += [1, 0]
            groups += [row["document"]] * 2
    n_pairs = len(y) // 2
    if n_pairs < min_pairs:
        sys.exit(f"only {n_pairs} labelled pairs (need ≥ {min_pairs}); label more pairs first")
    X, y = np.array(X), np.array(y)
    docs = sorted(set(groups))
    accs = []
    for k in range(min(folds, len(docs))):
        test_docs = set(docs[k::folds])
        te = np.array([g in test_docs for g in groups])
        if te.all() or not te.any():
            continue
        m = lgb.LGBMClassifier(n_estimators=60, num_leaves=7, min_child_samples=4, learning_rate=0.1,
                               verbose=-1, random_state=0)
        m.fit(X[~te], y[~te], feature_name=[f"d_{f}" for f in FEATURES])
        accs.append(float((m.predict(X[te]) == y[te]).mean()))
    model = lgb.LGBMClassifier(n_estimators=60, num_leaves=7, min_child_samples=4, learning_rate=0.1,
                               verbose=-1, random_state=0)
    model.fit(X, y, feature_name=[f"d_{f}" for f in FEATURES])
    model.booster_.save_model(dst)          # plain-text format
    acc = f"{sum(accs) / len(accs):.3f} over {len(accs)} document-grouped folds" if accs else "n/a"
    print(f"trained on {n_pairs} labelled pairs from {len(docs)} documents; CV pairwise accuracy: {acc}")
    print(f"model written to {dst}")


if __name__ == "__main__":
    main()
