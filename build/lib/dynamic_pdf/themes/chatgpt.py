from ..schema.theme import Theme, ColorPalette, Typography, SpacingScale, HeaderFooterConfig, DecorationConfig

CHATGPT_THEME = Theme(
    name="chatgpt",
    colors=ColorPalette(
        primary="#10a37f",
        secondary="#0d8c6d",
        accent="#10a37f",
        background="#ffffff",
        surface="#f7f7f8",
        text_primary="#000000",
        text_secondary="#5e5e5e",
        text_muted="#acacbe",
        text_on_primary="#ffffff",
        border="#d9d9e3",
        code_bg="#000000",
        code_text="#ffffff",
        success="#10a37f",
        warning="#f59e0b",
        error="#ef4146",
        info="#3b82f6",
        tip="#8b5cf6",
        header_bg="#202123",
        header_text="#ffffff",
        footer_bg="#202123",
        footer_text="#acacbe",
        drop_cap="#10a37f",
    ),
    typography=Typography(
        heading_family="Inter",
        body_family="Inter",
        mono_family="JetBrains Mono",
        base_size=11.0,               # 11 pt (APA 7: Arial/Calibri 11 pt)
        line_height=1.5,
        heading_scale=[1.45, 1.27, 1.18, 1.09, 1.0, 0.91],  # H1=16, H2=14, H3=13
        caption_size_ratio=0.73,
        note_size_ratio=0.73,
        code_size=9.0,
    ),
    spacing=SpacingScale(
        page_margin_top=72.0,         # 1 inch all sides
        page_margin_bottom=72.0,
        page_margin_left=72.0,
        page_margin_right=72.0,
        paragraph_spacing_after=6.0,
        first_line_indent=0.0,        # ChatGPT style: no indent + block spacing
        block_gap=12.0,
        heading_spacing_before=[24.0, 18.0, 14.0, 12.0, 10.0, 8.0],
        heading_spacing_after=[10.0, 8.0, 6.0, 5.0, 4.0, 4.0],
    ),
    header_footer=HeaderFooterConfig(enabled=True, height=50.0, show_page_number=True),
    decorations=DecorationConfig(heading_accent_bar=True, drop_cap_enabled=False),
)
