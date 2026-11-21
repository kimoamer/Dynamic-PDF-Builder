"""
Document profile selection — deterministic, explainable.

A profile captures *what kind of document this is* (executive report,
proposal, academic paper…). It is chosen from explicit metadata first, then
from measurable content signals. Every decision carries human-readable
reasons so ``design_explain()`` can show why a layout was chosen.
"""
from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from ..core.keywords import keywords, pattern
from ..core.normalize import SemanticDocument


class Profile(str, Enum):
    EXECUTIVE_REPORT = "executive_report"
    PROPOSAL = "proposal"
    CORPORATE_MEMO = "corporate_memo"
    ACADEMIC_REPORT = "academic_report"
    TECHNICAL_MANUAL = "technical_manual"
    DATA_REPORT = "data_report"
    FINANCIAL_REPORT = "financial_report"
    LETTER = "letter"
    INVOICE = "invoice"
    GENERAL = "general"


ALIASES = {
    "report": Profile.EXECUTIVE_REPORT, "executive": Profile.EXECUTIVE_REPORT,
    "memo": Profile.CORPORATE_MEMO, "academic": Profile.ACADEMIC_REPORT,
    "paper": Profile.ACADEMIC_REPORT, "manual": Profile.TECHNICAL_MANUAL,
    "technical": Profile.TECHNICAL_MANUAL, "data": Profile.DATA_REPORT,
    "financial": Profile.FINANCIAL_REPORT, "finance": Profile.FINANCIAL_REPORT,
    "rtl_report": Profile.EXECUTIVE_REPORT,
    # the names the kits go by, as an author writes them
    "quote": Profile.INVOICE, "quotation": Profile.INVOICE, "estimate": Profile.INVOICE,
    "statements": Profile.FINANCIAL_REPORT, "feasibility": Profile.FINANCIAL_REPORT,
}


class ProfileDecision(BaseModel):
    profile: Profile
    direction: str
    explicit: bool = False
    reasons: List[str] = Field(default_factory=list)
    scores: Dict[str, float] = Field(default_factory=dict)
    confidence: float = 1.0            # calibrated: share of such decisions that were right
    uncertain: bool = False            # the evidence was split; a balanced general layout is used
    alternatives: List[str] = Field(default_factory=list)   # the closest other types, when uncertain
    audience: Optional[str] = None     # meta.audience and what it was read as, when given


def resolve_profile_name(name: str) -> Profile:
    key = (name or "").strip().lower().replace("-", "_").replace(" ", "_")
    if key in ALIASES:
        return ALIASES[key]
    try:
        return Profile(key)
    except ValueError:
        valid = ", ".join(p.value for p in Profile)
        raise ValueError(f"Unknown document type {name!r}. Valid: {valid}") from None


_KW = tuple(Profile(k) for k in keywords()["profiles"])    # keyword lists: dynamic_pdf/data/keywords.json
UNCERTAIN_BELOW = 0.6           # a confidence under this is reported as uncertain


def _kw_hits(profile: Profile, texts: List[str]) -> int:
    pat = pattern("profiles", profile.value)
    return sum(1 for t in texts if pat.search(t))


def audience_hint(audience: Optional[str]) -> Optional[dict]:
    """What ``meta.audience`` suggests: ``{"name", "purpose", "profile"}`` for the first
    audience group whose words it uses, or None."""
    if not audience:
        return None
    groups = keywords()["audiences"]
    for name in groups["_order"]:
        if pattern("audiences", name).search(audience):
            g = groups[name]
            return {"name": name, "purpose": g["purpose"], "profile": g["profile"]}
    return None


def confidence(best: float, second: float) -> float:
    """How often a decision with this lead was right on the labelled calibration set
    (``tests/data/document_types.json``, split ``calibration``)."""
    table = keywords()["profile_confidence"]
    if best < table["no_signal_below"]:
        return table["no_signal"]
    lead = best - second
    for edge, value in zip(table["lead_edges"], table["values"]):
        if lead < edge:
            return value
    return table["values"][-1]


def select_profile(doc: SemanticDocument, requested: Optional[str] = None) -> ProfileDecision:
    """Pick a profile: explicit request > meta.document_type > content scoring."""
    for source, value in (("design()", requested), ("meta.document_type", doc.meta.document_type)):
        if value and value != "auto":
            prof = resolve_profile_name(value)
            return ProfileDecision(profile=prof, direction=doc.direction, explicit=True,
                                   reasons=[f"{source} requested '{value}'"])

    st = doc.stats
    headings = st.heading_texts
    all_text = doc.all_text()
    head_and_start = headings + all_text[:12]
    scores: Dict[Profile, float] = {p: 0.0 for p in Profile}
    why: Dict[Profile, List[str]] = {p: [] for p in Profile}

    def add(p: Profile, pts: float, reason: str):
        if pts:
            scores[p] += pts
            why[p].append(reason)

    # Academic
    add(Profile.ACADEMIC_REPORT, 3 * st.has_abstract, "structured abstract present")
    add(Profile.ACADEMIC_REPORT, min(3, st.bibliography_entries), f"{st.bibliography_entries} bibliography entries")
    add(Profile.ACADEMIC_REPORT, min(2, st.citations + st.footnotes) * 0.75,
        f"{st.citations} citations / {st.footnotes} footnotes")
    add(Profile.ACADEMIC_REPORT, min(2, st.math), f"{st.math} equations")
    # Technical manual
    add(Profile.TECHNICAL_MANUAL, min(4, st.code_blocks) * 0.9, f"{st.code_blocks} code blocks")
    add(Profile.TECHNICAL_MANUAL, min(2, st.callouts) * 0.5, f"{st.callouts} callouts/admonitions")
    # Data / financial
    add(Profile.DATA_REPORT, min(3, st.charts), f"{st.charts} charts")
    add(Profile.DATA_REPORT, min(3, st.table_rows / 15), f"{st.table_rows} table rows")
    add(Profile.DATA_REPORT, 2 * (st.numeric_ratio > 0.5 and st.tables > 0), "numeric-dense tables")
    # Executive
    add(Profile.EXECUTIVE_REPORT, min(3, st.metrics * 1.5), f"{st.metrics} KPI/metric blocks")
    add(Profile.EXECUTIVE_REPORT, 1.0 * st.has_cover, "cover page")
    # Letter / memo / invoice: short, few headings
    short = st.words < 700 and st.headings <= 2
    add(Profile.LETTER, 2 * (short and st.has_signature), "short document with signature")
    add(Profile.CORPORATE_MEMO, 1 * (short and not st.has_cover), "short, no cover")
    fin_hits = _kw_hits(Profile.FINANCIAL_REPORT, st.table_headers)
    row_hits = _kw_hits(Profile.FINANCIAL_REPORT, st.row_labels)
    add(Profile.FINANCIAL_REPORT, min(3, row_hits / 4), f"{row_hits} financial line items")
    add(Profile.FINANCIAL_REPORT, min(3, fin_hits * 1.0), f"{fin_hits} financial table columns")
    inv_hits = _kw_hits(Profile.INVOICE, st.table_headers)
    add(Profile.INVOICE, min(3, inv_hits * 1.0), f"{inv_hits} invoice table columns")
    if pattern("salutation").search(st.first_paragraph):
        add(Profile.LETTER, 2.5, "opens with a salutation")
    memo_fields = len(pattern("memo_fields").findall(st.first_paragraph))
    if memo_fields >= 2:
        add(Profile.CORPORATE_MEMO, 2.5, f"memo header block ({memo_fields} To/From/Subject fields)")
    if _kw_hits(Profile.LETTER, st.last_paragraphs):
        add(Profile.LETTER, 1.5, "closes with a valediction")

    # Keyword evidence (headings weigh more)
    for p in _KW:
        if p == Profile.LETTER:
            continue                      # handled by salutation/valediction rules
        h = _kw_hits(p, headings)
        b = _kw_hits(p, head_and_start)
        add(p, min(4, h * 1.2 + b * 0.4), f"{h} heading / {b} body keyword matches")

    # Gate: invoices/letters/memos must actually be short documents
    for p in (Profile.INVOICE, Profile.LETTER, Profile.CORPORATE_MEMO):
        if st.words > 1500 or st.headings > 6:
            scores[p] = 0
            why[p] = []

    hint = audience_hint(doc.meta.audience)
    if hint and hint["profile"]:
        add(Profile(hint["profile"]), 1.5, f"meta.audience {doc.meta.audience!r} reads as {hint['name']}")
    audience = None
    if (doc.meta.audience or "").strip():
        audience = (f"{doc.meta.audience!r}: read as {hint['name']}" + (
            f", +1.5 for {hint['profile']}" if hint["profile"] else ", no document type implied")
                    if hint else f"{doc.meta.audience!r}: no audience group matched; not used")

    order = list(Profile)
    ranked = sorted(scores, key=lambda p: (-scores[p], p != Profile.EXECUTIVE_REPORT, order.index(p)))
    best, second = ranked[0], ranked[1]
    conf = confidence(scores[best], scores[second])
    uncertain = scores[best] >= keywords()["profile_confidence"]["no_signal_below"] and conf < UNCERTAIN_BELOW
    alternatives: List[str] = []
    if scores[best] < keywords()["profile_confidence"]["no_signal_below"]:
        best = Profile.GENERAL
        reasons = ["no strong content signal; using balanced general layout"]
    elif uncertain:
        alternatives = [best.value, second.value]
        reasons = [f"uncertain ({conf:.0%}): {best.value} {scores[best]:.1f} against {second.value} "
                   f"{scores[second]:.1f}; using balanced general layout"] + why[best]
        best = Profile.GENERAL
    else:
        reasons = why[best]
    if doc.direction == "rtl":
        reasons = reasons + [f"right-to-left direction (language '{doc.language}', "
                             f"RTL ratio {doc.stats.rtl_ratio:.0%})"]
    return ProfileDecision(profile=best, direction=doc.direction, reasons=reasons,
                           scores={p.value: round(v, 2) for p, v in scores.items() if v},
                           confidence=conf, uncertain=uncertain, alternatives=alternatives, audience=audience)
