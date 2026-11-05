"""M7.9: art direction, design variants, refinement and the gates that guard them."""
import io
import zipfile

import pytest
from docx import Document as WordDocument
from PIL import Image

from dynamic_pdf import DocumentBuilder
from dynamic_pdf.design.art_direction import Adjust, content_changes, read_brief, select_directions
from dynamic_pdf.design.directions import DIRECTIONS
from dynamic_pdf.intelligence import variants as vmod
from dynamic_pdf.intelligence.variants import VariantBudget, _next_refinement, _title_on, _words
from dynamic_pdf.qa.visual_critique import HEURISTIC_LABEL, PageSignals, VisualCritique, critique_pdf

pymupdf = pytest.importorskip("pymupdf")

PARA = ("The harbour moved more freight this year than in any year since records began, "
        "and the new quay opened on time and within its approved budget of forty million. ")


@pytest.fixture(scope="module")
def photo(tmp_path_factory):
    path = tmp_path_factory.mktemp("m79") / "photo.png"
    img = Image.new("RGB", (1600, 1000), (40, 80, 110))
    img.paste((220, 190, 120), (1000, 200, 1300, 500))
    img.save(path)
    return str(path)


def report(photo=None, second=None):
    b = DocumentBuilder()
    b.meta(title="Harbour Annual Report 2025", author="Harbour Authority")
    b.heading("Chair's letter")
    b.paragraph(PARA * 3)
    b.paragraph(PARA * 2)
    b.heading("The year in numbers")
    b.paragraph(PARA)
    b.table(["Line", "2024", "2025"], [["Revenue", "41.2", "44.8"], ["Costs", "30.1", "31.6"]])
    b.heading("People and safety")
    b.paragraph(PARA * 3)
    if photo:
        b.image(photo, alt_text="The new quay at dusk", caption="The new quay")
    b.paragraph(PARA * 2)
    if second:
        b.heading("Environment")
        b.paragraph(PARA)
        b.image(second, alt_text="Sheds", caption="The sheds")
        b.paragraph(PARA)
        b.heading("Outlook")
        b.paragraph(PARA)
    b.heading("Appendix: governance")
    b.paragraph(PARA)
    return b


def arabic():
    b = DocumentBuilder()
    b.meta(title="التقرير السنوي لهيئة المياه ٢٠٢٥", language="ar")
    b.direction("rtl")
    text = "شهد عام ٢٠٢٥ تقدمًا ملموسًا في خدمات الهيئة، إذ اكتمل تحديث شبكة المياه في المنطقة الشرقية. "
    b.heading("كلمة رئيس مجلس الإدارة")
    b.paragraph(text * 3)
    b.heading("النتائج المالية")
    b.paragraph(text)
    b.table(["البند", "٢٠٢٤", "٢٠٢٥"], [["الإيرادات", "١٨٧٫٣", "٢١٤٫١"]])
    return b


@pytest.fixture(scope="module")
def result(photo):
    return report(photo).design_variants(n=3)


def fonts(pdf):
    with pymupdf.open(stream=pdf, filetype="pdf") as d:
        return {f[3].split("+")[-1] for p in d for f in p.get_fonts()}


# ── the public API ────────────────────────────────────────────────────────────

def test_three_valid_designs_and_a_transparent_recommendation(result):
    assert len(result) == 3 and len({v.id for v in result}) == 3
    assert all(v.valid and v.pdf and v.docx for v in result), [v.report.hard_failures for v in result]
    assert result.recommended in result.variants and not result.fallback
    said = " ".join(result.reasons)
    assert "no person has judged it" in said and "not chosen" in said


def test_designs_differ_in_more_than_colour(result):
    assert len({tuple(v.plan.rhythm()) for v in result}) == 3
    assert len({v.plan.bands for v in result}) >= 2
    assert len({frozenset(fonts(v.pdf)) for v in result}) >= 2


def test_a_longer_document_gets_different_covers(photo):
    b = report(photo)
    for title in ("Operations", "Finance", "Environment", "Outlook"):
        b.heading(title)
        b.paragraph(PARA * 8)
        b.paragraph(PARA * 8)
    got = b.design_variants(n=3)
    assert len({v.plan.cover for v in got}) >= 2, [v.plan.cover for v in got]


def test_each_design_records_its_plan(result):
    for v in result:
        plan = v.plan.explain()
        assert plan["direction"] == v.id and plan["sections"] and plan["typography"]
        assert v.report.heuristic_label == HEURISTIC_LABEL


def test_named_families_are_used_and_unknown_ones_refused(photo):
    got = report(photo).design_variants(families=["financial_data"])
    assert [v.id for v in got] == ["financial_data"]
    with pytest.raises(ValueError):
        report(photo).design_variants(families=["no_such_family"])
    with pytest.raises(ValueError):
        report(photo).design_variants(n=9)


def test_export_writes_files_and_decisions(result, tmp_path):
    paths = result.export(str(tmp_path))
    assert (tmp_path / "decisions.json").exists()
    for v in result:
        assert open(paths[v.id]["pdf"], "rb").read(4) == b"%PDF"
        assert paths[v.id]["docx"].endswith(".docx")


def test_default_output_is_untouched(photo):
    def text(b):
        with pymupdf.open(stream=b.render(), filetype="pdf") as d:
            return [p.get_text() for p in d]
    b = report(photo)
    before = text(b)
    b.design_variants(families=["editorial_modern"])
    assert text(b) == before


# ── choosing directions ───────────────────────────────────────────────────────

def _brief(builder):
    from dynamic_pdf.core.normalize import normalize
    sem = normalize(builder.build())
    return read_brief(sem, "report", 6)


def test_no_direction_is_hardwired_first():
    picks = {select_directions(_brief(report()), 1)[0][0].id, select_directions(_brief(arabic()), 1)[0][0].id}
    assert len(picks) == 2


def test_arabic_institutional_only_for_right_to_left_work():
    ltr = {d.id for d, *_ in select_directions(_brief(report()), len(DIRECTIONS))}
    rtl = {d.id for d, *_ in select_directions(_brief(arabic()), len(DIRECTIONS))}
    assert "arabic_institutional" not in ltr and "arabic_institutional" in rtl


def test_directions_do_not_number_right_to_left_headings():
    from dynamic_pdf.design.profile import Profile
    profile = next(iter(Profile))
    d = DIRECTIONS["corporate_conservative"]
    assert d.recipe(profile, False, 1.0).section_numbering
    assert not d.recipe(profile, True, 1.0).section_numbering


def test_short_documents_lose_the_contents_page():
    b = report()
    got = b.design_variants(families=["corporate_conservative"]).variants[0]
    assert not any(x.type == "table_of_contents" for x in got.document.blocks)


def test_author_contents_block_is_kept():
    b = report()
    b.table_of_contents()
    got = b.design_variants(families=["corporate_conservative"]).variants[0]
    assert any(x.type == "table_of_contents" for x in got.document.blocks)


# ── gates: a design that fails is rejected, not repaired ──────────────────────

def _spoil(monkeypatch, fn):
    real = vmod.direct

    def spoiled(*a, **k):
        made = real(*a, **k)
        fn(made.document)
        return made
    monkeypatch.setattr(vmod, "direct", spoiled)


def test_lost_text_rejects_the_design(monkeypatch):
    def drop(doc):
        i = next(i for i, b in enumerate(doc.blocks) if b.type == "paragraph" and "harbour" in b.text)
        del doc.blocks[i]
    _spoil(monkeypatch, drop)
    got = report().design_variants(families=["editorial_modern"])
    assert got.variants[0].report.status == "rejected" and got.recommended is None and got.fallback
    assert any("lost" in f for f in got.variants[0].report.hard_failures)


def test_altered_number_rejects_the_design(monkeypatch):
    def alter(doc):
        t = next(b for b in doc.blocks if b.type == "table")
        rows = t.rows
        rows[0][1] = "44.9" if rows[0][1] == "41.2" else "99.9"
    _spoil(monkeypatch, alter)
    got = report().design_variants(families=["financial_data"])
    assert got.variants[0].report.status == "rejected"


def test_invented_text_rejects_the_design(monkeypatch):
    def add(doc):
        b = next(b for b in doc.blocks if b.type == "paragraph")
        b.text += " Profits doubled."
    _spoil(monkeypatch, add)
    assert report().design_variants(families=["executive_premium"]).variants[0].report.status == "rejected"


def test_content_changes_passes_a_clean_design(result, photo):
    src = report(photo).build()
    for v in result:
        assert content_changes(src, v.document, v.theme) == []


def test_a_failing_docx_rejects_only_that_design(monkeypatch, photo):
    import dynamic_pdf.renderers.docx_renderer as R
    real = R.render_docx
    calls = []

    def flaky(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")
        return real(*a, **k)
    monkeypatch.setattr(R, "render_docx", flaky)
    got = report(photo).design_variants(families=["editorial_modern", "financial_data"])
    assert [v.report.status for v in got] == ["rejected", "valid"] and got.recommended.id == "financial_data"


# ── budget and refinement ─────────────────────────────────────────────────────

def test_render_budget_stops_the_batch(photo):
    got = report(photo).design_variants(n=3, budget=VariantBudget(max_renders=2, max_refinements=0))
    assert got.stats["renders"] <= 2
    assert any(v.report.status == "not_rendered" for v in got)


def test_zero_refinements_means_one_render_per_design(photo):
    got = report(photo).design_variants(families=["executive_premium"], budget=VariantBudget(max_refinements=0))
    assert got.variants[0].report.refinements == []


def _critique(*pages, observations=()):
    return VisualCritique(index=80, pages=list(pages), observations=list(observations))


def _page(n, words=200, ink=0.3, first="Body text here", tail=0.1):
    fields = dict(page=n, words=words, ink=ink, first_line=first, tail=tail)
    return PageSignals.model_construct(**fields)


def test_short_last_section_is_asked_to_follow_on():
    c = _critique(_page(1), _page(2, words=40, ink=0.07, first="4 Team"))
    step = _next_refinement(c, Adjust(), None, ["Team"], 2)
    assert "Team" in step[0].no_break and "last page" in step[1]


def test_short_last_page_then_tightens_spacing():
    c = _critique(_page(1), _page(2, words=40, ink=0.07, first="4 Team"))
    step = _next_refinement(c, Adjust(no_break=frozenset({"Team"})), None, ["Team"], 2)
    assert step[0].density < 1.0


def test_page_growth_drops_opening_pages_first():
    c = _critique(*[_page(i) for i in range(1, 9)])
    step = _next_refinement(c, Adjust(), None, [], 4)
    assert step[0].openers is False


def test_nothing_to_refine_returns_none():
    assert _next_refinement(_critique(_page(1), _page(2)), Adjust(), None, [], 2) is None


def test_arabic_display_title_matches_from_one_word():
    # display Arabic can extract a word per line, and in presentation forms
    assert _title_on("ﺍﻟﻤﻮﺍﺭﺩ", ["مشاريع البنية", "الموارد البشرية"]) == "الموارد البشرية"
    assert _title_on("Body text", ["Team"]) is None
    assert _title_on("", ["Team"]) is None


def test_words_ignore_reversal():
    assert _words("melborp") == _words("problem")


# ── visual critique says what it is ───────────────────────────────────────────

def test_critique_measures_pages_and_labels_itself(result):
    c = critique_pdf(result.variants[0].pdf)
    assert c.label == HEURISTIC_LABEL and "not a human" in c.label
    assert len(c.pages) == result.variants[0].report.pages


def test_intended_pages_are_not_reported_sparse():
    b = DocumentBuilder()
    b.paragraph("One line.")
    b.page_break()
    b.paragraph(PARA * 12)
    pdf = b.render()
    assert any(o.code == "sparse_page" and o.page == 1 for o in critique_pdf(pdf).observations)
    assert not any(o.page == 1 for o in critique_pdf(pdf, intended=[1]).observations)


# ── DOCX stays a document ─────────────────────────────────────────────────────

def _word(v):
    return WordDocument(io.BytesIO(v.docx))


def test_text_and_tables_stay_editable(result):
    for v in result:
        w = _word(v)
        assert any("harbour" in p.text for p in w.paragraphs)
        assert w.tables
        with zipfile.ZipFile(io.BytesIO(v.docx)) as z:
            media = [n for n in z.namelist() if n.startswith("word/media/")]
        assert len(media) <= 3                     # the author's pictures, never pages


def test_pdf_pages_are_not_rasterised(result):
    for v in result:
        with pymupdf.open(stream=v.pdf, filetype="pdf") as d:
            assert all(len(p.get_text().split()) > 3 for p in d)


def test_slab_headings_keep_their_band_in_a_style(photo):
    """LibreOffice ignored direct shading on our heading style and left white text on white."""
    v = report(photo).design_variants(families=["financial_data"]).variants[0]
    w = _word(v)
    bands = [s for s in w.styles if s.name.startswith("Heading 1 Band")]
    assert bands and bands[0].base_style.name == "Heading 1"
    assert bands[0].element.pPr.find("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}shd") is not None
    assert any(p.style.name.startswith("Heading 1 Band") for p in w.paragraphs)


def test_heading_after_a_float_clears_it(photo):
    """A float taller than its text must not pull the next heading up beside it."""
    b = DocumentBuilder()
    b.meta(title="Float")
    b.heading("Before")
    b.paragraph(PARA)
    b.image(photo, alt_text="Quay", placement="float_end")
    b.paragraph(PARA * 3)
    b.heading("After")
    b.paragraph(PARA)
    v = b.design_variants(families=["editorial_modern"]).variants[0]
    assert v.valid, v.report.hard_failures
    with zipfile.ZipFile(io.BytesIO(v.docx)) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    assert "<w:tblpPr" in xml and 'w:clear="all"' in xml
    assert [p.text.strip() for p in _word(v).paragraphs if p.text.strip() == "After"]


# ── shared QA learned about designed pages ────────────────────────────────────

def test_arabic_digit_runs_compare_up_to_reversal_only_in_the_pdf():
    from dynamic_pdf.qa.content_preservation import _either_way
    assert _either_way("٢٠٢٥") == _either_way("٥٢٠٢")
    assert _either_way("٢٠٢٥") != _either_way("٢٠٢٦")


def test_direction_ids_are_the_five_requested():
    assert set(DIRECTIONS) == {"corporate_conservative", "editorial_modern", "executive_premium",
                               "financial_data", "arabic_institutional"}
