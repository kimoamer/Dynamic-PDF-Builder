"""
Optional learned ordering of valid design variants (LightGBM, CPU, offline).

The ranker is a student of AI preference comparisons, not of human judgment. It only
reorders designs that already passed the hard gates and it is off unless a caller names a
model. A model loads only with a training record whose gate passed; any problem leaves the
deterministic selector in charge, and the result says which selector chose.
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Dict, List, Optional, Sequence

FEATURES = [
    "pages", "page_growth", "fit", "index", "sparse_share", "alike_share", "page_variety", "type_contrast", "image_share",
    "last_page_ink", "cover_image", "cover_colour", "opener_pages", "figure_pages", "side_images", "bleed_images",
    "base_size", "line_height", "band_fill", "band_rule", "grammar_rules", "refinements",
]
MAX_MODEL_BYTES = 2 * 1024 * 1024
MODEL_FORMAT = "dynamic-pdf-builder/variant-ranker"


class RankerRefused(Exception):
    """This model may not be used. The reason says why."""


def variant_features(v) -> Dict[str, float]:
    """Measurements of one finished design: page rhythm, cover, type, images, density, bands."""
    r, plan = v.report, v.plan
    h = r.heuristics or {}
    cover = (plan.cover if plan else "") or ""
    compositions = [s.composition for s in plan.sections] if plan else []
    openers = [s.opener for s in plan.sections] if plan else []
    bands = (plan.bands if plan else "") or ""
    size, leading = _typography(plan.typography if plan else "")
    estimated = plan.brief.estimated_pages if plan else 0
    out = {
        "pages": float(r.pages), "page_growth": r.pages / estimated if estimated else 1.0, "fit": r.fit, "index": r.index,
        "cover_image": float(cover in ("image_top", "split", "full")), "cover_colour": float(cover in ("masthead", "colour_panel", "full")),
        "opener_pages": float(sum(o == "page" for o in openers)), "figure_pages": float(sum(o == "performance page" for o in openers)),
        "side_images": float(sum("float" in c for c in compositions)), "bleed_images": float(sum("bleed" in c for c in compositions)),
        "base_size": size, "line_height": leading, "band_fill": float("filled" in bands),
        "band_rule": float(bands in ("line", "institutional")), "grammar_rules": float(len(r.grammar_rules)),
        "refinements": float(len(r.refinements)),
    }
    for key in ("sparse_share", "alike_share", "page_variety", "type_contrast", "image_share", "last_page_ink"):
        out[key] = float(h.get(key, 0.0))
    return out


def _typography(text: str) -> tuple:
    tail = text.rsplit(" ", 1)[-1] if text else ""
    try:
        size, leading = tail.split("/")
        return float(size), float(leading)
    except ValueError:
        return 0.0, 0.0


def vector(features: Dict[str, float]) -> List[float]:
    return [float(features.get(k, 0.0)) for k in FEATURES]


def pair_features(a: Dict[str, float], b: Dict[str, float]) -> List[float]:
    return [x - y for x, y in zip(vector(a), vector(b))]


def read_record(model_path: str) -> dict:
    side = os.path.splitext(model_path)[0] + ".json"
    if not os.path.isfile(side):
        raise RankerRefused(f"no training record beside {model_path}")
    with open(side, encoding="utf-8") as f:
        record = json.load(f)
    if record.get("format") != MODEL_FORMAT:
        raise RankerRefused("the training record has another format")
    return record


class VariantRanker:
    def __init__(self, booster, record: dict, digest: str):
        self._booster, self.record, self.digest = booster, record, digest

    @classmethod
    def load(cls, path: str) -> "VariantRanker":
        if not os.path.isfile(path):
            raise RankerRefused(f"model file not found: {path}")
        if os.path.getsize(path) > MAX_MODEL_BYTES:
            raise RankerRefused("model file exceeds 2 MB")
        record = read_record(path)
        with open(path, "rb") as f:
            raw = f.read()
        digest = hashlib.sha256(raw).hexdigest()
        if record.get("model_sha256") != digest:
            raise RankerRefused("the model does not match its training record")
        if record.get("features") != FEATURES:
            raise RankerRefused("the model was trained on other features")
        if not (record.get("gate") or {}).get("passed"):
            raise RankerRefused("the model did not pass its evaluation gate")
        text = raw.decode("utf-8")
        if not text.startswith("tree\n"):
            raise RankerRefused("not a LightGBM text model")
        try:
            import lightgbm
        except ImportError as e:
            raise RankerRefused("lightgbm is not installed") from e
        return cls(lightgbm.Booster(model_str=text), record, digest)

    def scores(self, candidates: Sequence[Dict[str, float]]) -> List[float]:
        n = len(candidates)
        if n < 2:
            return [0.0] * n
        rows, owners = [], []
        for i in range(n):
            for j in range(n):
                if i != j:
                    rows.append(pair_features(candidates[i], candidates[j]))
                    owners.append(i)
        import numpy as np
        out = [0.0] * n
        for owner, p in zip(owners, self._booster.predict(np.array(rows, dtype=float))):
            out[owner] += float(p) / (n - 1)
        return out


def load_model(path: str):
    """A ``.json`` path is a calibrated weights model; anything else a LightGBM ranker."""
    if path.lower().endswith(".json"):
        from .variant_weights import WeightsRanker
        return WeightsRanker.load(path)
    return VariantRanker.load(path)


def choose(valid: Sequence, deterministic, model_path: Optional[str], loader=load_model):
    """The design to recommend, and a note of which selector chose it and why."""
    note = {"selector": "deterministic", "model": None}
    if not model_path:
        return deterministic, note
    try:
        ranker = loader(model_path)
        scores = ranker.scores([getattr(ranker, "features", variant_features)(v) for v in valid])
    except RankerRefused as e:
        note["fallback_reason"] = str(e)
        return deterministic, note
    except Exception as e:  # noqa: BLE001 - a broken model must never stop a document
        note["fallback_reason"] = f"the model failed: {e}"
        return deterministic, note
    best = max(range(len(valid)), key=lambda i: scores[i])
    note.update(selector="learned", model=os.path.basename(model_path), model_sha256=ranker.digest,
                labels=ranker.record.get("labels"), scores={v.id: round(s, 4) for v, s in zip(valid, scores)},
                deterministic_choice=deterministic.id if deterministic else None)
    return valid[best], note
