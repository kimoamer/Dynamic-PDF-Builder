"""
dynamic-pdf CLI — render Markdown or JSON to PDF from the command line.

Usage:
    dynamic-pdf render input.md -o output.pdf --theme claude
    dynamic-pdf render input.md -o output.docx --design auto
    dynamic-pdf render input.md --format both
    dynamic-pdf render input.json -o output.pdf
    dynamic-pdf render invoice.md --data invoice.json --data lines=lines.csv
    dynamic-pdf batch letter.md --data people.csv -o out/ --name "letter-{{ id }}"
    dynamic-pdf lint input.md [--json] [--strict]
    dynamic-pdf review input.md [-o pages/] [--json]
    dynamic-pdf compare old.md new.md -o changes.docx
    dynamic-pdf render input.md --direction auto --grammar --brand brand.json
    dynamic-pdf variants input.md -o designs/ -n 3
    dynamic-pdf themes
    dynamic-pdf schema -o document.schema.json
    dynamic-pdf version
"""
import argparse
import sys
import os


def main():
    parser = argparse.ArgumentParser(
        prog="dynamic-pdf",
        description="Dynamic PDF Builder — generate beautiful PDFs from Markdown or JSON.",
    )
    sub = parser.add_subparsers(dest="command", help="Available commands")

    # ─── render ───
    render_p = sub.add_parser("render", help="Render a Markdown or JSON file to PDF")
    render_p.add_argument("input", help="Input file (.md or .json)")
    render_p.add_argument("-o", "--output", default=None,
                          help="Output path; .pdf or .docx (default: <input>.<format>)")
    render_p.add_argument("-f", "--format", choices=["pdf", "docx", "xlsx", "both"], default=None,
                          help="Output format (default: from --output extension, else pdf)")
    render_p.add_argument("--design", default="auto", metavar="PROFILE",
                          help='"auto" (default), a profile (executive_report, proposal, ...) '
                               'or "none" for classic theme rendering')
    render_p.add_argument("-t", "--theme", default="claude", help="Theme name (default: claude)")
    render_p.add_argument("--section-numbers", action="store_true", help="Enable section numbering")
    render_p.add_argument("--permissive", action="store_true",
                          help="Render failed blocks as visible markers instead of failing (exit code 3 if degraded)")
    render_p.add_argument("--compose", choices=["off", "smart"], default="off",
                          help="CPU-only intelligent page composition (default: off)")
    render_p.add_argument("--report", default=None, metavar="FILE",
                          help="Write the composition report (JSON) to FILE")
    render_p.add_argument("--qa", action="store_true",
                          help="Inspect rendered pages, auto-fix layout defects (bounded retries), report findings")
    render_p.add_argument("--allow-remote-assets", action="store_true",
                          help="Allow fetching http(s) images (public hosts only)")
    render_p.add_argument("--data", action="append", default=[], metavar="[NAME=]FILE",
                          help="Fill the input as a template from a .json/.csv/.xlsx file (repeatable)")
    _design_args(render_p)
    render_p.add_argument("--variants", type=int, default=None, metavar="N",
                          help="Try N art directions and export the recommended valid one")

    # ─── variants ───
    var_p = sub.add_parser("variants", help="Write several art-directed designs and explain the recommendation")
    var_p.add_argument("input", help="Input file (.md or .json)")
    var_p.add_argument("-o", "--output", default=None, metavar="DIR",
                       help="Directory for the designs and decisions.json (default: <input>-variants)")
    var_p.add_argument("-n", type=int, default=3, help="How many directions to try, 1 to 5 (default: 3)")
    var_p.add_argument("-t", "--theme", default="claude", help="Theme name (default: claude)")
    var_p.add_argument("--office", action="store_true", help="Also open each DOCX in LibreOffice")
    var_p.add_argument("--permissive", action="store_true", help=argparse.SUPPRESS)
    var_p.add_argument("--allow-remote-assets", action="store_true",
                       help="Allow fetching http(s) images (public hosts only)")
    _design_args(var_p)

    # ─── batch ───
    batch_p = sub.add_parser("batch", help="Render one document per data record from a template")
    batch_p.add_argument("template", help="Template file (.md or .json)")
    batch_p.add_argument("--data", required=True, metavar="FILE",
                         help="Records: a .csv/.xlsx file or a JSON list")
    batch_p.add_argument("--context", action="append", default=[], metavar="[NAME=]FILE",
                         help="Data shared by every document (repeatable)")
    batch_p.add_argument("-o", "--output", default=".", metavar="DIR", help="Output directory")
    batch_p.add_argument("--name", default="document-{{ index }}",
                         help='File name template (default: "document-{{ index }}")')
    batch_p.add_argument("-f", "--format", choices=["pdf", "docx", "both"], default="pdf")
    batch_p.add_argument("--design", default="auto", metavar="PROFILE")
    batch_p.add_argument("-t", "--theme", default=None)
    batch_p.add_argument("--permissive", action="store_true")
    batch_p.add_argument("--allow-remote-assets", action="store_true")

    # ─── lint ───
    lint_p = sub.add_parser("lint", help="Report content warnings (totals, references, formats ...); edits nothing")
    lint_p.add_argument("input", help="Input file (.md or .json)")
    lint_p.add_argument("--json", action="store_true", help="Print the warnings as JSON")
    lint_p.add_argument("--strict", action="store_true", help="Exit with code 1 when there are warnings")

    # ─── review ───
    rev_p = sub.add_parser("review", help="List what a reader would notice on the pages, each with what to change")
    rev_p.add_argument("input", help="Input file (.md or .json)")
    rev_p.add_argument("-o", "--output", default=None, metavar="DIR", help="Save one PNG a page here")
    rev_p.add_argument("--dpi", type=int, default=60, help="Resolution of the page images (default 60)")
    rev_p.add_argument("--json", action="store_true", help="Print the review as JSON")
    rev_p.add_argument("-t", "--theme", default="claude", help="Theme name (default: claude)")
    rev_p.add_argument("--design", default=None, metavar="PROFILE", help='Design profile, e.g. "auto"')

    # ─── compare ───
    cmp_p = sub.add_parser("compare", help="Mark what changed between two versions: tracked changes in Word, a review copy in PDF")
    cmp_p.add_argument("old", help="Earlier version (.md or .json)")
    cmp_p.add_argument("new", help="Later version (.md or .json)")
    cmp_p.add_argument("-o", "--output", default="changes.docx", help="Output .docx or .pdf (default: changes.docx)")
    cmp_p.add_argument("--reviewer", default=None, help='Name on each change (default "Changes")')
    cmp_p.add_argument("-t", "--theme", default="claude", help="Theme name (default: claude)")

    # ─── themes ───
    sub.add_parser("themes", help="List available themes")

    # ─── schema ───
    schema_p = sub.add_parser("schema", help="Print the JSON Schema of a document (for JSON input and agents)")
    schema_p.add_argument("-o", "--output", default=None, help="Write the schema to this file instead")

    # ─── version ───
    sub.add_parser("version", help="Show version")

    args = parser.parse_args()

    if args.command in ("render", "variants"):
        from .utils.errors import DynamicPDFError
        try:
            (_cmd_render if args.command == "render" else _cmd_variants)(args)
        except DynamicPDFError as e:
            print(f"Error: {type(e).__name__}: {e}", file=sys.stderr)
            sys.exit(2)
    elif args.command == "batch":
        from .utils.errors import DynamicPDFError
        try:
            _cmd_batch(args)
        except DynamicPDFError as e:
            print(f"Error: {type(e).__name__}: {e}", file=sys.stderr)
            for note in getattr(e, "__notes__", ()):
                print(f"  {note}", file=sys.stderr)
            sys.exit(2)
    elif args.command == "lint":
        _cmd_lint(args)
    elif args.command == "review":
        _cmd_review(args)
    elif args.command == "compare":
        import argparse as _ap
        old = _load(_ap.Namespace(input=args.old, theme=args.theme, data=None), None)
        new = _load(_ap.Namespace(input=args.new, theme=args.theme, data=None), None)
        res = new.compared_with(old, reviewer=args.reviewer).export(args.output)
        print(f"changes: {res.docx_path or res.pdf_path}")
    elif args.command == "themes":
        _cmd_themes()
    elif args.command == "schema":
        _cmd_schema(args.output)
    elif args.command == "version":
        _cmd_version()
    else:
        parser.print_help()


def _design_args(p):
    p.add_argument("--direction", default=None, metavar="NAME",
                   help='Art direction: "auto" or a name (corporate_conservative, editorial_modern, ...)')
    p.add_argument("--grammar", action="store_true", help="Follow the packaged approved design grammar")
    p.add_argument("--brand", default=None, metavar="FILE", help="Brand kit as a JSON file (colours, fonts, logo)")
    p.add_argument("--ranker", default=None, metavar="auto|FILE",
                   help='Learned selector among the valid designs: "auto" (the packaged model) or a model file')


def _brand(path):
    if not path:
        return None
    import json
    from .design import BrandKit
    with open(path, "r", encoding="utf-8") as f:
        return BrandKit(**json.load(f))


def _load(args, policy):
    from . import DocumentBuilder
    input_path = args.input
    if not os.path.exists(input_path):
        print(f"Error: File not found: {input_path}", file=sys.stderr)
        sys.exit(1)
    with open(input_path, "r", encoding="utf-8") as f:
        content = f.read()
    is_json = os.path.splitext(input_path)[1].lower() == ".json"
    context = None
    if getattr(args, "data", None):
        from .templates import load_context, render_template
        context = load_context(args.data)
        if not is_json:
            content = render_template(content, context)
    if is_json:
        import json
        from .schema.document import Document
        payload = json.loads(content)
        if context is not None:
            from .templates import render_json_template
            payload = render_json_template(payload, context)
        if args.theme != "claude":
            payload["theme"] = args.theme
        doc = Document.model_validate(payload)
        builder = DocumentBuilder(theme=doc.theme, policy=policy)
        builder._meta = doc.meta
        builder._blocks = list(doc.blocks)
        builder._source_kind = "json"
        builder._source_text = content
        return builder
    return DocumentBuilder.from_markdown(content, theme=args.theme, policy=policy)


def _cmd_variants(args):
    from .design.directions import DIRECTIONS
    policy = _policy_from_args(args)
    builder = _load(args, policy)
    families = None
    if args.direction and args.direction != "auto":
        if args.direction not in DIRECTIONS:
            print(f"Error: unknown direction {args.direction!r}; choose from {sorted(DIRECTIONS)}", file=sys.stderr)
            sys.exit(1)
        families = [args.direction]
    if not 1 <= args.n <= len(DIRECTIONS):
        print(f"Error: -n must be between 1 and {len(DIRECTIONS)}", file=sys.stderr)
        sys.exit(1)
    out = args.output or os.path.splitext(args.input)[0] + "-variants"
    made = builder.design_variants(n=args.n, families=families, brand=_brand(args.brand), office=args.office,
                                   grammar=True if args.grammar else None, ranker=args.ranker)
    paths = made.export(out)
    for v in made.variants:
        r = v.report
        mark = "*" if v is made.recommended else " "
        line = f"{mark} {v.id}: {r.status}, {r.pages} pages, fit {r.fit:g}, index {r.index:g}, score {r.score:g}"
        print(line + (f" -> {', '.join(paths[v.id].values())}" if paths.get(v.id) else ""))
        for f in r.hard_failures[:3]:
            print(f"    rejected: {f}")
    print(f"recommended: {made.recommended.id if made.recommended else 'none'}")
    for why in made.reasons:
        print(f"  - {why}")
    print(f"decisions: {os.path.join(out, 'decisions.json')}")
    if made.recommended is None:
        sys.exit(4)


def _policy_from_args(args):
    from .policy import RenderPolicy
    from .assets import AssetPolicy
    return RenderPolicy(
        error_mode="permissive" if args.permissive else "strict",
        assets=AssetPolicy(allow_remote=bool(args.allow_remote_assets)),
    )


def _report(paths, diagnostics):
    for d in diagnostics:
        print(f"{d['level']}: [{d['code']}] {d['message']}", file=sys.stderr)
    degraded = any(d["level"] == "error" for d in diagnostics)
    mark = "⚠ Rendered (degraded)" if degraded else "✓ Rendered"
    for path in paths:
        size_kb = os.path.getsize(path) / 1024
        print(f"{mark} {path} ({size_kb:.1f} KB)")
    if degraded:
        sys.exit(3)


def _cmd_render(args):
    input_path = args.input
    out_ext = os.path.splitext(args.output)[1].lower().lstrip(".") if args.output else ""
    fmt = args.format or (out_ext if out_ext in ("pdf", "docx", "xlsx") else "pdf")
    stem = os.path.splitext(args.output)[0] if args.output else os.path.splitext(input_path)[0]
    policy = _policy_from_args(args)
    builder = _load(args, policy)
    if args.section_numbers:
        builder.section_numbering(True)
    builder.design(None if args.design == "none" else args.design, brand=_brand(args.brand),
                   direction=args.direction, variants=args.variants, grammar=args.grammar, ranker=args.ranker)
    if args.compose != "off":
        builder.compose(args.compose)

    targets = ["pdf", "docx"] if fmt == "both" else [fmt]
    diagnostics = []
    paths = []
    for target in targets:
        path = args.output if (args.output and fmt != "both") else f"{stem}.{target}"
        res = builder.export(path, format=target, qa=args.qa)
        diagnostics += res.diagnostics
        paths.append(path)
        if res.composition and target == targets[-1]:
            c = res.composition
            print(f"composition: {c['strategy']} ({c['page_count']} pages, "
                  f"{c['render_attempts']} renders + {c['repair_renders']} repairs, {c['time_s']}s)")
            if args.report:
                import json
                with open(args.report, "w", encoding="utf-8") as fh:
                    json.dump(c, fh, ensure_ascii=False, indent=1)
        if res.design is not None and target == targets[-1]:
            print(f"design: {res.design.recommended or 'stable designed output (no variant passed)'}")
            for why in res.design.reasons[:4]:
                print(f"  - {why}")
        if res.status != "ok":
            print(f"{target} status: {res.status} — " + "; ".join(res.status_reasons), file=sys.stderr)
        for rep in res.qa.values():
            print(rep.summary())
            for fix in rep.fixes_applied:
                print(f"  fixed: {fix}")
            for f in rep.findings:
                print(f"  {f.severity}: [{f.code}] {f.message}", file=sys.stderr)
    _report(paths, diagnostics)


def _cmd_batch(args):
    from .templates import load_context, load_data, render_batch
    from .utils.errors import TemplateError
    with open(args.template, "r", encoding="utf-8") as f:
        template = f.read()
    records = load_data(args.data)
    if not isinstance(records, list):
        raise TemplateError(f"{args.data} must hold a list of records")
    results = render_batch(
        template, records, args.output,
        kind="json" if args.template.lower().endswith(".json") else "markdown",
        name=args.name, formats=("pdf", "docx") if args.format == "both" else (args.format,),
        design=None if args.design == "none" else args.design, theme=args.theme,
        policy=_policy_from_args(args), context=load_context(args.context))
    paths, diagnostics = [], []
    for res in results:
        paths += [p for p in (res.pdf_path, res.docx_path) if p]
        diagnostics += res.diagnostics
    _report(paths, diagnostics)


def _cmd_review(args):
    builder = _load(args, None)
    if args.design:
        builder.design(args.design)
    result = builder.review(args.output, dpi=args.dpi)
    if args.json:
        import json
        print(json.dumps(result, ensure_ascii=False, indent=1))
    else:
        for i in result["issues"]:
            where = f"page {i['page']}" if i["page"] else "document"
            print(f"{i['severity']:7} {where:9} {i['code']}: {i['message']}")
            if i["fix"]:
                print(f"{'':17} fix: {i['fix']}")
        print(f"{result['pages']} pages, {len(result['issues'])} issues; "
              + ("passed" if result["passed"] else "has errors")
              + (f"; page images in {args.output}" if args.output else ""))
    sys.exit(0 if result["passed"] else 1)


def _cmd_lint(args):
    from . import DocumentBuilder
    if not os.path.exists(args.input):
        print(f"Error: File not found: {args.input}", file=sys.stderr)
        sys.exit(1)
    with open(args.input, "r", encoding="utf-8") as f:
        content = f.read()
    if args.input.lower().endswith(".json"):
        import json
        from .schema.document import Document
        doc = Document.model_validate(json.loads(content))
        builder = DocumentBuilder(theme=doc.theme)
        builder._meta, builder._blocks = doc.meta, list(doc.blocks)
    else:
        builder = DocumentBuilder.from_markdown(content)
    warnings = builder.lint()
    if args.json:
        import json
        print(json.dumps([w.to_dict() for w in warnings], ensure_ascii=False, indent=1))
    else:
        for w in warnings:
            print(w)
        print(f"{len(warnings)} warning{'s' if len(warnings) != 1 else ''}" if warnings else "no warnings")
    if args.strict and warnings:
        sys.exit(1)


def _cmd_themes():
    from .themes import list_themes
    themes = list_themes()
    print(f"Available themes ({len(themes)}):")
    for name in themes:
        print(f"  • {name}")


def _cmd_schema(output):
    import json
    from .schema.document import Document
    text = json.dumps(Document.model_json_schema(), ensure_ascii=False, indent=1)
    if output:
        with open(output, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    else:
        print(text)


def _cmd_version():
    from . import __version__
    print(f"Dynamic PDF Builder v{__version__}")


if __name__ == "__main__":
    main()
