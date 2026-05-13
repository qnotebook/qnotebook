"""Spell-check overlay using pyenchant (optional dependency).

If pyenchant is unavailable, `HAS_ENCHANT = False` and the feature is
skipped cleanly by the UI.
"""

from __future__ import annotations

import re
from typing import Iterable

from PyQt6.QtCore import Qt
from PyQt6.QtGui import (
    QColor,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextDocument,
)


try:
    import enchant  # type: ignore
    HAS_ENCHANT = True
except ImportError:
    enchant = None  # type: ignore
    HAS_ENCHANT = False


WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]*")


class SpellHighlighter(QSyntaxHighlighter):
    """Red wavy underline on misspelled words.

    Uses enchant when available; otherwise a no-op (never flags anything).
    """

    def __init__(self, doc: QTextDocument, lang: str = "en_US") -> None:
        super().__init__(doc)
        self._dict = None
        self._ignored: set[str] = set()
        if HAS_ENCHANT:
            try:
                self._dict = enchant.Dict(lang)  # type: ignore[attr-defined]
            except Exception:
                self._dict = None

        self._fmt = QTextCharFormat()
        self._fmt.setUnderlineColor(QColor("red"))
        self._fmt.setUnderlineStyle(
            QTextCharFormat.UnderlineStyle.WaveUnderline
        )

    def is_active(self) -> bool:
        return self._dict is not None

    def add_to_dictionary(self, word: str) -> None:
        if self._dict is not None:
            try:
                self._dict.add(word)
            except Exception:
                pass
        self.rehighlight()

    def ignore_word(self, word: str) -> None:
        self._ignored.add(word)
        self.rehighlight()

    def suggestions(self, word: str, n: int = 5) -> list[str]:
        if self._dict is None:
            return []
        try:
            return list(self._dict.suggest(word))[:n]
        except Exception:
            return []

    def highlightBlock(self, text: str) -> None:  # noqa: N802
        if self._dict is None:
            return
        for m in WORD_RE.finditer(text):
            word = m.group(0)
            if word in self._ignored:
                continue
            try:
                if not self._dict.check(word):
                    self.setFormat(m.start(), m.end() - m.start(), self._fmt)
            except Exception:
                continue
