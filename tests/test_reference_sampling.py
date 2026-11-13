"""Regression checks for the offline M7.7/M7.10 bridge and blind-pair planner."""
import hashlib
import json
import sys
import types
from pathlib import Path

import pytest

from tools.design_learning import reference_sampling as S


def graph(doc, page, count=2, direction="rtl", family="image_split", image=.25):
    return {"ref": f"{doc}:{page}", "doc": doc, "page": page,
            "measures": {"image_share": image, "text_share": .15},
            "direction": direction, "family": family, "cluster_in_document": 1}


def test_bridge_reuses_measured_reference_pages_without_inventing_labels():
    graphs = {"documents": [{"doc_id": "a", "pages": 2}],
              "pages": [graph("a", 1, image=.6), graph("a", 2, image=.1)]}
    cov = {"pages": [{"ref": f"a:{p}", "ai_observation": {"depth": "contact_sheet"}} for p in (1, 2)],
           "documents": [{"doc_id": "a", "rights_note": "unknown"}]}
    prof = S.bridge(graphs, cov)
    assert prof["reference_pages"] == 2
    assert prof["label_kind"] == "none"
    assert prof["documents"][0]["common_proxies"] == {
        "cover_image_share": .6, "image_share_mean": .1, "text_share_mean": .15,
        "pages_without_image_share": 0,
    }
    assert prof["documents"][0]["language_hint"] == "arabic"
    assert "nodes" not in json.dumps(prof) and "preferred" not in json.dumps(prof)


def test_reference_language_respects_catalog_and_does_not_flip_on_one_foreign_page():
    graphs = {
        "documents": [{"doc_id": "ar", "file": "02-Arabic/annual.pdf", "pages": 3},
                      {"doc_id": "bi", "file": "03-Bilingual/contract.pdf", "pages": 2}],
        "pages": [graph("ar", 1, direction="rtl"), graph("ar", 2, direction="ltr"),
                  graph("ar", 3, direction="rtl"), graph("bi", 1, direction="ltr"),
                  graph("bi", 2, direction="rtl")]}
    out = S.bridge(graphs)
    a, b = out["documents"]
    assert a["language_hint"] == "arabic" and a["language_basis"] == "catalog_folder"
    assert b["language_hint"] == "bilingual" and b["language_basis"] == "catalog_folder"
    # paths are read for the folder label and never copied out (the format name itself
    # contains "profiles", so a bare substring test for "file" cannot tell)
    dumped = json.dumps(out)
    assert "annual.pdf" not in dumped and "contract.pdf" not in dumped and "02-Arabic" not in dumped
    assert all("file" not in d for d in out["documents"])


def test_bridge_refuses_missing_or_unmatched_pages():
    graphs = {"documents": [{"doc_id": "a", "pages": 2}], "pages": [graph("a", 1)]}
    with pytest.raises(ValueError, match="missing or out-of-range"):
        S.bridge(graphs)
    graphs["pages"].append(graph("a", 2))
    with pytest.raises(ValueError, match="coverage page references"):
        S.bridge(graphs, {"pages": [], "documents": []})
    graphs["pages"][1]["measures"]["image_share"] = float("nan")
    with pytest.raises(ValueError, match="finite fraction"):
        S.bridge(graphs)


@pytest.fixture
def batch(tmp_path):
    path = tmp_path / "batches" / "new-003"
    path.mkdir(parents=True)
    entries = []
    for doc, lang in (("arabic_policy", .9), ("english_policy", 0.0), ("bilingual_report", .6)):
        for n in ("a", "b", "c"):
            body = (doc + n).encode()
            digest = hashlib.sha256(body).hexdigest()
            entries.append({"document": doc, "document_hash": doc + "-source", "candidate": n,
                            "design": n, "pdf_sha256": digest, "docx_sha256": digest,
                            "layout_facts": {"facts_version": 1, "image_share_mean": {"a": .05, "b": .5, "c": .9}[n],
                                             "cover_image_share": {"a": .1, "b": .7, "c": .4}[n],
                                             "text_share_mean": .2, "pages_without_image_share": .5,
                                             "last_page_fill": .6, "arabic_line_share": lang,
                                             "both_scripts_side_by_side": .3 if doc.startswith("bilingual") else 0},
                            "_body": body})
            render = path / "renders" / doc / (n + ".pdf")
            render.parent.mkdir(parents=True, exist_ok=True)
            render.write_bytes(body)
    with (path / "candidates.jsonl").open("w", encoding="utf-8") as f:
        for c in entries:
            f.write(json.dumps({k: v for k, v in c.items() if k != "_body"}) + "\n")
    split = tmp_path / "split.json"
    split.write_text(json.dumps({"families": {"arabic": ["arabic_policy"], "english": ["english_policy"],
                                              "bilingual": ["bilingual_report"]},
                                 "evaluation_families": ["english"]}), encoding="utf-8")
    dataset = tmp_path / "ai.jsonl"
    dataset.write_text("", encoding="utf-8")
    return path, dataset, split


def test_plan_balances_languages_and_preserves_holdout(batch):
    path, dataset, split = batch
    result = S.plan(str(path), str(dataset), str(split), source="pdf", count=6, max_per_doc=2)
    assert result["summary"]["selected"] == 6
    assert result["summary"]["languages"]["arabic"] == 2
    assert result["summary"]["languages"]["bilingual"] == 2
    assert len({(p["document"], frozenset((p["a"], p["b"]))) for p in result["pairs"]}) == 6
    assert all(p["split"] == "evaluation" for p in result["pairs"] if p["document"] == "english_policy")
    assert not any("preferred" in p for p in result["pairs"])


def test_plan_requires_media_hashes_and_disallows_metadata_only_sheets(batch, tmp_path):
    path, dataset, split = batch
    first = S.plan(str(path), str(dataset), str(split), source="pdf", count=2)
    p = tmp_path / "plan.json"
    S.write_json(str(p), first)
    assert len(S.sheet_pairs(str(path), "pdf", str(p))) == 2
    fake = S.plan(str(path), str(dataset), str(split), source="pdf", count=2, require_media=False)
    S.write_json(str(p), fake)
    with pytest.raises(ValueError, match="metadata-only"):
        S.sheet_pairs(str(path), "pdf", str(p))
    bad = path / "renders" / "arabic_policy" / "a.pdf"
    bad.write_bytes(b"tampered")
    result = S.plan(str(path), str(dataset), str(split), source="pdf", count=9)
    assert result["summary"]["missing_media_pairs"] > 0


def test_plan_refuses_source_hash_leakage(batch):
    path, dataset, split = batch
    rows = S.jsonl(str(path / "candidates.jsonl"))
    for r in rows:
        if r["document"] == "english_policy":
            r["document_hash"] = "arabic_policy-source"
    (path / "candidates.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="source-hash leakage"):
        S.plan(str(path), str(dataset), str(split), source="pdf")


def test_frozen_plan_refuses_a_changed_holdout_split(batch, tmp_path):
    path, dataset, split = batch
    proposal = S.plan(str(path), str(dataset), str(split), source="pdf", count=2)
    plan_file = tmp_path / "plan.json"
    S.write_json(str(plan_file), proposal)
    assert len(S.sheet_pairs(str(path), "pdf", str(plan_file))) == 2
    split.write_text('{"families": {}, "evaluation_families": []}', encoding="utf-8")
    with pytest.raises(ValueError, match="held-out family split changed"):
        S.sheet_pairs(str(path), "pdf", str(plan_file))


def test_word_requires_actual_word_build_not_a_pdf_masquerading_as_word(batch):
    path, dataset, split = batch
    with pytest.raises(ValueError, match="Word build/version evidence"):
        S.plan(str(path), str(dataset), str(split), source="word")
    meta = S.plan(str(path), str(dataset), str(split), source="word", require_media=False)
    assert meta["metadata_only"]
    assert meta["source"] == "word"


def test_pair_names_from_older_batches_do_not_hide_new_renders(batch):
    path, dataset, split = batch
    dataset.write_text(json.dumps({
        "batch": "old-001", "document": "arabic_policy",
        "document_hash": "arabic_policy-source", "formats_inspected": ["pdf"],
        "a": {"candidate": "a", "pdf_sha256": "old-asset-a"},
        "b": {"candidate": "b", "pdf_sha256": "old-asset-b"},
    }) + "\n", encoding="utf-8")
    result = S.plan(str(path), str(dataset), str(split), source="pdf", count=9, max_per_doc=3)
    pairs = {(p["document"], frozenset((p["a"], p["b"]))) for p in result["pairs"]}
    assert ("arabic_policy", frozenset(("a", "b"))) in pairs


def test_word_manifest_requires_matching_source_and_export_hashes(batch, tmp_path):
    path, dataset, split = batch
    entries = S.jsonl(str(path / "candidates.jsonl"))
    word_dir = path / "word"
    word_dir.mkdir()
    manifest = {"word_build": "16.0.17932", "files": []}
    for c in entries:
        doc, candidate = c["document"], c["candidate"]
        source = path / "renders" / doc / (candidate + ".docx")
        export = word_dir / (doc + "__" + candidate + ".pdf")
        payload = (doc + candidate).encode()
        source.write_bytes(payload)
        export.write_bytes(payload)
        manifest["files"].append({
            "file": doc + "__" + candidate, "ok": True,
            "docx_sha256": c["docx_sha256"], "pdf_sha256": hashlib.sha256(payload).hexdigest()})
    (word_dir / "word.json").write_text(json.dumps(manifest), encoding="utf-8")
    proposal = S.plan(str(path), str(dataset), str(split), source="word", count=2)
    frozen = tmp_path / "plan-word.json"
    S.write_json(str(frozen), proposal)
    assert len(S.sheet_pairs(str(path), "word", str(frozen))) == 2
    pair = proposal["pairs"][0]
    export = word_dir / (pair["document"] + "__" + pair["a"] + ".pdf")
    export.write_bytes(b"changed Word export")
    with pytest.raises(ValueError, match="hash-mismatched"):
        S.sheet_pairs(str(path), "word", str(frozen))


def test_trainer_preflight_blocks_before_model_or_lightgbm(batch, tmp_path):
    import importlib.util
    path, dataset, split = batch
    spec = importlib.util.spec_from_file_location("trainer", "scripts/train_variant_ranker.py")
    trainer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(trainer)
    model = tmp_path / "should-not-exist.txt"
    with pytest.raises(SystemExit, match="data-quality preflight blocked training"):
        trainer.main(["--dataset", str(dataset), "--batches", str(path.parent),
                      "--split", str(split), "--out", str(model)])
    assert not model.exists()


def test_audit_blocks_incomplete_and_does_not_assume_human_labels(batch, monkeypatch):
    path, dataset, split = batch
    fake = types.ModuleType("tools.design_learning.readiness")
    fake._candidates = lambda batches: ({}, set())
    fake.usable = lambda rows, skipped: rows
    monkeypatch.setitem(sys.modules, "tools.design_learning.readiness", fake)
    result = S.audit(str(dataset), str(path.parent), str(split))
    assert result["ready"] is False
    assert result["usable"] == 0
    assert any("human audit" in x for x in result["issues"])
