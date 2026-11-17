"""
The learned selector: one model slot for every place the engine chooses among valid results.

A model is one JSON file, its training record with the model inside. Two kinds load here:
calibrated monotone weights (``variant_weights``) and boosted trees, trained with LightGBM and
walked here in plain Python, so run time needs nothing beyond the standard library. Both
answer the same question about a pair: the chance that one design is preferred to another,
from the difference of their measured facts and the document's context.

The model is a student of AI preference comparisons, not of human judgment. It only orders
results that already passed the hard gates. It is off unless a caller asks (``ranker="auto"``
for the model packaged with a release, or a path). It replaces the fixed choice only when its
win probability over that choice clears the threshold in its record; otherwise it abstains.
The result says which selector chose and what moved it, and any problem with a model leaves
the fixed selector in charge.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from typing import Callable, Dict, List, Optional, Sequence

from ..design.profile import Profile

# Measured facts only: what a page shows, never what a plan says about it. A design from a
# direction added later is described by the same facts.
FEATURES = [
    "fit", "index",                                             # the fixed selector's two inputs
    # the page images
    "sparse_share", "alike_share", "page_variety", "type_contrast", "image_share", "last_page_ink",
    # the document, read from its PDF (PageFacts.document)
    "pages", "page_growth", "cover_image_share", "cover_colour_share", "cover_title_to_body", "cover_words",
    "opener_page_share", "page_kind_entropy", "page_kinds", "longest_same_kind_run", "image_share_mean",
    "text_share_mean", "pages_without_image_share", "interior_gap_pages", "largest_interior_gap", "mean_page_bottom",
    "short_pages_before_last", "last_page_fill", "last_page_words", "band_words_mean", "band_words_spread",
    "body_size", "body_leading", "distinct_sizes", "largest_to_body", "font_faces", "arabic_line_share",
    "arabic_right_edge_share", "both_scripts_side_by_side",
    # the renderer's regions (PageFacts.layout)
    "layout_utilization", "layout_balance", "layout_efficiency", "layout_readability", "layout_typography",
    "layout_placement", "layout_tables", "layout_wasted", "layout_cpl", "layout_separated_figures",
]
# The document itself, the same for every design of it: taste may depend on the kind of document.
CONTEXT = ["arabic", "bilingual", "pages", "words", "tables", "figures", "photos"] + [f"type_{p.value}" for p in Profile]

MODEL_FORMAT = "dynamic-pdf-builder/variant-ranker"       # boosted trees
WEIGHTS_FORMAT = "dynamic-pdf-builder/variant-weights"    # calibrated monotone weights
MAX_MODEL_BYTES = 2 * 1024 * 1024
OVERRIDE = 0.6                  # win probability over the fixed choice needed to replace it, unless the record sets one
PACKAGED = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models", "variant-ranker.json")
ALLOW_FIXTURES = False          # tests only: a record marked synthetic_fixture is otherwise refused


class RankerRefused(Exception):
    """This model may not be used. The reason says why."""


# ── features ───────────────────────────────────────────────────────────────────────────

def _numbers(seen: dict) -> Dict[str, float]:
    return {k: float(seen[k]) if isinstance(seen.get(k), (int, float)) and not isinstance(seen.get(k), bool) else 0.0
            for k in FEATURES}


def variant_features(v) -> Dict[str, float]:
    """The measured facts of one finished design, and the fixed selector's two inputs."""
    r, plan = v.report, getattr(v, "plan", None)
    estimated = plan.brief.estimated_pages if plan else 0
    out = _numbers({"fit": r.fit, "index": r.index, "pages": r.pages,
                    "page_growth": r.pages / estimated if estimated else 1.0,
                    **(r.heuristics or {}), **(r.facts or {})})
    ty = getattr(getattr(v, "theme", None), "typography", None)
    if not out["body_leading"] and out["body_size"] and ty:
        out["body_leading"] = float(ty.line_height)     # no body line wraps: the page cannot show it, the theme set it
    return out


def from_candidate(c: dict) -> Dict[str, float]:
    """The same facts from a row of a batch's candidates.jsonl."""
    return _numbers({**(c.get("features") or {}), **(c.get("layout_facts") or {})})


def layout_features(metrics: Dict[str, float]) -> Dict[str, float]:
    """A layout candidate of one design: its layout facts. The rest is the same for every
    candidate of that design, so it does not move a comparison."""
    metrics = metrics or {}
    return _numbers({"pages": metrics.get("pages", 0.0), **{f"layout_{k}": v for k, v in metrics.items()}})


def context_features(brief) -> Dict[str, float]:
    """The document's context from its brief. None: all zero."""
    out = dict.fromkeys(CONTEXT, 0.0)
    if brief is not None:
        out.update(arabic=float(brief.language == "rtl"), bilingual=float(brief.language == "bilingual"),
                   pages=float(brief.estimated_pages), words=float(brief.words), tables=float(brief.tables),
                   figures=float(brief.charts), photos=float(brief.photos))
        if f"type_{brief.profile}" in out:
            out[f"type_{brief.profile}"] = 1.0
    return out


def vector(features: Dict[str, float]) -> List[float]:
    return [float(features.get(k, 0.0)) for k in FEATURES]


def pair_features(a: Dict[str, float], b: Dict[str, float]) -> List[float]:
    return [x - y for x, y in zip(vector(a), vector(b))]


def context_vector(context: Optional[Dict[str, float]]) -> List[float]:
    return [float((context or {}).get(k, 0.0)) for k in CONTEXT]


# ── models ─────────────────────────────────────────────────────────────────────────────

def _sigmoid(z: float) -> float:
    return 1 / (1 + math.exp(-z)) if z >= 0 else math.exp(z) / (1 + math.exp(z))


class Pairwise:
    """What both model kinds share. A kind gives ``logit(d, c)``: how strongly the first of a
    pair is preferred, from the difference ``d`` of their facts and the context ``c``."""

    record: dict
    digest: str

    def logit(self, d: List[float], c: List[float]) -> float:
        raise NotImplementedError

    def prob(self, a: Dict[str, float], b: Dict[str, float], context=None) -> float:
        """The chance that ``a`` is preferred to ``b``."""
        return _sigmoid(self.logit(pair_features(a, b), context_vector(context)))

    def scores(self, candidates: Sequence[Dict[str, float]], context=None) -> List[float]:
        """One score a candidate: its mean chance of being preferred to each of the others."""
        n = len(candidates)
        if n < 2:
            return [0.0] * n
        return [sum(self.prob(a, b, context) for j, b in enumerate(candidates) if j != i) / (n - 1)
                for i, a in enumerate(candidates)]

    def reasons(self, a: Dict[str, float], b: Dict[str, float], context=None, top: int = 3) -> List[str]:
        """The facts that moved the preference of ``a`` over ``b`` most: each is set equal in
        turn, and the change in the preference is its share."""
        d, c = pair_features(a, b), context_vector(context)
        whole = self.logit(d, c)
        moved = sorted(((whole - self.logit(d[:i] + [0.0] + d[i + 1:], c), k) for i, k in enumerate(FEATURES) if d[i]),
                       key=lambda m: -abs(m[0]))
        return [f"{k} {'for' if m > 0 else 'against'} it ({a.get(k, 0.0):g} against {b.get(k, 0.0):g})"
                for m, k in moved[:top] if abs(m) > 1e-9]


def _leaf(node, x: List[float]) -> float:
    while isinstance(node, list):                # [feature, threshold, at or below, above]; a leaf is its value
        node = node[2] if x[node[0]] <= node[1] else node[3]
    return node


def _check_tree(node, width: int, depth: int = 0) -> None:
    if isinstance(node, (int, float)) and not isinstance(node, bool):
        return
    if (depth > 64 or not isinstance(node, list) or len(node) != 4 or not isinstance(node[0], int)
            or not 0 <= node[0] < width or not isinstance(node[1], (int, float))):
        raise RankerRefused("the model's trees are not in the expected form")
    _check_tree(node[2], width, depth + 1)
    _check_tree(node[3], width, depth + 1)


class VariantRanker(Pairwise):
    """Boosted trees over the fact differences and the context, walked in plain Python."""

    def __init__(self, record: dict):
        trees = (record.get("model") or {}).get("trees")
        if not isinstance(trees, list) or not trees:
            raise RankerRefused("the model's trees are not in the expected form")
        for t in trees:
            _check_tree(t, len(FEATURES) + len(CONTEXT))
        self.record, self.trees, self.digest = record, trees, record["model_sha256"]

    def raw(self, x: List[float]) -> float:
        return sum(_leaf(t, x) for t in self.trees)

    def logit(self, d, c):
        # antisymmetric by construction: preferring a to b is exactly not preferring b to a
        return (self.raw(d + c) - self.raw([-v for v in d] + c)) / 2

    @classmethod
    def load(cls, path: str) -> "VariantRanker":
        record = read_record(path)
        if record["format"] != MODEL_FORMAT:
            raise RankerRefused("the training record has another format")
        return cls(record)


def model_digest(model) -> str:
    return hashlib.sha256(json.dumps(model, sort_keys=True).encode("utf-8")).hexdigest()


def read_record(path: str) -> dict:
    """A model file that may be used: its size, format, features, hash and gate all checked."""
    if not os.path.isfile(path):
        raise RankerRefused(f"model file not found: {path}")
    if os.path.getsize(path) > MAX_MODEL_BYTES:
        raise RankerRefused("model file exceeds 2 MB")
    try:
        with open(path, encoding="utf-8") as f:
            record = json.load(f)
    except (ValueError, UnicodeDecodeError) as e:
        raise RankerRefused("the model file is not a JSON training record") from e
    if not isinstance(record, dict) or record.get("format") not in (MODEL_FORMAT, WEIGHTS_FORMAT):
        raise RankerRefused("the training record has another format")
    if record.get("features") != FEATURES or record.get("context", CONTEXT) != CONTEXT:
        raise RankerRefused("the model was trained on other features")
    if record.get("model_sha256") != model_digest(record.get("model")):
        raise RankerRefused("the model does not match its training record")
    if record.get("synthetic_fixture"):
        if not ALLOW_FIXTURES:
            raise RankerRefused("this is a test fixture, not a model")
    elif not (record.get("gate") or {}).get("passed"):
        raise RankerRefused("the model did not pass its evaluation gate")
    return record


def load_model(path: str) -> Pairwise:
    record = read_record(path)
    if record["format"] == WEIGHTS_FORMAT:
        from .variant_weights import WeightsRanker
        return WeightsRanker(record)
    return VariantRanker(record)


# ── choosing ───────────────────────────────────────────────────────────────────────────

def resolve(ranker: Optional[str]) -> Optional[str]:
    """``None`` or ``"off"``: no model. ``"auto"``: the model packaged with this release. Else a path."""
    if not ranker or ranker == "off":
        return None
    return PACKAGED if ranker == "auto" else ranker


def choose(valid: Sequence, deterministic, ranker: Optional[str], loader: Optional[Callable] = None, *, context=None,
           features: Callable = variant_features, name: Callable = lambda v: v.id):
    """The result to deliver, and a note of which selector chose it and why.

    ``valid`` are results that passed the hard gates and ``deterministic`` is the fixed
    selector's choice among them. The model's choice replaces it only when the model gives it
    a win probability over the fixed choice of at least the record's ``override_threshold``."""
    note = {"selector": "deterministic", "model": None}
    path = resolve(ranker)
    if not path:
        return deterministic, note
    try:
        if ranker == "auto" and not os.path.isfile(path):
            raise RankerRefused("no model is packaged with this release")
        model = (loader or load_model)(path)        # an unusable model is reported even when there is no choice to make
        if len(valid) < 2:
            return deterministic, note
        facts = [features(v) for v in valid]
        scores = model.scores(facts, context)
        best = max(range(len(valid)), key=lambda i: scores[i])
        found = {"model": os.path.basename(path), "model_sha256": model.digest, "labels": model.record.get("labels"),
                 "scores": {name(v): round(s, 4) for v, s in zip(valid, scores)},
                 "deterministic_choice": name(deterministic) if deterministic is not None else None}
        fixed = next((i for i, v in enumerate(valid) if v is deterministic), None)
        if fixed is not None and fixed != best and hasattr(model, "prob"):
            margin = model.prob(facts[best], facts[fixed], context)
            threshold = float(model.record.get("override_threshold", OVERRIDE))
            found.update(margin=round(margin, 4), threshold=threshold)
            if margin < threshold:              # not sure enough to replace the fixed choice
                note.update(found, abstained=True, learned_choice=name(valid[best]))
                return deterministic, note
            found["reasons"] = model.reasons(facts[best], facts[fixed], context)
    except RankerRefused as e:
        note["fallback_reason"] = str(e)
        return deterministic, note
    except Exception as e:  # noqa: BLE001 - a broken model must never stop a document
        note["fallback_reason"] = f"the model failed: {e}"
        return deterministic, note
    note.update(found, selector="learned")
    return valid[best], note
