"""
Document-level art direction: a plan for the whole document before anything is drawn.

``read_brief`` reads what the document is. ``select_directions`` picks the directions that
suit it and says why. ``direct`` turns one direction into a design: cover, section
treatments, figures, tables and page bands. Every step is presentation only. Text and
numbers are never written, images are never invented, and anything the author set
explicitly stays as it is.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field, replace as _replace
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from ..core.content_ledger import build_content_ledger
from ..core.table_types import read_cell
from ..core.normalize import SemanticDocument, is_rtl_text
from ..fonts.manager import covering_face
from ..schema.blocks import (CoverPageBlock, FigureCell, FigureMatrixBlock, HeadingBlock, ImageBlock, ImageTextPanelBlock,
                             LedgerRow, LedgerSection, PairedRow, PairedRowColumnsBlock, ParallelLedgerBlock,
                             PerformanceFigure, PerformancePageBlock,
                             SectionOpenerBlock)
from ..schema.media import ImageTreatment, MediaPlacement
from ..schema.theme import Theme
from . import BrandKit, DesignPlan, apply_brand, apply_plan, apply_recipe, compile_tokens, plan_design
from .archetypes import ink as dark_ink
from .archetypes import mix
from .directions import DIRECTIONS, Direction, page_system, palette
from .focal import focal_point

_SUMMARY = re.compile(r"summary|highlight|overview|letter|foreword|recommendation|at a glance|in brief|in numbers"
                      r"|كلمة|ملخص|أبرز|رسالت", re.I)
_APPENDIX = re.compile(r"appendix|annex|notes? to|references|bibliography|ملحق|إيضاحات|المراجع", re.I)
_PURPOSES = (
    ("financial_statements", re.compile(r"statement|interim|accounts|القوائم|fund\b|صندوق", re.I)),
    ("annual_report", re.compile(r"annual|yearbook|التقرير السنوي|البيان السنوي", re.I)),
    ("board_paper", re.compile(r"decision paper|board|committee", re.I)),
    ("sustainability", re.compile(r"sustainab|esg|climate|الاستدامة", re.I)),
    ("impact", re.compile(r"impact", re.I)),
    ("policy", re.compile(r"policy|brief\b", re.I)),
    ("proposal", re.compile(r"proposal|tender|bid\b", re.I)),
    ("manual", re.compile(r"manual|installation|handbook|guide\b", re.I)),
)
_PROFILE_PURPOSE = {"academic_report": "research", "technical_manual": "manual", "proposal": "proposal",
                    "corporate_memo": "memo", "data_report": "report", "executive_report": "report"}
_AUDIENCE = {"financial_statements": "investors and auditors", "annual_report": "stakeholders and the public",
             "board_paper": "directors", "sustainability": "stakeholders and assurers", "impact": "supporters and funders",
             "policy": "policy makers", "proposal": "funders or clients", "manual": "technicians",
             "research": "researchers", "memo": "colleagues", "report": "general professional readers"}
# How well each direction suits each purpose, before the document's own content is counted.
_FIT: Dict[str, Dict[str, float]] = {
    "financial_statements": {"financial_data": 3, "corporate_conservative": 2, "executive_premium": 1},
    "annual_report": {"executive_premium": 3, "editorial_modern": 2, "corporate_conservative": 1.5, "financial_data": 1},
    "board_paper": {"corporate_conservative": 3, "financial_data": 2, "executive_premium": 1.5},
    "sustainability": {"editorial_modern": 2.5, "executive_premium": 2, "financial_data": 2},
    "impact": {"editorial_modern": 3, "executive_premium": 2, "corporate_conservative": 0.5},
    "policy": {"corporate_conservative": 2.5, "financial_data": 2, "editorial_modern": 1.5},
    "proposal": {"editorial_modern": 3, "executive_premium": 2.5, "corporate_conservative": 1},
    "manual": {"corporate_conservative": 3, "financial_data": 2, "editorial_modern": 0.5},
    "research": {"corporate_conservative": 3, "editorial_modern": 1, "financial_data": 1},
    "memo": {"corporate_conservative": 3, "financial_data": 1.5},
    "report": {"corporate_conservative": 2, "executive_premium": 2, "editorial_modern": 2, "financial_data": 2},
}
MAX_CHAPTERS = 8
MAX_PANELS = 2
MIN_PANEL_GAP = 6              # blocks between panels, so a composition stays an event
PANEL_WORDS = 60
OVERLAY_DIRECTIONS = ("editorial_modern", "executive_premium")
_MARKUP = re.compile(r"[*<\[`]")
_FIGURE = re.compile(r"[-+(]?[\d٠-٩][\d٠-٩.,٫٬ ]*[)%٪]?|[—–-]")
MIN_CONTENTS_PAGES = 6


class SectionBrief(BaseModel):
    title: str
    role: str                                     # summary | narrative | data | image | appendix
    words: int
    tables: int = 0
    charts: int = 0
    metrics: int = 0
    photos: int = 0
    quotes: int = 0


class DocumentBrief(BaseModel):
    purpose: str
    audience: str
    profile: str
    language: str                                 # rtl | ltr | bilingual
    words: int
    density: str                                  # sparse | normal | dense
    estimated_pages: float
    sections: List[SectionBrief] = Field(default_factory=list)
    tables: int = 0
    charts: int = 0
    metrics: int = 0
    photos: int = 0
    quotes: int = 0
    author_cover: bool = False
    author_bands: bool = False


class SectionTreatment(BaseModel):
    section: str
    role: str
    opener: str
    composition: str
    reasons: List[str] = Field(default_factory=list)


class ArtDirectionPlan(BaseModel):
    """What a design will do to the document, and why."""

    direction: str
    name: str
    summary: str
    brief: DocumentBrief
    fit_reasons: List[str] = Field(default_factory=list)
    cover: str = ""
    sections: List[SectionTreatment] = Field(default_factory=list)
    bands: str = ""
    typography: str = ""
    decisions: List[str] = Field(default_factory=list)
    refinements: List[str] = Field(default_factory=list)

    def rhythm(self) -> List[str]:
        return [f"{s.opener}/{s.composition}" for s in self.sections]

    def explain(self) -> dict:
        return self.model_dump()


@dataclass
class Adjust:
    """What the refinement step may change between renders."""

    density: float = 1.0
    openers: bool = True           # section opening pages and page-long statements
    hero_page: bool = True
    side_images: bool = True
    statement_pages: bool = True
    major_breaks: bool = True
    exhibits: float = 1.0          # image bands and charts, as a share of their planned height
    no_break: frozenset = field(default_factory=frozenset)   # sections that follow on instead of opening a page


@dataclass
class Directed:
    plan: ArtDirectionPlan
    document: object
    theme: Theme
    design: DesignPlan


# ───────────────────────────── reading the document ─────────────────────────────

def _words(text: Optional[str]) -> int:
    return len((text or "").split())


def _sections(blocks) -> List[Tuple[Optional[int], list]]:
    """(index of the H1, indices of what follows it), in document order."""
    out: List[Tuple[Optional[int], list]] = []
    current: list = []
    head: Optional[int] = None
    for i, b in enumerate(blocks):
        if b.type == "heading" and b.level == 1:
            if head is not None or current:
                out.append((head, current))
            head, current = i, []
        elif b.type not in ("cover_page", "table_of_contents", "toc", "watermark"):
            current.append(i)
    if head is not None or current:
        out.append((head, current))
    return out


def role_of(block) -> str:
    intent = getattr(block, "intent", None)
    return intent.role if intent else "unknown"


def _is_photo(block) -> bool:
    return block.type == "image" and role_of(block) == "photo"


def _brief_section(title: str, blocks) -> SectionBrief:
    count = Counter(b.type for b in blocks)
    words = sum(_words(getattr(b, "text", None)) for b in blocks)
    photos = sum(1 for b in blocks if _is_photo(b))
    s = SectionBrief(title=title, role="narrative", words=words, tables=count["table"], charts=count["chart"],
                     metrics=count["metric_row"], photos=photos, quotes=count["quote"])
    exhibits = s.tables + s.charts + s.metrics
    if _APPENDIX.search(title):
        s.role = "appendix"
    elif _SUMMARY.search(title) and words < 220:
        s.role = "summary"
    elif exhibits and words < 90 * (exhibits + 1):
        s.role = "data"
    elif photos:
        s.role = "image"
    return s


def read_brief(sem: SemanticDocument, profile: str, estimated_pages: float) -> DocumentBrief:
    blocks = sem.blocks
    title = sem.meta.title or ""
    sections = [_brief_section(blocks[h].text if h is not None else "", [blocks[i] for i in idx])
                for h, idx in _sections(blocks)]
    purpose = next((p for p, rx in _PURPOSES if rx.search(title)), None)
    purpose = purpose or _PROFILE_PURPOSE.get(profile, "report")
    words = sum(s.words for s in sections)
    tables, charts = sum(s.tables for s in sections), sum(s.charts for s in sections)
    metrics, photos = sum(s.metrics for s in sections), sum(s.photos for s in sections)
    exhibits = tables + charts + metrics
    density = "dense" if exhibits * 90 > words else "sparse" if words < 350 and not exhibits else "normal"
    language = "rtl" if sem.direction == "rtl" else "bilingual" if sem.stats.bilingual else "ltr"
    return DocumentBrief(purpose=purpose, audience=_AUDIENCE.get(purpose, _AUDIENCE["report"]), profile=profile,
                         language=language, words=words, density=density, estimated_pages=round(estimated_pages, 1),
                         sections=sections, tables=tables, charts=charts, metrics=metrics, photos=photos,
                         quotes=sum(s.quotes for s in sections), author_cover=sem.stats.has_cover,
                         author_bands=sem.meta.page_system is not None)


def select_directions(brief: DocumentBrief, n: int = 3) -> List[Tuple[Direction, float, List[str]]]:
    """Directions ranked for this document, each with the reasons that placed it."""
    ranked = []
    for d in DIRECTIONS.values():
        score = _FIT.get(brief.purpose, _FIT["report"]).get(d.id, 0.3)
        why = [f"{brief.purpose.replace('_', ' ')} for {brief.audience}: base fit {score:g}"]
        if d.id == "arabic_institutional":
            if brief.language == "ltr":
                continue
            score += 3.5
            why.append("written in Arabic or in two languages")
        if d.id == "financial_data" and brief.tables >= 2:
            score += 0.4 * min(brief.tables, 4)
            why.append(f"{brief.tables} tables need exact, dense setting")
        if d.id in ("editorial_modern", "executive_premium") and brief.photos:
            score += 0.4 * min(brief.photos, 3)
            why.append(f"{brief.photos} photographs can carry the composition")
        if d.id == "executive_premium" and brief.estimated_pages < 3:
            score -= 1.5
            why.append("too short for opening pages")
        if d.id == "editorial_modern" and brief.density == "dense":
            score -= 1.0
            why.append("dense exhibits suit a narrow column less well")
        if d.id == "editorial_modern" and brief.language == "rtl":
            score -= 0.5
        ranked.append((d, round(score, 2), why))
    ranked.sort(key=lambda r: (-r[1], r[0].id))
    return ranked[:max(1, n)]


# ───────────────────────────── applying a direction ─────────────────────────────

def _hint(block, **values) -> None:
    block.hints = {**(block.hints or {}), **values}


def _major(s: SectionBrief) -> bool:
    return s.words >= 150 or s.photos > 0 or s.tables + s.charts >= 2


def _first_photo(blocks) -> Optional[ImageBlock]:
    photos = [b for b in blocks if _is_photo(b) and (b.intent is None or b.intent.crop_allowed)]
    hero = [b for b in photos if b.intent and b.intent.prominence == "hero"]
    return (hero or photos or [None])[0]


def _cover(sem, d: Direction, brief: DocumentBrief, primary: str, accent: str, logo: Optional[str],
           plan: ArtDirectionPlan) -> None:
    """Dress a cover built from metadata. A cover the author wrote is left alone."""
    if brief.author_cover:
        plan.cover = "the author's own cover"
        plan.decisions.append("cover: kept the author's cover page unchanged")
        return
    if not sem.meta.title:
        plan.cover = "none"
        plan.decisions.append("cover: no title in the metadata, so none was built")
        return
    if sem.blocks and sem.blocks[0].type == "cover_page":
        sem.blocks.pop(0)
    short = brief.estimated_pages < 3
    kind = "masthead" if short else d.cover
    if kind == "masthead" and _opens_with_title(sem):
        plan.cover = "none"
        plan.decisions.append("cover: the document opens with its own title, so no masthead repeats it")
        return
    photo = _first_photo(sem.blocks)
    if kind in ("image_top", "split") and photo is None:
        kind = "type_left" if kind == "image_top" else "colour_panel"
    c = CoverPageBlock(title=sem.meta.title, subtitle=sem.meta.subject or sem.meta.description,
                       author=sem.meta.author)
    if kind == "masthead":
        c.background_color, c.layout = primary, "left_aligned"
        c.hints = {"masthead": True, "title_scale": 2.3 if d.base_size >= 10 else 2.7}
        if d.id == "editorial_modern":
            c.background_color = accent
    elif kind == "type_centered":
        c.layout = "centered"
        c.logo = logo
        c.hints = {"title_scale": 1.45, "rule": accent, "drop": 0.3}
    elif kind == "type_left":
        c.layout, c.logo = "left_aligned", logo
        c.hints = {"title_scale": 1.5, "rule": accent, "drop": 0.52}
    elif kind == "image_top":
        c.layout, c.background_image = "left_aligned", photo.src
        c.background_treatment = _cover_crop(photo.src)
        c.hints = {"image_top": d.extras.get("cover_image_top", 0.6), "title_scale": d.extras.get("cover_title_scale", 1.0)}
        if d.extras.get("cover_panel"):           # the page behind the title becomes a colour panel
            c.background_color, c.text_color = primary, "#FFFFFF"
        if d.extras.get("cover_centred"):
            c.layout = "centered"
    elif kind == "split":
        c.layout, c.background_image, c.logo = "split", photo.src, logo
        c.background_treatment = _cover_crop(photo.src)
        c.hints = {"title_scale": 1.25, "rule": accent, "drop": 0.34}
    elif kind == "colour_panel":
        c.layout, c.background_color, c.text_color = "left_aligned", primary, "#FFFFFF"
        c.hints = {"title_scale": d.extras.get("cover_title_scale", 1.3), "rule": accent,
                   "drop": d.extras.get("cover_title_drop", 0.42)}
    else:                                       # "full": the darkest, quietest cover
        c.layout, c.background_color, c.text_color = "left_aligned", primary, "#FFFFFF"
        if photo is not None:
            c.background_image = photo.src
            c.background_treatment = _cover_crop(photo.src)
            c.overlay_color, c.overlay_opacity = primary, 0.62
        c.hints = {"title_scale": 1.15, "rule": accent, "drop": 0.56}
    sem.blocks.insert(0, c)
    plan.cover = kind
    plan.decisions.append(f"cover: {kind}" + (f", using the document's own photo {photo.src!r}"
                                              if c.background_image else ", type only"))
    if short and d.cover != "masthead":
        plan.decisions.append(f"cover: about {brief.estimated_pages} pages is too short for a cover page, "
                              "so the title opens page one")


def _opens_with_title(sem) -> bool:
    """The first block the reader meets is a top-level heading that says the document's title."""
    from ..core.inline import plain_text
    first = next((b for b in sem.blocks if b.type not in ("table_of_contents", "watermark", "page_media",
                                                          "page_section")), None)
    return (first is not None and first.type == "heading" and first.level == 1
            and " ".join(plain_text(first.text).split()).casefold()
            == " ".join((sem.meta.title or "").split()).casefold())


def _cover_crop(src) -> ImageTreatment:
    """Fill the box, cropping around the subject of the picture rather than its middle."""
    fx, fy = focal_point(src)
    return ImageTreatment(fit="cover", focal_x=fx, focal_y=fy)


def _photo(b: ImageBlock, d: Direction, section: SectionBrief, side: str, adjust: Adjust,
           room_after: int, plan: ArtDirectionPlan, compact: bool = False) -> str:
    """Place one photograph. Only photographs that allow it are cropped."""
    if b.placement or b.treatment or b.width or b.height:
        plan.decisions.append(f"image {b.src!r}: the author's size or placement kept")
        return "author image"
    crop = bool(b.intent and b.intent.crop_allowed)
    hero = bool(b.intent and b.intent.prominence == "hero") or d.side_image == 0.0
    if not hero and d.side_image and adjust.side_images and room_after >= 2:
        b.placement = MediaPlacement(mode="floating", horizontal=side, width_ratio=d.side_image)
        return f"float {side}"
    if compact and crop:                          # following on: a band that fits under what came before
        b.placement = MediaPlacement(width_ratio=1.0, height_ratio=0.28 * adjust.exhibits,
                                     bleed=d.hero_image == "bleed")
        b.treatment = _cover_crop(b.src)
        return "image band, following on"
    if d.hero_image == "bleed":
        b.placement = MediaPlacement(width_ratio=1.0, bleed=True)
        return "bleed image"
    if d.hero_image == "band" and crop:
        b.placement = MediaPlacement(width_ratio=1.0, height_ratio=0.34 * adjust.exhibits)
        b.treatment = _cover_crop(b.src)
        return "image band"
    b.placement = MediaPlacement(width_ratio=(0.82 if d.id == "corporate_conservative" else 1.0) * adjust.exhibits)
    return "column image"


def _chart(b, d: Direction, primary: str, muted: str, adjust: Adjust) -> None:
    b.height = b.height * adjust.exhibits
    if b.colors:
        return
    data = b.data if isinstance(b.data, dict) else {}
    periods = data and all(read_cell(str(k)).kind in ("year", "period") for k in data)
    if b.chart_type in ("bar", "column") and periods and len(data) > 1:
        b.colors = [muted] * (len(data) - 1) + [primary]     # the current period carries the tone
    else:
        b.colors = [primary]
    if d.id == "financial_data":
        b.height = min(b.height, 2.7 * adjust.exhibits)
    elif d.id in ("editorial_modern", "executive_premium"):
        b.height = min(b.height, 3.3 * adjust.exhibits)


def _table(b, d: Direction) -> None:
    hints = b.hints or {}
    if "style" in b.model_fields_set and b.style != "striped":
        return
    if d.table != "default" and not b.header_bg:
        hints = {**hints, "design": d.table}
        # the tint marks the latest period when periods run across the columns; a column of
        # years down the side is a label, not a period of figures
        if d.table == "ledger" and hints.get("current_period_col") is not None:
            hints["current_col"] = hints["current_period_col"]
    b.hints = hints


def _opener_block(heading, chapters: List[str], current: int, blocks, follow: List[int], d: Direction):
    """A section opening page. A short first paragraph moves in as the standfirst: same
    words, same order."""
    standfirst = None
    first = follow[0] if follow else None
    if first is not None and blocks[first].type == "paragraph" and _words(blocks[first].text) <= 44:
        standfirst = blocks[first].text
    block = SectionOpenerBlock(title=heading.text, standfirst=standfirst, chapters=chapters, current=current)
    block.id = heading.id
    return block, first if standfirst else None


def _performance(blocks, follow: List[int], heading) -> Optional[Tuple[PerformancePageBlock, List[int]]]:
    """A row of figures given a page, under the section's own title. Nothing is added."""
    rows = [i for i in follow if blocks[i].type == "metric_row"]
    if len(rows) != 1 or len(blocks[rows[0]].metrics) < 3:
        return None
    m = blocks[rows[0]].metrics
    hero = PerformanceFigure(value=m[0].value, label=m[0].label, delta=m[0].delta)
    tiles = [PerformanceFigure(value=x.value, label=x.label, delta=x.delta) for x in m[1:]]
    intro = [i for i in follow if i < rows[0]]
    standfirst = None
    used = [rows[0]]
    if len(intro) == 1 and blocks[intro[0]].type == "paragraph" and _words(blocks[intro[0]].text) <= 44:
        standfirst = blocks[intro[0]].text
        used.append(intro[0])
    elif intro:
        return None
    page = PerformancePageBlock(title=heading.text, standfirst=standfirst, hero=hero, tiles=tiles)
    page.id = heading.id
    return page, used


def _apply_sections(sem, d: Direction, brief: DocumentBrief, primary: str, accent: str, muted: str,
                    adjust: Adjust, plan: ArtDirectionPlan, rtl: bool) -> None:
    blocks = sem.blocks
    secs = [(h, idx) for h, idx in _sections(blocks) if h is not None]
    titles = [blocks[h].text for h, _ in secs]
    briefs = {t.title: t for t in brief.sections}
    pages_enough = brief.estimated_pages >= 5 and len(secs) <= MAX_CHAPTERS
    replace: Dict[int, object] = {}
    remove: set = set()
    previous = None
    side_flip = False
    for number, (h, idx) in enumerate(secs):
        heading = blocks[h]
        s = briefs.get(heading.text) or _brief_section(heading.text, [blocks[i] for i in idx])
        why: List[str] = []
        major = _major(s)
        opener = d.opener
        composition = s.role
        if number == 0 and plan.cover == "masthead" and opener == "slab":
            opener = "rule"                       # two bands in a row would fight
            why.append("under the masthead: a rule, not a second band")
            _hint(heading, opener="rule", rule=accent, rule_width=1.2, weight="regular")
        if s.role == "appendix":
            opener = "quiet"
            if brief.estimated_pages >= 5 and adjust.major_breaks:
                _hint(heading, break_before="if_not_empty")
            if d.opener != "none":
                _hint(heading, scale=0.72)
            why.append("appendix: set down a level so the main sections lead")
        elif d.kpi == "hero_page" and adjust.hero_page and s.metrics == 1 and pages_enough:
            made = _performance(blocks, idx, heading)
            if made:
                replace[h], used = made
                remove.update(used)
                opener, composition = "performance page", "figures"
                why.append("one row of figures: given a page of its own, largest first")
        if s.role != "appendix" and h not in replace:
            if opener == "rule":
                pass
            elif opener == "page":
                if (adjust.openers and pages_enough and major and previous != "page"
                        and heading.text not in adjust.no_break):
                    block, moved = _opener_block(heading, titles, number, blocks, idx, d)
                    replace[h] = block
                    if moved is not None:
                        remove.add(moved)
                    why.append("large section: opens on its own page; chapters listed in the strip")
                else:
                    opener = "rule"
                    _hint(heading, opener="rule", rule=accent, rule_width=1.2, weight="regular")
                    if adjust.major_breaks and major and pages_enough:
                        _hint(heading, break_before="if_not_empty")
                    why.append("after an opening page, or short: a rule keeps the rhythm from repeating")
            elif opener == "hang":
                _hint(heading, opener="hang", hang=d.hang, rule=primary, rule_width=0.8)
                if adjust.major_breaks and major and brief.estimated_pages >= 4 and number:
                    if s.role in ("image", "narrative"):
                        _hint(heading, drop=0.09 if not s.photos else 0.0, break_before="if_not_empty")
                    why.append("large section opens a page, with room left above it")
            elif opener == "slab":
                bleed = d.id == "arabic_institutional"
                _hint(heading, opener="slab", fill=primary, bleed=bleed)
                if adjust.major_breaks and d.break_major and major and brief.estimated_pages >= 4 and number:
                    _hint(heading, break_before="if_not_empty")
        if heading.text in adjust.no_break:
            for key in ("break_before", "drop"):
                (heading.hints or {}).pop(key, None)
        previous = opener
        side = "end" if not (d.side_alternates and side_flip) else "start"
        lead_done = not d.lead or s.role in ("data", "appendix")
        for pos, i in enumerate(idx):
            b = blocks[i]
            if i in remove:
                continue
            if b.type == "paragraph" and not lead_done:
                lead_done = True
                if not (b.hints or {}).get("flow_run") and _words(b.text) <= 70:
                    _hint(b, lead=True)
            elif b.type == "image" and _is_photo(b):
                room = sum(1 for j in idx[pos + 1:] if blocks[j].type == "paragraph")
                composition = f"{composition}: {_photo(b, d, s, side, adjust, room, plan, heading.text in adjust.no_break)}"
                side_flip = not side_flip
                side = "end" if not (d.side_alternates and side_flip) else "start"
            elif b.type == "chart":
                _chart(b, d, primary, mix(primary, "#FFFFFF", 0.62), adjust)
            elif b.type == "figure_matrix":
                for cell in b.figures:
                    if cell.chart is not None:
                        _chart(cell.chart, d, primary, mix(primary, "#FFFFFF", 0.62), adjust)
            elif b.type == "table":
                _table(b, d)
            elif b.type == "metric_row" and d.kpi in ("ruled", "band"):
                _hint(b, style=d.kpi)
            elif b.type == "metric_row" and d.kpi == "hero_page":
                _hint(b, style="ruled")
            elif b.type == "quote" and b.style == "blockquote" and d.statement != "plain":
                last = not any(blocks[j].type == "paragraph" for j in idx[pos + 1:])
                page = (d.statement == "page" and adjust.statement_pages and adjust.openers and pages_enough and
                        last and _words(b.text) <= 24)
                _hint(b, statement="page" if page else "inline")
                if page:
                    why.append("a short sentence closes the section: given the whole page")
        plan.sections.append(SectionTreatment(section=heading.text, role=s.role, opener=opener,
                                              composition=composition, reasons=why))
    if d.extras.get("closing_band") and secs:
        _closing_band(blocks, secs[-1][1], remove, d, plan)
    sem.blocks = [replace.get(i, b) for i, b in enumerate(blocks) if i not in remove]


def _plain_text(text: str) -> bool:
    return not _MARKUP.search(text or "")


def _pair(a, b) -> bool:
    """Two paragraphs that say one thing in two languages."""
    return (a.type == b.type == "paragraph" and is_rtl_text(a.text) != is_rtl_text(b.text)
            and _plain_text(a.text) and _plain_text(b.text))


def _ledger(b) -> Optional[ParallelLedgerBlock]:
    """A table labelled in a language at each edge, with only figures between. The labels must
    already be there: this moves them, and writes none."""
    h = b.headers
    if (b.type != "table" or not b.caption or b.table_number or not 3 <= len(h) <= 6
            or is_rtl_text(h[0]) == is_rtl_text(h[-1])):
        return None
    rows = [*b.rows, *([b.footer_row] if b.footer_row else [])]
    if len(rows) < 2 or any(len(r) != len(h) for r in rows):
        return None
    if any(not _FIGURE.fullmatch(c.strip()) for r in rows for c in r[1:-1]):
        return None
    last = len(b.rows)
    lines = [LedgerRow(label=r[0], label_alt=r[-1], values=r[1:-1], total=i >= last) for i, r in enumerate(rows)]
    return ParallelLedgerBlock(periods=h[1:-1], label_header=h[0], label_header_alt=h[-1], title_first=True,
                               sections=[LedgerSection(title=b.caption, rows=lines)])


def _matrix(charts, adjust: Adjust) -> FigureMatrixBlock:
    columns = 3 if len(charts) % 3 == 0 else 2
    return FigureMatrixBlock(figures=[FigureCell(chart=c) for c in charts], columns=columns,
                             cell_height=(104.0 if columns == 3 else 128.0) * adjust.exhibits)


def _panel(b, text: str, d: Direction, count: int, primary: str, rtl: bool) -> ImageTextPanelBlock:
    """Overlay keeps the panel off the picture's subject; a split alternates down the document."""
    overlay = d.id in OVERLAY_DIRECTIONS
    if overlay:
        left = focal_point(b.src)[0] >= 0.5
        side = "start" if left != rtl else "end"
    else:
        side = "start" if count % 2 == 0 else "end"
    return ImageTextPanelBlock(image=b, paragraphs=[text], layout="overlay" if overlay else "split", side=side,
                               panel_color=primary, tone="dark")


def _compose(sem, d: Direction, primary: str, adjust: Adjust, plan: ArtDirectionPlan, rtl: bool) -> None:
    """Grammar compositions, where the document already has the structure each one needs."""
    e = d.extras
    if not any(e.get(k) for k in ("image_panel", "chart_matrix", "paired_columns", "ledger_tables")):
        return
    blocks, out, i = sem.blocks, [], 0
    panels, since_panel, appendix = 0, MIN_PANEL_GAP, False
    while i < len(blocks):
        b = blocks[i]
        since_panel += 1
        if b.type == "heading" and b.level == 1:
            appendix = bool(_APPENDIX.search(b.text))
        if e.get("chart_matrix") and b.type == "chart":
            j = i
            while j < len(blocks) and blocks[j].type == "chart" and blocks[j].chart_type == b.chart_type:
                j += 1
            if j - i >= 2:
                out.append(_matrix(blocks[i:j], adjust))
                plan.decisions.append(f"matrix: {j - i} charts of one kind in equal cells")
                i = j
                continue
        if e.get("paired_columns") and i + 1 < len(blocks) and _pair(b, blocks[i + 1]):
            j = i
            rows = []
            while j + 1 < len(blocks) and _pair(blocks[j], blocks[j + 1]):
                rows.append(PairedRow(first=blocks[j].text, second=blocks[j + 1].text))
                j += 2
            out.append(PairedRowColumnsBlock(rows=rows))
            plan.decisions.append(f"paired columns: {len(rows)} paragraphs in two languages, row by row")
            i = j
            continue
        if e.get("ledger_tables") and b.type == "table":
            made = _ledger(b)
            if made:
                out.append(made)
                plan.decisions.append("ledger: figures once, labelled from each language's edge")
                i += 1
                continue
        if (e.get("image_panel") and _is_photo(b) and not appendix and panels < MAX_PANELS
                and since_panel >= MIN_PANEL_GAP and i + 1 < len(blocks) and blocks[i + 1].type == "paragraph"
                and 12 <= _words(blocks[i + 1].text) <= PANEL_WORDS and _plain_text(blocks[i + 1].text)):
            out.append(_panel(b, blocks[i + 1].text, d, panels, primary, rtl))
            plan.decisions.append("panel: a photograph and the short text after it set as one composition")
            panels += 1
            since_panel = 0
            i += 2
            continue
        out.append(b)
        i += 1
    sem.blocks = out


def _closing_band(blocks, last: List[int], remove: set, d: Direction, plan: ArtDirectionPlan) -> None:
    """A last photograph that may be cropped becomes a band across the page, where it falls."""
    kept = [i for i in last if i not in remove]
    b = blocks[kept[-1]] if kept else None
    if b is None or b.type != "image" or not _is_photo(b) or not (b.intent and b.intent.crop_allowed):
        return
    if b.width or b.height:
        return
    b.placement = MediaPlacement(width_ratio=1.0, height_ratio=d.extras["closing_band"], bleed=True)
    b.treatment = _cover_crop(b.src)
    plan.decisions.append(f"image {b.src!r}: closes the document as a band across the page")


HANG_EDGE = 28.0               # a hanging heading keeps at least this far from the paper edge


def _fit_hang(d: Direction, theme: Theme, rtl: bool, plan: ArtDirectionPlan) -> Direction:
    """Headings hang into the start margin, so they may hang no further than that margin allows.
    The reviewed standard can narrow a direction's margin after the direction chose its hang."""
    if not d.hang:
        return d
    sp = theme.spacing
    start = sp.page_margin_right if rtl else sp.page_margin_left
    room = max(0.0, round(start - HANG_EDGE, 1))
    if d.hang <= room:
        return d
    plan.decisions.append(f"headings: hang {d.hang:g}pt reduced to {room:g}pt to fit the "
                          f"{start:g}pt start margin")
    return _replace(d, hang=room)


def _arabic_chars(sem) -> str:
    """Characters of this document that the Arabic face has to draw."""
    text = str(sem.meta.model_dump()) + "".join(str(b.model_dump()) for b in sem.blocks)
    return "".join(sorted({c for c in text if "؀" <= c <= "ۿ" or c in "%¹²³"}))


def direct(sem: SemanticDocument, direction: Direction, *, brand: Optional[BrandKit] = None,
           base_theme: Optional[Theme] = None, adjust: Optional[Adjust] = None,
           fit_reasons: Optional[List[str]] = None) -> Directed:
    """One complete design of ``sem``. The source is not changed."""
    from .planner import plan_layout
    adjust = adjust or Adjust()
    d = direction
    base = plan_design(sem, None, brand, base_theme=base_theme)
    rtl = sem.direction == "rtl"
    recipe = d.recipe(base.decision.profile, rtl, adjust.density)
    theme = apply_recipe(recipe, base_theme)
    notes = apply_brand(theme, brand) if brand else []
    primary, accent = palette(d, brand.primary if brand else None, brand.accent if brand else None)
    theme.colors.primary = primary
    theme.colors.accent = accent
    theme.decorations.heading_accent_bar = False
    theme.decorations.table_row_alternating = d.table == "default"
    if rtl or sem.stats.bilingual:
        if theme.typography.arabic_family in (None, "Amiri"):
            theme.typography.arabic_family = covering_face(d.arabic_family, _arabic_chars(sem))
    from .reviewed_quality import DIRECTION_PALETTE, apply_reviewed_quality
    script = "bilingual" if sem.stats.bilingual else sem.direction
    notes += apply_reviewed_quality(theme, script=script,
                                    palette=DIRECTION_PALETTE[d.id], preserve_brand=bool(brand))
    primary, accent = theme.colors.primary, theme.colors.accent
    tokens = compile_tokens(theme)
    design = DesignPlan(decision=base.decision, recipe=recipe, theme=theme, tokens=tokens,
                        section_numbering=recipe.section_numbering or sem.meta.section_numbering, notes=notes)
    out = apply_plan(sem, design)
    design.layout = plan_layout(out, design)
    estimated = float(getattr(design.layout, "estimated_pages", 1) or 1)
    brief = read_brief(sem, base.decision.profile.value, estimated)
    plan = ArtDirectionPlan(direction=d.id, name=d.name, summary=d.summary, brief=brief, fit_reasons=fit_reasons or [],
                            typography=f"{theme.typography.heading_family} headings, {theme.typography.body_family} "
                                       f"{theme.typography.base_size:g}/{theme.typography.line_height:g}",
                            bands=d.bands)
    plan.decisions += notes
    primary = dark_ink(theme)
    muted = theme.colors.text_secondary
    logo = brand.logo if brand else None
    if brief.estimated_pages < MIN_CONTENTS_PAGES and not any(b.type == "table_of_contents" for b in sem.blocks):
        out.blocks = [b for b in out.blocks if b.type != "table_of_contents"]
        plan.decisions.append(f"contents: about {brief.estimated_pages} pages needs no contents page")
    _cover(out, d, brief, primary, accent, logo, plan)
    _compose(out, d, primary, adjust, plan, rtl)
    d = _fit_hang(d, theme, rtl, plan)
    _apply_sections(out, d, brief, primary, accent, muted, adjust, plan, rtl)
    if brief.author_bands:
        plan.bands = "the author's own page system"
        plan.decisions.append("bands: kept the author's page system")
    else:
        out.meta.page_system = page_system(d, company=brand.name if brand else None, logo=logo, primary=primary,
                                           accent=accent, muted=muted, rtl=rtl, has_title=bool(sem.meta.title))
    return Directed(plan=plan, document=out.to_document(), theme=theme, design=design)


# ───────────────────────────── what a design may not change ─────────────────────────────

def content_changes(source_doc, directed_doc, theme: Theme, brand_assets=()) -> List[str]:
    """How the designed document's words, numbers and assets depart from the source.

    Words must all survive, once each and in order. A design may add the title block
    from metadata and the chapter list on an opening page, both of which repeat what the
    author wrote; anything else it adds is a failure.
    """
    from ..core.normalize import normalize
    from ..policy import AssetPolicy
    assets = AssetPolicy()
    src = build_content_ledger(source_doc, assets, theme)
    new = build_content_ledger(directed_doc, assets, theme)
    have, got = Counter(src.strings()), Counter(new.strings())
    out = [f"lost: {t[:70]!r}" for t in (have - got)]
    meta = normalize(source_doc).meta
    allowed = {t for t in (meta.title, meta.subject, meta.description, meta.author) if t}
    allowed |= set(src.strings())
    out += [f"added: {t[:70]!r}" for t in (got - have) if t not in allowed]
    # sentences must keep their order; a figure's label and value may swap inside a tile,
    # and an opening page lists later chapters, so neither counts here
    prose = [t for t in src.strings() if len(t.split()) >= 6]
    order = iter(e.text for e in new.entries if not e.kind.startswith("chapters"))
    if not all(any(t == x for x in order) for t in prose):
        out.append("reordered: the author's text no longer reads in the same order")
    known = {sha for _, sha in src.assets}
    brand_marks = set(brand_assets)
    out += [f"asset not in the source: {where}" for where, sha in new.assets
            if sha not in known and not any(m in where for m in brand_marks)]
    lost_assets = known - {sha for _, sha in new.assets}
    out += [f"asset lost: {sha[:12]}" for sha in lost_assets]
    return out


__all__ = ["Adjust", "ArtDirectionPlan", "Directed", "DocumentBrief", "SectionBrief", "SectionTreatment",
           "content_changes", "direct", "read_brief", "select_directions", "is_rtl_text"]
