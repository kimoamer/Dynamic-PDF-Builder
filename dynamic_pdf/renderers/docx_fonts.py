"""Embed bundled fonts in a DOCX, so Word shows the design on a machine without them.

Fonts travel in the package as obfuscated parts (ECMA-376, part 4), which every recent Word
reads. All bundled families are under the SIL Open Font License and allow embedding.
"""

from __future__ import annotations

import io
import os
import re
import uuid
import zipfile
from typing import Iterable, List, Tuple

from ..fonts.manager import BUNDLED_DIR, font_catalog

FONT_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/font"
FONT_TYPE = "application/vnd.openxmlformats-officedocument.obfuscatedFont"
KEY_SPACE = uuid.UUID("6f2b9c1e-3f7a-4c55-9a51-0d4e5b7c2a10")
ELEMENT = {"regular": "embedRegular", "bold": "embedBold", "italic": "embedItalic"}
BEFORE_EMBED = ("writeProtection", "view", "zoom", "removePersonalInformation", "removeDateAndTime",
                "doNotDisplayPageBoundaries", "displayBackgroundShape", "printPostScriptOverText",
                "printFractionalCharacterWidth", "printFormsData")


def obfuscate(data: bytes, key: str) -> bytes:
    """XOR the first 32 bytes with the GUID, read backwards, as the standard sets out."""
    secret = bytes.fromhex(key.replace("-", ""))[::-1]
    head = bytes(b ^ secret[i % 16] for i, b in enumerate(data[:32]))
    return head + data[32:]


def _settings(xml: str) -> str:
    if "<w:embedTrueTypeFonts" in xml:
        return xml
    place = 0
    for name in BEFORE_EMBED:
        for m in re.finditer(rf"<w:{name}\b[^>]*/>", xml):
            place = max(place, m.end())
    if not place:
        place = xml.index(">", xml.index("<w:settings")) + 1
    return xml[:place] + "<w:embedTrueTypeFonts/>" + xml[place:]


def embed_fonts(docx: bytes, families: Iterable[str]) -> bytes:
    """The same document with these catalog families inside. Others are left to Word."""
    catalog = font_catalog()
    wanted = sorted({f for f in families if f in catalog})
    if not wanted:
        return docx
    parts: List[Tuple[str, bytes]] = []
    entries, rels = [], []
    number = 0
    for family in wanted:
        tags = []
        for style, name in catalog[family]["files"].items():
            number += 1
            key = str(uuid.uuid5(KEY_SPACE, f"{family}/{style}")).upper()
            with open(os.path.join(BUNDLED_DIR, name), "rb") as f:
                parts.append((f"word/fonts/font{number}.odttf", obfuscate(f.read(), key)))
            rels.append(f'<Relationship Id="rIdF{number}" Type="{FONT_REL}" Target="fonts/font{number}.odttf"/>')
            tags.append((list(ELEMENT).index(style), f'<w:{ELEMENT[style]} r:id="rIdF{number}" w:fontKey="{{{key}}}"/>'))
        body = "".join(t for _, t in sorted(tags))
        entries.append((family, f'<w:font w:name="{family}">{body}</w:font>'))
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(docx)) as src, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == "[Content_Types].xml":
                text = data.decode("utf-8")
                if 'Extension="odttf"' not in text:
                    text = text.replace("<Default ", f'<Default Extension="odttf" ContentType="{FONT_TYPE}"/><Default ', 1)
                data = text.encode("utf-8")
            elif item.filename == "word/settings.xml":
                data = _settings(data.decode("utf-8")).encode("utf-8")
            elif item.filename == "word/fontTable.xml":
                text = data.decode("utf-8")
                for family, entry in entries:     # a font Word already listed is replaced, not doubled
                    text = re.sub(rf'<w:font w:name="{re.escape(family)}">.*?</w:font>', "", text, flags=re.S)
                data = text.replace("</w:fonts>", "".join(e for _, e in entries) + "</w:fonts>").encode("utf-8")
            elif item.filename == "word/_rels/fontTable.xml.rels":
                continue
            dst.writestr(item.filename, data)
        dst.writestr("word/_rels/fontTable.xml.rels",
                     '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                     '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                     + "".join(rels) + "</Relationships>")
        for name, data in parts:
            dst.writestr(name, data)
    return out.getvalue()
