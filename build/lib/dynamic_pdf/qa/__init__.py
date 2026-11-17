"""Visual & structural quality assurance for generated PDF and DOCX."""
from .report import Finding, QAReport
from .pdf_checks import check_pdf
from .docx_checks import check_docx, docx_to_pdf
from .glyphs import uncovered_chars
from .rasterize import rasterize_pdf, contact_sheet

__all__ = ["Finding", "QAReport", "check_pdf", "check_docx", "docx_to_pdf",
           "uncovered_chars", "rasterize_pdf", "contact_sheet"]
