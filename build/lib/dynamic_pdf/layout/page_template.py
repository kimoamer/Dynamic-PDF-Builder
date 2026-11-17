from reportlab.platypus import PageTemplate, BaseDocTemplate, Frame
from reportlab.lib.units import inch

def get_page_template(theme, pagesize, margin):
    # A simple single-frame layout matching the document margins
    w, h = pagesize
    frame = Frame(margin, margin, w - 2*margin, h - 2*margin, id='normal')
    
    def on_page(canvas, doc):
        canvas.saveState()
        # Optional: draw header/footer here
        # canvas.setFont(theme.typography.body_family, 9)
        # canvas.drawString(margin, margin/2, f"Page {doc.page}")
        canvas.restoreState()
        
    return PageTemplate(id='Main', frames=frame, onPage=on_page)
