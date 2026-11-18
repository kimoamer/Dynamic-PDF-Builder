"""The themes that are complete looks: they differ in structure, colour and type, and each one
passes the hard gates in English and Arabic."""
import colorsys
import itertools

import pytest

from dynamic_pdf import DocumentBuilder
from dynamic_pdf.design.art_direction import _section_level
from dynamic_pdf.design.looks import LOOKS
from dynamic_pdf.fonts import list_font_families
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
    bundled = set(list_font_families()) | {"Amiri"}
    for x in looks:
        d = x.direction
        assert {d.heading_family, d.body_family, d.arabic_family} <= bundled, x.id
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
