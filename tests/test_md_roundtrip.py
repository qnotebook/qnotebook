"""Round-trip property tests for markdown_to_qdoc / qdoc_to_markdown.

Each sample, when rendered to a QTextDocument and serialized back, should
either be unchanged (fixed point) or converge after one normalization pass.
We assert the second-generation output is a fixed point."""

from __future__ import annotations

import pytest

from PyQt6.QtGui import QTextDocument

from qnotebook.md_to_qdoc import markdown_to_qdoc
from qnotebook.qdoc_to_md import qdoc_to_markdown


SAMPLES = [
    pytest.param("# Hello\n", id="h1"),
    pytest.param("## Heading 2\n", id="h2"),
    pytest.param("### Heading 3\n", id="h3"),
    pytest.param("#### Heading 4\n", id="h4"),
    pytest.param("##### Heading 5\n", id="h5"),
    pytest.param("###### Heading 6\n", id="h6"),
    pytest.param("Just a paragraph.\n", id="para"),
    pytest.param("First para.\n\nSecond para.\n", id="two-paras"),
    pytest.param("**bold** text\n", id="bold"),
    pytest.param("_italic_ text\n", id="italic"),
    pytest.param("~~strike~~ text\n", id="strike"),
    pytest.param("`inline code` here\n", id="inline-code"),
    pytest.param("Mixed **bold** and _italic_ and ~~strike~~.\n", id="mixed-inline"),
    pytest.param("- one\n- two\n- three\n", id="bullet-list"),
    pytest.param("1. one\n2. two\n3. three\n", id="ordered-list"),
    pytest.param("- nested\n  - child\n  - sibling\n- back\n", id="nested-list"),
    pytest.param("- [ ] todo\n- [x] done\n- [ ] another\n", id="task-list"),
    pytest.param("See [link](https://example.com) here.\n", id="inline-link"),
    pytest.param("See [[WikiPage]] link.\n", id="wikilink"),
    pytest.param("See [[Foo:Bar]] nested.\n", id="wikilink-nested"),
    pytest.param("See [[Target|alias text]] with alias.\n", id="wikilink-alias"),
    pytest.param("```\ncode block\nline 2\n```\n", id="fence"),
    pytest.param("```python\nx = 1\ny = 2\n```\n", id="fence-lang"),
    pytest.param("> a quote\n> second line\n", id="blockquote"),
    pytest.param("| a | b |\n| --- | --- |\n| 1 | 2 |\n", id="table"),
    pytest.param("---\n", id="hr"),
    pytest.param(
        "# Title\n\nIntro **para**.\n\n## Sub\n\n- a\n- b\n\nEnd.\n",
        id="mixed-doc",
    ),
    pytest.param("This is #tagged and so is #another-tag.\n", id="tags"),
    pytest.param("At start: #todo then later #done.\n", id="tag-mid-line"),
]


def _normalize(md: str) -> str:
    """Run md through the round-trip once; returns the canonical form."""
    doc = QTextDocument()
    markdown_to_qdoc(md, doc)
    return qdoc_to_markdown(doc)


@pytest.mark.parametrize("md", SAMPLES)
def test_roundtrip_is_fixed_point(qapp, md):
    once = _normalize(md)
    twice = _normalize(once)
    assert once == twice, f"Not a fixed point.\nONCE:  {once!r}\nTWICE: {twice!r}"


@pytest.mark.parametrize("md", SAMPLES)
def test_roundtrip_preserves_content_words(qapp, md):
    """Every word in the source (outside syntax) should appear in the output."""
    once = _normalize(md)
    # Heuristic: strip markdown syntax tokens and compare word sets
    import re

    def words(s):
        stripped = re.sub(r"[`*_~#\[\]|>\-]+", " ", s)
        return set(w for w in stripped.split() if w and not w.startswith("http"))

    src_words = words(md)
    out_words = words(once)
    missing = src_words - out_words
    # Allow table alignment tokens, digits for list items
    missing = {w for w in missing if w not in {"---", ":---"}}
    assert not missing, f"Lost words: {missing}"


def test_empty_document(qapp):
    doc = QTextDocument()
    markdown_to_qdoc("", doc)
    assert qdoc_to_markdown(doc).strip() == ""


def test_wikilink_alias_preserved(qapp):
    md = "[[Target|display text]]\n"
    out = _normalize(md)
    assert "[[Target|display text]]" in out


def test_ordered_list_starts_at_one(qapp):
    md = "1. one\n2. two\n3. three\n"
    out = _normalize(md)
    assert "1. one" in out
    assert "2. two" in out
    assert "3. three" in out


def test_task_checkbox_states_preserved(qapp):
    md = "- [ ] todo\n- [x] done\n"
    out = _normalize(md)
    assert "[ ] todo" in out
    assert "[x] done" in out


def test_tag_roundtrip(qapp):
    md = "Before #todo middle and #another-tag end.\n"
    out = _normalize(md)
    assert "#todo" in out
    assert "#another-tag" in out


def test_fenced_python_roundtrip(qapp):
    md = "```python\ndef f(x):\n    return x + 1\n```\n"
    once = _normalize(md)
    twice = _normalize(once)
    assert once == twice
    assert "def f(x):" in once
    assert "```python" in once


def test_fenced_unknown_lang_roundtrip(qapp):
    md = "```zzzzznotalang\nhello world\n```\n"
    once = _normalize(md)
    twice = _normalize(once)
    assert once == twice


def test_fenced_code_content_preserved(qapp):
    md = "```javascript\nconst x = 42;\nconsole.log(x);\n```\n"
    once = _normalize(md)
    assert "const x = 42;" in once
    assert "console.log(x);" in once


def test_tag_in_code_not_styled(qapp):
    # Backtick code content carrying a # shouldn't be wrecked.
    md = "Use `#define FOO 1` in headers.\n"
    out = _normalize(md)
    assert "`#define FOO 1`" in out
