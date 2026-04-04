"""
dynamic-pdf CLI — render Markdown or JSON to PDF from the command line.

Usage:
    dynamic-pdf render input.md -o output.pdf --theme claude
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
    render_p.add_argument("-o", "--output", default=None, help="Output PDF path (default: <input>.pdf)")
    render_p.add_argument("-t", "--theme", default="claude", help="Theme name (default: claude)")
    render_p.add_argument("--section-numbers", action="store_true", help="Enable section numbering")

    # ─── themes ───
    sub.add_parser("themes", help="List available themes")

    # ─── version ───
    sub.add_parser("version", help="Show version")

    args = parser.parse_args()

    if args.command == "render":
        _cmd_render(args)
    elif args.command == "themes":
        _cmd_themes()
    elif args.command == "version":
        _cmd_version()
    else:
        parser.print_help()


def _cmd_render(args):
    from . import DocumentBuilder

    input_path = args.input
    if not os.path.exists(input_path):
        print(f"Error: File not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    output_path = args.output or os.path.splitext(input_path)[0] + ".pdf"
    ext = os.path.splitext(input_path)[1].lower()

    with open(input_path, "r", encoding="utf-8") as f:
        content = f.read()

    if ext == ".json":
        import json
        from . import render_from_json
        payload = json.loads(content)
        if args.theme != "claude":
            payload["theme"] = args.theme
        result = render_from_json(payload)
        if result["success"]:
            import base64
            with open(output_path, "wb") as out:
                out.write(base64.b64decode(result["pdf_base64"]))
            size_kb = result["metadata"]["file_size_bytes"] / 1024
            print(f"✓ Rendered {output_path} ({size_kb:.1f} KB)")
        else:
            print("Error: Rendering failed", file=sys.stderr)
            sys.exit(1)
    else:
        # Treat as Markdown
        builder = DocumentBuilder.from_markdown(content, theme=args.theme)
        if args.section_numbers:
            builder.section_numbering(True)
        builder.render(output_path)
        size_kb = os.path.getsize(output_path) / 1024
        print(f"✓ Rendered {output_path} ({size_kb:.1f} KB)")


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
