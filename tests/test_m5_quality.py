"""M5: regression tests for each confirmed layout/typography/QA defect."""
import re
import sys
import unicodedata
import pymupdf
from dynamic_pdf import DocumentBuilder, render_from_json
from dynamic_pdf.qa import check_pdf, check_docx
from conftest import fixture_text
from stress_docs import (arabic_long_report, bilingual_corporate, executive_proposal,
                         financial_complex, technical_manual)

AR = re.compile("[؀-ۿﭐ-﷿ﹰ-﻿]")


def _pdf(b):
    return pymupdf.open(stream=b.render(), filetype="pdf")


def _spans(doc, page=None):
    pages = [doc[page]] if page is not None else doc
    return [s for p in pages for bl in p.get_text("dict")["blocks"] for ln in bl.get("lines", [])
            for s in ln["spans"] if s["text"].strip()]


# ── whitespace / pagination ──────────────────────────────────────────────

def test_proposal_no_longer_spills_onto_a_near_empty_page():
    b = DocumentBuilder.from_markdown(fixture_text("proposal.md")).design()
    assert _pdf(b).page_count == 1
    assert any(d.startswith("pagination:") for d in b.design_explain()["layout"])


def test_heading_and_long_table_do_not_leave_a_gap():
    """ReportLab's KeepTogether used to push heading+caption+table to a new page."""
    b = DocumentBuilder().design("financial_report")
    b.heading("Statement").paragraph("Intro " * 120)
    b.table(["Item", "Value"], [[f"Line {i}", f"{i * 1000:,}"] for i in range(80)], caption="Ledger")
    doc = _pdf(b)
    first = next(i for i, p in enumerate(doc) if "Statement" in p.get_text())
    assert "Line 0" in doc[first].get_text() and "Ledger" in doc[first].get_text()


def test_financial_tables_flow_without_near_empty_pages():
    b = financial_complex().design()
    doc = _pdf(b)
    assert b.design_explain()["profile"] == "financial_report"
    assert doc.page_count <= 6
    rep = check_pdf(doc.tobytes())
    assert all(f >= 0.5 for f in rep.page_fill[1:-1]), rep.page_fill


def test_landscape_run_includes_its_heading_and_intro():
    headers = [f"Column header {i}" for i in range(11)]
    rows = [[f"value {r}-{c} lorem ipsum" for c in range(11)] for r in range(25)]
    b = (DocumentBuilder().heading("Data").paragraph("Intro text.").table(headers, rows)
         .heading("After").paragraph("Closing.").design("data_report"))
    doc = _pdf(b)
    page = next(p for p in doc if re.search(r"^(\d+\s+)?Data$", p.get_text(), re.M))
    assert page.rect.width > page.rect.height and "Intro text." in page.get_text()
    docx = __import__("docx").Document(__import__("io").BytesIO(b.render_docx()))
    first_land = next(i for i, s in enumerate(docx.sections) if s.page_width > s.page_height)
    assert first_land >= 0


def test_code_filename_stays_with_code(tmp_path):
    b = technical_manual(str(tmp_path)).design()
    for p in _pdf(b):
        t = p.get_text()
        if "server.toml" in t:
            assert "[server]" in t


def test_nested_ordered_lists_use_letters():
    t = _pdf(executive_proposal().design())[0].get_text()
    assert re.search(r"a\.\s+Source inventory", t) and re.search(r"b\.\s+Quality baseline", t)


# ── Arabic / bilingual typography ────────────────────────────────────────

def test_arabic_never_drawn_in_a_latin_font():
    for b in (bilingual_corporate().design(), arabic_long_report().design(),
              DocumentBuilder.from_markdown(fixture_text("bilingual.md")).design()):
        bad = [(s["font"], s["text"]) for s in _spans(_pdf(b)) if AR.search(s["text"])
               and not s["font"].startswith("Amiri")]
        assert not bad, bad[:3]


def test_bilingual_keeps_latin_face_and_first_strong_direction():
    b = bilingual_corporate().design()
    doc = _pdf(b)
    assert b.last_render.theme.typography.body_family == "Helvetica"
    assert b.design_explain()["direction"] == "ltr"
    label = next(s for s in _spans(doc, 2) if "Revenue" in s["text"] and "SAR" not in s["text"])
    assert label["bbox"][0] < 150                      # LTR label starts at the left edge


def test_rtl_header_and_toc_are_shaped_and_right_aligned():
    b = arabic_long_report().design()
    doc = _pdf(b)
    W = doc[1].rect.width
    header = [s for s in _spans(doc, 2) if s["bbox"][1] < 40 and AR.search(s["text"])]
    assert header and header[0]["font"].startswith("Amiri") and header[0]["bbox"][2] > W * 0.7
    toc = doc[1]
    assert "جدول المحتويات" in unicodedata.normalize("NFKC", toc.get_text())[::-1] or \
        "جدول" in unicodedata.normalize("NFKC", toc.get_text()) or "لودج" in unicodedata.normalize("NFKC", toc.get_text())
    entries = [s for s in _spans(doc, 1) if AR.search(s["text"]) and 120 < s["bbox"][1] < 700]
    assert entries and min(s["bbox"][2] for s in entries) > W * 0.6          # titles flush right
    nums = [s for s in _spans(doc, 1) if s["text"].strip().isdigit() and s["bbox"][1] > 120
            and s["bbox"][1] < 700]
    assert nums and max(s["bbox"][0] for s in nums) < W * 0.3                # numbers on the left
    assert len([l for l in toc.get_links() if l.get("kind") == 1]) >= 12


def test_metric_tiles_do_not_overlap_with_arabic_face():
    rep = check_pdf(bilingual_corporate().design().render())
    assert not [f for f in rep.findings if f.code == "overlap"]


# ── QA correctness ───────────────────────────────────────────────────────

def test_docx_qa_is_unverified_without_libreoffice(monkeypatch):
    import dynamic_pdf.qa.docx_checks as dc
    monkeypatch.setattr(dc.shutil, "which", lambda name: None)
    data = DocumentBuilder().heading("H").paragraph("p").render_docx()
    rep = check_docx(data, heading_texts=["H"])
    assert rep.status == "unverified" and not rep.passed and not rep.errors
    assert "UNVERIFIED" in rep.summary()


def test_export_status_reflects_qa(monkeypatch, tmp_path):
    import dynamic_pdf.qa.docx_checks as dc
    monkeypatch.setattr(dc.shutil, "which", lambda name: None)
    res = DocumentBuilder().heading("H").paragraph("p").export(str(tmp_path / "a.docx"), qa=True)
    assert res.status == "unverified"
    res = DocumentBuilder().quality("permissive").paragraph("Stars ★").export(str(tmp_path / "b.pdf"), qa=True)
    assert res.status == "failed"
    res = DocumentBuilder().paragraph("fine").export(str(tmp_path / "c.pdf"), qa=True)
    assert res.status == "ok"


def _synthetic(lines_per_page):
    doc = pymupdf.open()
    for lines in lines_per_page:
        p = doc.new_page(width=595, height=842)
        for i, (txt, size) in enumerate(lines):
            p.insert_text((72, 100 + i * 20), txt, fontsize=size)
    return doc.tobytes()


def test_detects_wasted_space_but_not_before_a_new_section():
    full = [("Body line", 11)] * 32
    wasted = _synthetic([full, [("Short page", 11)], full])
    assert "wasted_space" in [f.code for f in check_pdf(wasted).findings]
    section = _synthetic([full, [("Short page", 11)], [("Results", 16)] + full[:-1]])
    rep = check_pdf(section, major_headings=["Results"])
    assert "wasted_space" not in [f.code for f in rep.findings]


def test_detects_detached_caption():
    data = _synthetic([[("Body line", 11)] * 31 + [("Table 2: Regional revenue", 9)], [("Region Revenue", 11)]])
    rep = check_pdf(data, captions=["Table 2: Regional revenue"])
    assert "detached_caption" in [f.code for f in rep.errors]


def test_detects_low_density_and_oversized_heading():
    sparse = _synthetic([[("Body", 11)] * 30] + [[("Body", 11)] * 4] * 4 + [[("End", 11)]])
    assert "low_density" in [f.code for f in check_pdf(sparse).findings]
    big = _synthetic([[("Body", 11)] * 30, [("HUGE", 48), ("Body", 11)]])
    assert "oversized_heading" in [f.code for f in check_pdf(big, body_size=11).findings]


# ── design by default for new APIs, legacy preserved ────────────────────

def test_export_designs_by_default_and_legacy_render_does_not(tmp_path):
    md = fixture_text("executive.md")
    b = DocumentBuilder.from_markdown(md)
    res = b.export(str(tmp_path / "x.pdf"))
    assert res.profile == "executive_report"
    legacy = DocumentBuilder.from_markdown(md)
    legacy.render()
    assert legacy.last_design is None
    off = DocumentBuilder.from_markdown(md).design(None)
    assert off.export(str(tmp_path / "y.pdf")).profile is None


def test_explicit_theme_is_the_design_base(tmp_path):
    b = DocumentBuilder(theme="government").heading("Executive Summary").paragraph("x")
    b.export(str(tmp_path / "g.pdf"))
    assert b.last_render.theme.name.startswith("government")


def test_cli_designs_by_default_and_can_opt_out(tmp_path):
    import subprocess
    src = tmp_path / "in.md"
    src.write_text(fixture_text("proposal.md"), encoding="utf-8")
    for extra, pages in (([], 1), (["--design", "none"], None)):
        out = tmp_path / f"o{len(extra)}.pdf"
        r = subprocess.run([sys.executable, "-m", "dynamic_pdf.cli", "render", str(src), "-o", str(out)] + extra,
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        if pages:
            assert pymupdf.open(out).page_count == pages


def test_json_render_unchanged_legacy():
    res = render_from_json({"blocks": [{"type": "heading", "text": "H"}, {"type": "paragraph", "text": "p"}]})
    assert res["status"] == "ok"
