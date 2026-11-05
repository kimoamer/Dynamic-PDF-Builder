"""python -m tools.design_learning <command>: see docs/LEARNING_PIPELINE.md."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

from . import pipeline as P
from . import preferences as A


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.design_learning", description=__doc__)
    ap.add_argument("--config", help="paths file (default config/design-learning.json, or DPB_LEARNING_CONFIG)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("paths", help="print the folders in use")
    sub.add_parser("status", help="what is imported, reviewed, published and trained")
    i = sub.add_parser("import", help="register new PDFs from the inbox, or copy them in from a folder")
    i.add_argument("source", nargs="?")
    sub.add_parser("analyze", help="measure every PDF and rebuild the atlas and page graphs")
    sub.add_parser("validate", help="check page coverage and the grammar")
    r = sub.add_parser("review", help="draw pages nobody has looked at, or record notes")
    r.add_argument("--record", help="JSONL of notes to add")
    r.add_argument("--limit", type=int, default=24)
    a = sub.add_parser("approve", help="record who approved which rules")
    a.add_argument("--rules", required=True, help="comma-separated ids, or all")
    a.add_argument("--reviewer-type", required=True, choices=P.REVIEWER_TYPES)
    a.add_argument("--model")
    a.add_argument("--reviewer")
    sub.add_parser("publish", help="write the approved grammar into the package")
    g = sub.add_parser("preferences", help="AI design comparisons")
    gs = g.add_subparsers(dest="step", required=True)
    x = gs.add_parser("generate")
    x.add_argument("batch")
    x.add_argument("--docs")
    x.add_argument("--n", type=int, default=4)
    x.add_argument("--baseline", action="store_true", help="also render each design without the grammar")
    x = gs.add_parser("sheets")
    x.add_argument("batch")
    x.add_argument("--pairs", type=int, default=2)
    x.add_argument("--repeats", type=int, default=1)
    x.add_argument("--docs", help="only these documents, comma separated")
    x.add_argument("--source", choices=("pdf", "word"), default="pdf", help="word: DOCX pages as Microsoft Word lays them out")
    x = gs.add_parser("word", help="render a batch's DOCX through Microsoft Word")
    x.add_argument("batch")
    x = gs.add_parser("record")
    x.add_argument("batch")
    x.add_argument("answers")
    x.add_argument("--model", required=True)
    x.add_argument("--date", required=True)
    x.add_argument("--method", default="blind whole-document sheets, labels A/B, PDF pages viewed as images")
    x.add_argument("--source", choices=("pdf", "word"), default="pdf")
    gs.add_parser("check")
    x = gs.add_parser("readiness", help="is the dataset ready for a training experiment? Trains nothing")
    x.add_argument("--out", help="write the report to this folder")
    t = sub.add_parser("train", help="train the optional variant ranker (needs lightgbm)")
    t.add_argument("--name", required=True, help="model name under training/models")
    t.add_argument("--min-pairs", type=int, default=200)
    e = sub.add_parser("evaluate", help="read a model's training record and gate")
    e.add_argument("--name", required=True)
    c = sub.add_parser("trace", help="generate one fictional document and show the rules and selector that ran")
    c.add_argument("document")
    c.add_argument("--no-grammar", action="store_true")
    c.add_argument("--model", help="path of a trained ranker")
    args = ap.parse_args(argv)
    p = P.paths(args.config)
    dataset = os.path.join(p["ai_preferences"], "ai-preferences.jsonl")

    def work(name):
        return os.path.join(p["ai_preferences"], "batches", name)

    if args.cmd == "paths":
        P.report(p)
    elif args.cmd == "status":
        P.report(P.do_status(p))
    elif args.cmd == "import":
        P.report(P.do_import(p, args.source))
    elif args.cmd == "analyze":
        P.report(P.do_analyze(p))
    elif args.cmd == "validate":
        errors = P.do_validate(p)
        P.report({"ok": not errors, "errors": errors})
        return 1 if errors else 0
    elif args.cmd == "review":
        P.report(P.do_review(p, args.record, args.limit))
    elif args.cmd == "approve":
        P.report(P.do_approve(p, args.rules.split(","), args.reviewer_type, args.model, args.reviewer))
    elif args.cmd == "publish":
        P.report(P.do_publish(p))
    elif args.cmd == "preferences":
        if args.step == "generate":
            P.report(A.generate(work(args.batch), args.docs.split(",") if args.docs else None, args.n, baseline=args.baseline))
        elif args.step == "sheets":
            P.report(A.sheets(work(args.batch), args.pairs, repeats=args.repeats, source=args.source,
                              docs=args.docs.split(",") if args.docs else None))
        elif args.step == "word":
            from .word import export
            P.report(export(os.path.join(work(args.batch), "renders"), os.path.join(work(args.batch), "word"), 300))
        elif args.step == "record":
            P.report(A.record(work(args.batch), args.answers, dataset, model=args.model, date=args.date, method=args.method,
                              source=args.source))
        elif args.step == "readiness":
            from .readiness import report as readiness
            P.report(readiness(dataset, os.path.join(p["ai_preferences"], "batches"), p["document_split"], args.out))
        else:
            P.report(A.check(dataset))
    elif args.cmd == "train":
        script = os.path.join(P.ROOT, "scripts", "train_variant_ranker.py")
        out = os.path.join(p["models"], args.name + ".txt")
        return subprocess.call([sys.executable, script, "--dataset", dataset, "--batches", os.path.join(p["ai_preferences"], "batches"),
                                "--split", p["document_split"], "--out", out, "--min-pairs", str(args.min_pairs)])
    elif args.cmd == "trace":
        P.report(A.trace(args.document, not args.no_grammar, args.model))
    elif args.cmd == "evaluate":
        P.report(P._load(os.path.join(p["models"], args.name + ".json"), {"error": "no such model"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
