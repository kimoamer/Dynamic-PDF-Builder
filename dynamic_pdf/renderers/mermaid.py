from reportlab.platypus import Paragraph, Spacer
from reportlab.lib.styles import ParagraphStyle
from ..fonts import get_font_name
import tempfile
import os

def render_mermaid(block, theme):
    try:
        from playwright.sync_api import sync_playwright
        import base64
        
        # HTML harness to render mermaid client-side and screenshot
        mermaid_html = f"""
        <!DOCTYPE html>
        <html>
        <head><script type="module">
          import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';
          mermaid.initialize({{ startOnLoad: true }});
        </script></head>
        <body style="background: white;">
          <pre class="mermaid">{block.diagram}</pre>
        </body>
        </html>
        """
        
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
            tf_name = tf.name
            
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.set_content(mermaid_html)
            # wait for mermaid to finish rendering SVG
            page.wait_for_selector('svg')
            # locator screenshot to exactly bound the svg
            svg_element = page.locator('svg').first
            svg_element.screenshot(path=tf_name)
            browser.close()
            
        from reportlab.platypus import Image
        from reportlab.lib.utils import ImageReader
        img = ImageReader(tf_name)
        w, h = img.getSize()
        # Scale to max width safely
        max_w = 450
        if w > max_w:
            h = h * (max_w / w)
            w = max_w
            
        rl_img = Image(tf_name, width=w, height=h)
        rl_img.hAlign = 'CENTER'
        rl_img.spaceAfter = theme.spacing.block_gap
        os.unlink(tf_name)
        return [rl_img]
        
    except ImportError:
        # Graceful fallback: style as a code block
        from .code_block import render_code_block
        from ..schema.blocks import CodeBlock
        fallback_block = CodeBlock(language="mermaid", code=f"/* Playwright not installed */\n{block.diagram}")
        return render_code_block(fallback_block, theme)
    except Exception as e:
        style = ParagraphStyle(
            'ErrBlock',
            fontName=get_font_name(theme.typography.mono_family),
            textColor=theme.colors.error
        )
        return [Paragraph(f"[Mermaid Render Failed: {str(e)}]", style)]
