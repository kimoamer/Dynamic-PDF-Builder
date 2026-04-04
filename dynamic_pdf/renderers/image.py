from reportlab.platypus import Image, Spacer
from reportlab.lib.utils import ImageReader
import builtins

def render_image(block, theme):
    try:
        # Load image via ImageReader (supports path, bytes, etc)
        img = ImageReader(block.src)
        # Determine current size
        w, h = img.getSize()
        
        # simple scale down if desired, let's max out at 500
        desired_width = block.width or 500
        if w > desired_width:
            h = h * (desired_width / w)
            w = desired_width
            
        rl_img = Image(block.src, width=w, height=h)
        rl_img.hAlign = block.alignment.upper()
        rl_img.spaceAfter = theme.spacing.block_gap
        
        return [rl_img]
    except Exception as e:
        from reportlab.platypus import Paragraph
        from reportlab.lib.styles import ParagraphStyle
        return [Paragraph(f"[Image Failed: {str(e)}]", ParagraphStyle('err'))]
