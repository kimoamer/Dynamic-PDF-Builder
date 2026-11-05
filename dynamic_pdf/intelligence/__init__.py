"""Intelligent, CPU-only page composition (deterministic; no external services)."""
from .composer import CandidateResult, ComposeOptions, Composer, CompositionReport
from .media_options import AutoMediaOptions
from .geometry import Geometry, Region
from .scoring import LayoutScore, score_layout

__all__ = ["AutoMediaOptions", "ComposeOptions", "Composer", "CompositionReport", "CandidateResult",
           "Geometry", "Region", "LayoutScore", "score_layout"]
