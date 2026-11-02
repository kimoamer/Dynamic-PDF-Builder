"""M1: canonical semantic document — lossless, typed, renderer-independent."""
import re
import pytest
from dynamic_pdf import DocumentBuilder
from dynamic_pdf.core import normalize, parse_inline, runs_to_plain, block_text
from dynamic_pdf.core.inline import plain_text
from conftest import fixture_text, all_fixtures


def _source_words(md: str):
    """Words of the Markdown source with markup stripped (front matter removed)."""
    body = re.sub(r"^---\n.*?\n---\n", "", md, flags=re.S)
    body = re.sub(r"```\w*", " ", body)
    body = re.sub(r"\$\$", " ", body)
    body = re.sub(r"\]\([^)]*\)", "]", body)          # link targets are not visible words
    body = re.sub(r"\[\^(\w+)\]:?", r" \1 ", body)
    body = re.sub(r"(?m)^\s*\d+\.\s", " ", body)        # list markers are numbering, not text
    body = re.sub(r":::\w*", " ", body)                 # callout fences
    words = re.findall(r"[\w٠-٩][\w٠-٩.,%$'’-]*", body)
    return [w.strip(".,") for w in words if w.strip(".,")]


@pytest.mark.parametrize("name", all_fixtures())
def test_markdown_to_ast_is_lossless(name):
    md = fixture_text(name)
    sem = DocumentBuilder.from_markdown(md).semantic()
    ast_text = " ".join(plain_text(re.sub(r"\[\^(\w+)\]", r" \1 ", t)) for t in sem.all_text())
    ast_text += " " + " ".join(f"{b.variant}" for b in sem.blocks if b.type == "callout")
    ast_words = set(w.strip(".,") for w in re.findall(r"[\w٠-٩][\w٠-٩.,%$'’-]*", ast_text))
    missing = [w for w in _source_words(md) if w not in ast_words]
    assert not missing, f"words lost in AST: {missing[:10]}"


def test_inline_runs_keep_semantics():
    runs = parse_inline("See **bold** and [docs](https://x.org/a) `code` x^2^ [^3]")
    by_text = {r.text: r for r in runs}
    assert by_text["bold"].bold
    assert by_text["docs"].link == "https://x.org/a"
    assert by_text["code"].code
    assert by_text["2"].superscript
    assert by_text["3"].footnote_ref == "3"
    assert runs_to_plain(runs) == "See bold and docs code x2 3"


def test_unsafe_links_are_not_links_but_text_survives():
    runs = parse_inline("[click](javascript:alert(1))")
    assert all(r.link is None for r in runs)
    assert "click" in runs_to_plain(runs)


def test_normalize_does_not_mutate_and_assigns_unique_ids():
    b = DocumentBuilder().heading("Intro").heading("Intro").heading("مقدمة").paragraph("x")
    doc = b.build()
    sem = normalize(doc)
    assert [h.id for h in sem.outline] == ["intro", "intro-2", "section-3"]
    assert all(blk.id is None for blk in doc.blocks if blk.type == "heading")


def test_loose_inputs_are_coerced_to_typed_models():
    b = (DocumentBuilder().bullet_list(["a", {"text": "b", "children": ["c"]}])
         .two_column(left=["left"], right=[{"type": "paragraph", "text": "right"}]))
    sem = b.semantic()
    lst, cols = sem.blocks
    assert lst.items[1].children[0].text == "c"
    assert cols.left[0].type == "paragraph" and cols.right[0].text == "right"


def test_stats_direction_and_provenance():
    sem = DocumentBuilder.from_markdown(fixture_text("arabic_report.md")).semantic()
    assert sem.direction == "rtl" and sem.language == "ar"
    assert sem.provenance.source_kind == "markdown" and len(sem.provenance.source_sha256) == 64
    fin = DocumentBuilder.from_markdown(fixture_text("financial.md")).semantic()
    assert fin.stats.tables == 1 and fin.stats.table_rows == 40 and fin.stats.numeric_ratio > 0.9
    assert fin.direction == "ltr"


def test_block_text_reaches_nested_content():
    b = DocumentBuilder().sidebar(main_content=["main"], sidebar_content=["side"])
    assert set(block_text(b.semantic().blocks[0])) == {"main", "side"}


def test_v03_calls_unchanged_without_design():
    b = DocumentBuilder(theme="academic").heading("A").paragraph("B")
    assert b.design_explain()["profile"] is None
    b.render()
    assert b.last_render.theme.name == "academic"
    assert b.last_design is None
