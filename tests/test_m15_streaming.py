"""M15: streaming that streams (F14) — incremental parse, preview, final export()."""
import random

import pytest

from dynamic_pdf import RenderPolicy, ResourceLimits, ResourceLimitError, stream
from dynamic_pdf.markdown.parser import parse_markdown
from dynamic_pdf.markdown.preprocessors import preprocess_markdown
from dynamic_pdf.streaming import MarkdownStream

DOC = """---
title: Streamed report
author: Ada
---
# Streamed report

Intro paragraph with **bold that spans
two lines** and a [link](https://example.com).

- one
- two

- three, after a blank line (same loose list)
  continued

1. first
2. second

| Region | Sales |
| --- | ---: |
| North | 1,200 |
| South | 900 |

```python
def f():

    return 1  # blank line inside the fence
```

$$
E = mc^2

$$

:::warning
A callout

over two paragraphs :::

> quoted
> text

Term
: definition

Footnote ref[^1].

[^1]: First note.
[^2]: Second note.

Setext heading
--------------

    indented code

***

Last paragraph *unterminated
"""


def _whole(text):
    return parse_markdown(preprocess_markdown(text))[1]


def _feed(text, sizes):
    s, i = MarkdownStream(), 0
    want = _whole(text)
    while i < len(text):
        n = next(sizes)
        s.write(text[i:i + n])
        i += n
        assert s.blocks == want[:len(s.blocks)], f"committed blocks diverged at offset {i}"
    return s, want


def test_one_character_at_a_time_matches_whole_parse():
    s, want = _feed(DOC, iter(lambda: 1, None))
    assert s.front_matter == {"title": "Streamed report", "author": "Ada"}
    assert len(s.blocks) > 10                       # it really committed while streaming
    assert s.blocks + s.pending_blocks() == want


@pytest.mark.parametrize("seed", range(5))
def test_random_chunk_boundaries_and_crlf(seed):
    rnd = random.Random(seed)
    text = DOC.replace("\n", "\r\n") if seed % 2 else DOC
    s, want = _feed(text, iter(lambda: rnd.randint(1, 40), None))
    assert s.blocks + s.pending_blocks() == want


def test_unfinished_constructs_are_not_committed():
    s = MarkdownStream()
    s.write("# Title\n\nPara one.\n\n```python\nx = 1\n\nmore code\n")
    assert [b.type for b in s.blocks] == ["heading", "paragraph"]   # open fence stays pending
    assert [b.type for b in s.pending_blocks()] == ["code"]
    s.write("```\n\n| a | b |\n| - |")
    assert [b.type for b in s.blocks] == ["heading", "paragraph", "code"]
    s.write(" - |\n| 1 | 2 |\n\nAfter\n")
    assert [b.type for b in s.blocks][-1] == "table"


def test_open_display_math_and_callout_wait():
    s = MarkdownStream()
    s.write("Intro\n\n$$\na\n\nb\n")
    assert [b.type for b in s.blocks] == []            # the $$ span is not closed
    s.write("$$\n\n:::info\nhello\n\nworld\n\nnext\n")
    assert [b.type for b in s.blocks] == ["paragraph", "math"]
    s.write("\nend :::\n\nTail\n")
    assert [b.type for b in s.blocks][-1] == "callout"


def test_preview_mid_fence_and_final_export(tmp_path):
    out = tmp_path / "out.pdf"
    with stream(str(out), theme="claude", design="auto") as s:
        s.write("---\ntitle: Live\n---\n# Live\n\nSome text.\n\n```python\nprint('open fence')\n")
        pdf = s.preview()
        assert pdf.startswith(b"%PDF")
        assert not out.exists()
        s.write("```\n\nDone.\n")
    assert out.read_bytes().startswith(b"%PDF")
    assert s.result.pdf_path == str(out) and s.result.profile is not None    # designed export()
    assert s.builder._meta.title == "Live"
    assert s.builder._blocks == _whole("# Live\n\nSome text.\n\n```python\nprint('open fence')\n```\n\nDone.\n")


def test_legacy_call_still_works(tmp_path):
    out = tmp_path / "legacy.pdf"
    with stream(str(out), theme="claude") as s:
        s.write("# Hello")
        s.write("\n\nWorld")
    assert out.read_bytes().startswith(b"%PDF")


def test_policy_limits_and_no_output_on_error(tmp_path):
    out = tmp_path / "x.pdf"
    policy = RenderPolicy(limits=ResourceLimits(max_input_chars=10))
    with pytest.raises(ResourceLimitError):
        with stream(str(out), policy=policy) as s:
            s.write("# 12345678901")
    assert not out.exists()
    with pytest.raises(RuntimeError):
        with stream(str(out)) as s:
            s.write("# Hi\n")
            raise RuntimeError("caller failed")
    assert not out.exists()


def test_docx_and_classic(tmp_path):
    out = tmp_path / "s.docx"
    with stream(str(out), design=None) as s:
        s.write("# Word\n\ntext\n")
    assert s.result.docx_path == str(out) and out.stat().st_size > 0
