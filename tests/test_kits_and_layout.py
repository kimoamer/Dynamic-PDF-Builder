"""Ready-made documents (kits), and the layout fixes they brought out: loose justified lines, right-to-left
lines that end in a break, columns in right-to-left text, amounts in words under a column of figures,
and design as the default of render()."""
import io

import pytest

from dynamic_pdf import DocumentBuilder, kit, kit_example, kits


def _ar_invoice():
    d = kit_example("invoice")
    d.update(language="ar", date="١٧ نوفمبر ٢٠٢٦", due="١٧ ديسمبر ٢٠٢٦")
    d["seller"].update(name="مؤسسة النيل", address="طريق الملك فهد، الرياض")
    d["buyer"].update(name="شركة الدلتا", address="شارع العليا، الرياض")
    return d


def _lines(pdf: bytes):
    """(middle, left, right) of each text line on page one, top of the page first."""
    import pypdfium2 as pdfium
    tp = pdfium.PdfDocument(pdf)[0].get_textpage()
    lines = []
    for i in range(tp.count_rects()):
        l, b, r, t = tp.get_rect(i)
        mid = (b + t) / 2
        hit = next((x for x in lines if abs(x[0] - mid) < 5), None)
        if hit:
            hit[1], hit[2] = min(hit[1], l), max(hit[2], r)
        else:
            lines.append([mid, l, r])
    return sorted(lines, reverse=True)


def test_the_invoice_kit_computes_its_totals():
    assert "invoice" in kits()
    doc = kit("invoice", kit_example("invoice")).build()
    table = [b for b in doc.blocks if b.type == "table"][0]
    cells = {r[0]: r[-1] for r in table.rows}
    assert cells["Subtotal"] == "2,657.50" and cells["VAT"] == "398.63" and cells["Total due"] == "3,056.13"
    assert "Three thousand fifty-six riyals" in cells["In words"]
    assert [b.type for b in doc.blocks][:3] == ["heading", "paragraph", "two_column"]


def test_the_invoice_kit_names_what_is_missing_or_wrong():
    d = kit_example("invoice")
    del d["buyer"]["name"]
    with pytest.raises(ValueError, match="'buyer.name' is missing"):
        kit("invoice", d)
    d = kit_example("invoice")
    d["items"][1]["price"] = "a lot"
    with pytest.raises(ValueError, match=r"items\[1\]\.price"):
        kit("invoice", d)
    with pytest.raises(ValueError, match="no kit"):
        kit("payslip", {})


def test_an_arabic_invoice_reads_from_the_right(tmp_path):
    pdf = kit("invoice", _ar_invoice()).render()
    top = _lines(pdf)[:3]                       # the title and the two date lines
    rights = [r for _, _, r in top]
    assert max(rights) - min(rights) < 2, top   # every line ends at the right margin
    for fmt in ("docx", "xlsx"):
        assert kit("invoice", _ar_invoice()).export(str(tmp_path / f"a.{fmt}"))


def test_two_columns_in_arabic_put_the_first_on_the_right():
    import pypdfium2 as pdfium

    def x_of(pdf, needle):
        tp = pdfium.PdfDocument(pdf)[0].get_textpage()
        found = tp.search(needle).get_next()
        return tp.get_charbox(found[0])[0]
    ar = DocumentBuilder().two_column(["العمود الأول 111"], ["العمود الثاني 222"]).render()
    assert x_of(ar, "111") > x_of(ar, "222")
    en = DocumentBuilder().two_column(["First column 111"], ["Second column 222"]).render()
    assert x_of(en, "111") < x_of(en, "222")


def test_a_column_of_amounts_keeps_its_figures_with_a_words_row():
    from dynamic_pdf.core.table_types import infer_table
    rows = [["Paper", "37.50"], ["Toner", "2,620.00"], ["VAT", "398.63"],
            ["In words", "Three thousand fifty-six riyals only"]]
    assert infer_table(["Item", "Amount"], rows).columns[1].figure


def test_a_loose_justified_line_keeps_natural_spacing():
    from reportlab.lib.enums import TA_JUSTIFY
    from reportlab.lib.styles import ParagraphStyle

    from dynamic_pdf.layout.factory import Paragraph
    style = ParagraphStyle("j", fontName="Helvetica", fontSize=10, leading=13, alignment=TA_JUSTIFY)
    loose = Paragraph("Questions should be sent in writing to "
                      "procurement.department.contract-renewals@example-holdings.com before the end of the month.", style)
    loose.wrap(300, 500)
    assert loose._loose_lines(loose.blPara)
    plain = Paragraph("An ordinary paragraph of words that wraps over several lines without any long word "
                      "in it, so every line but the last is justified as usual.", style)
    plain.wrap(300, 500)
    assert not plain._loose_lines(plain.blPara)


def test_render_designs_by_default():
    b = DocumentBuilder().heading("Report").paragraph("Revenue rose.")
    b.render()
    assert b.last_design is not None
    classic = DocumentBuilder().heading("Report").paragraph("Revenue rose.").design(None)
    classic.render()
    assert classic.last_design is None


def test_the_mcp_kit_tool(tmp_path):
    from dynamic_pdf.ai import mcp_server as M
    tools = M.tools(str(tmp_path))
    assert tools["kit"]("invoice")["example"]["number"]
    assert tools["kit"]("invoice", kit_example("invoice"), "i.docx")["path"].endswith("i.docx")
    with pytest.raises(M.InputError, match="missing"):
        tools["kit"]("invoice", {"number": "1"})


def test_a_theme_logo_is_drawn_once_and_kept_by_the_design(tmp_path):
    import pypdfium2 as pdfium
    import pypdfium2.raw as raw
    from PIL import Image

    from dynamic_pdf.themes.registry import get_theme, register_theme
    logo = tmp_path / "logo.png"
    Image.new("RGB", (120, 40), "#336699").save(logo)
    t = get_theme("claude")
    t.name, t.header_footer.enabled, t.header_footer.header_style = "test_logo_once", True, "logo_left"
    t.header_footer.logo = str(logo)
    register_theme(t)

    def images(pdf):
        return sum(o.type == raw.FPDF_PAGEOBJ_IMAGE for o in pdfium.PdfDocument(pdf)[0].get_objects())
    assert images(DocumentBuilder(theme=t.name).paragraph("x").design(None).render()) == 1
    assert images(DocumentBuilder(theme=t.name).paragraph("x").render()) == 1   # the design keeps it on page one


def _figures(name, data):
    from decimal import Decimal
    table = [b for b in kit(name, data).build().blocks if b.type == "table"][0]
    return [r[-1] for r in table.rows], [Decimal(r[-1].replace(",", "")) for r in table.rows[:-1]]


def test_a_quotation_with_a_discount_adds_up_as_printed():
    assert {"invoice", "quote", "letter"} <= set(kits())
    shown, vals = _figures("quote", kit_example("quote"))
    assert shown[2:6] == ["2,657.50", "-132.88", "378.69", "2,903.31"]
    assert vals[0] + vals[1] == vals[2] and sum(vals[2:5]) == vals[5]       # each figure rounded where computed
    d = kit_example("invoice")
    d["discount"] = 150
    assert _figures("invoice", d)[0][3] == "-150.00"
    d["discount"] = "-5%"
    with pytest.raises(ValueError, match="invoice: discount"):
        kit("invoice", d)


def test_a_unit_price_keeps_its_decimals():
    d = kit_example("invoice")
    d["items"] = [{"description": "Fuel", "quantity": 3, "price": "0.333"}]
    table = [b for b in kit("invoice", d).build().blocks if b.type == "table"][0]
    assert table.rows[0][2] == "0.333" and table.rows[0][3].startswith("1.0")


def test_the_letter_kit():
    b = kit("letter", kit_example("letter"))
    doc = b.build()
    kinds = [x.type for x in doc.blocks]
    assert kinds[-2:] == ["signature", "paragraph"] and doc.meta.title == "Renewal of the supply agreement"
    text = " ".join(getattr(x, "text", "") or "" for x in doc.blocks)
    assert "Dear Ms Sara Ahmed," in text and "Yours sincerely," in text and "Enclosures: Quotation" in text
    b.render()
    assert b.last_design.decision.profile.value == "letter"
    assert not any(getattr(x, "hints", None) and x.hints.get("title_block") for x in b._prepared()[0].blocks)
    with pytest.raises(ValueError, match="letter: 'signature.name' is missing"):
        kit("letter", {**kit_example("letter"), "signature": {}})


def test_a_signature_is_literal_text_and_reads_from_the_right_in_arabic():
    import pypdfium2 as pdfium
    pdf = DocumentBuilder().signature("Smith & Jones <Partners>", title="R&D").design(None).render()
    assert "Smith & Jones <Partners>" in pdfium.PdfDocument(pdf)[0].get_textpage().get_text_range()
    lines = _lines(DocumentBuilder().paragraph("نص عربي قصير").signature("عمر حسن", title="مدير المبيعات")
                   .design(None).render())[:3]                    # the paragraph, the name, the title
    rights = [r for _, _, r in lines]
    assert max(rights) - min(rights) < 2, lines                    # all at the right margin


def test_a_phone_number_in_arabic_reads_left_to_right_in_word():
    from docx import Document
    data = DocumentBuilder().paragraph("هاتف: +966 11 000 0000 بين 2024 2025").paragraph("Phone: +966 11 000 0000").render_docx()
    texts = [p.text for p in Document(io.BytesIO(data)).paragraphs if p.text.strip()]
    ar = next(t for t in texts if "هاتف" in t)
    en = next(t for t in texts if "Phone" in t)
    assert "‪+966 11 000 0000‬" in ar and "2024 2025" in ar and "‪" not in ar.split("‬")[1]
    assert "‪" not in en


def test_the_cv_kit():
    doc = kit("cv", kit_example("cv")).build()
    heads = [b.text for b in doc.blocks if b.type == "heading"]
    assert heads[:3] == ["Layla Mansour", "Summary", "Experience"] and "Senior financial analyst" in heads
    text = " ".join(getattr(b, "text", "") or "" for b in doc.blocks)
    assert "Delta Engineering Co. | Cairo | 2022 – Present" in text and "Nile Office Supplies | Alexandria | 2019 – 2022" in text
    ar = kit("cv", {"language": "ar", "name": "ليلى", "headline": "محللة مالية",
                    "contact": {"email": "layla@example.com"},
                    "education": [{"degree": "بكالوريوس", "institution": "جامعة القاهرة", "start": "2015", "end": "2019"}]})
    paras = [b for b in ar.build().blocks if b.type == "rich_text"]
    assert any(p.text.startswith("**محللة مالية**") and "layla" in p.text for p in paras)  # one paragraph: from the right
    assert any(p.text == "جامعة القاهرة | من 2015 إلى 2019" for p in paras) and {p.alignment for p in paras} == {"right"}
    with pytest.raises(ValueError, match=r"cv: 'experience\[0\]\.role' is missing"):
        kit("cv", {"name": "x", "experience": [{"organisation": "y"}]})


def test_a_cv_reads_cleanly_for_applicant_tracking_systems():
    import re

    import pypdfium2 as pdfium
    from docx import Document
    d = kit_example("cv")
    d["summary"] = " ".join(["Specialising in consolidation, intercompany reconciliation, transfer-pricing documentation "
                             "and international financial reporting standards implementation."] * 4)
    b = kit("cv", d)
    pdf = b.render()
    assert b.last_design.decision.profile.value == "general"                  # no numbered sections
    text = "".join(pdfium.PdfDocument(pdf)[i].get_textpage().get_text_range() for i in range(len(pdfium.PdfDocument(pdf))))
    assert text.count("Layla Mansour") == 1 and "Page" not in text            # no running header or footer
    assert not re.search(r"[a-z]-\s*\n", text)                               # no word split over two lines
    assert "Summary" in text and "intercompany reconciliation" in " ".join(text.split())
    docx = Document(io.BytesIO(b.render_docx()))
    assert not docx.tables and not any(p.text for s in docx.sections for p in s.header.paragraphs + s.footer.paragraphs)
    assert [p.style.name for p in docx.paragraphs if p.text == "Experience"] == ["Heading 2"]
