"""tools/reference_analyzer visual atlas: full page index, caching, composition labels, RTL,
spreads, the diverse shortlist and human decisions. Every fixture is synthetic
(sample_corpus.build_visual): the real references never enter the repository."""
import http.client
import json
import os
import shutil
import sys
import threading

import pytest

pytest.importorskip("pymupdf")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from tools.reference_analyzer import atlas, curation, sample_corpus, visual  # noqa: E402
from tools.reference_analyzer.run import main  # noqa: E402

KNOWN = "known_compositions.pdf"


def quiet(_):
    pass


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    ref = tmp_path_factory.mktemp("visual_refs")
    sample_corpus.build_visual(str(ref))
    (ref / "unreadable.pdf").write_bytes(b"not a pdf at all")
    out = tmp_path_factory.mktemp("visual_out")
    res = atlas.build(str(ref), str(out), target=30, log=quiet)
    pages = {(p["file"], p["page"]): p for p in res["index"]["pages"]}
    return {"ref": ref, "out": out, "res": res, "pages": pages, "index": res["index"], "short": res["shortlist"]}


def labels(page):
    return {x["label"] for x in page["labels"]}


def decision(page, sha, **kw):
    return {"sha256": sha, "page": page, "file": "x.pdf", "decision": None, "pinned": False, "ratings": {}, "notes": "",
            "reviewer": "Test Reviewer", "updated_at": "2026-01-01T00:00:00Z", **kw}


def curated(*ds):
    return {**curation.empty(), "decisions": list(ds)}


def sha_of(corpus, file=KNOWN):
    return corpus["pages"][(file, 1)]["sha256"]


# ── full index ──────────────────────────────────────────────────────────

def test_every_page_is_indexed_or_an_explicit_error(corpus):
    idx = corpus["index"]
    readable = [d for d in idx["documents"] if d["status"] == "ok"]
    assert sum(d["pages"] for d in readable) == len(idx["pages"]) == 16 + 6 + 60 + 4 + len(
        [k for k in corpus["pages"] if k[0] in ("arabic_report.pdf", "bilingual.pdf")])
    assert [e["file"] for e in idx["errors"]] == ["unreadable.pdf"]
    assert all(g["passed"] for g in idx["gates"]), idx["gates"]


def test_a_page_that_fails_is_recorded_not_dropped(corpus, tmp_path, monkeypatch):
    ref = tmp_path / "ref"
    ref.mkdir()
    shutil.copy(corpus["ref"] / KNOWN, ref / KNOWN)
    real, calls = atlas.raster_features, []

    def flaky(im):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("bad page")
        return real(im)
    monkeypatch.setattr(atlas, "raster_features", flaky)
    res = atlas.build(str(ref), str(tmp_path / "out"), target=5, log=quiet)
    idx = res["index"]
    assert [(e["page"], "bad page" in e["error"]) for e in idx["errors"]] == [(2, True)]
    assert len(idx["pages"]) == 15
    assert idx["gates"][0]["passed"]


def test_gate_fails_when_a_page_goes_missing():
    doc = {"sha256": "a" * 64, "status": "ok", "page_count": 2}
    page = {"sha256": "a" * 64, "page": 1}
    short = {"entries": [page]}
    assert not atlas.gates([doc], [page], [], short)[0]["passed"]


def test_related_documents_stay_separate(corpus):
    full, extract = sha_of(corpus), sha_of(corpus, "known_compositions_extract.pdf")
    assert full != extract
    assert len([p for p in corpus["index"]["pages"] if p["sha256"] == extract]) == 6
    assert len([p for p in corpus["index"]["pages"] if p["sha256"] == full]) == 16
    files = {e["file"] for e in corpus["short"]["entries"]}
    assert {KNOWN, "known_compositions_extract.pdf"} <= files


def test_an_exact_copy_is_indexed_once_and_reported(corpus, tmp_path):
    ref = tmp_path / "ref"
    ref.mkdir()
    shutil.copy(corpus["ref"] / "bilingual.pdf", ref / "a.pdf")
    shutil.copy(corpus["ref"] / "bilingual.pdf", ref / "b.pdf")
    idx = atlas.build(str(ref), str(tmp_path / "out"), target=2, log=quiet)["index"]
    assert {p["file"] for p in idx["pages"]} == {"a.pdf"}
    assert [d["exact_copy_of"] for d in idx["documents"]] == [None, "a.pdf"]
    assert all(g["passed"] for g in idx["gates"]), idx["gates"]


def test_index_keeps_measurements_and_never_the_text(corpus):
    raw = json.dumps(corpus["index"])
    assert "distribution network" not in raw and "Quarterly results" not in raw
    assert "Harbour Review" not in raw


def test_images_exist_and_stay_clean_of_overlays(corpus):
    base = corpus["out"] / "visual-atlas"
    for p in corpus["index"]["pages"]:
        assert (base / p["thumb"]).exists() and (base / p["image"]).exists()
    page = corpus["pages"][(KNOWN, 2)]
    from PIL import Image
    with Image.open(base / page["image"]) as im:
        magenta = [c for n, c in im.convert("RGB").getcolors(1 << 24) if c[0] > 180 and c[1] < 60 and c[2] > 90]
    assert not magenta
    overlay = (base / "data" / f"overlay-{page['sha256'][:12]}.js").read_text(encoding="utf-8")
    assert overlay.startswith("ATLAS_OVERLAYS[") and '"text"' in overlay


def test_gallery_is_offline_and_starts_clean(corpus):
    html = (corpus["out"] / "visual-atlas" / "index.html").read_text(encoding="utf-8")
    assert "http://" not in html and "https://" not in html
    assert 'id="overlays" aria-pressed="false"' in html
    assert 'loading="lazy"' in html and "IntersectionObserver" in html


# ── reproducibility and caching ─────────────────────────────────────────

def test_two_clean_runs_write_identical_files(corpus, tmp_path):
    atlas.build(str(corpus["ref"]), str(tmp_path), target=30, log=quiet)
    for name in ("visual-page-index.json", "visual-shortlist.json"):
        assert (tmp_path / name).read_bytes() == (corpus["out"] / name).read_bytes(), name


def test_second_run_opens_no_document(corpus, tmp_path, monkeypatch):
    ref = tmp_path / "ref"
    ref.mkdir()
    shutil.copy(corpus["ref"] / "bilingual.pdf", ref / "a.pdf")
    out = tmp_path / "out"
    first = atlas.build(str(ref), str(out), target=2, log=quiet)
    assert first["stats"] == {"measured_documents": 1, "cached_documents": 0}
    monkeypatch.setattr(atlas, "measure_document", lambda *a, **k: pytest.fail("rendered a cached document"))
    second = atlas.build(str(ref), str(out), target=2, log=quiet)
    assert second["stats"] == {"measured_documents": 0, "cached_documents": 1}
    assert second["index"] == first["index"]


def test_changed_file_version_or_missing_image_invalidates_only_that_document(corpus, tmp_path, monkeypatch):
    ref = tmp_path / "ref"
    ref.mkdir()
    shutil.copy(corpus["ref"] / "bilingual.pdf", ref / "a.pdf")
    shutil.copy(corpus["ref"] / "arabic_report.pdf", ref / "b.pdf")
    out = tmp_path / "out"
    res = atlas.build(str(ref), str(out), target=2, log=quiet)
    shutil.copy(corpus["ref"] / "known_compositions_extract.pdf", ref / "a.pdf")
    assert atlas.build(str(ref), str(out), target=2, log=quiet)["stats"] == {"measured_documents": 1, "cached_documents": 1}
    page = next(p for p in res["index"]["pages"] if p["file"] == "b.pdf")
    os.remove(out / "visual-atlas" / page["thumb"])
    assert atlas.build(str(ref), str(out), target=2, log=quiet)["stats"] == {"measured_documents": 1, "cached_documents": 1}
    monkeypatch.setattr(atlas, "VERSION", atlas.VERSION + 1)
    assert atlas.build(str(ref), str(out), target=2, log=quiet)["stats"]["measured_documents"] == 2


def test_rules_are_applied_to_cached_measurements(corpus, tmp_path, monkeypatch):
    ref = tmp_path / "ref"
    ref.mkdir()
    shutil.copy(corpus["ref"] / "bilingual.pdf", ref / "a.pdf")
    out = tmp_path / "out"
    atlas.build(str(ref), str(out), target=2, log=quiet)
    monkeypatch.setattr(atlas, "classify", lambda *a: [{"label": "callout", "confidence": "low", "evidence": "changed"}])
    res = atlas.build(str(ref), str(out), target=2, log=quiet)
    assert res["stats"]["measured_documents"] == 0
    assert labels(res["index"]["pages"][0]) >= {"callout"}


def test_output_inside_a_git_repository_is_refused(corpus, capsys):
    target = os.path.join(ROOT, "tests", "atlas-output-must-not-exist")
    with pytest.raises(ValueError, match="outside git"):
        atlas.build(str(corpus["ref"]), target, log=quiet)
    assert not os.path.exists(target)
    assert main(["atlas", "--input", str(corpus["ref"]), "--output", target]) == 2


# ── composition labels ──────────────────────────────────────────────────

@pytest.mark.parametrize("page,kind,required,forbidden",
                         [(n, *v) for n, v in sample_corpus.VISUAL_PAGES.items()], ids=lambda v: str(v))
def test_known_pages_get_their_labels(corpus, page, kind, required, forbidden):
    p = corpus["pages"][(KNOWN, page)]
    found = labels(p)
    assert required <= found, (kind, found, p["geometry"], p["raster"])
    assert not forbidden & found, (kind, found)


def test_layout_types_of_known_pages(corpus):
    types = {corpus["pages"][(KNOWN, n)]["layout_type"]: n for n in range(1, 16)}
    assert corpus["pages"][(KNOWN, 4)]["layout_type"] == "full_page_visual"
    assert corpus["pages"][(KNOWN, 5)]["layout_type"] == "split"
    assert corpus["pages"][(KNOWN, 3)]["layout_type"] == "display"
    assert corpus["pages"][(KNOWN, 15)]["layout_type"] == "blank"
    assert corpus["pages"][(KNOWN, 7)]["layout_type"] == "multi_column_text"
    assert len(types) >= 6


def test_every_label_shows_its_evidence(corpus):
    for p in corpus["index"]["pages"]:
        for x in p["labels"]:
            assert x["evidence"] and x["confidence"] in ("low", "medium", "high") and x["label"] in visual.LABELS


def test_no_label_claims_quality(corpus):
    words = json.dumps([list(visual.LABELS), list(visual.LABELS.values()), list(visual.LAYOUT_TYPES)]).lower()
    assert not any(w in words for w in atlas.FORBIDDEN)
    assert "aesthetic" not in {k for p in corpus["index"]["pages"] for k in p}
    assert corpus["index"]["gates"][-1]["passed"]


def test_arabic_and_bilingual_pages_are_labelled(corpus):
    assert "arabic_rtl" in labels(corpus["pages"][("arabic_report.pdf", 1)])
    assert "bilingual" in labels(corpus["pages"][("bilingual.pdf", 1)])


def test_repeating_pages_are_recognised(corpus):
    register = [p for p in corpus["index"]["pages"] if p["file"] == "repeating_register.pdf"]
    assert sum("repeating_system" in labels(p) for p in register) >= 50


def test_mirror_is_an_involution():
    sig = (1 << 5) | (1 << 40) | (1 << 150)
    assert visual._mirror(visual._mirror(sig)) == sig
    assert visual._mirror(1) == 1 << (visual.SW - 1)


def test_largest_rect_finds_the_empty_area():
    grid = [[False, False, False], [True, True, False], [True, True, False], [True, True, True]]
    area, box = visual._largest_rect(grid)
    assert area == 6 and box == (0, 1, 2, 4)


# ── spreads and RTL ─────────────────────────────────────────────────────

def test_facing_pairs_follow_reading_direction():
    assert visual.spread_of(1, 8, rtl=False, sheet=False) == {"kind": "single", "order": [1], "reads": "left_to_right"}
    assert visual.spread_of(2, 8, rtl=False, sheet=False)["order"] == [2, 3]
    assert visual.spread_of(3, 8, rtl=False, sheet=False)["order"] == [2, 3]
    assert visual.spread_of(3, 8, rtl=True, sheet=False)["order"] == [3, 2]
    assert visual.spread_of(8, 8, rtl=False, sheet=False)["kind"] == "single"


def test_sheet_spreads_stay_whole(corpus):
    p = corpus["pages"][("spread_sheets.pdf", 2)]
    assert p["sheet_spread"] and p["spread"]["kind"] == "sheet" and p["spread"]["order"] == [2]
    assert p["width_pt"] > p["height_pt"]


def test_rtl_document_reads_right_to_left(corpus):
    assert corpus["pages"][("arabic_report.pdf", 2)]["spread"]["reads"] == "right_to_left"
    assert corpus["pages"][("spread_sheets.pdf", 2)]["spread"]["reads"] == "left_to_right"


# ── shortlist ───────────────────────────────────────────────────────────

def test_shortlist_covers_every_document_with_reasons(corpus):
    short = corpus["short"]
    assert {e["file"] for e in short["entries"]} == {d["file"] for d in corpus["index"]["documents"] if d["status"] == "ok"}
    assert all(e["reasons"] and e["source"] == "algorithm" for e in short["entries"])


def test_largest_document_does_not_dominate(corpus):
    cov = corpus["short"]["coverage"]
    assert cov["by_document"]["repeating_register.pdf"] <= max(4, 30 * 0.16 + 1)
    assert cov["largest_layout_share"] < 0.5
    assert len(cov["by_label"]) >= 10


def test_shortlist_reaches_rare_compositions(corpus):
    names = {x for e in corpus["short"]["entries"] for x in e["labels"]}
    assert {"kpi_dashboard", "full_bleed", "pull_quote", "infographic", "financial_table"} <= names


def test_blank_pages_are_never_candidates(corpus):
    assert all(not (e["file"] == KNOWN and e["page"] == 15) for e in corpus["short"]["entries"])


def test_distinctiveness_separates_outliers_from_repeats(corpus):
    register = [p["distinctiveness"]["corpus_rank"] for p in corpus["index"]["pages"] if p["file"] == "repeating_register.pdf"]
    assert corpus["pages"][(KNOWN, 4)]["distinctiveness"]["corpus_rank"] > sum(register) / len(register)
    assert all(0 <= p["distinctiveness"]["score"] <= 1 for p in corpus["index"]["pages"])


# ── human decisions ─────────────────────────────────────────────────────

def test_a_new_atlas_has_no_invented_decisions(corpus):
    data = json.loads((corpus["out"] / "human-curation.json").read_text(encoding="utf-8"))
    assert data["decisions"] == [] and curation.validate(data) == []
    assert all("decision" not in p and "ratings" not in p for p in corpus["index"]["pages"])


def test_human_selections_survive_a_rerun_and_rename(corpus, tmp_path):
    ref = tmp_path / "ref"
    ref.mkdir()
    shutil.copy(corpus["ref"] / KNOWN, ref / KNOWN)
    shutil.copy(corpus["ref"] / "repeating_register.pdf", ref / "repeating_register.pdf")
    out = tmp_path / "out"
    first = atlas.build(str(ref), str(out), target=8, log=quiet)
    sha = sha_of(corpus)
    in_first = {(e["sha256"], e["page"]) for e in first["shortlist"]["entries"]}
    not_chosen = next(p["page"] for p in first["index"]["pages"]
                      if p["sha256"] == sha and (sha, p["page"]) not in in_first and p["layout_type"] != "blank")
    rejected = next(e["page"] for e in first["shortlist"]["entries"] if e["sha256"] == sha)
    data = curated(decision(not_chosen, sha, pinned=True, notes="Clear hierarchy", ratings={"clarity": 4}),
                   decision(rejected, sha, decision="reject"))
    curation.save(str(out / "human-curation.json"), data)
    os.rename(ref / KNOWN, ref / "renamed.pdf")
    second = atlas.build(str(ref), str(out), target=8, log=quiet)
    picked = {(e["sha256"], e["page"]): e for e in second["shortlist"]["entries"]}
    assert picked[(sha, not_chosen)]["source"] == "human"
    assert (sha, rejected) not in picked
    assert any(p["page"] == rejected and p["sha256"] == sha for p in second["index"]["pages"])
    saved = json.loads((out / "human-curation.json").read_text(encoding="utf-8"))["decisions"]
    assert {d["page"]: d["notes"] for d in saved}[not_chosen] == "Clear hierarchy"
    assert second["curation"]["pinned"] == 1 and second["curation"]["rejected"] == 1


def test_stale_decisions_are_reported_and_kept(corpus, tmp_path):
    ref = tmp_path / "ref"
    ref.mkdir()
    shutil.copy(corpus["ref"] / "bilingual.pdf", ref / "a.pdf")
    out = tmp_path / "out"
    out.mkdir()
    gone = decision(3, "f" * 64, decision="accept")
    curation.save(str(out / "human-curation.json"), curated(gone))
    res = atlas.build(str(ref), str(out), target=2, log=quiet)
    assert res["stale_decisions"] == [gone]
    assert curation.load(str(out / "human-curation.json"))["decisions"] == [gone]


def test_invalid_curation_stops_the_build_and_stays_on_disk(corpus, tmp_path):
    ref = tmp_path / "ref"
    ref.mkdir()
    shutil.copy(corpus["ref"] / "bilingual.pdf", ref / "a.pdf")
    out = tmp_path / "out"
    out.mkdir()
    raw = '{"format": "something else"}'
    (out / "human-curation.json").write_text(raw, encoding="utf-8")
    with pytest.raises(ValueError):
        atlas.build(str(ref), str(out), target=2, log=quiet)
    assert (out / "human-curation.json").read_text(encoding="utf-8") == raw


@pytest.mark.parametrize("patch", [
    {"decision": "maybe"}, {"ratings": {"clarity": 6}}, {"ratings": {"clarity": True}}, {"ratings": {"beauty": 3}},
    {"page": 0}, {"sha256": "abc"}, {"reviewer": ""}, {"pinned": "yes"}, {"notes": 3}, {"score": 1},
], ids=str)
def test_curation_validation_rejects(patch):
    assert curation.validate(curated({**decision(1, "a" * 64), **patch}))


def test_curation_rejects_duplicates_and_accepts_unrated_pins():
    assert curation.validate(curated(decision(1, "a" * 64), decision(1, "a" * 64)))
    assert curation.validate(curated(decision(1, "a" * 64, pinned=True))) == []


def test_pinned_beats_rejected():
    data = curated(decision(1, "a" * 64, decision="reject", pinned=True))
    assert curation.kept(data) == {("a" * 64, 1)} and curation.rejected(data) == set()


def test_curation_command(tmp_path, capsys):
    good = tmp_path / "good.json"
    curation.save(str(good), curated(decision(1, "a" * 64, decision="accept")))
    assert main(["curation", str(good)]) == 0
    bad = tmp_path / "bad.json"
    bad.write_text('{"format": "x"}', encoding="utf-8")
    assert main(["curation", str(bad)]) == 1


# ── local server ────────────────────────────────────────────────────────

@pytest.fixture
def server(corpus, tmp_path):
    shutil.copytree(corpus["out"] / "visual-atlas", tmp_path / "visual-atlas")
    curation.save(str(tmp_path / "human-curation.json"), curation.empty())
    srv = atlas.make_server(str(tmp_path), 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv, tmp_path
    srv.shutdown()
    srv.server_close()


def call(srv, method, path, body=None, host=None):
    port = srv.server_address[1]
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request(method, path, body=body, headers={"Host": host or f"127.0.0.1:{port}", "Content-Type": "application/json"})
    r = c.getresponse()
    data = r.read()
    c.close()
    return r.status, data


def test_server_binds_to_loopback_and_saves_valid_decisions(server):
    srv, out = server
    assert srv.server_address[0] == "127.0.0.1"
    assert call(srv, "GET", "/index.html")[0] == 200
    data = curated(decision(1, "a" * 64, decision="accept"))
    assert call(srv, "PUT", "/api/curation", json.dumps(data))[0] == 200
    assert json.loads(call(srv, "GET", "/api/curation")[1])["decisions"][0]["decision"] == "accept"
    assert curation.load(str(out / "human-curation.json"))["decisions"][0]["page"] == 1


def test_server_rejects_invalid_decisions_and_foreign_hosts(server):
    srv, out = server
    before = (out / "human-curation.json").read_bytes()
    bad = curated(decision(1, "a" * 64, decision="maybe"))
    assert call(srv, "PUT", "/api/curation", json.dumps(bad))[0] == 400
    assert call(srv, "PUT", "/api/curation", "{broken")[0] == 400
    assert call(srv, "PUT", "/api/curation", json.dumps(curated()), host="evil.example")[0] == 403
    assert call(srv, "GET", "/api/curation", host="evil.example")[0] == 403
    assert call(srv, "PUT", "/visual-page-index.json", "{}")[0] == 403
    assert (out / "human-curation.json").read_bytes() == before


def test_server_does_not_serve_files_outside_the_atlas(server):
    srv, out = server
    assert call(srv, "GET", "/../human-curation.json")[0] == 404
    assert call(srv, "GET", "/%2e%2e/human-curation.json")[0] == 404
