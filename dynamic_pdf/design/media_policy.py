"""
What each kind of document allows an image to do.

A policy proposes; it decides nothing about a page. Measurement checks the room, a real
render proves the layout, and a person judges the quality. Weights and ratios here are
starting values: none has been calibrated against human review.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, FrozenSet, Tuple

MEDIA_POLICY_VERSION = "m78.1"

COMPACT, FULL_WIDTH, FLOAT = "compact", "full_width", "float"


@dataclass(frozen=True)
class MediaPolicy:
    profile: str
    styles: Tuple[str, ...]               # in the order this kind of document prefers them
    float_roles: FrozenSet[str] = frozenset()
    compact_ratio: float = 0.56           # of the content width
    compact_height: float = 0.48          # of the content height
    full_height: float = 0.72


_PHOTO = frozenset({"photo"})
_EDITORIAL = MediaPolicy("editorial", (FLOAT, FULL_WIDTH, COMPACT), _PHOTO)
_DATA = MediaPolicy("data", (FULL_WIDTH, COMPACT))
_TECHNICAL = MediaPolicy("technical", (FULL_WIDTH, COMPACT), compact_ratio=0.7)
_ACADEMIC = MediaPolicy("academic", (COMPACT, FULL_WIDTH), compact_ratio=0.7)
_SMALL = MediaPolicy("correspondence", (COMPACT,), compact_ratio=0.38, compact_height=0.3)

_POLICIES: Dict[str, MediaPolicy] = {
    "executive_report": _EDITORIAL, "proposal": _EDITORIAL, "general": _EDITORIAL,
    "financial_report": _DATA, "data_report": _DATA,
    "technical_manual": _TECHNICAL,
    "academic_report": _ACADEMIC,
    "letter": _SMALL, "corporate_memo": _SMALL, "invoice": _SMALL,
}


def media_policy_for(profile: str) -> MediaPolicy:
    return _POLICIES.get(profile, _POLICIES["general"])


@dataclass(frozen=True)
class ArchetypeCapability:
    """How far a layout archetype has been carried. Only evidence moves these flags."""
    implemented_pdf: bool = False
    implemented_docx: bool = False
    validated_lo_builds: Tuple[str, ...] = ()
    validated_word_builds: Tuple[str, ...] = ()
    human_approved: bool = False
    allowed_roles: FrozenSet[str] = frozenset()

    @property
    def status(self) -> str:
        return "optional" if self.implemented_pdf and self.implemented_docx else "unsupported"


_BUILT = ArchetypeCapability(implemented_pdf=True, implemented_docx=True)

ARCHETYPE_CAPABILITIES: Dict[str, ArchetypeCapability] = {
    "section_opener": _BUILT,          # takes no image yet
    "performance_page": _BUILT,        # needs measured data; no KPI is ever invented
    "parallel_ledger": _BUILT,         # needs comparison data
    "statement_page": ArchetypeCapability(),
    "editorial_sink": ArchetypeCapability(),
    "image_slab_divider": ArchetypeCapability(),
    "figure_matrix": _BUILT,
    "image_text_panel": _BUILT,
    "paired_row_columns": _BUILT,
}
