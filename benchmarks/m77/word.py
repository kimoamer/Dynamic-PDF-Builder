"""
The measured comparison again, as Microsoft Word lays the DOCX out.

    python benchmarks/m77/run.py OUT --keep-files
    python benchmarks/m77/word.py OUT

Adds slug.word.jpg sheets and a "word" entry per demonstration to OUT/results.json.
Windows with Word installed only. A result holds for the Word version it names, and no other.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from tools.design_learning.word import export  # noqa: E402

spec = importlib.util.spec_from_file_location("m77run", os.path.join(ROOT, "benchmarks", "m77", "run.py"))
run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run)


def main(out: str) -> int:
    word = os.path.join(out, "word")
    summary = export(out, word)
    print(summary)
    with open(os.path.join(word, "word.json"), encoding="utf-8") as f:
        pages = {r["file"]: r["pages"] for r in json.load(f)["files"]}
    path = os.path.join(out, "results.json")
    with open(path, encoding="utf-8") as f:
        results = json.load(f)
    for row in results["demonstrations"]:
        slug = f"{row['rule'].replace('.', '-')}--{row['document']}"
        if f"{slug}.grammar" not in pages:
            continue
        pair = []
        for label in ("baseline", "grammar"):
            with open(os.path.join(word, f"{slug}.{label}.pdf"), "rb") as f:
                pair.append(f.read())
        change = run.changed_pages(*pair)
        order = sorted(range(len(change["change_by_page"])), key=lambda i: -change["change_by_page"][i])
        run.sheet(pair[0], pair[1], sorted(order[:3]), os.path.join(out, slug + ".word.jpg"))
        row["docx"]["word"] = {"baseline": pages[f"{slug}.baseline"], "with_rule": pages[f"{slug}.grammar"],
                               "pixels": {k: v for k, v in change.items() if k != "change_by_page"}}
    results["word_version"] = f"Microsoft Word {summary['word_build']}"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)
    return 0 if not summary["failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
