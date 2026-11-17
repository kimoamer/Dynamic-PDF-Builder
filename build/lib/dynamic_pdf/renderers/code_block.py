import html
from pygments import lex
from pygments.lexers import get_lexer_by_name, guess_lexer
from pygments.styles import get_style_by_name
from pygments.util import ClassNotFound
from reportlab.platypus import Paragraph
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.colors import HexColor

from ..fonts import get_font_name

def render_code_block(block, theme):
    try:
        lexer = get_lexer_by_name(block.language)
    except ClassNotFound:
        try:
            lexer = guess_lexer(block.code)
        except ClassNotFound:
            lexer = get_lexer_by_name("text")
            
    pygments_theme = "monokai" if "claude" in theme.name or "dark" in theme.name else "default"
    pygments_style = get_style_by_name(pygments_theme)
    
    formatted = []
    for ttype, value in lex(block.code, lexer):
        color = None
        curr_ttype = ttype
        while curr_ttype is not None:
            if curr_ttype in pygments_style.styles:
                style_def = pygments_style.style_for_token(curr_ttype)
                color = style_def.get("color", None)
                if color: break
            curr_ttype = curr_ttype.parent
            
        value = html.escape(value).replace("\n", "<br/>").replace(" ", "&nbsp;")
        if color:
            formatted.append(f'<font color="#{color}">{value}</font>')
        else:
            formatted.append(f'<font color="{theme.colors.code_text}">{value}</font>')
            
    html_code = "".join(formatted)
    
    style = ParagraphStyle(
        'CodeBlock',
        fontName=get_font_name(theme.typography.mono_family),
        fontSize=theme.typography.base_size * 0.9,
        leading=theme.typography.base_size * 1.1,
        textColor=HexColor(theme.colors.code_text),
        backColor=HexColor(theme.colors.code_bg),
        borderPadding=theme.spacing.block_gap,
        spaceAfter=theme.spacing.block_gap,
        wordWrap='CJK',
    )
    
    return [Paragraph(html_code, style)]
