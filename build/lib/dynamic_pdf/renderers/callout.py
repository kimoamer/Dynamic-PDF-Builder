from reportlab.platypus import Table, Paragraph
from reportlab.lib.colors import HexColor

def render_callout(block, theme, body_style):
    # Determine the accent color based on the variant
    color_hex = getattr(theme.colors, block.variant, theme.colors.info)
    color = HexColor(color_hex)
    
    p = Paragraph(f"<b>{block.variant.upper()}:</b> {block.text}", body_style)
    
    t = Table([[p]], style=[
        ('BACKGROUND', (0,0), (-1,-1), HexColor(theme.colors.surface)),
        ('TEXTCOLOR', (0,0), (-1,-1), HexColor(theme.colors.text_primary)),
        ('PADDING', (0,0), (-1,-1), 10),
        ('BOX', (0,0), (-1,-1), 1, color),
        ('LINELEFT', (0,0), (-1,-1), 4, color), # Thicker left border
    ])
    t.hAlign = 'LEFT'
    t.spaceAfter = theme.spacing.block_gap
    return [t]
