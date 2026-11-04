"""
What the default output is on one source tree, to compare two trees.

    python benchmarks/m75/default_output.py snapshot --root TREE OUT.json
    python benchmarks/m75/default_output.py compare MAIN.json BRANCH.json

The snapshot renders the benchmark corpus through the unchanged public paths, plain and
with ``design()``, and records page counts, the text of every PDF page and the DOCX
body. The comparison lists every document that differs, so a change to default output
is a named line in a report, never an assumption.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import time
import warnings
import zipfile


def _sha(data) -> str:
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode("utf-8")).hexdigest()[:16]


def snapshot(root: str, out: str) -> None:
    warnings.simplefilter("ignore")
    sys.path[:0] = [root, os.path.join(root, "benchmarks", "m7"), os.path.join(root, "benchmarks", "m74"),
                    os.path.join(root, "tests")]
    import pymupdf
    from corpus import CORPUS
    from extra_docs import editorial_briefing
    from dynamic_pdf.qa import check_docx
    docs = {name: entry[2] for name, entry in CORPUS.items()}
    docs["editorial_briefing"] = editorial_briefing
    result: dict = {}
    for name, make in docs.items():
        for mode in ("plain", "design"):
            b = make()
            if mode == "plain":
                b._design_mode = None
            else:
                b.design()
            t0 = time.perf_counter()
            pdf = b.render()
            t1 = time.perf_counter()
            docx = b.render_docx()
            t2 = time.perf_counter()
            pages = [p.get_text() for p in pymupdf.open(stream=pdf, filetype="pdf")]
            with zipfile.ZipFile(io.BytesIO(docx)) as z:
                body = z.read("word/document.xml")
            qa = check_docx(docx, visual=True)
            result[f"{name}/{mode}"] = {
                "pdf_pages": len(pages), "pdf_text": [_sha(t) for t in pages], "docx_body": _sha(body),
                "docx_pages": qa.pages, "docx_errors": sorted(f"{f.code}: {f.message}" for f in qa.errors),
                "pdf_s": round(t1 - t0, 3), "docx_s": round(t2 - t1, 3)}
            print(name, mode, len(pages), flush=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1)


def compare(a_path: str, b_path: str) -> int:
    with open(a_path, encoding="utf-8") as f:
        a = json.load(f)
    with open(b_path, encoding="utf-8") as f:
        b = json.load(f)
    same = 0
    for key in sorted(a):
        x, y = a[key], b[key]
        notes = []
        if x["pdf_pages"] != y["pdf_pages"]:
            notes.append(f"PDF pages {x['pdf_pages']} -> {y['pdf_pages']}")
        elif x["pdf_text"] != y["pdf_text"]:
            changed = [i + 1 for i, (p, q) in enumerate(zip(x["pdf_text"], y["pdf_text"])) if p != q]
            notes.append(f"PDF text differs on pages {changed}")
        if x["docx_pages"] != y["docx_pages"]:
            notes.append(f"DOCX pages {x['docx_pages']} -> {y['docx_pages']}")
        if x["docx_body"] != y["docx_body"]:
            notes.append("DOCX body differs")
        if len(x["docx_errors"]) != len(y["docx_errors"]):
            notes.append(f"DOCX QA errors {len(x['docx_errors'])} -> {len(y['docx_errors'])}")
        if notes:
            print(f"{key}: {'; '.join(notes)}")
        else:
            same += 1
    total = lambda d, k: sum(v[k] for v in d.values())                  # noqa: E731
    print(f"{same} of {len(a)} identical. Render time PDF {total(a, 'pdf_s'):.1f}s -> {total(b, 'pdf_s'):.1f}s, "
          f"DOCX {total(a, 'docx_s'):.1f}s -> {total(b, 'docx_s'):.1f}s")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("snapshot")
    s.add_argument("--root", required=True)
    s.add_argument("out")
    c = sub.add_parser("compare")
    c.add_argument("a")
    c.add_argument("b")
    a = ap.parse_args(argv)
    if a.cmd == "snapshot":
        snapshot(os.path.abspath(a.root), os.path.abspath(a.out))
        return 0
    return compare(a.a, a.b)


if __name__ == "__main__":
    sys.exit(main())
