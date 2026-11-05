"""
The design grammar as authored by an AI reviewer from the corpus.

Each rule says when it applies, what it needs, how it behaves right to left, which pages
support it and when it should not be used. ``layout_constraints`` carry their own source:
``measured`` comes from the page graphs, ``ai_observation`` from looking at the pages.

A rule with ``engine`` set can be consumed by ``dynamic_pdf.design.grammar``. A rule with
``requires`` needs a layout primitive the engine does not have; it stays documented and is
never imitated with something else.
"""
from __future__ import annotations

GRAMMAR_VERSION = "1.0.0"

_D = {"0b": "ref-0b2bf0ebc355", "db": "ref-db25596332d2", "82": "ref-82ccd1d81704", "02": "ref-0218e5046957",
      "af": "ref-af94892827c8", "cf": "ref-cf936a817893", "4b": "ref-4bbfe8f46cb3", "7f": "ref-7f52f49c5dd6",
      "fb": "ref-fb5a68768723", "93": "ref-9325a2a9012f", "b7": "ref-b7b9ddcb4981"}


def ev(*items):
    """``ev("db:2 why", ...)`` -> evidence entries with full page references."""
    out = []
    for item in items:
        where, why = item.split(" ", 1)
        doc, page = where.split(":")
        out.append({"ref": f"{_D[doc]}:{page}", "why": why})
    return out


def m(statement):
    return {"statement": statement, "source": "measured"}


def o(statement):
    return {"statement": statement, "source": "ai_observation"}


FAMILY_TEXT = {
    "cover_image": "First page carried by a colour field, photograph or illustration, with little text.",
    "cover_type": "A cover carried by type alone. Only one page remains after close review; most candidates were notices.",
    "section_opener": "A page or strong band that starts a part. Little text, large type.",
    "kpi_dashboard": "A page led by a few large figures.",
    "financial_table": "A page given over to a statement or a large numeric grid.",
    "table_in_text": "Tables inside running text.",
    "data_story": "Charts with commentary and sources.",
    "infographic": "A diagram or drawn figure leads the page.",
    "image_inset": "Text page with one or more contained images.",
    "image_split": "Image and text share the page in large zones.",
    "full_bleed_image": "An image reaches the page edges and takes most of the page.",
    "editorial_asymmetric": "Unequal columns or offset blocks. Precision was low: one of four sampled pages held up.",
    "card_grid": "Repeating cards: portrait or picture with short text.",
    "letter": "Signed message from a named person.",
    "contents": "Contents and lists of figures.",
    "multi_column_text": "Two or more text columns, including parallel language columns.",
    "single_column_text": "One text column.",
    "notes_references": "Notes, references, glossaries and credits.",
    "back_cover": "Closing page: logo, address, links or colophon.",
    "blank_or_notice": "Blank pages and legal notices.",
    "academic_opening": "Journal first page with a narrow metadata margin.",
}

RULES = [
    {
        "id": "cover.photo_over_panel", "name": "Photograph over a colour panel", "slot": "cover",
        "families": ["cover_image"], "page_roles": ["cover"],
        "content_roles": ["reports with at least one photograph the author allows on the cover"],
        "required_elements": ["title", "a photograph from the document"],
        "layout_constraints": [
            m("On the evidence page the photograph runs edge to edge from the top to y=0.73."),
            o("The title sits inside the panel, centred, in reversed type; the seam is the only strong edge on the page."),
            o("The photograph is never placed under the title, so no scrim is needed."),
        ],
        "rtl_behavior": "Centred text needs no mirroring; the title uses the Arabic face and its own line height.",
        "evidence_pages": ev("82:1 Photograph over the upper two thirds, colour panel below with the centred title.",
                             "82:3 Same photograph-over-colour-bar idea reused on the contents page."),
        "confidence": "medium",
        "failure_conditions": ["no usable photograph", "a title long enough to overflow the panel",
                               "a photograph whose subject sits at the bottom edge and is cut by the panel"],
        "safe_fallback": "cover.low_title_field, then the direction's own cover",
        "when": {"min_photos": 1, "min_pages": 3,
                 "directions": ["corporate_conservative", "arabic_institutional", "financial_data"]},
        "engine": {"direction": {"cover": "image_top"},
                   "extras": {"cover_image_top": 0.62, "cover_panel": 1, "cover_centred": 1, "cover_title_scale": 1.15}},
        "measures": ["largest_image", "max_size_pt", "display_ratio"],
    },
    {
        "id": "cover.low_title_field", "name": "Very large title low on a colour field", "slot": "cover",
        "families": ["cover_image"], "page_roles": ["cover"],
        "content_roles": ["any report; needs no image"],
        "required_elements": ["title", "brand or direction colour"],
        "layout_constraints": [
            m("On the evidence page the title starts at y=0.56 at 72 pt, from x=0.07."),
            m("Cover display ratio (largest type to body type) has a median of 2.86 across cover_image pages."),
            o("Everything hangs from the start edge; the upper half stays empty."),
        ],
        "rtl_behavior": "Title and rule hang from the right edge; the Arabic title takes the taller line height.",
        "evidence_pages": ev("db:2 Two-line title very large at the lower start on a field.",
                             "cf:1 Field-led cover where the title does not depend on a photograph."),
        "confidence": "medium",
        "failure_conditions": ["titles over about 32 characters at this scale: at 37 to 50 characters blind review found the title cut, a word broken and the rest of the cover pushed onto a blank page", "brand colour too light for reversed type"],
        "safe_fallback": "the direction's own cover",
        "when": {"min_pages": 3, "max_title_chars": 32,
                 "directions": ["executive_premium", "editorial_modern", "corporate_conservative", "arabic_institutional",
                                "financial_data"]},
        "engine": {"direction": {"cover": "colour_panel"}, "extras": {"cover_title_drop": 0.56, "cover_title_scale": 1.9}},
        "measures": ["display_ratio", "max_size_pt"],
    },
    {
        "id": "opener.edge_strip_page", "name": "Section opening page with an edge strip", "slot": "opener",
        "families": ["section_opener"], "page_roles": ["section opener"],
        "content_roles": ["major sections of documents of five pages or more"],
        "required_elements": ["section title", "at least three sections so the strip means something"],
        "layout_constraints": [
            m("Strip on the evidence pages occupies the outer third of the page: x from 0.673 to 1.0 in page terms."),
            m("Section opener pages have a median text share of 0.10 and a display ratio of 4.2."),
            o("Text hangs from the strip; the rest of the page stays quiet."),
            o("Opening pages never follow one another."),
        ],
        "rtl_behavior": "The strip sits on the reading-start edge, so it moves to the right in Arabic. Seen on an Arabic document.",
        "evidence_pages": ev("cf:113 Strip on the edge, heading, rule, large title, nothing else.",
                             "cf:179 The same device repeated for each goal.",
                             "af:3 Half title: quiet page, start-aligned title at mid height."),
        "confidence": "high",
        "failure_conditions": ["short documents, where opening pages inflate length", "sections under the major threshold"],
        "safe_fallback": "A rule above the heading, which the engine already applies after an opening page.",
        "when": {"min_pages": 5, "min_sections": 3,
                 "directions": ["corporate_conservative", "arabic_institutional", "financial_data"]},
        "engine": {"direction": {"opener": "page"}, "extras": {}},
        "measures": ["text_share", "display_ratio"],
    },
    {
        "id": "kpi.hero_and_grid", "name": "One leading figure and a ruled grid of the rest", "slot": "kpi",
        "families": ["kpi_dashboard"], "page_roles": ["highlights", "executive summary", "performance"],
        "content_roles": ["a section whose main content is one row of three or more figures"],
        "required_elements": ["metric row of at least three figures", "section title"],
        "layout_constraints": [
            m("Largest figure median 70 pt on kpi_dashboard pages, a display ratio near 8.7."),
            o("One figure leads. The others sit in a ruled grid at a clearly lower level."),
            o("Figures stay in the author's order and none is added."),
        ],
        "rtl_behavior": "Grid order runs from the right; digits keep their own left-to-right order inside each cell.",
        "evidence_pages": ev("db:28 Two zones, one huge figure, banded rows.", "db:18 The same device as a repeating section page.",
                             "4b:8 One hero figure and six figures in a ruled grid, in an Arabic edition."),
        "confidence": "medium",
        "failure_conditions": ["two metric rows in one section", "figures that need their own context paragraph",
                               "only two documents show this family, so it may be a house style"],
        "safe_fallback": "kpi.ruled_strip",
        "when": {"min_metrics": 1, "min_pages": 5},
        "engine": {"direction": {"kpi": "hero_page"}, "extras": {}},
        "measures": ["numeric_big", "display_ratio"],
    },
    {
        "id": "kpi.ruled_strip", "name": "Ruled figures in the text flow", "slot": "kpi",
        "families": ["kpi_dashboard"], "page_roles": ["summary inside running text"],
        "content_roles": ["short documents with a metric row"],
        "required_elements": ["metric row"],
        "layout_constraints": [o("No tile backgrounds: rules separate the figures, so the page stays light.")],
        "rtl_behavior": "Order runs from the right.",
        "evidence_pages": ev("4b:8 Ruled regional figures."),
        "confidence": "medium",
        "failure_conditions": ["more than five figures in a row"],
        "safe_fallback": "the direction's own figures",
        "when": {"min_metrics": 1, "max_pages": 4.99},
        "engine": {"direction": {"kpi": "ruled"}, "extras": {}},
        "measures": ["numeric_big"],
    },
    {
        "id": "table.current_period_ledger", "name": "Statement with the current period carried by tone", "slot": "table",
        "families": ["financial_table"], "page_roles": ["financial statement", "comparative table"],
        "content_roles": ["tables with two or more numeric period columns"],
        "required_elements": ["at least two numeric columns"],
        "layout_constraints": [
            m("financial_table pages have a median table share of 0.59 across 101 pages in 7 documents."),
            o("Hairline row rules, no zebra; one period column carries a tint; totals take heavier rules."),
            o("Line items may indent; numbers align on the end edge of their column."),
        ],
        "rtl_behavior": "Labels start at the right and period columns run leftwards; digits are not reversed.",
        "evidence_pages": ev("82:123 Comparative column tinted, double rules on totals.", "82:126 Prior period on a grey band.",
                             "db:135 Current year tinted and bold under a display heading.",
                             "db:136 Same system, second statement.", "7f:28 A plain variant: only bold and rules."),
        "confidence": "high",
        "failure_conditions": ["a table with one numeric column", "the author's own table style, which is kept",
                               "very wide equity statements, which need landscape pages"],
        "safe_fallback": "The direction's own table style.",
        "when": {"min_tables": 1},
        "engine": {"direction": {"table": "ledger"}, "extras": {}},
        "measures": ["table_share"],
    },
    {
        "id": "bands.dense_filled_head_foot", "name": "Filled head and foot bands that alternate", "slot": "bands",
        "families": ["table_in_text", "financial_table", "single_column_text"],
        "page_roles": ["running pages of long institutional documents"],
        "content_roles": ["reports where the reader needs to know the document and section on every page"],
        "required_elements": ["title", "page number"],
        "layout_constraints": [
            m("On the evidence pages the head occupies y 0.007 to 0.024 and the foot y 0.976 to 0.993: both touch the page edge."),
            o("The head carries the document and the foot the section and folio; the folio moves to the outer edge on facing pages."),
        ],
        "rtl_behavior": "Start and end swap, so the title sits at the right. Numbering stays in Arabic reading order.",
        "evidence_pages": ev("82:124 Head and foot bands on a statement page.", "82:125 The facing page with the folio on the other side.",
                             "82:50 The same bands on a table page."),
        "confidence": "medium",
        "failure_conditions": ["documents under four pages, where bands outweigh the content",
                               "printers that cannot print to the edge"],
        "safe_fallback": "The direction's own bands.",
        "when": {"min_pages": 4, "directions": ["financial_data", "corporate_conservative"]},
        "engine": {"direction": {"bands": "dual_filled"}, "extras": {}},
        "measures": ["header_items", "footer_items"],
    },
    {
        "id": "image.alternating_inset", "name": "Contained photographs alternating sides", "slot": "image",
        "families": ["image_inset"], "page_roles": ["narrative pages with several photographs"],
        "content_roles": ["sections with two or more photographs and enough text to wrap them"],
        "required_elements": ["two or more photographs", "at least two paragraphs after each photograph"],
        "layout_constraints": [
            m("image_inset pages: median largest image 0.08 of the page, text share 0.43, in 7 documents."),
            o("Images stay inside the text frame, and sides alternate so the page does not lean one way."),
        ],
        "rtl_behavior": "Sides are logical. The first photograph goes to the reading-end edge, which is the left in Arabic.",
        "evidence_pages": ev("cf:165 Two columns with a photograph and tinted callouts.", "4b:38 One photograph above two columns.",
                             "82:21 Three inset photographs with captions."),
        "confidence": "medium",
        "failure_conditions": ["photographs that must be read at full width", "short paragraphs that cannot wrap", "a heading within the image height: Word sets it beside the image, the PDF below it"],
        "safe_fallback": "The direction's own image placement, which the refinement step also falls back to.",
        "when": {"min_photos": 2, "directions": ["corporate_conservative", "financial_data", "arabic_institutional"]},
        "engine": {"direction": {"side_image": 0.4, "side_alternates": True}, "extras": {}},
        "measures": ["largest_image", "text_share"],
    },
    {
        "id": "closing.image_band", "name": "Closing photograph as a full-width band", "slot": "closing",
        "families": ["image_split", "back_cover"], "page_roles": ["last section"],
        "content_roles": ["documents that end on a photograph the author allows to crop"],
        "required_elements": ["photograph as the last block of the last section, crop allowed"],
        "layout_constraints": [
            m("The evidence page keeps its text above y=0.57 and gives the lower part to a photograph."),
            o("The band reaches both page edges and closes the document without any added content."),
            o("The references anchor the band to the page foot. The engine sets it in the flow; see foot_anchored_media."),
        ],
        "rtl_behavior": "No mirroring needed: the band is symmetric.",
        "evidence_pages": ev("b7:4 Contact details above, photograph across the lower part of the page."),
        "confidence": "low",
        "failure_conditions": ["one template is the only close evidence", "a photograph that is not the last block",
                               "crop not allowed by the author"],
        "safe_fallback": "The image stays where the direction placed it.",
        "when": {"min_photos": 1, "min_pages": 3},
        "engine": {"direction": {}, "extras": {"closing_band": 0.34}},
        "measures": ["largest_image"],
    },
    # Documented. The engine lacks what these need, so nothing imitates them.
    {
        "id": "chart.caption_bar", "name": "Chart under a tinted caption bar", "slot": "chart",
        "families": ["data_story"], "page_roles": ["data pages"],
        "content_roles": ["charts with a title and a source"], "required_elements": ["chart", "figure title", "source"],
        "layout_constraints": [o("A tinted bar the width of the chart holds the figure title; the source sits under the chart.")],
        "rtl_behavior": "Title starts at the right; the chart axis follows the data.",
        "evidence_pages": ev("cf:59 Two charts each under a caption bar.", "cf:149 Same device with text below.",
                             "cf:174 Three charts sharing one bar."),
        "confidence": "high", "failure_conditions": ["charts without a title"],
        "safe_fallback": "The chart's own caption.", "when": None, "engine": None, "requires": ["figure_caption_band"],
    },
    {
        "id": "chart.small_multiples", "name": "Matrix of small charts", "slot": "chart",
        "families": ["data_story"], "page_roles": ["data pages"], "content_roles": ["four to eight related series"],
        "required_elements": ["several charts of one kind"],
        "layout_constraints": [o("Equal cells, shared scale, each with its own short title.")],
        "rtl_behavior": "Reading order of the cells runs from the right.",
        "evidence_pages": ev("82:6 Six small bar charts in two columns."), "confidence": "medium",
        "failure_conditions": ["series on different scales"], "safe_fallback": "Charts one after another.",
        "when": None, "engine": None, "requires": ["figure_matrix"],
    },
    {
        "id": "card.portrait_grid", "name": "Repeating portrait cards", "slot": "cards",
        "families": ["card_grid"], "page_roles": ["people", "case lists"],
        "content_roles": ["board or team lists"], "required_elements": ["a picture, name and short text per card"],
        "layout_constraints": [o("Same card height across a row; two to three per row.")],
        "rtl_behavior": "Rows fill from the right.",
        "evidence_pages": ev("db:60 Biography grid.", "4b:7 Small photographs each heading a short text."),
        "confidence": "medium", "failure_conditions": ["uneven text lengths"], "safe_fallback": "A two-column table.",
        "when": None, "engine": None, "requires": ["card_grid"],
    },
    {
        "id": "editorial.overlaid_panel", "name": "Tinted text panel over a photograph", "slot": "image",
        "families": ["image_split", "full_bleed_image"], "page_roles": ["feature openings"],
        "content_roles": ["short feature text"], "required_elements": ["large photograph", "short text"],
        "layout_constraints": [o("The panel covers a quiet part of the photograph; never a face.")],
        "rtl_behavior": "Panel moves to the reading-start side.",
        "evidence_pages": ev("4b:16 Tinted panel overlaid on a full-height photograph.",
                             "db:8 Curved colour field under a photograph."),
        "confidence": "medium", "failure_conditions": ["busy photographs"], "safe_fallback": "Text under the image.",
        "when": None, "engine": None, "requires": ["image_text_panel"],
    },
    {
        "id": "editorial.outer_callout", "name": "Narrow callout at the outer edge", "slot": "text",
        "families": ["editorial_asymmetric"], "page_roles": ["editorial pages"],
        "content_roles": ["a short aside beside long text"], "required_elements": ["aside"],
        "layout_constraints": [o("A tinted narrow column, outside the main measure, with an offset heading across the text.")],
        "rtl_behavior": "Outer edge mirrors.",
        "evidence_pages": ev("4b:33 Offset heading and outer callout.", "4b:32 Narrow tinted callout beside a large photograph."),
        "confidence": "low", "failure_conditions": ["family precision was 1 of 4"], "safe_fallback": "A callout in the text.",
        "when": None, "engine": None, "requires": ["outer_margin_column"],
    },
    {
        "id": "bilingual.parallel_columns", "name": "Parallel language columns", "slot": "bilingual",
        "families": ["multi_column_text"], "page_roles": ["bilingual body text"],
        "content_roles": ["text held in two languages"], "required_elements": ["paired paragraphs in two languages"],
        "layout_constraints": [o("Paired paragraphs start on the same line; each column aligns to its own direction.")],
        "rtl_behavior": "Arabic takes the right column and aligns right; English takes the left and aligns left.",
        "evidence_pages": ev("7f:7 Matching columns, each aligned to its own direction.", "fb:23 Landscape comparison with four ruled columns."),
        "confidence": "high", "failure_conditions": ["unpaired text"], "safe_fallback": "One language after the other.",
        "when": None, "engine": None, "requires": ["paired_row_columns"],
    },
    {
        "id": "bilingual.parallel_ledger", "name": "Figures once, labels from each language's edge", "slot": "bilingual",
        "families": ["table_in_text"], "page_roles": ["bilingual financial tables"],
        "content_roles": ["comparative figures in two languages"], "required_elements": ["labels in both languages"],
        "layout_constraints": [o("Figures sit in the centre; each language labels from its own outer edge.")],
        "rtl_behavior": "Both directions on one row.",
        "evidence_pages": ev("7f:4 Row labels in both languages at opposite ends, figures in the centre."),
        "confidence": "high", "failure_conditions": ["more than four periods"], "safe_fallback": "Two separate tables.",
        "when": None, "engine": None, "requires": [],
        "author_block": "parallel_ledger: already a block for authors; it needs paired labels, which no adapter can invent.",
    },
    {
        "id": "academic.metadata_margin", "name": "Article opening with a metadata margin", "slot": "opening",
        "families": ["academic_opening"], "page_roles": ["journal first page"],
        "content_roles": ["articles with dates, editors and licence"], "required_elements": ["metadata", "abstract"],
        "layout_constraints": [o("A narrow start margin holds metadata, while the title and body use a wide column.")],
        "rtl_behavior": "Not observed.",
        "evidence_pages": ev("02:1 Journal first page."), "confidence": "low",
        "failure_conditions": ["a single page of evidence"], "safe_fallback": "Metadata under the title.",
        "when": None, "engine": None, "requires": ["first_page_margin_column"],
    },
    {
        "id": "letter.portrait_opener", "name": "Letter with portrait, lead and signature", "slot": "opening",
        "families": ["letter"], "page_roles": ["chair or chief executive letter"],
        "content_roles": ["a signed message"], "required_elements": ["portrait", "signature", "lead text"],
        "layout_constraints": [o("Portrait, display heading and lead on the start side; letter text in the end column, closing with a signature.")],
        "rtl_behavior": "Not observed in the Arabic documents.",
        "evidence_pages": ev("db:85 Portrait, heading, lead, signature, boxed contents.", "db:82 Portrait at start, letter at end.",
                             "82:9 Wide photograph with a colour title bar."),
        "confidence": "medium", "failure_conditions": ["no portrait"], "safe_fallback": "A plain section with a signature block.",
        "when": None, "engine": None, "requires": ["unequal_page_zones"],
    },
]

UNSUPPORTED = {
    "figure_caption_band": "A tinted caption bar tied to a chart in both renderers.",
    "figure_matrix": "A grid of equal chart cells with a shared title.",
    "card_grid": "Repeating equal-height cards that flow across pages.",
    "image_text_panel": "A text panel layered over an image, with live text in PDF and DOCX.",
    "outer_margin_column": "A column outside the text frame that mirrors on facing pages.",
    "paired_row_columns": "Rows that keep two language columns aligned paragraph by paragraph across pages.",
    "first_page_margin_column": "A first-page-only margin column.",
    "unequal_page_zones": "Named page zones of unequal width with text flowing from one to the other.",
    "foot_anchored_media": "A body image anchored to the page foot, with the text above it, in both renderers.",
    "gradient_scrim": "A partial gradient over a photograph; the engine has flat overlays only.",
    "masked_image_shape": "Images clipped to curves or rounded panels in both renderers.",
}
