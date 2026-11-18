"""
Themes that are complete looks: each one a page structure (cover, section openings, figures, tables,
running bands), a palette of its own hue, and its own Latin and Arabic faces. No two share a
structure or a hue; ``tests`` hold them to that.

    DocumentBuilder(theme="ledger")          # or .theme("ledger"), or "theme: ledger" in the front matter

A look is drawn by the same art-direction pipeline as ``design(direction=...)``: it is rendered,
checked against the hard gates and refined before it is delivered. Its colours are the document's
brand unless the caller gives a brand kit of their own, which then wins.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Dict

from .brand import BrandKit
from .directions import DIRECTIONS, Direction


@dataclass(frozen=True)
class Look:
    id: str
    name: str                  # in English
    name_ar: str
    summary: str
    direction: Direction       # the structure; its id stays its family's, whose rules it follows
    primary: str
    accent: str

    @property
    def brand(self) -> BrandKit:
        return BrandKit(primary=self.primary, accent=self.accent)

    @property
    def structure(self) -> tuple:
        d = self.direction
        return d.cover, d.masthead, d.opener, d.kpi, d.table, d.bands, d.statement

    def theme(self):
        """The look as a plain theme, for ``design(None)`` and as the base the design starts from."""
        from ..themes.registry import get_theme
        d = self.direction
        t = get_theme(d.base_theme)
        t.name = self.id
        ty, c = t.typography, t.colors
        ty.heading_family, ty.body_family, ty.arabic_family = d.heading_family, d.body_family, d.arabic_family
        c.primary = c.header_bg = c.footer_bg = c.table_header_bg = c.drop_cap = self.primary
        c.secondary, c.accent, c.link = self.primary, self.accent, self.accent
        c.header_text = c.footer_text = c.table_header_text = c.text_on_primary = "#FFFFFF"
        return t


def _on(family: str, **changes) -> Direction:
    return replace(DIRECTIONS[family], **changes)


LOOKS: Dict[str, Look] = {x.id: x for x in (
    Look("executive", "Executive", "رسمي",
         "Formal and restrained: a centred type cover, numbered sections, serif text, quiet rules.",
         _on("corporate_conservative", heading_family="Libre Franklin", body_family="Source Serif 4",
             arabic_family="IBM Plex Sans Arabic", masthead="centred"),
         "#1F3A5F", "#A9792B"),
    Look("magazine", "Magazine", "مجلة",
         "Editorial rhythm: a wide start margin with headings hung into it, a drop cap, statements set large.",
         _on("editorial_modern", heading_family="Oswald", body_family="Spectral", arabic_family="Markazi Text",
             masthead="rule", break_major=False),
         "#D7263D", "#17191E"),           # this family sets its text in ink and leads with the brand colour
    Look("luxe", "Luxe", "فاخر",
         "A dark full cover, generous space, light headings over fine rules, statements given room.",
         _on("executive_premium", heading_family="EB Garamond", body_family="EB Garamond", arabic_family="El Messiri",
             masthead="strip"),
         "#6B1F5E", "#B8893A"),
    Look("ledger", "Ledger", "مالي",
         "Dense and exact: a masthead instead of a cover, a filled running header, ledger tables, figures in a band.",
         _on("financial_data", heading_family="Barlow", body_family="Barlow", arabic_family="Tajawal"),
         "#0F766E", "#EA580C"),
    Look("civic", "Civic", "حكومي",
         "Institutional: a framed cover, full-width section slabs, filled table heads, the organisation on every page.",
         _on("arabic_institutional", heading_family="Noto Serif", body_family="Noto Serif",
             arabic_family="Noto Naskh Arabic", cover="frame", masthead="framed", kpi="tiles", table="default"),
         "#14532D", "#B8862D"),
    Look("scholar", "Scholar", "أكاديمي",
         "A paper: title and authors on page one, serif text, ruled tables, numbered sections, no colour.",
         _on("academic_paper", heading_family="Crimson Pro", body_family="Crimson Pro", arabic_family="Amiri"),
         "#111111", "#111111"),
    Look("tech", "Tech", "تقني",
         "Clean and modern: a side panel of colour, headings beside a bar, boxed figures, a filled foot, sans type.",
         _on("corporate_conservative", heading_family="Manrope", body_family="Manrope", arabic_family="Noto Sans Arabic",
             cover="side_panel", masthead="bar", opener="bar", kpi="boxed", table="tinted", bands="foot_bar",
             numbered=False, base_size=10.5, line_height=1.5, margins=(70, 66, 70, 70)),
         "#6D28D9", "#0891B2"),
    Look("warm", "Warm", "دافئ",
         "Friendly: colour across the head of the cover, rounded headings over a short rule, tinted figures.",
         _on("corporate_conservative", heading_family="Nunito", body_family="PT Serif", arabic_family="Cairo",
             cover="band_top", masthead="tint", opener="under", kpi="tint", table="default", statement="inline",
             bands="centred", numbered=False, lead=True, density=1.05, margins=(74, 70, 76, 76), base_size=11,
             line_height=1.5, heading_scale=(2.1, 1.4, 1.18, 1.05, 1.0, 0.95)),
         "#B45309", "#3F6212"),
)}
