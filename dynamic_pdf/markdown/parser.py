"""
Markdown → Block tree parser.
Handles: headings, paragraphs, code fences (mermaid/math), bullet lists,
ordered lists, GFM tables, blockquotes, images, horizontal rules,
callout admonitions, task lists (- [ ] / - [x]), definition lists,
footnote references, and YAML front matter.
"""
import re
from markdown_it import MarkdownIt
from ..schema.blocks import (
    HeadingBlock, ParagraphBlock, CodeBlock, BulletListBlock, NumberedListBlock,
    ImageBlock, MathBlock, MermaidBlock, TableBlock, QuoteBlock, DividerBlock,
    CalloutBlock, ChecklistBlock, ChecklistItem, DefinitionListBlock, DefinitionItem,
    FootnoteBlock,
)


def markdown_to_blocks(md_text: str) -> list:
    """Parse a markdown string into a list of typed Block objects."""
    # Extract YAML front matter (---\n...\n---)
    front_matter = {}
    fm_match = re.match(r'^---\s*\n(.*?)\n---\s*\n', md_text, re.DOTALL)
    if fm_match:
        md_text = md_text[fm_match.end():]
        # Simple YAML key: value parsing
        for line in fm_match.group(1).split('\n'):
            if ':' in line:
                k, v = line.split(':', 1)
                front_matter[k.strip()] = v.strip()

    md = MarkdownIt("commonmark", {"html": False}).enable(["table"])
    tokens = md.parse(md_text)
    blocks = []
    footnotes = {}
    idx = 0

    while idx < len(tokens):
        t = tokens[idx]

        # ─── Headings ───
        if t.type == "heading_open":
            level = int(t.tag[1])
            idx += 1
            content = _collect_inline(tokens, idx)
            blocks.append(HeadingBlock(level=level, text=content))
            idx += 1  # heading_close

        # ─── Paragraphs ───
        elif t.type == "paragraph_open":
            idx += 1
            content = _collect_inline(tokens, idx)

            # Image-only paragraph
            if content.startswith("!["):
                img_match = re.match(r'!\[([^\]]*)\]\(([^)]+?)(?:\s+"([^"]*)")?\)', content)
                if img_match:
                    blocks.append(ImageBlock(
                        src=img_match.group(2),
                        caption=img_match.group(3) or img_match.group(1) or None,
                        alt_text=img_match.group(1) or None,
                    ))
                    idx += 2
                    continue

            # Callout admonition (:::variant)
            if content.startswith(":::"):
                parts = content.split("\n", 1)
                variant = parts[0].replace(":::", "").strip() or "info"
                body = parts[1] if len(parts) > 1 else ""
                blocks.append(CalloutBlock(text=body, variant=variant))
                idx += 2
                continue

            # Footnote definition: [^N]: text
            fn_match = re.match(r'^\[\^(\w+)\]:\s*(.+)', content)
            if fn_match:
                blocks.append(FootnoteBlock(marker=fn_match.group(1), text=fn_match.group(2)))
                idx += 2
                continue

            # Definition list: term\n: definition
            if '\n: ' in content or content.startswith(': '):
                items = _parse_definition_list(content)
                if items:
                    blocks.append(DefinitionListBlock(items=items))
                    idx += 2
                    continue

            blocks.append(ParagraphBlock(text=content))
            idx += 1  # paragraph_close

        # ─── Code Fences ───
        elif t.type == "fence":
            lang = (t.info or "").strip() or "text"
            code = (t.content or "").rstrip("\n")
            if lang == "mermaid":
                blocks.append(MermaidBlock(diagram=code))
            elif lang in ("math", "latex"):
                blocks.append(MathBlock(latex=code))
            else:
                blocks.append(CodeBlock(language=lang, code=code))

        # ─── Bullet Lists ───
        elif t.type == "bullet_list_open":
            items, is_checklist, idx = _collect_list_items(tokens, idx)
            if is_checklist:
                blocks.append(ChecklistBlock(items=[
                    ChecklistItem(text=txt, checked=checked)
                    for txt, checked in items
                ]))
            else:
                blocks.append(BulletListBlock(items=[i[0] for i in items]))
            continue

        # ─── Ordered Lists ───
        elif t.type == "ordered_list_open":
            items, _, idx = _collect_list_items(tokens, idx)
            blocks.append(NumberedListBlock(items=[i[0] for i in items]))
            continue

        # ─── Tables ───
        elif t.type == "table_open":
            headers, rows, idx = _collect_table(tokens, idx)
            blocks.append(TableBlock(headers=headers, rows=rows))
            continue

        # ─── Block Quotes ───
        elif t.type == "blockquote_open":
            parts, idx = _collect_blockquote(tokens, idx)
            blocks.append(QuoteBlock(text="\n".join(parts)))
            continue

        # ─── Horizontal Rule ───
        elif t.type == "hr":
            blocks.append(DividerBlock())

        idx += 1

    return blocks


def _collect_inline(tokens, idx) -> str:
    if idx < len(tokens) and tokens[idx].type == "inline":
        return tokens[idx].content or ""
    return ""


def _collect_list_items(tokens, start_idx):
    """Walk tokens from list_open to list_close. Detect checklist items."""
    items = []
    is_checklist = False
    idx = start_idx + 1
    while idx < len(tokens):
        t = tokens[idx]
        if t.type in ("bullet_list_close", "ordered_list_close"):
            idx += 1
            break
        if t.type == "list_item_open":
            idx += 1
            while idx < len(tokens) and tokens[idx].type != "list_item_close":
                if tokens[idx].type == "inline":
                    text = tokens[idx].content or ""
                    # Check for GFM task list
                    check_match = re.match(r'^\[([ xX])\]\s*(.*)', text)
                    if check_match:
                        is_checklist = True
                        checked = check_match.group(1).lower() == 'x'
                        items.append((check_match.group(2), checked))
                    else:
                        items.append((text, False))
                idx += 1
        idx += 1
    return items, is_checklist, idx


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
