from reportlab.platypus import Table
from ..layout.factory import create_flowables

def render_two_column(block, theme):
    # This acts as an orchestrator recursively calling the factory!
    from ..layout.factory import create_flowables
    
    left_flowables = []
    for lb in block.left:
        left_flowables.extend(create_flowables(lb, theme))
        
    right_flowables = []
    for rb in block.right:
        right_flowables.extend(create_flowables(rb, theme))
        
    # Put them side by side in a 1-row Table
    ratio = block.ratio
    total_w = 480 # fallback typical text width
    w_left = total_w * ratio
    w_right = total_w * (1 - ratio)
    
    t = Table([[left_flowables, right_flowables]], colWidths=[w_left, w_right], style=[
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING', (0,0), (-1,-1), 0),
        ('RIGHTPADDING', (0,0), (0,0), theme.spacing.block_gap), # margin between columns
        ('RIGHTPADDING', (1,0), (1,0), 0),
        ('BOTTOMPADDING', (0,0), (-1,-1), 0),
        ('TOPPADDING', (0,0), (-1,-1), 0),
    ])
    
    t.hAlign = 'LEFT'
    t.spaceAfter = theme.spacing.block_gap
    return [t]
