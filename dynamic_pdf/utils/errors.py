"""Custom exceptions for Dynamic PDF Builder."""


class DynamicPDFError(Exception):
    """Base exception for all Dynamic PDF Builder errors."""


class ThemeError(DynamicPDFError):
    """Theme not found or invalid configuration."""


class FontError(DynamicPDFError):
    """Font loading or registration failed."""


class BlockRenderError(DynamicPDFError):
    """A content block failed to render."""

    def __init__(self, block_type: str, message: str, original: Exception = None):
        self.block_type = block_type
        self.original = original
        super().__init__(f"[{block_type}] {message}")


class ValidationError(DynamicPDFError):
    """Input validation failed."""


class EncryptionError(DynamicPDFError):
    """PDF encryption failed."""


class AssetError(DynamicPDFError):
    """An external asset (image, logo, script) was refused or could not be loaded."""


class ResourceLimitError(DynamicPDFError):
    """Input exceeded a configured resource limit (size, count, pixels...)."""


class RenderError(DynamicPDFError):
    """Rendering failed as a whole (wraps the collected diagnostics)."""

    def __init__(self, message: str, diagnostics=None):
        self.diagnostics = list(diagnostics or [])
        super().__init__(message)
