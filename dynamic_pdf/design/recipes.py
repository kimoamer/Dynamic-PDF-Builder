"""
Design recipes — the visual "house style" for each document profile.

A recipe is a set of *typographic and layout decisions* (type ramp, measure,
spacing rhythm, header/footer treatment, numbering, navigation). Recipes
never touch content: they only restyle, number and add navigation (TOC).
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from ..schema.theme import Theme
from ..themes.registry import get_theme
from .profile import Profile, ProfileDecision


class DesignRecipe(BaseModel):
    profile: Profile
    base_theme: str
    body_family: Optional[str] = None
    heading_family: Optional[str] = None
    base_size: float = 10.5
    line_height: float = 1.45
    heading_scale: List[float] = Field(default_factory=lambda: [1.9, 1.45, 1.2, 1.05, 1.0, 0.95])
    density: float = 1.0                       # spacing multiplier (0.8 compact … 1.25 airy)
    margins: Tuple[float, float, float, float] = (64, 64, 68, 68)   # top, bottom, left, right
    first_line_indent: float = 0.0             # 0 = block paragraphs
    drop_cap: bool = False
    heading_accent_bar: bool = False
    section_numbering: bool = False
    toc: str = "auto"                          # "auto" | "never" | "always"
    toc_min_headings: int = 6
    header_style: str = "line"
    footer_style: str = "minimal"
    header_enabled: bool = True
    skip_first_page_header: bool = True
    page_number_format: str = "Page {n} of {total}"
    heading_ramp_locked: bool = False          # the planner leaves the ramp alone
    body_columns: int = 1                      # columns for runs of prose (planner decides where)
    notes: List[str] = Field(default_factory=list)


_SERIF = "Times-Roman"
_SANS = "Helvetica"

RECIPES = {
    Profile.EXECUTIVE_REPORT: DesignRecipe(
        profile=Profile.EXECUTIVE_REPORT, base_theme="claude", base_size=10.5, line_height=1.45,
        heading_scale=[2.0, 1.45, 1.18, 1.05, 1.0, 0.95], density=1.05,
        heading_accent_bar=True, section_numbering=True, toc_min_headings=6,
        header_style="line", footer_style="minimal",
        notes=["evidence-led hierarchy: large H1, numbered sections, quiet running header"]),
    Profile.PROPOSAL: DesignRecipe(
        profile=Profile.PROPOSAL, base_theme="modern_minimal", base_size=11, line_height=1.55,
        heading_scale=[2.2, 1.5, 1.2, 1.05, 1.0, 0.95], density=1.2, margins=(72, 72, 78, 78),
        heading_accent_bar=True, toc="never", header_style="minimal", footer_style="page_only",
        page_number_format="{n}",
        notes=["editorial, airy rhythm; no TOC so the narrative leads"]),
    Profile.CORPORATE_MEMO: DesignRecipe(
        profile=Profile.CORPORATE_MEMO, base_theme="modern_minimal", base_size=10.5,
        line_height=1.4, heading_scale=[1.5, 1.25, 1.1, 1.0, 1.0, 0.95], density=0.85,
        margins=(60, 60, 64, 64), toc="never", header_enabled=False,
        footer_style="page_only", page_number_format="{n} / {total}",
        notes=["dense but legible; no ornament, no running header"]),
    Profile.ACADEMIC_REPORT: DesignRecipe(
        profile=Profile.ACADEMIC_REPORT, base_theme="academic", body_family=_SERIF,
        heading_family=_SERIF, base_size=11, line_height=1.5,
        heading_scale=[1.55, 1.3, 1.12, 1.0, 1.0, 0.95], density=1.0,
        margins=(72, 72, 72, 72), first_line_indent=18, section_numbering=True,
        toc_min_headings=5, header_style="minimal", footer_style="centered",
        page_number_format="{n}",
        notes=["serif text face, indented paragraphs, stable numbering"]),
    Profile.TECHNICAL_MANUAL: DesignRecipe(
        profile=Profile.TECHNICAL_MANUAL, base_theme="claude", base_size=10, line_height=1.45,
        heading_scale=[1.8, 1.4, 1.18, 1.05, 1.0, 0.95], density=0.95,
        section_numbering=True, toc="always", toc_min_headings=3,
        header_style="line", footer_style="minimal",
        notes=["numbered procedures and always-on TOC for navigation"]),
    Profile.DATA_REPORT: DesignRecipe(
        profile=Profile.DATA_REPORT, base_theme="data_report", base_size=9.5, line_height=1.35,
        heading_scale=[1.8, 1.35, 1.15, 1.05, 1.0, 0.95], density=0.85,
        margins=(56, 56, 54, 54), section_numbering=True, toc_min_headings=6,
        header_style="line", footer_style="minimal",
        notes=["compact type and narrow margins to give tables and charts room"]),
    Profile.FINANCIAL_REPORT: DesignRecipe(
        profile=Profile.FINANCIAL_REPORT, base_theme="corporate_dark", base_size=10,
        line_height=1.4, heading_scale=[1.9, 1.4, 1.15, 1.05, 1.0, 0.95], density=0.9,
        margins=(60, 60, 60, 60), section_numbering=True, toc_min_headings=5,
        header_style="line", footer_style="minimal",
        notes=["restrained, numeric-friendly typography"]),
    Profile.LETTER: DesignRecipe(
        profile=Profile.LETTER, base_theme="modern_minimal", body_family=_SERIF,
        heading_family=_SERIF, base_size=11, line_height=1.45,
        heading_scale=[1.3, 1.15, 1.05, 1.0, 1.0, 1.0], density=1.0,
        margins=(84, 72, 80, 80), toc="never", header_enabled=False,
        footer_style="page_only", page_number_format="{n}",
        notes=["formal letter: no cover, no running header, generous margins"]),
    Profile.INVOICE: DesignRecipe(
        profile=Profile.INVOICE, base_theme="modern_minimal", base_size=10, line_height=1.35,
        heading_scale=[1.8, 1.2, 1.05, 1.0, 1.0, 1.0], density=0.85, toc="never",
        header_enabled=False, footer_style="page_only", page_number_format="{n} / {total}",
        notes=["formal and restrained; tables carry the content"]),
    Profile.GENERAL: DesignRecipe(
        profile=Profile.GENERAL, base_theme="claude", base_size=10.5, line_height=1.5,
        density=1.0, toc_min_headings=8, header_style="line", footer_style="minimal",
        notes=["balanced general-purpose layout"]),
}


def recipe_for(decision: ProfileDecision, bilingual: bool = False) -> DesignRecipe:
    r = RECIPES[decision.profile].model_copy(deep=True)
    if bilingual:
        # Mixed documents keep the Latin text face; Arabic paragraphs/runs switch
        # to the Arabic face individually, each aligned to its own direction.
        r.first_line_indent = 0
        r.drop_cap = False
        r.line_height = max(r.line_height, 1.55)
        r.notes.append("bilingual: Latin face for English, Amiri per Arabic paragraph/run, "
                       "per-paragraph alignment, no indents")
    elif decision.direction == "rtl":
        # Amiri is bundled with full Arabic coverage; Latin runs still render.
        r.body_family = "Amiri"
        r.heading_family = "Amiri"
        r.first_line_indent = 0
        r.drop_cap = False
        r.line_height = max(r.line_height, 1.6)    # Arabic needs taller line boxes
        r.notes.append("RTL: Arabic face, right-aligned blocks, taller leading, no indents")
    return r


class EvidenceRecipe(BaseModel):
    """An opt-in overlay on the existing recipe, built only from accepted reference patterns.

    ``evidence`` maps each change to pattern ids accepted in
    the reviewed ``pattern_review.json`` of the offline analyzer (a test checks them).
    ``not_applied`` records what was asked for but has no accepted evidence.
    ``status`` comes from the baseline/proposed comparison in
    ``benchmarks/m74``: only "active" recipes are used by default.
    """
    name: str
    title: str
    profiles: Tuple[Profile, ...]
    scripts: Tuple[str, ...]                   # "ltr" | "rtl" | "bilingual"
    base_size: float
    line_height: float
    heading_scale: Optional[List[float]] = None    # None: the existing ramp stays
    body_columns: int = 1
    evidence: Dict[str, Tuple[str, ...]]
    not_applied: Dict[str, str] = Field(default_factory=dict)
    status: str = "inconclusive"               # "active" | "inconclusive"
    status_reason: str = ""

    def applies(self, profile: Profile, script: str) -> bool:
        return profile in self.profiles and script in self.scripts


_H1_RAMP = "heading-ramp-H1 >2.6× body"
_NO_MARGIN = "side-margin patterns need more evidence; recipe margins unchanged"
_REPORTS = (Profile.EXECUTIVE_REPORT, Profile.PROPOSAL, Profile.DATA_REPORT, Profile.FINANCIAL_REPORT,
            Profile.CORPORATE_MEMO, Profile.GENERAL, Profile.TECHNICAL_MANUAL)

EVIDENCE_RECIPES: Dict[str, EvidenceRecipe] = {r.name: r for r in (
    EvidenceRecipe(
        name="financial_corporate", title="Financial / Corporate",
        profiles=(Profile.FINANCIAL_REPORT, Profile.CORPORATE_MEMO), scripts=("ltr",),
        base_size=10.0, line_height=1.25, heading_scale=[2.75, 1.6, 1.25, 1.05, 1.0, 0.95],
        evidence={"base_size": ("body-size-9.5–10.4 pt",), "line_height": ("leading-≤1.25×",),
                  "heading_scale": (_H1_RAMP,), "accent": ("restrained-accent",)},
        not_applied={"margins": _NO_MARGIN,
                     "table padding": "table-padding needs more evidence; planner padding unchanged"},
        status_reason="no measured gain on either document: no page or table-split saved, lower readability "
                      "score, and a heading separated from its table; no human review yet"),
    EvidenceRecipe(
        name="editorial_executive", title="Editorial / Executive",
        profiles=(Profile.EXECUTIVE_REPORT, Profile.PROPOSAL, Profile.DATA_REPORT), scripts=("ltr",),
        base_size=10.0, line_height=1.38, heading_scale=[2.75, 1.6, 1.25, 1.05, 1.0, 0.95], body_columns=2,
        evidence={"base_size": ("body-size-9.5–10.4 pt",), "line_height": ("leading-1.26–1.40×",),
                  "heading_scale": (_H1_RAMP,), "body_columns": ("multi-column-body",)},
        not_applied={"whitespace": "no accepted pattern measures whitespace; " + _NO_MARGIN},
        status_reason="safe on all three documents, but columns were used on one fictional briefing only, "
                      "the proposal lost body size, and no human review exists yet"),
    EvidenceRecipe(
        name="arabic_bilingual", title="Arabic / Bilingual",
        profiles=_REPORTS, scripts=("rtl", "bilingual"),
        base_size=12.0, line_height=1.4,
        evidence={"base_size": ("body-size-≥11.5 pt",), "line_height": ("leading-1.26–1.40×",),
                  "direction": ("script-arabic_rtl", "script-bilingual")},
        not_applied={"heading ramp": "tried and withdrawn: at 12 pt an H1 of 2.75× wrapped bilingual headings "
                                     "mid-phrase and overlapped the Arabic cover subtitle",
                     "facing pages": "accepted, but recipes have no signal for two-sided printing",
                     "columns": "the column flow is left-to-right only",
                     "spacing": "no accepted pattern measures Arabic spacing beyond leading"},
        status_reason="larger body text is safe on three of four documents; the long Arabic report goes over "
                      "the page limit and falls back; no human review yet"),
)}


def apply_evidence_recipe(recipe: DesignRecipe, evidence: EvidenceRecipe) -> DesignRecipe:
    """The existing recipe with an evidence recipe's accepted changes on top."""
    r = recipe.model_copy(deep=True)
    r.base_size = evidence.base_size
    r.line_height = evidence.line_height
    if evidence.heading_scale:
        r.heading_scale = list(evidence.heading_scale)
        r.heading_ramp_locked = True
    r.body_columns = evidence.body_columns
    r.notes.append(f"evidence recipe {evidence.name}: {r.base_size:g}pt / {r.line_height:g}, "
                   f"H1 {r.heading_scale[0]:g}× body")
    return r


def apply_recipe(recipe: DesignRecipe, base: Optional[Theme] = None) -> Theme:
    """Return a new Theme expressing ``recipe`` (``base`` defaults to the recipe's theme)."""
    t = (base or get_theme(recipe.base_theme)).model_copy(deep=True)
    t.name = f"{t.name}+{recipe.profile.value}"
    ty, sp, hf, dec = t.typography, t.spacing, t.header_footer, t.decorations
    if recipe.body_family:
        ty.body_family = recipe.body_family
    if recipe.heading_family:
        ty.heading_family = recipe.heading_family
    from .tokens import font_available
    for attr in ("body_family", "heading_family"):
        if not font_available(getattr(ty, attr)):
            # deterministic, explicit fallback instead of a silent substitution
            setattr(ty, attr, _SANS)
            recipe.notes.append(f"{attr.replace('_', ' ')} not installed; using {_SANS}")
    ty.base_size = ty.body_size = recipe.base_size
    ty.line_height = recipe.line_height
    ty.heading_scale = list(recipe.heading_scale)
    ty.heading_h1_size = ty.heading_h2_size = ty.heading_h3_size = 0
    d = recipe.density
    sp.page_margin_top, sp.page_margin_bottom, sp.page_margin_left, sp.page_margin_right = recipe.margins
    sp.paragraph_spacing_after = round(recipe.base_size * 0.6 * d, 1)
    sp.block_gap = round(recipe.base_size * 0.9 * d, 1)
    sp.heading_spacing_before = [round(v * d, 1) for v in (26, 20, 16, 12, 10, 8)]
    sp.heading_spacing_after = [round(v * d, 1) for v in (10, 8, 6, 5, 4, 4)]
    sp.first_line_indent = recipe.first_line_indent
    dec.drop_cap_enabled = recipe.drop_cap
    dec.heading_accent_bar = recipe.heading_accent_bar
    hf.enabled = True
    if recipe.header_enabled:
        hf.header_style = recipe.header_style
        hf.height = 40.0
    else:
        hf.header_style = "none"
        hf.height = 0.0
    hf.footer_style = recipe.footer_style
    hf.show_page_number = True
    hf.page_number_format = recipe.page_number_format
    hf.skip_first_page_header = recipe.skip_first_page_header
    return t
