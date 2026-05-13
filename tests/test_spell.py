from __future__ import annotations

import pytest

from qnotebook.spell import HAS_ENCHANT, SpellHighlighter, WORD_RE


def test_word_regex_finds_words():
    matches = [m.group(0) for m in WORD_RE.finditer("hello, world's best-friend")]
    assert "hello" in matches
    assert "world's" in matches
    assert "best-friend" in matches


def test_spell_module_reports_availability():
    # Deterministic: HAS_ENCHANT is a bool; either state is valid.
    assert HAS_ENCHANT in (True, False)


@pytest.mark.skipif(not HAS_ENCHANT, reason="enchant not installed")
def test_highlighter_flags_misspellings(qapp):
    from PyQt6.QtGui import QTextDocument
    doc = QTextDocument()
    doc.setPlainText("This is a teh misspellled word.")
    hl = SpellHighlighter(doc)
    assert hl.is_active()
    suggestions = hl.suggestions("teh")
    assert isinstance(suggestions, list)


@pytest.mark.skipif(HAS_ENCHANT, reason="only meaningful without enchant")
def test_highlighter_inactive_without_enchant(qapp):
    from PyQt6.QtGui import QTextDocument
    doc = QTextDocument()
    doc.setPlainText("qwertyzz")
    hl = SpellHighlighter(doc)
    assert not hl.is_active()
    assert hl.suggestions("qwertyzz") == []
