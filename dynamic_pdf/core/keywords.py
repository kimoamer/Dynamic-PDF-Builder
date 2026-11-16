"""
Keyword lists as data (``dynamic_pdf/data/keywords.json``), compiled to patterns once.

A list is a mapping with up to three keys: ``en`` fragments match whole words, ``ar``
fragments match anywhere (Arabic joins prefixes to the word), ``raw`` fragments are used
as written. Matching ignores case.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from importlib import resources
from typing import Optional


@lru_cache(maxsize=1)
def keywords() -> dict:
    return json.loads(resources.files("dynamic_pdf").joinpath("data/keywords.json").read_text(encoding="utf-8"))


def compile_terms(entry: dict) -> Optional[re.Pattern]:
    parts = []
    if entry.get("en"):
        parts.append(r"\b(?:" + "|".join(entry["en"]) + r")\b")
    parts += list(entry.get("ar") or [])
    parts += list(entry.get("raw") or [])
    return re.compile("|".join(f"(?:{p})" for p in parts), re.IGNORECASE) if parts else None


@lru_cache(maxsize=None)
def pattern(*path: str) -> Optional[re.Pattern]:
    """The compiled pattern of the list at ``path``, e.g. ``pattern("tables", "total")``."""
    entry = keywords()
    for key in path:
        entry = entry[key]
    return compile_terms(entry)
