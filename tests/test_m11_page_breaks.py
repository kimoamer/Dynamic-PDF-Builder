"""M11: page breaks chosen by dynamic programming (``dynamic_pdf/layout/breaks.py``)."""
import io
import random

import pytest

from dynamic_pdf.layout.breaks import (Item, _options, _page_cost, natural_pages, plan_segment)

H = 100.0


def _brute(items, H, final, j=0, rem=None):
    """Cheapest (pages, badness) over every way to break, without memo."""
    n = len(items)
    if j >= n:
        return (0, 0.0)
    best = None
    for opt in _options(items, H, j, rem):
        sub = _brute(items, H, final, opt[0], opt[1])
        cand = (1 + sub[0], round(_page_cost(opt, n, H, final) + sub[1], 6))
        best = cand if best is None or cand < best else best
    return best


def _pages_of(plan, items):
    return [[i for i in range(p.start, p.end + (1 if p.split is not None else 0))] for p in plan.pages]


# ───────────────────────── dynamic programme on synthetic heights ─────────────────────────

def test_plan_is_natural_when_every_page_fills():
    items = [Item(30) for _ in range(9)]                 # 3 per page, nothing kept
    sp = plan_segment(items, H)
    assert [p.start for p in sp.pages] == [0, 3, 6]
    assert sp.page_starts == [] and sp.releases == []
    assert all(p.natural for p in sp.pages)


def test_near_empty_last_page_is_balanced_without_a_new_page():
    # natural: 3 + 3 + 1 item(s); the last page holds a fifth
    items = [Item(30) for _ in range(6)] + [Item(20)]
    assert natural_pages(items, H)[0] == 3
    sp = plan_segment(items, H)
    assert len(sp.pages) == 3
    assert sp.pages[-1].fill >= 1 / 3
    assert sp.page_starts, "an earlier break moves lines onto the last page"


def test_kept_table_pushed_to_the_next_page_is_released_to_fill_it():
    # a 70 pt table kept on one page follows 50 pt of text: natural leaves page 1 half empty
    items = [Item(50), Item(70, releasable=True, min_piece=20, kind="exhibit"), Item(60)]
    nat_pages = natural_pages(items, H)[0]
    sp = plan_segment(items, H)
    assert len(sp.pages) <= nat_pages
    assert sp.releases == [1]
    assert sp.pages[0].fill > 0.9


def test_a_lateral_move_is_planned_but_not_worth_a_render():
    # natural fills 0.95 / 0.65 / 0.5; the plan's 0.8 / 0.8 / 0.5 is smoother, but no page fact
    # (pages, underfilled, near-empty, parted lead-in) changes
    items = [Item(80), Item(15), Item(65), Item(50)]
    sp = plan_segment(items, H)
    assert sp.page_starts == [1] and sp.facts == sp.natural_facts and not sp.gain
    kept = plan_segment([Item(50), Item(70, releasable=True, min_piece=20, kind="exhibit"), Item(60)], H)
    assert kept.gain and kept.facts[1] < kept.natural_facts[1]


def test_a_heading_never_ends_a_page():
    rnd = random.Random(3)
    for _ in range(50):
        items = [Item(rnd.uniform(5, 45), keep_with_next=rnd.random() < 0.25, kind="heading")
                 if rnd.random() < 0.3 else Item(rnd.uniform(5, 60)) for _ in range(rnd.randint(3, 14))]
        sp = plan_segment(items, H)
        for p in sp.pages[:-1]:
            if p.split is None and p.end > p.start:
                last = items[p.end - 1]
                # only a keep chain that cannot fit anywhere may overflow, as in ReportLab
                assert not last.keep_with_next or natural_pages(items, H)[0] == len(sp.pages)


def test_never_more_pages_than_the_natural_layout_and_matches_brute_force():
    rnd = random.Random(11)
    for _ in range(120):
        items = []
        for _ in range(rnd.randint(1, 9)):
            kind = rnd.choice(["text", "heading", "exhibit", "list"])
            h = rnd.uniform(4, 80)
            items.append(Item(h, ink=h * rnd.uniform(0.7, 1.0), space_before=rnd.choice([0, 6, 12]),
                              space_after=rnd.choice([0, 4, 8]), splittable=kind in ("text", "list") and h > 30,
                              min_piece=min(h, 12), keep_with_next=kind == "heading",
                              releasable=kind == "exhibit" and rnd.random() < 0.5, kind=kind))
        final = rnd.random() < 0.7
        sp = plan_segment(items, H, final)
        assert len(sp.pages) <= sp.natural_pages
        assert (len(sp.pages), round(sp.badness, 6)) == _brute(items, H, final)
        assert sp.badness <= sp.natural_badness + 1e-5


def test_lead_in_stays_with_its_exhibit_when_it_costs_nothing():
    # text, text, lead-in, exhibit: natural ends page 1 after the lead-in
    items = [Item(35), Item(35), Item(20), Item(60, kind="exhibit"), Item(10)]
    sp = plan_segment(items, H)
    assert len(sp.pages) == natural_pages(items, H)[0]
    starts = [p.start for p in sp.pages]
    assert 3 not in starts or 2 in starts


def test_space_before_is_dropped_at_a_page_top_and_space_after_need_not_fit():
    # each item is 45 tall with 10 before and 10 after: two fit on a page only because the
    # first space before and the last space after are not counted
    items = [Item(40, space_before=10, space_after=10) for _ in range(4)]
    assert natural_pages(items, H)[0] == 2


# ───────────────────────── documents ─────────────────────────

def _kept_tables_doc():
    from dynamic_pdf import DocumentBuilder
    b = DocumentBuilder().meta(title="Field operations review")
    words = ("The field teams completed the scheduled inspections, logged every defect against its asset "
             "and closed the actions agreed at the previous review within the agreed time. ")
    for s in range(5):
        b.heading(f"Region {s + 1}", level=1)
        for _ in range(3 + s % 2):
            b.paragraph(words * 3)
        b.table(["Asset", "Inspections", "Defects", "Closed"],
                [[f"Asset {r}", str(10 + r), str(r % 4), str(r % 3)] for r in range(11)],
                caption=f"Inspections in region {s + 1}")
    return b


@pytest.fixture(scope="module")
def natural():
    """The designed document as it is without the optimizer."""
    import warnings
    import dynamic_pdf.layout.breaks as B
    warnings.simplefilter("ignore")
    real, B.plan_document = B.plan_document, lambda *a, **k: ([], [], "off")
    try:
        return _kept_tables_doc().design("auto")._prepared()
    finally:
        B.plan_document = real


def test_measured_heights_add_up():
    from dynamic_pdf.intelligence.analysis import measure_blocks
    from dynamic_pdf.themes import get_theme
    doc = _kept_tables_doc().build()
    for m in measure_blocks(doc, get_theme("claude"))[0]:
        assert m.height == pytest.approx(m.space_before + m.body + m.space_after, abs=0.01)
        assert m.ink <= m.height + 0.01


def test_optimizer_keeps_content_and_improves_verified_facts(natural):
    from dynamic_pdf.core.normalize import normalize
    from dynamic_pdf.layout.breaks import optimize_breaks, page_facts
    doc, theme = natural
    out, rep = optimize_breaks(doc, theme)
    assert rep.applied, rep.reason
    a, n = rep.after, rep.before
    assert a["pages"] <= n["pages"] and a["underfilled"] < n["underfilled"]
    assert a["near_empty_last"] <= n["near_empty_last"] and a["errors"] <= n["errors"]
    assert page_facts(out, theme) == rep.after          # deterministic
    # content is never touched: same text, same order
    assert normalize(out).all_text() == normalize(doc).all_text()
    assert out.model_dump(exclude={"blocks": {"__all__": {"hints"}}}) == doc.model_dump(
        exclude={"blocks": {"__all__": {"hints"}}})


def test_fallback_when_the_render_does_not_confirm_the_plan(monkeypatch):
    import dynamic_pdf.layout.breaks as B
    from dynamic_pdf.themes import get_theme
    doc = _kept_tables_doc().build()
    theme = get_theme("claude")
    monkeypatch.setattr(B, "plan_document", lambda *a, **k: ([3], [], ""))
    worse = iter([{"pages": 3, "underfilled": 0, "near_empty_last": 0, "separated": 0, "wasted": 0, "errors": 0},
                  {"pages": 4, "underfilled": 0, "near_empty_last": 0, "separated": 0, "wasted": 0, "errors": 0}])
    monkeypatch.setattr(B, "page_facts", lambda *a, **k: next(worse))
    out, rep = B.optimize_breaks(doc, theme)
    assert out is doc and not rep.applied and "did not confirm" in rep.reason


def test_design_applies_and_explains_page_breaks_only_when_verified():
    import warnings
    import dynamic_pdf.layout.breaks as B
    warnings.simplefilter("ignore")
    b = _kept_tables_doc().design("auto")
    doc, _ = b._prepared()
    hinted = [i for i, blk in enumerate(doc.blocks) if (blk.hints or {}).get("page_start")
              or (blk.type == "table" and not (blk.hints or {}).get("keep_together"))]
    log = [d.decision for d in b.last_design.layout.decisions if d.target == "pagination"]
    applied = [x for x in log if x.startswith("page breaks:")]
    assert bool(applied) == bool(hinted)
    pages_on = b.render() and b.last_render.page_count
    real = B.plan_document
    try:
        B.plan_document = lambda *a, **k: ([], [], "off")
        off = _kept_tables_doc().design("auto")
        off.render()
        pages_off = off.last_render.page_count
    finally:
        B.plan_document = real
    assert pages_on <= pages_off


def test_docx_takes_the_released_tables_but_not_the_pdf_page_starts():
    import docx
    from dynamic_pdf.core.normalize import normalize
    from dynamic_pdf.layout.breaks import with_breaks
    from dynamic_pdf.renderers.docx_renderer import render_docx
    from dynamic_pdf.themes import get_theme
    doc = _kept_tables_doc().build()
    table = next(i for i, blk in enumerate(doc.blocks) if blk.type == "table")
    para = next(i for i, blk in enumerate(doc.blocks) if blk.type == "paragraph" and i > 3)
    doc.blocks[table].hints = {"keep_together": True}

    def rows_kept(d):
        t = docx.Document(io.BytesIO(render_docx(normalize(d), get_theme("claude"))[0])).tables[0]
        return [all(p.paragraph_format.keep_with_next for p in r.cells[0].paragraphs) for r in t.rows]

    assert all(rows_kept(doc)[:-1])                       # kept: every row holds on to the next
    hinted = with_breaks(doc, [para], [table])
    assert not any(rows_kept(hinted)[1:-1])               # released: Word may split it
    d = docx.Document(io.BytesIO(render_docx(normalize(hinted), get_theme("claude"))[0]))
    assert not any(p.paragraph_format.page_break_before for p in d.paragraphs)


def test_composer_candidates_drop_page_breaks_planned_for_another_rhythm():
    from dynamic_pdf.intelligence.candidates import apply
    from dynamic_pdf.layout.breaks import with_breaks
    from dynamic_pdf.themes import get_theme
    doc = with_breaks(_kept_tables_doc().build(), [4], [])
    d, _, _ = apply("compact", doc, get_theme("claude"), 595.28, [])
    assert not any((b.hints or {}).get("page_start") for b in d.blocks)


def test_word_page_forecast_scales_heights_by_the_font_calibration():
    from dynamic_pdf.layout.word_fit import WORD_LINE_FACTOR, predict_word_pages, word_factor
    from dynamic_pdf.themes import get_theme
    theme = get_theme("claude")
    doc = _kept_tables_doc().build()
    assert word_factor(theme) == WORD_LINE_FACTOR.get(theme.typography.body_family, 1.0)
    pages = [predict_word_pages(doc, theme, factor=k) for k in (0.6, 1.0, 1.6)]
    assert pages[0] <= pages[1] <= pages[2] and pages[0] < pages[2]


def test_variants_take_page_breaks_as_a_refinement_within_their_budget(monkeypatch):
    import warnings
    import dynamic_pdf.layout.breaks as B
    from dynamic_pdf.intelligence.variants import VariantBudget
    warnings.simplefilter("ignore")
    calls = []

    def confirmed(doc, theme, policy=None, cache=None, natural=None):
        calls.append(natural is not None)
        facts, pdf, geo = B._render(doc, theme, policy)
        rep = B.BreakReport(applied=True, before=facts, after=facts, renders=1, rendered=(pdf, geo))
        return doc, rep

    monkeypatch.setattr(B, "optimize_breaks", confirmed)
    v = _kept_tables_doc().design_variants(families=["corporate_conservative"]).variants[0]
    assert calls == [True]                      # verified against the design's own render
    assert v.valid and any(s.startswith("kept: page breaks") for s in v.report.refinements)
    none = _kept_tables_doc().design_variants(families=["corporate_conservative"],
                                              budget=VariantBudget(max_refinements=0)).variants[0]
    assert len(calls) == 1 and none.report.refinements == [] and none.report.renders == 1


def test_refinement_renders_the_change_with_the_best_forecast(monkeypatch):
    from dynamic_pdf.design.art_direction import Adjust
    from dynamic_pdf.intelligence import variants as V
    run = V._Runner.__new__(V._Runner)
    run.base_pages, run.budget = 2, V.VariantBudget(max_forecasts=3)
    options = [(Adjust(density=0.9), "a"), (Adjust(exhibits=0.8), "b"), (Adjust(openers=False), "c")]
    monkeypatch.setattr(V, "_refinements", lambda *a: iter(options))

    def ranked(forecasts):
        got = iter(forecasts)
        monkeypatch.setattr(V._Runner, "_forecast", lambda self, d, adj, why: next(got))
        return run._ranked(None, [], None, Adjust(), None, [])[1]

    assert ranked([(1, 5), (0, 6), (0, 5)]) == "c"          # fewest faults, then fewest pages
    assert ranked([(0, 5), (0, 5), (0, 5)]) == "a"          # ties keep the ladder's order
    assert ranked([(1, 5), None]) == "a"                    # no forecast: the ladder stands
    monkeypatch.setattr(V, "_refinements", lambda *a: iter(options[:1]))
    assert ranked([]) == "a"                                # one change: nothing to forecast
    monkeypatch.setattr(V, "_refinements", lambda *a: iter(options))
    run.budget = V.VariantBudget()
    assert ranked([]) == "a"                                # default budget: the ladder, no forecast


def test_forecast_matches_the_render_on_a_plain_document(natural):
    from dynamic_pdf.layout.breaks import forecast, page_facts
    doc, theme = natural
    pages, fill = forecast(doc, theme)
    assert pages == page_facts(doc, theme)["pages"] and 0 < fill <= 1


def test_landscape_runs_are_left_alone_and_split_the_document_into_runs():
    from dynamic_pdf.layout.breaks import _items
    from dynamic_pdf.themes import get_theme
    doc = _kept_tables_doc().build()
    wide = next(i for i, blk in enumerate(doc.blocks) if blk.type == "table")
    doc.blocks[wide].hints = {"landscape": True}
    runs, _ = _items(doc, get_theme("claude"))
    where = {it.index: (k, frozen) for k, (items, _, frozen) in enumerate(runs) for it in items}
    last = len(doc.blocks) - 1
    assert where[wide][1]                         # the landscape run is frozen
    assert not where[last][1]                     # portrait pages after it are planned
    assert where[wide][0] != where[last][0]
