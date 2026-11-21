"""The themes that are complete looks: they differ in structure, colour and type, and each one
passes the hard gates in English and Arabic."""
import colorsys
import itertools

import pytest

from dynamic_pdf import DocumentBuilder
from dynamic_pdf.design.art_direction import _section_level
from dynamic_pdf.design.looks import LOOKS
from dynamic_pdf.fonts import font_catalog
from dynamic_pdf.schema.blocks import HeadingBlock, ParagraphBlock
from dynamic_pdf.utils.color import contrast_ratio, hex_to_rgb

EN = """---
title: Annual Review 2026
subject: Growth across every region
author: Finance department
---

# Annual Review 2026

## Highlights

Revenue grew in every region this year, led by the north, while costs held below plan.

> Growth this year came from customers we already had.
> — Chief Executive

## Results by region

| Region | Revenue | Change |
|---|---:|---:|
| North | 18.4 | +16% |
| East | 12.1 | +11% |
| Total | 30.5 | +14% |

:::tip
Orders booked for the first quarter already cover 70% of its plan.
:::

## Outlook

We expect steady growth next year.

### Risks

- Energy prices may rise faster than planned.
- Two large contracts renew in the second half.
"""

AR = """---
title: المراجعة السنوية 2026
subject: نمو في كل المناطق
author: الإدارة المالية
---

# المراجعة السنوية 2026

## أبرز النتائج

نمت الإيرادات في كل المناطق هذا العام بقيادة الشمال، وبقيت التكاليف دون الخطة.

> جاء نمو هذا العام من عملائنا الحاليين.
> — الرئيس التنفيذي

## النتائج حسب المنطقة

| المنطقة | الإيرادات | التغير |
|---|---:|---:|
| الشمال | 18.4 | +16% |
| الشرق | 12.1 | +11% |
| الإجمالي | 30.5 | +14% |

## التوقعات

نتوقع نموًا مستقرًا في العام القادم.

- رفع الهامش نقطة واحدة.
- تقصير دورة النقد عشرة أيام.
"""


def _hue(color):
    h, s, _ = colorsys.rgb_to_hsv(*(v / 255 for v in hex_to_rgb(color)))
    return h * 360, s


def test_no_two_looks_share_a_structure():
    looks = list(LOOKS.values())
    assert len(looks) == 8
    assert len({x.structure for x in looks}) == len(looks)
    for part in ("cover", "bands"):                        # what a reader sees first, and on every page
        assert len({getattr(x.direction, part) for x in looks}) == len(looks), part
    mastheads = [x.direction.masthead for x in looks if x.direction.cover != "title_block"]
    assert len(set(mastheads)) == len(mastheads)
    for a, b in itertools.combinations(looks, 2):          # any two differ in most of what they are made of
        assert sum(p != q for p, q in zip(a.structure, b.structure)) >= 4, (a.id, b.id)


def test_no_two_looks_share_a_hue_or_a_face():
    looks = list(LOOKS.values())
    coloured = [x for x in looks if _hue(x.primary)[1] > 0.2]
    assert len(coloured) == len(looks) - 1                 # the paper is black
    for a, b in itertools.combinations(coloured, 2):
        d = abs(_hue(a.primary)[0] - _hue(b.primary)[0])
        assert min(d, 360 - d) >= 30, (a.id, b.id)
    for part in ("heading_family", "arabic_family"):
        assert len({getattr(x.direction, part) for x in looks}) == len(looks), part
    embeddable = set(font_catalog())                       # the faces Word gets inside the file
    for x in looks:
        d = x.direction
        assert {d.heading_family, d.body_family, d.arabic_family} <= embeddable, x.id
        assert contrast_ratio(x.primary, "#FFFFFF") >= 4.5, x.id       # white type reads on the colour


@pytest.mark.parametrize("name", list(LOOKS))
@pytest.mark.parametrize("source", [EN, AR], ids=["en", "ar"])
def test_look_is_delivered_and_passes_the_gates(name, source):
    b = DocumentBuilder.from_markdown(source).theme(name)
    variant = b._variant_set().variants[0]
    assert variant.valid, variant.report.hard_failures     # otherwise the classic look would be delivered
    assert b.render()[:4] == b"%PDF"


@pytest.mark.parametrize("name", list(LOOKS))
def test_look_exports_to_word(name, tmp_path):
    out = tmp_path / "look.docx"
    DocumentBuilder.from_markdown(EN).theme(name).export(str(out))
    assert out.stat().st_size > 5000


def test_theme_in_front_matter_and_brand_over_look():
    from dynamic_pdf.design.brand import BrandKit
    b = DocumentBuilder.from_markdown(EN.replace("title:", "theme: tech\ntitle:", 1))
    assert b._look().id == "tech" and b._kit().primary == LOOKS["tech"].primary
    b.design(brand=BrandKit(primary="#005A9C"))
    assert b._kit().primary == "#005A9C"                    # the caller's colours win; the structure stays
    assert b._request()["families"] == [LOOKS["tech"].direction]


def test_sections_are_read_under_a_title_heading():
    def h(level):
        return HeadingBlock(text="x", level=level)
    assert _section_level([h(1), h(2), h(2), h(3)]) == 2    # "# Title" over "## Section"
    assert _section_level([h(1), h(2), h(1)]) == 1
    assert _section_level([h(2), h(2)]) == 2
    assert _section_level([ParagraphBlock(text="x")]) == 1


def test_heading_is_kept_with_the_list_under_it():
    import pypdfium2 as pdfium
    for gap in range(300, 680, 4):                         # the heading at every height down the page
        b = DocumentBuilder().design(None).paragraph("Opening line.").spacer(gap)
        b.heading("Tail heading", 3).bullet_list([f"entry {i} under the heading" for i in range(4)])
        pdf = pdfium.PdfDocument(b.render())
        pages = [pdf[i].get_textpage().get_text_range() for i in range(len(pdf))]
        head = next(i for i, t in enumerate(pages) if "Tail heading" in t)
        assert "entry 0 under the heading" in pages[head], gap


def _docx(name, source=EN):
    import io
    import docx
    return docx.Document(io.BytesIO(DocumentBuilder.from_markdown(source).theme(name).render_docx()))


@pytest.mark.parametrize("name", ["civic", "magazine", "executive", "ledger"])
def test_word_running_title_names_a_style_its_headings_use(name):
    import re
    d = _docx(name)
    used = {p.style.name for p in d.paragraphs}
    for s in d.sections:
        for part in (s.header, s.footer, s.even_page_header, s.even_page_footer, s.first_page_header):
            for ref in re.findall(r'STYLEREF "([^"]+)"', part._element.xml):
                assert ref in used, (name, ref)      # otherwise Word prints "Reference source not found"


def test_word_hang_and_rule_live_in_the_heading_style():
    d = _docx("magazine")
    head = next(p for p in d.paragraphs if p.text == "Highlights")
    assert head.style.paragraph_format.left_indent.pt < -20           # LibreOffice drops a paragraph's own
    assert "w:pBdr" in head.style.element.xml


def test_word_pictures_and_charts_sit_on_single_lines():
    chart = '\n```chart\n{"type": "bar", "data": {"North": 18.4, "East": 12.1}}\n```\n'
    d = _docx("magazine", EN.replace("## Outlook", chart + "\n## Outlook"))
    holders = [p for p in d.paragraphs if p._p.xpath(".//w:drawing")]
    assert holders and all(p.paragraph_format.line_spacing == 1.0 for p in holders)


def test_word_chart_axis_reaches_above_the_tallest_bar():
    from dynamic_pdf.renderers.docx_chart import _ceiling
    assert _ceiling({"": [18.4, 12.1, 9.6, 8.1]}, False) == 20
    assert _ceiling({"a": [3, 4], "b": [2, 2]}, True) == 7
    assert _ceiling({"": [-3.0]}, False) is None


def test_word_keeps_a_short_list_on_one_page():
    import io
    import docx
    d = docx.Document(io.BytesIO(DocumentBuilder().numbered_list(["one", "two", "three"]).render_docx()))
    items = [p for p in d.paragraphs if p.text in ("one", "two", "three")]
    assert [bool(p.paragraph_format.keep_with_next) for p in items] == [True, True, False]


def test_runs_of_one_arabic_line_are_not_an_overlap():
    from dynamic_pdf.qa.pdf_checks import _runs_of_one_line
    line = ((63.8, 247.7, 310.4, 263.4), "واستبدلت", 10.0)
    end = ((68.1, 247.7, 167.5, 264.7), "البالية", 10.0)        # same top, marks reach lower
    tail = ((68.0, 106.0, 89.0, 124.0), "مرسى.", 10.0)
    whole = ((64.0, 100.0, 527.0, 124.0), "أنجزت", 10.0)         # same bottom, marks reach higher
    assert _runs_of_one_line(line, end) and _runs_of_one_line(tail, whole)
    below = ((64.0, 112.0, 527.0, 136.0), "سطر آخر", 10.0)       # a different line half a line down
    assert not _runs_of_one_line(whole, below)
    word = ((100.3, 103.3, 242.3, 124.9), "مركز", 10.0)           # a voweled word mid-line: its own run
    assert _runs_of_one_line(word, whole)
    offset = ((68.2, 61.1, 193.2, 82.7), "أنجزت", 10.0)          # its box shifted by the marks
    assert _runs_of_one_line(offset, ((63.8, 58.1, 527.4, 81.0), "سطر", 10.0))
    half = ((64.0, 111.0, 300.0, 135.0), "سطر", 10.0)            # half a line lower: an overlap
    assert not _runs_of_one_line(half, whole)
