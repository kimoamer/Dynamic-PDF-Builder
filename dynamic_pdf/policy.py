"""
Render policy: error semantics, diagnostics and resource limits.

A ``RenderPolicy`` belongs to the *caller* (application/service), never to the
document payload, so untrusted JSON/Markdown cannot loosen security settings.

Error modes
-----------
``strict`` (default)
    Any block, asset or renderer failure raises a typed ``DynamicPDFError``
    and no output artifact is written.
``permissive``
    Failures are rendered as a visible marker, recorded as ``error``
    diagnostics, and the result status is ``degraded``.

In both modes, content-preserving fallbacks (e.g. Mermaid source shown as code
because the browser renderer is unavailable) are recorded as ``warning``
diagnostics — never silently.
"""
from __future__ import annotations

import contextvars
import warnings
from dataclasses import dataclass, field, asdict
from typing import List, Optional

from .assets import AssetPolicy
from .utils.errors import DynamicPDFError, ResourceLimitError

STRICT = "strict"
PERMISSIVE = "permissive"


@dataclass(frozen=True)
class ResourceLimits:
    max_input_chars: int = 2_000_000       # Markdown / text input
    max_blocks: int = 10_000               # top-level blocks per document
    max_table_cells: int = 250_000         # per table
    max_mermaid_chars: int = 50_000        # per diagram source
    renderer_timeout_s: float = 20.0       # external renderer (browser) timeout


@dataclass(frozen=True)
class RenderPolicy:
    error_mode: str = STRICT
    assets: AssetPolicy = field(default_factory=AssetPolicy)
    limits: ResourceLimits = field(default_factory=ResourceLimits)

    def __post_init__(self):
        if self.error_mode not in (STRICT, PERMISSIVE):
            raise ValueError(f"error_mode must be 'strict' or 'permissive', got {self.error_mode!r}")

    @property
    def strict(self) -> bool:
        return self.error_mode == STRICT


@dataclass
class Diagnostic:
    level: str                      # "error" | "warning"
    code: str                       # e.g. "block_render_failed", "asset_refused"
    message: str
    block_index: Optional[int] = None
    block_type: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


class DiagnosticCollector:
    """Collects diagnostics for one render; status is derived from contents."""

    language = "en"          # document language for engine-generated labels

    def __init__(self, policy: RenderPolicy):
        self.policy = policy
        self.items: List[Diagnostic] = []
        self.block_index: Optional[int] = None
        self.block_type: Optional[str] = None

    @property
    def errors(self) -> List[Diagnostic]:
        return [d for d in self.items if d.level == "error"]

    @property
    def warnings(self) -> List[Diagnostic]:
        return [d for d in self.items if d.level == "warning"]

    @property
    def status(self) -> str:
        if self.errors:
            return "degraded"
        return "ok"

    def warn(self, code: str, message: str) -> None:
        self.items.append(Diagnostic("warning", code, message, self.block_index, self.block_type))
        warnings.warn(f"[dynamic_pdf:{code}] {message}", RuntimeWarning, stacklevel=3)

    def fail(self, code: str, message: str, exc: Optional[BaseException] = None,
             error_cls=None) -> None:
        """Record an error. In strict mode raise a typed exception instead."""
        if self.policy.strict:
            if isinstance(exc, DynamicPDFError):
                raise exc
            cls = error_cls or DynamicPDFError
            raise cls(message) from exc
        self.items.append(Diagnostic("error", code, message, self.block_index, self.block_type))


_current: contextvars.ContextVar[Optional[DiagnosticCollector]] = contextvars.ContextVar(
    "dynamic_pdf_diagnostics", default=None)


def current() -> DiagnosticCollector:
    """Return the active collector (a strict throwaway one outside a render)."""
    col = _current.get()
    if col is None:
        col = DiagnosticCollector(RenderPolicy())
    return col


def activate(collector: DiagnosticCollector):
    return _current.set(collector)


def deactivate(token) -> None:
    _current.reset(token)


def check_limit(name: str, value: int, maximum: int) -> None:
    if value > maximum:
        raise ResourceLimitError(f"{name} ({value}) exceeds limit ({maximum})")


__all__ = [
    "RenderPolicy", "ResourceLimits", "AssetPolicy", "Diagnostic",
    "DiagnosticCollector", "STRICT", "PERMISSIVE", "current", "check_limit",
]
