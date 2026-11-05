"""
Design directions: five coherent ways to set the same document.

A direction differs from the others in composition, type, image handling, rhythm, density
and page bands, not only in colour. The rules here are written out as code: the planner
reads nothing from a reference library at run time. Colours are defaults that a brand
kit replaces.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

from ..schema.page_system import Band, BandRow, Logo, PageSystem
from .archetypes import mix
from .profile import Profile
from .recipes import DesignRecipe



@dataclass(frozen=True)
class Direction:
    id: str
    name: str
    summary: str
    base_theme: str
    heading_family: str
    body_family: str
    arabic_family: str
    base_size: float
    line_height: float
    heading_scale: Tuple[float, ...]
    density: float
    margins: Tuple[float, float, float, float]      # top, bottom, start, end
    primary: str
    accent: str
    cover: str                 # type_centered | image_top | full | split | masthead
    opener: str                # none | rule | hang | slab | page
    kpi: str                   # tiles | ruled | band | hero_page
    table: str                 # open | ledger | default
    hero_image: str            # inline | bleed | band
    side_image: float          # width share of a side image; 0 keeps images in the column
    side_alternates: bool
    statement: str             # plain | inline | page
    bands: str                 # line | folio | quiet | filled | institutional
    numbered: bool = False
    drop_cap: bool = False
    lead: bool = False
    toc_min: int = 5
    hang: float = 0.0          # how far headings hang into the start margin
    break_major: bool = False  # large sections open a page
    extras: Dict[str, float] = field(default_factory=dict)

    def margins_for(self, rtl: bool) -> Tuple[float, float, float, float]:
        top, bottom, start, end = self.margins
        return (top, bottom, end, start) if rtl else (top, bottom, start, end)

    def recipe(self, profile: Profile, rtl: bool, density: float = 1.0) -> DesignRecipe:
        """The direction as a recipe, so type, spacing and the planner work as they do
        for any designed document. Arabic is set larger and looser than Latin."""
        size = self.base_size + (1.5 if rtl else 0.0)
        height = max(self.line_height, 1.65) if rtl else self.line_height
        return DesignRecipe(
            profile=profile, base_theme=self.base_theme, body_family=self.body_family,
            heading_family=self.heading_family, base_size=size, line_height=height,
            heading_scale=list(self.heading_scale), density=self.density * density,
            margins=self.margins_for(rtl), drop_cap=self.drop_cap and not rtl,
            section_numbering=self.numbered, toc="auto", toc_min_headings=self.toc_min,
            heading_ramp_locked=True, notes=[f"art direction: {self.name}"])


DIRECTIONS: Dict[str, Direction] = {d.id: d for d in (
    Direction(
        id="corporate_conservative", name="Corporate Conservative", arabic_family="IBM Plex Sans Arabic",
        summary="Formal and restrained: centred type cover, numbered sections, serif text, quiet rules.",
        base_theme="modern_minimal", heading_family="Open Sans", body_family="Source Serif 4", base_size=11, line_height=1.42,
        heading_scale=(1.75, 1.32, 1.14, 1.05, 1.0, 0.95), density=1.0, margins=(76, 70, 74, 74),
        primary="#1F3A5F", accent="#8A6D3B", cover="type_centered", opener="none", kpi="tiles", table="open",
        hero_image="inline", side_image=0.0, side_alternates=False, statement="plain", bands="line",
        numbered=True, toc_min=4),
    Direction(
        id="editorial_modern", name="Editorial Modern", arabic_family="Markazi Text",
        summary="Magazine rhythm: wide start margin, headings hung into it, images that bleed or float.",
        base_theme="modern_minimal", heading_family="Montserrat", body_family="Spectral", base_size=10.5, line_height=1.5,
        heading_scale=(2.9, 1.5, 1.2, 1.05, 1.0, 0.95), density=1.1, margins=(66, 66, 150, 58),
        primary="#17191E", accent="#D1495B", cover="image_top", opener="hang", kpi="ruled", table="open",
        hero_image="bleed", side_image=0.5, side_alternates=True, statement="inline", bands="folio",
        drop_cap=True, lead=True, toc_min=8, hang=96.0, break_major=True),
    Direction(
        id="executive_premium", name="Executive Premium", arabic_family="El Messiri",
        summary="Dark full cover, generous space, section opening pages, figures and statements given a page.",
        base_theme="modern_minimal", heading_family="EB Garamond", body_family="EB Garamond", base_size=11.5, line_height=1.5,
        heading_scale=(2.5, 1.5, 1.2, 1.05, 1.0, 0.95), density=1.28, margins=(92, 84, 88, 88),
        primary="#14283C", accent="#B58B3C", cover="full", opener="page", kpi="hero_page", table="open",
        hero_image="band", side_image=0.44, side_alternates=False, statement="page", bands="quiet",
        lead=True, toc_min=5, break_major=True),
    Direction(
        id="financial_data", name="Financial / Data-Driven", arabic_family="Tajawal",
        summary="Dense and exact: masthead instead of a cover, filled running header, ledger tables, KPI bands.",
        base_theme="modern_minimal", heading_family="Barlow", body_family="Barlow", base_size=9.6, line_height=1.36,
        heading_scale=(1.7, 1.3, 1.12, 1.03, 1.0, 0.95), density=0.82, margins=(50, 50, 50, 50),
        primary="#123B5D", accent="#1E8C7A", cover="masthead", opener="slab", kpi="band", table="ledger",
        hero_image="band", side_image=0.34, side_alternates=False, statement="plain", bands="filled",
        toc_min=9),
    Direction(
        id="arabic_institutional", name="Arabic / Bilingual Institutional", arabic_family="Noto Naskh Arabic",
        summary="Mirrored institutional page: image panel cover, full-width slabs, organisation on every page.",
        base_theme="modern_minimal", heading_family="Noto Serif", body_family="Noto Serif", base_size=10.4, line_height=1.55,
        heading_scale=(1.9, 1.4, 1.18, 1.05, 1.0, 0.95), density=1.08, margins=(78, 72, 72, 72),
        primary="#0E5A4F", accent="#B8862D", cover="split", opener="slab", kpi="ruled", table="ledger",
        hero_image="band", side_image=0.42, side_alternates=True, statement="inline", bands="institutional",
        toc_min=5, break_major=True),
)}


def palette(direction: Direction, primary: Optional[str], accent: Optional[str]) -> Tuple[str, str]:
    """The direction's two working colours, taken from the brand when it has them. The
    premium direction deepens the brand colour; the editorial one leads with it as accent."""
    if direction.id == "editorial_modern":
        return direction.primary, primary or accent or direction.accent
    p = primary or direction.primary
    if direction.id == "executive_premium":
        p = mix(p, "#000000", 0.42)
    return p, accent or direction.accent


def page_system(direction: Direction, *, company: Optional[str], logo: Optional[str], primary: str,
                accent: str, muted: str, rtl: bool, has_title: bool) -> PageSystem:
    """Running heads and feet: each direction has its own architecture, not a recoloured one."""
    label = company or ("{title}" if has_title else "")
    title = "{title}" if has_title else label
    numbers = "{page} / {pages}" if rtl else "Page {page} of {pages}"
    values = {"company": company} if company else {}
    kind = direction.bands
    mark = [Logo(src=logo, max_height=20, max_width=90, alt_text=company)] if logo else []
    if kind == "line":
        return PageSystem(header=Band(rows=[BandRow(start=[title], end=["{section}"], size=8, color=muted,
                                                    rule_below=True, rule_color=primary, rule_width=0.5)]),
                          footer=Band(rows=[BandRow(start=[label], end=[numbers], size=8, color=muted)]),
                          values=values, body_gap=16)
    if kind == "folio":
        odd = BandRow(start=["{section}"], end=["{page}"], size=8.5, color=muted)
        even = BandRow(start=["{page}"], end=["{section}"], size=8.5, color=muted)
        return PageSystem(footer=Band(rows=[odd]), even_footer=Band(rows=[even]), values=values, edge_distance=28)
    if kind == "quiet":
        return PageSystem(header=Band(rows=[BandRow(end=mark or [""], size=7.5)], accent_color=accent, accent_height=3,
                                      bleed=True),
                          footer=Band(rows=[BandRow(start=[title], end=["{page}"], size=7.5, color=muted)]),
                          values=values, edge_distance=26, body_gap=18)
    if kind == "filled":
        return PageSystem(header=Band(rows=[BandRow(start=[title], end=["{section}"], size=8, bold=True, color="#FFFFFF",
                                                    fill=primary)], bleed=True, padding=7),
                          footer=Band(rows=[BandRow(start=[label], end=[numbers], size=7.5, color=muted,
                                                    rule_below=False)]),
                          values=values, edge_distance=0, body_gap=16)
    if kind == "dual_filled":                     # only a grammar rule asks for this
        def bar(start, end):
            return Band(rows=[BandRow(start=start, end=end, size=7.5, bold=True, color="#FFFFFF", fill=primary)],
                        bleed=True, padding=5)
        foot = label or "{section}"
        return PageSystem(header=bar([title], ["{section}"]), footer=bar([foot], [numbers]),
                          even_footer=bar([numbers], [foot]), values=values, edge_distance=0, body_gap=16)
    head = BandRow(start=mark or [label], end=[title if mark or label != title else "{section}"], size=8.5,
                   color=primary, rule_below=True, rule_color=accent, rule_width=1.2)
    foot = BandRow(start=[label], center=["{page}"], end=["{section}"], size=8, color=muted)
    return PageSystem(header=Band(rows=[head]), footer=Band(rows=[foot]), values=values, body_gap=14)
