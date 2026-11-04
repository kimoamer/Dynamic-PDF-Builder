"""tools/reference_analyzer: extraction, metadata, repeatability, corrupt files, scans,
Arabic/bilingual, spreads, duplicates, independence of related documents, isolation."""
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
