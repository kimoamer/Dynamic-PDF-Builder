import latex2mathml.converter
from reportlab.platypus import Paragraph
from reportlab.lib.styles import ParagraphStyle
from ..fonts import get_font_name
import tempfile
import matplotlib.pyplot as plt
from svglib.svglib import svg2rlg
import os

def render_math(block, theme):
    try:
        # We can render Math formulas via matplotlib's mathtext
        fig = plt.figure(figsize=(0.01, 0.01))
        fig.text(0, 0, f"${block.latex}$", fontsize=12)
        
        with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as tf:
            fig.savefig(tf.name, format="svg", bbox_inches="tight", transparent=True)
            tf_name = tf.name
            
        plt.close(fig)
        drawing = svg2rlg(tf_name)
        drawing.hAlign = 'CENTER'
        drawing.spaceAfter = theme.spacing.block_gap
        os.unlink(tf_name)
        
        return [drawing]
        
    except Exception as e:
        style = ParagraphStyle(
            'MathFallback',
            fontName=get_font_name(theme.typography.mono_family),
            textColor=theme.colors.error
        )
        return [Paragraph(f"[Math Render Failed: {block.latex}]", style)]
