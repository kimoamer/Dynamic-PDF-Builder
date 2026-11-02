"""
Design tokens — one compiled, renderer-independent view of a Theme.

Both the PDF and DOCX renderers resolve sizes, colours and spacing through
``compile_tokens`` so every theme token means the same thing in every format
(fixes per-heading size tokens previously ignored by the PDF path).
"""
from __future__ import annotations

from typing import Dict, List

from pydantic import BaseModel, Field

from ..schema.theme import Theme
from ..utils.color import contrast_ratio

_BUNDLED_OR_BUILTIN = {
    "Helvetica", "Times-Roman", "Times", "Courier", "Serif", "Monospace",
    "JetBrains Mono", "Amiri",
}


class FontTokens(BaseModel):
    heading: str
    body: str
    mono: str
    arabic: str


class DesignTokens(BaseModel):
    fonts: FontTokens
    body_size: float
    line_height: float
    heading_sizes: List[float]          # H1..H6 in pt
    title_size: float
    caption_size: float
    note_size: float
    code_size: float
    colors: Dict[str, str]
    margins: Dict[str, float]           # top/bottom/left/right in pt
    paragraph_after: float
    first_line_indent: float
    block_gap: float
    heading_before: List[float]
    heading_after: List[float]
    list_indent: float
    warnings: List[str] = Field(default_factory=list)


def heading_size(theme: Theme, level: int) -> float:
    """Resolve a heading size: explicit ``heading_hN_size`` wins over scale."""
    ty = theme.typography
    idx = max(0, min(5, level - 1))
    explicit = {1: ty.heading_h1_size, 2: ty.heading_h2_size, 3: ty.heading_h3_size}.get(level, 0)
    if explicit and explicit > 0:
        return float(explicit)
    return ty.base_size * ty.heading_scale[idx]


def font_available(family: str) -> bool:
    from ..fonts.manager import list_available_fonts, register_fonts
    register_fonts()
    available = set(list_available_fonts()) | _BUNDLED_OR_BUILTIN
    return family in available or f"{family}-Regular" in available


def compile_tokens(theme: Theme) -> DesignTokens:
    ty, sp, c = theme.typography, theme.spacing, theme.colors
    warnings: List[str] = []
    for role, fam in (("heading", ty.heading_family), ("body", ty.body_family)):
        if not font_available(fam):
            warnings.append(f"{role} font '{fam}' is not installed; PDF falls back to Helvetica")
    pairs = [(c.text_primary, c.background, "body text"),
             (c.table_header_text, c.table_header_bg, "table header text")]
    hf = theme.header_footer
    if hf.enabled and hf.header_style in ("bar", "gradient", "banner", "split", "logo_left",
                                          "logo_right", "modern", "boxed"):
        pairs.append((hf.header_text_color or c.header_text, hf.header_bg or c.header_bg,
                      "header text"))
    for fg, bg, label in pairs:
        try:
            ratio = contrast_ratio(fg, bg)
            if ratio < 4.5:
                warnings.append(f"{label} contrast {ratio:.2f}:1 is below WCAG AA (4.5:1)")
        except Exception:
            warnings.append(f"invalid colour for {label}: {fg} on {bg}")
    return DesignTokens(
        fonts=FontTokens(heading=ty.heading_family, body=ty.body_family,
                         mono=ty.mono_family, arabic=ty.arabic_family or ty.body_family),
        body_size=ty.base_size,
        line_height=ty.line_height,
        heading_sizes=[heading_size(theme, lv) for lv in range(1, 7)],
        title_size=ty.title_size or ty.base_size * ty.heading_scale[0] * 1.4,
        caption_size=ty.caption_size or ty.base_size * ty.caption_size_ratio,
        note_size=ty.note_size or ty.base_size * ty.note_size_ratio,
        code_size=ty.code_size,
        colors={k: v for k, v in c.model_dump().items() if isinstance(v, str)},
        margins={"top": sp.page_margin_top, "bottom": sp.page_margin_bottom,
                 "left": sp.page_margin_left, "right": sp.page_margin_right},
        paragraph_after=sp.paragraph_spacing_after,
        first_line_indent=sp.first_line_indent,
        block_gap=sp.block_gap,
        heading_before=list(sp.heading_spacing_before),
        heading_after=list(sp.heading_spacing_after),
        list_indent=sp.list_indent,
        warnings=warnings,
    )
