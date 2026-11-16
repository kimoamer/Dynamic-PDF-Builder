"""
Is the AI preference dataset ready for a training experiment?

This trains nothing. It counts what a trainer would accept, says what the data covers, how
consistent the reviewer was, whether every row can be traced to a render, and whether the
held-out documents leak into training. The gate is the trainer's own 200 usable comparisons;
a shortfall is reported as it stands, never filled.
"""
from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from typing import Dict, List, Optional

from .pipeline import _dump, _jsonl, _load
from .preferences import PLAIN

GATE = 200
TRACE_FIELDS = ("comparison", "batch", "document", "document_hash", "reviewer_type", "model", "review_date",
                "evaluation_method", "formats_inspected", "pages_shown", "pages_total", "shown_px")


def _pair(r: dict) -> tuple:
    return r["batch"], r["document"], frozenset((r["a"]["candidate"], r["b"]["candidate"]))


def _won(r: dict) -> Optional[str]:
    return r["a"]["candidate"] if r["preferred"] == "A" else r["b"]["candidate"] if r["preferred"] == "B" else None


def usable(rows: List[dict], skipped: set) -> List[dict]:
    """The trainer's rule: clear answers, not low confidence, not repeats, no self-contradiction,
    and no design later found defective."""
    seen: Dict[tuple, set] = defaultdict(set)
    for r in rows:
        seen[_pair(r)].add(_won(r))       # judges who disagree leave the pair out, like a flipped repeat
    once: set = set()
    out = []
    for r in rows:
        if (r["preferred"] in ("A", "B") and r["confidence"] != "low" and len(seen[_pair(r)]) == 1
                and not r["reversed_repeat"] and (r["batch"], r["comparison"]) not in once
                and (r["batch"], r["document"], r["a"]["candidate"]) not in skipped
                and (r["batch"], r["document"], r["b"]["candidate"]) not in skipped):
            once.add((r["batch"], r["comparison"]))       # judges who agree count a comparison once
            out.append(r)
    return out


def _candidates(batches: str):
    cands, skipped = {}, set()
    for name in sorted(os.listdir(batches)):
        path = os.path.join(batches, name, "candidates.jsonl")
        if os.path.exists(path):
            for c in _jsonl(path):
                cands[(name, c["document"], c["candidate"])] = c
        path = os.path.join(batches, name, "superseded.json")
        if os.path.exists(path):
            for item in _load(path).get("candidates", []):
                skipped.add((name, item["document"], item["candidate"]))
    return cands, skipped


def _language(document: str) -> str:
    return "bilingual" if document.startswith("bilingual") else "arabic" if document.startswith("arabic") else "english"


def _fact_links(rows: List[dict], cands: dict) -> List[dict]:
    """How often the preferred design has the larger measured fact. Descriptive only: with this
    few rows it is a check on the data, not a finding about design."""
    tally: Dict[str, List[int]] = defaultdict(lambda: [0, 0])
    for r in rows:
        win, lose = (r["a"], r["b"]) if r["preferred"] == "A" else (r["b"], r["a"])
        w = cands.get((r["batch"], r["document"], win["candidate"]), {}).get("layout_facts")
        x = cands.get((r["batch"], r["document"], lose["candidate"]), {}).get("layout_facts")
        if not w or not x:
            continue
        for k, v in w.items():
            if k != "facts_version" and v != x.get(k):
                tally[k][0] += v > x.get(k, 0)
                tally[k][1] += 1
    out = [{"fact": k, "winner_higher": a, "differed": n, "share": round(a / n, 2)} for k, (a, n) in tally.items() if n >= 10]
    return sorted(out, key=lambda t: -abs(t["share"] - 0.5))[:10]


def report(dataset: str, batches: str, split_path: str, out: Optional[str] = None) -> dict:
    rows = _jsonl(dataset)
    split = _load(split_path)
    cands, skipped = _candidates(batches)
    good = usable(rows, skipped)
    held = {d for f, ds in split["families"].items() if f in split["evaluation_families"] for d in ds}
    family = {d: f for f, ds in split["families"].items() for d in ds}
    train = [r for r in good if r["document"] not in held]
    test = [r for r in good if r["document"] in held]

    first = {(r.get("model"), *_pair(r)): r for r in rows if not r["reversed_repeat"]}      # each judge against itself
    repeats = [(first[(r.get("model"), *_pair(r))], r) for r in rows if r["reversed_repeat"] and (r.get("model"), *_pair(r)) in first]
    agree = sum(_won(a) == _won(b) for a, b in repeats)
    flips = [b["comparison"] for a, b in repeats if _won(a) != _won(b)]

    missing = Counter(f for r in rows for f in TRACE_FIELDS if r.get(f) in (None, "", []))
    unmatched = [r["comparison"] for r in rows for side in ("a", "b")
                 if (cands.get((r["batch"], r["document"], r[side]["candidate"])) or {}).get("pdf_sha256") != r[side]["pdf_sha256"]]
    answers = [r for r in rows if not r["reversed_repeat"] and r["preferred"] in ("A", "B")]
    side_a = sum(r["preferred"] == "A" for r in answers)
    baseline = [r for r in good if r["a"]["candidate"].split("@")[0] == r["b"]["candidate"].split("@")[0]
                and (PLAIN in r["a"]["candidate"]) != (PLAIN in r["b"]["candidate"])]
    grammar_won = sum(PLAIN not in _won(r) for r in baseline)
    wins, plays = Counter(), Counter()
    for r in good:
        for side in ("a", "b"):
            plays[r[side]["candidate"].split("@")[0]] += 1
        wins[_won(r).split("@")[0]] += 1
    unknown_docs = sorted({r["document"] for r in rows} - set(family))
    leaks = sorted({r["document"] for r in train} & {r["document"] for r in test})
    shared_hash = sorted({r["document_hash"] for r in train} & {r["document_hash"] for r in test})
    with_facts = sum(1 for r in good if all(
        (cands.get((r["batch"], r["document"], r[s]["candidate"])) or {}).get("layout_facts") for s in ("a", "b")))

    weaknesses = []
    if len(good) < GATE:
        weaknesses.append(f"{len(good)} usable comparisons against a gate of {GATE}: not enough to train")
    if len(test) < 40:
        weaknesses.append(f"only {len(test)} held-out comparisons: an agreement figure would be too noisy to trust")
    if len({r["document"] for r in good}) < 30:
        weaknesses.append(f"{len({r['document'] for r in good})} documents: all fictional, written by one author, sharing "
                          "five generated pictures, so a model could learn this corpus and not design")
    if len({r.get("model") for r in rows}) == 1:
        weaknesses.append("one reviewer model: its taste and blind spots are in every row, and no human has checked them")
    if repeats and len(repeats) < 30:
        weaknesses.append(f"{len(repeats)} reversed repeats: consistency is a small sample, and a reviewer may remember a sheet")
    if answers and abs(side_a / len(answers) - 0.5) > 0.1:
        weaknesses.append(f"side A won {side_a} of {len(answers)}: a position preference to look into")
    pct = Counter(r["confidence"] for r in rows)
    if pct.get("high", 0) < len(rows) * 0.25:
        weaknesses.append(f"{pct.get('high', 0)} of {len(rows)} answers are high confidence: thumbnails limit what can be seen")
    word = sum("word" in (r.get("formats_inspected") or []) for r in good)
    if word < len(good) / 2:
        weaknesses.append(f"{word} of {len(good)} usable comparisons were judged on Word pages")
    if with_facts < len(good):
        weaknesses.append(f"{len(good) - with_facts} usable comparisons predate the layout facts and lack them")

    result = {
        # The volume threshold is *not* permission to train or a sign-off on quality.
        # The independent local audit additionally needs real Word evidence, human
        # review, author/asset provenance, and strict split/hash isolation.
        "verdict": "volume gate met; independent quality audit required" if len(good) >= GATE and not leaks and not unmatched else "not ready",
        "gate": GATE, "rows": len(rows), "usable": len(good), "train_usable": len(train), "held_out_usable": len(test),
        "excluded": {"ties_or_abstentions": sum(r["preferred"] in ("tie", "abstain") for r in rows),
                     "low_confidence": sum(r["confidence"] == "low" for r in rows),
                     "reversed_repeats": sum(bool(r["reversed_repeat"]) for r in rows)},
        "coverage": {"documents": dict(Counter(r["document"] for r in good)),
                     "families": dict(Counter(family.get(r["document"], "?") for r in good)),
                     "languages": dict(Counter(_language(r["document"]) for r in good)),
                     "formats": dict(Counter(f for r in good for f in r.get("formats_inspected") or [])),
                     "batches": dict(Counter(r["batch"] for r in good))},
        "consistency": {"reversed_pairs": len(repeats), "agreed": agree, "flipped": flips,
                        "side_a_won": side_a, "clear_answers": len(answers), "confidence": dict(pct)},
        "provenance": {"reviewer_types": sorted({r.get("reviewer_type") for r in rows}), "models": sorted({str(r.get("model")) for r in rows}),
                       "missing_fields": dict(missing), "rows_not_matching_a_render": sorted(set(unmatched)),
                       "with_layout_facts": with_facts},
        "leakage": {"evaluation_families": split["evaluation_families"], "documents_in_both": leaks, "hashes_in_both": shared_hash,
                    "documents_outside_the_split": unknown_docs,
                    "note": "Families never cross the split, but all documents share the same generated pictures and author."},
        "signals": {"grammar_against_own_baseline": {"comparisons": len(baseline), "grammar_won": grammar_won},
                    "design_win_rate": {d: {"won": wins[d], "of": plays[d]} for d in sorted(plays)},
                    "facts_most_tied_to_the_winner": _fact_links(good, cands)},
        "weaknesses": weaknesses,
    }
    if out:
        os.makedirs(out, exist_ok=True)
        _dump(os.path.join(out, "dataset-readiness.json"), result)
        with open(os.path.join(out, "dataset-readiness.md"), "w", encoding="utf-8", newline="\n") as f:
            f.write(_markdown(result))
    return result


def _markdown(r: dict) -> str:
    c, k, p, s = r["coverage"], r["consistency"], r["provenance"], r["signals"]
    base = s["grammar_against_own_baseline"]
    lines = ["# Dataset readiness", "",
             "Written by `python -m tools.design_learning preferences readiness`. No model was trained.", "",
             f"**Verdict: {r['verdict']}.** {r['usable']} usable comparisons against a gate of {r['gate']}: "
             f"{r['train_usable']} for training and {r['held_out_usable']} held out, from {r['rows']} rows.", "",
             "## Excluded", "",
             *[f"- {k_.replace('_', ' ')}: {v}" for k_, v in r["excluded"].items()], "",
             "## Coverage", "", "| Slice | Usable |", "| --- | --- |",
             *[f"| {name}: {k_} | {v} |" for name in ("languages", "families", "formats", "batches") for k_, v in sorted(c[name].items())], "",
             f"{len(c['documents'])} documents appear. Fewest: " +
             ", ".join(f"{d} ({n})" for d, n in sorted(c["documents"].items(), key=lambda x: x[1])[:4]) + ".", "",
             "## Consistency", "",
             f"- Reversed repeats: {k['agreed']} of {k['reversed_pairs']} agreed" + (f"; flipped: {', '.join(k['flipped'])}" if k["flipped"] else "") + ".",
             f"- Side A won {k['side_a_won']} of {k['clear_answers']} clear answers.",
             f"- Confidence: {json.dumps(k['confidence'])}.", "",
             "## Provenance", "",
             f"- Reviewer types: {', '.join(p['reviewer_types'])}. Models: {', '.join(p['models'])}.",
             f"- Rows missing a traced field: {sum(p['missing_fields'].values())}.",
             f"- Rows whose hash matches no render on record: {len(p['rows_not_matching_a_render'])}.",
             f"- Usable rows with measured layout facts on both sides: {p['with_layout_facts']}.", "",
             "## Leakage", "",
             f"- Held-out families: {', '.join(r['leakage']['evaluation_families'])}.",
             f"- Documents on both sides: {len(r['leakage']['documents_in_both'])}. Same source hash on both sides: {len(r['leakage']['hashes_in_both'])}.",
             f"- Documents outside the split: {len(r['leakage']['documents_outside_the_split'])}.",
             f"- {r['leakage']['note']}", "",
             "## What the rows say", "",
             f"Grammar design against the same design without it: {base['grammar_won']} of {base['comparisons']} went to the grammar. "
             "These are one AI reviewer's preferences on fictional documents, not a measure of quality.", "",
             "| Direction | Won | Of |", "| --- | --- | --- |",
             *[f"| {d} | {v['won']} | {v['of']} |" for d, v in s["design_win_rate"].items()], "",
             "Facts most often higher on the preferred side (descriptive only):", "",
             *[f"- {t['fact']}: {t['winner_higher']} of {t['differed']}" for t in s["facts_most_tied_to_the_winner"]], "",
             "## Remaining weaknesses", "", *[f"- {w}" for w in r["weaknesses"]], ""]
    return "\n".join(lines)


__all__ = ["GATE", "report", "usable"]
