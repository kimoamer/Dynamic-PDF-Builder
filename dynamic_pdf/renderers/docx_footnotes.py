"""Real Word footnotes: a ``footnotes.xml`` part and ``w:footnoteReference`` runs.

A footnote the text refers to (``[^1]`` ... ``[^1]: text``) becomes a Word footnote at its
first reference, so Word sets it at the foot of the page and keeps it numbered while the
document is edited. A one-character mark that is not a digit ("*", "†", "a") is kept
as written (``w:customMarkFollows``); a number or a label (``[^method]``) is numbered. A definition reached before any reference to it, and a
second reference to the same note, keep their earlier rendering (a note paragraph, a
superscript marker): the author's text is never dropped or doubled.
"""
from __future__ import annotations

from typing import Dict, Optional

from docx.enum.style import WD_STYLE_TYPE
from docx.opc.constants import CONTENT_TYPE as CT, RELATIONSHIP_TYPE as RT
from docx.opc.packuri import PackURI
from docx.opc.part import XmlPart
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Pt
from docx.text.paragraph import Paragraph

_SEPARATORS = (
    f'<w:footnotes {nsdecls("w", "r")}>'
    '<w:footnote w:type="separator" w:id="-1"><w:p><w:pPr><w:spacing w:after="0" w:line="240" '
    'w:lineRule="auto"/></w:pPr><w:r><w:separator/></w:r></w:p></w:footnote>'
    '<w:footnote w:type="continuationSeparator" w:id="0"><w:p><w:pPr><w:spacing w:after="0" '
    'w:line="240" w:lineRule="auto"/></w:pPr><w:r><w:continuationSeparator/></w:r></w:p></w:footnote>'
    '</w:footnotes>')


class _NotesPart:
    """What a paragraph inside the footnotes part asks of its part: styles from the document,
    relationships (hyperlinks) on the footnotes part itself."""

    def __init__(self, notes: XmlPart, doc_part):
        self._notes, self._doc = notes, doc_part

    def __getattr__(self, name):
        return getattr(self._notes, name)

    @property
    def document(self):
        return self._doc.document

    def get_style_id(self, *a):
        return self._doc.get_style_id(*a)

    def get_style(self, *a):
        return self._doc.get_style(*a)


class _Parent:
    def __init__(self, part):
        self.part = part


class Footnotes:
    def __init__(self, doc, blocks, note_size: float):
        self.doc = doc
        self.note_size = note_size
        self.defs: Dict[str, str] = {}
        for b in blocks:
            if getattr(b, "type", "") == "footnote":
                self.defs.setdefault(b.marker, b.text)
        self.emitted: Dict[str, int] = {}
        self.in_body = set()
        self.auto = 0
        self._part: Optional[XmlPart] = None

    # ── the part and its styles ──
    def _ensure(self):
        if self._part is not None:
            return self._part
        doc = self.doc
        part = XmlPart(PackURI("/word/footnotes.xml"), CT.WML_FOOTNOTES, parse_xml(_SEPARATORS), doc.part.package)
        doc.part.relate_to(part, RT.FOOTNOTES)
        styles = doc.styles
        if "Footnote Text" not in [s.name for s in styles]:
            ft = styles.add_style("Footnote Text", WD_STYLE_TYPE.PARAGRAPH)
            ft.base_style = styles["Normal"]
            ft.font.size = Pt(self.note_size)
            ft.paragraph_format.space_after = Pt(0)
            ft.paragraph_format.first_line_indent = None
            fr = styles.add_style("Footnote Reference", WD_STYLE_TYPE.CHARACTER)
            fr.font.superscript = True
        self._part = part
        self._proxy = _NotesPart(part, doc.part)
        return part

    # ── renderer hooks ──
    def reference(self, paragraph, marker: str, write) -> bool:
        """Put a footnote reference in ``paragraph`` and the note in the footnotes part.
        ``write(p, text)`` sets the note's text as runs. False: render the marker as before."""
        if marker not in self.defs or marker in self.emitted or marker in self.in_body:
            return False
        part = self._ensure()
        from ..core.numbering import numbered_note
        custom = not numbered_note(marker)          # a label or number is Word's next number, as in the PDF
        if not custom:
            self.auto += 1
        nid = len(self.emitted) + 1
        self.emitted[marker] = nid
        ref = paragraph.add_run()
        ref.style = "Footnote Reference"
        el = OxmlElement("w:footnoteReference")
        el.set(qn("w:id"), str(nid))
        if custom:
            el.set(qn("w:customMarkFollows"), "1")
        ref._r.append(el)
        if custom:
            ref._r.append(_text(marker))
        note = OxmlElement("w:footnote")
        note.set(qn("w:id"), str(nid))
        part.element.append(note)
        p_el = OxmlElement("w:p")
        note.append(p_el)
        p = Paragraph(p_el, _Parent(self._proxy))
        p.style = "Footnote Text"
        mark = p.add_run()
        mark.style = "Footnote Reference"
        mark._r.append(_text(marker) if custom else OxmlElement("w:footnoteRef"))
        p.add_run(" ")
        write(p, self.defs[marker])
        return True

    def skip_block(self, marker: str) -> bool:
        """Whether a footnote definition already lives in the footnotes part."""
        if marker in self.emitted:
            return True
        self.in_body.add(marker)
        return False


def _text(s: str):
    t = OxmlElement("w:t")
    t.text = s
    t.set(qn("xml:space"), "preserve")
    return t
