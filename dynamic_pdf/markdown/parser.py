"""
Markdown → Block tree parser.
Handles: headings, paragraphs, code fences (mermaid/math), bullet lists,
ordered lists, GFM tables, blockquotes, images, horizontal rules,
callout admonitions, task lists (- [ ] / - [x]), definition lists,
footnote references, and YAML front matter.
"""
import re
from typing import Dict, List, Tuple
from markdown_it import MarkdownIt
from ..schema.blocks import (
    ListItemModel,
    HeadingBlock, ParagraphBlock, CodeBlock, BulletListBlock, NumberedListBlock,
    ImageBlock, MathBlock, MermaidBlock, TableBlock, QuoteBlock, DividerBlock,
    CalloutBlock, ChecklistBlock, ChecklistItem, DefinitionListBlock, DefinitionItem,
    FootnoteBlock, TOCBlock,
)


_FN_DEF_SENTINEL = "\u2063FNDEF\u2063"
_FN_DEF_RE = re.compile("(?m)^" + _FN_DEF_SENTINEL + r"(\w+):[ \t]*(.*?)(?=\n" + _FN_DEF_SENTINEL + r"|\Z)",
                        re.DOTALL)


def split_front_matter(md_text: str) -> Tuple[Dict[str, object], str]:
    """Split a leading ``---`` YAML-like front matter block.

    Supports ``key: value``, quoted values and ``[a, b]`` inline lists.
    """
    front_matter: Dict[str, object] = {}
    fm_match = re.match(r'^\ufeff?---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)', md_text, re.DOTALL)
    if not fm_match:
        return front_matter, md_text
    for line in fm_match.group(1).splitlines():
        if ':' not in line or line.lstrip().startswith('#'):
            continue
        k, v = line.split(':', 1)
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
            v = v[1:-1]
        elif v.startswith('[') and v.endswith(']'):
            v = [x.strip().strip('"\'') for x in v[1:-1].split(',') if x.strip()]
        front_matter[k.strip()] = v
    return front_matter, md_text[fm_match.end():]


def parse_markdown(md_text: str) -> Tuple[Dict[str, object], list]:
    """Parse Markdown into ``(front_matter, blocks)``."""
    front_matter, body = split_front_matter(md_text)
    blocks = _parse_body(body)
    numbered = False
    for b in blocks:
        if b.type == "table" and b.hints and b.hints.pop("table_caption", None):
            numbered, b.hints = True, b.hints or None
    if numbered:
        front_matter.setdefault("numbering", "true")     # "Table: ..." asks for numbered tables
    return front_matter, blocks


def markdown_to_blocks(md_text: str) -> list:
    """Parse a markdown string into a list of typed Block objects."""
    return parse_markdown(md_text)[1]


def _tokens(md_text: str) -> list:
    """markdown-it tokens exactly as the block parser sees them (also used by streaming)."""
    # Footnote definitions ("[^1]: text") would otherwise be consumed by
    # CommonMark as link reference definitions and silently disappear.
    md_text = re.sub(r'(?m)^\[\^(\w+)\]:', _FN_DEF_SENTINEL + r'\1:', md_text)
    md = MarkdownIt("commonmark", {"html": False}).enable(["table", "strikethrough"])
    return md.parse(md_text)


def _parse_body(md_text: str) -> list:
    tokens = _tokens(md_text)
    blocks = []
    footnotes = {}
    idx = 0

    while idx < len(tokens):
        t = tokens[idx]

        # ─── Headings ───
        if t.type == "heading_open":
            level = int(t.tag[1])
            idx += 1
            content, anchor = _attr_id(_collect_inline(tokens, idx))
            blocks.append(HeadingBlock(level=level, text=content, id=anchor))
            idx += 1  # heading_close

        # ─── Paragraphs ───
        elif t.type == "paragraph_open":
            idx += 1
            content = _collect_inline(tokens, idx)

            # Image-only paragraph (the *whole* paragraph must be the image,
            # otherwise surrounding text would be lost)
            if content.startswith("!["):
                img_text, anchor = _attr_id(content)
                img_match = re.fullmatch(r'\s*!\[([^\]]*)\]\(([^)\s]+?)(?:\s+"([^"]*)")?\)\s*', img_text)
                if img_match:
                    blocks.append(ImageBlock(
                        src=img_match.group(2),
                        caption=img_match.group(3) or img_match.group(1) or None,
                        alt_text=img_match.group(1) or None,
                        id=anchor,
                    ))
                    idx += 2
                    continue

            # Callout admonition (:::variant ... :::), may span paragraphs
            if content.startswith(":::") and content.strip() != ":::":
                parts = content.split("\n", 1)
                variant = parts[0].replace(":::", "").strip() or "info"
                body_parts = [parts[1] if len(parts) > 1 else ""]
                idx += 2
                closed = body_parts[0].rstrip().endswith(":::")
                while not closed and idx < len(tokens):
                    nt = tokens[idx]
                    if nt.type == "paragraph_open":
                        txt = _collect_inline(tokens, idx + 1)
                        body_parts.append(txt)
                        idx += 3
                        closed = txt.rstrip().endswith(":::")
                    else:
                        break
                body = "\n\n".join(body_parts).rstrip()
                if body.endswith(":::"):
                    body = body[:-3].rstrip()
                blocks.append(CalloutBlock(text=body, variant=variant))
                continue

            # Footnote definitions: [^N]: text. Definitions on consecutive lines form one
            # Markdown paragraph, so each one that starts a line starts its own footnote;
            # other lines continue the footnote above them.
            if content.startswith(_FN_DEF_SENTINEL):
                for fn_match in _FN_DEF_RE.finditer(content):
                    blocks.append(FootnoteBlock(marker=fn_match.group(1), text=fn_match.group(2).strip()))
                idx += 2
                continue
            content = content.replace(_FN_DEF_SENTINEL, "[^")

            # [TOC], [LOF], [LOT]: a contents page, a list of figures, a list of tables
            listing = {"[TOC]": "contents", "[LOF]": "figures", "[LOT]": "tables"}.get(content.strip())
            if content.strip() in ("[REFERENCES]", "[BIBLIOGRAPHY]"):      # where the cited works are listed
                from ..schema.blocks import BibliographyBlock
                blocks.append(BibliographyBlock(entries=[]))
                idx += 2
                continue
            if listing:
                blocks.append(TOCBlock(kind=listing))
                idx += 2
                continue

            # "Table: caption {#id}" right after a table is that table's caption (Pandoc's form)
            cap = _TABLE_CAPTION.match(content)
            if cap and blocks and blocks[-1].type == "table" and not blocks[-1].caption:
                caption, anchor = _attr_id(cap.group(1))
                blocks[-1].caption, blocks[-1].id = caption, anchor or blocks[-1].id
                blocks[-1].hints = {"table_caption": True}
                idx += 2
                continue

            # Definition list: term\n: definition
            if '\n: ' in content or content.startswith(': '):
                items = _parse_definition_list(content)
                if items:
                    blocks.append(DefinitionListBlock(items=items))
                    idx += 2
                    continue

            blocks.append(ParagraphBlock(text=_field_lines(content)))
            idx += 1  # paragraph_close

        # ─── Code Fences ───
        elif t.type == "fence":
            info, fence_id = _attr_id((t.info or "").strip())
            lang = info.split()[0] if info.split() else "text"
            code = (t.content or "").rstrip("\n")
            if lang == "mermaid":
                blocks.append(MermaidBlock(diagram=code))
            elif lang == "chart":
                blocks.append(_chart_block(code, fence_id))
            elif lang in ("math", "latex"):
                blocks.append(MathBlock(latex=code, id=fence_id))
            else:
                blocks.append(CodeBlock(language=lang, code=code))

        # ─── Indented code ───
        elif t.type == "code_block":
            blocks.append(CodeBlock(language="text", code=(t.content or "").rstrip("\n")))

        # ─── Bullet Lists ───
        elif t.type == "bullet_list_open":
            items, idx = _collect_list(tokens, idx)
            flat_tasks = all(it.checked is not None and not it.children for it in items)
            if items and flat_tasks:
                # Flat GFM task list → dedicated checklist block (v0.3 behaviour)
                blocks.append(ChecklistBlock(items=[
                    ChecklistItem(text=it.text, checked=it.checked) for it in items]))
            else:
                blocks.append(BulletListBlock(items=_simplify_items(items),
                                              nested=any(it.children for it in items)))
            continue

        # ─── Ordered Lists ───
        elif t.type == "ordered_list_open":
            start = int(t.attrGet("start") or 1)
            items, idx = _collect_list(tokens, idx)
            blocks.append(NumberedListBlock(items=_simplify_items(items), start=start))
            continue

        # ─── Tables ───
        elif t.type == "table_open":
            headers, rows, idx = _collect_table(tokens, idx)
            blocks.append(TableBlock(headers=headers, rows=rows))
            continue

        # ─── Block Quotes ───
        elif t.type == "blockquote_open":
            parts, idx = _collect_blockquote(tokens, idx)
            # paragraphs of the quote are separated by a blank line; a single newline is a soft break
            blocks.append(QuoteBlock(text="\n\n".join(parts)))
            continue

        # ─── Horizontal Rule ───
        elif t.type == "hr":
            blocks.append(DividerBlock())

        idx += 1

    return blocks


_TABLE_CAPTION = re.compile(r"^Table:\s+(\S.*)$", re.S)
_ATTR_ID = re.compile(r"\s*\{#([A-Za-z][\w:.-]*)\}\s*$")


def _chart_block(code: str, anchor):
    """A ```chart fence: a JSON object with ``type`` and ``data`` (as ``DocumentBuilder.chart``
    takes them) and optionally ``title``, ``x_label``, ``y_label``, ``colors``, ``legend``."""
    import json
    from ..schema.blocks import ChartBlock
    try:
        spec = json.loads(code)
    except json.JSONDecodeError as e:
        raise ValueError(f"a ```chart block holds JSON, as {{\"type\": \"bar\", \"data\": {{\"A\": 1}}}}; "
                         f"this one does not parse: {e}") from None
    if not isinstance(spec, dict) or "data" not in spec or not (spec.get("type") or spec.get("chart_type")):
        raise ValueError('a ```chart block needs "type" (bar, line, pie ...) and "data"')
    spec = dict(spec)
    spec["chart_type"] = spec.pop("type", None) or spec["chart_type"]
    return ChartBlock(id=anchor, **spec)


def _attr_id(text: str):
    """("text", "id") from "text {#id}", Pandoc's attribute for an anchor."""
    m = _ATTR_ID.search(text)
    return (text[:m.start()], m.group(1)) if m else (text, None)


_FIELD_LINE = re.compile(r"^\s*[^\W\d_][\w .'/&-]{0,30}?:[ \t]+\S")


def _field_lines(content: str) -> str:
    """A paragraph whose every line is a ``Label: value`` pair (a memo's To/From/Subject
    block, a letter's reference lines) keeps one pair per line. In Markdown a single
    newline is only a soft break, so the lines are marked as hard breaks; the words and
    their order are unchanged."""
    lines = content.split("\n")
    if len(lines) < 2 or not all(_FIELD_LINE.match(line) for line in lines):
        return content
    return "\\\n".join(line.rstrip() for line in lines)


def _collect_inline(tokens, idx) -> str:
    if idx < len(tokens) and tokens[idx].type == "inline":
        return tokens[idx].content or ""
    return ""


_TASK_RE = re.compile(r'^\[([ xX])\]\s+(.*)', re.DOTALL)


def _collect_list(tokens, start_idx) -> Tuple[List[ListItemModel], int]:
    """Recursively walk ``*_list_open … *_list_close`` preserving hierarchy.

    Every list item keeps all of its text (multiple paragraphs, code) and its
    nested lists become ``children``; task markers become ``checked``.
    Returns (items, index after the matching close token).
    """
    open_type = tokens[start_idx].type
    close_type = open_type.replace("_open", "_close")
    items: List[ListItemModel] = []
    idx = start_idx + 1
    while idx < len(tokens):
        t = tokens[idx]
        if t.type == close_type and t.level == tokens[start_idx].level:
            return items, idx + 1
        if t.type == "list_item_open":
            item, idx = _collect_list_item(tokens, idx)
            items.append(item)
            continue
        idx += 1
    return items, idx


def _collect_list_item(tokens, start_idx) -> Tuple[ListItemModel, int]:
    level = tokens[start_idx].level
    texts: List[str] = []
    children: List[ListItemModel] = []
    children_ordered = None
    idx = start_idx + 1
    while idx < len(tokens):
        t = tokens[idx]
        if t.type == "list_item_close" and t.level == level:
            idx += 1
            break
        if t.type in ("bullet_list_open", "ordered_list_open"):
            sub, idx = _collect_list(tokens, idx)
            if children and children_ordered != (t.type == "ordered_list_open"):
                # a second, differently-typed sub-list: keep items, mark mixed
                children_ordered = None
            else:
                children_ordered = t.type == "ordered_list_open"
            children.extend(sub)
            continue
        if t.type == "inline":
            texts.append(t.content or "")
        elif t.type in ("fence", "code_block"):
            texts.append((t.content or "").rstrip("\n"))
        idx += 1
    text = "\n\n".join(texts)       # the item's paragraphs; a single newline would be a soft break
    checked = None
    m = _TASK_RE.match(text) or (re.match(r'^\[([ xX])\]$', text))
    if m:
        checked = m.group(1).lower() == "x"
        text = m.group(2) if m.lastindex and m.lastindex >= 2 else ""
    return ListItemModel(text=text, children=children, checked=checked,
                         children_ordered=children_ordered), idx


def _simplify_items(items: List[ListItemModel]) -> list:
    """Plain strings for simple items (v0.3 shape), models when structure matters."""
    if all(not it.children and it.checked is None and it.children_ordered is None for it in items):
        return [it.text for it in items]
    return items


def _collect_list_items(tokens, start_idx):
    """Deprecated flat API kept for compatibility: ([(text, checked)], is_checklist, idx)."""
    items, idx = _collect_list(tokens, start_idx)
    flat = []

    def walk(its):
        for it in its:
            flat.append((it.text, bool(it.checked)))
            walk(it.children)
    walk(items)
    return flat, any(it.checked is not None for it in items), idx


def _collect_table(tokens, start_idx):
    headers, rows = [], []
    idx = start_idx + 1
    in_head = False
    current_row = []
    while idx < len(tokens):
        t = tokens[idx]
        if t.type == "table_close":
            idx += 1
            break
        elif t.type == "thead_open":
            in_head = True
        elif t.type == "thead_close":
            in_head = False
        elif t.type == "tr_open":
            current_row = []
        elif t.type == "tr_close":
            if in_head:
                headers = current_row
            else:
                rows.append(current_row)
        elif t.type in ("th_open", "td_open"):
            idx += 1
            if idx < len(tokens) and tokens[idx].type == "inline":
                current_row.append(tokens[idx].content or "")
            else:
                current_row.append("")
        idx += 1
    return headers, rows, idx


def _collect_blockquote(tokens, start_idx):
    parts = []
    idx = start_idx + 1
    while idx < len(tokens):
        if tokens[idx].type == "blockquote_close":
            idx += 1
            break
        if tokens[idx].type == "inline":
            parts.append(tokens[idx].content or "")
        elif tokens[idx].type in ("fence", "code_block"):
            parts.append((tokens[idx].content or "").rstrip("\n"))
        idx += 1
    return parts, idx


def _parse_definition_list(content: str) -> list:
    """Parse definition list from text like 'term\\n: definition'."""
    items = []
    lines = content.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if i + 1 < len(lines) and lines[i + 1].strip().startswith(': '):
            term = line
            defn = lines[i + 1].strip()[2:]
            items.append(DefinitionItem(term=term, definition=defn))
            i += 2
        else:
            i += 1
    return items
