from ..schema.theme import Theme, ColorPalette, Typography, SpacingScale, HeaderFooterConfig, DecorationConfig

CLAUDE_THEME = Theme(
    name="claude",
    colors=ColorPalette(
        primary="#da7756",
        secondary="#c4694a",
        accent="#da7756",
        background="#ffffff",
        surface="#f9fafb",
        text_primary="#1a1a1a",
        text_secondary="#6b7280",
        text_muted="#9ca3af",
        text_on_primary="#ffffff",
        border="#e5e7eb",
        code_bg="#1e1e2e",
        code_text="#cdd6f4",
        success="#10b981",
        warning="#f59e0b",
        error="#ef4444",
        info="#3b82f6",
        tip="#8b5cf6",
        header_bg="#da7756",
        header_text="#ffffff",
        footer_bg="#1a1a1a",
        footer_text="#ffffff",
        drop_cap="#da7756",
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
        first_line_indent=36.0,
        block_gap=8.0,
        heading_spacing_before=[24.0, 18.0, 14.0, 12.0, 10.0, 8.0],
        heading_spacing_after=[10.0, 8.0, 6.0, 5.0, 4.0, 4.0],
    ),
    header_footer=HeaderFooterConfig(enabled=True, height=50.0, show_page_number=True),
    decorations=DecorationConfig(
        heading_accent_bar=True,
        drop_cap_enabled=True,
        drop_cap_lines=3,
        drop_cap_font_size_ratio=3.0,
    ),
)
