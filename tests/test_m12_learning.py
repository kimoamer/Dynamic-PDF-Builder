"""M12: the scripted AI review, human signal, and calibrated weights. No real model is called."""
import importlib.util
import json
import threading
import urllib.parse
import urllib.request
from types import SimpleNamespace

import pytest

from dynamic_pdf.intelligence import variant_ranker as VR
from dynamic_pdf.intelligence import variant_weights as W
from dynamic_pdf.intelligence.variants import VariantReport
from tools.design_learning import ab_page, ai_review
from tools.design_learning.readiness import usable


def write_batch(tmp_path):
    d = tmp_path / "batches" / "b1"
    (d / "sheets").mkdir(parents=True)
    for cid in ("cmp-001", "cmp-002"):
        (d / "sheets" / f"{cid}.jpg").write_bytes(b"\xff\xd8\xff fake sheet")
    cands = [{"document": "doc", "document_hash": "h", "candidate": c, "pdf_sha256": c + "-p", "docx_sha256": c + "-d",
              "grammar_version": "1.0.0", "features": {}} for c in ("financial_data", "editorial_modern")]
    (d / "candidates.jsonl").write_text("\n".join(json.dumps(c) for c in cands), encoding="utf-8")
    key = [{"comparison": "cmp-001", "document": "doc", "a": "financial_data", "b": "editorial_modern", "reversed_repeat": False,
            "pages_shown": [3, 3], "pages_total": [3, 3], "shown_px": 240},
           {"comparison": "cmp-002", "document": "doc", "a": "editorial_modern", "b": "financial_data", "reversed_repeat": True,
            "pages_shown": [3, 3], "pages_total": [3, 3], "shown_px": 240}]
    (d / "key.json").write_text(json.dumps({"comparisons": key}), encoding="utf-8")
    return d


def answer(preferred, **k):
    return json.dumps({"preferred": preferred, "criteria": {"hierarchy": 1 if preferred == "A" else -1},
                       "justification": "clearer bands", "confidence": "medium", "pages": ["A1", "B2"], **k})


class FakeBatches:
    def __init__(self, replies, statuses=("in_progress", "ended")):
        self.replies, self.statuses, self.created = replies, list(statuses), None

    def create(self, requests):
        self.created = requests
        return SimpleNamespace(id="msgbatch_test", processing_status="in_progress")

    def retrieve(self, batch_id):
        return SimpleNamespace(processing_status=self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0])

    def results(self, batch_id):
        for r in self.created:
            text = self.replies.get(r["custom_id"])
            if text is None:
                yield SimpleNamespace(custom_id=r["custom_id"], result=SimpleNamespace(type="errored"))
                continue
            msg = SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], model=r["params"]["model"],
                                  stop_reason="end_turn", usage=SimpleNamespace(input_tokens=1, output_tokens=1))
            yield SimpleNamespace(custom_id=r["custom_id"], result=SimpleNamespace(type="succeeded", message=msg))


def client(replies, **k):
    return SimpleNamespace(messages=SimpleNamespace(batches=FakeBatches(replies, **k)))


JUDGES = ["judge-one", "judge-two"]


class TestAIReview:
    def test_two_judges_are_asked_blind_and_recorded_as_ai_with_their_prompt(self, tmp_path):
        d = write_batch(tmp_path)
        dataset = tmp_path / "ai-preferences.jsonl"
        c = client({"j0-cmp-001": answer("A"), "j0-cmp-002": answer("B"), "j1-cmp-001": answer("A"),
                    "j1-cmp-002": "not json"})
        slept = []
        report = ai_review.run(str(d), str(dataset), JUDGES, client=c, date="2026-11-16", sleep=slept.append, poll=1)
        sent = c.messages.batches.created
        assert len(sent) == 4 and slept == [1]
        assert {r["params"]["model"] for r in sent} == set(JUDGES)
        blob = json.dumps(sent)
        assert "financial_data" not in blob and "editorial_modern" not in blob       # nothing names a design
        assert sent[0]["params"]["system"] == ai_review.RUBRIC
        assert sent[0]["params"]["output_config"]["format"]["type"] == "json_schema"
        rows = [json.loads(x) for x in dataset.read_text(encoding="utf-8").splitlines()]
        assert len(rows) == 3 and {r["reviewer_type"] for r in rows} == {"ai"}
        assert all(r["prompt_sha256"] == ai_review.prompt_sha256() and r["review_date"] == "2026-11-16"
                   and r["message_batch"] == "msgbatch_test" for r in rows)
        assert report["recorded"] == {"judge-one": 2, "judge-two": 1}
        assert report["not_recorded"][0]["comparison"] == "cmp-002" and "invalid" in report["not_recorded"][0]["reason"]
        pair = report["pairs"][0]
        assert pair["sheets"] == 1 and pair["same_answer"] == 1
        assert report["reversed_repeats"]["judge-one"] == {"repeats": 1, "consistent": 1}
        assert json.loads((d / "agreement.json").read_text(encoding="utf-8"))["judges"] == JUDGES
        with pytest.raises(SystemExit, match="already reviewed"):
            ai_review.run(str(d), str(dataset), JUDGES, client=c)

    def test_it_can_submit_and_collect_later(self, tmp_path):
        d = write_batch(tmp_path)
        c = client({}, statuses=("in_progress",))
        out = ai_review.run(str(d), str(tmp_path / "x.jsonl"), JUDGES, client=c, wait=False)
        assert out["status"] == "in_progress" and (d / "ai-review.json").exists()
        with pytest.raises(SystemExit, match="same"):
            ai_review.run(str(d), str(tmp_path / "x.jsonl"), ["judge-one", "other"], client=c, wait=False)

    def test_one_judge_is_not_enough(self, tmp_path):
        with pytest.raises(SystemExit, match="two"):
            ai_review.run(str(write_batch(tmp_path)), "x", ["judge-one"], client=client({}))

    def test_answers_must_cite_pages_unless_abstaining(self):
        with pytest.raises(ValueError):
            ai_review.Answer.model_validate_json(answer("A", pages=[]))
        with pytest.raises(ValueError):
            ai_review.Answer.model_validate_json(answer("A", pages=["page 2"]))
        assert ai_review.Answer.model_validate_json(answer("abstain", pages=[], justification="")).preferred == "abstain"


def row(cid, preferred, model, batch="t", a="x", b="y", repeat=False):
    return {"comparison": cid, "batch": batch, "document": "d", "document_hash": "d", "a": {"candidate": a},
            "b": {"candidate": b}, "preferred": preferred, "confidence": "medium", "reversed_repeat": repeat, "model": model}


def test_agreement_with_people_is_reported_where_they_judged_the_same_sheet():
    rows = [row("cmp-1", "A", "m1"), row("cmp-1", "B", "m2"), row("cmp-2", "A", "m1", a="p", b="q")]
    humans = [{"batch": "t", "comparison": "cmp-1", "preferred": "A", "reviewer_type": "human"},
              {"batch": "t", "comparison": "cmp-1", "preferred": "A", "reviewer_type": "ai"}]       # not a person
    r = ai_review.agreement(rows, humans)
    assert r["with_humans"] == {"m1": {"judgments": 1, "same_answer": 1}, "m2": {"judgments": 1, "same_answer": 0}}
    assert r["pairs"][0]["sheets"] == 1 and r["pairs"][0]["same_answer"] == 0 and r["pairs"][0]["cohen_kappa"] is not None


def test_agreeing_judges_count_a_comparison_once_and_disagreeing_ones_not_at_all():
    rows = [row("cmp-1", "A", "m1"), row("cmp-1", "A", "m2"), row("cmp-2", "A", "m1", a="p", b="q"),
            row("cmp-2", "B", "m2", a="p", b="q")]
    assert [(r["comparison"], r["model"]) for r in usable(rows, set())] == [("cmp-1", "m1")]
    spec = importlib.util.spec_from_file_location("trainer", "scripts/train_variant_ranker.py")
    trainer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(trainer)
    for r in rows:
        r["reviewer_type"] = "ai"
    assert trainer.usable(rows) == usable(rows, set())


class TestJudgingPage:
    def test_a_judgment_is_human_and_reads_like_an_audit_row(self, tmp_path):
        d = write_batch(tmp_path)
        out = tmp_path / "training" / "human_preferences" / "human-audit.jsonl"
        j = ab_page.Judging(str(d), str(out), "A. Person")
        assert j.todo() == ["cmp-001", "cmp-002"]
        r = j.judge("cmp-001", "B", "B1 has a clear cover", "high", date="2026-11-16")
        assert r["reviewer_type"] == "human" and r["reviewer"] == "A. Person" and r["visual_evidence"]
        assert r["document_hash"] == "h" and r["batch"] == "b1" and r["a"]["candidate"] == "financial_data"
        assert j.todo() == ["cmp-002"]
        with pytest.raises(ValueError, match="what you saw"):
            j.judge("cmp-002", "A", " ", "high")
        with pytest.raises(SystemExit, match="human_preferences"):
            ab_page.Judging(str(d), str(tmp_path / "ai_preferences" / "x.jsonl"), "A. Person")

    def test_the_page_serves_the_sheet_and_saves_the_answer(self, tmp_path):
        d = write_batch(tmp_path)
        out = tmp_path / "human_preferences" / "human-audit.jsonl"
        server = ab_page.serve(ab_page.Judging(str(d), str(out), "A. Person"), port=0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            page = urllib.request.urlopen(base + "/").read().decode()
            assert "/img/cmp-001.jpg" in page and "financial_data" not in page
            assert urllib.request.urlopen(base + "/img/cmp-001.jpg").read().startswith(b"\xff\xd8")
            data = urllib.parse.urlencode({"preferred": "A", "confidence": "medium", "evidence": "A2 reads better"}).encode()
            nxt = urllib.request.urlopen(base + "/c/cmp-001", data=data).read().decode()
            assert "/img/cmp-002.jpg" in nxt
            with pytest.raises(urllib.error.HTTPError):
                urllib.request.urlopen(base + "/img/..%2Fkey.json")
        finally:
            server.shutdown()
        saved = json.loads(out.read_text(encoding="utf-8"))
        assert saved["preferred"] == "A" and saved["comparison"] == "cmp-001"


def facts(**k):
    base = {key: 0.5 for key in W.FEATURES}
    return {**base, **k}


class FakeVariant:
    def __init__(self, id, fit=1.0, sparse=0.0):
        self.id, self.plan = id, None
        self.report = VariantReport(status="valid", fit=fit, index=50.0, pages=4, heuristics={"sparse_share": sparse})


class TestWeights:
    def pairs(self):
        # the preferred side has more fit and, by accident of the data, more sparse pages
        return [(facts(fit=1.0 + i % 3, sparse_share=0.4), facts(fit=0.2, sparse_share=0.1)) for i in range(30)]

    def test_weights_learn_the_signal_and_keep_their_direction(self):
        m = W.fit(self.pairs())
        w = dict(zip(W.FEATURES, m["weights"]))
        assert w["fit"] > 0 and w["sparse_share"] <= 0          # held to its sign whatever the data says
        held = W.evaluate(m, self.pairs()[:5])
        assert held["agreement"] == 1.0 and 0 <= held["brier"] < 0.25
        assert W.fit(self.pairs()) == m                          # deterministic

    def record(self, tmp_path, **change):
        m = W.fit(self.pairs())
        rec = {"format": W.FORMAT, "model": m, "model_sha256": W.digest(m), "gate": {"passed": True}}
        rec.update(change)
        path = tmp_path / "w.json"
        path.write_text(json.dumps(rec), encoding="utf-8")
        return str(path), m

    def test_a_passing_record_ranks_by_measured_facts(self, tmp_path):
        path, _ = self.record(tmp_path)
        a, b = FakeVariant("a", fit=0.5), FakeVariant("b", fit=2.0)
        best, note = VR.choose([a, b], a, path)
        assert best is b and note["selector"] == "learned" and note["deterministic_choice"] == "a"
        assert set(W.measured(a)) == set(W.FEATURES)

    @pytest.mark.parametrize("change,reason", [({"gate": {"passed": False}}, "gate"), ({"model_sha256": "0"}, "match"),
                                               ({"format": "x"}, "format")])
    def test_a_record_that_is_not_clean_is_refused(self, tmp_path, change, reason):
        path, _ = self.record(tmp_path, **change)
        with pytest.raises(VR.RankerRefused, match=reason):
            W.WeightsRanker.load(path)
        best, note = VR.choose([FakeVariant("a")], None, path)
        assert note["selector"] == "deterministic" and reason in note["fallback_reason"]

    def test_altered_or_unconstrained_weights_are_refused(self, tmp_path):
        path, m = self.record(tmp_path)
        broken = dict(m, weights=[-1.0] * len(W.FEATURES))
        rec = {"format": W.FORMAT, "model": broken, "model_sha256": W.digest(broken), "gate": {"passed": True}}
        (tmp_path / "w.json").write_text(json.dumps(rec), encoding="utf-8")
        with pytest.raises(VR.RankerRefused, match="monotone"):
            W.WeightsRanker.load(path)
        broken = dict(m, features=W.FEATURES[:-1])
        rec.update(model=broken, model_sha256="x")
        (tmp_path / "w.json").write_text(json.dumps(rec), encoding="utf-8")
        with pytest.raises(VR.RankerRefused, match="features"):
            W.WeightsRanker.load(path)


@pytest.fixture
def trainer():
    spec = importlib.util.spec_from_file_location("trainer", "scripts/train_variant_ranker.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def training_world(tmp_path):
    batch = tmp_path / "batches" / "t"
    batch.mkdir(parents=True)
    docs = ["d1", "d2", "e1"]
    with open(batch / "candidates.jsonl", "w", encoding="utf-8") as f:
        for doc in docs:
            for c, fit in (("good", 2.0), ("weak", 0.5)):
                f.write(json.dumps({"document": doc, "candidate": c, "features": facts(fit=fit, index=50.0)}) + "\n")
    rows = []
    for n, doc in enumerate(docs * 2):
        a, b = ("good", "weak") if n % 2 else ("weak", "good")
        rows.append({"comparison": f"cmp-{n}", "batch": "t", "document": doc, "a": {"candidate": a}, "b": {"candidate": b},
                     "preferred": "A" if a == "good" else "B", "confidence": "high", "reversed_repeat": False,
                     "reviewer_type": "ai"})
    data = tmp_path / "data.jsonl"
    data.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    split = tmp_path / "split.json"
    split.write_text(json.dumps({"families": {"f": ["d1", "d2"], "g": ["e1"]}, "evaluation_families": ["g"]}), encoding="utf-8")
    return str(data), str(tmp_path / "batches"), str(split)


class TestWeightsTrainer:
    def test_the_same_preflight_blocks_before_anything_is_written(self, tmp_path, trainer):
        data, batches, split = training_world(tmp_path)
        out = tmp_path / "w.json"
        with pytest.raises(SystemExit, match="preflight blocked"):
            trainer.main(["--kind", "weights", "--dataset", data, "--batches", batches, "--split", split, "--out", str(out)])
        assert not out.exists()

    def test_a_fixture_trains_and_its_gate_never_lets_it_load(self, tmp_path, trainer, monkeypatch):
        import tools.design_learning.reference_sampling as S
        monkeypatch.setattr(S, "audit", lambda *a, **k: {"ready": True, "issues": []})
        data, batches, split = training_world(tmp_path)
        out = tmp_path / "w.json"
        trainer.main(["--kind", "weights", "--dataset", data, "--batches", batches, "--split", split, "--out", str(out),
                      "--min-pairs", "2", "--synthetic-fixture"])
        rec = json.loads(out.read_text(encoding="utf-8"))
        assert rec["format"] == W.FORMAT and rec["features"] == W.FEATURES and rec["human_labels"] == 0
        assert rec["agreement"]["learned"] == 1.0 and "held_out_brier" in rec["calibration"]
        assert rec["gate"]["checks"]["not_a_fixture"] is False and rec["gate"]["passed"] is False
        assert rec["model_sha256"] == W.digest(rec["model"])
        with pytest.raises(VR.RankerRefused, match="gate"):
            W.WeightsRanker.load(str(out))

    def test_a_weights_model_is_one_json_file(self, tmp_path, trainer):
        with pytest.raises(SystemExit, match="json"):
            trainer.main(["--kind", "weights", "--dataset", "d", "--batches", "b", "--split", "s", "--out", "m.txt"])
