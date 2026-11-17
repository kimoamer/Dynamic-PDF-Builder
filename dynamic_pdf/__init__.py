"""
Dynamic PDF Builder
Generate designed PDF and editable DOCX documents from Markdown, JSON, or structured blocks.
"""
from .builder import (
    DocumentBuilder,
    ExportResult,
    render_from_json,
    markdown_to_pdf,
    render_to_bytes,
    render_to_base64,
)
from .schema.blocks import Block
from .streaming import stream
from .guide import guide
from .fonts.manager import register_custom_font, list_available_fonts
from .themes.registry import list_themes, register_theme, get_theme
from .policy import RenderPolicy, ResourceLimits, Diagnostic
from .assets import AssetPolicy
from .intelligence import ComposeOptions, CompositionReport
from .utils.errors import (
    DynamicPDFError, BlockRenderError, EncryptionError, AssetError,
    ResourceLimitError, RenderError, QualityError,
)


def render(blocks: list, output: str, theme: str = "claude") -> None:
    """Quick render: list of Block objects → PDF file."""
    builder = DocumentBuilder(theme=theme)
    builder._blocks.extend(blocks)
    builder.render(output)


__version__ = "0.3.0"

__all__ = [
    # Core
    "DocumentBuilder", "ExportResult", "Block", "render", "guide",
    # Helpers
    "markdown_to_pdf", "render_from_json", "render_to_bytes", "render_to_base64",
    # Streaming
    "stream",
    # Fonts
    "register_custom_font", "list_available_fonts",
    # Themes
    "list_themes", "register_theme", "get_theme",
    # Policy & errors
    "RenderPolicy", "ResourceLimits", "AssetPolicy", "Diagnostic",
    "ComposeOptions", "CompositionReport",
    "DynamicPDFError", "BlockRenderError", "EncryptionError", "AssetError",
    "ResourceLimitError", "RenderError", "QualityError",
    # Version
    "__version__",
]
