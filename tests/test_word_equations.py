"""Equations reach Word as native, editable Office Math (OMML), not pictures."""
import io
import zipfile

import pytest
from lxml import etree

from dynamic_pdf import DocumentBuilder
from dynamic_pdf.renderers.omml import latex_to_omml
from dynamic_pdf.schema.blocks import MathBlock

M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"


def tags(latex, display=True):
    root = latex_to_omml(latex, display)
    return root, [e.tag.replace(M, "") for e in root.iter() if isinstance(e.tag, str)]


def val(root, path):
    return root.find(path).get(M + "val")


@pytest.mark.parametrize("latex, expected", [
    (r"E = mc^2", {"sSup"}),
    (r"x_i^2", {"sSubSup"}),
    (r"\frac{a+b}{2}", {"f", "num", "den"}),
    (r"\sqrt{x}", {"rad", "degHide"}),
    (r"\sqrt[3]{x}", {"rad", "deg"}),
    (r"\left( \frac{1}{2} \right)", {"d", "begChr", "endChr"}),
    (r"\begin{pmatrix} a & b \\ c & d \end{pmatrix}", {"d", "m", "mr"}),
    (r"\overline{AB}", {"bar"}),
    (r"\hat{\beta}", {"acc"}),
])
def test_each_structure_becomes_its_word_counterpart(latex, expected):
    _, seen = tags(latex)
    assert expected <= set(seen), seen


def test_a_large_operator_carries_its_limits_and_takes_its_operand():
    root, _ = tags(r"\sum_{i=1}^{n} x_i")
    nary = root.find(f".//{M}nary")
    assert val(nary, f"{M}naryPr/{M}chr") == "∑"
    assert "".join(nary.find(f"{M}sub").itertext()) == "i=1" and "".join(nary.find(f"{M}sup").itertext()) == "n"
    assert nary.find(f"{M}e/{M}sSub") is not None                # x_i is what is summed


def test_a_limit_is_a_function_with_its_limit_below():
    root, _ = tags(r"\lim_{n \to \infty} a_n")
    func = root.find(f".//{M}func")
    assert "".join(func.find(f"{M}fName/{M}limLow/{M}e").itertext()) == "lim"
    assert func.find(f"{M}e/{M}sSub") is not None


def test_a_binomial_has_no_bar_and_brackets_that_grow():
    root, _ = tags(r"\binom{n}{k}")
    d = root.find(f".//{M}d")
    assert val(d, f"{M}dPr/{M}begChr") == "(" and val(d, f"{M}e/{M}f/{M}fPr/{M}type") == "noBar"


def test_words_in_a_formula_are_ordinary_text_and_names_are_upright():
    root, _ = tags(r"\sin\theta \text{ if } x")
    runs = {"".join(r.itertext()): r for r in root.iter(f"{M}r")}
    assert runs["sin"].find(f"{M}rPr/{M}sty") is not None
    assert runs["\xa0if\xa0"].find(f"{M}rPr/{M}nor") is not None


def test_display_and_inline_forms():
    assert latex_to_omml("x", True).tag == M + "oMathPara"
    assert latex_to_omml("x", False).tag == M + "oMath"


def _document_xml(b):
    with zipfile.ZipFile(io.BytesIO(b.render_docx())) as z:
        return z.read("word/document.xml").decode("utf-8")


def test_the_word_file_holds_an_equation_and_its_number_not_a_picture():
    b = DocumentBuilder().heading("Results")
    b._blocks.append(MathBlock(latex=r"\frac{a}{b}", equation_number=3))
    b.math(r"E = mc^2")
    xml = _document_xml(b)
    assert xml.count("<m:oMath>") == 2 and "<m:oMathPara>" in xml and "<w:drawing>" not in xml
    assert "(3)</w:t>" in xml and 'w:val="right"' in xml          # the number sits at the far edge


def test_what_office_math_cannot_hold_falls_back_to_the_picture(monkeypatch):
    import dynamic_pdf.renderers.omml as O

    def refuse(*a, **k):
        raise ValueError("cannot")
    monkeypatch.setattr(O, "latex_to_omml", refuse)
    xml = _document_xml(DocumentBuilder().math(r"x^2"))
    assert "<m:oMath" not in xml and "<w:drawing>" in xml and 'descr="Equation: x^2"' in xml
