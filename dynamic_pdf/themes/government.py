"""Government theme — conservative, high-contrast, accessible."""
from ..schema.theme import Theme, ColorPalette, Typography, SpacingScale, HeaderFooterConfig, DecorationConfig

GOVERNMENT_THEME = Theme(
    name="government",
    colors=ColorPalette(
        primary="#003366",
        secondary="#004488",
        accent="#003366",
        background="#ffffff",
        surface="#F0F3F5",
        text_primary="#000000",
        text_secondary="#333333",
        text_muted="#555555",
        text_on_primary="#ffffff",
        border="#A0A0A0",
        code_bg="#F0F3F5",
        code_text="#000000",
        success="#006600",
        warning="#CC6600",
        error="#CC0000",
        info="#003366",
        tip="#003366",
        header_bg="#003366",
        header_text="#ffffff",
        footer_bg="#003366",
        footer_text="#ffffff",
        drop_cap="#003366",
    ),
    typography=Typography(
        heading_family="Inter",
        body_family="Inter",
        mono_family="JetBrains Mono",
        base_size=12.0,               # 12 pt for government accessibility
        line_height=1.5,
        heading_scale=[1.17, 1.17, 1.08, 1.0, 0.92, 0.83],  # H1=H2=14 pt
        caption_size_ratio=0.67,      # ~8 pt captions
        note_size_ratio=0.67,         # ~8 pt footnotes
        code_size=9.0,
    ),
    spacing=SpacingScale(
        page_margin_top=72.0,         # 1 inch all sides
        page_margin_bottom=72.0,
        page_margin_left=72.0,
        page_margin_right=72.0,
        paragraph_spacing_after=8.0,
        first_line_indent=36.0,
        block_gap=10.0,
        heading_spacing_before=[28.0, 24.0, 20.0, 16.0, 14.0, 12.0],
        heading_spacing_after=[14.0, 12.0, 10.0, 8.0, 6.0, 4.0],
    ),
    header_footer=HeaderFooterConfig(enabled=True, height=55.0, show_page_number=True, show_date=True),
    decorations=DecorationConfig(
        heading_accent_bar=True,
        heading_accent_bar_width=5.0,
        drop_cap_enabled=False,
        table_row_alternating=True,
    ),
)
