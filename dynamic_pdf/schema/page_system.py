"""
Slot-based running headers and footers.

A band is a stack of rows; each row has physical slots (``left``, ``center``,
``right``) and reading slots (``start``, ``end``) that swap sides in a right-to-left
document. A slot holds text and logos. Text may carry fields such as ``{title}``,
``{section}`` or ``{page}``, so ``"Page {page} of {pages}"`` is one item. Fields stay
live in Word: page numbers and section titles are real fields, not baked-in text.
"""

from typing import Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field

FIELDS = ("title", "subtitle", "section", "chapter", "date", "period", "author", "department",
          "confidentiality", "code", "website", "email", "phone", "company", "page", "pages")


class Logo(BaseModel):
    """A logo or small brand mark. Its aspect ratio is always kept."""

    src: str
    max_height: float = Field(24, gt=0)
    max_width: float = Field(120, gt=0)
    alt_text: Optional[str] = None


SlotItem = Union[str, Logo]


class BandRow(BaseModel):
    left: List[SlotItem] = Field(default_factory=list)
    center: List[SlotItem] = Field(default_factory=list)
    right: List[SlotItem] = Field(default_factory=list)
    start: List[SlotItem] = Field(default_factory=list)
    end: List[SlotItem] = Field(default_factory=list)
    size: Optional[float] = None                 # points; theme footer size by default
    bold: bool = False
    color: Optional[str] = None
    fill: Optional[str] = None
    rule_below: bool = False
    rule_color: Optional[str] = None
    rule_width: float = 0.6
    max_lines: int = Field(2, ge=1, le=4)

    def slots(self, rtl: bool) -> tuple:
        """The physical left, center and right contents for this direction."""
        first, last = (self.end, self.start) if rtl else (self.start, self.end)
        return list(first) + list(self.left), list(self.center), list(self.right) + list(last)


class Band(BaseModel):
    rows: List[BandRow] = Field(default_factory=list)
    accent_color: Optional[str] = None           # a thin band of colour along one edge
    accent_height: float = Field(0, ge=0)
    accent_edge: Literal["outer", "inner"] = "outer"
    row_gap: float = Field(2, ge=0)
    padding: float = Field(3, ge=0)              # inside a filled row, above and below
    max_height: Optional[float] = None           # a taller band warns and drops rows
    bleed: bool = False                          # fills and accent reach the page edges


class SectionBands(BaseModel):
    """Bands for one named page section; what is left out keeps the default."""

    header: Optional[Band] = None
    footer: Optional[Band] = None


class PageSystem(BaseModel):
    header: Optional[Band] = None
    footer: Optional[Band] = None
    first_page: Literal["auto", "same", "none", "custom"] = "auto"
    first_header: Optional[Band] = None
    first_footer: Optional[Band] = None
    even_header: Optional[Band] = None           # odd pages use header and footer
    even_footer: Optional[Band] = None
    sections: Dict[str, SectionBands] = Field(default_factory=dict)
    values: Dict[str, str] = Field(default_factory=dict)   # {period}, {code}, {department}...
    edge_distance: float = Field(20, ge=0)       # page edge to the band
    body_gap: float = Field(10, ge=0)            # band to the body text

    def bands(self):
        """Every band this system can draw, for measuring the page margins."""
        out = [self.header, self.first_header, self.even_header]
        out += [s.header for s in self.sections.values()]
        foot = [self.footer, self.first_footer, self.even_footer]
        foot += [s.footer for s in self.sections.values()]
        return [b for b in out if b], [b for b in foot if b]


def settled(system: PageSystem, blocks) -> PageSystem:
    """``auto`` leaves a cover clean and treats any other first page like the rest."""
    if system.first_page != "auto":
        return system
    cover = bool(blocks) and getattr(blocks[0], "type", None) == "cover_page"
    return system.model_copy(update={"first_page": "none" if cover else "same"})
