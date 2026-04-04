from reportlab.platypus import Table, Paragraph, Spacer
from reportlab.lib.colors import HexColor
from ..fonts import get_font_name
from reportlab.lib.styles import ParagraphStyle

def render_table(block, theme, body_style):
    data = []
    
    # Headers
    header_style = ParagraphStyle(
        'TableHeader',
        parent=body_style,
        fontName=get_font_name(theme.typography.body_family, bold=True)
    )
    data.append([Paragraph(h, header_style) for h in block.headers])
    
    # Rows
    for row in block.rows:
        data.append([Paragraph(str(cell), body_style) for cell in row])
        
    t = Table(data, style=[
        ('BACKGROUND', (0,0), (-1,0), HexColor(theme.colors.surface)),
        ('TEXTCOLOR', (0,0), (-1,0), HexColor(theme.colors.text_primary)),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BOTTOMPADDING', (0,0), (-1,0), 6),
        ('GRID', (0,0), (-1,-1), 1, HexColor(theme.colors.border)),
    ])
    t.hAlign = 'LEFT'
    t.spaceAfter = theme.spacing.block_gap
    return [t]
