from pydantic import BaseModel, model_validator
from typing import List, Optional, Any
from .blocks import Block
from .enums import PageSize, Orientation

class Meta(BaseModel):
    title: Optional[str] = None
    author: Optional[str] = None
    subject: Optional[str] = None               # PDF /Subject
    keywords: List[str] = []                    # PDF /Keywords
    description: Optional[str] = None           # PDF /Description
    creator_tool: str = "Dynamic PDF Builder"   # PDF /Creator
    language: str = "en"
    page_size: PageSize = PageSize.A4
    orientation: Orientation = Orientation.PORTRAIT
    page_number_start: int = 1                  # Offset start
    section_numbering: bool = False             # Auto-number headings 1, 1.1, 1.1.2
    rtl: bool = False                           # Document-level RTL
    direction: Optional[str] = None             # "ltr" | "rtl" | None (auto-detect)
    document_type: Optional[str] = None         # e.g. executive_report, proposal, academic_report
    audience: Optional[str] = None              # free text, e.g. "board", "engineers"
    encrypt: bool = False                       # Password-protect
    owner_password: Optional[str] = None
    user_password: Optional[str] = None

class Document(BaseModel):
    meta: Meta = Meta()
    theme: str = "claude"
    blocks: List[Block] = []

    @model_validator(mode="after")
    def _validate_heading_hierarchy(self):
        """Warn on heading level skips (WCAG 1.3.1): e.g. H1→H3 without H2."""
        last_level = 0
        for b in self.blocks:
            if hasattr(b, 'type') and b.type == 'heading':
                if b.level > last_level + 1 and last_level > 0:
                    import warnings
                    warnings.warn(
                        f"Heading level skipped: H{last_level}→H{b.level} "
                        f"(WCAG 1.3.1 recommends sequential heading levels)",
                        stacklevel=2,
                    )
                last_level = b.level
        return self

class RenderResult(BaseModel):
    success: bool
    pdf_base64: Optional[str] = None
    metadata: dict = {}
