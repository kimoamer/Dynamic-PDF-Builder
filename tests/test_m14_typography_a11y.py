"""M14: Arabic text extraction, hyphenation, contrast, tagging, Word footnotes, QA without PyMuPDF."""
import io

import pymupdf
import pytest

from dynamic_pdf import DocumentBuilder

SRC = ("يسر إدارة الموارد البشرية إبلاغكم بتحديث سياسة العمل المرن اعتباراً من الأول من ديسمبر وذلك بعد تقييم "
       "التجربة التي استمرت ستة أشهر وأظهرت تحسناً في الإنتاجية ورضا الموظفين وتعاون الفرق المختلفة في جميع "
       "الإدارات والفروع الرئيسية للشركة")


def _text(pdf: bytes) -> str:
    return " ".join("".join(p.get_text() for p in pymupdf.open(stream=pdf, filetype="pdf")).split())


# ── F10: Arabic extracts as the letters the author wrote ─────────────────

@pytest.mark.parametrize("design", [False, True])
def test_verbatim_search_finds_arabic_source_text(design):
    heading = "سياسة العمل المرن"
    b = DocumentBuilder().meta(title="t", language="ar").direction("rtl").heading(heading).paragraph(SRC)
    if design:
        b.design()
    text = _text(b.render())
    assert not any(0xFB50 <= ord(c) <= 0xFEFF for c in text), "presentation forms in extracted text"
    assert heading in text
    assert SRC in text                      # verbatim: no NFKC, lam-alef ("إبلاغكم", "الأول") in order


def test_raw_extractor_reads_the_exact_mirror():
    pdfminer = pytest.importorskip("pdfminer.high_level")
    pdf = DocumentBuilder().meta(title="t", language="ar").direction("rtl").paragraph("إبلاغكم من الأول").render()
    raw = pdfminer.extract_text(io.BytesIO(pdf))
    assert "إبلاغكم"[::-1] in raw and "الأول"[::-1] in raw


def test_latin_fonts_keep_their_tounicode():
    from reportlab.pdfbase import ttfonts
    plain = ttfonts.makeToUnicodeCMap.__defaults__[0]
    subset = [0, 32, 65, 0x0628]
    assert ttfonts.makeToUnicodeCMap("X", subset) == plain("X", subset)
    assert "<01> <06270644>" in ttfonts.makeToUnicodeCMap("X", [0, 0xFEFB])   # lam-alef, visual order


# ── F11: hyphenation of justified left-to-right body text ────────────────

LONG = ("Internationalization considerations notwithstanding, telecommunications infrastructure "
        "modernization necessitates comprehensive interoperability characterization, institutional "
        "accountability mechanisms and multidisciplinary implementation responsibilities. ") * 4


def _lines(pdf: bytes):
    return [" ".join(s["text"] for s in ln["spans"]).rstrip()
            for p in pymupdf.open(stream=pdf, filetype="pdf")
            for b in p.get_text("dict")["blocks"] for ln in b.get("lines", [])]


def _hyphen_ends(lines):
    return [ln for ln in lines if ln.endswith("-") and ln[-2:-1].isalpha()]


def test_justified_probe_paragraph_hyphenates_and_keeps_every_word():
    from dynamic_pdf.qa.content_preservation import _dehyphenate
    b = DocumentBuilder().meta(title="t").paragraph(LONG)
    pdf = b.render()
    assert _hyphen_ends(_lines(pdf)), "no line of the probe broke at a hyphenation point"
    joined = " ".join(_dehyphenate("".join(p.get_text() for p in pymupdf.open(stream=pdf))).split())
    assert LONG.strip() in joined
    data, rep = DocumentBuilder().meta(title="t").paragraph(LONG).qa("pdf")
    assert rep.passed, rep.summary()


@pytest.mark.parametrize("make", [
    lambda b: b.heading("Internationalization considerations notwithstanding telecommunications "
                        "infrastructure modernization necessitates interoperability characterization"),
    lambda b: b.table(["Characterization"], [[LONG[:400]]]),
    lambda b: b.code("text", LONG[:300]),
    lambda b: b.bullet_list([LONG[:400]]),
])
def test_no_hyphenation_outside_body_paragraphs(make):
    pdf = make(DocumentBuilder().meta(title="t")).render()
    assert not _hyphen_ends(_lines(pdf))


def test_no_hyphenation_in_right_to_left_or_without_a_dictionary():
    from dynamic_pdf.layout.factory import _hyphenation_lang
    assert _hyphenation_lang("ar") == "" and _hyphenation_lang("en") == "en"
    pdf = DocumentBuilder().meta(title="t", language="ar").direction("rtl").paragraph(LONG).render()
    assert not _hyphen_ends(_lines(pdf))


def test_word_hyphenates_body_text_only():
    from docx.oxml.ns import qn
    from conftest import open_docx
    d = open_docx(DocumentBuilder().meta(title="t").heading("H").paragraph(LONG).render_docx())
    assert d.settings.element.find(qn("w:autoHyphenation")) is not None
    sup = lambda name: d.styles[name].element.pPr.find(qn("w:suppressAutoHyphens")).get(qn("w:val"))
    assert sup("Normal") == "1" and sup("Body Text") == "0"       # headings, tables, code inherit Normal
    rtl = open_docx(DocumentBuilder().meta(title="t", language="ar").direction("rtl").paragraph("نص").render_docx())
    assert rtl.settings.element.find(qn("w:autoHyphenation")) is None


# ── F16: QA and variants without PyMuPDF (AGPL) ──────────────────────────

@pytest.fixture
def no_pymupdf(monkeypatch):
    """PyMuPDF uninstalled, as far as the package can tell: importing it fails."""
    pytest.importorskip("pypdfium2")
    import sys
    for name in ("pymupdf", "fitz"):
        monkeypatch.setitem(sys.modules, name, None)        # `import pymupdf` raises ImportError
    monkeypatch.delenv("DYNAMIC_PDF_QA_BACKEND", raising=False)
    from dynamic_pdf.qa.pdf_backend import backend_name
    assert backend_name() == "pdfium"


def _sample():
    return (DocumentBuilder().meta(title="Quarterly review", author="Ops")
            .heading("Summary").paragraph(LONG)
            .heading("Figures").table(["Region", "Revenue"], [["North", "1,200"], ["South", "980"]])
            .heading("ملخص").paragraph(SRC))


def test_qa_runs_without_pymupdf(no_pymupdf):
    from reportlab.pdfgen.canvas import Canvas
    from dynamic_pdf.qa import check_pdf
    from dynamic_pdf.qa.visual_critique import critique_pdf
    data, rep = _sample().design().qa("pdf")
    assert rep.passed and rep.pages >= 1, rep.summary()
    assert critique_pdf(data).available
    buf = io.BytesIO()                     # a planted defect is still caught
    c = Canvas(buf)
    c.setFont("Helvetica", 11)
    c.drawString(560, 700, "This line runs off the right edge of the page")
    c.setFont("ZapfDingbats", 14)
    c.drawString(72, 600, "IIIII")
    c.save()
    codes = {f.code for f in check_pdf(buf.getvalue(), margins={"left": 54, "right": 54}).errors}
    assert {"clipped_text", "missing_glyph"} <= codes


def test_variants_run_without_pymupdf(no_pymupdf):
    got = _sample().design_variants(n=3)
    assert any(v.valid for v in got), [v.report.hard_failures for v in got]
    for v in got:
        assert not [u for u in v.report.unverified if "PDF reader" in u or "PyMuPDF" in u], v.report.unverified
        assert v.report.heuristics, "the page images were not measured"


# ── contrast (WCAG AA) ───────────────────────────────────────────────────

def _canvas_pdf(draw) -> bytes:
    from reportlab.pdfgen.canvas import Canvas
    buf = io.BytesIO()
    c = Canvas(buf)
    draw(c)
    c.save()
    return buf.getvalue()


def _contrast(pdf):
    from dynamic_pdf.qa import check_pdf
    return [f for f in check_pdf(pdf).findings if f.code == "low_contrast"]


def _draw_samples(c):
    from reportlab.lib.colors import HexColor
    c.setFont("Helvetica", 11)
    c.setFillColor(HexColor("#999999"))                 # 2.85:1 on white: fails body text
    c.drawString(72, 700, "Pale grey body text")
    c.setFillColor(HexColor("#333333"))
    c.drawString(72, 650, "Dark body text")
    c.setFillColor(HexColor("#1f4e79"))                 # a dark band with white type passes
    c.rect(60, 560, 300, 40, fill=1, stroke=0)
    c.setFillColor(HexColor("#ffffff"))
    c.drawString(72, 575, "White on navy")
    c.setFont("Helvetica-Bold", 20)
    c.setFillColor(HexColor("#888888"))                 # 3.54:1: enough for large text
    c.drawString(72, 500, "Large grey heading")


def _check_contrast():
    found = _contrast(_canvas_pdf(_draw_samples))
    assert [f.text for f in found] == ["Pale grey body text"], [(f.text, f.message) for f in found]
    assert "2.85:1" in found[0].message and "4.5:1" in found[0].message
    assert found[0].severity == "warning"               # reported, never a gate failure


def test_contrast_check_measures_text_against_what_is_painted_behind_it():
    _check_contrast()


def test_contrast_check_without_pymupdf(no_pymupdf):
    _check_contrast()


def test_default_designs_have_no_low_contrast_body_text():
    _, rep = _sample().design().qa("pdf")
    assert not [f for f in rep.findings if f.code == "low_contrast"], rep.summary()


# ── DOCX: real Word footnotes ────────────────────────────────────────────

FN_MD = ("Sleep supports recall.[^1] Doses vary.[^dagger] See note one again.[^1]\n\n"
         "[^1]: Data available on [request](https://example.com/data).\n"
         "[^dagger]: Two participants withdrew.\n"
         "[^9]: Defined but never referenced.\n")


def _parts(data: bytes) -> dict:
    import zipfile
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return {n: z.read(n).decode("utf-8") for n in z.namelist() if n.endswith((".xml", ".rels"))}


def test_referenced_footnotes_are_word_footnotes():
    from conftest import docx_text, open_docx
    data = DocumentBuilder.from_markdown(FN_MD).render_docx()
    parts = _parts(data)
    notes, body = parts["word/footnotes.xml"], parts["word/document.xml"]
    assert "footnotes+xml" in parts["[Content_Types].xml"]
    assert "relationships/footnotes" in parts["word/_rels/document.xml.rels"]
    assert body.count("<w:footnoteReference") == 2                   # one per note; a repeat stays a marker
    assert 'w:customMarkFollows="1"' in body and '<w:t xml:space="preserve">dagger</w:t>' in body
    assert "Data available on" in notes and "Two participants withdrew." in notes and "<w:footnoteRef/>" in notes
    assert "https://example.com/data" in parts["word/_rels/footnotes.xml.rels"]   # the link works in the note
    assert "Data available" not in body and "Two participants" not in body         # not also in the flow
    assert "Defined but never referenced." in body and "Defined but" not in notes  # unreferenced: as before
    d = open_docx(data)                                     # python-docx opens it; the styles exist
    assert d.styles["Footnote Text"] and d.styles["Footnote Reference"]
    text = docx_text(data)
    assert "Two participants withdrew." in text and "again" in text


def test_footnoted_docx_keeps_its_content_ledger():
    from dynamic_pdf.core.content_ledger import build_content_ledger
    from dynamic_pdf.qa.content_preservation import VERIFIED, check_docx_content
    b = DocumentBuilder.from_markdown(FN_MD)
    result = check_docx_content(build_content_ledger(b.semantic().to_document()), b.render_docx())
    assert result.status == VERIFIED, result.details          # "recall.1" reads with its number


def test_libreoffice_sets_the_footnotes_at_the_foot_of_the_page():
    from dynamic_pdf.qa.docx_checks import docx_to_pdf
    pdf = docx_to_pdf(DocumentBuilder.from_markdown(FN_MD).render_docx())
    if not pdf:
        pytest.skip("LibreOffice is not available")
    page = pymupdf.open(stream=pdf, filetype="pdf")[0]
    note = page.search_for("Two participants withdrew.")
    body = page.search_for("Sleep supports recall.")
    assert note and body and note[0].y0 > page.rect.height * 0.6 > body[0].y1


# ── F9: tagged PDF (opt-in spike) ────────────────────────────────────────

def _tagged_sample(tagged=True):
    import tempfile
    from PIL import Image
    png = tempfile.mktemp(suffix=".png")
    Image.new("RGB", (300, 150), (30, 90, 160)).save(png)
    return (DocumentBuilder().meta(title="Tagged sample", tagged=tagged)
            .heading("Summary").paragraph(LONG * 8)
            .heading("Detail", level=2).bullet_list(["First item", "Second item"])
            .image(png, caption="A blue box", alt_text="A blue rectangle")
            .table(["Region", "Revenue"], [["North", "1"], ["South", "2"]] * 25))


def _tree(pdf: bytes):
    import pikepdf
    p = pikepdf.open(io.BytesIO(pdf))
    out = []

    def walk(e, depth):
        kids = [k for k in e.K if isinstance(k, pikepdf.Dictionary)]
        mcrs = [k for k in kids if k.get("/Type") == "/MCR"]
        out.append((depth, str(e.S)[1:], len(mcrs), str(e.get("/Alt", ""))))
        for k in kids:
            if k.get("/Type") == "/StructElem":
                assert k.P == e
                walk(k, depth + 1)
    walk(p.Root.StructTreeRoot.K[0], 0)
    return p, out


def test_tagged_pdf_has_a_structure_tree():
    pytest.importorskip("pikepdf")
    pdf = _tagged_sample().render()
    p, tree = _tree(pdf)
    assert p.Root.MarkInfo.Marked is True and str(p.Root.Lang) == "en"
    tags = [t for _, t, _, _ in tree]
    assert tags[0] == "Document" and tags[1:4] == ["H1", "P", "H2"]
    assert tags.count("LI") == 2 and tags.count("LBody") == 2 and "L" in tags
    assert ("Figure", "A blue rectangle") in [(t, alt) for _, t, _, alt in tree]
    assert "Caption" in tags and tags.count("TH") == 2 and tags.count("TD") == 100
    first_tr = tags.index("TR")
    assert tags[first_tr + 1:first_tr + 3] == ["TH", "TH"]             # header cells in the first row
    assert [n for _, t, n, _ in tree if t == "P"][0] >= 2                # a paragraph split over pages: one P
    # every marked-content id on every page is in the parent tree, and only those
    nums = list(p.Root.StructTreeRoot.ParentTree.Nums)
    import pikepdf
    for index, page in enumerate(p.pages):
        ids = [ops[1].MCID for ops, op in pikepdf.parse_content_stream(page)
               if str(op) == "BDC" and isinstance(ops[1], pikepdf.Dictionary) and "/MCID" in ops[1]]
        if ids:
            assert page.StructParents == index and str(page.Tabs) == "/S"
            assert sorted(ids) == list(range(len(ids))) == list(range(len(nums[nums.index(index) + 1])))


def test_tagging_changes_neither_pixels_nor_text():
    pytest.importorskip("pikepdf")
    plain, tagged = _tagged_sample(False).render(), _tagged_sample(True).render()
    a, b = pymupdf.open(stream=plain), pymupdf.open(stream=tagged)
    assert [p.get_pixmap(dpi=40).samples for p in a] == [p.get_pixmap(dpi=40).samples for p in b]
    assert [p.get_text() for p in a] == [p.get_text() for p in b]
    import pikepdf
    assert "/StructTreeRoot" not in pikepdf.open(io.BytesIO(plain)).Root      # off unless asked for


def test_running_heads_and_feet_are_artifacts():
    pytest.importorskip("pikepdf")
    import pikepdf
    pdf = pikepdf.open(io.BytesIO(_tagged_sample().render()))
    ops = [(str(op), operands) for operands, op in pikepdf.parse_content_stream(pdf.pages[0])]
    assert any(op == "BMC" and str(o[0]) == "/Artifact" for op, o in ops)



def test_a_word_hyphenated_across_a_page_break_is_rejoined():
    # extraction puts a blank line where a page or column ends between the two halves
    from dynamic_pdf.qa.content_preservation import _dehyphenate
    assert _dehyphenate("Effects were estim-\n\nated with mixed models") == "Effects were estimated with mixed models"
    assert _dehyphenate("well-\n\n42 cases") == "well-\n\n42 cases"          # a digit is not a word's tail


def test_a_word_hyphenated_over_the_running_head_and_foot_is_found():
    from dynamic_pdf.qa.content_preservation import _split_over_bands
    text = "effects were estim-\nsleep and recall\ndiscussion\npage 3 of 4\n\nated with mixed models"
    assert _split_over_bands(text, "estimated", 1) == 1
    assert _split_over_bands("effects were estim-\nnothing here", "estimated", 1) == 0
