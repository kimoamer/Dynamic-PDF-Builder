"""
Calibrated, monotone weights over measured facts: the model to beat before any LightGBM.

A pairwise logistic model (Bradley-Terry): the chance that design a is preferred to design b
is ``sigmoid(w . (x_a - x_b) / scale)``, so a score difference reads as a win probability.
Weights whose direction is known are held to it (``MONOTONE``): more fit never counts against
a design, more sparse pages never for it. It replaces ``fit * 6 + index`` only when a caller
names a model whose training record passed the same gate as the LightGBM ranker.

The features are measurements, never description strings. ``measured`` and
``from_candidate`` are the only two places that read them.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from typing import Dict, List, Sequence, Tuple

FORMAT = "dynamic-pdf-builder/variant-weights"
FEATURES = ["fit", "index", "pages", "page_growth", "sparse_share", "alike_share", "page_variety", "type_contrast",
            "image_share", "last_page_ink"]
MONOTONE = {"fit": 1, "index": 1, "page_growth": -1, "sparse_share": -1, "alike_share": -1, "page_variety": 1,
            "last_page_ink": 1}                     # +1 never hurts, -1 never helps; absent means free
MAX_BYTES = 64 * 1024
HEURISTICS = ("sparse_share", "alike_share", "page_variety", "type_contrast", "image_share", "last_page_ink")


def measured(v) -> Dict[str, float]:
    """A finished design's measured facts.
    shortcut: reads the variant report's page heuristics; switch to PageFacts when M9 lands."""
    r = v.report
    estimated = v.plan.brief.estimated_pages if getattr(v, "plan", None) else 0
    out = {"fit": float(r.fit), "index": float(r.index), "pages": float(r.pages),
           "page_growth": r.pages / estimated if estimated else 1.0}
    out.update({k: float((r.heuristics or {}).get(k, 0.0)) for k in HEURISTICS})
    return out


def from_candidate(c: dict) -> Dict[str, float]:
    """The same facts from a row of a batch's candidates.jsonl.
    shortcut: reads the recorded ``features``; switch to the recorded PageFacts when M9 lands."""
    f = c.get("features") or {}
    return {k: float(f.get(k, 0.0)) for k in FEATURES}


def _vec(f: Dict[str, float]) -> List[float]:
    return [float(f.get(k, 0.0)) for k in FEATURES]


def _sigmoid(z: float) -> float:
    return 1 / (1 + math.exp(-z)) if z >= 0 else math.exp(z) / (1 + math.exp(z))


def fit(pairs: Sequence[Tuple[dict, dict]], *, l2: float = 0.05, steps: int = 3000, rate: float = 0.2) -> dict:
    """Weights from (preferred, other) pairs of facts, by projected gradient descent. Deterministic."""
    import numpy as np
    d = np.array([[a - b for a, b in zip(_vec(w), _vec(lo))] for w, lo in pairs], dtype=float)
    if not len(d):
        raise ValueError("no pairs to fit")
    scale = d.std(axis=0)
    scale[scale < 1e-6] = 1.0                       # a fact that never differs carries no signal
    x = d / scale
    w = np.zeros(len(FEATURES))
    sign = np.array([MONOTONE.get(k, 0) for k in FEATURES])
    for _ in range(steps):
        z = x @ w
        grad = -(x * (1 / (1 + np.exp(z)))[:, None]).mean(axis=0) + l2 * w
        w -= rate * grad
        w = np.where(sign > 0, np.maximum(w, 0), np.where(sign < 0, np.minimum(w, 0), w))
    return {"features": FEATURES, "monotone": MONOTONE, "weights": [round(float(v), 6) for v in w],
            "scale": [round(float(v), 6) for v in scale], "l2": l2}


def score(model: dict, facts: Dict[str, float]) -> float:
    return sum(w * x / s for w, x, s in zip(model["weights"], _vec(facts), model["scale"]))


def evaluate(model: dict, pairs: Sequence[Tuple[dict, dict]]) -> dict:
    """Held-out agreement, and how well the win probabilities are calibrated (Brier, log loss)."""
    if not pairs:
        return {"agreement": None, "brier": None, "log_loss": None}
    p = [_sigmoid(score(model, w) - score(model, lo)) for w, lo in pairs]
    return {"agreement": sum(x > 0.5 for x in p) / len(p), "brier": round(sum((1 - x) ** 2 for x in p) / len(p), 4),
            "log_loss": round(-sum(math.log(max(x, 1e-12)) for x in p) / len(p), 4)}


def digest(model: dict) -> str:
    return hashlib.sha256(json.dumps({k: model[k] for k in ("features", "monotone", "weights", "scale")},
                                     sort_keys=True).encode("utf-8")).hexdigest()


class WeightsRanker:
    features = staticmethod(measured)

    def __init__(self, record: dict):
        self.record, self.model, self.digest = record, record["model"], record["model_sha256"]

    @classmethod
    def load(cls, path: str) -> "WeightsRanker":
        from .variant_ranker import RankerRefused
        if not os.path.isfile(path):
            raise RankerRefused(f"model file not found: {path}")
        if os.path.getsize(path) > MAX_BYTES:
            raise RankerRefused("weights file exceeds 64 KB")
        with open(path, encoding="utf-8") as f:
            record = json.load(f)
        if record.get("format") != FORMAT:
            raise RankerRefused("the training record has another format")
        model = record.get("model") or {}
        if model.get("features") != FEATURES or len(model.get("weights", [])) != len(FEATURES) \
                or len(model.get("scale", [])) != len(FEATURES):
            raise RankerRefused("the model was trained on other features")
        if model.get("monotone") != MONOTONE or any(MONOTONE.get(k, 0) * w < 0 for k, w in zip(FEATURES, model["weights"])):
            raise RankerRefused("the weights break their monotone constraints")
        if record.get("model_sha256") != digest(model):
            raise RankerRefused("the model does not match its training record")
        if not (record.get("gate") or {}).get("passed"):
            raise RankerRefused("the model did not pass its evaluation gate")
        return cls(record)

    def scores(self, candidates: Sequence[Dict[str, float]]) -> List[float]:
        return [score(self.model, c) for c in candidates]
