"""
Human preference files exported by the M7 gallery.

    python benchmarks/m7/preferences.py validate FILE...
    python benchmarks/m7/preferences.py summary RESULTS_JSON FILE...

Format (``dynamic-pdf-builder/m7-human-preferences``, version 1)::

    {"format": "dynamic-pdf-builder/m7-human-preferences", "version": 1,
     "reviewer": "initials", "exported_at": "ISO-8601",
     "judgments": [{"document": "proposal", "shown_as": {"A": "smart", "B": "baseline"},
                    "choice": "A" | "B" | "tie", "preferred_variant": "smart" | "baseline" | "tie",
                    "reasons": ["whitespace", ...], "note": "free text",
                    "layout_id": {"baseline": "…", "smart": "…"}, "judged_at": "ISO-8601"}]}

Human judgments are kept apart from automated metrics: this module never
creates a judgment, and ``summary`` drops any judgment whose layout ids no
longer match the benchmark results (the layout changed after it was judged).
"""
from __future__ import annotations

import json
import sys
from typing import Dict, List

FORMAT = "dynamic-pdf-builder/m7-human-preferences"
VARIANTS = {"baseline", "smart"}


def validate(data: dict, fmt: str = FORMAT, variants=VARIANTS) -> List[str]:
    """Problems in one preference file (empty list = valid)."""
    errs = []
    if data.get("format") != fmt or data.get("version") != 1:
        errs.append("not a preference file of this benchmark (format/version)")
    js = data.get("judgments")
    if not isinstance(js, list):
        return errs + ["judgments must be a list"]
    seen = set()
    for k, j in enumerate(js):
        where = f"judgment {k} ({j.get('document', '?')})"
        shown = j.get("shown_as") or {}
        if set(shown) != {"A", "B"} or set(shown.values()) != set(variants):
            errs.append(f"{where}: shown_as must map A and B to {' and '.join(sorted(variants))}")
            continue
        choice = j.get("choice")
        if choice not in ("A", "B", "tie"):
            errs.append(f"{where}: choice must be A, B or tie (unlabelled judgments are not allowed)")
            continue
        expect = "tie" if choice == "tie" else shown[choice]
        if j.get("preferred_variant") != expect:
            errs.append(f"{where}: preferred_variant {j.get('preferred_variant')!r} contradicts choice {choice}")
        if j.get("document") in seen:
            errs.append(f"{where}: duplicate document")
        seen.add(j.get("document"))
        if not isinstance(j.get("reasons", []), list):
            errs.append(f"{where}: reasons must be a list")
    return errs


def summary(results: dict, files: List[dict]) -> Dict[str, Dict[str, int]]:
    """Per document: counts of smart / baseline / tie across reviewers (hash-checked)."""
    docs = results["documents"]
    out: Dict[str, Dict[str, int]] = {}
    for f in files:
        if validate(f):
            continue
        for j in f["judgments"]:
            d = docs.get(j["document"])
            if not d or any(d[v]["layout_id"] != (j.get("layout_id") or {}).get(v) for v in VARIANTS):
                continue        # judged a different rendering: stale
            c = out.setdefault(j["document"], {"smart": 0, "baseline": 0, "tie": 0})
            c[j["preferred_variant"]] += 1
    return out


def main(argv):
    if argv[:1] == ["validate"]:
        bad = 0
        for p in argv[1:]:
            errs = validate(json.load(open(p, encoding="utf-8")))
            print(p, "OK" if not errs else "INVALID:\n  " + "\n  ".join(errs))
            bad += bool(errs)
        return 1 if bad else 0
    if argv[:1] == ["summary"]:
        res = json.load(open(argv[1], encoding="utf-8"))
        print(json.dumps(summary(res, [json.load(open(p, encoding="utf-8")) for p in argv[2:]]), indent=1))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
