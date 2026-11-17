"""
Calibrated, monotone weights over measured facts: the model to beat before any LightGBM.

A pairwise logistic model (Bradley-Terry): the chance that design a is preferred to design b
is ``sigmoid(w . (x_a - x_b) / scale)``, so a score difference reads as a win probability.
Weights whose direction is known are held to it (``MONOTONE``): more fit never counts against
a design, more sparse pages never for it. It is one of the two kinds the learned selector
loads (``variant_ranker``), reads the same facts and passes the same gate.
"""
from __future__ import annotations

import math
from typing import Dict, List, Sequence, Tuple

from .variant_ranker import FEATURES, WEIGHTS_FORMAT, Pairwise, RankerRefused, model_digest, read_record

FORMAT = WEIGHTS_FORMAT
MONOTONE = {"fit": 1, "index": 1, "page_growth": -1, "sparse_share": -1, "alike_share": -1, "page_variety": 1,
            "last_page_ink": 1, "last_page_fill": 1, "short_pages_before_last": -1, "interior_gap_pages": -1,
            "largest_interior_gap": -1, "layout_wasted": -1, "layout_separated_figures": -1}
#           +1 never hurts, -1 never helps; absent means free


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
    return {"monotone": MONOTONE, "weights": [round(float(v), 6) for v in w],
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


digest = model_digest


class WeightsRanker(Pairwise):
    def __init__(self, record: dict):
        model = record.get("model") or {}
        if len(model.get("weights", [])) != len(FEATURES) or len(model.get("scale", [])) != len(FEATURES):
            raise RankerRefused("the model was trained on other features")
        if model.get("monotone") != MONOTONE or any(MONOTONE.get(k, 0) * w < 0 for k, w in zip(FEATURES, model["weights"])):
            raise RankerRefused("the weights break their monotone constraints")
        self.record, self.model, self.digest = record, model, record["model_sha256"]

    def logit(self, d, c):
        return sum(w * x / s for w, x, s in zip(self.model["weights"], d, self.model["scale"]))

    @classmethod
    def load(cls, path: str) -> "WeightsRanker":
        record = read_record(path)
        if record["format"] != FORMAT:
            raise RankerRefused("the training record has another format")
        return cls(record)
