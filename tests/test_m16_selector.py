"""M16: one model slot the main path can use, without LightGBM at run time."""
import importlib.util
import json
import random
import subprocess
import sys

import pymupdf
import pytest

from conftest import fixture_text
from dynamic_pdf import DocumentBuilder
from dynamic_pdf.intelligence import variant_ranker as VR
from dynamic_pdf.intelligence import variant_weights as W


def proposal():
    return DocumentBuilder.from_markdown(fixture_text("proposal.md"))


def fixture_model(tmp_path, *, threshold=0.6, name="fixture.json", **weights):
    """A weights model marked as a test fixture. ``pages=5`` prefers the longer design, which is
    not the fixed selector's choice for the proposal."""
    model = {"monotone": W.MONOTONE, "weights": [float(weights.get(k, 0.0)) for k in VR.FEATURES],
             "scale": [1.0] * len(VR.FEATURES), "l2": 0.0}
    record = {"format": W.FORMAT, "labels": "test fixture", "features": VR.FEATURES, "context": VR.CONTEXT,
              "override_threshold": threshold, "model": model, "model_sha256": VR.model_digest(model),
              "synthetic_fixture": True, "gate": {"passed": False}}
    path = tmp_path / name
    path.write_text(json.dumps(record), encoding="utf-8")
    return str(path)


@pytest.fixture
def fixtures_allowed(monkeypatch):
    monkeypatch.setattr(VR, "ALLOW_FIXTURES", True)


@pytest.fixture
def trainer():
    spec = importlib.util.spec_from_file_location("trainer", "scripts/train_variant_ranker.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ── inference without LightGBM ─────────────────────────────────────────────────────────

def test_the_tree_walker_gives_lightgbms_own_predictions(trainer):
    pytest.importorskip("lightgbm")
    import numpy as np
    rng = random.Random(16)
    width = len(VR.FEATURES) + len(VR.CONTEXT)
    X = [[rng.uniform(-2, 2) for _ in range(width)] for _ in range(600)]
    y = [int(r[0] * 1.5 - r[3] + 0.5 * r[10] * (1 if r[-3] > 0 else -1) + rng.gauss(0, 0.5) > 0) for r in X]
    booster = trainer.train(X, y)
    model = {"trees": trainer.to_trees(booster)}
    ranker = VR.VariantRanker({"model": model, "model_sha256": VR.model_digest(model)})
    probe = [[rng.uniform(-3, 3) for _ in range(width)] for _ in range(1000)]
    ours = np.array([VR._sigmoid(ranker.raw(r)) for r in probe])
    assert np.abs(ours - booster.predict(np.array(probe))).max() < 1e-9
    assert len(json.dumps(model)) < 200_000


def test_using_a_tree_model_never_imports_lightgbm(tmp_path):
    model = {"trees": [[VR.FEATURES.index("pages"), 0.0, -2.0, 2.0]]}      # prefers the longer design
    record = {"format": VR.MODEL_FORMAT, "features": VR.FEATURES, "context": VR.CONTEXT, "model": model,
              "model_sha256": VR.model_digest(model), "synthetic_fixture": True, "gate": {"passed": False}}
    path = tmp_path / "trees.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    code = ("import sys, warnings; warnings.simplefilter('ignore'); sys.modules['lightgbm'] = None\n"
            "from dynamic_pdf import DocumentBuilder\n"
            "from dynamic_pdf.intelligence import variant_ranker as VR\n"
            "VR.ALLOW_FIXTURES = True\n"
            f"made = DocumentBuilder.from_markdown(open({str('tests/fixtures/proposal.md')!r}, encoding='utf-8').read())"
            f".design_variants(n=3, ranker={str(path)!r})\n"
            "s = made.stats['selection']\n"
            "assert s['selector'] == 'learned' and made.recommended.id == 'executive_premium', s\n"
            "assert sys.modules['lightgbm'] is None\n")
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr[-800:]


# ── the main path ──────────────────────────────────────────────────────────────────────

def test_export_delivers_the_learned_choice_and_says_why(tmp_path, fixtures_allowed):
    out = tmp_path / "out.pdf"
    res = proposal().design("auto", variants=3, ranker=fixture_model(tmp_path, pages=5)).export(str(out))
    s = res.design.selection
    assert res.design.recommended == "executive_premium" and s["selector"] == "learned"
    assert s["deterministic_choice"] == "editorial_modern" and s["margin"] >= s["threshold"] == 0.6
    assert s["labels"] == "test fixture" and any(r.startswith("pages for it") for r in s["reasons"])
    assert any("learned selector" in r for r in res.design.reasons)
    assert len(pymupdf.open(str(out))) == 2                    # the file is the learned choice, not the fixed one


def test_the_cli_names_a_model_too(tmp_path, fixtures_allowed, monkeypatch, capsys):
    from dynamic_pdf import cli
    src = tmp_path / "in.md"
    src.write_text(fixture_text("proposal.md"), encoding="utf-8")
    model = fixture_model(tmp_path, pages=5)
    monkeypatch.setattr(sys, "argv", ["dynamic-pdf", "render", str(src), "-o", str(tmp_path / "o.pdf"), "--variants", "3",
                                      "--ranker", model])
    cli.main()
    assert "design: executive_premium" in capsys.readouterr().out
    monkeypatch.setattr(sys, "argv", ["dynamic-pdf", "variants", str(src), "-o", str(tmp_path / "v"), "-n", "3",
                                      "--ranker", model])
    cli.main()
    shown = capsys.readouterr().out
    assert "recommended: executive_premium" in shown and "learned selector" in shown


def test_the_model_abstains_when_it_is_not_sure_enough(tmp_path, fixtures_allowed):
    made = proposal().design_variants(n=3, ranker=fixture_model(tmp_path, threshold=0.9999, pages=5))
    s = made.stats["selection"]
    assert made.recommended.id == "editorial_modern" and s["selector"] == "deterministic"
    assert s["abstained"] and s["learned_choice"] == "executive_premium" and s["margin"] < s["threshold"]
    assert any("not sure enough" in r for r in made.reasons)


def test_a_model_that_agrees_changes_nothing_but_the_note(tmp_path, fixtures_allowed):
    made = proposal().design_variants(n=3, ranker=fixture_model(tmp_path, fit=5))
    assert made.recommended.id == "editorial_modern" and made.stats["selection"]["selector"] == "learned"


def test_off_auto_without_a_packaged_model_and_a_refused_model_render_the_same_bytes(tmp_path, monkeypatch):
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1700000000")
    plain = proposal().design("auto", variants=3).render()
    assert proposal().design("auto", variants=3, ranker="off").render() == plain
    for asked, reason in (("auto", "no model is packaged"), (str(tmp_path / "none.json"), "not found"),
                          (fixture_model(tmp_path, pages=5), "fixture")):       # a fixture is refused outside tests
        b = proposal().design("auto", variants=3, ranker=asked)
        assert b.render() == plain
        s = b.last_variants.stats["selection"]
        assert s["selector"] == "deterministic" and reason in s["fallback_reason"]


def test_asking_for_the_selector_asks_for_variants(tmp_path, fixtures_allowed):
    res = proposal().design("auto", ranker=fixture_model(tmp_path, pages=5)).export(str(tmp_path / "o.pdf"))
    assert res.design is not None and res.design.recommended == "executive_premium"
    assert proposal().design("auto", ranker="off").export(str(tmp_path / "p.pdf")).design is None


# ── one feature function ───────────────────────────────────────────────────────────────

def test_one_feature_function_serves_designs_dataset_rows_and_layouts():
    made = proposal().design_variants(n=2)
    v = made.variants[0]
    f = VR.variant_features(v)
    assert list(f) == VR.FEATURES and f["fit"] == v.report.fit and f["body_size"] == v.report.facts["body_size"]
    assert f["layout_utilization"] == v.report.facts["layout_utilization"] and f["sparse_share"] == v.report.heuristics["sparse_share"]
    row = {"features": {"fit": 2.0, "cover_colour": 1.0}, "layout_facts": {"last_page_fill": 0.4, "page_kinds": 3}}
    c = VR.from_candidate(row)
    assert list(c) == VR.FEATURES and c["fit"] == 2.0 and c["last_page_fill"] == 0.4 and "cover_colour" not in c
    layout = VR.layout_features({"utilization": 0.7, "pages": 3.0, "wasted": 0.1})
    assert layout["layout_utilization"] == 0.7 and layout["pages"] == 3.0 and layout["fit"] == 0.0
    assert not [k for k in VR.FEATURES if k.startswith(("cover_image", "band_fill", "grammar", "refinement"))
                and not k.endswith("_share")]                       # no plan descriptors


def test_context_describes_the_document_and_is_the_same_for_its_designs():
    a = proposal().design_variants(n=2).stats["context"]          # one context a document, not one a design
    assert list(a) == VR.CONTEXT and a["type_proposal"] == 1.0 and a["arabic"] == 0.0 and a["tables"] == 1.0
    assert a["pages"] == 1.0 and set(VR.context_features(None).values()) == {0.0}


# ── the trainer writes what the package reads ──────────────────────────────────────────

def test_the_booster_is_written_as_one_json_file_the_package_loads(tmp_path, trainer, monkeypatch):
    pytest.importorskip("lightgbm")
    import tools.design_learning.reference_sampling as S
    from test_m12_learning import training_world
    monkeypatch.setattr(S, "audit", lambda *a, **k: {"ready": True, "issues": []})
    data, batches, split = training_world(tmp_path)
    out = tmp_path / "ranker.json"
    trainer.main(["--dataset", data, "--batches", batches, "--split", split, "--out", str(out), "--min-pairs", "2",
                  "--synthetic-fixture"])
    rec = json.loads(out.read_text(encoding="utf-8"))
    assert rec["format"] == VR.MODEL_FORMAT and rec["features"] == VR.FEATURES and rec["context"] == VR.CONTEXT
    assert rec["model"]["trees"] and rec["model_sha256"] == VR.model_digest(rec["model"]) and rec["override_threshold"] == VR.OVERRIDE
    assert rec["gate"]["passed"] is False and not (tmp_path / "ranker.txt").exists()
    with pytest.raises(VR.RankerRefused, match="fixture"):
        VR.load_model(str(out))
    monkeypatch.setattr(VR, "ALLOW_FIXTURES", True)
    assert isinstance(VR.load_model(str(out)), VR.VariantRanker)
    with pytest.raises(SystemExit, match="json"):
        trainer.main(["--dataset", "d", "--batches", "b", "--split", "s", "--out", "m.txt"])
