"""
Choosing where images go, without touching what the document says.

Each plan is a proposal with its reasons: whether it holds up is decided by rendering
it. Plans never generate text and never crop. An image the author placed or sized keeps
exactly what they set, and an image of unknown purpose stays inline and uncropped.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from ..media import ingest
from ..schema.media import ImageTreatment, resolve_placement
from .media_policy import COMPACT, FLOAT, FULL_WIDTH, MEDIA_POLICY_VERSION, MediaPolicy

LOCKING_FIELDS = ("placement", "width", "height", "treatment")
_INFORMATIONAL = {"photo", "figure", "chart", "screenshot", "diagram"}
_MIX = "mix"
_CAPTION_ROOM = 48.0       # a caption, a source line and their gaps under a float
_PAGE_GAP = 12.0


@dataclass(frozen=True)
class PlacementDecision:
    source_node_id: Optional[str]
    block: int
    anchor_group_id: str
    placement: str
    box: Tuple[float, Optional[float]]        # width and height, in points; None: from the aspect
    fit: str
    logical_side: Optional[str]
    target_overrides: Dict[str, str]
    reason_codes: Tuple[str, ...]
    width_ratio: Optional[float] = None


@dataclass
class MediaPlan:
    name: str
    style: str
    policy_version: str
    source_hash: str
    decisions: List[PlacementDecision]
    rejected: List[dict] = field(default_factory=list)
    metrics: Dict[str, float] = field(default_factory=dict)
    reasons: List[str] = field(default_factory=list)
    lossless_bands: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def role_of(block) -> str:
    intent = getattr(block, "intent", None)
    role = intent.role if intent is not None else "auto"
    return "unknown" if role == "auto" else role


def locked_fields(block) -> List[str]:
    """Fields the author actually set. A field left at its default locks nothing."""
    return [name for name in LOCKING_FIELDS
            if name in block.model_fields_set and getattr(block, name) is not None]


def _following_height(index: int, blocks, measures: Sequence) -> float:
    """Height of the paragraphs right after an image, at the full frame width. A float
    never reaches past them to a heading, table or column run."""
    total = 0.0
    for nxt in blocks[index + 1:]:
        if nxt.type != "paragraph" or (nxt.hints or {}).get("flow_run") is not None:
            break
        total += measures[blocks.index(nxt)].height if measures else 0
    return total


class _Sizer:
    def __init__(self, doc, policy: MediaPolicy, envelope, options, assets, positions, measures):
        self.doc, self.policy, self.env, self.o = doc, policy, envelope, options
        self.assets, self.positions, self.measures = assets, positions, measures

    def decide(self, i: int, block, style: str):
        """A decision for one image in one style, or the code of why it cannot be."""
        role, intent = role_of(block), block.intent
        if style not in self.policy.styles:
            return "policy_disallows_style"
        if role in ("decorative", "logo", "signature") and style != COMPACT:
            return "role_stays_inline"
        if role == "unknown" and style != COMPACT:
            return "unknown_role_stays_inline"
        prominence = intent.prominence if intent else "normal"
        if prominence == "hero" and style == COMPACT:
            return "hero_stays_large"
        if prominence == "supporting" and style == FULL_WIDTH:
            return "supporting_stays_small"
        asset = ingest(block.src, self.assets)
        room_w, room_h = self.env.inner_width, self.env.inner_height
        dpi_w = room_w if asset.is_vector else asset.width * 72 / self.o.min_dpi
        least = (intent.min_display_width_pt if intent else None) or 0
        if least > dpi_w:
            return "needs_better_asset"
        if least > room_w:
            return "minimum_exceeds_frame"
        if style == COMPACT:
            ratio = self.policy.compact_ratio if role == "photo" else 1.0
            width = min(dpi_w, room_w * ratio, room_h * self.policy.compact_height * asset.aspect)
        else:
            width = min(dpi_w, room_w, room_h * self.policy.full_height * asset.aspect)
        codes = ["measured_frame", "aspect_kept"]
        if width == dpi_w and not asset.is_vector:
            codes.append("dpi_limited")
        width = max(width, least)
        if style == FLOAT:
            return self._float(i, block, role, width, least, asset, codes)
        placement = "inline" if style == COMPACT else "full_width"
        return self._decision(i, block, placement, width, None, None, codes)

    def _float(self, i, block, role, width, least, asset, codes):
        if role not in self.policy.float_roles:
            return "role_cannot_float"
        room_w = self.env.inner_width
        width = max(min(width, room_w * 0.38), least)
        narrow = room_w - width - _PAGE_GAP
        if narrow < self.o.min_float_text_width_pt:
            return "float_text_too_narrow"
        height = width / asset.aspect
        spot = self.positions.get(i)
        left = spot.top - self.env.bottom - _PAGE_GAP if spot else 0
        if height + _CAPTION_ROOM > left:
            return "float_does_not_fit_page"
        wrapped = _following_height(i, self.doc.blocks, self.measures) * room_w / narrow
        if wrapped < height + _CAPTION_ROOM:
            return "float_needs_more_text"
        return self._decision(i, block, "float_end", width, "end", width / room_w,
                              codes + ["text_wraps_beside_image"])

    @staticmethod
    def _decision(i, block, placement, width, side, ratio, codes):
        return PlacementDecision(block.id, i, f"group-{i}", placement, (round(width, 3), None), "contain", side,
                                 {}, tuple(codes), ratio)


def plan_media(doc, policy: MediaPolicy, envelope, options, assets, positions: Dict[int, object],
               measures: Sequence, source_hash: str) -> List[MediaPlan]:
    """Plans for the images of ``doc``, best guess first, in a fixed order. Equal plans
    appear once. ``positions`` holds where each block is predicted to start."""
    sizer = _Sizer(doc, policy, envelope, options, assets, positions, measures)
    images = [(i, b) for i, b in enumerate(doc.blocks) if b.type == "image"]
    free = [(i, b) for i, b in images if not locked_fields(b)]
    kept = [{"block": i, "style": "any", "code": "explicit_locked", "fields": locked_fields(b)}
            for i, b in images if locked_fields(b)]
    plans: List[MediaPlan] = []
    seen = set()
    for style in (_MIX, *policy.styles):
        decisions, rejected = [], list(kept)
        for i, block in free:
            tried = policy.styles if style == _MIX else (style,)
            outcome = None
            for one in tried:
                outcome = sizer.decide(i, block, one)
                if isinstance(outcome, PlacementDecision):
                    break
                rejected.append({"block": i, "style": one, "code": outcome})
            if isinstance(outcome, PlacementDecision):
                decisions.append(outcome)
        key = tuple((d.block, d.placement, d.box) for d in decisions)
        if decisions and key not in seen:
            seen.add(key)
            plans.append(MediaPlan(f"media:{style}", style, MEDIA_POLICY_VERSION, source_hash, decisions, rejected))
    return plans[:options.max_media_candidates]


def apply_media_plan(doc, plan: MediaPlan):
    """A copy of ``doc`` with the plan applied. Only layout fields change."""
    out = doc.model_copy(deep=True)
    for d in plan.decisions:
        block = out.blocks[d.block]
        placement = resolve_placement(d.placement)
        placement.width_ratio = d.width_ratio
        block.placement = placement
        block.width = d.box[0]
        block.treatment = ImageTreatment(fit=d.fit)
    if plan.lossless_bands and out.meta.page_system is not None:
        out.meta.page_system = out.meta.page_system.model_copy(update={"lossless": True})
    return out


def band_decision(doc, theme, render_policy) -> dict:
    """Whether the bands lose text as designed, and whether a lossless layout saves it."""
    from ..layout.page_envelope import resolve_page_envelope
    if doc.meta.page_system is None:
        return {"status": "none", "losses": []}
    before = resolve_page_envelope(doc, theme, render_policy).band_losses
    if not before:
        return {"status": "kept", "losses": []}
    trial = doc.model_copy(deep=True)
    trial.meta.page_system = trial.meta.page_system.model_copy(update={"lossless": True})
    after = resolve_page_envelope(trial, theme, render_policy).band_losses
    return {"status": "band_content_unfit" if after else "reflowed",
            "losses": [x.describe() for x in (after or before)]}


__all__ = ["COMPACT", "FLOAT", "FULL_WIDTH", "MediaPlan", "PlacementDecision", "apply_media_plan", "band_decision",
           "locked_fields", "plan_media", "role_of"]
