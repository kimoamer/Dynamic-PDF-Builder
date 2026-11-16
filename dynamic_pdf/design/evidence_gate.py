"""
Safety gate for evidence recipes.

A recipe from ``EVIDENCE_RECIPES`` is an opt-in overlay. It is used on a
document only when its comparison evidence allowed it (``status == "active"``)
and this document passes the safety checks against the existing design. In
every other case the existing design stays and the outcome says why, labelled
``inconclusive`` or ``not_applicable``. Nothing here judges how a page looks.
"""
from __future__ import annotations

import io
import warnings
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from .recipes import EVIDENCE_RECIPES, EvidenceRecipe

GATES = ("evidence", "preview")
MAX_EXTRA_PAGES = 0.15          # share of the baseline pages a recipe may add (at least one page)


class RecipeOutcome(BaseModel):
    recipe: Optional[str] = None
    status: str = "inconclusive"            # active | inconclusive | not_applicable
    applied: bool = False                   # False: the existing design was kept
    reasons: List[str] = Field(default_factory=list)
    evidence: Dict[str, List[str]] = Field(default_factory=dict)
    not_applied: Dict[str, str] = Field(default_factory=dict)
    baseline: Optional[dict] = None
    proposed: Optional[dict] = None


def resolve_recipe(name: str, plan, bilingual: bool) -> Tuple[Optional[EvidenceRecipe], Optional[str]]:
    """The recipe to try on this document, or None and why not."""
    profile = plan.decision.profile
    script = "rtl" if plan.decision.direction == "rtl" else ("bilingual" if bilingual else "ltr")
    if name == "auto":
        for r in EVIDENCE_RECIPES.values():
            if r.applies(profile, script):
                return r, None
        return None, f"no evidence recipe covers {profile.value} ({script})"
    r = EVIDENCE_RECIPES[name]
    if not r.applies(profile, script):
        return None, f"{name} does not cover {profile.value} ({script})"
    return r, None


def split_tables(geo, doc) -> int:
    """Tables placed on more than one page."""
    pages: Dict[int, set] = {}
    for reg in geo.regions:
        if reg.role == "table" and reg.block is not None:
            pages.setdefault(reg.block, set()).add(reg.page)
    return sum(len(p) > 1 for p in pages.values())


def measure(sem, theme, policy=None) -> dict:
    """Layout facts of one design, from a real render."""
    from ..intelligence.geometry import Geometry
    from ..intelligence.scoring import score_layout
    from ..layout.engine import LayoutEngine
    geo = Geometry()
    doc = sem.to_document()
    eng = LayoutEngine(doc, policy=policy, theme=theme, geometry=geo)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        eng.render(io.BytesIO())
    sc = score_layout(geo, doc, theme)
    return {"pages": eng.page_count, "valid": sc.valid, "hard_errors": list(sc.hard_errors),
            "split_tables": split_tables(geo, doc)}


def safety_failures(base: dict, prop: dict) -> List[str]:
    """Why ``prop`` may not replace ``base`` (empty = safe)."""
    out = []
    if not prop["valid"]:
        new = [e for e in prop["hard_errors"] if e not in base["hard_errors"]]
        out.append("hard layout errors: " + "; ".join(new or prop["hard_errors"]))
    if prop["split_tables"] > base["split_tables"]:
        out.append(f"tables split across pages: {base['split_tables']} → {prop['split_tables']}")
    limit = base["pages"] + max(1, int(base["pages"] * MAX_EXTRA_PAGES))
    if prop["pages"] > limit:
        out.append(f"pages: {base['pages']} → {prop['pages']} (limit {limit})")
    return out


def run_gate(name: str, gate: str, base_sem, sem, plan, requested, brand, base_theme, policy):
    """Returns the (semantic document, plan) to render; ``plan.recipe_outcome`` records the outcome."""
    from . import apply_plan, plan_design
    from .planner import drop_short_contents, fit_pages, plan_layout
    recipe, why_not = resolve_recipe(name, plan, base_sem.stats.bilingual)
    if recipe is None:
        plan.recipe_outcome = RecipeOutcome(recipe=None if name == "auto" else name, status="not_applicable",
                                            reasons=[why_not + "; existing design kept"])
        return sem, plan
    outcome = RecipeOutcome(recipe=recipe.name, status=recipe.status,
                            evidence={k: list(v) for k, v in recipe.evidence.items()},
                            not_applied=dict(recipe.not_applied))
    if gate == "evidence" and recipe.status != "active":
        outcome.reasons = [recipe.status_reason or "comparison evidence does not support this recipe yet",
                           "existing design kept"]
        plan.recipe_outcome = outcome
        return sem, plan

    prop_plan = plan_design(base_sem, requested, brand, base_theme=base_theme, evidence=recipe)
    prop_sem = apply_plan(base_sem, prop_plan)
    prop_plan.layout = plan_layout(prop_sem, prop_plan)
    fit_pages(prop_sem, prop_plan, policy)
    drop_short_contents(prop_sem, prop_plan)

    outcome.baseline = measure(sem, plan.theme, policy)
    outcome.proposed = measure(prop_sem, prop_plan.theme, policy)
    failures = safety_failures(outcome.baseline, outcome.proposed)
    if failures:
        outcome.status = "inconclusive"
        outcome.reasons = failures
    if failures and gate == "evidence":
        outcome.reasons = failures + ["existing design kept"]
        plan.recipe_outcome = outcome
        return sem, plan
    outcome.applied = True
    if not failures:
        outcome.reasons = ["safety checks passed"]
    prop_plan.recipe_outcome = outcome
    return prop_sem, prop_plan
