"""Academic theme — serif fonts, traditional spacing, black & white."""
from ..schema.theme import Theme, ColorPalette, Typography, SpacingScale, HeaderFooterConfig, DecorationConfig

ACADEMIC_THEME = Theme(
    name="academic",
    colors=ColorPalette(
        primary="#1a1a1a",
        secondary="#333333",
        accent="#1a1a1a",
        background="#ffffff",
        surface="#f5f5f5",
        text_primary="#000000",
        text_secondary="#333333",
        text_muted="#666666",
        text_on_primary="#ffffff",
        border="#cccccc",
        code_bg="#f5f5f5",
        code_text="#333333",
        success="#2e7d32",
        warning="#f57f17",
        error="#c62828",
        info="#1565c0",
        tip="#6a1b9a",
        header_bg="#1a1a1a",
        header_text="#ffffff",
        footer_bg="#ffffff",
        footer_text="#666666",
        drop_cap="#1a1a1a",
    ),
    typography=Typography(
        heading_family="Inter",       # would be Georgia/Times if bundled
        body_family="Inter",
        mono_family="JetBrains Mono",
        base_size=12.0,               # academic standard: TNR 12 pt
        line_height=1.5,
        heading_scale=[1.17, 1.17, 1.08, 1.0, 0.92, 0.83],  # H1=H2=14 pt, H3=13 pt
        caption_size_ratio=0.67,      # ~8 pt captions
        note_size_ratio=0.67,         # ~8 pt footnotes
        code_size=9.0,
    ),
    spacing=SpacingScale(
        page_margin_top=72.0,         # 1 inch all sides (no header bar)
        page_margin_bottom=72.0,
        page_margin_left=72.0,
        page_margin_right=72.0,
        paragraph_spacing_after=6.0,
        first_line_indent=36.0,       # 0.5 inch APA standard
        block_gap=10.0,
        heading_spacing_before=[32.0, 28.0, 24.0, 18.0, 14.0, 12.0],
        heading_spacing_after=[14.0, 12.0, 10.0, 8.0, 6.0, 4.0],
    ),
    header_footer=HeaderFooterConfig(enabled=False, show_page_number=True),
    decorations=DecorationConfig(
        heading_accent_bar=False,     # no accent bars in academic
        drop_cap_enabled=False,       # clean academic style
        table_row_alternating=False,  # plain borders only
    ),
)
