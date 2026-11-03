"""Intelligent, CPU-only page composition (deterministic; no external services)."""
from .composer import CandidateResult, ComposeOptions, Composer, CompositionReport
from .geometry import Geometry, Region
from .scoring import LayoutScore, score_layout

__all__ = ["ComposeOptions", "Composer", "CompositionReport", "CandidateResult",
           "Geometry", "Region", "LayoutScore", "score_layout"]
