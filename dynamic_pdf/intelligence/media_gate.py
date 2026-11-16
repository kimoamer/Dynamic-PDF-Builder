"""
The composer's side of automatic image placement.

A plan reaches the output only by passing, in order: the hard gates (content kept, every
block placed, nothing clipped or overlapping, no informational crop, bands whole, every
requested format), the composer's non-regression policy, and a measured gain. Anything
not fully checked is not approved: the designed layout stays.
"""

from __future__ import annotations

import subprocess
import time
from typing import Dict, List, Optional

LEGIBILITY_WEIGHT = 8.0     # score points for full image legibility; uncalibrated
BAND_RESCUE = 100.0         # keeping band text outranks any layout score
MIN_LO_TIMEOUT_S = 5


def image_legibility(doc, geometry, assets, min_dpi: float) -> float:
    """Mean of how close each image comes to the resolution and width it needs, from
    where it was really drawn. 1.0 when there is no image to judge."""
    from ..media import ingest
    values: List[float] = []
    for i, block in enumerate(doc.blocks):
        if block.type != "image":
            continue
        drawn = max((r.x1 - r.x0 for r in geometry.regions if r.block == i and r.role == "figure"), default=0)
        if drawn <= 0:
            continue
        asset = ingest(block.src, assets)
        value = 1.0 if asset.is_vector else min(1.0, asset.width * 72 / drawn / min_dpi)
        least = block.intent.min_display_width_pt if block.intent else None
        if least and drawn < least - .5:
            value = min(value, drawn / least)
        values.append(value)
    return round(sum(values) / len(values), 4) if values else 1.0


class MediaGate:
    def __init__(self, composer, doc, theme):
        from ..core.content_ledger import build_content_ledger
        from ..design.media_planner import band_decision
        from ..design.media_policy import MEDIA_POLICY_VERSION
        from ..layout.engine import is_rtl_document
        from ..policy import RenderPolicy
        self.c, self.doc, self.theme = composer, doc, theme
        self.o = composer.o.media
        self.assets = (composer.policy or RenderPolicy()).assets
        self.rtl = is_rtl_document(doc)
        self.plans: Dict[str, object] = {}
        self.bonuses: Dict[str, float] = {}
        self.statuses: Dict[str, str] = {}
        self.base_pdf: Optional[bytes] = None
        self.base_legibility = 1.0
        self.base_valid = True
        self.ledger = build_content_ledger(doc, self.assets, theme)
        self.bands = band_decision(doc, theme, composer.policy) if self.o.lossless_bands else {"status": "kept"}
        r = composer.report
        r.source_ledger = self.ledger.fingerprint()
        r.asset_hashes = dict(self.ledger.assets)
        r.effective_policy_version = MEDIA_POLICY_VERSION
        r.band_decisions = [self.bands]
        r.media_decisions = []
        r.validation_by_format = {}

    # ── plans ──
    def _policy(self, profile: str):
        from ..design.media_policy import media_policy_for
        recipe = self.c.recipe
        return recipe.media_policy if recipe is not None else media_policy_for(profile)

    def shortlist(self, doc, theme, profile: str, measures) -> list:
        """Candidates to render, the likely shortest first. A clean prediction is no
        reason to skip them: it says nothing about how images are used."""
        from ..design.media_planner import MediaPlan, apply_media_plan
        from ..design.media_policy import MEDIA_POLICY_VERSION
        from .candidates import media_candidates
        from .composer import CandidateResult
        plans = media_candidates(doc, theme, self._policy(profile), self.o, self.c.policy, measures,
                                 self.ledger.fingerprint())
        if self.bands["status"] == "band_content_unfit":
            self.c.report.media_decisions.append({"name": "bands", "status": "rejected",
                                                  "reason": "band_content_unfit"})
            return []
        if self.rescue and not plans:
            plans = [MediaPlan("media:bands", "bands", MEDIA_POLICY_VERSION, self.ledger.fingerprint(), [])]
        ranked = []
        for rank, plan in enumerate(plans):
            plan.lossless_bands = self.rescue
            res = CandidateResult(name=plan.name, reason=f"image plan: {plan.style}")
            self.c.report.candidates.append(res)
            why = self.c._over_budget()
            if why:
                res.rejected = f"not evaluated: {why}"
                self.c.report.fallbacks.append(why)
                break
            d = apply_media_plan(doc, plan)
            res.changes = [f"block {x.block}: {x.placement}, {x.box[0]:g} pt wide" for x in plan.decisions]
            pred, pages, _ = self.c._predict(d, theme)
            res.predicted_score, res.predicted_pages = pred.score, pages
            self.plans[res.name] = plan
            ranked.append((pages, rank, res, d))
        ranked.sort(key=lambda x: x[:2])
        return [(res, d, theme) for _, _, res, d in ranked]

    @property
    def rescue(self) -> bool:
        return self.bands["status"] == "reflowed"

    def owns(self, res) -> bool:
        return res.name in self.plans

    def bonus(self, res) -> float:
        return self.bonuses.get(res.name, 0.0)

    def suggesting(self, res) -> bool:
        """In suggest mode a sound plan is reported, never delivered."""
        if self.o.mode != "suggest" or not self.base_valid:
            return False            # a broken layout is not worth keeping over a proven plan
        res.rejected = "suggested only: the designed layout is kept"
        self.statuses[res.name] = "suggested"
        return True

    # ── checks ──
    def baseline(self, pdf: bytes, geometry, valid: bool) -> None:
        self.base_pdf, self.base_valid = pdf, valid
        self.base_legibility = image_legibility(self.doc, geometry, self.assets, self.o.min_dpi)

    def review(self, res, d, t, pdf: bytes, geometry) -> float:
        """Hard gates of a rendered plan. Sets ``res.rejected`` on failure; otherwise
        returns what the plan has earned beyond the layout score."""
        from ..core.content_ledger import build_content_ledger
        from ..qa.content_preservation import check_preservation, same_extracted_words
        from ..qa.media_checks import check_pdf_media
        from ..qa.placement_checks import check_placement
        plan = self.plans[res.name]
        report = check_preservation(self.ledger, candidate=build_content_ledger(d, self.assets, t),
                                    geometry=geometry, pdf=pdf)
        reasons = [f"{x.name}: {x.details[0]}" for x in report.layers if x.status == "failed" and x.details]
        reasons += check_placement(self.doc, d, geometry, plan, self.rtl)
        reasons += [f"{x['code']}: page {x.get('page', '?')}" for x in check_pdf_media(pdf)]
        qa = self.c.inspect(d, t, pdf)
        if qa is not None:
            reasons += [f"QA {f.code}: {f.message}" for f in qa.errors]
        if not reasons and report.status == "unknown" and not same_extracted_words(self.base_pdf, pdf):
            reasons.append("unverified: the extracted text differs from the designed layout's")
        if reasons:
            res.rejected = "; ".join(reasons[:3])
            return 0.0
        legibility = image_legibility(d, geometry, self.assets, self.o.min_dpi)
        res.metrics["image_legibility"] = legibility
        bonus = LEGIBILITY_WEIGHT * (legibility - self.base_legibility)
        if plan.lossless_bands:
            bonus += BAND_RESCUE
        self.bonuses[res.name] = bonus
        return bonus

    def settle_docx(self, best, designed):
        """The chosen plan must also hold as DOCX when DOCX was asked for. Only the designed
        layout and this one plan are rendered, so a failure restores the designed layout."""
        if "docx" not in self.o.targets:
            return best
        why = self._docx_failure(best[1], best[2], designed[1], designed[2])
        if why is None:
            return best
        best[0].rejected = why
        self.statuses[best[0].name] = "rejected"
        self.c.report.fallback_reason = why
        return designed

    def _render_docx(self, doc, theme) -> bytes:
        from ..core.normalize import normalize
        from ..renderers.docx_renderer import render_docx
        return render_docx(normalize(doc), theme, self.c.policy)[0]

    def _docx_failure(self, d, t, base_doc, base_theme) -> Optional[str]:
        from ..qa.content_preservation import check_docx_content, check_pdf_content, same_extracted_words
        from ..qa.docx_checks import check_docx, docx_to_pdf, office_version
        from ..qa.media_checks import check_docx_media
        v = self.c.report.validation_by_format
        if self.o.max_docx_renders < 2:
            v["docx"] = "unverified"
            return "unverified: the DOCX render budget does not cover baseline and candidate"
        data, base_data = self._render_docx(d, t), self._render_docx(base_doc, base_theme)
        structural = check_docx(data)
        content = check_docx_content(self.ledger, data)
        problems = ([f"QA {f.code}: {f.message}" for f in structural.errors] + content.details[:2]
                    if content.status == "failed" else [f"QA {f.code}: {f.message}" for f in structural.errors])
        problems += [x["code"] for x in check_docx_media(data)]
        if problems:
            v["docx"] = "failed"
            return "docx: " + "; ".join(problems[:3])
        if self.o.word_required:
            v["word"] = "unverified"
            self.c.report.unverified.append("word (no Word adapter)")
        if self.o.docx_validation == "structural":
            v["docx"] = "structural_only"
            return "unverified: Word was required but could not be run" if self.o.word_required else None
        limit = self.c.o.time_budget_s - (time.perf_counter() - self.c._t0)
        try:
            timeout = max(MIN_LO_TIMEOUT_S, int(limit))
            pdf, base_pdf = docx_to_pdf(data, timeout), docx_to_pdf(base_data, timeout)
        except subprocess.TimeoutExpired:
            pdf = base_pdf = None
        if pdf is None or base_pdf is None:
            v["docx"] = "unverified"
            self.c.report.unverified.append("docx_libreoffice (not available)")
            return "unverified: LibreOffice could not check the DOCX"
        extracted = check_pdf_content(self.ledger, pdf)
        if extracted.status == "failed":
            v["docx"] = "failed"
            return "docx via LibreOffice: " + extracted.details[0]
        if extracted.status == "unknown" and not same_extracted_words(base_pdf, pdf):
            v["docx"] = "unverified"
            return "unverified: LibreOffice text differs from the designed layout's"
        pages, base_pages = _pages(pdf), _pages(base_pdf)
        if pages > base_pages + self.c.o.max_extra_pages:
            v["docx"] = "rejected"
            return f"docx adds {pages - base_pages} pages under LibreOffice"
        v["docx"] = f"libreoffice ({office_version() or 'unknown'}); pages {base_pages} -> {pages}"
        return "unverified: Word was required but could not be run" if self.o.word_required else None

    # ── report ──
    def finish(self, final) -> None:
        """Record what happened to each plan, and how far the delivered PDF is proven."""
        from ..core.content_ledger import build_content_ledger
        from ..qa.content_preservation import check_preservation, same_extracted_words
        r = self.c.report
        delivered = r.strategy
        for res in r.candidates:
            plan = self.plans.get(res.name)
            if plan is None:
                continue
            status = self.statuses.get(res.name) or ("accepted" if res.name == delivered else "rejected")
            r.media_decisions.append({**plan.to_dict(), "status": status, "reason": res.rejected})
        report = check_preservation(self.ledger, candidate=build_content_ledger(final.doc, self.assets, final.theme),
                                    pdf=final.pdf)
        status = report.status
        if status == "unknown" and same_extracted_words(self.base_pdf, final.pdf):
            status = "matches_baseline"
        r.validation_by_format["pdf"] = status
        if status == "failed":
            r.status = "failed"
            r.reasons.append("delivered PDF does not preserve the source: " + "; ".join(
                d for x in report.layers for d in x.details[:1]))
        if self.bands["status"] == "band_content_unfit":
            r.status = "failed"
            r.fallback_reason = "band_content_unfit"
            r.reasons.append("band text cannot be set whole: " + "; ".join(self.bands["losses"][:3]))
        elif self.bands["status"] == "reflowed" and delivered not in self.plans:
            r.status = "failed"
            r.fallback_reason = r.fallback_reason or "bands_not_applied"
            r.reasons.append("the designed bands cut text and no lossless layout could be delivered")


def _pages(pdf: bytes) -> int:
    from ..qa.pdf_backend import open_pdf
    with open_pdf(pdf) as doc:
        return len(doc)
