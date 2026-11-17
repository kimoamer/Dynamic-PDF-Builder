"""Displayed equations with an id are numbered, and {ref:id} reads "Equation (n)", as tables and figures."""
import io

import pytest

from dynamic_pdf import DocumentBuilder
from dynamic_pdf.markdown.preprocessors import extract_math
from dynamic_pdf.schema.blocks import MathBlock

MD = r"""---
title: Energy
---
# Model

The energy follows {ref:eq-energy}, and the variance {ref:eq-var}.

$$ E = mc^2 $$ {#eq-energy}

$$ \sigma^2 = \frac{1}{n}\sum x_i^2 $$ {#eq-var}

$$ a^2 + b^2 = c^2 $$
"""


def test_markdown_gives_the_id_and_numbers_follow_document_order():
    assert extract_math("$$ x $$ {#eq-a}") == "```math {#eq-a}\n x \n```"
    maths = [b for b in DocumentBuilder.from_markdown(MD).build().blocks if b.type == "math"]
    assert [(m.id, m.equation_number) for m in maths] == [("eq-energy", 1), ("eq-var", 2), (None, None)]


def test_an_authors_number_holds_and_the_count_goes_on_from_it():
    b = DocumentBuilder().add_block(MathBlock(latex="a", id="a")).add_block(MathBlock(latex="b", equation_number=5))
    b.add_block(MathBlock(latex="c", id="c")).add_block(MathBlock(latex="d", inline=True, id="d"))
    assert [m.equation_number for m in b.build().blocks] == [1, 5, 6, None]
    assert b._blocks[0].equation_number is None                  # the source is left as written


def test_both_formats_show_the_number_and_the_reference():
    pymupdf = pytest.importorskip("pymupdf")
    b = DocumentBuilder.from_markdown(MD)
    text = " ".join(pymupdf.open(stream=b.render(), filetype="pdf")[0].get_text().split())
    assert "follows Equation (1), and the variance Equation (2)." in text and "(1)" in text and "(2)" in text
    import docx
    paras = [p.text for p in docx.Document(io.BytesIO(b.render_docx())).paragraphs]
    assert "The energy follows Equation (1), and the variance Equation (2)." in paras
    assert sum(p.endswith("(1)") or p.endswith("(2)") for p in paras) == 2


def test_arabic_references_read_in_arabic():
    b = DocumentBuilder().meta(language="ar").paragraph("كما في {ref:eq-a}.").add_block(MathBlock(latex="x", id="eq-a"))
    import docx
    assert "كما في المعادلة (1)." in [p.text for p in docx.Document(io.BytesIO(b.render_docx())).paragraphs]
