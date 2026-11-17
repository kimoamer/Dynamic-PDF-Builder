"""M18: what the trainer chooses and what its gate asks, beyond a better average."""
import importlib.util
import random

import pytest

from dynamic_pdf.intelligence import variant_ranker as VR
from dynamic_pdf.intelligence import variant_weights as W


@pytest.fixture(scope="module")
def trainer():
    spec = importlib.util.spec_from_file_location("trainer18", "scripts/train_variant_ranker.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def weights(threshold=0.6, **w):
    model = {"monotone": W.MONOTONE, "weights": [float(w.get(k, 0.0)) for k in VR.FEATURES],
             "scale": [1.0] * len(VR.FEATURES), "l2": 0.0}
    return W.WeightsRanker({"model": model, "model_sha256": VR.model_digest(model), "override_threshold": threshold})


def cand(name, pages, fixed=False):
    return {"candidate": name, "features": {"pages": pages}, "layout_facts": {}, "deterministic_pick": fixed, "context": None}


def row(doc, a, b, preferred):
    return {"batch": "t", "document": doc, "a": {"candidate": a}, "b": {"candidate": b}, "preferred": preferred}


def test_a_gain_carried_by_one_document_does_not_hold_when_documents_are_resampled(trainer):
    assert trainer.resampled_gain([1] * 9, [0] * 9, list("aaabbbccc"), 500, 0.05) == 1.0
    assert trainer.resampled_gain([1] * 9, [1] * 9, list("aaabbbccc"), 500, 0.05) == 0.0
    lucky = trainer.resampled_gain([1, 1, 1, 0, 0, 0, 0, 0, 0], [0] * 9, list("aaabbbccc"), 500, 0.05)
    assert lucky == 0.0 and trainer.resampled_gain([], [], [], 500, 0.05) is None


def test_the_override_threshold_is_the_lowest_confidence_that_was_right_often_enough(trainer):
    assert trainer.override_threshold([0.9] * 30)[0] == 0.6
    mixed = [0.62] * 30 + [0.38] * 30 + [0.9] * 25              # unsure half right, sure always right
    t, seen = trainer.override_threshold(mixed)
    assert t == 0.65 and seen == {"asserted": 25, "precision": 1.0}
    assert trainer.override_threshold([0.55] * 40)[0] == 0.95    # never sure enough: it will rarely overrule
    assert trainer.override_threshold([0.9] * 19)[0] == 0.95     # too few to trust


def test_cross_validation_never_trains_on_the_family_it_predicts(trainer):
    family = {"d1": "f", "d2": "f", "e1": "g", "h1": "h"}
    picks = [(d, cand("x", 3), cand("y", 2)) for d in ("d1", "d2", "e1", "h1")]
    seen = []

    def make(train):
        seen.append({family[d] for d, *_ in train})
        return weights(pages=1)
    probs = trainer.cross_validate(make, picks, family)
    assert len(probs) == 4 and all(p > 0.5 for p in probs)
    assert sorted(map(sorted, seen)) == [["f", "g"], ["f", "h"], ["g", "h"]]
    assert trainer.cross_validate(make, picks[:2], family) == []          # one family: nothing to leave out


def test_an_override_is_right_only_when_the_judges_preferred_it_to_the_fixed_choice(trainer):
    cands = {("t", d, c["candidate"]): c for d in ("d1", "d2", "d3", "d4")
             for c in (cand("long", 5), cand("short", 2, fixed=True))}
    rows = [row("d1", "long", "short", "A"), row("d2", "short", "long", "A"), row("d3", "long", "short", "A"),
            row("d4", "short", "long", "B")]
    out = trainer.overrides(weights(pages=5), rows, cands)
    assert out == {"documents": 4, "overrode": 4, "right": 3, "wrong": 1, "unjudged": 0, "abstained": 0}
    shy = trainer.overrides(weights(threshold=0.9999999999, pages=1), rows, cands)
    assert shy["overrode"] == 0 and shy["abstained"] == 4
    assert trainer.overrides(weights(pages=5), [row("d1", "long", "other", "A")], cands)["unjudged"] == 1


def test_the_booster_cannot_learn_that_more_fit_is_worse(trainer):
    pytest.importorskip("lightgbm")
    rng, fit = random.Random(18), VR.FEATURES.index("fit")
    width = len(VR.FEATURES) + len(VR.CONTEXT)
    X = [[rng.uniform(-2, 2) for _ in range(width)] for _ in range(400)]
    y = [int(r[fit] < 0) for r in X]                              # labels that say more fit loses
    model = {"trees": trainer.to_trees(trainer.train(X, y, rounds=20))}
    ranker = VR.VariantRanker({"model": model, "model_sha256": VR.model_digest(model)})
    base = [0.0] * width
    raw = [ranker.raw(base[:fit] + [v / 4] + base[fit + 1:]) for v in range(-8, 9)]
    assert all(b >= a - 1e-12 for a, b in zip(raw, raw[1:]))
