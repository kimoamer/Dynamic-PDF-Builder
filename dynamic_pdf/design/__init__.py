"""Design layer: profiles, recipes, brand kits and compiled tokens."""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from ..core.normalize import SemanticDocument
from ..schema.blocks import TOCBlock
from ..schema.theme import Theme
from .brand import BrandKit, apply_brand
from .profile import Profile, ProfileDecision, select_profile, resolve_profile_name
from .recipes import (DesignRecipe, EVIDENCE_RECIPES, EvidenceRecipe, RECIPES, apply_evidence_recipe,
                      apply_recipe, recipe_for)
from .tokens import DesignTokens, compile_tokens, heading_size
from .reviewed_quality import apply_evidence_typography, apply_reviewed_quality


class DesignPlan(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    decision: ProfileDecision
    recipe: DesignRecipe
    theme: Theme
    tokens: DesignTokens
    section_numbering: bool
    toc_inserted: bool = False
    notes: List[str] = Field(default_factory=list)
    layout: Optional[object] = None          # planner.LayoutPlan
    recipe_outcome: Optional[object] = None  # evidence_gate.RecipeOutcome, when one was requested

    def explain(self) -> dict:
        out = {
            "profile": self.decision.profile.value,
            "explicit": self.decision.explicit,
            "direction": self.decision.direction,
            "reasons": self.decision.reasons,
            "scores": self.decision.scores,
            "confidence": self.decision.confidence,
            "uncertain": self.decision.uncertain,
            "audience": self.decision.audience,
            "base_theme": self.recipe.base_theme,
            "typography": {
                "body": f"{self.theme.typography.body_family} {self.tokens.body_size}pt / "
                        f"{self.tokens.line_height}",
                "headings": [round(s, 1) for s in self.tokens.heading_sizes[:3]],
            },
            "section_numbering": self.section_numbering,
            "toc_inserted": self.toc_inserted,
            "notes": self.recipe.notes + self.notes,
            "layout": ([f"{d.target}: {d.decision}" for d in self.layout.decisions]
                       if self.layout is not None else []),
            "estimated_pages": getattr(self.layout, "estimated_pages", None),
            "warnings": self.tokens.warnings,
        }
        if self.recipe_outcome is not None:
            out["evidence_recipe"] = self.recipe_outcome.model_dump()
        return out


def plan_design(doc: SemanticDocument, requested: Optional[str] = None,
                brand: Optional[BrandKit] = None, base_theme: Optional[Theme] = None,
                evidence: Optional[EvidenceRecipe] = None) -> DesignPlan:
    """Select profile → recipe → theme (+brand) → tokens. Pure; content untouched."""
    decision = select_profile(doc, requested)
    recipe = recipe_for(decision, bilingual=doc.stats.bilingual and doc.direction == "ltr")
    if evidence is not None:
        recipe = apply_evidence_recipe(recipe, evidence)
    theme = apply_recipe(recipe, base_theme)
    notes: List[str] = []
    if brand:
        notes += apply_brand(theme, brand)
    script = "bilingual" if doc.stats.bilingual else doc.direction
    notes += apply_reviewed_quality(theme, script=script, preserve_brand=bool(brand))
    if evidence is not None:
        notes += apply_evidence_typography(theme, recipe)
    tokens = compile_tokens(theme)
    return DesignPlan(decision=decision, recipe=recipe, theme=theme, tokens=tokens,
                      section_numbering=recipe.section_numbering or doc.meta.section_numbering,
                      notes=notes)


def apply_plan(doc: SemanticDocument, plan: DesignPlan) -> SemanticDocument:
    """Apply structural (navigation-only) decisions: numbering, auto TOC."""
    out = doc.model_copy(deep=True)
    out.meta.section_numbering = plan.section_numbering
    r = plan.recipe
    want_toc = (r.toc == "always" and doc.stats.headings >= 2) or (
        r.toc == "auto" and doc.stats.headings >= r.toc_min_headings)
    if want_toc and not doc.stats.has_toc:
        pos = 0
        while pos < len(out.blocks) and out.blocks[pos].type in ("cover_page", "watermark"):
            pos += 1
        # deepest level that keeps the TOC to about one page (≤ 28 entries)
        depth = 1
        for d in (3, 2):
            if sum(1 for o in doc.outline if o.level <= d) <= 28:
                depth = d
                break
        out.blocks.insert(pos, TOCBlock(depth=depth))
        plan.toc_inserted = True
    return out


__all__ = [
    "BrandKit", "DesignPlan", "DesignRecipe", "DesignTokens", "Profile", "ProfileDecision",
    "RECIPES", "apply_brand", "apply_plan", "apply_recipe", "compile_tokens", "heading_size",
    "plan_design", "recipe_for", "resolve_profile_name", "select_profile",
]
