"""Automatic image placement: opt-in, bounded, and unable to change what a document says."""
import importlib.util
import io
import shutil
import sys
import zipfile
from pathlib import Path

import pytest
from PIL import Image
from pydantic import ValidationError

from dynamic_pdf import DocumentBuilder
from dynamic_pdf.core.content_ledger import build_content_ledger
from dynamic_pdf.core.normalize import block_text, normalize
from dynamic_pdf.design.media_planner import (MediaPlan, apply_media_plan, band_decision, locked_fields, plan_media,
                                              role_of)
from dynamic_pdf.design.media_policy import (ARCHETYPE_CAPABILITIES, COMPACT, FLOAT, FULL_WIDTH, media_policy_for)
from dynamic_pdf.design.recipes import EVIDENCE_RECIPES, RECIPES
from dynamic_pdf.design.profile import Profile
from dynamic_pdf.intelligence import AutoMediaOptions
from dynamic_pdf.intelligence.analysis import frame_geometry, measure_blocks, simulate
from dynamic_pdf.intelligence.composer import Composer
from dynamic_pdf.intelligence.geometry import Geometry, Region
from dynamic_pdf.intelligence.media_gate import image_legibility
from dynamic_pdf.layout.engine import LayoutEngine
from dynamic_pdf.layout.page_envelope import resolve_page_envelope
from dynamic_pdf.media import physical_side
from dynamic_pdf.policy import RenderPolicy
from dynamic_pdf.qa.placement_checks import check_placement
from dynamic_pdf.schema.media import ImageTreatment, resolve_placement
from dynamic_pdf.schema.media_intent import MediaIntent, NormalizedRect
from dynamic_pdf.schema.page_system import Band, BandRow, PageSystem

_spec = importlib.util.spec_from_file_location(
    "m78_cases", Path(__file__).resolve().parents[1] / "benchmarks" / "m78" / "cases.py")
cases = importlib.util.module_from_spec(_spec)
sys.modules["m78_cases"] = cases
_spec.loader.exec_module(cases)

AUTO = AutoMediaOptions(mode="auto")
ASSETS = RenderPolicy().assets


@pytest.fixture(scope="module")
def a(tmp_path_factory):
    return cases.assets(tmp_path_factory.mktemp("assets"))


def composed(a, name="executive_narrative", media=AUTO, **options):
    b = cases.make_case(name, a)
    b.compose("smart", media=media, **options)
    return b, b.render()


def plans(a, name="executive_narrative", options=AUTO, profile=None, edit=None):
    b = cases.make_case(name, a)
    d, t = b._prepared_base()
    if edit:
        edit(d)
    measures, fg = measure_blocks(d, t, None, {})
    positions = {}
    for r in simulate(measures, fg).regions:
        positions.setdefault(r.block, r)
    env = resolve_page_envelope(d, t)
    return d, t, plan_media(d, media_policy_for(profile or b.last_design.decision.profile.value), env, options,
                            ASSETS, positions, measures, "h")


def xml_parts(data):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return {n: z.read(n) for n in z.namelist() if n.startswith("word/") and n.endswith((".xml", ".rels"))}


def image_of(doc):
    return next(b for b in doc.blocks if b.type == "image")


# ── off means off ───────────────────────────────────────────────────────────────

def test_options_default_to_off():
    o = AutoMediaOptions()
    assert o.mode == "off" and o.targets == ("pdf",) and o.docx_validation == "libreoffice"
    assert not o.word_required and o.min_dpi == 110 and o.min_float_text_width_pt == 180
    assert o.max_media_candidates == 4 and o.max_docx_renders == 2 and o.lossless_bands


@pytest.mark.parametrize("bad", [{"targets": ("pdf", "pdf")}, {"targets": ()}, {"min_dpi": 0}, {"mode": "on"}])
def test_options_reject_bad_values(bad):
    with pytest.raises(ValidationError):
        AutoMediaOptions(**bad)


@pytest.mark.parametrize("name", cases.CASES)
def test_mode_off_changes_nothing(a, name):
    plain = cases.make_case(name, a)
    plain.compose("smart")
    off = cases.make_case(name, a)
    off.compose("smart", media=AutoMediaOptions())
    assert plain.render() == off.render() or _same_pages(plain.render(), off.render())
    assert xml_parts(plain.render_docx()) == xml_parts(off.render_docx())
    assert off.last_composition.media_decisions is None and off.last_composition.source_ledger is None
    assert all(not c.name.startswith("media:") for c in off.last_composition.candidates)


def _same_pages(x, y):
    import pymupdf
    with pymupdf.open(stream=x, filetype="pdf") as p, pymupdf.open(stream=y, filetype="pdf") as q:
        return [i.get_pixmap().samples for i in p] == [i.get_pixmap().samples for i in q]


def test_off_measures_no_images(a, monkeypatch):
    import dynamic_pdf.design.media_planner as planner
    monkeypatch.setattr(planner, "ingest", lambda *a: pytest.fail("off must not read images"))
    b = cases.make_case("executive_narrative", a)
    b.compose("smart")
    b.render()


# ── content and explicit choices ────────────────────────────────────────────────

def test_plans_leave_the_source_alone(a):
    d, t, found = plans(a)
    original, ledger = d.model_dump_json(), build_content_ledger(d, ASSETS, t)
    assert len(found) > 1
    for plan in found:
        assert not ledger.diff(build_content_ledger(apply_media_plan(d, plan), ASSETS, t))
    assert d.model_dump_json() == original


def test_intent_is_not_content():
    image = DocumentBuilder().image("x.png", caption="C", intent=MediaIntent(role="photo", anchor="note"))._blocks[-1]
    assert block_text(image) == ["C"]


def test_intent_is_the_last_image_argument():
    import inspect
    assert list(inspect.signature(DocumentBuilder.image).parameters)[-1] == "intent"


def test_rects_are_normalized():
    with pytest.raises(ValidationError):
        NormalizedRect(x0=0, y0=0, x1=1.2, y1=1)
    with pytest.raises(ValidationError):
        NormalizedRect(x0=.5, y0=0, x1=.2, y1=1)


def test_a_default_is_not_an_explicit_choice(a):
    assert locked_fields(DocumentBuilder().image("x.png")._blocks[-1]) == []
    assert locked_fields(DocumentBuilder().image("x.png", width=120)._blocks[-1]) == ["width"]


@pytest.mark.parametrize("field,value", [
    ("width", 180), ("height", 100), ("placement", resolve_placement("float_start")),
    ("treatment", ImageTreatment(fit="contain"))])
def test_explicit_choices_are_hard_constraints(a, field, value):
    d, _, found = plans(a, edit=lambda d: setattr(image_of(d), field, value))
    assert not found
    b = cases.make_case("executive_narrative", a)
    setattr(b._blocks[2], field, value)
    wanted = b._blocks[2].model_dump_json()
    b.compose("smart", media=AUTO)
    b.render()
    assert b._prepared()[0].blocks[2].model_dump_json() == wanted
    assert all(x["block"] != 2 or x["code"] == "explicit_locked"
               for x in b.last_composition.media_decisions) if b.last_composition.media_decisions else True


@pytest.mark.parametrize("role", ["chart", "screenshot", "diagram", "figure"])
def test_structural_images_never_float_or_crop(a, role):
    _, _, found = plans(a, edit=lambda d: setattr(image_of(d), "intent", MediaIntent(role=role)))
    assert found
    for plan in found:
        for d in plan.decisions:
            assert d.placement != "float_end" and d.fit == "contain"


def test_unknown_role_stays_inline_and_is_not_guessed_from_shape(a):
    _, _, found = plans(a, edit=lambda d: setattr(image_of(d), "intent", None))
    assert found and {d.placement for p in found for d in p.decisions} == {"inline"}
    assert role_of(DocumentBuilder().image("x.png")._blocks[-1]) == "unknown"


@pytest.mark.parametrize("role", ["logo", "signature", "decorative"])
def test_identity_images_stay_inline(a, role):
    _, _, found = plans(a, edit=lambda d: setattr(image_of(d), "intent", MediaIntent(role=role)))
    assert {d.placement for p in found for d in p.decisions} <= {"inline"}


def test_no_plan_ever_crops_or_goes_behind_text(a):
    for name in cases.CASES:
        d, _, found = plans(a, name)
        for plan in found:
            done = apply_media_plan(d, plan)
            for x in plan.decisions:
                block = done.blocks[x.block]
                assert block.treatment.fit == "contain" and block.placement.mode in ("inline", "floating")
                assert not block.placement.bleed


def test_width_respects_the_dpi_limit(a):
    _, _, found = plans(a, "low_dpi")
    assert found
    for plan in found:
        for d in plan.decisions:
            assert d.box[0] <= 90 * 72 / 110 + .01 and "dpi_limited" in d.reason_codes


def test_a_legibility_minimum_is_not_shrunk_to_please_the_dpi(a):
    _, _, found = plans(a, "low_dpi", edit=lambda d: setattr(
        image_of(d), "intent", MediaIntent(role="photo", min_display_width_pt=300)))
    assert not found


def test_screenshot_keeps_its_minimum_width(a):
    _, _, found = plans(a, "technical_figure")
    assert found and all(d.box[0] >= 350 for p in found for d in p.decisions)


def test_hero_and_supporting_images(a):
    def hero(d):
        image_of(d).intent = MediaIntent(role="photo", prominence="hero")
    def supporting(d):
        image_of(d).intent = MediaIntent(role="photo", prominence="supporting")
    assert COMPACT not in {p.style for p in plans(a, edit=hero)[2]}
    assert FULL_WIDTH not in {p.style for p in plans(a, edit=supporting)[2]}


def test_plans_are_deterministic(a):
    first = [p.to_dict() for p in plans(a)[2]]
    assert first == [p.to_dict() for p in plans(a)[2]]


# ── policy ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("profile", ["financial_report", "data_report", "technical_manual", "academic_report",
                                     "letter", "corporate_memo"])
def test_only_editorial_documents_float(profile):
    assert FLOAT not in media_policy_for(profile).styles


@pytest.mark.parametrize("profile", ["letter", "corporate_memo"])
def test_correspondence_stays_small(profile):
    assert media_policy_for(profile).styles == (COMPACT,)


def test_recipes_carry_their_policy():
    assert RECIPES[Profile.EXECUTIVE_REPORT].media_policy is media_policy_for("executive_report")
    assert "media_policy" not in RECIPES[Profile.EXECUTIVE_REPORT].model_dump()


def test_evidence_recipes_stay_inconclusive():
    assert {r.status for r in EVIDENCE_RECIPES.values()} == {"inconclusive"}


@pytest.mark.parametrize("name", ["statement_page", "editorial_sink", "image_slab_divider", "figure_matrix"])
def test_unbuilt_archetypes_are_unsupported(name):
    assert ARCHETYPE_CAPABILITIES[name].status == "unsupported"


def test_no_archetype_claims_approval():
    assert not any(c.human_approved or c.validated_word_builds for c in ARCHETYPE_CAPABILITIES.values())


# ── right to left ───────────────────────────────────────────────────────────────

def test_logical_end_is_the_left_in_rtl(a):
    assert physical_side("end", True) == "left" and physical_side("end", False) == "right"
    d, t, found = plans(a, "arabic_dense_bands")
    plan = next(p for p in found if p.style == "mix")
    assert plan.decisions[0].placement == "float_end" and plan.decisions[0].logical_side == "end"
    assert build_content_ledger(apply_media_plan(d, plan), ASSETS, t).strings() == \
        build_content_ledger(d, ASSETS, t).strings()


def test_arabic_float_lands_on_the_left(a):
    d, t, found = plans(a, "arabic_dense_bands")
    plan = next(p for p in found if p.style == "mix")
    done, geo = apply_media_plan(d, plan), Geometry()
    LayoutEngine(normalize(done), theme=t, geometry=geo).render(io.BytesIO())
    assert not check_placement(d, done, geo, plan, True)
    figure = next(r for r in geo.regions if r.role == "figure")
    assert figure.x0 == pytest.approx(geo.pages[figure.page].frame_x0, abs=8)


# ── the composer ────────────────────────────────────────────────────────────────

def test_clean_preflight_does_not_stop_the_search(a):
    b, _ = composed(a, "low_dpi")
    r = b.last_composition
    assert any(c.name.startswith("media:") and c.rendered for c in r.candidates)


def test_a_sound_plan_is_delivered_with_its_evidence(a):
    b, pdf = composed(a)
    r = b.last_composition
    assert r.strategy == "media:mix" and r.page_count == 2 and r.status == "ok"
    assert r.effective_policy_version and r.source_ledger and r.asset_hashes
    accepted = [x for x in r.media_decisions if x["status"] == "accepted"]
    assert len(accepted) == 1 and accepted[0]["decisions"][0]["reason_codes"]


def test_render_budget_covers_the_baseline(a):
    b, _ = composed(a, max_renders=2)
    assert sum(c.rendered for c in b.last_composition.candidates) == 2


def test_suggest_keeps_the_designed_output(a):
    designed = cases.make_case("executive_narrative", a)
    designed.compose("smart")
    wanted = designed.render()
    b, pdf = composed(a, media=AutoMediaOptions(mode="suggest"))
    r = b.last_composition
    assert r.strategy == designed.last_composition.strategy
    assert _same_pages(pdf, wanted)
    assert any(x["status"] == "suggested" for x in r.media_decisions)


def test_equal_scores_keep_the_baseline(a):
    b, _ = composed(a, "technical_figure")
    assert b.last_composition.strategy == "baseline"


def test_image_legibility_counts_in_the_decision(a):
    b, _ = composed(a, "low_dpi")
    c = next(x for x in b.last_composition.candidates if x.name == b.last_composition.strategy)
    assert c.metrics["image_legibility"] == 1.0 and c.metrics["adjusted"] > c.score


def test_legibility_uses_the_drawn_width(a):
    doc = DocumentBuilder()
    doc.image(a["tiny"], intent=MediaIntent(min_display_width_pt=200))
    block = doc._blocks[0]
    geo = Geometry()
    geo.regions.append(Region(1, "main", 700, 600, 0, 180, 0, "figure"))
    model = type("D", (), {"blocks": [block]})
    assert image_legibility(model, geo, ASSETS, 110) == pytest.approx(90 * 72 / 180 / 110, abs=.001)


def test_a_failing_gate_rejects_the_plan(a, monkeypatch):
    import dynamic_pdf.qa.placement_checks as checks
    monkeypatch.setattr(checks, "check_placement", lambda *a: ["block 2: the image overlaps text"])
    b, _ = composed(a)
    r = b.last_composition
    assert not r.strategy.startswith("media:")
    assert all("overlaps" in (c.rejected or "") for c in r.candidates if c.name.startswith("media:") and c.rendered)


def test_a_crashing_candidate_restores_the_baseline(a, monkeypatch):
    real = Composer._render

    def fault(self, doc, theme):
        if doc is not self_doc.get("base", doc):
            raise RuntimeError("injected candidate fault")
        self_doc.setdefault("base", doc)
        return real(self, doc, theme)
    self_doc = {}
    monkeypatch.setattr(Composer, "_render", fault)
    b, pdf = composed(a)
    assert pdf.startswith(b"%PDF") and b.last_composition.strategy == "baseline"
    assert b.last_composition.fallbacks


def test_a_broken_asset_is_not_hidden(a, tmp_path):
    bad = tmp_path / "broken.png"
    bad.write_bytes(b"not an image")
    b = DocumentBuilder()
    b.paragraph(cases.EN)
    b.image(str(bad), intent=MediaIntent(role="photo"))
    b.compose("smart", media=AUTO)
    with pytest.raises(Exception):
        b.render()


def test_placement_check_finds_overlap_and_the_wrong_side(a):
    d, t, found = plans(a)
    plan = next(p for p in found if p.style == "mix")
    done = apply_media_plan(d, plan)
    geo = Geometry()
    from dynamic_pdf.intelligence.geometry import PageInfo
    geo.pages[1] = PageInfo(1, "main", 780, 60, 60, 480)
    geo.regions += [Region(1, "main", 700, 500, 100, 280, 2, "figure", in_float=True),
                    Region(1, "main", 690, 600, 90, 300, 3, "body")]
    assert any("overlaps" in e for e in check_placement(d, done, geo, plan, False))
    geo.regions[1] = Region(1, "main", 690, 600, 300, 520, 3, "body")
    assert any("wrong side" in e for e in check_placement(d, done, geo, plan, False))
    assert not check_placement(d, done, geo, plan, True)


def test_placement_check_notices_an_image_outside_the_plan(a):
    d, _, found = plans(a)
    empty = MediaPlan("x", "x", "v", "h", [])
    changed = d.model_copy(deep=True)
    image_of(changed).width = 10
    assert check_placement(d, changed, Geometry(), empty, False)


# ── bands in the automatic path ─────────────────────────────────────────────────

def lossy(b):
    b.page_system(PageSystem(header=Band(rows=[BandRow(start=["First note", "Second note"], max_lines=1)])))
    return b


def test_bands_that_lose_text_are_reflowed_on_the_automatic_path(a):
    b = lossy(cases.make_case("executive_narrative", a))
    b.compose("smart", media=AUTO)
    b.render()
    r = b.last_composition
    assert r.band_decisions[0]["status"] == "reflowed"
    assert r.strategy.startswith("media:") and b._prepared()[0].meta.page_system.lossless


def test_bands_alone_are_reason_enough_for_a_plan(a):
    b = lossy(DocumentBuilder())
    b.paragraph(cases.EN)
    b.compose("smart", media=AUTO)
    b.render()
    assert b.last_composition.strategy == "media:bands"


def test_the_same_bands_keep_cutting_when_auto_is_off(a):
    b = lossy(cases.make_case("executive_narrative", a))
    b.compose("smart")
    b.render()
    assert b._prepared()[0].meta.page_system.lossless is False


def test_bands_that_cannot_fit_fail_rather_than_pass(a):
    b = cases.make_case("executive_narrative", a)
    b.page_system(PageSystem(header=Band(rows=[BandRow(start=["word " * 400], max_lines=1)])))
    b.compose("smart", media=AUTO)
    b.render()
    r = b.last_composition
    assert r.status == "failed" and r.fallback_reason == "band_content_unfit"
    assert not r.strategy.startswith("media:")


def test_band_decision_reports_nothing_without_a_system(a):
    d, t = cases.make_case("executive_narrative", a)._prepared_base()
    assert band_decision(d, t, None)["status"] == "none"


# ── formats ─────────────────────────────────────────────────────────────────────

def test_a_pdf_only_plan_leaves_the_docx_as_designed(a):
    designed = cases.make_case("executive_narrative", a)
    designed.compose("smart")
    b, _ = composed(a)
    assert b.last_composition.strategy == "media:mix"
    assert xml_parts(b.render_docx()) == xml_parts(designed.render_docx())


def test_structural_docx_is_labelled_structural_only(a):
    b, _ = composed(a, media=AutoMediaOptions(mode="auto", targets=("pdf", "docx"), docx_validation="structural"))
    r = b.last_composition
    assert r.strategy == "media:mix" and r.validation_by_format["docx"] == "structural_only"
    assert b"w:tblpPr" in xml_parts(b.render_docx())["word/document.xml"]      # text wraps a floating table


def test_without_libreoffice_the_candidate_is_not_approved(a, monkeypatch):
    import dynamic_pdf.qa.docx_checks as checks
    monkeypatch.setattr(checks, "docx_to_pdf", lambda *a, **k: None)
    b, _ = composed(a, media=AutoMediaOptions(mode="auto", targets=("pdf", "docx")))
    r = b.last_composition
    assert r.strategy == "editorial" and r.status == "unverified"
    assert r.validation_by_format["docx"] == "unverified" and "LibreOffice" in r.fallback_reason


def test_word_is_never_reported_as_passed(a):
    b, _ = composed(a, media=AutoMediaOptions(mode="auto", targets=("pdf", "docx"), docx_validation="structural",
                                              word_required=True))
    r = b.last_composition
    assert r.validation_by_format["word"] == "unverified" and not r.strategy.startswith("media:")
    assert r.status == "unverified"


def test_docx_budget_too_small_is_not_an_approval(a):
    b, _ = composed(a, media=AutoMediaOptions(mode="auto", targets=("pdf", "docx"), max_docx_renders=1))
    assert not b.last_composition.strategy.startswith("media:")
    assert b.last_composition.validation_by_format["docx"] == "unverified"


@pytest.mark.skipif(not (shutil.which("soffice") or shutil.which("libreoffice")), reason="needs LibreOffice")
def test_libreoffice_gate_compares_each_format_with_its_own_baseline(a):
    b, _ = composed(a, media=AutoMediaOptions(mode="auto", targets=("pdf", "docx")))
    assert b.last_composition.validation_by_format["docx"].startswith(("libreoffice", "unverified", "rejected"))


# ── cache ───────────────────────────────────────────────────────────────────────

def test_cache_notices_a_changed_file_at_the_same_path(a, tmp_path):
    path = tmp_path / "photo.png"
    shutil.copy(a["portrait"], path)
    b = cases.make_case("low_dpi", {**a, "tiny": str(path)})
    b.compose("smart", media=AUTO)
    b.render()
    first = b._composition[0]
    Image.new("RGB", (1200, 1500), "#123456").save(path)
    b.render()
    assert b._composition[0] != first


def test_without_media_the_cache_key_ignores_files(a):
    b = cases.make_case("low_dpi", a)
    b.compose("smart")
    assert b._media_cache_inputs(*b._prepared_base()) == ""


def test_core_does_not_reach_into_the_tools():
    root = Path(__file__).resolve().parents[1] / "dynamic_pdf"
    for name in ("design/media_planner.py", "design/media_policy.py", "intelligence/media_gate.py",
                 "qa/placement_checks.py", "qa/content_preservation.py", "core/content_ledger.py"):
        text = (root / name).read_text(encoding="utf-8")
        assert "reference_analyzer" not in text and "from tools" not in text


def test_frame_used_by_plans_is_the_rendered_one(a):
    d, t = cases.make_case("arabic_dense_bands", a)._prepared_base()
    assert frame_geometry(d, t).height == pytest.approx(resolve_page_envelope(d, t).height)
