"""Field values for header and footer bands, from the document and its page system."""

from datetime import datetime
from typing import Dict, Tuple


def band_values(document, hf=None) -> Tuple[Dict[str, str], Dict[str, str]]:
    """The fixed field values, and sample values for the fields that change by page,
    so margins are measured against the longest running title."""
    meta = document.meta
    system = meta.page_system
    values = {"title": meta.title or "", "subtitle": meta.subject or "", "author": meta.author or "",
              "date": datetime.now().strftime(getattr(hf, "date_format", None) or "%B %d, %Y")}
    if hf is not None:
        for key, attr in (("company", "company_name"), ("website", "website"), ("email", "email"),
                          ("phone", "phone")):
            if getattr(hf, attr, None):
                values[key] = getattr(hf, attr)
    if system is not None:
        values.update(system.values)
    heads = [b.text for b in document.blocks if getattr(b, "type", None) == "heading" and b.level <= 2]
    longest = max(heads, key=len, default="")
    return values, {"section": longest, "chapter": longest}
