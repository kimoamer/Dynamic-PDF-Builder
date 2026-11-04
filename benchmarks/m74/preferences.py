"""
Human A/B/Tie judgments exported by the M7.4 gallery.

    python benchmarks/m74/preferences.py validate FILE...
    python benchmarks/m74/preferences.py summary RESULTS_JSON FILE...

Same shape as the M7 preference files, with the variants ``baseline`` and
``proposed`` and ``document`` set to ``recipe/document``. This module never
creates a judgment, and ``summary`` drops any judgment whose layout ids no
longer match the results (the layout changed after it was judged).
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from typing import Dict, List

HERE = os.path.dirname(os.path.abspath(__file__))
FORMAT = "dynamic-pdf-builder/m74-human-preferences"
VARIANTS = {"baseline", "proposed"}

_spec = importlib.util.spec_from_file_location("m7_preferences", os.path.join(HERE, "..", "m7", "preferences.py"))
_m7 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_m7)


def validate(data: dict) -> List[str]:
    return _m7.validate(data, FORMAT, VARIANTS)


def summary(results: dict, files: List[dict]) -> Dict[str, Dict[str, int]]:
    """Per document: counts of proposed / baseline / tie across reviewers (hash-checked)."""
    docs = results["documents"]
    out: Dict[str, Dict[str, int]] = {}
    for f in files:
        if validate(f):
            continue
        for j in f["judgments"]:
            d = docs.get(j["document"])
            if not d or any(d[v]["layout_id"] != (j.get("layout_id") or {}).get(v) for v in VARIANTS):
                continue        # judged a different rendering: stale
            c = out.setdefault(j["document"], {"proposed": 0, "baseline": 0, "tie": 0})
            c[j["preferred_variant"]] += 1
    return out


def main(argv):
    if argv[:1] == ["validate"]:
        bad = 0
        for p in argv[1:]:
            with open(p, encoding="utf-8") as f:
                errs = validate(json.load(f))
            print(p, "OK" if not errs else "INVALID:\n  " + "\n  ".join(errs))
            bad += bool(errs)
        return 1 if bad else 0
    if argv[:1] == ["summary"]:
        with open(argv[1], encoding="utf-8") as f:
            res = json.load(f)
        files = []
        for p in argv[2:]:
            with open(p, encoding="utf-8") as f:
                files.append(json.load(f))
        print(json.dumps(summary(res, files), indent=1))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
