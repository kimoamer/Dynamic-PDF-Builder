"""Human-reviewed formal document defaults for *designed* PDF/DOCX outputs.

These are deterministic design constraints, not an ML preference model. The
preference log remains external and never feeds this module automatically.
Raw/custom-theme rendering is deliberately unchanged.
"""
from __future__ import annotations

from typing import List

from ..schema.theme import Theme

# The palette families approved during the human A/B review. Distinct
# composition directions may use distinct members of this finite set.
PALETTES = {
    "navy": ("#1B365D", "#2B547E", "#1E40AF"),
    "slate": ("#2B547E", "#1B365D", "#1E40AF"),
    "charcoal": ("#1F2937", "#334155", "#1B365D"),
    "forest": ("#064E3B", "#115E59", "#1B365D"),
}
DIRECTION_PALETTE = {
    "corporate_conservative": "navy",
    "editorial_modern": "slate",
    "executive_premium": "charcoal",
    "financial_data": "navy",
    "arabic_institutional": "forest",
}

# Cover, H1..H3, body, caption and note sizes in pt. The bilingual compromise
# has to be checked per script in the rendering layer in a follow-up change.
SIZE = {
    "ltr": (26.0, 17.0, 14.0, 12.0, 11.5, 9.5, 9.5),
    "rtl": (28.0, 19.0, 16.0, 14.0, 13.5, 10.5, 10.5),
    "bilingual": (27.0, 18.0, 15.0, 13.0, 12.5, 10.0, 10.0),
}


def apply_reviewed_quality(theme: Theme, *, script: str = "ltr", palette: str = "navy",
                           preserve_brand: bool = False) -> List[str]:
    """Mutate a *copied* theme with a predictable formal typography/palette.

    Caller retains control of branded colours, but not invalid font sizes or
    oversized content margins. Returns explanatory notes for design_explain().
    """
    if script not in SIZE:
        raise ValueError(f"unknown script {script!r}")
    if palette not in PALETTES:
        raise ValueError(f"unknown palette {palette!r}")
    title, h1, h2, h3, body, caption, note = SIZE[script]
    ty = theme.typography
    ty.base_size = ty.body_size = body
    ty.title_size = title
    ty.heading_h1_size = h1
    ty.heading_h2_size = h2
    ty.heading_h3_size = h3
    ty.heading_scale = [h1 / body, h2 / body, h3 / body, 1.02, 0.98, 0.94]
    ty.caption_size = caption
    ty.note_size = note
    # The PDF renderer still consumes the ratios for many captions/notes.
    ty.caption_size_ratio = caption / body
    ty.note_size_ratio = note / body
    ty.line_height = 1.65 if script == "rtl" else 1.55 if script == "bilingual" else 1.5

    sp = theme.spacing
    for key in ("page_margin_top", "page_margin_bottom", "page_margin_left", "page_margin_right"):
        setattr(sp, key, max(64.0, min(80.0, float(getattr(sp, key)))))
    sp.paragraph_spacing_after = max(5.0, min(9.0, sp.paragraph_spacing_after))
    sp.block_gap = max(7.0, min(13.0, sp.block_gap))
    sp.heading_spacing_before = [min(25.0, max(10.0, v)) for v in sp.heading_spacing_before]
    sp.heading_spacing_after = [min(11.0, max(4.0, v)) for v in sp.heading_spacing_after]

    c = theme.colors
    c.background = "#FFFFFF"
    c.text_primary = "#1F2937"
    c.text_secondary = "#334155"
    c.text_muted = "#475569"
    if not preserve_brand:
        c.primary, c.secondary, c.accent = PALETTES[palette]
        c.header_bg = c.footer_bg = c.table_header_bg = c.primary
        c.header_text = c.footer_text = c.table_header_text = c.text_on_primary = "#FFFFFF"
        c.link = c.accent
        c.drop_cap = c.primary
    return [f"human-reviewed formal standard: {script}, body {body:g}pt, H1 {h1:g}pt, "
            f"cover {title:g}pt; {'brand palette retained' if preserve_brand else palette + ' palette'}"]
