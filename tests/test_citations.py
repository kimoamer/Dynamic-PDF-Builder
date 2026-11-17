"""[@key] citations from a BibTeX library, written in APA or IEEE, with the list of works cited."""
import io

import pytest

from dynamic_pdf import DocumentBuilder
from dynamic_pdf.core.citations import parse_bibtex
from dynamic_pdf.utils.errors import AssetError

BIB = r"""
@string{jcp = "Journal of Coastal Policy"}
@comment{ignored}
@article{abara2023,
  author = {Abara, Tomas and Halvorsen, Ines},
  title = {Retreat without {L}eaving: managed relocation},
  journal = {Journal of Coastal Policy}, volume = 12, number = {2}, pages = {45--67}, year = 2023,
  doi = {10.1000/jcp.2023.12}
}
@book{lund2022, author = "Peter Lund", title = "Choice Models for Relocation", publisher = {Estuary Press}, year = {2022}}
@inproceedings{kim2021, author={Kim, Ji-Woo and Park, S. and Lee, Dana}, title={Floods \& Markets},
  booktitle={Proc. Coastal Econ.}, pages={1--10}, year={2021}}
@misc{unused2020, author={Nobody, A.}, title={Never cited}, year={2020}}
"""
TEXT = "Retreat works [@abara2023, p. 50]; markets respond [@kim2021; @lund2022]. Again [@abara2023]."


def test_bibtex_fields_braces_quotes_numbers_and_tex():
    lib = parse_bibtex(BIB)
    assert set(lib) == {"abara2023", "lund2022", "kim2021", "unused2020"}
    assert lib["abara2023"]["title"] == "Retreat without Leaving: managed relocation"
    assert lib["abara2023"]["pages"] == "45–67" and lib["abara2023"]["volume"] == "12"
    assert lib["kim2021"]["title"] == "Floods & Markets" and lib["lund2022"]["author"] == "Peter Lund"


def built(style):
    b = DocumentBuilder().heading("Intro").paragraph(TEXT).bibtex(BIB, style=style)
    blocks = b.build().blocks
    return blocks[1].text, blocks[-1]


def test_apa_writes_author_and_year_and_lists_by_author():
    text, refs = built("apa")
    assert text == ("Retreat works (Abara & Halvorsen, 2023, p. 50); markets respond (Kim et al., 2021; Lund, 2022). "
                    "Again (Abara & Halvorsen, 2023).")
    assert [e.key for e in refs.entries] == ["abara2023", "kim2021", "lund2022"]       # the uncited entry is left out
    assert refs.entries[0].authors == "Abara, T., & Halvorsen, I." and refs.entries[0].source == "Journal of Coastal Policy, 12(2), 45–67"
    assert refs.style == "apa" and refs.entries[0].doi == "10.1000/jcp.2023.12"


def test_ieee_numbers_in_order_of_first_citation():
    text, refs = built("ieee")
    assert text == "Retreat works [1, p. 50]; markets respond [2], [3]. Again [1]."
    assert [e.key for e in refs.entries] == ["abara2023", "kim2021", "lund2022"] and refs.style == "ieee"
    assert refs.entries[1].authors == "J. W. Kim, S. Park and D. Lee"


def test_markdown_front_matter_file_marker_and_formats(tmp_path):
    (tmp_path / "refs.bib").write_text(BIB, encoding="utf-8")
    md = (f"---\ntitle: P\nbibliography: {tmp_path / 'refs.bib'}\ncitation-style: ieee\n---\n# Intro\n\n{TEXT}\n\n"
          "# References\n\n[REFERENCES]\n\n# Appendix\n\nMore.\n")
    b = DocumentBuilder.from_markdown(md)
    kinds = [x.type for x in b.build().blocks]
    assert kinds.index("bibliography") < kinds.index("heading", kinds.index("bibliography"))   # the list where the marker is
    import docx
    paras = [p.text for p in docx.Document(io.BytesIO(b.render_docx())).paragraphs if p.text.strip()]
    assert paras.count("References") == 1 and paras[paras.index("References") + 1].startswith("[1] T. Abara and I. Halvorsen")
    pymupdf = pytest.importorskip("pymupdf")
    pdf = " ".join(pymupdf.open(stream=b.render(), filetype="pdf")[0].get_text().split())
    assert "Retreat works [1, p. 50]" in pdf and "[3] P. Lund" in pdf


def test_an_unknown_key_stays_and_lint_reports_it_with_or_without_a_library():
    b = DocumentBuilder().paragraph("As shown [@missing2019] and [@abara2023].").bibtex(BIB)
    assert "[@missing2019]" in b.build().blocks[0].text and "(Abara & Halvorsen, 2023)" in b.build().blocks[0].text
    assert [w.rule for w in b.lint()] == ["unresolved_citation"]
    assert [w.rule for w in DocumentBuilder().paragraph("No library [@x].").lint()] == ["unresolved_citation"]


def test_text_without_citations_and_code_are_left_alone():
    b = DocumentBuilder().paragraph("Email me at [someone@example.com] please.").code("python", "x = [@not_a_cite]").bibtex(BIB)
    blocks = b.build().blocks
    assert blocks[0].text == "Email me at [someone@example.com] please." and blocks[1].code == "x = [@not_a_cite]"
    assert len(blocks) == 2                                   # nothing cited: no list is added


def test_the_bib_file_is_read_under_the_asset_policy(tmp_path):
    from dynamic_pdf.assets import AssetPolicy
    from dynamic_pdf.policy import RenderPolicy
    (tmp_path / "refs.bib").write_text(BIB, encoding="utf-8")
    with pytest.raises(AssetError):
        DocumentBuilder(policy=RenderPolicy(assets=AssetPolicy(allow_local=False))).bibtex(str(tmp_path / "refs.bib"))
