from reportlab.platypus import Spacer
from reportlab.platypus.flowables import Flowable
from reportlab.lib.colors import HexColor

class DividerFlowable(Flowable):
    def __init__(self, width, color="#000000", thickness=1.0, space_before=12, space_after=12):
        super().__init__()
        self.width = width
        self.color = color
        self.thickness = thickness
        self.space_before = space_before
        self.space_after = space_after
        # flowables need explicit width and height 
        self.height = space_before + space_after + thickness

    def draw(self):
        self.canv.saveState()
        self.canv.setStrokeColor(HexColor(self.color))
        self.canv.setLineWidth(self.thickness)
        
        y = self.space_after + (self.thickness / 2.0)
        self.canv.line(0, y, self.width, y)
        
        self.canv.restoreState()

    def wrap(self, availWidth, availHeight):
        return (availWidth, self.height)
