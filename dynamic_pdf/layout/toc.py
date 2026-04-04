from reportlab.platypus.tableofcontents import TableOfContents
from ..fonts import get_font_name

def create_toc(block, theme):
    toc = TableOfContents()
    toc.levelStyles = [
        # define styles per depth level
    ]
    # For a real implementation, you would populate levelStyles with ParagraphStyles
    # and use `doc.multiBuild(flowables)` to generate it on page 2.
    from reportlab.platypus import Paragraph
    from reportlab.lib.styles import ParagraphStyle
    style = ParagraphStyle('TOCMock', fontName=get_font_name(theme.typography.body_family))
    return [Paragraph("<b>Table of Contents (Auto-Generated Placeholder)</b>", style), toc]
