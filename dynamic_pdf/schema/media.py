"""
Media placement model, shared by the PDF and DOCX renderers.

A document says what an image is for and where it belongs; ``dynamic_pdf.media``
turns that into geometry and each renderer draws the same plan.

``start`` and ``end`` are reading directions: ``start`` is the right-hand side of
a right-to-left document. ``left`` and ``right`` are physical and never mirror.
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field

PlacementMode = Literal["inline", "anchored", "floating", "behind_text", "in_front_of_text"]
TextWrap = Literal["inline", "top_bottom", "square", "none"]
Reference = Literal["page", "margins", "content"]
Horizontal = Literal["start", "end", "left", "right", "center"]
Vertical = Literal["top", "middle", "bottom"]
RepeatScope = Literal["once", "every_page", "cover", "sections"]


class ImageTreatment(BaseModel):
    """How an image is shown inside the box it is given. Nothing here can distort
    it: the aspect ratio is always kept, and ``cover`` crops rather than stretches."""

    fit: Literal["contain", "cover"] = "contain"
    focal_x: float = Field(0.5, ge=0, le=1)      # kept in view when ``cover`` crops
    focal_y: float = Field(0.5, ge=0, le=1)
    crop_left: float = Field(0, ge=0, lt=1)      # fractions of the source image
    crop_top: float = Field(0, ge=0, lt=1)
    crop_right: float = Field(0, ge=0, lt=1)
    crop_bottom: float = Field(0, ge=0, lt=1)
    rotation: float = 0                          # degrees clockwise
    opacity: float = Field(1, ge=0, le=1)
    border_width: float = Field(0, ge=0)
    border_color: Optional[str] = None
    shadow: bool = False
    padding: float = Field(0, ge=0)


class MediaPlacement(BaseModel):
    """Where an image sits relative to the text and the page."""

    mode: PlacementMode = "inline"
    wrap: Optional[TextWrap] = None              # None: the usual wrap for the mode
    relative_to: Reference = "content"
    horizontal: Horizontal = "center"
    vertical: Vertical = "top"
    offset_x: float = 0                          # points, towards the reading end
    offset_y: float = 0                          # points, down the page
    width_ratio: Optional[float] = Field(None, gt=0, le=1.5)   # of the reference box
    height_ratio: Optional[float] = Field(None, gt=0, le=1.5)
    gutter: float = Field(12, ge=0)              # space kept between image and text
    z_index: int = 0
    bleed: bool = False                          # inline only: runs edge to edge

    def text_wrap(self) -> TextWrap:
        if self.wrap:
            return self.wrap
        return {"inline": "inline", "floating": "square", "anchored": "none",
                "behind_text": "none", "in_front_of_text": "none"}[self.mode]


PLACEMENT_PRESETS = {
    "inline": MediaPlacement(),
    "full_width": MediaPlacement(width_ratio=1.0),
    "full_bleed": MediaPlacement(width_ratio=1.0, bleed=True),
    "float_start": MediaPlacement(mode="floating", horizontal="start", width_ratio=0.42),
    "float_end": MediaPlacement(mode="floating", horizontal="end", width_ratio=0.42),
    "behind_text": MediaPlacement(mode="behind_text", relative_to="margins", width_ratio=1.0),
    "in_front_of_text": MediaPlacement(mode="in_front_of_text", relative_to="page",
                                       horizontal="end", vertical="top"),
}


def resolve_placement(value) -> Optional[MediaPlacement]:
    """A placement from its preset name, a dict or itself."""
    if value is None or isinstance(value, MediaPlacement):
        return value
    if isinstance(value, str):
        if value not in PLACEMENT_PRESETS:
            raise ValueError(f"Unknown placement {value!r}; one of {sorted(PLACEMENT_PRESETS)}")
        return PLACEMENT_PRESETS[value].model_copy()
    return MediaPlacement.model_validate(value)
