"""
What the environment can set, in one place.

The library is configured in Python: pass a ``RenderPolicy``, a provider, a folder. A deployment
that is configured from outside (a container, a function, a process manager) can give the same
things as ``DYNAMIC_PDF_*`` variables. What a caller passes always wins, then the variable, then
the default. Variables are read when they are needed, never at import, so a host may set them
after importing the library. ``docs/CONFIGURATION.md`` lists them.
"""
import os
from typing import Callable, Optional

PREFIX = "DYNAMIC_PDF_"
SETTINGS = {
    "ERROR_MODE": "strict or permissive: what a failing block does when no RenderPolicy is passed (default strict)",
    "RENDER_TIMEOUT_S": "seconds a request of the render worker may take (default: none; the worker's command line: 60)",
    "MAX_PAGES": "pages a request of the render worker may produce (default: none; the worker's command line: 500)",
    "MAX_MEMORY_MB": "memory of the render worker's subprocess, POSIX only (default: none; the worker's command line: 2048)",
    "AI_MODEL": "model the optional AI layer asks when the caller names none",
    "AI_CACHE": "folder for the AI layer's replies, or off for none (default ~/.cache/dynamic-pdf-builder/ai)",
    "PREFERENCES_DIR": "a human_preferences folder where accept() records a kept design when the caller names none",
    "QA_BACKEND": "pymupdf or pdfium: the PDF reader the checks use when both are installed",
    "MERMAID_JS": "path of a local mermaid.js, so diagrams render without the network",
    "MCP_OUT": "the only folder the MCP server writes to (default mcp-out)",
}


def get(name: str, default: Optional[str] = None) -> Optional[str]:
    """The variable ``DYNAMIC_PDF_<name>``, or ``default`` when it is unset or empty."""
    if name not in SETTINGS:
        raise KeyError(f"{name} is not a setting of this library")
    return os.environ.get(PREFIX + name, "").strip() or default


def number(name: str, default=None, cast: Callable = float):
    raw = get(name)
    if raw is None:
        return default
    try:
        return cast(raw)
    except ValueError:
        raise ValueError(f"{PREFIX}{name} must be a number, got {raw!r}") from None
