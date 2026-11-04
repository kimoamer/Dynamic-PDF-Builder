"""
The human pattern review in machine-readable form (``pattern_review.json``).

Each decision on a pattern links to the documents (doc id, SHA-256) and pages
it rests on. A decision records where a pattern was seen and what it may be
used for; it is never a claim that the pattern is good. ``check`` keeps the
file honest: every accepted pattern must state where it applies and why, and
how often a pattern occurs cannot stand in for a reason.
"""
from __future__ import annotations

import json
import os
import re
from typing import Dict, List, Optional

FORMAT = "dynamic-pdf-builder/pattern-review"
DECISIONS = ("accept", "reject", "needs_more_evidence")
ROLES = ("supports", "contradicts", "unchecked")
REVIEW_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pattern_review.json")
SUMMARY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "REAL_CORPUS_REVIEW.md")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_FREQUENCY_ONLY = re.compile(r"(?i)\W*(common|frequent|popular|recurring|seen often|most documents)\W*")


def load(path: str = REVIEW_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def by_decision(review: dict) -> Dict[str, List[dict]]:
    out: Dict[str, List[dict]] = {d: [] for d in DECISIONS}
    for p in review["patterns"]:
        out[p["decision"]].append(p)
    return out


def accepted_ids(review: dict) -> set:
    return {p["pattern_id"] for p in review["patterns"] if p["decision"] == "accept"}


def validate(review: dict, patterns: Optional[dict] = None) -> List[str]:
    """Problems in a review (empty list = valid). With ``patterns`` (a run's design-patterns.json) the ids
    and support are also checked against that run."""
    errs: List[str] = []
    if review.get("format") != FORMAT or review.get("version") != 1:
        errs.append("not a pattern review file (format/version)")
    docs = review.get("documents") or {}
    for label, d in docs.items():
        if not _SHA.match(d.get("sha256", "")) or not d.get("doc_id"):
            errs.append(f"document {label}: needs doc_id and a full SHA-256")
    seen = set()
    for p in review.get("patterns", []):
        pid = p.get("pattern_id", "?")
        if pid in seen:
            errs.append(f"{pid}: duplicate")
        seen.add(pid)
        if p.get("decision") not in DECISIONS:
            errs.append(f"{pid}: decision must be one of {DECISIONS}")
            continue
        reason = str(p.get("reason", ""))
        if not reason.strip():
            errs.append(f"{pid}: a decision needs a reason")
        elif _FREQUENCY_ONLY.fullmatch(reason):
            errs.append(f"{pid}: frequency is not a reason")
        ev = p.get("evidence") or []
        if not ev:
            errs.append(f"{pid}: no evidence")
        for e in ev:
            if e.get("doc") not in docs:
                errs.append(f"{pid}: unknown document {e.get('doc')!r}")
            if e.get("role") not in ROLES or not e.get("pages"):
                errs.append(f"{pid}: evidence needs a role and pages ({e.get('doc')})")
        if p["decision"] == "accept":
            if not p.get("applies_to"):
                errs.append(f"{pid}: an accepted pattern must say where it applies")
            if not any(e.get("role") == "supports" for e in ev):
                errs.append(f"{pid}: an accepted pattern needs supporting pages")
        elif p.get("applies_to"):
            errs.append(f"{pid}: only accepted patterns may be applied")
    if patterns is not None:
        run = {c["id"]: c for c in patterns.get("recurring", []) + patterns.get("observations", [])}
        for pid in sorted(seen - set(run)):
            errs.append(f"{pid}: not in this run")
        for pid in sorted(set(run) - seen):
            errs.append(f"{pid}: in this run but not reviewed")
        for p in review.get("patterns", []):
            c = run.get(p.get("pattern_id"))
            if c and c["support_docs"] != p.get("run_support", p.get("support")):
                errs.append(f"{p['pattern_id']}: support {p.get('support')} here, {c['support_docs']} in this run")
    return errs


def summary_counts(text: str) -> Dict[str, int]:
    """Rows per verdict section of REAL_CORPUS_REVIEW.md."""
    out = {}
    for name, key in (("Accept", "accept"), ("Reject", "reject"), ("Needs More Evidence", "needs_more_evidence")):
        m = re.search(rf"^### {name}\n(.*?)(?=^##|\Z)", text, re.M | re.S)
        rows = [ln for ln in (m.group(1) if m else "").splitlines() if ln.startswith("|")]
        out[key] = max(0, len(rows) - 2)
    return out


def check(path: str = REVIEW_PATH, patterns_path: Optional[str] = None) -> List[str]:
    review = load(path)
    patterns = None
    if patterns_path:
        with open(patterns_path, encoding="utf-8") as f:
            patterns = json.load(f)
    errs = validate(review, patterns)
    if os.path.exists(SUMMARY_PATH):
        with open(SUMMARY_PATH, encoding="utf-8") as f:
            want = summary_counts(f.read())
        have = {k: len(v) for k, v in by_decision(review).items()}
        if want != have:
            errs.append(f"decisions {have} differ from REAL_CORPUS_REVIEW.md {want}")
    return errs
