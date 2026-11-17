"""
A small render worker: JSON requests in, JSON responses out, one subprocess per request.

    python -m dynamic_pdf.service --timeout 60 --max-pages 500 --max-memory-mb 2048 < requests.jsonl

Each input line is a request::

    {"id": "1", "markdown": "# Hi"}                    # or "document": {...} (the JSON schema)
    {"id": "2", "markdown": "# {{ name }}", "data": {"name": "Ada"}, "format": "docx",
     "design": "auto", "theme": "claude"}

and each output line a response ``{"id", "status", "format", "content_base64", "page_count",
"diagnostics"}`` or ``{"id", "status": "error", "error"}``. The ``ResourceLimits`` and the
error mode belong to the operator (command line or ``render_request``), never to a request:
time is enforced by killing the subprocess, memory with ``RLIMIT_AS`` where the platform has
it, pages after rendering. Standard library only.
"""
import argparse
import base64
import dataclasses
import json
import os
import subprocess
import sys
import tempfile
from typing import Optional

from . import settings
from .policy import RenderPolicy, ResourceLimits

REQUEST_KEYS = {"id", "markdown", "document", "data", "format", "design", "theme"}


def _limit_memory(mb: Optional[int]):
    if not mb:
        return None
    try:
        import resource
    except ImportError:                 # Windows: no RLIMIT_AS
        return None

    def apply():
        resource.setrlimit(resource.RLIMIT_AS, (mb * 1024 * 1024, mb * 1024 * 1024))
    return apply


def render_request(request: dict, policy: Optional[RenderPolicy] = None) -> dict:
    """Render one request in a fresh subprocess under ``policy.limits``."""
    policy = policy or RenderPolicy()
    rid = request.get("id") if isinstance(request, dict) else None
    if not isinstance(request, dict) or set(request) - REQUEST_KEYS:
        extra = sorted(set(request) - REQUEST_KEYS) if isinstance(request, dict) else "not an object"
        return {"id": rid, "status": "error", "error": f"invalid request: unknown fields {extra}"}
    limits = policy.limits
    config = json.dumps({"error_mode": policy.error_mode, "limits": dataclasses.asdict(limits),
                         "allow_remote": policy.assets.allow_remote})
    try:
        proc = subprocess.run([sys.executable, "-m", "dynamic_pdf.service", "--worker", config],
                              input=json.dumps(request), capture_output=True, text=True,
                              timeout=limits.render_timeout_s, preexec_fn=_limit_memory(limits.max_memory_mb))
    except subprocess.TimeoutExpired:
        return {"id": rid, "status": "error",
                "error": f"ResourceLimitError: render time exceeds limit ({limits.render_timeout_s} s)"}
    if proc.returncode != 0 or not proc.stdout.strip():
        tail = (proc.stderr.strip().splitlines() or [""])[-1]
        hint = f"; memory limit is {limits.max_memory_mb} MB" if limits.max_memory_mb else ""
        return {"id": rid, "status": "error", "error": f"worker failed (exit {proc.returncode}){hint}: {tail}"}
    return json.loads(proc.stdout)


def _worker(config: dict, request: dict) -> dict:
    """Runs inside the subprocess."""
    from .assets import AssetPolicy
    from .builder import DocumentBuilder
    from .policy import check_limit
    limits = ResourceLimits(**config["limits"])
    policy = RenderPolicy(error_mode=config["error_mode"], limits=limits,
                          assets=AssetPolicy(allow_remote=config["allow_remote"]))
    rid, fmt = request.get("id"), request.get("format", "pdf")
    try:
        if fmt not in ("pdf", "docx"):
            raise ValueError(f"format must be 'pdf' or 'docx', got {fmt!r}")
        if ("markdown" in request) == ("document" in request):
            raise ValueError("a request needs exactly one of 'markdown' or 'document'")
        from .templates import builder_from_payload, render_document
        theme = request.get("theme")
        if "data" in request:
            text = request["markdown"] if "markdown" in request else json.dumps(request["document"])
            b = render_document(text, request["data"], kind="markdown" if "markdown" in request else "json",
                                theme=theme, policy=policy)
        elif "markdown" in request:
            b = DocumentBuilder.from_markdown(request["markdown"], theme=theme, policy=policy)
        else:
            b = builder_from_payload(request["document"], theme=theme, policy=policy)
        b.design(request.get("design", "auto"))
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "out." + fmt)
            res = b.export(path, format=fmt)
            if res.page_count is not None and limits.max_pages is not None:
                check_limit("Page count", res.page_count, limits.max_pages)
            with open(path, "rb") as fh:
                content = base64.b64encode(fh.read()).decode("ascii")
        return {"id": rid, "status": res.status, "format": fmt, "content_base64": content,
                "page_count": res.page_count, "diagnostics": res.diagnostics}
    except Exception as e:              # every failure becomes a response, never a traceback
        return {"id": rid, "status": "error", "error": f"{type(e).__name__}: {e}"}


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="python -m dynamic_pdf.service", description=__doc__.split("\n\n")[0])
    p.add_argument("--timeout", type=float, default=settings.number("RENDER_TIMEOUT_S", 60.0),
                   help="seconds per request (default DYNAMIC_PDF_RENDER_TIMEOUT_S, or 60)")
    p.add_argument("--max-pages", type=int, default=settings.number("MAX_PAGES", 500, int))
    p.add_argument("--max-memory-mb", type=int, default=settings.number("MAX_MEMORY_MB", 2048, int),
                   help="0 = no limit; POSIX only")
    p.add_argument("--permissive", action="store_true", default=settings.get("ERROR_MODE") == "permissive")
    p.add_argument("--allow-remote-assets", action="store_true")
    p.add_argument("--worker", help=argparse.SUPPRESS)
    args = p.parse_args(argv)
    if args.worker:
        print(json.dumps(_worker(json.loads(args.worker), json.loads(sys.stdin.read()))))
        return
    from .assets import AssetPolicy
    policy = RenderPolicy(error_mode="permissive" if args.permissive else "strict",
                          assets=AssetPolicy(allow_remote=args.allow_remote_assets),
                          limits=ResourceLimits(render_timeout_s=args.timeout, max_pages=args.max_pages,
                                                max_memory_mb=args.max_memory_mb or None))
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError as e:
            response = {"id": None, "status": "error", "error": f"invalid JSON: {e}"}
        else:
            response = render_request(request, policy)
        print(json.dumps(response), flush=True)


if __name__ == "__main__":
    main()
