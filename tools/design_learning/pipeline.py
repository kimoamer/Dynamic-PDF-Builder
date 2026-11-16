"""
Reference PDFs to approved grammar: import, analyze, validate, review, approve, publish.

Everything here runs offline and by hand. Reference PDFs and page images stay in the
folders named by ``config/design-learning.json``; only abstract rules reach the package.
An AI reviewer's work is recorded as AI work. Nothing here trains a model.
"""
from __future__ import annotations

import datetime
import json
import os
import shutil
import sys
from typing import Dict, List, Optional

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CONFIG = os.environ.get("DPB_LEARNING_CONFIG") or os.path.join(ROOT, "config", "design-learning.json")
REVIEWER_TYPES = ("ai", "human")
DEPTHS = ("detail_2up", "detail_3up", "full_page")


def is_absolute(path: str) -> bool:
    """Absolute on this machine or as a Windows drive path, so ``D:/refs`` is never read as
    a folder inside the repository when the config is used on Linux or macOS."""
    import ntpath
    return os.path.isabs(path) or ntpath.isabs(path)


def paths(config: Optional[str] = None) -> Dict[str, str]:
    with open(config or CONFIG, encoding="utf-8") as f:
        c = json.load(f)
    out = {k: v if is_absolute(v) else os.path.join(ROOT, v) for k, v in c.items() if isinstance(v, str)}
    out["grammar_work"] = os.path.join(out["analysis_dir"], "grammar")
    return out


def _load(path: str, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _dump(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write("\n")


def _jsonl(path: str) -> List[dict]:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


def known_hashes(p: Dict[str, str]) -> Dict[str, str]:
    cat = _load(os.path.join(p["analysis_dir"], "reference-catalog.json"), {"documents": []})
    return {d["sha256"]: d["file"] for d in cat["documents"] if d.get("sha256")}


def do_import(p: Dict[str, str], source: Optional[str] = None) -> dict:
    """Register the PDFs in the inbox, or copy in those from ``source``. Repeats are skipped."""
    from tools.reference_analyzer.catalog import discover, sha256_file
    os.makedirs(p["inbox"], exist_ok=True)
    if source:
        files = [source] if os.path.isfile(source) else discover(source)
        for f in files:
            target = os.path.join(p["inbox"], os.path.basename(f))
            if os.path.abspath(f) != os.path.abspath(target) and not os.path.exists(target):
                shutil.copy2(f, target)
    log = os.path.join(p["grammar_work"], "imports.jsonl")
    seen = {r["sha256"] for r in _jsonl(log)}
    known = known_hashes(p)
    added, repeated = [], []
    for f in discover(p["inbox"]):
        digest = sha256_file(f)
        rel = os.path.relpath(f, p["reference_dir"]).replace("\\", "/")
        if digest in known or digest in seen:
            repeated.append({"file": rel, "same_as": known.get(digest, "an earlier import")})
            continue
        seen.add(digest)
        added.append({"file": rel, "sha256": digest, "doc_id": "ref-" + digest[:12],
                      "imported_on": datetime.date.today().isoformat(), "rights": "unknown until recorded"})
    os.makedirs(p["grammar_work"], exist_ok=True)
    with open(log, "a", encoding="utf-8", newline="\n") as f:
        for r in added:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return {"imported": added, "skipped_repeats": repeated}


def do_analyze(p: Dict[str, str]) -> dict:
    """Measure every PDF, rebuild the atlas and the page graphs. Contact sheets stay as they are,
    because existing notes are keyed to their numbering; new pages join the review queue."""
    from tools.reference_analyzer import graphs
    from tools.reference_analyzer.run import main as analyzer
    args = ["--input", p["reference_dir"], "--output"]
    if analyzer(["analyze", *args, p["analysis_dir"], "--no-previews"]) or analyzer(["atlas", *args, os.path.join(p["analysis_dir"], "visual")]):
        raise SystemExit("the analyzer failed")
    g = graphs.build(p["analysis_dir"], p["reference_dir"])
    _dump(os.path.join(p["grammar_work"], "page-composition-graphs.json"), g)
    return {"documents": len(g["documents"]), "pages": len(g["pages"])}


def _coverage(p: Dict[str, str]) -> dict:
    from tools.reference_analyzer import coverage as C
    g = _load(os.path.join(p["grammar_work"], "page-composition-graphs.json"))
    cat = _load(os.path.join(p["analysis_dir"], "reference-catalog.json"))
    if g is None or cat is None:
        raise SystemExit("no analysis yet: run analyze first")
    if not os.path.exists(os.path.join(p["analysis_dir"], "visual", "review-sheets", "manifest.json")):
        os.makedirs(os.path.join(p["analysis_dir"], "visual", "review-sheets"), exist_ok=True)
        _dump(os.path.join(p["analysis_dir"], "visual", "review-sheets", "manifest.json"), {"sheets": []})
    return C.build(p["analysis_dir"], cat, g)


def do_validate(p: Dict[str, str]) -> List[str]:
    """Problems that must block a publish; an empty list means every check passed."""
    errors: List[str] = []
    cov = _coverage(p)
    expected = sum(d["pages"] for d in cov["documents"])
    if len(cov["pages"]) != expected or len({x["ref"] for x in cov["pages"]}) != expected:
        errors.append(f"coverage has {len(cov['pages'])} pages for {expected} expected")
    missing = [x["ref"] for x in cov["pages"] if not x["measured"]["structural"]]
    if missing:
        errors.append(f"{len(missing)} pages not measured")
    full = _load(p["grammar_file"])
    if full is None:
        return errors + [f"no grammar at {p['grammar_file']}"]
    refs = {x["ref"] for x in cov["pages"]}
    need = ("page_roles", "required_elements", "layout_constraints", "rtl_behavior", "evidence_pages", "confidence",
            "failure_conditions", "safe_fallback")
    for r in full["rules"]:
        errors += [f"{r['id']}: missing {k}" for k in need if not r.get(k)]
        errors += [f"{r['id']}: unknown evidence {e['ref']}" for e in r.get("evidence_pages", ()) if e["ref"] not in refs]
        if r.get("engine") and r.get("requires"):
            errors.append(f"{r['id']}: an engine rule cannot also need a missing primitive")
    return errors


def do_review(p: Dict[str, str], record: Optional[str] = None, limit: int = 24) -> dict:
    """Without ``record``: list pages no one has looked at and draw them. With it: add notes."""
    notes = os.path.join(p["grammar_work"], "review-notes-detail.jsonl")
    if record:
        rows = _jsonl(record)
        for r in rows:
            for k in ("ref", "family", "note", "confidence", "depth", "shown_px", "reviewer"):
                if not r.get(k):
                    raise SystemExit(f"note for {r.get('ref')!r} lacks {k}")
            if r["reviewer"] not in REVIEWER_TYPES or r["depth"] not in DEPTHS:
                raise SystemExit(f"bad reviewer or depth on {r['ref']}")
            if r["reviewer"] == "ai" and not r.get("model"):
                raise SystemExit(f"an AI note must name its model: {r['ref']}")
        with open(notes, "a", encoding="utf-8", newline="\n") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        return {"recorded": len(rows)}
    from tools.reference_analyzer import detail_sheets as D
    cov = _coverage(p)
    queue = [x["ref"] for x in cov["pages"] if x["ai_observation"]["depth"] == "measured_only"]
    _dump(os.path.join(p["grammar_work"], "review-queue.json"), {"pages": queue})
    rows = []
    for i, batch in D.batches(queue[:limit], 2):
        rows += D.sheet(p["analysis_dir"], batch, os.path.join(p["grammar_work"], "detail-sheets", f"queue-{i:02d}.jpg"),
                        cols=2, cell_w=780, captions=batch)
    if rows:
        D.write_manifest(os.path.join(p["grammar_work"], "detail-sheets", "queue-manifest.json"), rows)
    return {"unreviewed_pages": len(queue), "sheets_drawn_for": len(rows)}


def do_approve(p: Dict[str, str], rules: List[str], reviewer_type: str, model: Optional[str], reviewer: Optional[str]) -> dict:
    """Record who approved which rules. Nothing defaults to a person."""
    if reviewer_type not in REVIEWER_TYPES:
        raise SystemExit(f"--reviewer-type must be one of {REVIEWER_TYPES}")
    if reviewer_type == "ai" and not model:
        raise SystemExit("an AI approval must name its model")
    if reviewer_type == "human" and not reviewer:
        raise SystemExit("a human approval must name the person")
    full = _load(p["grammar_file"])
    usable = {r["id"] for r in full["rules"] if r.get("engine")}
    chosen = sorted(usable) if rules == ["all"] else rules
    unknown = set(chosen) - usable
    if unknown:
        raise SystemExit(f"cannot approve {sorted(unknown)}: unknown, or the engine cannot use them")
    record = {"rules": chosen, "grammar_version": full["version"], "reviewer_type": reviewer_type, "model": model,
              "reviewer": reviewer, "date": datetime.date.today().isoformat(), "human_approved": reviewer_type == "human"}
    path = os.path.join(p["grammar_approvals"])
    log = _load(path, {"approvals": []})
    log["approvals"].append(record)
    _dump(path, log)
    return record


def do_publish(p: Dict[str, str]) -> dict:
    """Write the packaged grammar from the latest approval, after validation."""
    from tools.reference_analyzer.grammar_build import approved
    errors = do_validate(p)
    if errors:
        raise SystemExit("cannot publish:\n" + "\n".join(errors))
    log = _load(p["grammar_approvals"], {"approvals": []})
    if not log["approvals"]:
        raise SystemExit("nothing approved: run approve first")
    a = log["approvals"][-1]
    full = _load(p["grammar_file"])
    if a["grammar_version"] != full["version"]:
        raise SystemExit("the approval is for another grammar version")
    keep = dict(full, rules=[r for r in full["rules"] if r["id"] in a["rules"]])
    out = approved(keep, {k: a[k] for k in ("reviewer_type", "model", "reviewer", "date", "human_approved")})
    _dump(p["packaged_grammar"], out)
    from dynamic_pdf.design.grammar import load
    g = load(p["packaged_grammar"])
    return {"published": p["packaged_grammar"], "version": g.version, "rules": g.ids()}


def do_status(p: Dict[str, str]) -> dict:
    from tools.reference_analyzer.catalog import discover
    cov = _coverage(p)
    full = _load(p["grammar_file"], {"rules": []})
    pub = _load(p["packaged_grammar"], {"rules": [], "approval": {}})
    prefs = [f for f in sorted(os.listdir(p["ai_preferences"])) if f.endswith(".jsonl")] if os.path.isdir(p["ai_preferences"]) else []
    models = [f for f in sorted(os.listdir(p["models"])) if f.endswith(".txt")] if os.path.isdir(p["models"]) else []
    return {"inbox_pdfs": len(discover(p["inbox"])) if os.path.isdir(p["inbox"]) else 0, "coverage": cov["summary"],
            "grammar_rules": len(full["rules"]), "engine_rules": sum(bool(r.get("engine")) for r in full["rules"]),
            "published_rules": len(pub["rules"]), "published_approval": pub.get("approval"),
            "ai_preference_files": prefs, "models": models, "paths": {k: v for k, v in p.items()}}


def report(data) -> None:
    sys.stdout.write(json.dumps(data, ensure_ascii=False, indent=1) + "\n")
