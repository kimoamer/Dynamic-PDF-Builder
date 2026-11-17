from reportlab.platypus import Table, Paragraph, Spacer
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.colors import HexColor
from ..fonts import get_font_name

def render_metric_row(block, theme, body_style):
    data = []
    
    label_style = ParagraphStyle(
        'MetricLabel',
        parent=body_style,
        fontName=get_font_name(theme.typography.body_family, bold=False),
        textColor=HexColor(theme.colors.text_muted),
        fontSize=theme.typography.base_size * 0.9,
    )
    
    value_style = ParagraphStyle(
        'MetricValue',
        fontName=get_font_name(theme.typography.heading_family, bold=True),
        fontSize=theme.typography.base_size * 2.0,
        textColor=HexColor(theme.colors.text_primary),
        leading=theme.typography.base_size * 2.4,
    )
    
    row_cells = []
    for metric in block.metrics:
        # Build cell contents vertically: Label, Value, Delta
        cell_flowables = [
            Paragraph(metric.label.upper(), label_style),
            Paragraph(metric.value, value_style)
        ]
        
        if metric.delta:
            is_pos = "+" in metric.delta or "up" in metric.delta.lower()
            delta_color = theme.colors.success if is_pos else theme.colors.error
            delta_style = ParagraphStyle(
                'MetricDelta',
                fontName=get_font_name(theme.typography.body_family, bold=True),
                textColor=HexColor(delta_color),
                fontSize=theme.typography.base_size * 0.8
            )
            cell_flowables.append(Paragraph(metric.delta, delta_style))
            
        row_cells.append(cell_flowables)
        
    data.append(row_cells)
    
    # Determine column width layout to balance metrics across full page width
    available_width = 460  # assumption
    col_width = available_width / len(block.metrics) if block.metrics else available_width
    
    t = Table(data, colWidths=[col_width] * len(block.metrics), style=[
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 12),
        ('RIGHTPADDING', (0,0), (-1,-1), 16),
    ])
    
    t.hAlign = 'LEFT'
    t.spaceAfter = theme.spacing.block_gap * 1.5
    return [t]
