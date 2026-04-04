"""
Corporate Dark Theme — inspired by the Inneovate AI Maturity Assessment report.
Dark navy header/footer bars, teal accent, professional typography.
"""
from ..schema.theme import Theme, ColorPalette, Typography, SpacingScale, HeaderFooterConfig, DecorationConfig

CORPORATE_DARK_THEME = Theme(
    name="corporate_dark",
    colors=ColorPalette(
        primary="#0B1D3A",
        secondary="#1B365D",
        accent="#00897B",
        background="#ffffff",
        surface="#F0F4F8",
        text_primary="#1A1A2E",
        text_secondary="#4A5568",
        text_muted="#718096",
        text_on_primary="#ffffff",
        border="#CBD5E0",
        code_bg="#0B1D3A",
        code_text="#E2E8F0",
        success="#38A169",
        warning="#ECC94B",
        error="#E53E3E",
        info="#3182CE",
        tip="#805AD5",
        header_bg="#0B1D3A",
        header_text="#ffffff",
        footer_bg="#0B1D3A",
        footer_text="#ffffff",
        drop_cap="#0B1D3A",
    ),
    typography=Typography(
        heading_family="Inter",
        body_family="Inter",
        mono_family="JetBrains Mono",
        arabic_family="Amiri",
        base_size=11.0,               # 11 pt (APA 7: Arial/Calibri 11 pt)
        line_height=1.5,
        heading_scale=[1.45, 1.27, 1.18, 1.09, 1.0, 0.91],  # H1=16, H2=14, H3=13
        caption_size_ratio=0.73,      # ~8 pt captions
        note_size_ratio=0.73,         # ~8 pt footnotes
        code_size=9.0,
    ),
    spacing=SpacingScale(
        page_margin_top=72.0,         # 1 inch all sides
        page_margin_bottom=72.0,
        page_margin_left=72.0,
        page_margin_right=72.0,
        paragraph_spacing_before=0.0,
        paragraph_spacing_after=6.0,
        first_line_indent=36.0,
        block_gap=8.0,
        heading_spacing_before=[24.0, 18.0, 14.0, 12.0, 10.0, 8.0],
        heading_spacing_after=[10.0, 8.0, 6.0, 5.0, 4.0, 4.0],
        list_indent=24.0,
        list_bullet_indent=12.0,
        quote_indent=36.0,
        callout_padding=10.0,
    ),
    header_footer=HeaderFooterConfig(
        enabled=True,
        height=55.0,
        show_page_number=True,
        footer_separator=False,
    ),
    decorations=DecorationConfig(
        heading_accent_bar=True,
        heading_accent_bar_width=4.0,
        heading_accent_bar_gap=8.0,
        callout_left_bar_width=4.0,
        table_row_alternating=True,
        drop_cap_enabled=True,
        drop_cap_lines=3,
        drop_cap_font_size_ratio=3.2,
    ),
)
