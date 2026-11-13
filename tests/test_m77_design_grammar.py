"""M7.7: the grammar is opt-in, traceable and safe, and the learning files stay apart."""
import json
import os
from dataclasses import replace

import pytest

from dynamic_pdf import DocumentBuilder
from dynamic_pdf.design import grammar as G
from dynamic_pdf.design.art_direction import DocumentBrief, SectionBrief
from dynamic_pdf.design.directions import DIRECTIONS, palette, page_system
from dynamic_pdf.intelligence import variant_ranker as VR
from tools.design_learning import pipeline as P
from tools.design_learning import preferences as A

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DOCS = os.path.join(ROOT, "docs", "m77-design-grammar")


def load(name):
    with open(os.path.join(DOCS, name), encoding="utf-8") as f:
        return json.load(f)


def brief(**k):
    base = dict(purpose="report", audience="general", profile="report", language="ltr", words=900, density="normal",
                estimated_pages=8, sections=[SectionBrief(title=str(i), role="narrative", words=200) for i in range(4)])
    return DocumentBrief(**{**base, **k})


def builder(title="Harbour review"):
    b = DocumentBuilder()
    b.meta(title=title)
    for i in range(3):
        b.heading(f"Part {i + 1}", level=1)
        b.paragraph("The north quay works finished in the spring and the tide gauges were replaced. " * 6)
    b.table(["Item", "2025", "2024"], [["Income", "12.4", "11.9"], ["Costs", "8.1", "7.7"]])
    return b


class TestDeliverables:
    def test_every_page_is_accounted_for(self):
        c = load("full-corpus-coverage.json")
        assert c["summary"]["pages"] == len(c["pages"]) == 1064
        assert c["summary"]["documents"] == 13 and c["summary"]["measured"] == 1064
        assert len({p["ref"] for p in c["pages"]}) == 1064
        assert all(p["ai_observation"]["depth"] != "measured_only" for p in c["pages"])

    def test_nobody_is_recorded_as_a_human_reviewer(self):
        c = load("full-corpus-coverage.json")
        assert c["summary"]["human_reviewed"] == 0
        assert not any(p["unverified"]["human_reviewed"] for p in c["pages"])

    def test_both_unilever_reports_stay_separate(self):
        docs = {d["doc_id"] for d in load("full-corpus-coverage.json")["documents"]}
        assert {"ref-0b2bf0ebc355", "ref-db25596332d2"} <= docs

    def test_each_rule_has_every_required_part(self):
        rules = load("design-grammar.json")["rules"]
        assert len(rules) >= 15
        for r in rules:
            for key in ("page_roles", "required_elements", "layout_constraints", "rtl_behavior", "evidence_pages",
                        "confidence", "failure_conditions", "safe_fallback"):
                assert r[key], (r["id"], key)
            assert all(c["source"] in ("measured", "ai_observation") for c in r["layout_constraints"])

    def test_catalog_reports_the_precision_sample(self):
        c = load("layout-family-catalog.json")
        assert c["precision"]["sampled"] == 80 and c["precision"]["agreed"] == 55

    def test_rules_the_engine_lacks_are_not_faked(self):
        g = load("design-grammar.json")
        for r in g["rules"]:
            if r.get("requires"):
                assert r["engine"] is None
                assert set(r["requires"]) <= set(g["unsupported_primitives"])

    def test_page_graphs_stay_out_of_the_repository(self):
        found = [os.path.join(d, f) for d, _, files in os.walk(DOCS) for f in files]
        assert not [f for f in found if f.endswith("page-composition-graphs.json")]
        # The only PDFs here are the fictional grammar demonstrations.
        pdfs = [f for f in found if f.lower().endswith(".pdf")]
        assert all(os.path.basename(os.path.dirname(f)) == "comparisons" and f.endswith(".grammar.pdf") for f in pdfs)


class TestLoading:
    def test_packaged_grammar_loads_with_an_ai_approval(self):
        g = G.load()
        assert len(g.rules) >= 5
        assert g.approval["reviewer_type"] == "ai" and g.approval["human_approved"] is False

    def test_the_packaged_file_holds_no_evidence(self):
        with open(G.PACKAGED, encoding="utf-8") as f:
            text = f.read()
        assert "ref-" not in text and "evidence_pages" not in text

    @pytest.mark.parametrize("change", [{"status": "ai_reviewed"}, {"approval": {}}, {"format": "other"}])
    def test_anything_unapproved_is_refused(self, tmp_path, change):
        with open(G.PACKAGED, encoding="utf-8") as f:
            data = json.load(f)
        path = tmp_path / "g.json"
        path.write_text(json.dumps({**data, **change}), encoding="utf-8")
        with pytest.raises(G.GrammarError):
            G.load(str(path))

    def test_an_unknown_direction_field_is_refused(self, tmp_path):
        with open(G.PACKAGED, encoding="utf-8") as f:
            data = json.load(f)
        data["rules"][0]["engine"]["direction"] = {"nonsense": 1}
        path = tmp_path / "g.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(G.GrammarError):
            G.load(str(path))

    def test_nothing_means_no_grammar(self):
        assert G.resolve(None) is None and G.resolve(False) is None


class TestOverlay:
    def test_one_rule_per_slot(self):
        d = DIRECTIONS["corporate_conservative"]
        _, used = G.overlay(G.load(), d, brief(photos=2, tables=1, metrics=1), "Title")
        slots = [next(r.slot for r in G.load().rules if r.id == u) for u in used]
        assert len(slots) == len(set(slots))

    def test_a_cover_rule_needing_a_photo_falls_to_the_next(self):
        _, used = G.overlay(G.load(), DIRECTIONS["corporate_conservative"], brief(photos=0), "Title")
        assert "cover.low_title_field" in used and "cover.photo_over_panel" not in used

    def test_a_long_title_skips_the_large_type_cover(self):
        _, used = G.overlay(G.load(), DIRECTIONS["executive_premium"], brief(), "T" * 90)
        assert "cover.low_title_field" not in used

    def test_short_documents_get_no_opening_pages(self):
        _, used = G.overlay(G.load(), DIRECTIONS["corporate_conservative"], brief(estimated_pages=3), "Title")
        assert "opener.edge_strip_page" not in used

    def test_named_rules_limit_the_overlay(self):
        d, used = G.overlay(G.load(), DIRECTIONS["corporate_conservative"], brief(tables=1), "T", ["table.current_period_ledger"])
        assert used == ["table.current_period_ledger"] and d.table == "ledger"

    def test_the_source_direction_is_untouched(self):
        d = DIRECTIONS["corporate_conservative"]
        before = replace(d)
        G.overlay(G.load(), d, brief(tables=1), "T")
        assert d == before


class TestBands:
    def args(self, rtl=False):
        d = replace(DIRECTIONS["financial_data"], bands="dual_filled")
        primary, accent = palette(d, None, None)
        return d, dict(company="Fund", logo=None, primary=primary, accent=accent, muted="#666666", rtl=rtl, has_title=True)

    def test_head_and_foot_are_filled_and_alternate(self):
        d, k = self.args()
        s = page_system(d, **k)
        assert s.header.rows[0].fill and s.footer.rows[0].fill and s.even_footer.rows[0].fill
        assert s.footer.rows[0].start != s.even_footer.rows[0].start

    def test_directions_do_not_reach_the_new_bands_by_themselves(self):
        assert all(d.bands != "dual_filled" for d in DIRECTIONS.values())


class TestDesignVariants:
    def test_without_grammar_nothing_is_reported_or_changed(self):
        b = builder()
        v = b.design_variants(n=1, families=["corporate_conservative"]).variants[0]
        assert v.report.grammar_rules == [] and v.report.grammar_version is None
        assert not [d for d in v.plan.decisions if d.startswith("grammar")]

    def test_rules_used_are_traced_in_the_result(self):
        b = builder()
        made = b.design_variants(n=1, families=["corporate_conservative"], grammar=True,
                                 grammar_rules=["table.current_period_ledger"])
        v = made.variants[0]
        assert v.report.grammar_rules == ["table.current_period_ledger"]
        assert any(d.startswith("grammar") for d in v.plan.decisions)
        assert v.report.grammar_version == G.load().version

    def test_a_rule_changes_the_page(self):
        b = builder()
        plain = b.design_variants(n=1, families=["editorial_modern"]).variants[0]
        used = b.design_variants(n=1, families=["editorial_modern"], grammar=True,
                                 grammar_rules=["table.current_period_ledger"]).variants[0]
        assert plain.valid and used.valid and plain.pdf != used.pdf

    def test_a_design_the_rule_breaks_falls_back(self, monkeypatch):
        from dynamic_pdf.intelligence import variants as V
        real = V._Runner.run

        def run(self, direction, fit, why):
            v = real(self, direction, fit, why)
            if direction.table == "ledger" and direction.id == "editorial_modern":
                v.report.status = "rejected"
            return v

        monkeypatch.setattr(V._Runner, "run", run)
        made = builder().design_variants(n=1, families=["editorial_modern"], grammar=True,
                                         grammar_rules=["table.current_period_ledger"])
        v = made.variants[0]
        assert v.valid and v.report.grammar_rules == []
        assert any("failed the hard gates" in o for o in v.report.observations)

    def test_selection_is_deterministic_by_default(self):
        made = builder().design_variants(n=1, families=["editorial_modern"])
        assert made.stats["selection"] == {"selector": "deterministic", "model": None}


class FakeVariant:
    def __init__(self, id, fit=1.0):
        from dynamic_pdf.intelligence.variants import VariantReport
        self.id, self.plan = id, None
        self.report = VariantReport(status="valid", fit=fit, pages=4)


class TestLearnedRanker:
    def test_a_missing_model_keeps_the_fixed_choice(self, tmp_path):
        a, b = FakeVariant("a"), FakeVariant("b")
        best, note = VR.choose([a, b], a, str(tmp_path / "none.txt"))
        assert best is a and note["selector"] == "deterministic" and "not found" in note["fallback_reason"]

    def test_design_variants_survives_a_missing_model(self, tmp_path):
        made = builder().design_variants(n=1, families=["editorial_modern"], ranker_model=str(tmp_path / "none.txt"))
        assert made.recommended is made.variants[0]
        assert made.stats["selection"]["selector"] == "deterministic"
        assert "fallback_reason" in made.stats["selection"]

    def write(self, tmp_path, **record):
        import hashlib
        model = tmp_path / "m.txt"
        model.write_text("tree\nversion=v4\n", encoding="utf-8")
        base = {"format": VR.MODEL_FORMAT, "features": VR.FEATURES, "gate": {"passed": True},
                "model_sha256": hashlib.sha256(model.read_bytes()).hexdigest()}
        (tmp_path / "m.json").write_text(json.dumps({**base, **record}), encoding="utf-8")
        return str(model)

    @pytest.mark.parametrize("record,reason", [({"gate": {"passed": False}}, "gate"), ({"model_sha256": "0"}, "match"),
                                               ({"features": ["x"]}, "features"), ({"format": "x"}, "format")])
    def test_a_model_without_a_clean_record_is_refused(self, tmp_path, record, reason):
        with pytest.raises(VR.RankerRefused, match=reason):
            VR.VariantRanker.load(self.write(tmp_path, **record))

    def test_no_record_no_model(self, tmp_path):
        model = tmp_path / "m.txt"
        model.write_text("tree\n", encoding="utf-8")
        with pytest.raises(VR.RankerRefused, match="training record"):
            VR.VariantRanker.load(str(model))

    def test_a_learned_choice_says_so(self):
        class Fake:
            record, digest = {"labels": "ai_preference_distillation"}, "abc"

            def scores(self, rows):
                return [0.2, 0.8]

        a, b = FakeVariant("a"), FakeVariant("b")
        best, note = VR.choose([a, b], a, "m.txt", loader=lambda p: Fake())
        assert best is b and note["selector"] == "learned" and note["deterministic_choice"] == "a"
        assert note["labels"] == "ai_preference_distillation"

    def test_a_crashing_model_never_stops_a_document(self):
        def boom(path):
            raise RuntimeError("bad")

        a = FakeVariant("a")
        best, note = VR.choose([a], a, "m.txt", loader=boom)
        assert best is a and note["selector"] == "deterministic"

    def test_features_cover_the_finished_design(self):
        f = VR.variant_features(FakeVariant("a"))
        assert set(f) == set(VR.FEATURES)


def answers(tmp_path, rows):
    p = tmp_path / "answers.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return str(p)


def batch(tmp_path):
    d = tmp_path / "b1"
    (d / "sheets").mkdir(parents=True)
    (d / "sheets" / "cmp-001.jpg").write_bytes(b"x")
    (d / "sheets" / "cmp-002.jpg").write_bytes(b"x")
    cands = [{"document": "doc", "document_hash": "h", "candidate": c, "pdf_sha256": c + "p", "docx_sha256": c + "d",
              "grammar_version": "1.0.0", "features": {}} for c in ("x", "y")]
    (d / "candidates.jsonl").write_text("\n".join(json.dumps(c) for c in cands), encoding="utf-8")
    key = [{"comparison": "cmp-001", "document": "doc", "a": "x", "b": "y", "reversed_repeat": False,
            "pages_shown": [4, 4], "pages_total": [4, 4], "shown_px": 300},
           {"comparison": "cmp-002", "document": "doc", "a": "y", "b": "x", "reversed_repeat": True,
            "pages_shown": [4, 4], "pages_total": [4, 4], "shown_px": 300}]
    (d / "key.json").write_text(json.dumps({"comparisons": key}), encoding="utf-8")
    return str(d)


class TestAIPreferences:
    good = {"comparison": "cmp-001", "preferred": "A", "confidence": "medium", "justification": "A4 carries the table better.",
            "pages": ["A4", "B4"], "criteria": {"tables": 1}}

    def record(self, tmp_path, rows):
        data = tmp_path / "ai.jsonl"
        A.record(batch(tmp_path), answers(tmp_path, rows), str(data), model="claude-opus-5-5", date="2026-11-05", method="blind")
        return data

    def test_rows_say_they_are_ai_work(self, tmp_path):
        row = json.loads(self.record(tmp_path, [self.good]).read_text(encoding="utf-8"))
        assert row["reviewer_type"] == "ai" and row["model"] == "claude-opus-5-5"
        assert row["a"]["pdf_sha256"] == "xp" and row["document_hash"] == "h" and row["grammar_version"] == "1.0.0"

    def test_a_comparison_without_a_sheet_cannot_be_recorded(self, tmp_path):
        with pytest.raises(SystemExit, match="no such sheet"):
            self.record(tmp_path, [{**self.good, "comparison": "cmp-009"}])

    def test_an_answer_needs_a_reason_and_pages(self, tmp_path):
        with pytest.raises(SystemExit, match="visual reason"):
            self.record(tmp_path, [{**self.good, "justification": ""}])

    def test_abstaining_is_allowed(self, tmp_path):
        row = {"comparison": "cmp-001", "preferred": "abstain", "confidence": "low"}
        assert "abstain" in self.record(tmp_path, [row]).read_text(encoding="utf-8")

    def test_reversed_repeat_detects_a_flip(self, tmp_path):
        data = self.record(tmp_path, [self.good, {**self.good, "comparison": "cmp-002", "preferred": "A"}])
        out = A.check(str(data))
        assert out["reversed_pairs"] == 1 and out["reversed_inconsistent"] == ["cmp-002"]

    def test_reversed_repeat_detects_agreement(self, tmp_path):
        data = self.record(tmp_path, [self.good, {**self.good, "comparison": "cmp-002", "preferred": "B"}])
        assert A.check(str(data))["reversed_consistent"] == 1

    def test_rows_not_marked_as_ai_are_rejected(self, tmp_path):
        data = self.record(tmp_path, [self.good])
        row = json.loads(data.read_text(encoding="utf-8"))
        data.write_text(json.dumps({**row, "reviewer_type": "human"}), encoding="utf-8")
        with pytest.raises(SystemExit):
            A.check(str(data))


class TestWorkflow:
    def config(self, tmp_path):
        ref = tmp_path / "refs"
        (ref / "00-Inbox").mkdir(parents=True)
        an = tmp_path / "analysis"
        an.mkdir()
        return {"reference_dir": str(ref), "inbox": str(ref / "00-Inbox"), "analysis_dir": str(an),
                "grammar_work": str(an / "grammar"), "grammar_approvals": str(tmp_path / "a.json"),
                "grammar_file": os.path.join(DOCS, "design-grammar.json")}

    def test_import_registers_once(self, tmp_path):
        p = self.config(tmp_path)
        (tmp_path / "refs" / "00-Inbox" / "x.pdf").write_bytes(b"%PDF-1.4 fictional")
        assert len(P.do_import(p)["imported"]) == 1
        again = P.do_import(p)
        assert again["imported"] == [] and len(again["skipped_repeats"]) == 1

    def test_ai_approval_must_name_a_model(self, tmp_path):
        with pytest.raises(SystemExit, match="model"):
            P.do_approve(self.config(tmp_path), ["all"], "ai", None, None)

    def test_human_approval_must_name_a_person(self, tmp_path):
        with pytest.raises(SystemExit, match="person"):
            P.do_approve(self.config(tmp_path), ["all"], "human", None, None)

    def test_a_rule_the_engine_cannot_use_cannot_be_approved(self, tmp_path):
        with pytest.raises(SystemExit, match="cannot approve"):
            P.do_approve(self.config(tmp_path), ["chart.caption_bar"], "ai", "m", None)

    def test_ai_approval_is_never_recorded_as_human(self, tmp_path):
        assert P.do_approve(self.config(tmp_path), ["all"], "ai", "m", None)["human_approved"] is False

    def test_committed_config_keeps_references_outside_the_repository(self):
        with open(os.path.join(ROOT, "config", "design-learning.json"), encoding="utf-8") as f:
            c = json.load(f)
        from tools.design_learning.pipeline import is_absolute, paths
        resolved = paths()
        for key in ("reference_dir", "inbox", "analysis_dir"):
            assert is_absolute(c[key])
            assert resolved[key] == c[key]          # never joined onto the repository root


class TestBlindReviewFindings:
    """Blind review of the seed batch found a cover that no gate saw. These keep it found."""

    @staticmethod
    def _pdf(dark_behind: bool) -> bytes:
        pymupdf = pytest.importorskip("pymupdf")
        doc = pymupdf.open()
        doc.new_page()
        page = doc.new_page()
        if dark_behind:
            page.draw_rect(pymupdf.Rect(40, 40, 400, 120), fill=(0.1, 0.2, 0.3), color=None)
        page.insert_text((60, 80), "Prepared by the Authority", color=(1, 1, 1), fontsize=14)
        return doc.tobytes()

    def test_white_type_on_a_white_page_is_a_spilled_cover(self):
        from dynamic_pdf.intelligence.variants import _cover_spilled
        assert _cover_spilled(self._pdf(False))

    def test_white_type_on_a_band_is_fine(self):
        from dynamic_pdf.intelligence.variants import _cover_spilled
        assert not _cover_spilled(self._pdf(True))

    def test_low_title_rule_stops_at_titles_that_fit(self):
        rule = next(r for r in G.load().rules if r.id == "cover.low_title_field")
        assert rule.when["max_title_chars"] <= 32

    def test_trainer_skips_superseded_designs(self, tmp_path):
        import importlib.util
        spec = importlib.util.spec_from_file_location("train_ranker", "scripts/train_variant_ranker.py")
        t = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(t)
        batch = tmp_path / "b1"
        batch.mkdir()
        (batch / "candidates.jsonl").write_text('{"document": "d", "candidate": "x"}\n{"document": "d", "candidate": "y"}\n', encoding="utf-8")
        (batch / "superseded.json").write_text('{"candidates": [{"document": "d", "candidate": "y"}]}', encoding="utf-8")
        assert set(t.load_candidates(str(tmp_path))) == {("b1", "d", "x")}

    def test_analyze_writes_the_atlas_where_the_graphs_read_it(self, monkeypatch, tmp_path):
        import tools.reference_analyzer.graphs as graphs
        import tools.reference_analyzer.run as run
        from tools.design_learning import pipeline
        calls = []
        monkeypatch.setattr(run, "main", lambda argv: calls.append(argv) or 0)
        monkeypatch.setattr(graphs, "build", lambda *a: {"documents": [], "pages": []})
        p = {"reference_dir": "refs", "analysis_dir": str(tmp_path / "a"), "grammar_work": str(tmp_path / "g")}
        pipeline.do_analyze(p)
        assert calls[1][0] == "atlas" and calls[1][-1] == os.path.join(p["analysis_dir"], "visual")


class TestWordSheets:
    def _batch(self, tmp_path):
        rows = [{"document": "doc", "candidate": c} for c in ("one", "two")]
        (tmp_path / "candidates.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
        return str(tmp_path)

    def test_word_source_reads_word_exports_and_keeps_its_own_key(self, tmp_path, monkeypatch):
        from tools.design_learning import preferences as P
        seen = []
        monkeypatch.setattr(P, "blind_sheet", lambda a, b, path: seen.extend([a, b]) or {})
        P.sheets(self._batch(tmp_path), pairs_per_doc=1, repeats=0, source="word")
        assert all(os.path.join("word", "doc__") in p for p in seen)
        assert (tmp_path / "key-word.json").exists() and not (tmp_path / "key.json").exists()
        assert (tmp_path / "sheets-word").is_dir()

    def test_word_check_adds_no_preference_rows(self):
        check = json.load(open("training/ai_preferences/batches/seed-001/word-check.json", encoding="utf-8"))
        assert check["reviewer_type"] == "ai" and "not a preference evaluation" in check["note"]
        rows = [line for line in open("training/ai_preferences/ai-preferences.jsonl", encoding="utf-8")
                if json.loads(line)["batch"] == "seed-001"]
        assert len(rows) == 36
