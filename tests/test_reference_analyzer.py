"""tools/reference_analyzer: extraction, metadata, repeatability, corrupt files, scans,
Arabic/bilingual, spreads, duplicates, independence of related documents, isolation.
Every fixture is synthetic (sample_corpus.py): the defects found on real references
are reproduced here, never the references themselves."""
import hashlib
import json
import os
import subprocess
import sys

import pytest

pytest.importorskip("pymupdf")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from tools.reference_analyzer import sample_corpus  # noqa: E402
from tools.reference_analyzer.run import analyze, main  # noqa: E402

OUTPUTS = ("reference-catalog.json", "design-features.json", "design-patterns.json", "warnings.json",
           "analysis-report.html")


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    ref = tmp_path_factory.mktemp("refs")
    gt = sample_corpus.build(str(ref))
    (ref / "zero.pdf").write_bytes(b"")
    (ref / "garbage.pdf").write_bytes(b"not a pdf at all")
    out = tmp_path_factory.mktemp("out")
    res = analyze(str(ref), str(out), log=lambda s: None)
    return {"ref": ref, "out": out, "gt": gt, "res": res,
            "docs": {d["file"]: d for d in res["catalog"]["documents"]},
            "feat": {f["file"]: f for f in res["features"]}}


def _warn(corpus, file, code):
    return [w for w in corpus["res"]["warnings"] if w.get("file") == file and w["code"] == code]


def _raw(corpus, file, index):
    import pymupdf

    from tools.reference_analyzer.measure import extract_page
    with pymupdf.open(str(corpus["ref"] / file)) as doc:
        return extract_page(doc[index])


# ── measurements against ground truth ───────────────────────────────────

def test_known_geometry_matches_ground_truth(corpus):
    gt, f = corpus["gt"]["known_geometry.pdf"], corpus["feat"]["known_geometry.pdf"]
    s = f["summary"]
    assert s["body_size"]["value"] == gt["body_size"]
    assert abs(s["line_spacing_body"]["value"] - gt["line_height"]) <= 0.03
    mg = s["margins_body_median"]["value"]
    assert abs(mg["left"] - gt["margin_left"]) <= 1 and abs(mg["right"] - gt["margin_right"]) <= 1
    h = s["heading_hierarchy"]["value"]
    assert h[0]["size_pt"] == gt["h1_size"] and h[0]["level"] == 1 and h[0]["pages"] == [1, 2, 3]
    assert s["accent_colors"]["value"][0]["color"] == gt["accent"]
    assert s["rules"]["value"]["count"] == 3                       # table grid lines are not rules
    t = f["pages"][gt["table"]["page"] - 1]["tables"]["value"][0]
    assert (t["rows"], t["cols"]) == (gt["table"]["rows"], gt["table"]["cols"])
    assert t["column_widths_pt"] == [150.0, 100.0, 100.0, 101.3]
    assert t["banded_rows"] and t["header_fill"] and t["cell_padding_pt"]["left"] == gt["table"]["padding_left"]
    im = f["pages"][gt["image"]["page"] - 1]["images"]["value"][0]
    x0, y0, x1, y1 = im["bbox"]
    assert abs(x1 - x0 - gt["image"]["width"]) <= 1 and abs(y1 - y0 - gt["image"]["height"]) <= 1
    for pg in f["pages"]:
        assert pg["size"]["value"]["width_mm"] == 210.0 and pg["size"]["value"]["height_mm"] == 297.0


def test_every_value_states_unit_method_confidence_and_basis(corpus):
    for f in corpus["res"]["features"]:
        for k, v in f["summary"].items():
            assert set(v) == {"value", "unit", "method", "confidence", "basis"}, k
            assert v["confidence"] in ("high", "medium", "low") and v["basis"]
        for pg in f["pages"]:
            for k, v in pg.items():
                if isinstance(v, dict) and "value" in v:
                    assert v["method"] and v["confidence"] in ("high", "medium", "low"), k


def test_spreads_and_facing_pages(corpus):
    assert [s["page"] for s in corpus["feat"]["spread.pdf"]["summary"]["spreads"]["value"]] == [1, 2]
    w = _warn(corpus, "spread.pdf", "spread_detected")
    assert len(w) == 1 and w[0]["pages"] == [1, 2] and w[0]["page_count"] == 2       # one entry per code
    fp = corpus["feat"]["facing_pages.pdf"]["summary"]["facing_pages"]["value"]
    assert fp["odd"]["left"] == 90 and fp["odd"]["right"] == 50
    assert fp["even"]["left"] == 50 and fp["even"]["right"] == 90
    assert corpus["feat"]["known_geometry.pdf"]["summary"]["spreads"]["value"] == []


def test_arabic_and_bilingual_pages(corpus):
    ar = corpus["feat"]["arabic_report.pdf"]["summary"]
    assert ar["scripts"]["value"] == {"arabic_rtl": 2}
    assert set(ar["alignment"]["value"]) == {"rtl:right_or_justified"}
    assert {r["band"] for r in ar["running_elements"]["value"]} == {"top", "bottom"}
    assert _warn(corpus, "arabic_report.pdf", "arabic_presentation_forms")
    assert corpus["feat"]["bilingual.pdf"]["summary"]["scripts"]["value"] == {"bilingual": 1}


def test_scanned_page_has_no_text_layer(corpus):
    pg = corpus["feat"]["scanned.pdf"]["pages"][0]
    assert "no_text_layer_scanned" in pg["extraction"]["value"]
    assert pg["fonts"]["value"] == [] and _warn(corpus, "scanned.pdf", "no_text_layer_scanned")


# ── defects found on real references ────────────────────────────────────

def test_table_detection_keeps_the_layout_model_off():
    """PyMuPDF ≥2.1 gates find_tables with an ONNX model: tables vary with it and pages cost seconds."""
    import inspect

    from pymupdf import table

    from tools.reference_analyzer.measure import _table_finder_options
    has_option = "use_layout" in inspect.signature(table.find_tables).parameters
    assert _table_finder_options() == ({"use_layout": False} if has_option else {})


def test_running_elements_by_position_columns_and_leading(corpus):
    gt, f = corpus["gt"]["long_report.pdf"], corpus["feat"]["long_report.pdf"]
    s = f["summary"]
    assert abs(s["margins_body_median"]["value"]["top"] - (gt["margin_top"] - 9.7)) <= 2      # head excluded
    assert s["margins_body_median"]["value"]["bottom"] > 80                                   # footer excluded
    assert s["margins_body_median"]["value"]["left"] == gt["margin_left"]
    assert {r["band"] for r in s["running_elements"]["value"]} == {"top", "bottom"}
    assert s["columns"]["value"] == {str(gt["columns"]): gt["pages"]} or s["columns"]["value"] == {gt["columns"]: gt["pages"]}
    assert abs(s["line_spacing_body"]["value"] - gt["line_height"]) <= 0.03                   # 9.7 pt, body bin 9.5


def test_first_body_line_at_a_fixed_position_is_no_running_element(corpus):
    mg = corpus["feat"]["known_geometry.pdf"]["summary"]["margins_body_median"]["value"]
    assert abs(mg["top"] - 80) <= 3


def test_rotated_text_sets_no_margin(corpus):
    pg = corpus["feat"]["long_report.pdf"]["pages"][0]
    assert pg["margins_text"]["value"]["left"] == 40


def test_margins_are_never_negative_and_frame_ignores_short_pages(corpus):
    from tools.reference_analyzer.measure import classify_page
    raw = _raw(corpus, "known_geometry.pdf", 0)
    for b in raw["blocks"]:
        for ln in b["lines"]:
            ln["bbox"] = (-0.2, ln["bbox"][1], ln["bbox"][2], ln["bbox"][3])
    assert classify_page(raw, 10.0)["margins_text"]["value"]["left"] == 0
    s = corpus["feat"]["annual/northwind_annual_report_2023.pdf"]["summary"]
    assert s["margins_body_frame"]["value"]["bottom"] <= s["margins_body_median"]["value"]["bottom"]


def test_spread_sheets_with_a_footer_across_the_centre_are_measured_per_half(corpus):
    gt, s = corpus["gt"]["spread_sheets.pdf"], corpus["feat"]["spread_sheets.pdf"]["summary"]
    assert [x["page"] for x in s["spreads"]["value"]] == gt["spread_pages"]
    fp = s["facing_pages"]["value"]
    assert abs(fp["even"]["left"] - gt["outer"]) <= 1 and abs(fp["even"]["right"] - gt["inner"]) <= 1
    assert abs(fp["odd"]["left"] - gt["inner"]) <= 1 and abs(fp["odd"]["right"] - gt["outer"]) <= 1


def test_a4_landscape_pages_are_not_spreads(corpus):
    assert corpus["feat"]["landscape_slides.pdf"]["summary"]["spreads"]["value"] == []


def test_garbled_text_layer_is_not_reported_as_latin(corpus):
    pg = corpus["feat"]["garbled.pdf"]["pages"][0]
    assert pg["script"]["value"]["class"] == "undetermined" and pg["script"]["confidence"] == "low"
    assert _warn(corpus, "garbled.pdf", "broken_text_extraction")
    assert corpus["feat"]["known_geometry.pdf"]["pages"][0]["script"]["value"]["class"] == "latin_ltr"


def test_font_name_hints_the_script_of_a_garbled_page(corpus):
    from tools.reference_analyzer.measure import classify_page
    raw = _raw(corpus, "garbled.pdf", 0)
    for b in raw["blocks"]:
        for ln in b["lines"]:
            ln["font"] = "ABCDEF+TraditionalArabic"
            ln["spans"] = [("ABCDEF+TraditionalArabic", *sp[1:]) for sp in ln["spans"]]
    pg = classify_page(raw, 10.0)
    assert pg["script"]["value"]["font_hint"] == "arabic"
    assert {b["direction"] for b in pg["text_blocks"]["value"]} == {"rtl"}


def test_low_share_of_replacement_characters_is_flagged(corpus):
    from tools.reference_analyzer.measure import classify_page
    raw = _raw(corpus, "known_geometry.pdf", 0)
    assert "broken_text_extraction" not in classify_page(raw, 10.0)["extraction"]["value"]
    line = raw["blocks"][1]["lines"][0]
    line["text"] += "\ufffd" * 25
    assert "broken_text_extraction" in classify_page(raw, 10.0)["extraction"]["value"]


def test_image_tiles_are_one_placement(corpus):
    pg = corpus["feat"]["mixed_media.pdf"]["pages"][0]
    (im,) = pg["images"]["value"]
    assert im["fragments"] == 30 and [round(v) for v in im["bbox"]] == [100, 340, 460, 540]
    assert _warn(corpus, "mixed_media.pdf", "fragmented_images")


def test_photo_openers_are_not_scans_and_their_titles_are_display_type(corpus):
    f = corpus["feat"]["mixed_media.pdf"]
    assert "image_only_page" in f["pages"][1]["extraction"]["value"]
    assert not _warn(corpus, "mixed_media.pdf", "no_text_layer_scanned")
    s = f["summary"]
    assert [lv["size_pt"] for lv in s["heading_hierarchy"]["value"]] == [16.0]
    assert {d["size_pt"] for d in s["display_sizes"]["value"]} == {48.0, 40.0}


def test_caption_patterns_cite_the_pages_with_captions(corpus):
    from tools.reference_analyzer.patterns import build_patterns
    f = json.loads(json.dumps(corpus["feat"]["known_geometry.pdf"]))
    f["pages"][1]["images"]["value"] = [{"nearest_text": None}]
    f["pages"][2]["images"]["value"] = [{"nearest_text": {"position": "below", "smaller_than_body": True}}]
    f["summary"]["images"]["value"]["caption_below"] = 1
    (p,) = [c for c in build_patterns([f])["observations"] if c["id"] == "captions-below"]
    assert p["evidence"][0]["pages"] == [3]


def test_header_bands_have_no_caption(corpus):
    pg = corpus["feat"]["mixed_media.pdf"]["pages"][2]
    (im,) = pg["images"]["value"]
    assert im["placement"] == "band" and im["nearest_text"] is None
    assert corpus["feat"]["mixed_media.pdf"]["summary"]["images"]["value"]["caption_below"] == 0


def test_tables_boxes_padding_and_fills(corpus):
    f = corpus["feat"]["ruled_tables.pdf"]
    p1, p2 = f["pages"][0], f["pages"][1]
    (t,) = p1["tables"]["value"]                                     # the one-row box is not a table
    assert (t["rows"], t["cols"]) == (6, 3) and p1["ruled_boxes"]["value"] == 1
    assert abs(t["cell_padding_pt"]["left"] - corpus["gt"]["ruled_tables.pdf"]["padding"]) <= 1
    assert t["header_fill"] is None and not t["banded_rows"]        # thin filled rules are not row fills
    (t,) = p2["tables"]["value"]
    assert t["header_fill"] and t["banded_rows"]                     # filled cell by cell
    assert f["summary"]["tables"]["value"]["ruled_boxes"] == 1


def test_template_refills_count_once_and_compilations_not_at_all(corpus):
    assert _warn(corpus, "template_alpha.pdf", "possible_template_family")
    assert _warn(corpus, "template_gamma.pdf", "possible_template_family")
    assert corpus["docs"]["template_alpha.pdf"]["duplicates"] == []
    pats = corpus["res"]["patterns"]["recurring"] + corpus["res"]["patterns"]["observations"]
    small = [p for p in pats if p["id"] == "body-size-≤9.4 pt"][0]
    assert small["evidence_files"] == 2 and small["support_docs"] == 1
    assert _warn(corpus, "compilation.pdf", "mixed_design_system")
    s = corpus["feat"]["compilation.pdf"]["summary"]
    assert s["body_size"]["confidence"] == "low" and not s["design_uniformity"]["value"]["single_design"]
    assert [p for p in pats if p["id"] == "body-size-≥11.5 pt"][0]["support_docs"] == 0
    assert not _warn(corpus, "annual/northwind_annual_report_2023.pdf", "possible_template_family")


def test_paragraphs_split_into_one_block_per_line_are_rejoined():
    from tools.reference_analyzer.measure import _coalesce_line_blocks

    def block(y, x0=60, x1=500, size=10):
        ln = {"bbox": (x0, y - 9, x1, y + 2), "origin_y": y, "size": size}
        return {"bbox": ln["bbox"], "lines": [ln]}
    para = [block(100), block(115), block(130)]
    assert [b["baselines"] for b in _coalesce_line_blocks(para, 595)] == [3]
    assert len(_coalesce_line_blocks([block(100), block(130)], 595)) == 2            # paragraph gap
    assert len(_coalesce_line_blocks([block(100, 60, 120), block(115, 60, 120)], 595)) == 2   # narrow cells


# ── catalogue, metadata, duplicates ─────────────────────────────────────

def test_catalog_records_hash_pages_metadata_and_licence(corpus):
    d = corpus["docs"]["known_geometry.pdf"]
    assert d["sha256"] == hashlib.sha256((corpus["ref"] / "known_geometry.pdf").read_bytes()).hexdigest()
    assert d["page_count"] == 3 and d["pdf_metadata"]["title"] == "Known Geometry Reference"
    assert d["license"]["status"] == "CC0 (synthetic test file)"
    assert d["license"]["source"] == "05-Reviewed/known_geometry.json"
    assert d["provenance"]["source"] == "generated by sample_corpus.py"
    a = corpus["docs"]["annual/northwind_annual_report_2023.pdf"]
    assert a["license"]["status"] == "fictional sample — internal use"            # matched from CSV by filename
    s = corpus["docs"]["spread.pdf"]
    assert s["license"]["status"] == "unknown" and _warn(corpus, "spread.pdf", "license_unknown")
    assert all(not os.path.isabs(x["file"]) for x in corpus["res"]["catalog"]["documents"])


def test_reviewed_records_for_one_pdf_are_merged(corpus):
    """A features dump sorted first must not hide the rights index that describes the same bytes."""
    d = corpus["docs"]["facing_pages.pdf"]
    assert d["license"]["status"] == "study only"
    assert d["license"]["source"] == "05-Reviewed/rights-index.csv"
    assert d["license"]["evidence"] == "generated by sample_corpus.py"
    assert d["reviewed_metadata"]["files"] == ["05-Reviewed/observed-features.json", "05-Reviewed/rights-index.csv"]
    assert "sample text" not in json.dumps(d)                        # per-page text samples stay out
    assert not _warn(corpus, "facing_pages.pdf", "reviewed_page_count_mismatch")


def test_reviewed_records_never_match_other_bytes_or_folders(corpus):
    assert corpus["docs"]["spread.pdf"]["license"]["status"] == "unknown"
    assert _warn(corpus, "spread.pdf", "reviewed_sha256_mismatch")
    assert corpus["docs"]["scanned.pdf"]["license"]["status"] == "unknown"           # archive/scanned.pdf is another file
    assert _warn(corpus, "bilingual.pdf", "reviewed_page_count_mismatch")


def test_related_documents_remain_independent_records(corpus):
    """Same title and publisher, 12 vs 4 pages (like a full report and its summary edition)."""
    full = corpus["docs"]["annual/northwind_annual_report_2023.pdf"]
    summ = corpus["docs"]["annual/northwind_annual_report_2023_summary.pdf"]
    assert full["pdf_metadata"]["title"] == summ["pdf_metadata"]["title"]
    assert full["doc_id"] != summ["doc_id"] and full["sha256"] != summ["sha256"]
    assert (full["page_count"], summ["page_count"]) == (12, 4)
    assert full["duplicates"] == [] and summ["duplicates"] == []
    f1 = corpus["feat"]["annual/northwind_annual_report_2023.pdf"]
    f2 = corpus["feat"]["annual/northwind_annual_report_2023_summary.pdf"]
    assert len(f1["pages"]) == 12 and len(f2["pages"]) == 4
    assert f1["summary"]["body_size"]["value"] == 10.0 and f2["summary"]["body_size"]["value"] == 11.0


def test_exact_duplicates_are_kept_flagged_and_counted_once(corpus):
    a, b = corpus["docs"]["known_geometry.pdf"], corpus["docs"]["known_geometry_copy.pdf"]
    assert a["sha256"] == b["sha256"] and a["doc_id"] != b["doc_id"]
    assert a["duplicates"][0]["kind"] == "exact" and b["doc_id"] in a["duplicates"][0]["with"]
    assert _warn(corpus, "known_geometry_copy.pdf", "duplicate_exact")
    banded = [p for p in corpus["res"]["patterns"]["recurring"] + corpus["res"]["patterns"]["observations"]
              if p["id"] == "tables-banded"][0]
    assert banded["evidence_files"] == 2 and banded["support_docs"] == 1
    assert banded in corpus["res"]["patterns"]["observations"]       # one distinct document is not recurring


def test_unreadable_and_empty_files_do_not_stop_the_run(corpus):
    assert corpus["docs"]["zero.pdf"]["status"] == "unreadable"
    assert corpus["docs"]["garbage.pdf"]["status"] == "unreadable"
    assert corpus["docs"]["corrupt.pdf"]["status"] in ("unreadable", "empty")
    assert _warn(corpus, "garbage.pdf", "unreadable_pdf")
    analysed = {f["file"] for f in corpus["res"]["features"]}
    assert "garbage.pdf" not in analysed and "known_geometry.pdf" in analysed


def test_patterns_point_to_existing_pages_and_are_proposals(corpus):
    pages = {f["doc_id"]: len(f["pages"]) for f in corpus["res"]["features"]}
    pats = corpus["res"]["patterns"]
    assert pats["recurring"]
    for p in pats["recurring"] + pats["observations"]:
        assert p["basis"] == "inferred" and p["status"].startswith("proposal")
        assert (p in pats["recurring"]) == (p["support_docs"] >= pats["min_support_docs"])
        for e in p["evidence"]:
            assert all(1 <= n <= pages[e["doc_id"]] for n in e["pages"])
        assert "#" not in json.dumps(p["proposal"]) or p["category"] != "colour"   # no colour values proposed


# ── outputs, repeatability, isolation ───────────────────────────────────

def test_outputs_exist_and_report_is_offline(corpus):
    out = corpus["out"]
    for name in OUTPUTS:
        assert (out / name).exists(), name
    html = (out / "analysis-report.html").read_text(encoding="utf-8")
    assert "<script" not in html and "http://" not in html and "https://" not in html
    previews = [f for f in os.listdir(out / "previews") if f.endswith(".jpg")]
    assert previews and all(f'previews/{p}' in html for p in previews)


def test_repeatable_byte_identical_outputs(corpus, tmp_path):
    analyze(str(corpus["ref"]), str(tmp_path), log=lambda s: None)
    for name in OUTPUTS:
        assert (tmp_path / name).read_bytes() == (corpus["out"] / name).read_bytes(), name
    for p in os.listdir(corpus["out"] / "previews"):
        assert (tmp_path / "previews" / p).read_bytes() == (corpus["out"] / "previews" / p).read_bytes()


def test_cli_runs_without_network(corpus, tmp_path, monkeypatch, capsys):
    import socket
    attempts = []

    def deny(*a, **k):
        attempts.append(a)
        raise OSError("network disabled")
    monkeypatch.setattr(socket.socket, "connect", lambda self, *a, **k: deny(*a))
    monkeypatch.setattr(socket, "create_connection", deny)
    assert main(["analyze", "--input", str(corpus["ref"]), "--output", str(tmp_path), "--max-previews", "2"]) == 0
    assert attempts == [] and (tmp_path / "reference-catalog.json").exists()
    assert "PDF(s)" in capsys.readouterr().out


def test_tool_is_isolated_from_the_runtime_package():
    r = subprocess.run([sys.executable, "-c", "import sys, dynamic_pdf; from dynamic_pdf import DocumentBuilder;"
                        "DocumentBuilder().paragraph('x').render();"
                        "print(any(m == 'tools' or m.startswith('tools.') for m in sys.modules))"],
                       capture_output=True, text=True, cwd=ROOT)
    assert r.stdout.strip() == "False", r.stderr
    toml = open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8").read()
    assert 'include = ["dynamic_pdf*"]' in toml
    for dirpath, _, files in os.walk(os.path.join(ROOT, "dynamic_pdf")):
        for fn in files:
            if fn.endswith(".py"):
                src = open(os.path.join(dirpath, fn), encoding="utf-8").read()
                assert "reference_analyzer" not in src and "from tools" not in src, fn
