"""M13: the optional AI layer. Every model here is a fake; no request leaves the machine."""
import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

from dynamic_pdf import DocumentBuilder
from dynamic_pdf.ai import Critic, Director, Reply, ask, assist
from dynamic_pdf.ai.design import ADJUSTMENTS, DirectorReply, apply
from dynamic_pdf.design.art_direction import Adjust


class Fake:
    """A provider that answers from a script and remembers what it was asked."""

    def __init__(self, *replies, cache_dir=None, model="fake-model"):
        self.replies, self.calls, self.cache_dir, self.model = list(replies), [], cache_dir, model

    def complete(self, system, content, reply_model):
        self.calls.append({"system": system, "content": content, "schema": reply_model.__name__})
        r = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(r, Exception):
            raise r
        return r if isinstance(r, Reply) else Reply(json.dumps(r), self.model, "end_turn", {"input_tokens": 10, "output_tokens": 5})


def builder():
    b = DocumentBuilder()
    b.meta(title="Harbour review")
    for i in range(3):
        b.heading(f"Part {i + 1}", level=1)
        b.paragraph("The north quay works finished in the spring and the tide gauges were replaced. " * 6)
    b.table(["Item", "2025", "2024"], [["Income", "12.4", "11.9"], ["Costs", "8.1", "7.7"]])
    return b


def call(provider):
    return ask(provider, feature="t", context="brief", system="s", content=[{"type": "text", "text": "x"}],
               reply_model=DirectorReply, content_hash="c", facts={"f": 1})


class TestAsk:
    def test_a_valid_reply_is_used_and_names_the_model(self):
        reply, report = call(Fake({"directions": ["financial_data"]}))
        assert reply.directions == ["financial_data"]
        assert report["status"] == "ok" and report["model"] == "fake-model" and report["served_model"] == "fake-model"
        assert report["usage"] == {"input_tokens": 10, "output_tokens": 5} and "seconds" in report

    @pytest.mark.parametrize("answer,reason", [
        ({"directions": ["no_such_direction"]}, "invalid reply"),
        (Reply("not json", "fake-model"), "invalid reply"),
        (Reply("", "fake-model", "refusal"), "declined"),
        (RuntimeError("no network"), "request failed"),
    ])
    def test_anything_else_falls_back_and_says_why(self, answer, reason):
        reply, report = call(Fake(answer))
        assert reply is None and report["status"] == "fallback" and reason in report["reason"]

    def test_replies_are_cached_by_content_facts_prompt_and_model(self, tmp_path):
        fake = Fake({"directions": ["corporate_conservative"]}, cache_dir=str(tmp_path))
        first, a = call(fake)
        second, b = call(fake)
        assert len(fake.calls) == 1 and a["cache"] == "miss" and b["cache"] == "hit"
        assert first == second
        other = Fake({"directions": ["financial_data"]}, cache_dir=str(tmp_path), model="other-model")
        assert call(other)[0].directions == ["financial_data"]           # another model is another entry

    def test_an_unknown_context_is_refused(self):
        with pytest.raises(ValueError, match="context"):
            Director(Fake({}), context="everything")


class TestDirector:
    def test_it_ranks_directions_and_its_first_valid_design_is_recommended(self):
        fake = Fake({"directions": ["financial_data", "corporate_conservative"], "follow_on": ["Part 3", "Nope"],
                     "emphasis": "text", "reasons": ["tables lead"]})
        made = builder().design_variants(n=2, ai=Director(fake))
        assert [v.id for v in made.variants] == ["financial_data", "corporate_conservative"]
        assert made.recommended.id == "financial_data" and made.recommended.valid
        sel = made.stats["selection"]
        assert sel["selector"] == "ai" and sel["model"] == "fake-model" and "deterministic_choice" in sel
        report = made.stats["ai"]["director"]
        assert report["status"] == "ok" and report["intent"]["follow_on"] == ["Part 3"]
        assert any("Nope" in d for d in report["dropped"])
        assert "ranked first by fake-model" in " ".join(made.reasons)
        sent = json.loads(fake.calls[0]["content"][0]["text"])
        assert set(sent) >= {"brief", "allowed_directions"} and "text" not in sent    # brief context by default

    def test_a_failed_reply_keeps_the_fixed_selection(self):
        made = builder().design_variants(n=1, ai=Director(Fake(RuntimeError("no key"))))
        assert made.stats["selection"]["selector"] == "deterministic"
        assert made.stats["ai"]["director"]["status"] == "fallback"

    def test_directions_not_allowed_for_the_document_are_dropped(self):
        sem = builder().semantic()
        from dynamic_pdf.design.art_direction import read_brief, select_directions
        brief = read_brief(sem, "general", 3)
        ranked = select_directions(brief, 5)
        assert "arabic_institutional" not in [d.id for d, _, _ in ranked]
        order, adjust, report = Director(Fake({"directions": ["arabic_institutional"]})).choose(sem, brief, ranked)
        assert order is None and report["status"] == "fallback"
        order, adjust, report = Director(Fake({"directions": ["arabic_institutional", "financial_data"], "emphasis": "text"})
                                         ).choose(sem, brief, ranked)
        assert order[0] == "financial_data" and set(order) == {d.id for d, _, _ in ranked}
        assert adjust.exhibits < 1 and not adjust.hero_page

    def test_text_and_pages_contexts_send_more(self):
        sem = builder().semantic()
        from dynamic_pdf.design.art_direction import read_brief, select_directions
        brief = read_brief(sem, "general", 3)
        fake = Fake({"directions": ["financial_data"]})
        Director(fake, context="pages").choose(sem, brief, select_directions(brief, 5), plain_pdf=b"%PDF-1.4",
                                               request="for the board")
        content = fake.calls[0]["content"]
        assert content[0]["type"] == "document" and "document_text" in content[-1]["text"]
        assert json.loads(content[1]["text"])["caller_brief"] == "for the board"

    def test_a_brief_needs_a_director(self):
        with pytest.raises(ValueError, match="Director"):
            builder().design(brief="calm, for the board")
        with pytest.raises(ValueError, match="Director"):
            builder().design_variants(n=1, brief="calm")

    def test_design_hands_its_director_and_brief_to_design_variants(self):
        fake = Fake({"directions": ["corporate_conservative"]})
        b = builder().design(ai=Director(fake), brief="plain and calm")
        made = b.design_variants(n=1)
        assert made.recommended.id == "corporate_conservative"
        assert json.loads(fake.calls[0]["content"][0]["text"])["caller_brief"] == "plain and calm"


class TestCritic:
    def test_only_allowed_changes_and_known_sections_come_back(self):
        crit = SimpleNamespace(index=60.0, heuristics={}, pages=[], observations=[])
        fake = Fake({"issues": [{"page": 2, "kind": "sparse_page", "note": "half empty"}],
                     "adjustments": ["tighter_spacing"], "follow_on": ["Part 2", "Ghost"]})
        trial, note, report = Critic(fake).review(b"%PDF", crit, Adjust(), ["Part 1", "Part 2"], "corporate_conservative")
        assert trial.density == 0.9 and trial.no_break == {"Part 2"}
        assert note.startswith("critic: tighter_spacing") and report["issues"][0]["kind"] == "sparse_page"
        assert any("Ghost" in d for d in report["dropped"])
        assert fake.calls[0]["content"][0]["type"] == "document"

    def test_nothing_to_change_ends_the_rounds(self):
        crit = SimpleNamespace(index=60.0, heuristics={}, pages=[], observations=[])
        trial, _, report = Critic(Fake({"issues": [], "adjustments": []})).review(b"%PDF", crit, Adjust(), [], "x")
        assert trial is None and report["status"] == "ok"

    def test_rounds_are_bounded(self):
        with pytest.raises(ValueError):
            Critic(Fake({}), rounds=9)

    def test_a_critic_change_is_rendered_and_still_gated(self):
        fake = Fake({"issues": [], "adjustments": ["smaller_exhibits"]})
        made = builder().design_variants(n=1, families=["corporate_conservative"], critic=Critic(fake, rounds=2))
        v = made.variants[0]
        assert v.valid and v.report.hard_failures == []
        assert any(s.startswith(("kept: critic:", "undone: critic:")) for s in v.report.refinements)
        assert len(v.report.ai) == 2 and v.report.ai[0]["feature"] == "critic"
        assert made.stats["ai"]["critic"]["corporate_conservative"]

    def test_adjustments_stay_inside_the_ladder_bounds(self):
        a = Adjust()
        for _ in range(10):
            a = apply(a, list(ADJUSTMENTS), [])
        assert a.density >= 0.8 and a.exhibits >= 0.76


class TestAssist:
    def doc(self):
        b = builder()
        b._blocks.insert(1, b._blocks[0].__class__(text="Notes", level=3))      # a skipped level
        from dynamic_pdf.schema.blocks import ImageBlock
        b._blocks.append(ImageBlock(src="missing.png", caption="The quay"))
        b._blocks.append(ImageBlock(src="x.png", alt_text="Already described"))
        return b

    def test_alt_text_only_for_images_without_it_and_labelled(self):
        b = self.doc()
        before = b.build().model_dump_json()
        n = len(b._blocks)
        s = assist.alt_text(b, Fake({"items": [{"index": n - 2, "alt_text": "A quay at low tide"},
                                               {"index": n - 1, "alt_text": "overwrite?"}]}))
        assert s.label == "AI-written" and s.model == "fake-model"
        assert s.value == {n - 2: "A quay at low tide"}
        assert b.build().model_dump_json() == before                     # the author's document is untouched

    def test_metadata_and_summary(self):
        m = assist.metadata(builder(), Fake({"subject": "Harbour works", "keywords": ["quay", "tide"]}))
        assert m.value == {"subject": "Harbour works", "keywords": ["quay", "tide"]}
        s = assist.summary(builder(), Fake({"summary": "The quay reopened."}))
        block = s.as_block()
        assert block.text == "The quay reopened." and "AI-written" in block.title
        failed = assist.summary(builder(), Fake(Reply("", "fake-model", "refusal")))
        assert failed.value is None and failed.report["status"] == "fallback"
        with pytest.raises(ValueError):
            failed.as_block()

    def test_structure_repairs_come_as_a_diff_and_never_change_words(self):
        b = self.doc()
        s = assist.structure(b, Fake({"edits": [{"index": 1, "op": "set_heading_level", "level": 2},
                                                {"index": 0, "op": "paragraph_to_heading", "level": 1},
                                                {"index": 99, "op": "set_heading_level", "level": 1}]}))
        assert [e["index"] for e in s.value["edits"]] == [1] and len(s.report["dropped"]) == 2
        assert '-   "level": 3' in s.value["diff"] and '+   "level": 2' in s.value["diff"]
        assert b._blocks[1].level == 3 and s.value["document"].blocks[1].level == 2
        texts = lambda d: [getattr(x, "text", None) for x in d.blocks]                     # noqa: E731
        assert texts(s.value["document"]) == texts(b.build())


class TestAnthropicProvider:
    def test_requests_use_structured_outputs_and_the_model_setting(self):
        from dynamic_pdf.ai import DEFAULT_MODEL, AnthropicProvider
        sent = {}

        def create(**params):
            sent.update(params)
            return SimpleNamespace(content=[SimpleNamespace(type="text", text='{"directions": ["financial_data"]}')],
                                   model=params["model"], stop_reason="end_turn",
                                   usage=SimpleNamespace(input_tokens=3, output_tokens=4))

        client = SimpleNamespace(messages=SimpleNamespace(create=create))
        p = AnthropicProvider(client=client, cache_dir="")
        assert p.model == DEFAULT_MODEL
        reply, report = call(p)
        assert reply.directions == ["financial_data"] and report["model"] == DEFAULT_MODEL
        fmt = sent["output_config"]["format"]
        assert fmt["type"] == "json_schema" and fmt["schema"]["additionalProperties"] is False
        assert AnthropicProvider(model="another-model", client=client, cache_dir="").model == "another-model"


def test_the_package_and_default_rendering_never_import_the_ai_layer():
    code = ("import sys, dynamic_pdf\n"
            "b = dynamic_pdf.DocumentBuilder(); b.heading('A', 1); b.paragraph('Text.'); b.render()\n"
            "b.design('auto'); b.render()\n"
            "bad = [m for m in sys.modules if m == 'anthropic' or m.startswith(('anthropic.', 'dynamic_pdf.ai', 'mcp'))]\n"
            "assert not bad, bad\n")
    subprocess.run([sys.executable, "-c", code], check=True)


class TestAccept:
    def test_a_kept_design_is_recorded_as_human_signal(self, tmp_path):
        made = builder().design_variants(n=1, families=["corporate_conservative"])
        root = tmp_path / "training" / "human_preferences"
        row = made.accept("corporate_conservative", "A. Person", root=str(root), date="2026-11-16")
        saved = json.loads((root / "accepted.jsonl").read_text(encoding="utf-8"))
        assert saved == row and row["reviewer_type"] == "human" and row["accepted"]["candidate"] == "corporate_conservative"
        assert row["document_hash"] == made.stats["source_sha256"] and len(row["accepted"]["pdf_sha256"]) == 64
        with pytest.raises(ValueError, match="human_preferences"):
            made.accept("corporate_conservative", "A. Person", root=str(tmp_path / "ai_preferences"))
        with pytest.raises(ValueError, match="valid design"):
            made.accept("ghost", "A. Person", root=str(root))
        with pytest.raises(ValueError, match="name"):
            made.accept("corporate_conservative", " ", root=str(root))


class TestAgentSurface:
    DOC = {"meta": {"title": "T"}, "blocks": [{"type": "heading", "text": "One", "level": 1},
                                               {"type": "paragraph", "text": "Hello."}]}

    def test_cli_publishes_the_document_schema(self, tmp_path):
        out = tmp_path / "s.json"
        subprocess.run([sys.executable, "-m", "dynamic_pdf.cli", "schema", "-o", str(out)], check=True)
        s = json.loads(out.read_text(encoding="utf-8"))
        assert s["title"] == "Document" and "blocks" in s["properties"]

    def test_errors_name_the_field_and_a_fix(self):
        from dynamic_pdf.ai import mcp_server as M
        bad = {"meta": {"page_size": "B9"}, "blocks": [{"type": "heading", "text": "x", "level": 9}, {"type": "nope"},
                                                       {"type": "paragraph"}]}
        with pytest.raises(M.InputError) as e:
            M.explain(bad)
        msg = str(e.value)
        assert "meta.page_size" in msg and "use one of" in msg
        assert "blocks.0.heading.level" in msg and "at most 6" in msg
        assert "blocks.1" in msg and "known block type" in msg
        assert "blocks.2.paragraph.text" in msg and "add the required field 'text'" in msg

    def test_tools_write_only_inside_the_output_folder(self, tmp_path):
        from dynamic_pdf.ai import mcp_server as M
        res = M.render(self.DOC, "a.pdf", out_dir=str(tmp_path))
        assert res["pages"] == 1 and (tmp_path / "a.pdf").exists()
        for name in ("../a.pdf", "/tmp/a.pdf", "a.txt"):
            with pytest.raises(M.InputError, match="Fix"):
                M.render(self.DOC, name, out_dir=str(tmp_path))
        assert M.explain(self.DOC)["profile"]
        assert set(M.tools(str(tmp_path))) >= {"schema", "render", "variants", "explain"}
        assert ("lint" in M.tools(str(tmp_path))) == hasattr(DocumentBuilder, "lint")

    def test_the_server_lists_tools_and_returns_fixable_errors(self, tmp_path):
        pytest.importorskip("mcp")
        import asyncio

        from dynamic_pdf.ai import mcp_server as M
        server = M.build_server(str(tmp_path))

        async def go():
            names = {t.name for t in await server.list_tools()}
            with pytest.raises(Exception, match="at most 6"):
                await server.call_tool("render", {"document": {"blocks": [{"type": "heading", "text": "x", "level": 9}]}})
            return names
        assert asyncio.run(go()) >= {"schema", "render", "variants", "explain"}
