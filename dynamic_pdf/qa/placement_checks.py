"""
Checks on where images ended up, from the geometry of a real render.

These are the hard gates of automatic placement. They say whether a layout is sound,
never whether it looks good. They read ReportLab geometry, so they do not apply to a PDF
that LibreOffice produced from a DOCX.
"""

from __future__ import annotations

from typing import List

_TOLERANCE = 1.0
_NEVER_AUTOMATIC = {"behind_text", "in_front_of_text"}


def _overlap(a, b) -> bool:
    return (min(a.x1, b.x1) - max(a.x0, b.x0) > _TOLERANCE
            and min(a.top, b.top) - max(a.bottom, b.bottom) > _TOLERANCE)


def _check_image(i: int, block, geometry, rtl: bool) -> List[str]:
    errors: List[str] = []
    treatment, placement = block.treatment, block.placement
    if treatment is not None and (treatment.fit != "contain" or any(
            (treatment.crop_left, treatment.crop_top, treatment.crop_right, treatment.crop_bottom))):
        errors.append(f"block {i}: an informational image would be cropped")
    if placement is not None and placement.mode in _NEVER_AUTOMATIC:
        errors.append(f"block {i}: an informational image moved behind or over the text")
    regions = [r for r in geometry.regions if r.block == i]
    figures = [r for r in regions if r.role == "figure"]
    if not figures:
        return errors + [f"block {i}: the image was not placed"]
    figure = figures[0]
    page = geometry.pages.get(figure.page)
    if page is not None and (figure.x0 < page.frame_x0 - _TOLERANCE
                             or figure.x1 > page.frame_x0 + page.frame_width + _TOLERANCE):
        errors.append(f"block {i}: the image leaves the content frame")
    if any(r.role == "caption" and r.page != figure.page for r in regions):
        errors.append(f"block {i}: the caption is on another page than its image")
    if figure.in_float:
        beside = [r for r in geometry.regions if r.page == figure.page and not r.in_float
                  and r.block != i and r.top > figure.bottom and r.bottom < figure.top]
        if any(_overlap(figure, r) for r in beside):
            errors.append(f"block {i}: the image overlaps text")
        wrapped = [r for r in beside if r.x1 <= figure.x0 + _TOLERANCE or r.x0 >= figure.x1 - _TOLERANCE]
        if wrapped and placement is not None and placement.horizontal in ("end", "start"):
            on_left = figure.x0 < min(r.x0 for r in wrapped)
            wants_left = (placement.horizontal == "end") == rtl
            if on_left != wants_left:
                errors.append(f"block {i}: the image is on the wrong side for the text direction")
    return errors


def check_placement(base_doc, doc, geometry, plan, rtl: bool) -> List[str]:
    """What is wrong with a rendered plan; empty when it holds."""
    errors: List[str] = []
    planned = {d.block for d in plan.decisions}
    for i, (before, after) in enumerate(zip(base_doc.blocks, doc.blocks)):
        if before.type != "image":
            continue
        if i not in planned and before.model_dump() != after.model_dump():
            errors.append(f"block {i}: an image outside the plan changed")
        if i in planned:
            errors += _check_image(i, after, geometry, rtl)
    return errors
