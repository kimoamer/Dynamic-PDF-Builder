"""
The JSON Schema of a document, with a description of every field that has one in the source.

The models carry their explanations as comments beside each field (``rows: ... # Summary/total row``);
they are read from the source here, so the schema an agent reads says what the code says and cannot
drift from it.
"""
from __future__ import annotations

import ast
import io
import tokenize
from functools import lru_cache
from importlib import resources
from typing import Dict, Tuple


@lru_cache(maxsize=1)
def field_notes() -> Dict[Tuple[str, str], str]:
    """``{(class, field): comment}`` for every annotated field of the schema models."""
    notes: Dict[Tuple[str, str], str] = {}
    for entry in resources.files("dynamic_pdf.schema").iterdir():
        if not entry.name.endswith(".py"):
            continue
        source = entry.read_text(encoding="utf-8")
        comments = {tok.start[0]: tok.string.lstrip("#").strip()
                    for tok in tokenize.generate_tokens(io.StringIO(source).readline) if tok.type == tokenize.COMMENT}
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                        note = comments.get(item.lineno) or comments.get(item.end_lineno)
                        if note:
                            notes[(node.name, item.target.id)] = note
    return notes


# fields that mean the same wherever they appear
COMMON = {
    "id": "an id: {ref:id} in any text refers to this block, and a link to #id points at it",
    "lang": "the language of this block's text ('en', 'ar' ...); detected from the text when left out",
    "hints": "layout hints set by the design planner; leave this out",
    "type": "the kind of block",
    "text": "the text, as inline Markdown: **bold**, *italic*, [link](url), {ref:id}, [@key], {=table!D5}, {++edit++}",
    "title": "the title shown with it",
    "subtitle": "a line under the title",
    "caption": "the caption; with an id as well, it is numbered (Table 2, Figure 3) and can be referred to",
    "items": "the entries, in order",
    "headers": "the header cells",
    "rows": "the rows, each a list of cells; a cell is inline Markdown, and a cell that starts with = is a "
            "formula (=B2*C2, =SUM(ABOVE), =WORDS(D5)); columns are A, B, C ... and the header is row 1",
    "label": "the label shown", "value": "the value as it should read (for example '$4.2M')",
    "delta": "the change shown beside the value, as it should read (for example '+12%')",
    "note": "a short note shown with it", "color": "a colour, #RRGGBB", "colors": "colours, #RRGGBB, in order",
    "src": "the picture: a file path, a data: URI, or an http(s) URL (only when the asset policy allows remote)",
    "alt_text": "what the picture shows, for readers who cannot see it",
    "alignment": "left, center or right", "date": "the date, as it should read", "author": "the author, as it should read",
    "icon": "an icon name", "description": "a description", "keywords": "keywords",
    "entries": "the works, in order", "authors": "the authors, as they should read", "year": "the year",
    "doi": "the DOI, without https://doi.org/", "checked": "ticked or not", "term": "the term", "definition": "its definition",
    "attribution": "who said it", "start": "the first number", "level": "1 (a chapter) to 6",
    "numbered": "number this heading", "latex": "the formula in LaTeX (the matplotlib mathtext subset)",
    "diagram": "the Mermaid source", "code": "the code", "line_numbers": "number the lines",
    "highlight_lines": "line numbers to highlight", "x_label": "the title of the horizontal axis",
    "y_label": "the title of the vertical axis", "legend": "show a legend (when there are several series)",
    "key": "the citation key, as cited with [@key]", "page_size": "A4, A3, A5, Letter or Legal",
    "orientation": "portrait or landscape", "owner_password": "with encrypt: the password that grants every right",
    "user_password": "with encrypt: the password that opens the document", "fields": "the parts, each a label and its text",
    "max_value": "the value that fills the bar", "benchmark": "a target, marked on the bar",
    "events": "the events, in order", "children": "nested entries", "nested": "items may hold nested items",
}
# what each kind of block is for, where its class says nothing
MODELS = {
    "ParagraphBlock": "A paragraph of inline Markdown.", "HeadingBlock": "A heading, level 1 to 6.",
    "RichTextBlock": "Text with richer inline formatting.", "NoteBlock": "A short aside in smaller type.",
    "BulletListBlock": "A list with bullets.", "NumberedListBlock": "A numbered list.",
    "ChecklistItem": "One item of a checklist.", "DefinitionItem": "A term and its definition.",
    "TableBlock": "A table. Figures right-align, total rows are set in bold, and formula cells are computed.",
    "CodeBlock": "Program code, highlighted.", "ImageBlock": "A picture, with its caption and alt text.",
    "ChartBlock": "A chart drawn from data; a native chart in Word for bar, line, area, pie and doughnut.",
    "MathBlock": "An equation in LaTeX; numbered when it has an id.", "MermaidBlock": "A Mermaid diagram.",
    "CalloutBlock": "A boxed note: info, warning, tip, success, danger, caution, important or example.",
    "QuoteBlock": "A quotation.", "MetricItem": "One key figure.", "MetricRowBlock": "A row of key figures (KPIs).",
    "ProgressBarItem": "One bar.", "ProgressBarBlock": "Bars showing progress towards a value.",
    "ScoreDisplayBlock": "A score shown large.", "LegendItem": "One entry of a legend.", "LegendBlock": "A legend.",
    "BadgeBlock": "A small labelled badge.", "BibliographyEntry": "One work in a reference list.",
    "AbstractField": "One part of a structured abstract.", "TimelineEvent": "One event on a timeline.",
    "CoverPageBlock": "A cover page, or with the title_block hint a title at the head of page one.",
    "TOCBlock": "A table of contents, a list of figures or a list of tables.", "DividerBlock": "A horizontal rule.",
    "SpacerBlock": "Vertical space.", "PageBreakBlock": "A page break.", "WatermarkBlock": "A watermark on the pages.",
    "TwoColumnBlock": "Two columns side by side.", "ThreeColumnBlock": "Three columns side by side.",
    "Meta": "About the document: title, author, language, page size, numbering, reviewer, protection.",
}


def document_schema() -> dict:
    """``Document.model_json_schema()`` with the field notes as descriptions: a field's own comment
    in the source first, then what the field means wherever it appears."""
    from .document import Document
    schema = Document.model_json_schema()
    notes = field_notes()
    for name, model in [("Document", schema)] + list(schema.get("$defs", {}).items()):
        if not model.get("description") and name in MODELS:
            model["description"] = MODELS[name]
        for field, prop in model.get("properties", {}).items():
            note = notes.get((model.get("title", name), field)) or notes.get((name, field)) or COMMON.get(field)
            if note and "description" not in prop:
                prop["description"] = note
    return schema
