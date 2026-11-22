"""Footnotes at the foot of the page their reference falls on, as Word sets them.

A reference carries a mark (``<onDraw name="_dpb_note">``) that tells the page, as the reference is
drawn, to set its note at its foot: the note's height is taken from the frame there, so the text that
follows stops above it, and the page draws its notes in order under a short rule as it ends. The block
holding the reference is carried (``NoteCarrier``) so that it only fits on a page with room for those
notes too; a block that breaks leaves that room on the page its reference falls on, whichever piece of
a long table or paragraph holds it. A reference the carrier cannot find in the block's pieces falls back
to an anchor after the block (``FootnoteAnchor``).
"""
from __future__ import annotations

import re

from reportlab.platypus import Flowable

REF = re.compile(r"\[\^([\w-]+)\]")
GAP = 4.0              # the rule sits in the middle of twice this, above the first note on a page
MARK = "_dpb_note"     # the canvas callback a reference's onDraw names


def keys_in(f, depth: int = 0) -> set:
    """The note keys whose reference marks a flowable (or a piece of one) will draw."""
    if f is None or depth > 12:
        return set()
    if isinstance(f, (list, tuple)):
        return set().union(*(keys_in(x, depth + 1) for x in f)) if f else set()
    out = set()
    cb = getattr(f, "cbDefn", None)
    if cb is not None and getattr(cb, "kind", None) == "onDraw" and getattr(cb, "name", None) == MARK:
        out.add(cb.label)
    for name in ("frags", "_content", "_cellvalues", "_flowable", "_flowables"):
        inner = getattr(f, name, None)
        if inner is not None:
            out |= keys_in(inner, depth + 1)
    return out


def note_need(frame, paras) -> float:
    """Height the notes take at the frame's foot, with the rule's gap when they are its first."""
    first = not frame.__dict__.get("_dpb_notes")
    return sum(p.wrap(frame._aW, 1e6)[1] + p.getSpaceAfter() for p in paras) + (2 * GAP if first else 0)


def reserve(frame, paras) -> None:
    """Take the notes' height from the frame's foot and hand the notes to the page."""
    need = note_need(frame, paras)
    frame.__dict__.setdefault("_dpb_notes", []).extend(paras)
    frame._dpb_notes_h = frame.__dict__.get("_dpb_notes_h", 0) + need
    frame._y1p += need              # the text after stops short of the notes; draw_notes gives it back


class NoteCarrier(Flowable):
    """A block holding note references, laid out only where the notes of the references it draws
    there fit at the page's foot. Split, the piece that holds a reference leaves room for its note."""

    def __init__(self, inner, notes: dict, drawn: set):
        super().__init__()
        self.inner, self.notes, self.drawn = inner, notes, drawn     # notes: key -> paragraphs
        self._content = [inner]          # tagged with its block, as any container is
        self.frame = None
        self.width = self.height = 0

    def getSpaceBefore(self):
        return self.inner.getSpaceBefore()

    def getSpaceAfter(self):
        return self.inner.getSpaceAfter()

    def getKeepWithNext(self):
        return self.inner.getKeepWithNext()

    def _need(self, piece) -> float:
        keys = [k for k in sorted(keys_in(piece)) if k in self.notes and k not in self.drawn]
        if not keys or self.frame is None:
            return 0.0
        return note_need(self.frame, [p for k in keys for p in self.notes[k]])

    def wrap(self, aW, aH):
        self.width, self.height = self.inner.wrapOn(self.canv, aW, aH)     # a list measures on the canvas
        need = self._need(self.inner)
        return self.width, self.height + (need if self.height + need > aH else 0)   # too tall: split it

    def split(self, aW, aH):
        parts = self.inner.splitOn(self.canv, aW, aH)
        if len(parts) < 2:
            return []
        need = self._need(parts[0])
        if need:                         # the first piece holds a reference: it leaves its note's room
            parts = self.inner.splitOn(self.canv, aW, aH - need)
            if len(parts) < 2:
                return []
        head, rest = parts[0], parts[1:]
        for a in ("_dpb_block", "_dpb_role", "_dpb_level", "_dpb_extra_blocks"):
            if hasattr(self, a) and not hasattr(head, a):
                setattr(head, a, getattr(self, a))
        tail = NoteCarrier(rest[0], self.notes, self.drawn) if len(rest) == 1 else None
        return [head, tail] if tail is not None else [head, *rest]

    def draw(self):
        self.inner.drawOn(self.canv, 0, 0)


class FootnoteAnchor(Flowable):
    def __init__(self, notes):
        super().__init__()
        self.notes = list(notes)        # the notes' paragraphs, numbered as the text refers to them
        self.frame = None               # the frame it is laid out in, set by the page template
        self.width = self.height = 0

    def _need(self, frame) -> float:
        return note_need(frame, self.notes)

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
        reserve(frame, self.notes)


def draw_notes(canv, frames, color, rtl: bool) -> None:
    """The notes the page's frames reserved, top down from the reserved height, under a short rule."""
    for frame in frames:
        notes = frame.__dict__.pop("_dpb_notes", None)
        height = frame.__dict__.pop("_dpb_notes_h", 0)
        frame._y1p -= height            # the frame is reused: the next page gets its full height back
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
