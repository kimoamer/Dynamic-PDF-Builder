"""
dynamic-pdf CLI — render Markdown or JSON to PDF from the command line.

Usage:
    dynamic-pdf render input.md -o output.pdf --theme claude
    dynamic-pdf render input.md -o output.docx --design auto
    dynamic-pdf render input.md --format both
    dynamic-pdf render input.json -o output.pdf
    dynamic-pdf themes
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
    render_p.add_argument("-f", "--format", choices=["pdf", "docx", "both"], default=None,
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

    # ─── themes ───
    sub.add_parser("themes", help="List available themes")

    # ─── version ───
    sub.add_parser("version", help="Show version")

    args = parser.parse_args()

    if args.command == "render":
        from .utils.errors import DynamicPDFError
        try:
            _cmd_render(args)
        except DynamicPDFError as e:
            print(f"Error: {type(e).__name__}: {e}", file=sys.stderr)
            sys.exit(2)
    elif args.command == "themes":
        _cmd_themes()
    elif args.command == "version":
        _cmd_version()
    else:
        parser.print_help()


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
    from . import DocumentBuilder

    input_path = args.input
    if not os.path.exists(input_path):
        print(f"Error: File not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    out_ext = os.path.splitext(args.output)[1].lower().lstrip(".") if args.output else ""
    fmt = args.format or (out_ext if out_ext in ("pdf", "docx") else "pdf")
    stem = os.path.splitext(args.output)[0] if args.output else os.path.splitext(input_path)[0]
    ext = os.path.splitext(input_path)[1].lower()
    policy = _policy_from_args(args)

    with open(input_path, "r", encoding="utf-8") as f:
        content = f.read()

    if ext == ".json":
        import json
        from .schema.document import Document
        payload = json.loads(content)
        if args.theme != "claude":
            payload["theme"] = args.theme
        doc = Document.model_validate(payload)
        builder = DocumentBuilder(theme=doc.theme, policy=policy)
        builder._meta = doc.meta
        builder._blocks = list(doc.blocks)
        builder._source_kind = "json"
        builder._source_text = content
    else:
        builder = DocumentBuilder.from_markdown(content, theme=args.theme, policy=policy)
    if args.section_numbers:
        builder.section_numbering(True)
    builder.design(None if args.design == "none" else args.design)
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
        for rep in res.qa.values():
            print(rep.summary())
            for fix in rep.fixes_applied:
                print(f"  fixed: {fix}")
            for f in rep.findings:
                print(f"  {f.severity}: [{f.code}] {f.message}", file=sys.stderr)
    _report(paths, diagnostics)


def _cmd_themes():
    from .themes import list_themes
    themes = list_themes()
    print(f"Available themes ({len(themes)}):")
    for name in themes:
        print(f"  • {name}")


def _cmd_version():
    print("Dynamic PDF Builder v0.3.0")


if __name__ == "__main__":
    main()
