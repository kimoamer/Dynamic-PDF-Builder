"""P1-02 / P1-06: nested lists, numbering, task lists and content preservation."""
from dynamic_pdf import DocumentBuilder
from dynamic_pdf.markdown.parser import markdown_to_blocks, parse_markdown
from conftest import pdf_text


def test_parent_child_sibling_preserved():
    blocks = markdown_to_blocks("- Parent\n  - Child\n- Sibling\n")
    assert len(blocks) == 1
    lst = blocks[0]
    assert lst.type == "bullet_list"
    parent, sibling = lst.items
    assert parent.text == "Parent"
    assert [c.text for c in parent.children] == ["Child"]
    assert sibling.text == "Sibling"


def test_nested_survives_to_pdf():
    text = pdf_text(DocumentBuilder.from_markdown("- Parent\n  - Child\n- Sibling\n").render())
    for word in ("Parent", "Child", "Sibling"):
        assert word in text


def test_deep_and_mixed_nesting_with_numbering():
    md = "3. Three\n   - sub a\n   - sub b\n     1. deep\n4. Four\n"
    (lst,) = markdown_to_blocks(md)
    assert lst.type == "numbered_list" and lst.start == 3
    three, four = lst.items
    assert [c.text for c in three.children] == ["sub a", "sub b"]
    assert three.children_ordered is False
    assert three.children[1].children[0].text == "deep"
    assert three.children[1].children_ordered is True
    assert four.text == "Four"
    text = pdf_text(DocumentBuilder.from_markdown(md).render())
    for w in ("Three", "sub a", "sub b", "deep", "Four"):
        assert w in text


def test_flat_task_list_is_checklist_and_nested_tasks_keep_state():
    (flat,) = markdown_to_blocks("- [x] done\n- [ ] todo\n")
    assert flat.type == "checklist"
    assert [(i.text, i.checked) for i in flat.items] == [("done", True), ("todo", False)]
    (nested,) = markdown_to_blocks("- [ ] parent\n  - [x] child\n- plain\n")
    assert nested.type == "bullet_list"
    p, plain = nested.items
    assert p.checked is False and p.children[0].checked is True
    assert plain.checked is None


def test_multi_paragraph_list_item_keeps_all_text():
    (lst,) = markdown_to_blocks("- first para\n\n  second para\n- next\n")
    first = lst.items[0] if isinstance(lst.items[0], str) else lst.items[0].text
    assert "first para" in first and "second para" in first


def test_rtl_nested_list_keeps_children():
    md = "- عنصر رئيسي\n  - عنصر فرعي\n- عنصر آخر\n"
    (lst,) = markdown_to_blocks(md)
    assert lst.items[0].children[0].text == "عنصر فرعي"
    DocumentBuilder.from_markdown(md).render()   # renders without error


def test_plain_lists_keep_v03_shape():
    (lst,) = markdown_to_blocks("- a\n- b\n")
    assert lst.items == ["a", "b"]


def test_content_preservation_cases():
    md = (
        "![alt](img.png) followed by text\n\n"
        "[^1]: Single\n\n"
        "    indented code\n\n"
        ":::warning\nfirst\n\nsecond\n:::\n"
    )
    blocks = markdown_to_blocks(md)
    types = [b.type for b in blocks]
    assert types == ["paragraph", "footnote", "code", "callout"]
    assert "followed by text" in blocks[0].text
    assert blocks[1].marker == "1" and blocks[1].text == "Single"
    assert blocks[2].code == "indented code"
    assert blocks[3].variant == "warning" and blocks[3].text == "first\n\nsecond"


def test_front_matter_populates_meta():
    md = '---\ntitle: "Annual: Review"\nauthor: Ops\nkeywords: [a, b]\nlang: ar\n---\n# Hi\n'
    fm, blocks = parse_markdown(md)
    assert fm["title"] == "Annual: Review"
    b = DocumentBuilder.from_markdown(md)
    doc = b.build()
    assert doc.meta.title == "Annual: Review"
    assert doc.meta.author == "Ops"
    assert doc.meta.keywords == ["a", "b"]
    assert doc.meta.language == "ar"
    assert blocks[0].text == "Hi"


def test_inline_markup_is_escaped_not_injected():
    from dynamic_pdf.layout.factory import _md_inline
    out = _md_inline('a < b & <img src="/etc/passwd"/> [x](javascript:alert) **ok**')
    assert "<img" not in out and "&lt;img" in out
    assert "javascript" not in out
    assert "<b>ok</b>" in out
    text = pdf_text(DocumentBuilder().paragraph("1 < 2 & 3 > 2").render())
    assert "1 < 2 & 3 > 2" in text
