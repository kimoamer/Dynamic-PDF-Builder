"""Slot-based headers and footers, in both renderers."""
import io
import re
import zipfile

import pymupdf
import pytest
from PIL import Image

from dynamic_pdf import DocumentBuilder
from dynamic_pdf.layout.page_system import fill_fields
from dynamic_pdf.schema.page_system import Band, BandRow, Logo, PageSystem, SectionBands, settled

BODY = "The harbour authority surveyed every berth during the winter closure and logged each mooring. " * 6


@pytest.fixture
def logo(tmp_path):
    path = tmp_path / "logo.png"
    Image.new("RGBA", (600, 200), (20, 96, 122, 255)).save(path)
    return str(path)


def built(system, pages=3, cover=False, language="en", text=BODY):
    b = DocumentBuilder()
    b.meta(title="Tide Book", language=language)
    b.page_system(system)
    if cover:
        b.cover_page("Tide Book", background_color="#16324a")
    for n in range(pages):
        b.heading(f"Part {n + 1}", level=1)
        for _ in range(7):
            b.paragraph(text)
    return b


def pdf_of(b):
    return pymupdf.open(stream=b.render_bytes(), filetype="pdf")


def parts(b):
    with zipfile.ZipFile(io.BytesIO(b.render_docx())) as z:
        return {n: z.read(n).decode("utf-8", "replace") for n in z.namelist() if n.endswith((".xml", ".rels"))}


def headers(p, kind="header"):
    return [v for n, v in sorted(p.items()) if re.match(rf"word/{kind}\d*\.xml$", n)]


def top_text(page, depth=70):
    return " ".join(w[4] for w in page.get_text("words") if w[3] < depth)


def bottom_text(page, depth=70):
    return " ".join(w[4] for w in page.get_text("words") if w[1] > page.rect.height - depth)


def test_fields_fill_and_unset_ones_leave_no_braces():
    assert fill_fields("{title} / {nope}", {"title": "A"}) == "A /"


def test_slots_land_where_they_say():
    s = PageSystem(header=Band(rows=[BandRow(left=["LEFTSLOT"], center=["MIDSLOT"], right=["RIGHTSLOT"])]))
    page = pdf_of(built(s))[1]
    x = {w[4]: w[0] for w in page.get_text("words")}
    assert x["LEFTSLOT"] < page.rect.width * .3
    assert page.rect.width * .35 < x["MIDSLOT"] < page.rect.width * .55
    assert x["RIGHTSLOT"] > page.rect.width * .6


def test_start_and_end_swap_in_arabic():
    s = PageSystem(header=Band(rows=[BandRow(start=["BEGIN"], end=["FINISH"])]))
    arabic = "أنجزت هيئة الميناء مسح الأرصفة خلال فصل الشتاء. " * 10
    page = pdf_of(built(s, language="ar", text=arabic))[1]
    x = {w[4]: w[0] for w in page.get_text("words")}
    assert x["BEGIN"] > x["FINISH"]


def test_page_numbers_are_live_fields_in_word():
    s = PageSystem(footer=Band(rows=[BandRow(right=["Page {page} of {pages}"])]))
    b = built(s)
    assert "Page 2 of" in pdf_of(b)[1].get_text().replace("\n", " ")
    footer = "".join(headers(parts(b), "footer"))
    assert " PAGE " in footer and " NUMPAGES " in footer


def test_running_title_follows_the_headings():
    s = PageSystem(header=Band(rows=[BandRow(right=["{chapter}"])]))
    b = built(s)
    doc = pdf_of(b)
    assert "Part 1" in top_text(doc[0]) and "Part 3" in top_text(doc[doc.page_count - 1])
    assert 'STYLEREF "Heading 1"' in "".join(headers(parts(b)))


def test_first_page_is_clean_after_a_cover_but_kept_without_one():
    s = PageSystem(header=Band(rows=[BandRow(left=["RUNNING"])]))
    assert settled(s, []).first_page == "same"
    assert "RUNNING" in top_text(pdf_of(built(s))[0])
    doc = pdf_of(built(s, cover=True))
    assert "RUNNING" not in doc[0].get_text() and "RUNNING" in top_text(doc[1])
    assert "<w:titlePg" in parts(built(s, cover=True))["word/document.xml"]


def test_odd_and_even_pages_differ():
    s = PageSystem(header=Band(rows=[BandRow(left=["ODDPAGE"])]), even_header=Band(rows=[BandRow(left=["EVENPAGE"])]),
                   first_page="same")
    b = built(s)
    doc = pdf_of(b)
    assert "ODDPAGE" in top_text(doc[0]) and "EVENPAGE" in top_text(doc[1]) and "ODDPAGE" in top_text(doc[2])
    p = parts(b)
    assert "evenAndOddHeaders" in p["word/settings.xml"]
    assert 'w:type="even"' in p["word/document.xml"]


def test_section_bands_replace_the_running_ones():
    s = PageSystem(header=Band(rows=[BandRow(left=["MAINBAND"])]),
                   sections={"annex": SectionBands(header=Band(rows=[BandRow(left=["ANNEXBAND"])]))}, first_page="same")
    b = DocumentBuilder()
    b.page_system(s)
    b.paragraph("Main")
    b.page_section("annex")
    b.paragraph("Annex")
    doc = pdf_of(b)
    assert "MAINBAND" in top_text(doc[0]) and "ANNEXBAND" in top_text(doc[1])
    joined = headers(parts(b))
    assert any("MAINBAND" in h for h in joined) and any("ANNEXBAND" in h for h in joined)


def test_dense_band_pushes_the_body_down_and_never_overlaps_it(logo):
    s = PageSystem(header=Band(rows=[
        BandRow(start=[Logo(src=logo, max_height=26)], center=["Title line", "Second line"], end=["{date}", "Ref {code}"],
                rule_below=True),
        BandRow(start=["Period"], center=["Department"], end=["Code"], size=7)]),
        values={"date": "Nov 2026", "code": "SHA-1"})
    page = pdf_of(built(s))[0]
    band_bottom = max(w[3] for w in page.get_text("words") if w[4] in ("Period", "Department", "Code"))
    body_top = min(w[1] for w in page.get_text("words") if w[4] == "Part")
    assert body_top >= band_bottom


def test_logo_keeps_its_shape_within_its_limits(logo):
    s = PageSystem(header=Band(rows=[BandRow(left=[Logo(src=logo, max_height=20, max_width=40)])]))
    b = built(s, pages=1)
    box = pdf_of(b)[0].get_image_info()[0]["bbox"]
    assert (box[2] - box[0]) / (box[3] - box[1]) == pytest.approx(3, rel=.02)
    assert box[2] - box[0] <= 40.5
    assert "<pic:pic" in "".join(headers(parts(b)))


def test_text_too_long_for_its_slot_is_reported_not_overprinted():
    long = "A very long running title that cannot possibly fit into the narrow slot it was given " * 4
    s = PageSystem(header=Band(rows=[BandRow(left=[long], right=["x" * 40], max_lines=1)]))
    b = built(s, pages=1)
    with pytest.warns(RuntimeWarning, match="band_overflow"):
        b.render_bytes()


def test_arabic_band_table_reads_right_to_left_in_word():
    s = PageSystem(header=Band(rows=[BandRow(start=["بداية"], end=["نهاية"])]))
    assert "bidiVisual" in "".join(headers(parts(built(s, language="ar", text="نص عربي للتجربة " * 40))))


def test_band_text_stays_text_in_word(logo):
    s = PageSystem(header=Band(rows=[BandRow(left=["Saltmere"], right=[Logo(src=logo)])]))
    assert "<w:t" in "".join(headers(parts(built(s, pages=1))))
