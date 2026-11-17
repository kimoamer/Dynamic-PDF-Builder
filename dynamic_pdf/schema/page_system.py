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
    lossless: bool = False                       # never cut band text: reflow it, or refuse
    optional_fields: List[str] = Field(default_factory=list)   # may be blank in a lossless band

    def bands(self):
        """Every band this system can draw, for measuring the page margins."""
        out = [self.header, self.first_header, self.even_header]
        out += [s.header for s in self.sections.values()]
        foot = [self.footer, self.first_footer, self.even_footer]
        foot += [s.footer for s in self.sections.values()]
        return [b for b in out if b], [b for b in foot if b]


_COLOUR_KEYS = ("fill", "color", "rule_color", "accent_color")


def themed(system: PageSystem, colors) -> PageSystem:
    """The system with colours given by name ("primary", "accent", "text_muted" ...) taken from the
    theme, so a band follows the design it is used with."""
    def walk(x):
        if isinstance(x, dict):
            return {k: (getattr(colors, v, v) if k in _COLOUR_KEYS and isinstance(v, str) and not v.startswith("#")
                        else walk(v)) for k, v in x.items()}
        return [walk(v) for v in x] if isinstance(x, list) else x
    return PageSystem.model_validate(walk(system.model_dump()))


def _page(language: str) -> str:
    from ..i18n import page_format
    return page_format("Page {n} of {total}", language).replace("{n}", "{page}").replace("{total}", "{pages}")


def preset(name: str, logo: Optional[str] = None, language: str = "en", **values: str) -> PageSystem:
    """A ready-made header and footer, placed by reading edge so it mirrors in Arabic:

    - ``letterhead``: a large logo and the company at the head of page one, the contact details over a
      rule of the accent colour; later pages carry a small logo and the title.
    - ``modern``: the logo over a rule of the accent colour, the title and running section at the end.
    - ``banner``: the logo, on a light plate, and the title on a band of the primary colour.
    - ``report``: the title and running section over a hairline; company, confidentiality and page below.
    - ``minimal``: the page number only.

    Page one opens with the document's title, so its header carries the subtitle or company instead.
    Footers sit under a hairline.

    ``values`` fill the fields: company, website, email, phone, department, confidentiality, code ..."""
    def mark(height: float):
        return [Logo(src=logo, max_height=height, max_width=height * 5)] if logo else []
    page = _page(language)
    contact = "{website} · {email} · {phone}"
    # a hairline between the text and the footer
    foot = dict(accent_color="border", accent_height=0.6, accent_edge="inner", row_gap=0)
    muted = dict(size=7.5, color="text_muted")
    # page one opens with the document's own title, so its header does not repeat it
    systems = {
        "letterhead": dict(
            first_page="custom",
            first_header=Band(row_gap=1, rows=[
                BandRow(start=mark(40), end=["{company}"], bold=True, size=11, color="primary"),
                BandRow(end=[contact], rule_below=True, rule_color="accent", rule_width=1.6, **muted)]),
            header=Band(rows=[BandRow(start=mark(16), end=["{title}"], rule_below=True, **muted)]),
            first_footer=Band(**foot, rows=[BandRow(start=["{department}"], end=[page], **muted)]),
            footer=Band(**foot, rows=[BandRow(start=["{company}"], end=[page], **muted)])),
        "modern": dict(
            first_page="custom",
            first_header=Band(rows=[BandRow(start=mark(26), end=["{subtitle}"], rule_below=True, rule_color="accent",
                                            rule_width=2, size=8, color="text_secondary")]),
            header=Band(rows=[BandRow(start=mark(18), end=["{title} · {section}"], rule_below=True, rule_color="accent",
                                      rule_width=2, size=8, color="text_secondary")]),
            first_footer=Band(**foot, rows=[BandRow(start=["{confidentiality} · {company}"], end=["{page} / {pages}"], **muted)]),
            footer=Band(**foot, rows=[BandRow(start=["{confidentiality} · {company}"], end=["{page} / {pages}"], **muted)])),
        "banner": dict(
            first_page="custom",
            first_header=Band(bleed=True, padding=9, rows=[
                BandRow(fill="primary", start=mark(26), end=["{subtitle}"], bold=True, size=9.5)]),
            header=Band(bleed=True, padding=7, rows=[
                BandRow(fill="primary", start=mark(18), end=["{title}"], bold=True, size=9)]),
            first_footer=Band(**foot, rows=[BandRow(start=["{company}"], end=[page], **muted)]),
            footer=Band(**foot, rows=[BandRow(start=["{company}"], end=[page], **muted)])),
        "report": dict(
            first_page="custom",
            first_header=Band(rows=[BandRow(start=mark(20), end=["{company}"], rule_below=True, **muted)]),
            header=Band(rows=[BandRow(start=["{title}"], end=["{section}"], rule_below=True, **muted)]),
            first_footer=Band(**foot, rows=[BandRow(start=["{confidentiality}"], end=[page], **muted)]),
            footer=Band(**foot, rows=[BandRow(start=["{company}"], center=["{confidentiality}"], end=[page], **muted)])),
        "minimal": dict(footer=Band(rows=[BandRow(center=["{page}"], **muted)])),
    }
    if name not in systems:
        raise ValueError(f"no header and footer preset {name!r}; presets: {', '.join(PRESETS)}")
    return PageSystem(values={k: str(v) for k, v in values.items() if v not in (None, "")}, **systems[name])


PRESETS = ("letterhead", "modern", "banner", "report", "minimal")


def settled(system: PageSystem, blocks) -> PageSystem:
    """``auto`` leaves a cover clean and treats any other first page like the rest."""
    if system.first_page != "auto":
        return system
    cover = bool(blocks) and getattr(blocks[0], "type", None) == "cover_page"
    return system.model_copy(update={"first_page": "none" if cover else "same"})
