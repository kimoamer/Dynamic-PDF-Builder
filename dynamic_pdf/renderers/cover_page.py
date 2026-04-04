from reportlab.platypus import Paragraph, Spacer, PageBreak, Image
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.colors import HexColor
from ..fonts import get_font_name

def render_cover_page(block, theme):
    flowables = []
    
    # Push content down to center/start organically
    flowables.append(Spacer(1, 100))
    
    if block.logo:
        try:
            from reportlab.lib.utils import ImageReader
            img = ImageReader(block.logo)
            w, h = img.getSize()
            if w > 200:
                h = h * (200 / w)
                w = 200
            rl_img = Image(block.logo, width=w, height=h)
            rl_img.hAlign = 'LEFT'
            flowables.append(rl_img)
            flowables.append(Spacer(1, 40))
        except Exception:
            pass
            
    title_style = ParagraphStyle(
        'CoverTitle',
        fontName=get_font_name(theme.typography.heading_family, bold=True),
        fontSize=theme.typography.base_size * theme.typography.heading_scale[0] * 1.5,
        leading=theme.typography.base_size * theme.typography.heading_scale[0] * 1.8,
        textColor=HexColor(theme.colors.text_primary),
        spaceAfter=12
    )
    flowables.append(Paragraph(block.title, title_style))
    
    if block.subtitle:
        sub_style = ParagraphStyle(
            'CoverSubtitle',
            fontName=get_font_name(theme.typography.body_family, italic=True),
            fontSize=theme.typography.base_size * 1.5,
            textColor=HexColor(theme.colors.text_secondary),
            spaceAfter=40
        )
        flowables.append(Paragraph(block.subtitle, sub_style))

    if block.date:
        date_style = ParagraphStyle(
            'CoverDate',
            fontName=get_font_name(theme.typography.body_family),
            fontSize=theme.typography.base_size * 1.1,
            textColor=HexColor(theme.colors.text_muted)
        )
        flowables.append(Spacer(1, 100))
        flowables.append(Paragraph(block.date, date_style))

    flowables.append(PageBreak())
    return flowables
