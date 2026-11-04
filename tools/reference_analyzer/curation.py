"""
Human curation file: reviewer decisions, kept apart from everything the tool infers.

Pages are identified by document SHA-256 + page number, so a decision survives
reruns, renames and new analyzer versions. This module validates and stores
decisions. It never creates one.
"""
from __future__ import annotations

import json
import os
import re
from typing import Dict, List, Optional, Set, Tuple

FORMAT = "dynamic-pdf-builder/m75-human-curation"
DECISIONS = ("accept", "reject", "needs_review")
RATINGS = ("visual_appeal", "clarity", "applicability")
FIELDS = {"sha256", "page", "file", "decision", "pinned", "ratings", "notes", "reviewer", "updated_at"}
_SHA = re.compile(r"^[0-9a-f]{64}$")

Key = Tuple[str, int]


def empty() -> dict:
    return {"format": FORMAT, "version": 1,
            "note": "Written only by human reviewers, through the atlas. Measurements live in visual-page-index.json.",
            "decisions": []}


def validate(data: dict) -> List[str]:
    """Problems in a curation file (empty list = valid)."""
    if not isinstance(data, dict) or data.get("format") != FORMAT or data.get("version") != 1:
        return ["not a human curation file (format/version)"]
    if not isinstance(data.get("decisions"), list):
        return ["decisions must be a list"]
    errs: List[str] = []
    seen: Set[Key] = set()
    for i, d in enumerate(data["decisions"]):
        where = f"decision {i}"
        if not isinstance(d, dict):
            errs.append(f"{where}: not an object")
            continue
        extra = set(d) - FIELDS
        if extra:
            errs.append(f"{where}: unknown fields {sorted(extra)}")
        if not _SHA.match(str(d.get("sha256"))):
            errs.append(f"{where}: sha256 must be 64 hex characters")
        page = d.get("page")
        if not isinstance(page, int) or isinstance(page, bool) or page < 1:
            errs.append(f"{where}: page must be a positive integer")
        elif (d.get("sha256"), page) in seen:
            errs.append(f"{where}: duplicate of an earlier decision for this page")
        else:
            seen.add((d.get("sha256"), page))
        if d.get("decision") not in DECISIONS + (None,):
            errs.append(f"{where}: decision must be one of {DECISIONS} or null")
        if not isinstance(d.get("pinned", False), bool):
            errs.append(f"{where}: pinned must be true or false")
        ratings = d.get("ratings") or {}
        if not isinstance(ratings, dict) or set(ratings) - set(RATINGS):
            errs.append(f"{where}: ratings may only hold {RATINGS}")
        else:
            for k, v in ratings.items():
                if v is not None and (not isinstance(v, int) or isinstance(v, bool) or not 1 <= v <= 5):
                    errs.append(f"{where}: rating {k} must be 1-5 or null")
        if not isinstance(d.get("notes", ""), str):
            errs.append(f"{where}: notes must be text")
        if not str(d.get("reviewer") or "").strip():
            errs.append(f"{where}: reviewer is required")
    return errs


def load(path: str) -> dict:
    """The curation at ``path``, or an empty one. An invalid file is an error, never silently replaced."""
    if not os.path.exists(path):
        return empty()
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    errs = validate(data)
    if errs:
        raise ValueError(f"{path}: " + "; ".join(errs[:5]))
    return data


def save(path: str, data: dict) -> None:
    errs = validate(data)
    if errs:
        raise ValueError("; ".join(errs[:5]))
    data = {**data, "decisions": sorted(data["decisions"], key=lambda d: (d["sha256"], d["page"]))}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, path)


def _keys(data: dict, test) -> Set[Key]:
    return {(d["sha256"], d["page"]) for d in data["decisions"] if test(d)}


def kept(data: dict) -> Set[Key]:
    """Pages a reviewer pinned or accepted: they stay selected on every rerun."""
    return _keys(data, lambda d: d.get("pinned") or d.get("decision") == "accept")


def rejected(data: dict) -> Set[Key]:
    return _keys(data, lambda d: d.get("decision") == "reject" and not d.get("pinned"))


def stale(data: dict, known: Set[Key]) -> List[dict]:
    """Decisions for pages no longer in the corpus: reported, and kept in the file."""
    return [d for d in data["decisions"] if (d["sha256"], d["page"]) not in known]


def summary(data: dict) -> Dict[str, Optional[int]]:
    ds = data["decisions"]
    return {"decisions": len(ds), "accepted": sum(d.get("decision") == "accept" for d in ds),
            "rejected": sum(d.get("decision") == "reject" for d in ds),
            "needs_review": sum(d.get("decision") == "needs_review" for d in ds),
            "pinned": sum(bool(d.get("pinned")) for d in ds),
            "reviewers": len({d["reviewer"] for d in ds})}
