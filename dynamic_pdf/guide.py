"""The guide to the library, for people and AI agents: ``GUIDE.md``, shipped in the package."""
from __future__ import annotations

import re
from importlib import resources
from typing import Dict, Optional


def _sections() -> Dict[str, str]:
    text = resources.files("dynamic_pdf").joinpath("GUIDE.md").read_text(encoding="utf-8")
    parts = re.split(r"(?m)^## ", text)
    out = {"": parts[0].strip()}
    for part in parts[1:]:
        title = part.split("\n", 1)[0].strip()
        out[re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")] = "## " + part.strip()
    return out


def topics() -> list:
    return [k for k in _sections() if k]


def guide(topic: Optional[str] = None) -> str:
    """The whole guide, or one of its sections by topic (``"tables"``, ``"markdown"``, ...)."""
    sections = _sections()
    if not topic:
        return "\n\n".join(sections.values()) + "\n"
    key = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")
    found = sections.get(key) or next((v for k, v in sections.items() if k and k.startswith(key)), None)
    if found is None:
        raise ValueError(f"no topic {topic!r}; topics: {', '.join(topics())}")
    return found + "\n"
