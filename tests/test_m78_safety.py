"""Page envelope, lossless bands, float geometry and content preservation (M7.8, batch 1)."""
import importlib.util
import io
import sys
from pathlib import Path

import pytest

from dynamic_pdf.core.content_ledger import build_content_ledger
from dynamic_pdf.core.normalize import normalize
from dynamic_pdf.intelligence.analysis import frame_geometry
from dynamic_pdf.intelligence.geometry import Geometry
from dynamic_pdf.intelligence.scoring import score_layout
from dynamic_pdf.layout.engine import LayoutEngine
from dynamic_pdf.layout.page_envelope import resolve_page_envelope
from dynamic_pdf.layout.page_system import BandContentUnfit, BandMaker, fill_fields
from dynamic_pdf.policy import RenderPolicy
from dynamic_pdf.qa.content_preservation import check_preservation
from dynamic_pdf.renderers.docx_renderer import render_docx
from dynamic_pdf.schema.media import resolve_placement
from dynamic_pdf.schema.page_system import Band, BandRow, PageSystem

_spec = importlib.util.spec_from_file_location(
    "m78_cases", Path(__file__).resolve().parents[1] / "benchmarks" / "m78" / "cases.py")
cases = importlib.util.module_from_spec(_spec)
sys.modules["m78_cases"] = cases
_spec.loader.exec_module(cases)

PERMISSIVE = RenderPolicy(error_mode="permissive")
STRICT = RenderPolicy(error_mode="strict")


@pytest.fixture(scope="module")
def a(tmp_path_factory):
    return cases.assets(tmp_path_factory.mktemp("assets"))


def prepared(a, name="executive_narrative"):
    return cases.make_case(name, a)._prepared_base()


def rendered(d, t, policy=None):
    geo = Geometry()
    out = io.BytesIO()
    LayoutEngine(d, theme=t, geometry=geo, policy=policy or PERMISSIVE).render(out)
    return geo, out.getvalue()


def floated(a, side="float_end", name="executive_narrative"):
    d, t = prepared(a, name)
    image = next(b for b in d.blocks if b.type == "image")
    image.placement = resolve_placement(side)
    image.placement.width_ratio = 0.42
    return d, t


class _Quiet:
    def warn(self, *a, **k):
        pass


def maker(t, system, rtl=False):
    return BandMaker(t, system, rtl, PERMISSIVE.assets, _Quiet(), {"title": "T"})


def items(layout):
    return [i for r in layout.rows for c in r.cells for i in c.items]


# ── page envelope ───────────────────────────────────────────────────────────────

def test_composer_frame_matches_the_renderer_with_bands(a):
    d, t = prepared(a, "arabic_dense_bands")
    geo, _ = rendered(d, t)
    frame = next(iter(geo.pages.values())).frame_height
    assert frame_geometry(d, t).height == pytest.approx(frame, abs=.02)
    assert frame == pytest.approx(670.39, abs=.02)


@pytest.mark.parametrize("name", cases.CASES)
def test_envelope_matches_the_renderer_for_every_case(a, name):
    d, t = prepared(a, name)
    env = resolve_page_envelope(d, t)
    geo, _ = rendered(d, t)
    assert env.height == pytest.approx(next(iter(geo.pages.values())).frame_height, abs=.02)


def test_envelope_without_a_page_system_keeps_the_theme_clearance(a):
    d, t = prepared(a)
    assert d.meta.page_system is None
    env = resolve_page_envelope(d, t)
    fg = frame_geometry(d, t)
    assert (env.width, env.height, env.left, env.bottom) == (fg.width, fg.height, fg.left, fg.bottom)


def test_docx_margins_come_from_the_same_envelope(a):
    import docx
    d, t = prepared(a, "arabic_dense_bands")
    env = resolve_page_envelope(d, t)
    section = docx.Document(io.BytesIO(render_docx(normalize(d), t)[0])).sections[0]
    assert section.top_margin.pt == pytest.approx(env.top, abs=1)
    assert section.bottom_margin.pt == pytest.approx(env.bottom, abs=1)


# ── bands ───────────────────────────────────────────────────────────────────────

def test_legacy_band_keeps_cutting_but_records_it(a):
    _, t = prepared(a)
    band = Band(rows=[BandRow(start=["First", "Second", "Third"], max_lines=1)])
    layout = maker(t, PageSystem(header=band)).layout(band, 480)
    assert [(x.kind, x.text) for x in layout.losses] == [("item_dropped", "Second"), ("item_dropped", "Third")]


def test_legacy_unknown_field_stays_blank():
    assert fill_fields("Code {typo_field}", {}) == "Code"


def test_lossless_band_moves_items_to_new_rows(a):
    _, t = prepared(a)
    band = Band(rows=[BandRow(start=["First", "Second", "Third"], max_lines=1)])
    layout = maker(t, PageSystem(header=band, lossless=True)).layout(band, 480)
    assert not layout.losses and layout.reflowed
    assert items(layout) == ["First", "Second", "Third"]


def test_lossless_band_keeps_reading_order_right_to_left(a):
    _, t = prepared(a)
    long_text = "مراجعة " * 30
    band = Band(rows=[BandRow(start=["أول"], center=["ثان"], end=[long_text],
                              max_lines=2)])
    layout = maker(t, PageSystem(header=band, lossless=True), rtl=True).layout(band, 300)
    assert items(layout)[:2] == ["أول", "ثان"]


def test_lossless_unknown_field_is_an_error(a):
    d, t = prepared(a)
    d.meta.page_system = PageSystem(header=Band(rows=[BandRow(start=["Code {typo_field}"])]), lossless=True)
    with pytest.raises(BandContentUnfit, match="typo_field"):
        rendered(d, t, STRICT)
    with pytest.raises(BandContentUnfit):
        render_docx(normalize(d), t, policy=STRICT)


def test_lossless_declared_optional_field_may_be_blank(a):
    d, t = prepared(a)
    d.meta.page_system = PageSystem(header=Band(rows=[BandRow(start=["Code {code}"])]), lossless=True,
                                    optional_fields=["code"])
    assert not resolve_page_envelope(d, t).band_losses


def test_lossless_text_that_cannot_fit_is_refused_not_cut(a):
    d, t = prepared(a)
    d.meta.page_system = PageSystem(header=Band(rows=[BandRow(start=["word " * 400], max_lines=1)]), lossless=True)
    assert {x.kind for x in resolve_page_envelope(d, t).band_losses} == {"ellipsis"}
    with pytest.raises(BandContentUnfit):
        rendered(d, t, STRICT)


def test_lossless_max_height_cannot_drop_a_row(a):
    d, t = prepared(a)
    band = Band(rows=[BandRow(start=["One"]), BandRow(start=["Two"]), BandRow(start=["Three"])], max_height=16)
    d.meta.page_system = PageSystem(header=band, lossless=True)
    assert "row_dropped" in {x.kind for x in resolve_page_envelope(d, t).band_losses}


def test_running_titles_are_measured_by_width_not_by_letter_count(a):
    d, t = prepared(a)
    heading = d.blocks[0]
    d.blocks.insert(0, heading.model_copy(update={"text": "W" * 110}))
    d.blocks.insert(0, heading.model_copy(update={"text": "i" * 130}))
    d.meta.page_system = PageSystem(header=Band(rows=[BandRow(start=["{section}"], max_lines=1)]), lossless=True)
    assert [x.kind for x in resolve_page_envelope(d, t).band_losses] == ["ellipsis"]


# ── geometry ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("side", ["float_start", "float_end"])
def test_float_image_and_its_paragraphs_are_placed(a, side):
    d, t = floated(a, side)
    geo, _ = rendered(d, t)
    assert not score_layout(geo, d, t).hard_errors
    assert {"figure", "caption"} <= {r.role for r in geo.regions if r.block == 2}
    assert {r.block for r in geo.regions} >= {3, 4}


def test_float_regions_sit_beside_each_other_not_as_one_rectangle(a):
    d, t = floated(a)
    geo, _ = rendered(d, t)
    figure = next(r for r in geo.regions if r.role == "figure")
    beside = [r for r in geo.regions if r.block == 3 and r.page == figure.page]
    assert beside and all(r.x1 <= figure.x0 + .5 or r.x0 >= figure.x1 - .5 for r in beside)


def test_float_text_split_across_pages_keeps_offsets(a):
    d, t = floated(a, name="near_page_end")
    i = next(i for i, b in enumerate(d.blocks) if b.type == "image")
    d.blocks[i + 1].text = " ".join([cases.EN] * 8)
    geo, _ = rendered(d, t)
    assert not score_layout(geo, d, t).hard_errors
    report = check_preservation(build_content_ledger(d, None, t), geometry=geo)
    assert report.status == "verified", report.to_dict()
    pieces = geo.fragments(i + 1)
    assert len(pieces) > 1 and all(x[2] == y[1] for x, y in zip(pieces, pieces[1:]))


def test_images_behind_the_flow_count_as_placed_but_not_as_density(a):
    d, t = prepared(a, "low_dpi")
    next(b for b in d.blocks if b.type == "image").placement = resolve_placement("behind_text")
    geo, _ = rendered(d, t)
    assert not [e for e in score_layout(geo, d, t).hard_errors if "not placed" in e]
    assert any(r.role == "decorative" for r in geo.regions)


# ── content ledger ──────────────────────────────────────────────────────────────

def test_ledger_ignores_layout_and_keeps_repeats(a):
    d, t = prepared(a)
    base = build_content_ledger(d, None, t)
    moved = d.model_copy(deep=True)
    moved.blocks[2].placement = resolve_placement("float_end")
    moved.blocks[2].width = 180
    moved_ledger = build_content_ledger(moved, None, t)
    assert base.fingerprint() == moved_ledger.fingerprint() and not base.diff(moved_ledger)
    assert base.strings().count(cases.EN) == 10


@pytest.mark.parametrize("change,word", [
    (lambda d: d.blocks.pop(), "lost"),
    (lambda d: d.blocks.append(d.blocks[-1]), "added"),
    (lambda d: d.blocks.__setitem__(slice(0, 2), [d.blocks[1], d.blocks[0]]), "reordered"),
    (lambda d: setattr(d.blocks[2], "caption", "Other"), "lost"),
    (lambda d: setattr(d.blocks[2], "alt_text", "Other"), "lost"),
])
def test_ledger_detects_loss_repeats_order_and_rewording(a, change, word):
    d, t = prepared(a)
    base = build_content_ledger(d, None, t)
    other = d.model_copy(deep=True)
    change(other)
    assert any(x.startswith(word) for x in base.diff(build_content_ledger(other, None, t)))


def test_ledger_keeps_diacritics_exact(a):
    d, t = prepared(a, "arabic_dense_bands")
    base = build_content_ledger(d, None, t)
    other = d.model_copy(deep=True)
    other.blocks[1].text = other.blocks[1].text.replace("َ", "")
    assert base.diff(build_content_ledger(other, None, t))


def test_ledger_tracks_asset_bytes_and_band_declarations(a):
    d, t = prepared(a, "arabic_dense_bands")
    base = build_content_ledger(d, None, t)
    assert "{title}" in base.bands and d.meta.title in base.band_texts
    swapped = d.model_copy(deep=True)
    next(b for b in swapped.blocks if b.type == "image").src = a["wide"]
    assert "changed: assets" in base.diff(build_content_ledger(swapped, None, t))


# ── preservation across artifacts ───────────────────────────────────────────────

@pytest.mark.parametrize("name", cases.CASES)
def test_rendered_artifacts_preserve_the_source(a, name):
    d, t = prepared(a, name)
    ledger = build_content_ledger(d, None, t)
    geo, pdf = rendered(d, t)
    report = check_preservation(ledger, candidate=ledger, geometry=geo, pdf=pdf,
                                docx=render_docx(normalize(d), t)[0])
    assert report.status != "failed", report.to_dict()
    assert report.layer("docx").status == "verified", report.to_dict()


def test_arabic_extraction_mismatch_is_unknown_not_a_pass(a):
    d, t = prepared(a, "arabic_dense_bands")
    _, pdf = rendered(d, t)
    altered = d.model_copy(deep=True)
    altered.blocks[1].text = "كلمة " * 40 + altered.blocks[1].text
    report = check_preservation(build_content_ledger(altered, None, t), pdf=pdf)
    assert report.layer("pdf").status == "unknown"


def test_lost_latin_words_fail_the_pdf_layer(a):
    d, t = prepared(a)
    _, pdf = rendered(d, t)
    altered = d.model_copy(deep=True)
    altered.blocks[1].text += " Zebrafish"
    assert check_preservation(build_content_ledger(altered, None, t), pdf=pdf).status == "failed"


def test_a_missing_or_repeated_paragraph_fails_the_docx_layer(a):
    d, t = prepared(a)
    base = render_docx(normalize(d), t)[0]
    longer = d.model_copy(deep=True)
    longer.blocks.append(longer.blocks[1].model_copy(update={"text": "A paragraph the DOCX never received."}))
    assert check_preservation(build_content_ledger(longer, None, t), docx=base).status == "failed"
    shorter = d.model_copy(deep=True)
    shorter.blocks.pop()
    assert check_preservation(build_content_ledger(shorter, None, t), docx=base).status == "failed"


def test_an_unplaced_block_fails_the_fragment_layer(a):
    d, t = prepared(a)
    geo, _ = rendered(d, t)
    geo.regions = [r for r in geo.regions if r.block != 2]
    report = check_preservation(build_content_ledger(d, None, t), geometry=geo)
    assert report.status == "failed" and "block 2" in report.layer("fragments").details[0]


def test_nothing_to_check_is_unknown(a):
    d, t = prepared(a)
    assert check_preservation(build_content_ledger(d, None, t)).status == "unknown"
