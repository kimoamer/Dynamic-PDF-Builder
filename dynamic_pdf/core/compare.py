"""
What changed between two versions of a document, written as suggested edits (CriticMarkup), so
the comparison is a document: in Word every change is a tracked change to accept or reject, and
the PDF is a review copy.

Blocks are matched in order by their kind and text. A changed paragraph, heading, quote, callout
or list item shows its words removed and added; a table with the same columns shows its changed
cells and its added and removed rows. Blocks added are marked as additions and blocks removed as
removals; a removed picture or chart is named in a removed line. Formulas are compared by what
they show. Emphasis is kept where the text did not change.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import List

# a number with its separators and percent sign is one word: 3,400 changes as a whole
_WORDS = re.compile(r"\s+|[0-9٠-٩]+(?:[.,٫٬][0-9٠-٩]+)*[%٪]?|[\w؀-ۿ]+|[^\w\s]", re.UNICODE)
_TEXT_FIELDS = {"paragraph": ("text",), "heading": ("text",), "quote": ("text", "attribution"),
                "callout": ("title", "text"), "note": ("text",), "rich_text": ("text",), "footnote": ("text",)}


def _mark(kind: str, text: str) -> str:
    if not text.strip():
        return text
    lead, core, trail = re.match(r"(\s*)(.*?)(\s*)$", text, re.S).groups()
    return f"{lead}{{{kind}{kind}{core}{kind}{kind}}}{trail}" if kind != "~" else text


def added(text: str) -> str:
    return _mark("+", text) if text else text


def removed(text: str) -> str:
    return _mark("-", text) if text else text


def words(old: str, new: str) -> str:
    """``new`` with what differs from ``old`` marked word by word."""
    if old == new:
        return new
    a, b = _WORDS.findall(old or ""), _WORDS.findall(new or "")
    out = []
    for op, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        before, after = "".join(a[i1:i2]), "".join(b[j1:j2])
        if op == "equal":
            out.append(after)
        elif op == "insert":
            out.append(added(after))
        elif op == "delete":
            out.append(removed(before))
        elif before.strip() and after.strip():
            lead = re.match(r"\s*", after).group(0)
            out.append(f"{lead}{{~~{before.strip()}~>{after.strip()}~~}}" + after[len(after.rstrip()):])
        else:
            out.append(removed(before) + added(after))
    return "".join(out)


def _sig(b) -> tuple:
    t = getattr(b, "type", "")
    if t in _TEXT_FIELDS:
        return (t, " ".join(str(getattr(b, f, "") or "") for f in _TEXT_FIELDS[t]))
    if t in ("bullet_list", "numbered_list"):
        return (t, " | ".join(_item_text(i) for i in b.items))
    if t == "table":
        return (t, tuple(b.headers), len(b.rows))
    return (t, b.model_dump_json(exclude={"hints", "id"}))


def _item_text(item) -> str:
    return item if isinstance(item, str) else getattr(item, "text", "")


def _same_kind(a, b) -> bool:
    return getattr(a, "type", None) == getattr(b, "type", None) and (
        a.type != "table" or list(a.headers) == list(b.headers))


def _changed(old, new):
    """``new`` with its differences from ``old`` (a block of the same kind) marked."""
    t = new.type
    if t in _TEXT_FIELDS:
        return new.model_copy(update={f: words(getattr(old, f, "") or "", getattr(new, f, "") or "")
                                      for f in _TEXT_FIELDS[t] if getattr(new, f, None) is not None})
    if t in ("bullet_list", "numbered_list"):
        return new.model_copy(update={"items": _items(old.items, new.items)})
    if t == "table":
        return new.model_copy(update=_table(old, new))
    return new


def _items(old: list, new: list) -> list:
    a, b = [_item_text(i) for i in old], [_item_text(i) for i in new]
    out = []
    for op, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            out += new[j1:j2]
        else:
            for k, item in enumerate(old[i1:i2]):
                partner = new[j1 + k] if op == "replace" and j1 + k < j2 else None
                if partner is None:
                    out.append(_set_text(item, removed(_item_text(item))))
            for k, item in enumerate(new[j1:j2]):
                partner = old[i1 + k] if op == "replace" and i1 + k < i2 else None
                out.append(_set_text(item, words(_item_text(partner), _item_text(item)) if partner is not None
                                     else added(_item_text(item))))
    return out


def _set_text(item, text):
    return text if isinstance(item, str) else item.model_copy(update={"text": text})


def _table(old, new) -> dict:
    rows_a = [list(r) for r in old.rows]
    rows_b = [list(r) for r in new.rows]
    keys_a, keys_b = [r[0] if r else "" for r in rows_a], [r[0] if r else "" for r in rows_b]
    out = []
    for op, i1, i2, j1, j2 in SequenceMatcher(None, keys_a, keys_b, autojunk=False).get_opcodes():
        pairs = list(zip(rows_a[i1:i2], rows_b[j1:j2])) if op in ("equal", "replace") else []
        for ra, rb in pairs:
            out.append([words(str(x), str(y)) if x != y else str(y) for x, y in zip(ra + [""] * (len(rb) - len(ra)), rb)])
        for ra in rows_a[i1 + len(pairs):i2]:
            out.append([removed(str(x)) for x in ra])
        for rb in rows_b[j1 + len(pairs):j2]:
            out.append([added(str(x)) for x in rb])
    update = {"rows": out}
    if new.footer_row:
        fa = list(old.footer_row or [""] * len(new.footer_row))
        update["footer_row"] = [words(str(x), str(y)) if x != y else str(y) for x, y in zip(fa, new.footer_row)]
    if (old.caption or "") != (new.caption or "") and new.caption:
        update["caption"] = words(old.caption or "", new.caption)
    return update


def _gone(b):
    """A removed block, kept as a removal where it held text, named where it did not."""
    from ..schema.blocks import ParagraphBlock
    if b.type in _TEXT_FIELDS or b.type in ("bullet_list", "numbered_list", "table"):
        if b.type == "table":
            return b.model_copy(update={"rows": [[removed(str(x)) for x in r] for r in b.rows]})
        return _mark_all(b, removed)
    what = {"image": "picture", "chart": "chart", "math": "equation"}.get(b.type, b.type.replace("_", " "))
    name = getattr(b, "caption", None) or getattr(b, "title", None) or getattr(b, "alt_text", None) or ""
    return ParagraphBlock(text=removed(f"[{what} removed{': ' + name if name else ''}]"))


def _mark_all(b, mark):
    t = b.type
    if t in _TEXT_FIELDS:
        return b.model_copy(update={f: mark(getattr(b, f)) for f in _TEXT_FIELDS[t] if getattr(b, f, None)})
    if t in ("bullet_list", "numbered_list"):
        return b.model_copy(update={"items": [_set_text(i, mark(_item_text(i))) for i in b.items]})
    if t == "table":
        return b.model_copy(update={"rows": [[mark(str(x)) for x in r] for r in b.rows]})
    return b


def compare_blocks(old: list, new: list) -> List:
    """``new`` with every difference from ``old`` marked as a suggested edit."""
    a, b = [_sig(x) for x in old], [_sig(x) for x in new]
    out: List = []
    for op, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            out += new[j1:j2]
            continue
        olds, news = old[i1:i2], new[j1:j2]
        used = 0
        for nb in news:
            match = next((k for k in range(used, len(olds)) if _same_kind(olds[k], nb)), None) if op == "replace" else None
            if match is not None:
                out += [_gone(x) for x in olds[used:match]]
                out.append(_changed(olds[match], nb))
                used = match + 1
            else:
                out.append(_mark_all(nb, added))
        out += [_gone(x) for x in olds[used:]]
    return out
