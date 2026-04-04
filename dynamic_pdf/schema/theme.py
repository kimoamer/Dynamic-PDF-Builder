"""
Theme schema — the most comprehensive visual-token system for PDF generation.

Every visual aspect is individually controllable:
  • Per-element font sizes (title, heading, header, footer, paragraph, note, caption, symbol)
  • Per-element colors (text, background, accent for each zone)
  • Header/footer styles: 15+ named patterns composable into 100+ variations
  • Gradient, transparency, border, line, sidebar support
  • Full RTL / bilingual awareness
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


# ═══════════════════════ Color Palette ═══════════════════════

class ColorPalette(BaseModel):
    # Core brand colors
    primary: str = "#1a73e8"
    secondary: str = "#4a90d9"
    accent: str = "#00897B"
    # Page
    background: str = "#ffffff"
    surface: str = "#f7f9fc"
    # Text hierarchy
    text_primary: str = "#1a1a2e"
    text_secondary: str = "#5a6677"
    text_muted: str = "#8e99a4"
    text_on_primary: str = "#ffffff"
    # UI elements
    border: str = "#dde2e8"
    code_bg: str = "#1e1e2e"
    code_text: str = "#cdd6f4"
    # Semantic
    success: str = "#10b981"
    warning: str = "#f59e0b"
    error: str = "#ef4444"
    info: str = "#3b82f6"
    tip: str = "#8b5cf6"
    # Header / footer (overridable per-zone via HeaderFooterConfig)
    header_bg: str = "#0B1D3A"
    header_text: str = "#ffffff"
    footer_bg: str = "#0B1D3A"
    footer_text: str = "#ffffff"
    # Drop-cap
    drop_cap: str = "#0B1D3A"
    # Extended
    link: str = "#1a73e8"
    highlight: str = "#FFF3CD"
    table_header_bg: str = "#0B1D3A"
    table_header_text: str = "#ffffff"
    table_row_alt: str = "#f7f9fc"


# ═══════════════════════ Typography ═══════════════════════

class Typography(BaseModel):
    # ── Font families ──
    heading_family: str = "Inter"
    body_family: str = "Inter"
    mono_family: str = "JetBrains Mono"
    arabic_family: Optional[str] = "Amiri"

    # ── Per-element font sizes (points) ──
    # Set to 0 to use auto-calculated from base_size
    title_size: float = 0           # cover page title (auto = base_size * heading_scale[0])
    heading_h1_size: float = 0      # auto = base_size * heading_scale[0]
    heading_h2_size: float = 0      # auto = base_size * heading_scale[1]
    heading_h3_size: float = 0      # auto = base_size * heading_scale[2]
    header_title_size: float = 12.0 # header bar title
    header_subtitle_size: float = 8.5
    footer_text_size: float = 7.0   # footer text
    footer_detail_size: float = 6.5 # footer company/address/contact line
    body_size: float = 11.0         # synonym for base_size; kept for clarity
    note_size: float = 0            # auto = base_size * note_size_ratio
    caption_size: float = 0         # auto = base_size * caption_size_ratio
    symbol_size: float = 14.0       # bullets, icons, check marks
    code_size: float = 9.0          # code blocks

    # ── Scale system (used when per-element sizes are 0) ──
    # Body: 11 pt (Arial/Calibri standard per APA 7)
    # Headings: H1 = 16 pt, H2 = 14 pt, H3 = 13 pt
    # Captions/Footnotes: 8 pt
    base_size: float = 11.0
    line_height: float = 1.5
    heading_scale: List[float] = Field(default=[1.45, 1.27, 1.18, 1.09, 1.0, 0.91])
    caption_size_ratio: float = 0.73   # 11 * 0.73 ≈ 8 pt (standard for captions)
    note_size_ratio: float = 0.73      # 11 * 0.73 ≈ 8 pt (standard for footnotes)

    # ── Weights / transforms ──
    heading_bold: bool = True
    body_bold: bool = False


# ═══════════════════════ Spacing ═══════════════════════

class SpacingScale(BaseModel):
    # Page margins (1 inch = 72 pt, universal standard)
    page_margin_top: float = 72.0
    page_margin_bottom: float = 72.0
    page_margin_left: float = 72.0
    page_margin_right: float = 72.0
    # Paragraph
    paragraph_spacing_before: float = 0.0
    paragraph_spacing_after: float = 6.0
    first_line_indent: float = 36.0
    # Blocks
    block_gap: float = 8.0
    # Headings (H1→H6)
    heading_spacing_before: List[float] = Field(
        default=[28.0, 24.0, 20.0, 16.0, 14.0, 12.0]
    )
    heading_spacing_after: List[float] = Field(
        default=[12.0, 10.0, 8.0, 6.0, 6.0, 4.0]
    )
    # Lists
    list_indent: float = 24.0
    list_bullet_indent: float = 12.0
    # Blockquote / callout
    quote_indent: float = 36.0
    callout_padding: float = 12.0


# ═══════════════════════ Header / Footer Config ═══════════════════════

class HeaderFooterConfig(BaseModel):
    """
    Fully flexible header & footer system.

    `header_style` and `footer_style` select a drawing pattern.  Every
    colour, font, position, and size can be overridden individually,
    making 100+ unique combinations possible from ~15 base patterns.

    Header styles (header_style):
    ─────────────────────────────
      bar             Full-width solid color bar (default)
      gradient        Horizontal/vertical/diagonal gradient bar
      line            Thin line at bottom of header area + text above
      double_line     Two thin parallel lines
      logo_centered   Centred logo with title underneath
      logo_left       Logo left + title right
      logo_right      Logo right + title left
      minimal         Just text, no background or lines
      banner          Large full-bleed colour band
      accent_top      Thin accent colour stripe at page top + text below
      underline       Title with decorative underline
      boxed           Text inside a bordered rectangle
      split           Two-tone left/right halves
      sidebar         Vertical colour bar on left or right edge
      academic        Centred italic title, rule below
      modern          Full bar + white title sans-serif

    Footer styles (footer_style):
    ─────────────────────────────
      bar             Full-width solid colour bar (default)
      gradient        Gradient bar
      line            Thin line above + text below
      minimal         Just text, no decoration
      centered        All text centred (no left/right)
      three_column    Left | Centre | Right columns
      two_column      Left | Right only
      page_only       Just page number, nothing else
      logo_right      Company logo right-aligned in footer
      logo_left       Company logo left-aligned in footer
      copyright_line  Thin line + copyright centred + page right
      academic        Centred italic text + page number
      sidebar         Vertical bar (matches header sidebar)
    """
    enabled: bool = True
    height: float = 55.0
    footer_height: float = 44.0

    # ── Style selection ──
    header_style: str = "bar"
    footer_style: str = "bar"

    # ── Header content ──
    logo: Optional[str] = None
    logo_max_height: float = 30.0
    logo_width: Optional[float] = None   # auto if None
    title: Optional[str] = None
    subtitle: Optional[str] = None

    # ── Header colours (override ColorPalette if set) ──
    header_bg: Optional[str] = None        # None → palette.header_bg
    header_text_color: Optional[str] = None
    header_bg_gradient_end: Optional[str] = None   # 2nd colour for gradient
    header_bg_gradient_direction: str = "horizontal"  # horizontal | vertical | diagonal
    header_bg_opacity: float = 1.0
    header_border_color: Optional[str] = None
    header_border_width: float = 1.0
    header_accent_color: Optional[str] = None

    # ── Header layout positions ──
    # Each slot: None, "logo", "title", "subtitle", "page", "date", or "text:Custom String"
    header_left: Optional[str] = None
    header_center: Optional[str] = None
    header_right: Optional[str] = None

    # ── Footer content ──
    show_page_number: bool = True
    page_number_format: str = "Page {n}"   # e.g. "Page {n} of {total}", "{n}", "— {n} —"
    show_date: bool = False
    date_format: str = "%d %B %Y"
    copyright_text: Optional[str] = None
    company_name: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    website: Optional[str] = None
    footer_text: Optional[str] = None
    footer_logo: Optional[str] = None       # separate logo for footer
    footer_logo_max_height: float = 20.0

    # ── Footer colours (override ColorPalette if set) ──
    footer_bg: Optional[str] = None
    footer_text_color: Optional[str] = None
    footer_bg_gradient_end: Optional[str] = None
    footer_bg_gradient_direction: str = "horizontal"
    footer_bg_opacity: float = 1.0
    footer_border_color: Optional[str] = None
    footer_border_width: float = 1.0
    footer_accent_color: Optional[str] = None

    # ── Footer layout positions ──
    footer_left: Optional[str] = None
    footer_center: Optional[str] = None
    footer_right: Optional[str] = None

    # ── Sidebar (for sidebar header/footer styles) ──
    sidebar_width: float = 6.0
    sidebar_color: Optional[str] = None
    sidebar_position: str = "left"         # left | right
    sidebar_gradient_end: Optional[str] = None

    # ── Footer separator ──
    footer_separator: bool = False
    footer_separator_color: Optional[str] = None
    header_separator: bool = False
    header_separator_color: Optional[str] = None

    # ── Skip on first page (useful for cover pages) ──
    skip_first_page_header: bool = False
    skip_first_page_footer: bool = False


# ═══════════════════════ Decorations ═══════════════════════

class DecorationConfig(BaseModel):
    # Heading accent bar
    heading_accent_bar: bool = True
    heading_accent_bar_width: float = 4.0
    heading_accent_bar_color: Optional[str] = None
    heading_accent_bar_gap: float = 8.0
    # Code / table
    callout_left_bar_width: float = 4.0
    code_border_radius: float = 4.0
    table_header_bold: bool = True
    table_row_alternating: bool = True
    # Drop Cap
    drop_cap_enabled: bool = False
    drop_cap_lines: int = 3
    drop_cap_font_size_ratio: float = 3.2
    drop_cap_color: Optional[str] = None


# ═══════════════════════ Theme ═══════════════════════

class Theme(BaseModel):
    name: str
    colors: ColorPalette = ColorPalette()
    typography: Typography = Typography()
    spacing: SpacingScale = SpacingScale()
    header_footer: HeaderFooterConfig = HeaderFooterConfig()
    decorations: DecorationConfig = DecorationConfig()
