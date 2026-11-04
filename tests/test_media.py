"""The media model: asset handling, placement, and both renderers. Images are drawn
here; nothing third-party is involved."""
import io
import re
import warnings
import zipfile

import pymupdf
import pytest
from PIL import Image

from dynamic_pdf import DocumentBuilder
from dynamic_pdf.assets import AssetPolicy
from dynamic_pdf.media import (MediaAsset, PageGeometry, check_resolution, effective_dpi, fit_image, flow_box,
                               ingest, normal_mode, page_position, physical_side, raster_bytes)
from dynamic_pdf.policy import DiagnosticCollector, RenderPolicy
from dynamic_pdf.qa.media_checks import check_docx_media, check_pdf_media, docx_media_summary
from dynamic_pdf.schema.media import ImageTreatment, MediaPlacement, resolve_placement
from dynamic_pdf.svg_safe import sanitise
from dynamic_pdf.utils.errors import DynamicPDFError

TEXT = ("The harbour authority surveyed every berth during the winter closure and logged the "
        "state of each mooring along the quay. ") * 5
SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100" width="200" height="100">'
       '<rect width="200" height="100" fill="#14607a"/></svg>')


@pytest.fixture
def photo(tmp_path):
    path = tmp_path / "photo.png"
    image = Image.new("RGB", (800, 400), (30, 90, 130))
    image.paste((230, 170, 80), (600, 0, 800, 400))
    image.save(path)
    return str(path)


@pytest.fixture
def logo(tmp_path):
    path = tmp_path / "logo.png"
    image = Image.new("RGBA", (600, 200), (0, 0, 0, 0))
    image.paste((20, 96, 122, 255), (20, 20, 580, 180))
    image.save(path)
    return str(path)


def pdf_of(b):
    return pymupdf.open(stream=b.render_bytes(), filetype="pdf")


def docx_parts(data):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return {n: z.read(n) for n in z.namelist()}


def doc_with(*images, paragraphs=6):
    b = DocumentBuilder()
    b.heading("Quay", level=1)
    for call in images:
        call(b)
    for _ in range(paragraphs):
        b.paragraph(TEXT)
    return b


# ─── assets ───

def test_identical_bytes_share_one_asset(photo):
    policy = AssetPolicy()
    assert ingest(photo, policy) is ingest(photo, policy)


def test_exif_orientation_is_applied(tmp_path):
    path = tmp_path / "turned.jpg"
    exif = Image.Exif()
    exif[0x0112] = 6                               # rotate 90 degrees to display
    Image.new("RGB", (400, 200), "red").save(path, exif=exif)
    asset = ingest(str(path), AssetPolicy())
    assert (asset.width, asset.height) == (200, 400)


@pytest.mark.parametrize("mode,ext", [("RGB", "webp"), ("CMYK", "jpg"), ("P", "png"), ("LA", "png")])
def test_formats_become_drawable_raster(tmp_path, mode, ext):
    path = tmp_path / f"x.{ext}"
    Image.new(mode, (64, 32)).save(path)
    asset = ingest(str(path), AssetPolicy())
    with Image.open(io.BytesIO(raster_bytes(asset))) as image:
        assert image.format in ("PNG", "JPEG")
        assert image.mode in ("RGB", "RGBA", "L", "LA", "P")
        assert image.size == (64, 32)


def test_transparency_is_kept(logo):
    asset = ingest(logo, AssetPolicy())
    assert asset.has_alpha
    with Image.open(io.BytesIO(raster_bytes(asset))) as image:
        assert image.getchannel("A").getextrema()[0] == 0


def test_corrupted_file_is_refused(tmp_path):
    path = tmp_path / "bad.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\nnot an image")
    with pytest.raises(DynamicPDFError):
        ingest(str(path), AssetPolicy())


def test_decoded_pixel_limit_is_enforced(tmp_path):
    path = tmp_path / "big.png"
    Image.new("L", (300, 300)).save(path)
    with pytest.raises(DynamicPDFError):
        ingest(str(path), AssetPolicy(max_pixels=1000))


def test_file_size_limit_is_enforced(photo):
    with pytest.raises(DynamicPDFError):
        ingest(photo, AssetPolicy(max_bytes=10))


def test_remote_is_refused_without_permission():
    with pytest.raises(DynamicPDFError):
        ingest("https://example.invalid/a.png", AssetPolicy())


def test_low_resolution_is_reported(tmp_path):
    path = tmp_path / "small.png"
    Image.new("RGB", (100, 50)).save(path)
    asset = ingest(str(path), AssetPolicy())
    fitted = fit_image(asset, 400, 200)
    assert effective_dpi(asset, fitted) == pytest.approx(18, abs=1)
    collector = DiagnosticCollector(RenderPolicy())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        check_resolution(asset, fitted, collector, "Image")
    assert [d.code for d in collector.items] == ["image_low_resolution"]


# ─── SVG ───

@pytest.mark.parametrize("bad", [
    '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
    '<!DOCTYPE svg [<!ENTITY x "y">]><svg xmlns="http://www.w3.org/2000/svg"/>',
    '<svg xmlns="http://www.w3.org/2000/svg"><foreignObject/></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">'
    '<image xlink:href="http://example.invalid/a.png"/></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg" onload="x()"/>',
    '<svg xmlns="http://www.w3.org/2000/svg"><rect style="fill:url(http://example.invalid/a)"/></svg>',
])
def test_unsafe_svg_is_refused(bad):
    with pytest.raises(DynamicPDFError):
        sanitise(bad.encode(), AssetPolicy(), "test.svg")


def test_svg_stays_vector_in_pdf_and_gets_both_forms_in_docx(tmp_path):
    path = tmp_path / "mark.svg"
    path.write_text(SVG, encoding="utf-8")
    b = doc_with(lambda b: b.image(str(path), width=200), paragraphs=1)
    page = pdf_of(b)[0]
    assert not page.get_images() and page.get_drawings()
    parts = docx_parts(b.render_docx())
    names = [n for n in parts if n.startswith("word/media/")]
    assert any(n.endswith(".svg") for n in names) and any(n.endswith(".png") for n in names)
    assert b"svgBlip" in parts["word/document.xml"]
    assert b'Extension="svg"' in parts["[Content_Types].xml"] or b"image/svg+xml" in parts["[Content_Types].xml"]


# ─── geometry ───

def test_cover_crops_to_the_focal_point_and_contain_does_not(photo):
    asset = ingest(photo, AssetPolicy())
    whole = fit_image(asset, 200, 200, ImageTreatment(fit="contain"))
    assert (round(whole.width), round(whole.height)) == (200, 100) and not any(whole.crop)
    left = fit_image(asset, 200, 200, ImageTreatment(fit="cover", focal_x=0))
    right = fit_image(asset, 200, 200, ImageTreatment(fit="cover", focal_x=1))
    assert (left.width, left.height) == (200, 200)
    assert left.crop[0] == 0 and left.crop[2] == pytest.approx(.5)
    assert right.crop[2] == 0 and right.crop[0] == pytest.approx(.5)


def test_flow_box_keeps_shape_when_limited(photo):
    asset = ingest(photo, AssetPolicy())
    assert flow_box(asset, 1000, None, 400, None) == (400, 200)
    assert flow_box(asset, 400, None, 400, 100) == (200, 100)


def test_reading_sides_mirror_for_rtl():
    assert physical_side("start", False) == "left" and physical_side("start", True) == "right"
    assert physical_side("end", True) == "left" and physical_side("left", True) == "left"
    geo = PageGeometry(600, 800, 50, 70, 40, 60, True)
    p = MediaPlacement(relative_to="margins", horizontal="start")
    assert page_position(geo, p, 100, 100)[0] == 600 - 70 - 100


def test_wrap_choice_decides_the_mode():
    assert normal_mode(MediaPlacement(mode="anchored", wrap="square")) == "floating"
    assert normal_mode(MediaPlacement(mode="anchored", wrap="top_bottom")) == "inline"
    assert normal_mode(resolve_placement("behind_text")) == "behind_text"


# ─── old behaviour that was incomplete ───

def test_image_height_is_honoured_in_both_formats(photo):
    b = doc_with(lambda b: b.image(photo, width=300, height=90, treatment=ImageTreatment(fit="cover")), paragraphs=1)
    box = pdf_of(b)[0].get_image_info()[0]["bbox"]
    assert box[3] - box[1] == pytest.approx(90, abs=1)
    xml = docx_parts(b.render_docx())["word/document.xml"].decode()
    cy = int(re.search(r'<wp:extent cx="\d+" cy="(\d+)"', xml).group(1))
    assert cy / 12700 == pytest.approx(90, abs=1)
    assert "<a:srcRect" in xml


def test_border_and_shadow_are_drawn(photo):
    plain = doc_with(lambda b: b.image(photo, width=200), paragraphs=1)
    styled = doc_with(lambda b: b.image(photo, width=200, border=True, shadow=True), paragraphs=1)
    assert len(pdf_of(styled)[0].get_drawings()) > len(pdf_of(plain)[0].get_drawings())
    xml = docx_parts(styled.render_docx())["word/document.xml"].decode()
    assert "<a:ln " in xml and "outerShdw" in xml


def test_plain_image_call_still_works(photo):
    b = doc_with(lambda b: b.image(photo, caption="Quay", width=200), paragraphs=1)
    assert "Quay" in pdf_of(b)[0].get_text()
    assert b"<wp:inline" in docx_parts(b.render_docx())["word/document.xml"]


def test_cover_background_is_a_layer_under_live_text(photo):
    b = DocumentBuilder()
    b.cover_page("Annual Review", background_image=photo, layout="left_aligned", subtitle="Moorings")
    b.paragraph("Body")
    page = pdf_of(b)[0]
    assert "Annual Review" in page.get_text()
    kinds = [k for k, _ in page.get_bboxlog()]
    assert kinds.index("fill-image") < kinds.index("fill-text")
    box = page.get_image_info()[0]["bbox"]
    assert box[2] - box[0] >= page.rect.width - 1
    xml = docx_parts(b.render_docx())["word/document.xml"].decode()
    assert 'behindDoc="1"' in xml and "Annual Review" in xml


def test_cover_without_new_options_stays_legacy():
    b = DocumentBuilder()
    b.cover_page("Plain")
    b.paragraph("Body")
    assert "Plain" in pdf_of(b)[0].get_text()
    assert b"wp:anchor" not in docx_parts(b.render_docx())["word/document.xml"]


# ─── placement in the two renderers ───

def test_float_wraps_text_on_the_reading_end_side(photo):
    b = doc_with(lambda b: b.image(photo, placement="float_end", alt_text="Quay"))
    page = pdf_of(b)[0]
    box = page.get_image_info()[0]["bbox"]
    assert box[0] > page.rect.width / 2
    beside = [w for w in page.get_text("words") if box[1] < (w[1] + w[3]) / 2 < box[3]]
    assert beside and all(w[2] <= box[0] for w in beside)
    assert not check_pdf_media(b.render_bytes())
    xml = docx_parts(b.render_docx())["word/document.xml"].decode()
    assert "<w:tblpPr" in xml and 'w:tblpXSpec="right"' in xml


def test_float_mirrors_in_an_arabic_document(photo):
    b = DocumentBuilder()
    b.meta(title="تقرير", language="ar")
    b.heading("الملخص", level=1)
    b.image(photo, placement="float_start", alt_text="رسم")
    for _ in range(6):
        b.paragraph("أنجزت هيئة الميناء مسح الأرصفة خلال فصل الشتاء وسجلت حالة كل مرسى في الميناء. " * 4)
    page = pdf_of(b)[0]
    assert page.get_image_info()[0]["bbox"][0] > page.rect.width / 2
    assert 'w:tblpXSpec="right"' in docx_parts(b.render_docx())["word/document.xml"].decode()


def test_float_without_enough_text_falls_back_inline(photo):
    b = DocumentBuilder()
    b.image(photo, placement="float_end", alt_text="Quay")
    b.heading("Next", level=1)
    with pytest.warns(RuntimeWarning, match="float_fallback"):
        b.render_bytes()
    with pytest.warns(RuntimeWarning, match="float_fallback"):
        assert b"tblpPr" not in docx_parts(b.render_docx())["word/document.xml"]


def test_heading_is_not_stranded_by_a_float(photo):
    b = DocumentBuilder()
    for _ in range(9):
        b.paragraph(TEXT)
    b.heading("Late section", level=2)
    b.image(photo, placement="float_end", alt_text="Quay")
    for _ in range(4):
        b.paragraph(TEXT)
    for page in pdf_of(b):
        lines = [ln for ln in page.get_text().splitlines() if ln.strip()]
        assert not lines or lines[-1] != "Late section"


def test_full_bleed_reaches_both_page_edges(photo):
    b = doc_with(lambda b: b.image(photo, placement="full_bleed", height=120,
                                   treatment=ImageTreatment(fit="cover")), paragraphs=2)
    page = pdf_of(b)[0]
    box = page.get_image_info()[0]["bbox"]
    assert box[0] <= 0.5 and box[2] >= page.rect.width - 0.5
    xml = docx_parts(b.render_docx())["word/document.xml"].decode()
    assert "<wp:wrapTopAndBottom" in xml and '<wp:positionH relativeFrom="page">' in xml


def test_background_repeats_under_text_and_stays_out_of_the_text(photo):
    b = doc_with(lambda b: b.page_background(photo, opacity=.2), paragraphs=14)
    doc = pdf_of(b)
    assert doc.page_count >= 2
    for page in doc:
        kinds = [k for k, _ in page.get_bboxlog()]
        assert kinds.index("fill-image") < kinds.index("fill-text")
        assert "harbour" in page.get_text()
    parts = docx_parts(b.render_docx())
    assert b'behindDoc="1"' in next(v for n, v in parts.items() if n.startswith("word/header"))
    assert b"<wp:anchor" not in parts["word/document.xml"]


def test_a_repeated_image_is_embedded_once(photo):
    b = doc_with(lambda b: b.image(photo, width=100), lambda b: b.image(photo, width=100), paragraphs=1)
    assert sum(n.startswith("word/media/") for n in docx_parts(b.render_docx())) == 1
    assert len({x[0] for x in pdf_of(b)[0].get_images()}) == 1


def test_section_background_only_on_its_section(photo):
    b = doc_with(paragraphs=1)
    b.page_background(photo, scope="sections", sections=["annex"])
    b.page_section("annex")
    b.paragraph("Annex text")
    doc = pdf_of(b)
    assert doc.page_count == 2
    assert not doc[0].get_images() and doc[1].get_images()
    data = b.render_docx()
    assert data.count(b"") and b"sectPr" in docx_parts(data)["word/document.xml"]


def test_watermark_opacity_is_in_the_docx_pixels(logo):
    b = doc_with(lambda b: b.image_watermark(logo, opacity=.1), paragraphs=1)
    parts = docx_parts(b.render_docx())
    media = next(v for n, v in parts.items() if n.startswith("word/media/"))
    with Image.open(io.BytesIO(media)) as image:
        assert image.getchannel("A").getextrema()[1] <= 27


def test_rotation_keeps_the_drawing_native(photo):
    b = doc_with(lambda b: b.image(photo, width=200, treatment=ImageTreatment(rotation=10)), paragraphs=1)
    assert 'rot="600000"' in docx_parts(b.render_docx())["word/document.xml"].decode()


# ─── failure handling ───

def test_missing_image_is_a_typed_failure_or_a_marker(tmp_path):
    missing = str(tmp_path / "nope.png")
    strict = doc_with(lambda b: b.image(missing), paragraphs=1)
    with pytest.raises(DynamicPDFError):
        strict.render_bytes()
    loose = doc_with(lambda b: b.image(missing), paragraphs=1)
    loose.quality("permissive")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        doc = pdf_of(loose)
        assert "harbour" in doc[0].get_text()
        assert any(d.level == "error" for d in loose.last_render.diagnostics.items)
        assert b"harbour" in docx_parts(loose.render_docx())["word/document.xml"]


# ─── QA checks ───

def test_pdf_check_finds_text_painted_under_an_image(photo):
    from reportlab.pdfgen import canvas
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=(400, 400))
    c.drawString(60, 100, "hidden words behind the picture")
    c.drawImage(photo, 40, 60, 300, 150)
    c.save()
    assert [f["code"] for f in check_pdf_media(buffer.getvalue())] == ["text_under_image"]


def test_pdf_check_finds_a_stretched_image(photo):
    from reportlab.pdfgen import canvas
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=(400, 400))
    c.drawImage(photo, 40, 60, 300, 300)
    c.save()
    assert [f["code"] for f in check_pdf_media(buffer.getvalue())] == ["image_distorted"]


def test_docx_check_finds_distortion_and_missing_alt(photo):
    b = doc_with(lambda b: b.image(photo, width=200, alt_text="Quay"), paragraphs=1)
    data = b.render_docx()
    assert check_docx_media(data) == []
    parts = docx_parts(data)
    xml = parts["word/document.xml"].decode()
    xml = re.sub(r'(<wp:extent cx="\d+" cy=")\d+', r"\g<1>9000000", xml)
    xml = re.sub(r'descr="[^"]*"', 'descr=""', xml)
    parts["word/document.xml"] = xml.encode()
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for name, value in parts.items():
            z.writestr(name, value)
    assert {f["code"] for f in check_docx_media(out.getvalue())} == {"docx_image_distorted", "docx_image_no_alt"}


def test_docx_stays_text_not_a_picture_of_a_page(photo):
    b = doc_with(lambda b: b.page_background(photo, opacity=.3),
                 lambda b: b.image(photo, placement="float_end", alt_text="Quay"))
    summary = docx_media_summary(b.render_docx())
    assert summary["text_runs"] >= 6 and summary["anchored"] >= 1 and summary["embedded_images"] >= 1


def test_media_asset_is_exported_for_typing():
    assert MediaAsset.__dataclass_fields__["sha256"]
