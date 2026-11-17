"""
LaTeX as a native Word equation (OMML), so it can be edited in Word and read by screen readers.

The LaTeX is turned into MathML by ``latex2mathml`` (a core dependency) and the MathML into Office
Math here. The common structures are covered: scripts, fractions and binomials, roots, large
operators with their limits, accents and bars, fences, matrices and cases, and plain text. Anything
latex2mathml cannot read raises, and the caller falls back to the picture of the formula.
"""
from __future__ import annotations

from typing import List, Optional

from docx.oxml import OxmlElement
from docx.oxml.ns import qn

_MML = "{http://www.w3.org/1998/Math/MathML}"
_NARY = set("∑∏∐∫∬∭∮∯∰⋃⋂⋁⋀⨁⨂⨀")
_ACCENTS = {"^": "̂", "ˆ": "̂", "~": "̃", "˜": "̃", "˙": "̇", "¨": "̈",
            "→": "⃗", "⃗": "⃗", "ˇ": "̌", "´": "́", "`": "̀", "˘": "̆"}
_BARS = set("¯‾―_")
_TRANSPARENT = {"math", "mstyle", "mpadded", "mtd", "merror"}
_LIMITS = {"lim", "liminf", "limsup", "max", "min", "sup", "inf", "det", "Pr", "argmax", "argmin", "gcd"}


def _m(tag: str, *children, **vals):
    e = OxmlElement(f"m:{tag}")
    for k, v in vals.items():
        e.set(qn(f"m:{k}"), v)
    for c in children:
        if c is not None:
            e.append(c)
    return e


def _arg(tag: str, items: List) -> object:
    e = _m(tag)
    for item in items:
        e.append(item)
    return e


def _run(text: str, upright: bool = False, prose: bool = False):
    r = _m("r")
    if prose:                                    # words in a formula: ordinary upright text
        r.append(_m("rPr", _m("nor")))
    elif upright:
        r.append(_m("rPr", _m("sty", val="p")))
    t = OxmlElement("m:t")
    t.text = text
    if text != text.strip():
        t.set(qn("xml:space"), "preserve")
    r.append(t)
    return r


def _name(e) -> str:
    return e.tag.replace(_MML, "") if isinstance(e.tag, str) else ""


def _text(e) -> str:
    return "".join(e.itertext())


def _is_op(e, chars) -> bool:
    return _name(e) == "mo" and _text(e).strip() in chars


def _nary(e):
    """A large operator (a sum, an integral) with its limits, still without its operand."""
    name, kids = _name(e), list(e)
    if _is_op(e, _NARY):
        base, sub, sup, loc = e, None, None, "subSup"
    elif name in ("msub", "msup", "msubsup", "munder", "mover", "munderover") and kids and _is_op(kids[0], _NARY):
        base = kids[0]
        sub = kids[1] if name in ("msub", "msubsup", "munder", "munderover") else None
        sup = (kids[2] if name in ("msubsup", "munderover") else kids[1] if name in ("msup", "mover") else None)
        loc = "undOvr" if name.startswith("mu") or name == "mover" else "subSup"
    else:
        return None
    pr = _m("naryPr", _m("chr", val=_text(base).strip()), _m("limLoc", val=loc))
    if sub is None:
        pr.append(_m("subHide", val="1"))
    if sup is None:
        pr.append(_m("supHide", val="1"))
    return _m("nary", pr, _arg("sub", _node(sub) if sub is not None else []),
              _arg("sup", _node(sup) if sup is not None else []))


_PAIRS = {"(": ")", "[": "]", "{": "}", "|": "|", "‖": "‖", "⟨": "⟩"}


def _bracketed(kids, i) -> Optional[object]:
    """Brackets around a matrix or a binomial (``pmatrix``, ``\binom``) as a delimiter that grows."""
    if i + 2 >= len(kids) or _name(kids[i]) != "mo" or _name(kids[i + 2]) != "mo":
        return None
    open_, close, inside = _text(kids[i]).strip(), _text(kids[i + 2]).strip(), kids[i + 1]
    tall = _name(inside) == "mtable" or (_name(inside) == "mfrac" and inside.get("linethickness") in ("0", "0pt", "0em"))
    if not tall or _PAIRS.get(open_) != close:
        return None
    return _m("d", _m("dPr", _m("begChr", val=open_), _m("endChr", val=close)), _arg("e", _node(inside)))


def _limit(e):
    """``\\lim_{n \\to \\infty}`` and its kin: a function name with its limit below, still
    without its argument, as Word writes it."""
    if _name(e) not in ("msub", "munder") or len(e) < 2 or _text(e[0]).strip() not in _LIMITS:
        return None
    low = _m("limLow", _arg("e", [_run(_text(e[0]).strip(), upright=True)]), _arg("lim", _node(e[1])))
    return _m("func", _arg("fName", [low]))


def _row(children) -> List:
    """A sequence; a large operator or a limit takes the item after it as its operand."""
    kids, out, i = list(children), [], 0
    while i < len(kids):
        d = _bracketed(kids, i)
        if d is not None:
            out.append(d)
            i += 3
            continue
        nary = _nary(kids[i])
        nary = nary if nary is not None else _limit(kids[i])
        if nary is not None:
            nary.append(_arg("e", _node(kids[i + 1]) if i + 1 < len(kids) else []))
            out.append(nary)
            i += 2
            continue
        out += _node(kids[i])
        i += 1
    return out


def _fenced(kids) -> Optional[object]:
    """``\\left( ... \\right)`` as one delimiter that grows with what it holds."""
    def fence(e, form):
        return _name(e) == "mo" and (e.get("fence") == "true" or e.get("stretchy") == "true") and e.get("form") == form
    if not kids or not fence(kids[0], "prefix"):
        return None
    end = kids[-1] if len(kids) > 1 and fence(kids[-1], "postfix") else None
    inner = kids[1:-1] if end is not None else kids[1:]
    pr = _m("dPr", _m("begChr", val=_text(kids[0]).strip()), _m("endChr", val=_text(end).strip() if end is not None else ""))
    return _m("d", pr, _arg("e", _row(inner)))


def _node(e) -> List:
    name, kids = _name(e), list(e)
    if name in _TRANSPARENT:
        return _row(kids)
    if name == "semantics":
        return _node(kids[0]) if kids else []
    if name == "mrow":
        d = _fenced(kids)
        return [d] if d is not None else _row(kids)
    if name == "mi":
        text = _text(e)
        return [_run(text, upright=len(text) > 1 or e.get("mathvariant") == "normal")]
    if name in ("mn", "mo"):
        return [_run(_text(e))]
    if name in ("mtext", "ms"):
        return [_run(_text(e), prose=True)]
    if name == "mspace":
        return [_run(" ")]
    if name == "mphantom":
        return []
    if name == "msup":
        return [_m("sSup", _arg("e", _node(kids[0])), _arg("sup", _node(kids[1])))]
    if name == "msub":
        return [_m("sSub", _arg("e", _node(kids[0])), _arg("sub", _node(kids[1])))]
    if name == "msubsup":
        return [_m("sSubSup", _arg("e", _node(kids[0])), _arg("sub", _node(kids[1])), _arg("sup", _node(kids[2])))]
    if name == "mfrac":
        pr = _m("fPr", _m("type", val="noBar")) if e.get("linethickness") in ("0", "0pt", "0em") else None
        return [_m("f", pr, _arg("num", _node(kids[0])), _arg("den", _node(kids[1])))]
    if name == "msqrt":
        return [_m("rad", _m("radPr", _m("degHide", val="1")), _m("deg"), _arg("e", _row(kids)))]
    if name == "mroot":
        return [_m("rad", _arg("deg", _node(kids[1])), _arg("e", _node(kids[0])))]
    if name in ("mover", "munder"):
        mark = _text(kids[1]).strip() if _name(kids[1]) == "mo" else None
        if name == "mover" and mark in _ACCENTS:
            return [_m("acc", _m("accPr", _m("chr", val=_ACCENTS[mark])), _arg("e", _node(kids[0])))]
        if mark and mark in _BARS:
            return [_m("bar", _m("barPr", _m("pos", val="top" if name == "mover" else "bot")), _arg("e", _node(kids[0])))]
        return [_m("limUpp" if name == "mover" else "limLow", _arg("e", _node(kids[0])), _arg("lim", _node(kids[1])))]
    if name == "munderover":
        low = _m("limLow", _arg("e", _node(kids[0])), _arg("lim", _node(kids[1])))
        return [_m("limUpp", _arg("e", [low]), _arg("lim", _node(kids[2])))]
    if name == "mtable":
        rows = [_arg("mr", [_arg("e", _node(cell)) for cell in tr if _name(cell) == "mtd"]) for tr in kids if _name(tr) == "mtr"]
        return [_arg("m", rows)] if rows else []
    if name == "menclose":
        return [_m("borderBox", _arg("e", _row(kids)))]
    if name == "mfenced":
        pr = _m("dPr", _m("begChr", val=e.get("open", "(")), _m("endChr", val=e.get("close", ")")))
        return [_m("d", pr, *[_arg("e", _node(k)) for k in kids])]
    return _row(kids) if kids else ([_run(_text(e))] if _text(e).strip() else [])


def latex_to_omml(latex: str, display: bool = True):
    """The formula as ``m:oMathPara`` (a displayed equation) or ``m:oMath`` (inline)."""
    from latex2mathml.converter import convert
    from lxml import etree
    root = etree.fromstring(convert(latex).encode("utf-8"))
    body = _row(list(root))
    if not body:
        raise ValueError("the formula is empty")
    math = _arg("oMath", body)
    return _m("oMathPara", math) if display else math
