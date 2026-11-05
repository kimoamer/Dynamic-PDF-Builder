"""
Full-corpus coverage: where every reference page stands.

Three kinds of statement are kept apart for each page: what was measured, what an AI
reviewer saw and at what size, and what remains unverified. The reviewed family starts
from the measured one and changes only where a review note says otherwise.
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict
from typing import Dict, List, Optional

FORMAT = "dynamic-pdf-builder/m77-full-corpus-coverage"
# review-note wording that overrides a measured family, in order
NOTE_FAMILY = (
    (re.compile(r"^(notes?|references?|footnotes?|endnotes?)\b", re.I), "notes_references"),
    (re.compile(r"^blank\b|notice-only", re.I), "blank_or_notice"),
    (re.compile(r"^(chapter-opener|divider|section-opener)\b", re.I), "section_opener"),
    (re.compile(r"^(toc|contents)\b", re.I), "contents"),
    (re.compile(r"^kpi", re.I), "kpi_dashboard"),
    (re.compile(r"^(letter|embedded-letter|message)\b", re.I), "letter"),
    (re.compile(r"^infographic\b", re.I), "infographic"),
    (re.compile(r"^(back-cover|colophon|back)\b", re.I), "back_cover"),
    (re.compile(r"^statement\b", re.I), "statement"),
)
EXTRA_FAMILIES = {"notes_references": "Notes, references or endnotes",
                  "letter": "Signed letter or message",
                  "card_grid": "Cards and tiles arranged on a grid",
                  "academic_opening": "Article first page with a metadata margin"}


def parse_contact_notes(path: str, manifest: dict) -> Dict[str, dict]:
    """``ref -> {text, confidence, shown_px, sheet}`` from a contact-sheet notes file."""
    order, ref, px = [], {}, {}
    for s in manifest["sheets"]:
        n = int(re.search(r"(\d+)", s["name"]).group(1))
        for p in s["pages"]:
            order.append((n, p["slot"]))
            ref[(n, p["slot"])] = "ref-" + p["key"]
            px[(n, p["slot"])] = p.get("shown_px")
    pos = {k: i for i, k in enumerate(order)}
    out: Dict[str, dict] = {}
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as f:
        for line in f:
            token = line.split(" ")[0]
            if not re.match(r"\d+\.\d", token):
                continue
            rest = line[len(token):].strip()
            head = rest.split("|")[0].split()
            conf = {"h": "high", "m": "medium", "l": "low"}.get(head[-1] if head else "", "unstated")
            shared = token.count("-") + token.count(",") > 0
            for part in token.split(","):
                ends = part.split("-")
                a = tuple(int(x) for x in ends[0].split("."))
                b = tuple(int(x) for x in ends[-1].split(".")) if "." in ends[-1] else (a[0], int(ends[-1]))
                for k in order[pos[a]:pos[b] + 1]:
                    out[ref[k]] = {"text": rest, "confidence": conf, "shown_px": px[k], "sheet": k[0], "slot": k[1],
                                   "shared_note": shared}
    return out


def _read_jsonl(path: str) -> List[dict]:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


def reviewed_family(page: dict, contact: Optional[dict], detail: Optional[dict]) -> tuple:
    if detail and detail.get("family"):
        return detail["family"], "ai_detail" if detail["family"] != page["family"] else "measured_confirmed_detail"
    if contact:
        for rx, fam in NOTE_FAMILY:
            if rx.search(contact["text"]):
                if fam == "blank_or_notice" and (page["measures"].get("chars") or 0) > 400:
                    break
                if fam != page["family"]:
                    return fam, "ai_contact_sheet"
                break
    return page["family"], "measured"


def build(analysis_dir: str, catalog: dict, graphs: dict) -> dict:
    with open(os.path.join(analysis_dir, "visual", "review-sheets", "manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    sheets = os.path.join(analysis_dir, "visual", "review-sheets")
    contact = parse_contact_notes(os.path.join(sheets, "review-notes.txt"), manifest)
    quarantined = parse_contact_notes(os.path.join(sheets, "review-notes-unverified.txt"), manifest)
    details: Dict[str, dict] = {}
    for row in _read_jsonl(os.path.join(analysis_dir, "grammar", "review-notes-detail.jsonl")):
        details[row["ref"]] = row
    rights = {d["doc_id"]: (d.get("rights_status") or {}).get("status", "unknown") for d in catalog["documents"]}
    pages = []
    for g in graphs["pages"]:
        c, d = contact.get(g["ref"]), details.get(g["ref"])
        fam, source = reviewed_family(g, c, d)
        depth = d["depth"] if d else "contact_sheet" if c else "measured_only"
        conf = (d or {}).get("confidence") or (c or {}).get("confidence") or "none"
        pages.append({
            "ref": g["ref"], "doc": g["doc"], "page": g["page"],
            "measured": {"structural": True, "family": g["family"], "family_test": g["family_test"],
                         "direction": g["direction"], "facets": g["facets"]},
            "ai_observation": {"family": fam, "family_source": source, "depth": depth,
                               "shown_px": (d or {}).get("shown_px") or (c or {}).get("shown_px"),
                               "confidence": conf, "note_shared_with_other_pages": bool(c and c["shared_note"] and not d),
                               "note": (d or {}).get("note") or (c or {}).get("text")},
            "unverified": {"quarantined_note_exists": g["ref"] in quarantined, "human_reviewed": False},
            "weight": round(1 / max(1, g.get("cluster_in_document") or 1), 4),
            "template_cluster": g.get("cluster"),
        })
    count = Counter(p["ai_observation"]["depth"] for p in pages)
    return {
        "format": FORMAT, "version": 1,
        "note": "Every reference page: what was measured, what an AI reviewer saw and at what size. No person has "
                "reviewed these pages. Notes describe layout only. Rights notes record a reviewer's reading and are "
                "not a legal determination.",
        "summary": {"pages": len(pages), "documents": len(graphs["documents"]),
                    "measured": sum(p["measured"]["structural"] for p in pages), "by_depth": dict(count),
                    "family_source": dict(Counter(p["ai_observation"]["family_source"] for p in pages)),
                    "confidence": dict(Counter(p["ai_observation"]["confidence"] for p in pages)),
                    "quarantined_notes": sum(p["unverified"]["quarantined_note_exists"] for p in pages),
                    "human_reviewed": 0},
        "documents": [{**d, "rights_note": rights.get(d["doc_id"], "unknown")} for d in graphs["documents"]],
        "pages": pages,
    }


def family_summary(coverage: dict) -> Dict[str, dict]:
    out: Dict[str, dict] = defaultdict(lambda: {"pages": 0, "weighted": 0.0, "documents": set()})
    for p in coverage["pages"]:
        r = out[p["ai_observation"]["family"]]
        r["pages"] += 1
        r["weighted"] += p["weight"]
        r["documents"].add(p["doc"])
    return {k: {"pages": v["pages"], "weighted": round(v["weighted"], 1), "documents": len(v["documents"])}
            for k, v in sorted(out.items(), key=lambda kv: -kv[1]["weighted"])}
