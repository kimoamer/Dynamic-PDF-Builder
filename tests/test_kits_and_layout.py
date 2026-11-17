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


def test_npv_and_irr_are_computed_as_a_spreadsheet_computes_them():
    md = ("| Year | Net |\n|---|---:|\n| 0 | -10,000 |\n| 1 | 3,000 |\n| 2 | 4,200 |\n| 3 | 6,800 |\n"
          "| NPV | =B2+NPV(10%, B3:B5) |\n| IRR | =IRR(B2:B5) |\n")
    rows = DocumentBuilder.from_markdown(md).build().blocks[0].rows
    assert rows[-2][1] == "1,307" and rows[-1][1] == "16.3%"          # 1,307.29 and 16.34%, as Excel gives
    from dynamic_pdf.core.formulas import FormulaError
    with pytest.raises(FormulaError, match="change sign"):
        DocumentBuilder.from_markdown("| A | B |\n|---|---|\n| x | 5 |\n| y | =IRR(B2:B2) |\n").build()


def test_the_feasibility_kit():
    b = kit("feasibility", kit_example("feasibility"))
    doc = b.build()
    table = [x for x in doc.blocks if x.type == "table"][0]
    assert table.rows[0][1:] == ["2,500,000", "0", "0", "-2,500,000", "-2,500,000"]
    assert table.rows[-2][-2] == "1,514,510" and table.rows[-1][-2] == "35.1%"
    text = " ".join(getattr(x, "text", "") or "" for x in doc.blocks)
    assert "net present value is 1,514,510" in text and "Payback period: 2.2 years." in text
    chart = [x for x in doc.blocks if x.type == "chart"][0]
    assert chart.colors[0] != chart.colors[1] and len(set(chart.colors[1:])) == 1     # the outlay year stands apart
    assert not b.lint()
    with pytest.raises(ValueError, match="feasibility: 'years' needs at least two"):
        kit("feasibility", {**kit_example("feasibility"), "years": [{"year": "2026"}]})


def test_a_numbered_report_does_not_number_its_title():
    b = DocumentBuilder.from_markdown("---\ntitle: Annual review\n---\n\n# Annual review\n\n## Results\n\nText.\n")
    b.design("executive_report")
    doc, _ = b._prepared()
    heads = [x for x in doc.blocks if x.type == "heading"]
    assert (heads[0].hints or {}).get("unnumbered") and not (heads[1].hints or {}).get("unnumbered")


def test_the_page_number_reads_in_the_document_language():
    from dynamic_pdf.i18n import page_format
    assert page_format("Page {n} of {total}", "ar") == "صفحة {n} من {total}"
    assert page_format("Page {n} of {total}", "en") == "Page {n} of {total}" and page_format("{n} / {total}", "ar") == "{n} / {total}"


def test_the_statements_kit_balances_and_reads_like_accounts():
    b = kit("statements", kit_example("statements"))
    tables = [x for x in b.build().blocks if x.type == "table"]
    income = {r[0].strip("*"): r[1] for r in tables[0].rows}
    assert income["Cost of sales"] == "(6,200,000)" and income["Gross profit"] == "4,600,000"
    assert income["Profit for the year"] == "1,834,500"
    assert tables[1].rows[-1][1:] == tables[2].rows[-1][1:] == ["12,350,000", "11,090,000"]
    assert not b.lint()                                   # every total adds up, a one-line section included
    d = kit_example("statements")
    d["position"]["current_assets"][2]["values"] = [1250001, 840000]
    with pytest.raises(ValueError, match="does not balance in 2026: assets 12,350,001 but equity and liabilities 12,350,000"):
        kit("statements", d)


def test_lint_still_catches_a_wrong_one_line_total():
    md = "| Item | 2026 |\n|---|---:|\n| A | 100 |\n| Total A | 100 |\n| B | 50 |\n| Total B | 70 |\n"
    assert [w.rule for w in DocumentBuilder.from_markdown(md).lint()] == ["total_mismatch"]


def test_figures_and_years_do_not_decide_a_table_direction():
    from dynamic_pdf.core.normalize import is_rtl_table
    assert is_rtl_table(["البند", "2026", "2025"]) and not is_rtl_table(["Item", "2026", "2025"])
    assert not is_rtl_table(["Revenue", "الإيرادات", "Notes"]) and not is_rtl_table(["2026", "2025"])


def test_the_certificate_kit():
    import pypdfium2 as pdfium
    b = kit("certificate", kit_example("certificate"))
    pdf = pdfium.PdfDocument(b.render())
    w, h = pdf[0].get_size()
    assert len(pdf) == 1 and w > h                                   # one landscape page
    text = pdf[0].get_textpage().get_text_range()
    assert "Layla Mansour" in text and "Certificate of Completion" in text and "Page" not in text
    lines = _lines(b.render())
    name = next(x for x in lines if x[2] - x[1] > 0 and abs((x[1] + x[2]) / 2 - w / 2) < 3 and x[2] - x[1] > 150)
    assert name                                                      # set in the middle of the page
    ar = kit("certificate", {**kit_example("certificate"), "language": "ar", "recipient": "ليلى", "gender": "f"})
    assert any(x.text == "قد أتمّت بنجاح" for x in ar._blocks if x.type == "rich_text")


def test_large_rich_text_gets_room_for_its_lines():
    lines = _lines(DocumentBuilder().rich_text("Big name", font_size=28, alignment="center")
                   .rich_text("small line under it", alignment="center").design(None).render())
    big, small = lines[0], lines[1]
    assert big[0] - small[0] > 28 * 0.9                              # the lines do not overlap


def test_markdown_quotes_carry_their_style_and_attribution():
    q = DocumentBuilder.from_markdown("> [!pullquote]\n> Big statement.\n> — CEO")._blocks[0]
    assert (q.style, q.text, q.attribution) == ("pullquote", "Big statement.", "CEO")
    q = DocumentBuilder.from_markdown("> A dash - inside is text.")._blocks[0]
    assert (q.style, q.attribution) == ("blockquote", None)
    q = DocumentBuilder.from_markdown("> — only a dash line")._blocks[0]
    assert q.attribution is None                                     # a one-line quote is all quote


def test_each_quote_style_renders_and_mirrors_in_arabic():
    import pypdfium2 as pdfium
    from docx import Document
    for style in ("blockquote", "pullquote", "epigraph"):
        b = DocumentBuilder().paragraph("x").quote("A sentence worth quoting.", attribution="Ada", style=style)
        assert "Ada" in pdfium.PdfDocument(b.render())[0].get_textpage().get_text_range()
        assert b.render_docx()
    docx = Document(io.BytesIO(DocumentBuilder().quote("نص الاقتباس هنا", attribution="كاتب").render_docx()))
    xml = docx.element.xml
    assert "<w:right " in xml and "<w:left w:val=\"single\"" not in xml       # the bar on the right


def _signature_png(tmp_path):
    from PIL import Image, ImageDraw
    im = Image.new("RGBA", (360, 120), (0, 0, 0, 0))
    ImageDraw.Draw(im).line([(10, 90), (60, 20), (120, 90), (200, 30), (340, 60)], fill=(20, 40, 120, 255), width=5)
    path = tmp_path / "sig.png"
    im.save(path)
    return str(path)


def test_signatures_take_a_picture_an_alignment_and_a_row(tmp_path):
    import pypdfium2 as pdfium
    import pypdfium2.raw as raw
    from docx import Document
    sig = _signature_png(tmp_path)
    md = (f'```signature\n{{"name": "Omar Hassan", "title": "Director", "image": "{sig}"}}\n```\n\n'
          '```signatures\n[{"name": "A. One", "alignment": "center"}, {"name": "B. Two"}, {"name": "C. Three"}]\n```\n')
    b = DocumentBuilder.from_markdown(md)
    assert [x.type for x in b._blocks] == ["signature", "three_column"]
    pdf = pdfium.PdfDocument(b.render())
    assert sum(o.type == raw.FPDF_PAGEOBJ_IMAGE for o in pdf[0].get_objects()) == 1
    docx = Document(io.BytesIO(b.render_docx()))
    assert len(docx.inline_shapes) == 1 and len(docx.tables) == 1
    with pytest.raises(ValueError, match="holds JSON"):
        DocumentBuilder.from_markdown("```signature\nname: x\n```\n")
    with pytest.raises(ValueError, match="1 to 4 signatures"):
        DocumentBuilder().signatures([{"name": str(i)} for i in range(5)])


def test_signatures_in_a_row_stand_on_one_line(tmp_path):
    import pypdfium2 as pdfium
    pdf = DocumentBuilder().signatures([{"name": "Left signer", "image": _signature_png(tmp_path)},
                                        {"name": "Right signer"}]).design(None).render()
    tp = pdfium.PdfDocument(pdf)[0].get_textpage()
    y = [tp.get_charbox(tp.search(n).get_next()[0])[1] for n in ("Left signer", "Right signer")]
    assert abs(y[0] - y[1]) < 1                                      # both names on one baseline


def _logo(tmp_path):
    from PIL import Image
    path = tmp_path / "logo.png"
    Image.new("RGB", (300, 100), "#E07A1F").save(path)
    return str(path)


def test_header_presets_from_front_matter(tmp_path):
    import pypdfium2 as pdfium
    from dynamic_pdf.schema.page_system import PRESETS
    for name in PRESETS:
        md = (f"---\ntitle: Review\nheader: {name}\nlogo: {_logo(tmp_path)}\ncompany: Nile Co.\n"
              "confidentiality: Internal\n---\n\n# Review\n\n" + "Text. " * 50)
        b = DocumentBuilder.from_markdown(md)
        assert b._meta.page_system is not None and b._meta.page_system.values["company"] == "Nile Co."
        text = pdfium.PdfDocument(b.render())[0].get_textpage().get_text_range()
        assert "{" not in text                                      # every field filled or dropped
        assert b.render_docx()
    with pytest.raises(ValueError, match="presets: letterhead"):
        DocumentBuilder().page_system("fancy")


def test_band_colours_follow_the_theme_by_name():
    from dynamic_pdf.schema.page_system import preset, themed
    from dynamic_pdf.themes import get_theme
    colors = get_theme("claude").colors
    system = themed(preset("modern", company="X"), colors)
    assert system.header.rows[0].rule_color == colors.accent and system.footer.accent_color == colors.border
    assert themed(preset("banner"), colors).header.rows[0].fill == colors.primary


def test_an_arabic_band_keeps_its_title_whole_and_its_logo_first(tmp_path):
    from dynamic_pdf.layout import page_system as P
    seen = []
    orig = P.BandMaker._cell

    def spy(self, items, *a, **k):
        cell = orig(self, items, *a, **k)
        if cell.logos:
            seen.append(cell)
        return cell
    P.BandMaker._cell = spy
    try:
        DocumentBuilder.from_markdown(f"---\ntitle: المراجعة الربعية\nlanguage: ar\nheader: modern\nlogo: {_logo(tmp_path)}\n"
                                      "---\n\n# المراجعة الربعية\n\n" + "نص طويل. " * 900).render()
    finally:
        P.BandMaker._cell = orig
    assert seen and all(c.rtl for c in seen) and all(len(c.lines) <= 1 for c in seen)   # never broken in two


def test_a_letterhead_gives_later_pages_back_their_room(tmp_path):
    import pypdfium2 as pdfium
    md = (f"---\ntitle: Review\nheader: letterhead\nlogo: {_logo(tmp_path)}\ncompany: Nile Co.\n"
          "website: nile.example\n---\n\n# Review\n\n" + "Body text of the letter. " * 700)
    pdf = pdfium.PdfDocument(DocumentBuilder.from_markdown(md).render())

    def first_body_line(i):
        tp = pdf[i].get_textpage()
        return max(tp.get_charbox(k)[3] for k in range(tp.count_chars())
                   if tp.get_text_range(k, 1).strip() and "Body" in tp.get_text_range(max(0, k - 3), 8))
    assert len(pdf) >= 2 and first_body_line(1) > first_body_line(0) + 20     # a small header after page one


def test_bands_share_the_text_columns_edges(tmp_path):
    import pypdfium2 as pdfium
    md = "---\ntitle: Review\nheader: report\ncompany: Nile Co.\n---\n\n# Review\n\n" + "Body text here. " * 400
    pdf = pdfium.PdfDocument(DocumentBuilder.from_markdown(md).render())
    tp = pdf[1].get_textpage()
    title_x = tp.get_charbox(tp.search("Review").get_next()[0])[0]
    body_x = min(tp.get_charbox(k)[0] for k in range(tp.count_chars()) if tp.get_text_range(k, 1).strip())
    assert abs(title_x - body_x) < 1.5


def test_a_kit_logo_goes_where_the_document_wants_it(tmp_path):
    logo = _logo(tmp_path)
    letter = kit("letter", {**kit_example("letter"), "logo": logo})
    ps = letter._meta.page_system
    assert ps.first_header.rows[0].start[0].src == logo and ps.values["company"] == "Nile Office Supplies"
    assert ps.values["address"] == "King Fahd Road, Riyadh 12271"
    assert not any("King Fahd" in (getattr(b, "text", "") or "") for b in letter._blocks)   # not twice
    assert kit("invoice", {**kit_example("invoice"), "logo": logo})._meta.page_system is not None
    assert kit("cv", {**kit_example("cv"), "logo": logo})._meta.page_system.header is None   # ATS: no header
    cert = kit("certificate", {**kit_example("certificate"), "logo": logo})
    assert any(b.type == "image" and b.src == logo for b in cert._blocks)


def test_a_front_matter_logo_alone_brings_a_header(tmp_path):
    logo = _logo(tmp_path)
    b = DocumentBuilder.from_markdown(f"---\ntitle: T\nlogo: {logo}\n---\n\n# T\n\nText.\n")
    assert b._meta.page_system is not None and b._meta.page_system.first_page == "custom"
    letter = DocumentBuilder.from_markdown(f"---\ntitle: T\nlogo: {logo}\ndocument_type: letter\n---\n\nDear Sir,\n")
    assert len(letter._meta.page_system.first_header.rows) == 3                # the letterhead


def test_a_certificate_has_a_frame_and_stays_on_one_page(tmp_path):
    import pypdfium2 as pdfium
    ar = {**kit_example("certificate"), "language": "ar", "logo": _logo(tmp_path), "recipient": "ليلى منصور",
          "organisation": "أكاديمية النيل للتدريب", "achievement": "النمذجة المالية للمديرين",
          "signatures": [{"name": "عمر حسن", "title": "مدير البرنامج"}, {"name": "سارة أحمد", "title": "العميدة"}]}
    for data in (kit_example("certificate"), ar):
        b = kit("certificate", data)
        assert b._blocks[0].type == "page_media" and b._blocks[0].src.startswith("data:image/png")
        assert len(pdfium.PdfDocument(b.render())) == 1
    assert kit("certificate", {**kit_example("certificate"), "frame": False})._blocks[0].type != "page_media"


def test_a_built_cover_takes_the_title_off_the_next_page():
    md = "---\ntitle: Annual review\n---\n\n# Annual review\n\n## Results\n\n" + "Revenue rose in every region. " * 600
    b = DocumentBuilder.from_markdown(md).design("executive_report")
    blocks = b._prepared()[0].blocks
    assert blocks[0].type == "cover_page"
    assert [x.text for x in blocks if x.type == "heading"][0] == "Results"       # the title is on the cover only


def test_symbols_and_emoji_draw_and_copy_out_intact():
    import pypdfium2 as pdfium
    b = DocumentBuilder().heading("Launch 🚀 done ✅").paragraph(
        "Stars ★☆ ☐ ₹ and **bold 😀 🎉** thumbs 👍🏽 heart ❤️ family 👨‍👩‍👧.").paragraph("علامة ™ ونجمة ★ و 😀 في نص عربي")
    text = pdfium.PdfDocument(b.render())[0].get_textpage().get_text_range()
    for ch in "🚀✅★☆☐₹😀🎉👍❤👨👩👧":
        assert ch in text, ch                                   # drawn by a font that has it, and extracted as itself
    assert "️" not in text and "\U0001F3FD" not in text      # what would draw as a box is left out
    from dynamic_pdf.layout.factory import _glyph_fallback
    assert "‍" in _glyph_fallback("می‍خواهم")           # a joiner in Persian text is kept


def test_a_character_no_font_draws_is_reported(tmp_path):
    r = DocumentBuilder().paragraph("Hieroglyph 𓀀 here.").review(str(tmp_path / "r"), dpi=30)
    assert not r["passed"] and any(i["code"] == "missing_glyph" for i in r["issues"])


def test_a_cover_from_the_front_matter_is_a_bare_designed_page(tmp_path):
    import pypdfium2 as pdfium
    md = (f"---\ntitle: Annual Report 2026\nsubject: Growth\nauthor: Finance\ndate: November 2026\nlogo: {_logo(tmp_path)}\n"
          "cover: split\ncover_color: \"#1B365D\"\n---\n\n# Results\n\nText.\n")
    b = DocumentBuilder.from_markdown(md)
    cover = b._blocks[0]
    assert (cover.type, cover.layout, cover.background_color, cover.date) == ("cover_page", "split", "#1B365D", "November 2026")
    pdf = pdfium.PdfDocument(b.render())
    text = pdf[0].get_textpage().get_text_range()
    assert "Annual" in text and "Page" not in text and "/" not in text            # no header or footer on the cover
    tp = pdf[0].get_textpage()
    title_h = tp.get_charbox(tp.search("Annual").get_next()[0])
    assert title_h[3] - title_h[1] > 18                                           # the largest type in the document
    assert b.render_docx()
    plain = DocumentBuilder().cover_page("Plain cover").paragraph("x")
    assert "Page" not in pdfium.PdfDocument(plain.render())[0].get_textpage().get_text_range()


def test_preface_and_conclusion_pages_in_both_languages():
    import pypdfium2 as pdfium
    md = "---\nlanguage: ar\n---\n\n:::preface\nنص التمهيد هنا.\n:::\n\n# النتائج\n\nنص.\n\n:::conclusion خلاصة القول\nنص الخاتمة.\n:::\n"
    b = DocumentBuilder.from_markdown(md)
    pages = [x for x in b._blocks if x.type == "introduction_page"]
    assert [(x.title, x.position) for x in pages] == [("تمهيد", "front"), ("خلاصة القول", "back")]
    pdf = pdfium.PdfDocument(b.render())
    assert len(pdf) == 3                                                          # each on a page of its own
    lines = _lines(b.render())
    assert max(r for _, _, r in lines[1:3]) > 400                                 # set from the right
    en = DocumentBuilder().preface_page("Why this report.").heading("Body").conclusion_page("What next.")
    assert [x.title for x in en._blocks if x.type == "introduction_page"] == ["Preface", "Conclusion"]
    assert en.render_docx()


def test_maps_sketches_and_mind_maps_draw_in_pdf_and_word():
    import pypdfium2 as pdfium
    square = [[30, 30], [31, 30], [31, 31], [30, 31], [30, 30]]
    gj = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"name": "North"}, "geometry": {"type": "Polygon", "coordinates": [square]}},
        {"type": "Feature", "properties": {"name": "South"},
         "geometry": {"type": "Polygon", "coordinates": [[[x, y - 1] for x, y in square]]}}]}
    b = DocumentBuilder()
    b.chart("map", {"geojson": gj, "values": {"North": 3, "South": 9}, "points": [{"name": "Depot", "lon": 30.5, "lat": 30.2}]},
            title="Sales by region")
    b.chart("sketch", {"roads": [{"name": "شارع التحرير", "points": [[0, 5], [10, 5]]}],
                       "places": [{"name": "مكتبنا", "at": [6, 4], "kind": "site"}], "north": 0}, title="كروكي الموقع")
    b.chart("mindmap", {"Strategy": {"Growth": ["Markets", "Pricing"], "Costs": ["Suppliers"]}})
    pdf = pdfium.PdfDocument(b.render())                                 # chart text is drawn as outlines
    inked = sum(1 for pg in pdf for px in pg.render(scale=0.3).to_pil().convert("L").getdata() if px < 200)
    assert len(pdf) <= 3 and inked > 1500                                # three drawings, each within its page
    from docx import Document
    assert len(Document(io.BytesIO(b.render_docx())).inline_shapes) == 3 and not b.lint()
    md = '```chart\n{"type": "mindmap", "data": {"Plan": {"A": ["x"], "B": []}}}\n```\n'
    assert DocumentBuilder.from_markdown(md)._blocks[0].chart_type == "mindmap"
    for bad, say in (({"geojson": {"type": "FeatureCollection", "features": []}}, "nothing to draw"),):
        with pytest.raises(Exception, match=say):
            DocumentBuilder().chart("map", bad).render()
    with pytest.raises(Exception, match="one topic"):
        DocumentBuilder().chart("mindmap", {"A": {}, "B": {}}).render()


def test_shapes_are_shapes_in_word_and_labels_read():
    import pypdfium2 as pdfium
    from docx import Document
    from dynamic_pdf.layout.factory import _safe_color
    assert _safe_color("#fff").hexval() == "0xffffff"                    # not 0x000fff
    b = DocumentBuilder().shape("circle", width=60, height=60, fill_color="#E53E3E", label="A").shape(
        "rounded_rect", width=250, height=60, fill_color="#F7FAFC", label="حالة: نشط ✓")
    assert "A" in pdfium.PdfDocument(b.render())[0].get_textpage().get_text_range()
    docx = Document(io.BytesIO(b.render_docx()))
    assert len(docx.inline_shapes) == 2 and not docx.tables               # pictures of the shapes, not table cells
