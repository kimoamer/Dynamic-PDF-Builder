"""What an image is for. Placement says where it goes; intent says what may be done to it."""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

MediaRole = Literal["auto", "photo", "figure", "chart", "screenshot", "diagram", "logo", "signature",
                    "decorative"]
Prominence = Literal["normal", "supporting", "hero"]


class NormalizedRect(BaseModel):
    """A part of an image, as fractions of its width and height."""

    x0: float = Field(ge=0, le=1)
    y0: float = Field(ge=0, le=1)
    x1: float = Field(ge=0, le=1)
    y1: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _ordered(self):
        if self.x1 <= self.x0 or self.y1 <= self.y0:
            raise ValueError("a rect needs x1 > x0 and y1 > y0")
        return self


class MediaIntent(BaseModel):
    role: MediaRole = "auto"
    anchor: Optional[str] = None                  # id of the block this image belongs with
    min_display_width_pt: Optional[float] = Field(None, gt=0)
    crop_allowed: bool = False
    protected_rects: List[NormalizedRect] = Field(default_factory=list)
    prominence: Prominence = "normal"
