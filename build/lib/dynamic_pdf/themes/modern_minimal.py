"""Modern Minimal theme — heavy whitespace, thin type, minimal color."""
from ..schema.theme import Theme, ColorPalette, Typography, SpacingScale, HeaderFooterConfig, DecorationConfig

MODERN_MINIMAL_THEME = Theme(
    name="modern_minimal",
    colors=ColorPalette(
        primary="#111111",
        secondary="#333333",
        accent="#FF4D4D",
        background="#ffffff",
        surface="#FAFAFA",
        text_primary="#111111",
        text_secondary="#555555",
        text_muted="#999999",
        text_on_primary="#ffffff",
        border="#EEEEEE",
        code_bg="#F5F5F5",
        code_text="#111111",
        success="#00C853",
        warning="#FFD600",
        error="#FF1744",
        info="#2979FF",
        tip="#AA00FF",
        header_bg="#111111",
        header_text="#ffffff",
        footer_bg="#111111",
        footer_text="#999999",
        drop_cap="#FF4D4D",
    ),
    typography=Typography(
        heading_family="Inter",
        body_family="Inter",
        mono_family="JetBrains Mono",
        base_size=11.0,               # 11 pt
        line_height=1.7,              # extra generous whitespace
        heading_scale=[1.64, 1.45, 1.27, 1.09, 1.0, 0.91],  # H1=18, H2=16, H3=14
        caption_size_ratio=0.73,
        note_size_ratio=0.73,
        code_size=9.0,
    ),
    spacing=SpacingScale(
        page_margin_top=72.0,         # 1 inch all sides
        page_margin_bottom=72.0,
        page_margin_left=72.0,
        page_margin_right=72.0,
        paragraph_spacing_after=10.0,
        first_line_indent=0.0,       # no indent — block spacing instead
        block_gap=16.0,              # wide gaps
        heading_spacing_before=[40.0, 32.0, 24.0, 18.0, 14.0, 12.0],
        heading_spacing_after=[16.0, 12.0, 10.0, 8.0, 6.0, 4.0],
    ),
    header_footer=HeaderFooterConfig(enabled=True, height=40.0, show_page_number=True),
    decorations=DecorationConfig(
        heading_accent_bar=False,
        drop_cap_enabled=True,
        drop_cap_lines=3,
        drop_cap_font_size_ratio=3.5,
        table_row_alternating=True,
    ),
)
