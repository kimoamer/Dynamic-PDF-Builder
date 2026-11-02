"""Brand kits: organisation colours, fonts and logo applied on top of a recipe."""
from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from ..schema.theme import Theme
from ..utils.color import contrast_ratio, darken


class BrandKit(BaseModel):
    name: Optional[str] = None
    primary: Optional[str] = None          # headings accents, header bars, table headers
    secondary: Optional[str] = None
    accent: Optional[str] = None
    text: Optional[str] = None
    heading_font: Optional[str] = None     # registered font family name
    body_font: Optional[str] = None
    font_files: Dict[str, str] = Field(default_factory=dict)   # family -> .ttf path
    logo: Optional[str] = None             # loaded through the AssetPolicy at render time
    footer_text: Optional[str] = None


def _readable_on(bg: str) -> str:
    return "#FFFFFF" if contrast_ratio("#FFFFFF", bg) >= contrast_ratio("#111111", bg) else "#111111"


def apply_brand(theme: Theme, brand: BrandKit) -> List[str]:
    """Mutate ``theme`` with ``brand``. Returns notes describing adjustments."""
    notes: List[str] = []
    c, ty, hf = theme.colors, theme.typography, theme.header_footer
    for family, path in brand.font_files.items():
        from ..fonts.manager import register_custom_font
        if not register_custom_font(family, path):
            from ..utils.errors import FontError
            raise FontError(f"Brand font {family!r} could not be registered from {path}")
    if brand.primary:
        primary = brand.primary
        if contrast_ratio(primary, c.background) < 3.0:
            primary = darken(primary, 0.35)
            notes.append(f"brand primary darkened to {primary} for contrast on white")
        c.primary = c.header_bg = c.footer_bg = c.table_header_bg = c.drop_cap = primary
        c.link = primary
        c.header_text = c.footer_text = c.table_header_text = _readable_on(primary)
        c.text_on_primary = _readable_on(primary)
        theme.decorations.heading_accent_bar_color = brand.accent or primary
    if brand.secondary:
        c.secondary = brand.secondary
    if brand.accent:
        c.accent = brand.accent
    if brand.text:
        c.text_primary = brand.text
    if brand.heading_font:
        ty.heading_family = brand.heading_font
    if brand.body_font:
        ty.body_family = brand.body_font
    if brand.logo:
        hf.logo = brand.logo
        if hf.header_style in ("line", "minimal", "bar"):
            hf.header_style = "logo_right" if hf.header_style == "bar" else hf.header_style
    if brand.name:
        hf.company_name = brand.name
    if brand.footer_text:
        hf.footer_text = brand.footer_text
    return notes
