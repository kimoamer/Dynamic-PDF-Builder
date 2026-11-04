# M7.6: media engine and page system

One renderer-independent placement model for images, and slot-based running headers
and footers, in PDF and editable DOCX. Nothing here changes a document that does not ask
for it: 30 of 30 default-output documents are identical to `main`.

- Measurements: [report.md](report.md), [results.json](results.json)
- Rendered pages: [gallery/index.html](gallery/index.html) (before pages for the six media examples, after pages for all 14)
- Reproduce: `python benchmarks/m76/run.py OUT_DIR`

All example images are drawn by `benchmarks/m76/assets.py`. No reference artwork is used.

## Using it

```python
from dynamic_pdf import DocumentBuilder
from dynamic_pdf.schema.media import ImageTreatment
from dynamic_pdf.schema.page_system import Band, BandRow, Logo, PageSystem

b = DocumentBuilder()
b.meta(title="Annual Review", language="en")
b.page_system(PageSystem(
    header=Band(rows=[BandRow(start=[Logo(src="logo.png", max_height=20)], center=["{title}"],
                              end=["{section}"], rule_below=True)]),
    footer=Band(rows=[BandRow(left=["Saltmere"], right=["Page {page} of {pages}"])])))
b.cover_page("Annual Review", background_image="quay.jpg", layout="split")
b.page_background("paper.png", opacity=.4)
b.image_watermark("logo.png", opacity=.06)
b.image("plant.jpg", placement="float_end", caption="Pump room", figure_number=1,
        source="Authority survey", alt_text="Pump room")
b.image("quay.jpg", placement="full_bleed", height=200, treatment=ImageTreatment(fit="cover", focal_y=.6))
b.page_section("annex")
```

`image()` and `cover_page()` keep their old arguments and results.

| Concept | Where |
|---|---|
| Placement presets: `inline`, `full_width`, `full_bleed`, `float_start`, `float_end`, `behind_text`, `in_front_of_text` | `schema/media.py` |
| `MediaPlacement`: mode, wrap, reference (page, margins, content), start/end sides, offsets, z-order, bleed | `schema/media.py` |
| `ImageTreatment`: contain or cover, focal point, crop, rotation, opacity, border, shadow, padding | `schema/media.py` |
| Scopes: `every_page`, `cover`, `once`, `sections` | `page_background`, `image_watermark` |
| Asset intake, dedupe, resolution checks, geometry | `media.py` |
| Safe SVG | `svg_safe.py` |
| Bands: left/center/right or start/end slots, multiple rows, logos, fields | `schema/page_system.py` |
| Structural checks of placed images | `qa/media_checks.py` |

`first_page="auto"` leaves a cover clean and keeps the bands on any other first page.

## What was incomplete before

| Property | Before | Now |
|---|---|---|
| `image(height=)` | ignored in DOCX | honoured in both, with crop or contain |
| `image(border=, shadow=)` | stored, never drawn | drawn in PDF, native `a:ln` and `a:outerShdw` in DOCX |
| `image(width=)` larger than the file's natural size | PDF capped it | the stated width is used, up to the frame |
| Cover background | not available | image, colour or split panel behind live text |
| DOCX header and footer | plain text | tables with live fields and native logos |

## Implementation status

**Implemented and tested in both formats:** inline, full width, full bleed, floats with
wrapped text, behind and in front of text, page backgrounds, section backgrounds, image
watermarks, cover images, captions with number and source, alt text, contain, cover, focal
point, crop, rotation, opacity, border, shadow, `start` and `end` mirrored for right-to-left
documents, content-hash dedupe in a bounded 96 MiB cache, EXIF orientation, transparency,
PNG, JPEG, WebP and CMYK, DPI reporting, low-resolution warnings, size and pixel limits,
slot bands with odd and even pages, first page, sections, Arabic, bilingual rows and logos.

**Experimentally supported:**

- ICC profiles: images are converted to sRGB on intake, not carried through. This is not a
  colour-managed print workflow.
- SVG gradients and text depend on what svglib draws in PDF. Refused content is listed in
  `svg_safe.py`.
- In-front-of-text images are drawn as asked. The paint-order check reports text hidden
  beneath them, because it cannot tell a deliberate overlay from a mistake.

**Not verified:**

- **Microsoft Word has not opened any of these files.** Word automation hung in this
  environment. All DOCX pages shown were rendered by LibreOffice 24.2. The XML follows the
  OOXML schema and the checks read it structurally, but Word's own layout is unconfirmed.
- Text and image collision in the LibreOffice output is reviewed by eye. LibreOffice exports
  a cropped picture whole under a clip, so its box does not show what is visible, and the
  paint-order check is not valid there. It runs on engine PDFs only.

## Word and LibreOffice differences

| Topic | Behaviour | Consequence |
|---|---|---|
| Opacity | LibreOffice ignored DrawingML alpha on anchored pictures | Opacity is written into the PNG's pixels. Faded images are reduced to 2,400 px on the long edge |
| SVG | Word 2016 and later read `asvg:svgBlip`; others read the PNG | Both are embedded. A faded SVG has the PNG only |
| `{section}` field | `STYLEREF` searches the page, then backwards, then forwards. LibreOffice 24.2 showed the next level 2 heading on pages without one, where the PDF shows the current level 1 | Running titles can differ from the PDF on such pages |
| `{section}` level | Follows Heading 2 if the document has one, otherwise Heading 1 | Set by the document, not per page |
| Floats | A bare anchored picture ran past the bottom margin in LibreOffice | Floats are one-cell floating tables, which both applications keep whole. The caption stays a real paragraph |
| Float break | PDF splits text around a float exactly; Word and LibreOffice decide their own line breaks | The wrapped text differs line by line |
| Right-to-left band rows | LibreOffice reverses a plain table in a right-to-left section; Word does not | Band tables are marked `bidiVisual` and written in reading order, which reads the same in both |
| Indents in right-to-left paragraphs | `w:ind` left and right swap sides | Handled when placing cover text beside a split panel |
| Page layers | Word repeats drawings through the header, so they sit under all body content | An `every_page` watermark is hidden by a cover backdrop in DOCX, and drawn over it in PDF |
| Band fills that bleed | Page-anchored shapes behind the header table | Same appearance, but moving the table in Word does not move its fill |
| Pagination | Word and LibreOffice lay out with their own metrics | DOCX page counts can differ from the PDF: 3 PDF and 2 DOCX pages in `financial_report` |
| Drop caps | PDF only, from the existing design layer | Not added to DOCX here |

## Remaining limits on visual quality

- Automatic decisions about which image goes where are M7.8. Here the author decides.
- A float's height in DOCX is not known against the page until layout, so a float near a page
  end can leave white space beside it.
- `fill_fields` leaves an unset field blank without a warning, so a mistyped field name
  disappears quietly.
- Header band design is only as good as the author's choices. Theme-level band families
  arrive with the diversity work in M7.8.
- The heap figures in `report.md` are Python allocations from `tracemalloc`, not process RSS.
