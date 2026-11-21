"""Footnotes at the foot of the page their reference falls on, as Word sets them.

An anchor follows the block that first refers to a note. It takes no room where it stands; laid
out on a page, it reserves the note's height at the foot of the frame, so the text stops above it,
and hands the note to the page, which draws its notes in order under a short rule as it ends. A note
with no room left on the page goes to the next one, with the text that follows its reference.
"""
from __future__ import annotations

import re

from reportlab.platypus import Flowable

REF = re.compile(r"\[\^([\w-]+)\]")
GAP = 4.0              # the rule sits in the middle of twice this, above the first note on a page


class FootnoteAnchor(Flowable):
    def __init__(self, notes):
        super().__init__()
        self.notes = list(notes)        # the notes' paragraphs, numbered as the text refers to them
        self.frame = None               # the frame it is laid out in, set by the page template
        self.width = self.height = 0

    def _need(self, frame) -> float:
        first = not frame.__dict__.get("_dpb_notes")
        return sum(p.wrap(frame._aW, 1e6)[1] + p.getSpaceAfter() for p in self.notes) + (2 * GAP if first else 0)

    def wrap(self, aw, ah):
        frame = self.frame
        if frame is None:               # measured inside a group: it is laid out on its own later
            return aw, 0
        # shortcut: a note taller than an empty page is reserved whole and runs up into the text; notes
        # that long are not footnotes, so this is left as it is
        if self._need(frame) > frame._y - frame._y1p and not frame._atTop:
            return aw, frame._y - frame._y1p + 1          # no room left here: to the next page
        return aw, 0

    def draw(self):
        frame = self.frame
        if frame is None:
            return
        need = self._need(frame)
        frame.__dict__.setdefault("_dpb_notes", []).extend(self.notes)
        frame._dpb_notes_h = frame.__dict__.get("_dpb_notes_h", 0) + need
        frame._y1p += need              # the text above stops short of the notes; the next page resets it


def draw_notes(canv, frames, color, rtl: bool) -> None:
    """The notes the page's frames reserved, top down from the reserved height, under a short rule."""
    for frame in frames:
        notes = frame.__dict__.pop("_dpb_notes", None)
        height = frame.__dict__.pop("_dpb_notes_h", 0)
        if not notes:
            continue
        x, width = frame._x1 + frame._leftPadding, frame._aW
        y = frame._y1 + frame._bottomPadding + height
        rule = min(width * 0.3, 120)
        canv.saveState()
        canv.setStrokeColor(color)
        canv.setLineWidth(0.5)
        start = x + width - rule if rtl else x
        canv.line(start, y - GAP, start + rule, y - GAP)
        canv.restoreState()
        y -= 2 * GAP
        for p in notes:
            h = p.wrap(width, 1e6)[1]
            p.drawOn(canv, x, y - h)
            y -= h + p.getSpaceAfter()
