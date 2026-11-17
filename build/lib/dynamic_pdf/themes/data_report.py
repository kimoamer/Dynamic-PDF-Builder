"""Data Report theme — dense, metric-heavy, compact type."""
from ..schema.theme import Theme, ColorPalette, Typography, SpacingScale, HeaderFooterConfig, DecorationConfig

DATA_REPORT_THEME = Theme(
    name="data_report",
    colors=ColorPalette(
        primary="#2D3748",
        secondary="#4A5568",
        accent="#4299E1",
        background="#ffffff",
        surface="#EDF2F7",
        text_primary="#1A202C",
        text_secondary="#4A5568",
        text_muted="#718096",
        text_on_primary="#ffffff",
        border="#CBD5E0",
        code_bg="#1A202C",
        code_text="#E2E8F0",
        success="#48BB78",
        warning="#ECC94B",
        error="#FC8181",
        info="#63B3ED",
        tip="#B794F4",
        header_bg="#2D3748",
        header_text="#ffffff",
        footer_bg="#2D3748",
        footer_text="#A0AEC0",
        drop_cap="#4299E1",
    ),
    typography=Typography(
        heading_family="Inter",
        body_family="Inter",
        mono_family="JetBrains Mono",
        base_size=10.0,               # compact for dense data
        line_height=1.4,              # tight
        heading_scale=[1.4, 1.3, 1.2, 1.1, 1.0, 0.9],  # H1=14, H2=13, H3=12
        caption_size_ratio=0.8,       # 8 pt captions
        note_size_ratio=0.8,          # 8 pt notes
        code_size=8.5,
    ),
    spacing=SpacingScale(
        page_margin_top=90.0,
        page_margin_bottom=70.0,
        page_margin_left=54.0,        # narrower margins for more content
        page_margin_right=54.0,
        paragraph_spacing_after=4.0,
        first_line_indent=0.0,        # no indent in data reports
        block_gap=6.0,                # tight spacing
        heading_spacing_before=[20.0, 16.0, 14.0, 12.0, 10.0, 8.0],
        heading_spacing_after=[8.0, 6.0, 6.0, 4.0, 4.0, 4.0],
    ),
    header_footer=HeaderFooterConfig(enabled=True, height=45.0, show_page_number=True),
    decorations=DecorationConfig(
        heading_accent_bar=True,
        heading_accent_bar_width=3.0,
        drop_cap_enabled=False,
        table_row_alternating=True,
    ),
)
