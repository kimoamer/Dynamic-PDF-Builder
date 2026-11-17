"""QA findings, report and artifact manifest."""
from __future__ import annotations

import hashlib
from typing import List, Optional, Tuple

from pydantic import BaseModel, Field

ERROR, WARNING = "error", "warning"


class Finding(BaseModel):
    severity: str                       # "error" | "warning"
    code: str                           # overflow, clipped, overlap, blank_page, stranded_heading, ...
    message: str
    format: str = "pdf"
    page: Optional[int] = None          # 1-based
    bbox: Optional[Tuple[float, float, float, float]] = None
    text: Optional[str] = None          # text involved (used to map back to blocks)
    fixable: bool = False


class QAReport(BaseModel):
    format: str
    pages: int = 0
    findings: List[Finding] = Field(default_factory=list)
    attempts: int = 1
    fixes_applied: List[str] = Field(default_factory=list)
    sha256: Optional[str] = None
    page_images: List[str] = Field(default_factory=list)
    unverified: List[str] = Field(default_factory=list)   # checks that could not run
    page_fill: List[float] = Field(default_factory=list)

    @property
    def errors(self) -> List[Finding]:
        return [f for f in self.findings if f.severity == ERROR]

    @property
    def passed(self) -> bool:
        """No errors *and* every requested check actually ran."""
        return not self.errors and not self.unverified

    @property
    def status(self) -> str:
        """"pass" | "fail" | "unverified" (no errors found, but checks were skipped)."""
        if self.errors:
            return "fail"
        if self.unverified:
            return "unverified"
        return "pass"

    def summary(self) -> str:
        counts = {}
        for f in self.findings:
            counts[f.code] = counts.get(f.code, 0) + 1
        state = self.status.upper()
        detail = ", ".join(f"{k}×{v}" for k, v in sorted(counts.items())) or "no findings"
        extra = f"; unverified: {', '.join(self.unverified)}" if self.unverified else ""
        return f"{self.format.upper()} QA {state}: {self.pages} pages; {detail}; attempts={self.attempts}{extra}"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
