"""Options of automatic image placement. Everything is off until asked for."""

from typing import Literal, Tuple

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AutoMediaOptions(BaseModel):
    """``suggest`` reports a plan and keeps the designed output; ``auto`` applies a plan
    only when it passes every check for every format in ``targets``."""

    model_config = ConfigDict(frozen=True)

    mode: Literal["off", "suggest", "auto"] = "off"
    targets: Tuple[Literal["pdf", "docx"], ...] = ("pdf",)
    docx_validation: Literal["structural", "libreoffice"] = "libreoffice"
    word_required: bool = False
    min_dpi: float = Field(110.0, gt=0)
    min_float_text_width_pt: float = Field(180.0, gt=0)
    max_media_candidates: int = Field(4, ge=0)
    max_docx_renders: int = Field(2, ge=0)
    lossless_bands: bool = True

    @field_validator("targets")
    @classmethod
    def _distinct(cls, value):
        if not value or len(set(value)) != len(value):
            raise ValueError("targets must name each format once")
        return value
