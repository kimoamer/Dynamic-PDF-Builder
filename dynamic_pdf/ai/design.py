"""
Director and Critic: a model chooses among designs the engine already knows how to make.

The Director reads the document brief and returns ranked art directions, the sections that
should follow on instead of opening a page, and an emphasis. The Critic reads rendered pages
and their measurements and returns issues and changes from ``ADJUSTMENTS``. Neither returns
coordinates or text. Every value is checked against the allowed sets, anything else is
dropped and reported, and every design still passes the same hard gates and content ledger.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Callable, Dict, List, Literal, Optional, Sequence, Tuple

from pydantic import BaseModel, Field

from ..design.art_direction import Adjust
from ..design.directions import DIRECTIONS
from .provider import Provider, ask, check_context, pdf_block, sha, text_block

DirectionId = Literal[tuple(DIRECTIONS)]

# The changes a model may ask for: each one a step the refinement ladder could also take.
ADJUSTMENTS: Dict[str, Callable[[Adjust], Adjust]] = {
    "tighter_spacing": lambda a: replace(a, density=max(0.8, round(a.density * 0.9, 3))),
    "smaller_exhibits": lambda a: replace(a, exhibits=max(0.76, round(a.exhibits * 0.87, 3))),
    "no_opening_pages": lambda a: replace(a, openers=False),
    "no_major_breaks": lambda a: replace(a, major_breaks=False),
    "figures_join_sections": lambda a: replace(a, hero_page=False),
    "no_side_images": lambda a: replace(a, side_images=False),
    "no_statement_pages": lambda a: replace(a, statement_pages=False),
}
AdjustName = Literal[tuple(ADJUSTMENTS)]
EMPHASIS = {"figures": (), "text": ("smaller_exhibits", "figures_join_sections", "no_statement_pages")}


def apply(adjust: Adjust, names: Sequence[str], follow_on: Sequence[str]) -> Adjust:
    for name in names:
        adjust = ADJUSTMENTS[name](adjust)
    return replace(adjust, no_break=adjust.no_break | frozenset(follow_on)) if follow_on else adjust


def _known(titles: Sequence[str], asked: Sequence[str], report: dict) -> List[str]:
    kept = [t for t in asked if t in titles]
    if len(kept) < len(asked):
        report.setdefault("dropped", []).extend(f"no section titled {t!r}" for t in asked if t not in titles)
    return kept


class DirectorReply(BaseModel):
    directions: List[DirectionId] = Field(description="art directions, best first")
    follow_on: List[str] = Field(default_factory=list, description="exact H1 titles that should follow on instead of opening a page")
    emphasis: Literal["figures", "text"] = Field("figures", description="what the pages should lead with")
    reasons: List[str] = Field(default_factory=list, description="one short reason per choice")


DIRECTOR_SYSTEM = (
    "You are the art director of a document layout engine. You choose among designs the engine already makes; "
    "you never write or change the author's text and never give coordinates. Rank the allowed art directions for "
    "this document, best first, using only ids from the allowed list. Name sections that should follow on rather "
    "than open a page only by their exact titles. Choose an emphasis: 'figures' lets exhibits lead, 'text' lets "
    "the prose lead. If the caller wrote a brief, follow it where the allowed values allow."
)


class Director:
    """Ranked directions, section treatments and emphasis from a model, for ``design_variants``.

    ``context`` is ``"brief"`` (structure and statistics, the default), ``"text"`` (also the
    document's words) or ``"pages"`` (also the plain render as a PDF)."""

    def __init__(self, provider: Optional[Provider] = None, *, context: str = "brief"):
        self.context = check_context(context)
        self._provider = provider

    @property
    def provider(self) -> Provider:
        if self._provider is None:
            from .provider import AnthropicProvider
            self._provider = AnthropicProvider()
        return self._provider

    def choose(self, sem, brief, ranked: Sequence[tuple], *, request: Optional[str] = None,
               plain_pdf: Optional[bytes] = None) -> Tuple[Optional[List[str]], Adjust, dict]:
        """(direction ids best first, or None to keep the fixed order; the starting adjustment; report)."""
        allowed = [d.id for d, _, _ in ranked]
        facts = {"brief": brief.model_dump(), "allowed_directions": {d.id: {"name": d.name, "summary": d.summary, "fit": fit}
                                                                     for d, fit, _ in ranked},
                 "caller_brief": request}
        content = [text_block(facts)]
        if self.context in ("text", "pages"):
            facts["text"] = document_text(sem)
            content.append(text_block({"document_text": facts["text"]}))
        if self.context == "pages" and plain_pdf:
            content.insert(0, pdf_block(plain_pdf))
            facts["plain_pdf_sha256"] = sha(plain_pdf)
        reply, report = ask(self.provider, feature="director", context=self.context, system=DIRECTOR_SYSTEM, content=content,
                            reply_model=DirectorReply, content_hash=content_sha(sem), facts=facts)
        if reply is None:
            return None, Adjust(), report
        order = list(dict.fromkeys(d for d in reply.directions if d in allowed))
        if len(order) < len(set(reply.directions)):
            report.setdefault("dropped", []).extend(f"direction {d} is not allowed for this document"
                                                    for d in reply.directions if d not in allowed)
        if not order:
            report.update(status="fallback", reason="no allowed direction in the reply")
            return None, Adjust(), report
        order += [d for d in allowed if d not in order]      # the rest keep their fixed order
        follow = _known([s.title for s in brief.sections], reply.follow_on, report)
        report["intent"] = {"directions": order, "follow_on": follow, "emphasis": reply.emphasis, "reasons": reply.reasons}
        return order, apply(Adjust(), EMPHASIS[reply.emphasis], follow), report


class Issue(BaseModel):
    page: int = Field(description="1-based page number")
    kind: Literal["sparse_page", "crowded_page", "short_last_page", "awkward_break", "weak_hierarchy",
                  "image_problem", "table_problem", "other"]
    note: str


class CriticReply(BaseModel):
    issues: List[Issue] = Field(default_factory=list)
    adjustments: List[AdjustName] = Field(default_factory=list, description="changes from the allowed list, most useful first")
    follow_on: List[str] = Field(default_factory=list, description="exact H1 titles that should follow on instead of opening a page")


CRITIC_SYSTEM = (
    "You review rendered pages of one design for a document layout engine. Report concrete issues you can see, "
    "by page. Then ask only for changes from the allowed list, or name sections by their exact titles that should "
    "follow on instead of opening a page. Never ask for changed text. Ask for nothing when the pages are sound."
)


class Critic:
    """Issues and changes from the allowed list, for at most ``rounds`` extra renders per design.

    ``context="pages"`` (the default) sends the rendered PDF with its measurements; ``"brief"``
    sends only the measurements."""

    def __init__(self, provider: Optional[Provider] = None, *, rounds: int = 2, context: str = "pages"):
        if not 0 <= rounds <= 5:
            raise ValueError("rounds must be between 0 and 5")
        self.rounds, self.context, self._provider = rounds, check_context(context), provider

    provider = Director.provider

    def review(self, pdf: bytes, critique, adjust: Adjust, titles: Sequence[str],
               direction: str) -> Tuple[Optional[Adjust], str, dict]:
        """(the next adjustment or None, a note for the refinement log, report)."""
        facts = {"direction": direction, "index": critique.index, "heuristics": critique.heuristics,
                 "pages": [p.model_dump() for p in critique.pages], "observations": [o.model_dump() for o in critique.observations],
                 "section_titles": list(titles), "allowed_adjustments": list(ADJUSTMENTS),
                 "already": {"density": adjust.density, "exhibits": adjust.exhibits, "openers": adjust.openers,
                             "major_breaks": adjust.major_breaks, "hero_page": adjust.hero_page,
                             "side_images": adjust.side_images, "statement_pages": adjust.statement_pages,
                             "follow_on": sorted(adjust.no_break)}}
        content = ([pdf_block(pdf)] if self.context == "pages" else []) + [text_block(facts)]
        reply, report = ask(self.provider, feature="critic", context=self.context, system=CRITIC_SYSTEM, content=content,
                            reply_model=CriticReply, content_hash=sha(pdf), facts=facts)
        if reply is None:
            return None, "", report
        report["issues"] = [i.model_dump() for i in reply.issues]
        follow = _known(titles, reply.follow_on, report)
        trial = apply(adjust, reply.adjustments, follow)
        if trial == adjust:
            return None, "", report
        asked = [*reply.adjustments, *(f"follow on: {t!r}" for t in follow)]
        return trial, "critic: " + ", ".join(asked), report


def content_sha(doc) -> str:
    """The author's content: a SemanticDocument's own hash, else the Document's JSON."""
    known = getattr(getattr(doc, "provenance", None), "content_sha256", "")
    if known:
        return known
    return sha((doc.to_document() if hasattr(doc, "to_document") else doc).model_dump_json().encode("utf-8"))


def document_text(sem) -> List[dict]:
    """The author's words block by block, for the ``text`` context. Sent, never changed."""
    out = []
    for i, b in enumerate(sem.blocks):
        text = getattr(b, "text", None)
        if b.type == "table":
            text = " | ".join(b.headers) + "\n" + "\n".join(" | ".join(map(str, r)) for r in b.rows)
        if text:
            out.append({"index": i, "type": b.type, "text": text})
    return out
