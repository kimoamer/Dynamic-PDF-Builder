"""
Checks on the AI art-direction records, so they can never pass for human decisions.

``ai-design-curation.json`` and ``layout-archetypes.json`` are AI judgements of pages
that were looked at. They are separate from ``human-curation.json``, which holds human
decisions only. ``validate`` returns every rule a pair of records breaks.
"""
from __future__ import annotations

import json
import os
import re
from typing import Dict, List

FORMAT = "dynamic-pdf-builder/m75-ai-curation"
ARCHETYPE_FORMAT = "dynamic-pdf-builder/m75-layout-archetypes"
MIN_SELECTED, MAX_SELECTED = 30, 40
MIN_ARCHETYPES, MAX_ARCHETYPES = 5, 8
IMPLEMENTED = 3
PAGE_ID = re.compile(r"^[0-9a-f]{12}:p\d{4}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
IMAGE_PATH = re.compile(r"\.(png|jpe?g|webp|tiff?|pdf)\b", re.I)
ARCHETYPE_FIELDS = ("document_types", "page_role", "content_requirements", "layout", "typography", "relationships",
                    "whitespace_rhythm", "rtl_bilingual", "constraints_fallback", "reference_pages")
PAGE_FIELDS = ("visual_category", "selection_rationale", "distinctive_features", "reusable_composition",
               "confidence", "limitations", "inspection_level")


def _ai_only(record: dict, name: str) -> List[str]:
    out = []
    if record.get("reviewer", {}).get("kind") != "ai" or not record.get("reviewer", {}).get("model"):
        out.append(f"{name}: reviewer must be identified as an AI model")
    status = record.get("status", {})
    if status.get("human_approved") is not False or status.get("human_review") != "none":
        out.append(f"{name}: AI judgements must not be marked human-approved")
    return out


def _page(p: dict, criteria: List[str], where: str) -> List[str]:
    out = []
    if not PAGE_ID.match(p.get("page_id", "")) or not SHA256.match(p.get("document_sha256", "")):
        out.append(f"{where}: page needs a page_id and a document SHA-256")
    elif not p["document_sha256"].startswith(p["page_id"][:12]):
        out.append(f"{where}: page_id does not belong to the document")
    for field in PAGE_FIELDS:
        if not p.get(field):
            out.append(f"{where}: missing {field}")
    scores = p.get("scores", {})
    values = []
    for c in criteria:
        entry = scores.get(c)
        if entry is None:
            out.append(f"{where}: missing criterion {c}")
        elif entry.get("score") is None:
            if c != "rtl_bilingual":
                out.append(f"{where}: only rtl_bilingual may go unscored")
        elif not 1 <= entry["score"] <= 5 or not entry.get("justification"):
            out.append(f"{where}: {c} needs a score from 1 to 5 and a justification")
        else:
            values.append(entry["score"])
    if values and abs(sum(values) / len(values) - p.get("mean_score", -1)) > 0.01:
        out.append(f"{where}: mean_score does not match the scores")
    return out


def validate(curation: dict, archetypes: dict) -> List[str]:
    """Every broken rule; an empty list means the records are acceptable."""
    out = _ai_only(curation, "curation") + _ai_only(archetypes, "archetypes")
    if curation.get("format") != FORMAT:
        out.append("curation: unknown format")
    if archetypes.get("format") != ARCHETYPE_FORMAT:
        out.append("archetypes: unknown format")
    selected = curation.get("selected", [])
    if not MIN_SELECTED <= len(selected) <= MAX_SELECTED:
        out.append(f"curation: {len(selected)} pages selected, expected {MIN_SELECTED} to {MAX_SELECTED}")
    ids = [p.get("page_id") for p in selected]
    if len(ids) != len(set(ids)):
        out.append("curation: a page is selected twice")
    criteria = curation.get("scale", {}).get("criteria", [])
    for p in selected:
        out += _page(p, criteria, str(p.get("page_id")))
    for r in curation.get("rejected_candidates", []):
        if not r.get("reason"):
            out.append(f"{r.get('page_id')}: a rejected candidate needs a reason")
        if r.get("page_id") in ids:
            out.append(f"{r.get('page_id')}: both selected and rejected")
    cov = curation.get("review_coverage", {})
    pages = curation.get("corpus", {}).get("pages")
    if cov.get("pages_viewed", 0) + cov.get("unreviewed_count", 0) != pages:
        out.append("curation: viewed and unreviewed pages must add up to the corpus")
    if cov.get("unreviewed_count") != len(cov.get("unreviewed_pages", [])):
        out.append("curation: the unreviewed list does not match its count")
    items = archetypes.get("archetypes", [])
    if not MIN_ARCHETYPES <= len(items) <= MAX_ARCHETYPES:
        out.append(f"archetypes: {len(items)} documented, expected {MIN_ARCHETYPES} to {MAX_ARCHETYPES}")
    if sum(bool(a.get("implemented")) for a in items) != IMPLEMENTED:
        out.append(f"archetypes: expected {IMPLEMENTED} implemented")
    for a in items:
        out += [f"{a.get('id')}: missing {f}" for f in ARCHETYPE_FIELDS if not a.get(f)]
        out += [f"{a.get('id')}: reference {ref.get('label')} is not a selected page"
                for ref in a.get("reference_pages", []) if ref.get("page_id") not in ids]
        if a.get("implemented") and not a.get("implementation", {}).get("block"):
            out.append(f"{a.get('id')}: an implemented archetype must name its block")
    text = json.dumps([curation, archetypes], ensure_ascii=False)
    if IMAGE_PATH.search(text):
        out.append("records must not point at page images or PDFs: " + IMAGE_PATH.search(text).group(0))
    return out


def load(folder: str) -> Dict[str, dict]:
    records = {}
    for key, name in (("curation", "ai-design-curation.json"), ("archetypes", "layout-archetypes.json")):
        with open(os.path.join(folder, name), encoding="utf-8") as f:
            records[key] = json.load(f)
    return records
