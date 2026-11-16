"""
One objective over ``PageFacts``: hard gates, then one soft score from one weights table.

The gates reject a design for facts with no room for taste (lost words, clipped regions,
type too small). The soft score only orders designs that passed. Its weights are fixed by
hand: no person has calibrated them and no model has learned them (M12 will try).

``compose("smart")`` ranks layouts of one design by the ``layout`` part. ``design_variants``
ranks whole designs by ``fit`` plus the ``visual`` part. Both read this table.
"""
from __future__ import annotations

from typing import Dict, Optional

WEIGHTS: Dict[str, object] = {
    # layout part: soft metrics in 0..1 from the renderer's regions, worth 100 points in all
    "layout": {"utilization": 0.22, "balance": 0.12, "efficiency": 0.20, "readability": 0.20,
               "typography": 0.10, "placement": 0.10, "tables": 0.06},
    "wasted": 25.0,                   # points lost per unit of accidental whitespace
    # visual part: measurements of the page images, around a neutral 60
    "visual": {"base": 60.0, "page_variety": 14.0, "type_contrast": 10.0, "image_share": 8.0,
               "sparse_share": -22.0, "alike_share": -18.0, "last_page_ink": -10.0},
    "fit": 6.0,                       # points per unit of art-direction fit
}


def layout_score(metrics: Dict[str, float], wasted: float) -> float:
    w = WEIGHTS["layout"]
    return round(100 * sum(w[k] * metrics[k] for k in w) - WEIGHTS["wasted"] * wasted, 2)


def visual_index(h: Dict[str, float]) -> float:
    """A single number for ordering valid designs from their page images. Not a quality grade."""
    if not h:
        return 0.0
    w = WEIGHTS["visual"]
    score = w["base"]
    score += w["page_variety"] * h.get("page_variety", 0)
    score += w["type_contrast"] * min(h.get("type_contrast", 1), 3.5) / 3.5
    score += w["image_share"] * min(h.get("image_share", 0) / 0.15, 1)
    score += w["sparse_share"] * h.get("sparse_share", 0)
    score += w["alike_share"] * h.get("alike_share", 0)
    score += w["last_page_ink"] * max(0.0, 0.25 - h.get("last_page_ink", 1) * 2)
    return round(score, 2)


def design_score(fit: float, index: float) -> float:
    """The soft score of a whole design that passed the gates."""
    return round(WEIGHTS["fit"] * fit + index, 3)


def gates(facts, *, content, smallest_type: Optional[float] = None, **reports):
    """The hard failures of a rendered design: its own facts (layout faults, words per page)
    plus the QA reports given (``pdf_report``, ``docx_report``, ``preservation``, ``media``)."""
    from ..qa.visual_critique import hard_failures
    return hard_failures(content=content, layout_errors=facts.layout_errors, smallest_type=smallest_type,
                         critique=facts, **reports)


__all__ = ["WEIGHTS", "design_score", "gates", "layout_score", "visual_index"]
