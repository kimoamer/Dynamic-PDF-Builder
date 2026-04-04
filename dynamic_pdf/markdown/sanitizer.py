"""
Markdown Sanitizer — security layer for untrusted input.
Strips dangerous URIs, path traversal, limits nesting and block count.
"""
import re
from typing import Optional

MAX_BLOCK_COUNT = 2000
MAX_NESTING_DEPTH = 10
MAX_INPUT_LENGTH = 500_000  # 500KB

_DANGEROUS_URI_RE = re.compile(
    r'(javascript|data|vbscript)\s*:', re.IGNORECASE
)
_PATH_TRAVERSAL_RE = re.compile(r'\.\.[/\\]')


def sanitize_markdown(md_text: str, *, max_length: int = MAX_INPUT_LENGTH) -> str:
    """Sanitize markdown text from untrusted sources."""
    if not md_text:
        return ""

    # Cap input length
    if len(md_text) > max_length:
        md_text = md_text[:max_length]

    # Strip javascript: and data: URIs from links and images
    md_text = _DANGEROUS_URI_RE.sub("BLOCKED", md_text)

    # Strip path traversal in image/link paths
    md_text = _PATH_TRAVERSAL_RE.sub("", md_text)

    # Strip HTML script tags
    md_text = re.sub(r'<\s*script[^>]*>.*?</\s*script\s*>', '', md_text, flags=re.IGNORECASE | re.DOTALL)
    md_text = re.sub(r'<\s*script[^>]*/?\s*>', '', md_text, flags=re.IGNORECASE)

    # Strip HTML event handlers (onclick, onerror, etc.)
    md_text = re.sub(r'\bon\w+\s*=\s*["\'][^"\']*["\']', '', md_text, flags=re.IGNORECASE)

    # Strip HTML iframe/object/embed
    for tag in ('iframe', 'object', 'embed', 'form', 'input'):
        md_text = re.sub(rf'<\s*{tag}[^>]*/?\s*>', '', md_text, flags=re.IGNORECASE)
        md_text = re.sub(rf'</\s*{tag}\s*>', '', md_text, flags=re.IGNORECASE)

    return md_text


def validate_block_count(blocks: list, max_count: int = MAX_BLOCK_COUNT) -> list:
    """Truncate blocks list if it exceeds maximum count."""
    if len(blocks) > max_count:
        import warnings
        warnings.warn(f"Block count ({len(blocks)}) exceeds maximum ({max_count}), truncating.")
        return blocks[:max_count]
    return blocks
