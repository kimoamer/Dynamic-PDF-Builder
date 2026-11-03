"""
Optional learned ranker for *already valid* layout candidates (LightGBM, CPU).

* Never decides validity: hard constraints are enforced before ranking.
* Optional dependency (``pip install "dynamic-pdf-builder[ranker]"``); when
  LightGBM or the model file is missing, composition stays fully deterministic.
* Loads only LightGBM's plain-text model format — never pickle/joblib — and
  validates its header and feature list before use.
* No model ships with the library: train one from real human preferences with
  ``scripts/collect_preferences.py`` and ``scripts/train_ranker.py``.
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional, Sequence

FEATURES = ["utilization", "balance", "efficiency", "readability", "typography", "placement",
            "tables", "wasted", "pages", "cpl"]
MAX_MODEL_BYTES = 2 * 1024 * 1024


def feature_vector(metrics: Dict[str, float]) -> List[float]:
    return [float(metrics.get(k, 0.0)) for k in FEATURES]


def pair_features(a: Dict[str, float], b: Dict[str, float]) -> List[float]:
    """Pairwise representation used for training and inference (a − b)."""
    return [x - y for x, y in zip(feature_vector(a), feature_vector(b))]


class RankerUnavailable(Exception):
    pass


class PreferenceRanker:
    """Scores candidates by summed pairwise preference against the others."""

    def __init__(self, booster):
        self._booster = booster

    @classmethod
    def load(cls, path: str) -> "PreferenceRanker":
        try:
            import lightgbm  # optional
        except ImportError as e:
            raise RankerUnavailable("lightgbm is not installed") from e
        if not os.path.isfile(path):
            raise RankerUnavailable(f"model file not found: {path}")
        if os.path.getsize(path) > MAX_MODEL_BYTES:
            raise RankerUnavailable("model file exceeds 2 MB; refusing to load")
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        if not text.startswith("tree\n") or "version=" not in text[:200]:
            raise RankerUnavailable("not a LightGBM text model (only the text format is accepted)")
        names = next((ln.split("=", 1)[1].split() for ln in text.splitlines()
                      if ln.startswith("feature_names=")), [])
        expected = [f"d_{k}" for k in FEATURES]
        if names and names != expected:
            raise RankerUnavailable(f"model features {names} do not match {expected}")
        return cls(lightgbm.Booster(model_str=text))

    def rank(self, candidates: Sequence[Dict[str, float]]) -> List[float]:
        """One score per candidate = mean predicted P(candidate preferred over other)."""
        n = len(candidates)
        if n < 2:
            return [0.0] * n
        rows, owners = [], []
        for i in range(n):
            for j in range(n):
                if i != j:
                    rows.append(pair_features(candidates[i], candidates[j]))
                    owners.append(i)
        preds = self._booster.predict(rows)
        scores = [0.0] * n
        for o, p in zip(owners, preds):
            scores[o] += float(p) / (n - 1)
        return scores


def load_optional(path: Optional[str]) -> Optional[PreferenceRanker]:
    if not path:
        return None
    try:
        return PreferenceRanker.load(path)
    except RankerUnavailable:
        return None
