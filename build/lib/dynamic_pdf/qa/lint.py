"""
Content lint: what an editor would query in the author's content. Warnings only.

Nothing here changes a document. Each rule reads the semantic document and says where
it looked and what it found, so the author can decide. Rules:

``total_mismatch``    a row labelled total differs from the sum of the rows it closes
``percent_sum``       shares that should add up to 100 do not
``repeated_heading``  the same heading twice under one parent
``unresolved_ref``    a link, ``{ref:id}``, footnote or citation that points at nothing
``mixed_digits``      Western and Arabic-Indic digits in one paragraph or column
``number_format``     one column writes its figures two ways (grouping, decimals, separators)
``date_format``       full dates written in more than one format
``missing_alt_text``  an image with no alt text
``empty_section``     a heading with nothing under it
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Iterable, List, Optional, Tuple

from ..core.inline import parse_inline, plain_text
from ..core.keywords import pattern
from ..core.normalize import SemanticDocument, block_text
from ..core.numbering import REF as _REF
from ..core.table_types import ascii_digits, infer_table, read_cell

RULES = ("total_mismatch", "percent_sum", "repeated_heading", "unresolved_ref", "mixed_digits",
         "number_format", "date_format", "missing_alt_text", "empty_section")
_NOT_PROSE = {"code", "mermaid", "math", "diagram", "qrcode", "shape", "spacer", "divider", "page_break",
              "watermark", "page_media", "table_of_contents"}
_NOT_ADDITIVE = re.compile(r"average|mean|median|avg|rate|ratio|per\b|price|متوسط|معدل|نسبة|سعر", re.I)
_WESTERN, _INDIC = re.compile(r"[0-9]"), re.compile(r"[٠-٩۰-۹]")
_EURO = re.compile(r"^\d{1,3}(?:\.\d{3})+(?:,\d+)?$|^\d+,\d{1,2}$")
_US = re.compile(r"^\d{1,3}(?:,\d{3})+(?:\.\d+)?$")
_MONTH = (r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?"
          r"|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?")
_DATES = (("ISO (2025-03-31)", re.compile(r"\b(?:19|20)\d{2}-[01]\d-[0-3]\d\b")),
          ("day/month/year with slashes", re.compile(r"\b[0-3]?\d/[01]?\d/(?:19|20)\d{2}\b")),
          ("day.month.year with dots", re.compile(r"\b[0-3]?\d\.[01]?\d\.(?:19|20)\d{2}\b")),
          ("Month D, YYYY", re.compile(rf"\b{_MONTH}\s+[0-3]?\d(?:st|nd|rd|th)?,?\s+(?:19|20)\d{{2}}\b", re.I)),
          ("D Month YYYY", re.compile(rf"\b[0-3]?\d(?:st|nd|rd|th)?\s+{_MONTH}\s+(?:19|20)\d{{2}}\b", re.I)))


@dataclass
class LintWarning:
    rule: str
    message: str
    block: Optional[int] = None          # index in the document's blocks
    where: str = ""                      # what part of the block, in words

    def __str__(self) -> str:
        at = f"block {self.block}" if self.block is not None else "document"
        return f"[{self.rule}] {at}{', ' + self.where if self.where else ''}: {self.message}"

    def to_dict(self) -> dict:
        return asdict(self)


def _fmt(x: float, decimals: int) -> str:
    return f"{x:,.{decimals}f}"


def _walk(blocks, out=None, top=None):
    """(top-level index, block) for every block, children of layout blocks included."""
    out = [] if out is None else out
    for i, b in enumerate(blocks):
        idx = i if top is None else top
        out.append((idx, b))
        for name in ("left", "right", "main_content", "sidebar_content"):
            kids = getattr(b, name, None)
            if isinstance(kids, list):
                _walk([k for k in kids if hasattr(k, "type")], out, idx)
        cols = getattr(b, "columns", None)
        if b.type == "three_column" and isinstance(cols, list):
            for col in cols:
                _walk([k for k in col if hasattr(k, "type")], out, idx)
    return out


# ───────────────────────────── tables ─────────────────────────────

def _tables(sem) -> Iterable[Tuple[int, object, list, int]]:
    for i, b in _walk(sem.blocks):
        if b.type == "table":
            rows = [list(r) for r in b.rows] + ([list(b.footer_row)] if b.footer_row else [])
            yield i, b, rows, len(b.rows)


def _col_name(b, ci: int) -> str:
    h = plain_text(b.headers[ci]) if ci < len(b.headers or []) else ""
    return f'column "{h}"' if h.strip() else f"column {ci + 1}"


def _values(rows, ci):
    out = []
    for r in rows:
        c = read_cell(r[ci]) if ci < len(r) else None
        out.append(c if c is not None and c.value is not None and c.kind != "year" else None)
    return out


def _tol(decimals: int, n: int) -> float:
    unit = 10 ** -decimals
    return max(unit, 0.5 * unit * n) + 1e-9


def _totals(i, b, rows, body, warn):
    types = infer_table(b.headers or [], rows)
    totals = set(types.total_rows) | ({len(rows) - 1} if b.footer_row else set())
    subs = set(types.subtotal_rows)
    if not totals and not subs:
        return
    for ci, col in enumerate(types.columns):
        if col.role not in ("measure", "currency") or _NOT_ADDITIVE.search(plain_text(
                b.headers[ci]) if ci < len(b.headers or []) else ""):
            continue
        vals = _values(rows, ci)
        if len({v.unit for v in vals if v}) > 1:
            continue                                  # 2m next to 300k: not summed here
        dec = max((v.decimals for v in vals if v), default=0)
        for t in sorted(totals | subs):
            if vals[t] is None:
                continue
            start = max([s for s in totals | subs if s < t], default=-1)
            groups = []
            run = [v.value for v in vals[start + 1:t] if v]
            groups.append(run)
            parts = [v.value for k, v in enumerate(vals[:t]) if v and k not in totals | subs]
            groups.append(parts)
            if t in totals and subs:
                covered, last = [], -1
                for s in sorted(x for x in subs if x < t):
                    covered.append(vals[s].value if vals[s] else 0.0)
                    last = s
                groups.append(covered + [v.value for v in vals[last + 1:t] if v])
            groups = [g for g in groups if len(g) >= 2]
            if not groups:
                continue
            got = vals[t].value
            if any(abs(sum(g) - got) <= _tol(dec, len(g)) for g in groups):
                continue
            label = plain_text(next((c for c in rows[t] if str(c).strip()), "total"))
            warn("total_mismatch", f"{label!r} shows {_fmt(got, dec)}, but the rows above it add up to "
                                   f"{_fmt(sum(groups[0]), dec)}", i, f"table, {_col_name(b, ci)}")


def _shares(i, b, rows, body, warn):
    types = infer_table(b.headers or [], rows)
    totals = set(types.total_rows) | set(types.subtotal_rows) | ({len(rows) - 1} if b.footer_row else set())
    pct = [ci for ci, c in enumerate(types.columns) if c.role == "percent"]
    share = pattern("tables", "share_header")
    for ci in pct:
        vals = _values(rows, ci)
        head = plain_text(b.headers[ci]) if ci < len(b.headers or []) else ""
        parts = [v for k, v in enumerate(vals) if v and k not in totals]
        hundred = any(vals[t] and abs(vals[t].value - 100) < 1e-6 for t in totals)
        if len(parts) < 2 or any(v.value < 0 for v in parts) or not (share.search(head) or hundred):
            continue
        dec = max(v.decimals for v in parts)
        s = sum(v.value for v in parts)
        if abs(s - 100) > _tol(dec, len(parts)):
            warn("percent_sum", f"shares add up to {_fmt(s, dec)}%, not 100%", i, f"table, {_col_name(b, ci)}")
    # a breakdown across the row (agree / neutral / disagree): most rows make 100, the others are queried
    if len(pct) >= 2 and len(pct) == len(types.numeric_cols):
        sums = []
        for k, r in enumerate(rows):
            vals = [read_cell(r[ci]) if ci < len(r) else None for ci in pct]
            if k in totals or not all(v is not None and v.value is not None for v in vals):
                sums.append(None)
                continue
            dec = max(v.decimals for v in vals)
            sums.append((sum(v.value for v in vals), _tol(dec, len(vals)), dec))
        good = [x for x in sums if x and abs(x[0] - 100) <= x[1]]
        if len(good) * 2 > len([x for x in sums if x]):
            for k, x in enumerate(sums):
                if x and abs(x[0] - 100) > x[1]:
                    label = plain_text(next((c for c in rows[k] if str(c).strip()), f"row {k + 1}"))
                    warn("percent_sum", f"row {label[:40]!r} adds up to {_fmt(x[0], x[2])}%, not 100%", i,
                         f"table, row {k + 1}")


def _formats(i, b, rows, body, warn):
    types = infer_table(b.headers or [], rows)
    totals = set(types.total_rows) | set(types.subtotal_rows) | ({len(rows) - 1} if b.footer_row else set())
    for ci, col in enumerate(types.columns):
        if not col.figure:
            continue
        cells = [read_cell(r[ci]) for k, r in enumerate(rows)       # a total of "100%" may stand rounder
                 if ci < len(r) and str(r[ci]).strip() and k not in totals]
        cells = [c for c in cells if c.value is not None and c.kind != "year"]
        where = f"table, {_col_name(b, ci)}"
        if len({c.kind for c in cells}) > 1 or len({c.unit for c in cells}) > 1:
            continue
        grouped = {c.grouped for c in cells if c.grouped is not None}
        if len(grouped) > 1:
            warn("number_format", "some figures of 1,000 or more have a thousands separator and some do not",
                 i, where)
        decimals = {c.decimals for c in cells}
        if len(decimals) > 1 and len(cells) >= 2:
            shown = " and ".join(str(d) for d in sorted(decimals))
            warn("number_format", f"figures are given to {shown} decimal places", i, where)
        raw = [ascii_digits(plain_text(str(r[ci]))).strip().strip("()+-−%$€£ ") for r in rows if ci < len(r)]
        if any(_EURO.match(x) for x in raw) and any(_US.match(x) for x in raw):
            warn("number_format", "decimal comma and decimal point both used", i, where)


# ───────────────────────────── text ─────────────────────────────

def _texts(sem):
    """(block index, where, text) for every piece of prose, tables cell by cell."""
    for i, b in _walk(sem.blocks):
        if b.type in _NOT_PROSE:
            continue
        if b.type == "table":
            for ri, r in enumerate([b.headers or []] + [list(x) for x in b.rows]):
                for ci, c in enumerate(r):
                    yield i, f"table cell {ri},{ci}", str(c)
            continue
        if b.type in ("two_column", "three_column", "sidebar"):
            continue                                  # their children are walked on their own
        for s in block_text(b):
            yield i, b.type, s


def _anchors(sem) -> set:
    ids = {b.id for _, b in _walk(sem.blocks) if getattr(b, "id", None)}
    return ids | {o.id for o in sem.outline}


def _refs(sem, warn):
    ids = _anchors(sem)
    markers = {b.marker for _, b in _walk(sem.blocks) if b.type == "footnote"}
    used = set()
    for i, where, text in _texts(sem):
        for run in parse_inline(text):
            if run.code:
                continue
            if run.footnote_ref:
                used.add(run.footnote_ref)
                if run.footnote_ref not in markers:
                    warn("unresolved_ref", f"footnote [^{run.footnote_ref}] has no definition", i, where)
            if run.link and run.link.startswith("#") and run.link[1:] not in ids:
                warn("unresolved_ref", f"link to {run.link!r} points at no heading or block id", i, where)
            for ref in _REF.findall(run.text):
                if ref not in ids:
                    warn("unresolved_ref", f"{{ref:{ref}}} names no heading, table or figure", i, where)
    for i, b in _walk(sem.blocks):
        if b.type == "footnote" and b.marker not in used:
            warn("unresolved_ref", f"footnote {b.marker!r} is defined but never referenced", i)
    keys = {e.key for _, b in _walk(sem.blocks) if b.type == "bibliography" for e in b.entries}
    for i, b in _walk(sem.blocks):
        if b.type == "citation" and keys and b.key not in keys:
            warn("unresolved_ref", f"citation {b.key!r} is not in the bibliography", i)


def _digits(sem, warn):
    for i, where, text in _texts(sem):
        if where.startswith("table cell"):
            continue
        t = plain_text(text)
        if _WESTERN.search(t) and _INDIC.search(t):
            warn("mixed_digits", f"Western and Arabic-Indic digits in one passage: {t[:60]!r}", i, where)
    for i, b, rows, _ in _tables(sem):
        ncols = max([len(r) for r in rows] + [0])
        for ci in range(ncols):
            col = " ".join(plain_text(str(r[ci])) for r in rows if ci < len(r))
            if _WESTERN.search(col) and _INDIC.search(col):
                warn("mixed_digits", "Western and Arabic-Indic digits in one column", i, f"table, {_col_name(b, ci)}")


def _dates(sem, warn):
    found = {}
    for i, where, text in _texts(sem):
        t = plain_text(text)
        for name, rx in _DATES:
            m = rx.search(t)
            if m and name not in found:
                found[name] = (i, m.group(0))
    if len(found) > 1:
        examples = "; ".join(f"{name}: {ex!r}" for name, (_, ex) in found.items())
        warn("date_format", f"dates are written in {len(found)} formats ({examples})", min(i for i, _ in found.values()))
    slash = []
    for i, where, text in _texts(sem):
        slash += [(int(a), int(b_)) for a, b_ in re.findall(r"\b([0-3]?\d)/([01]?\d|[0-3]?\d)/(?:19|20)\d{2}\b",
                                                             plain_text(text))]
    if any(a > 12 for a, _ in slash) and any(b_ > 12 for _, b_ in slash):
        warn("date_format", "slash dates put the day first in some places and the month first in others")


def _headings(sem, warn):
    blocks = sem.blocks
    stack: List[Tuple[int, str]] = []
    seen = set()
    for i, b in enumerate(blocks):
        if b.type != "heading":
            continue
        text = " ".join(plain_text(b.text).split()).casefold()
        while stack and stack[-1][0] >= b.level:
            stack.pop()
        key = (b.level, tuple(stack), text)
        if key in seen:
            warn("repeated_heading", f"heading {plain_text(b.text)!r} appears twice under the same parent", i)
        seen.add(key)
        stack.append((b.level, text))
    skip = {"page_break", "spacer", "divider", "watermark", "page_media", "page_section"}
    for i, b in enumerate(blocks):
        if b.type != "heading":
            continue
        nxt = next((x for x in blocks[i + 1:] if x.type not in skip), None)
        if nxt is None or (nxt.type == "heading" and nxt.level <= b.level):
            warn("empty_section", f"heading {plain_text(b.text)!r} has no content under it", i)


def _alt(sem, warn):
    for i, b in _walk(sem.blocks):
        image = b if b.type == "image" else getattr(b, "image", None) if b.type == "image_text_panel" else None
        if image is not None and not (image.alt_text or "").strip():
            warn("missing_alt_text", f"image {image.src!r} has no alt text for readers who cannot see it", i)


def lint(sem: SemanticDocument, rules: Optional[Iterable[str]] = None) -> List[LintWarning]:
    """Warnings about ``sem``'s content, in document order. ``rules`` limits the rules run."""
    wanted = set(rules) if rules is not None else set(RULES)
    unknown = wanted - set(RULES)
    if unknown:
        raise ValueError(f"unknown lint rule(s) {sorted(unknown)}; choose from {RULES}")
    out: List[LintWarning] = []

    def warn(rule, message, block=None, where=""):
        if rule in wanted:
            out.append(LintWarning(rule, message, block, where))

    for i, b, rows, body in _tables(sem):
        _totals(i, b, rows, body, warn)
        _shares(i, b, rows, body, warn)
        _formats(i, b, rows, body, warn)
    for b_i, b in _walk(sem.blocks):
        if b.type == "chart" and b.chart_type in ("pie", "donut") and isinstance(b.data, dict):
            vals = [v for v in b.data.values() if isinstance(v, (int, float))]
            s = sum(vals)
            if len(vals) >= 2 and all(0 <= v <= 100 for v in vals) and 90 <= s <= 110 and abs(s - 100) > 0.5 * len(vals):
                warn("percent_sum", f"pie slices add up to {s:g}; as shares they should make 100", b_i, "chart")
    _refs(sem, warn)
    _digits(sem, warn)
    _dates(sem, warn)
    _headings(sem, warn)
    _alt(sem, warn)
    out.sort(key=lambda w: (w.block if w.block is not None else -1, RULES.index(w.rule)))
    return out


__all__ = ["LintWarning", "RULES", "lint"]
